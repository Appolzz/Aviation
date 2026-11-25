#!/usr/bin/env python3
"""
LootRadar — 24-Hour Rare Flight & Livery Tracker
Data pipeline: fetches the next 24 hours of arrivals, assigns Fortnite-style rarity,
enriches with plane-alert-db livery data, fetches Planespotters photos,
sends ntfy.sh push notifications, and writes data/arrivals.json.

Requirements: requests>=2.31.0 (stdlib only beyond that)
"""

import csv
import io
import json
import logging
import os
import re
import sys
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("lootrada")

# ---------------------------------------------------------------------------
# Paths (relative to repo root, script is in scripts/)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
CONFIG_DIR = REPO_ROOT / "config"
DATA_DIR = REPO_ROOT / "data"

AIRPORTS_JSON = CONFIG_DIR / "airports.json"
RARITY_JSON = CONFIG_DIR / "rarity_rules.json"
ARRIVALS_JSON = DATA_DIR / "arrivals.json"
SEEN_JSON = DATA_DIR / "seen_flights.json"
PHOTO_CACHE_JSON = DATA_DIR / "photo_cache.json"
USAGE_LEDGER_JSON = DATA_DIR / "api_usage_ledger.json"

# ---------------------------------------------------------------------------
# External constants
# ---------------------------------------------------------------------------
PLANE_ALERT_DB_URL = (
    "https://raw.githubusercontent.com/sdr-enthusiasts/plane-alert-db/main/"
    "plane-alert-db.csv"
)
FLIGHTAWARE_BASE = "https://aeroapi.flightaware.com/aeroapi"
RESULT_SET_COST_USD = 0.005
HARD_MONTHLY_CAP_USD = 4.25
PAGE_PACING_SECONDS = 7.0
PLANESPOTTERS_REG = "https://api.planespotters.net/pub/photos/reg/{reg}"
PLANESPOTTERS_HEX = "https://api.planespotters.net/pub/photos/hex/{hex}"
NTFY_BASE = "https://ntfy.sh/{topic}"

RARITY_ORDER = ["Common", "Uncommon", "Rare", "Epic", "Legendary", "Mythic"]
NOTIFY_RARITIES = {"Rare", "Epic", "Legendary", "Mythic"}

RARITY_COLORS = {
    "Common": "#64748b",
    "Uncommon": "#22c55e",
    "Rare": "#3b82f6",
    "Epic": "#a855f7",
    "Legendary": "#f59e0b",
    "Mythic": "#ef4444",
}

RARITY_NTFY_PRIORITY = {
    "Rare": "default",
    "Epic": "default",
    "Legendary": "high",
    "Mythic": "high",
}

RARITY_NTFY_TAGS = {
    "Rare": "airplane,star",
    "Epic": "airplane,star,sparkles",
    "Legendary": "airplane,crown,rotating_light",
    "Mythic": "airplane,crown,rotating_light,skull",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_json(path: Path, default=None):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to load %s: %s", path, exc)
    return default if default is not None else {}


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_timezone(iata: str, tz_overrides: dict) -> ZoneInfo:
    """Return ZoneInfo for an IATA code, falling back to UTC."""
    tz_name = tz_overrides.get(iata.upper(), "UTC")
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        log.warning("Unknown timezone %s for %s, using UTC", tz_name, iata)
        return ZoneInfo("UTC")


def airport_icao(iata: str, config: dict) -> str:
    """Resolve configured IATA codes to FlightAware ICAO identifiers."""
    mapping = config.get("iata_to_icao", {})
    code = mapping.get(iata.upper()) or ("K" + iata.upper() if len(iata) == 3 else iata.upper())
    return code.upper()


def account_usage_cost(payload) -> float | None:
    """Find the current period's reported cost in AeroAPI's usage response."""
    names = {"total_cost", "total_cost_usd", "cost", "cost_usd", "totalcost"}
    found = []
    def walk(value, depth=0):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.lower().replace("-", "_") in names:
                    try:
                        found.append((depth, float(str(child).replace("$", "").replace(",", "").strip())))
                    except (TypeError, ValueError):
                        walk(child, depth + 1)
                else:
                    walk(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                walk(child, depth + 1)
    walk(payload)
    if not found:
        return None
    shallowest = min(depth for depth, _ in found)
    # Prefer the highest-level aggregate; if the API returns only grouped
    # records, sum those peers rather than undercounting the account total.
    return sum(value for depth, value in found if depth == shallowest)


def current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def budget_guard(session: requests.Session, headers: dict, ledger: dict) -> tuple[float, str]:
    """Fail closed unless the free account usage endpoint returns a usable cost."""
    month = current_month()
    entry = ledger.get(month, {})
    ledger_cost = float(entry.get("estimated_cost_usd", 0) or 0)
    start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    params = {
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "all_keys": "true",
    }
    response = session.get(f"{FLIGHTAWARE_BASE}/account/usage", headers=headers, params=params, timeout=30)
    response.raise_for_status()
    live_cost = account_usage_cost(response.json())
    if live_cost is None:
        raise RuntimeError("Could not parse GET /account/usage cost; refusing paid requests for safety")
    cost = max(live_cost, ledger_cost)
    return cost, month


def record_usage(ledger: dict, month: str, page_count: int) -> None:
    entry = ledger.setdefault(month, {"result_sets_used": 0, "estimated_cost_usd": 0.0})
    entry["result_sets_used"] = int(entry.get("result_sets_used", 0)) + page_count
    entry["estimated_cost_usd"] = round(float(entry.get("estimated_cost_usd", 0)) + page_count * RESULT_SET_COST_USD, 4)
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_json(USAGE_LEDGER_JSON, ledger)


# ---------------------------------------------------------------------------
# ICAO type normalization
# ---------------------------------------------------------------------------

def build_normalization_map(rarity_config: dict) -> list:
    """Build ordered list of (keyword, icao_type) from config."""
    keywords = rarity_config.get("icao_type_normalization", {}).get("keywords", [])
    return [(kw.lower(), code) for kw, code in keywords]


def normalize_icao_type(raw_model: str, norm_map: list) -> str | None:
    """Map a raw aircraft model string to a standard ICAO type code."""
    if not raw_model:
        return None
    lowered = raw_model.lower()
    for keyword, code in norm_map:
        if keyword in lowered:
            return code
    # Fallback: try to extract 4-char ICAO code-like token (e.g. B738)
    m = re.search(r"\b([A-Z][A-Z0-9]{2,4})\b", raw_model)
    if m:
        return m.group(1).upper()
    return None


# ---------------------------------------------------------------------------
# Plane-alert-db enrichment
# ---------------------------------------------------------------------------

def download_plane_alert_db(session: requests.Session) -> tuple[dict, dict]:
    """
    Download and parse plane-alert-db.csv.
    Returns (reg_lookup, hex_lookup) dicts mapping to metadata dicts.
    """
    log.info("Downloading plane-alert-db.csv …")
    try:
        resp = session.get(PLANE_ALERT_DB_URL, timeout=30)
        resp.raise_for_status()
        content = resp.text
    except Exception as exc:
        log.error("Failed to download plane-alert-db: %s", exc)
        return {}, {}

    reg_lookup: dict = {}
    hex_lookup: dict = {}

    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        # Normalize keys by stripping leading $/#
        entry = {
            k.lstrip("$#").strip(): v.strip()
            for k, v in row.items()
            if k is not None
        }

        icao_hex = entry.get("ICAO", "").upper().replace(" ", "")
        reg_raw = entry.get("Registration", "").upper()
        reg_norm = re.sub(r"[\s\-]", "", reg_raw)

        tags = [t for t in [entry.get("Tag 1", ""), entry.get("Tag 2", ""), entry.get("Tag 3", "")] if t]
        payload = {
            "operator": entry.get("Operator", ""),
            "icao_type": entry.get("ICAO Type", "") or entry.get("Type", ""),
            "category": entry.get("Category", ""),
            "tags": tags,
            "link": entry.get("#Link", ""),
        }

        if icao_hex:
            hex_lookup[icao_hex] = payload
        if reg_norm:
            reg_lookup[reg_norm] = payload

    log.info("plane-alert-db loaded: %d reg entries, %d hex entries", len(reg_lookup), len(hex_lookup))
    return reg_lookup, hex_lookup


def lookup_plane_alert(
    reg: str | None, modes: str | None, reg_lookup: dict, hex_lookup: dict
) -> dict | None:
    """Return plane-alert-db entry for a registration or ModeS hex."""
    if reg:
        key = re.sub(r"[\s\-]", "", reg.upper())
        if key in reg_lookup:
            return reg_lookup[key]
    if modes:
        key = modes.upper().replace(" ", "")
        if key in hex_lookup:
            return hex_lookup[key]
    return None


# ---------------------------------------------------------------------------
# Rarity classification
# ---------------------------------------------------------------------------

def classify_rarity(
    icao_type: str | None,
    plane_alert_entry: dict | None,
    airport: str,
    rarity_config: dict,
    airline: dict | None = None,
) -> tuple[str, str]:
    """
    Return (rarity_tier, rarity_reason) for a flight.
    Checks tiers top-down: Mythic → Legendary → Epic → Rare → Uncommon → Common.
    """
    profiles = rarity_config.get("profiles", {})
    airport_upper = airport.upper()
    profile = profiles.get(airport_upper, profiles.get("DEFAULT", {}))

    pa_category = (plane_alert_entry or {}).get("category", "").lower()
    pa_tags = [(t or "").lower() for t in (plane_alert_entry or {}).get("tags", [])]
    icao_up = (icao_type or "").upper()
    airline = airline or {}
    airline_code = (airline.get("iata") or "").strip().upper()
    airline_icao = (airline.get("icao") or "").strip().upper()
    airline_name = re.sub(r"[^A-Z0-9]+", " ", (airline.get("name") or "").upper()).strip()

    allowed_airline_codes = {"UA", "UAL", "DL", "DAL", "AA", "AAL", "F9", "FFT", "AS", "ASA", "WN", "SWA"}
    allowed_airline_names = {
        "UNITED", "UNITED AIRLINES", "DELTA", "DELTA AIR LINES", "AMERICAN", "AMERICAN AIRLINES",
        "FRONTIER", "FRONTIER AIRLINES", "ALASKA", "ALASKA AIRLINES", "SOUTHWEST", "SOUTHWEST AIRLINES",
    }
    is_copa = airline_code == "CM" or airline_icao == "CMP" or "COPA" in airline_name
    is_listed_airline = (
        airline_code in allowed_airline_codes or airline_icao in allowed_airline_codes
        or airline_name in allowed_airline_names
    )

    def apply_airline_rule(rarity: str, reason: str) -> tuple[str, str]:
        # Copa is explicitly a Rare airline, regardless of the common narrowbody types it flies.
        if is_copa:
            return "Rare", "Copa Airlines"
        # Other carriers receive an Uncommon floor; aircraft already classified higher stay higher.
        if (airline_name or airline_code or airline_icao) and not is_listed_airline and rarity == "Common":
            return "Uncommon", f"Other airline — {airline.get('name') or airline_code or airline_icao}"
        return rarity, reason

    tier_names = ["mythic", "legendary", "epic", "rare", "uncommon", "common"]

    for tier_lower in tier_names:
        tier_data = profile.get(tier_lower, {})
        tier_title = tier_lower.capitalize()
        reason = tier_data.get("reason_template", tier_title)

        # 1. ICAO type list match
        if icao_up and icao_up in [t.upper() for t in tier_data.get("icao_types", [])]:
            return apply_airline_rule(tier_title, reason)

        # 2. plane-alert-db category match (Mythic/Epic tiers)
        pa_cats = [c.lower() for c in tier_data.get("plane_alert_categories", [])]
        if pa_cats and pa_category:
            if any(c in pa_category for c in pa_cats):
                entry_note = (plane_alert_entry or {}).get("operator", "") or tier_title
                return apply_airline_rule(tier_title, f"{reason} — {entry_note}".strip(" —"))

        # 3. plane-alert-db any match for epic tier (special livery)
        if tier_data.get("plane_alert_match") and plane_alert_entry is not None:
            tags_str = ", ".join(plane_alert_entry.get("tags", []))
            operator = plane_alert_entry.get("operator", "")
            livery_note = tags_str or operator or "Special Livery"
            return apply_airline_rule(tier_title, f"{reason} — {livery_note}".strip(" —"))

    return apply_airline_rule("Common", profile.get("common", {}).get("reason_template", "Standard Traffic"))


# ---------------------------------------------------------------------------
# FlightAware AeroAPI fetching
# ---------------------------------------------------------------------------

def fetch_arrivals_for_airport(
    session: requests.Session,
    iata: str,
    icao: str,
    window_start_utc: datetime,
    window_end_utc: datetime,
    headers: dict,
    ledger: dict,
    month: str,
    month_spend: float,
    run_meter: dict,
) -> list[dict]:
    """Fetch every scheduled arrival in the next 24 hours, one result set per request."""
    params = {
        "start": window_start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": window_end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        # One result set per request keeps the Personal-tier rate limit
        # enforceable. Continue pagination until exhausted or the monthly cap.
        "max_pages": 1,
    }
    url = f"{FLIGHTAWARE_BASE}/airports/{icao}/flights/scheduled_arrivals"
    next_url = None
    next_params = params
    arrivals = []
    airport_pages = 0
    while True:
        ledger_month_cost = float((ledger.get(month, {}) or {}).get("estimated_cost_usd", 0) or 0)
        accounted_month_spend = max(month_spend, ledger_month_cost)
        if accounted_month_spend + RESULT_SET_COST_USD > HARD_MONTHLY_CAP_USD:
            log.warning("Monthly safety cap ($4.25) reached — stopping additional API pages")
            run_meter["incomplete"] = True
            break
        last_request = run_meter.get("last_request_at")
        if last_request is not None:
            time.sleep(max(0.0, PAGE_PACING_SECONDS - (time.monotonic() - last_request)))
        request_started = time.monotonic()
        response = session.get(next_url or url, headers=headers, params=next_params if next_url is None else None, timeout=30)
        run_meter["last_request_at"] = request_started
        if response.status_code == 429:
            log.warning("FlightAware rate limit response; stopping this airport without retry")
            run_meter["incomplete"] = True
            break
        response.raise_for_status()
        payload = response.json()
        items = payload.get("scheduled_arrivals", [])
        arrivals.extend(items)

        # AeroAPI returns num_pages for the result sets actually delivered.
        pages = max(1, int(payload.get("num_pages", 1) or 1))
        airport_pages += pages
        record_usage(ledger, month, pages)
        month_spend += pages * RESULT_SET_COST_USD
        log.info("%s result set %d: %d arrivals", iata, airport_pages, len(items))

        next_ref = (payload.get("links") or {}).get("next")
        if not next_ref:
            break
        # AeroAPI's links.next is commonly root-relative (for example,
        # /airports/KDCA/...?cursor=...), while the API itself lives below
        # /aeroapi. A plain urljoin(url, next_ref) drops that API prefix and
        # sends the next request to a non-existent route (HTTP 404).
        next_parts = urlsplit(next_ref)
        if next_parts.scheme or next_parts.netloc:
            api_parts = urlsplit(FLIGHTAWARE_BASE)
            if next_parts.netloc.lower() != api_parts.netloc.lower():
                raise ValueError("FlightAware pagination link points outside the AeroAPI host")
            next_path = next_parts.path
            if not next_path.startswith(api_parts.path.rstrip("/") + "/"):
                next_path = api_parts.path.rstrip("/") + "/" + next_path.lstrip("/")
            next_url = urlunsplit((api_parts.scheme, api_parts.netloc, next_path, next_parts.query, ""))
        elif next_parts.path.startswith("/"):
            next_url = urlunsplit((
                urlsplit(FLIGHTAWARE_BASE).scheme,
                urlsplit(FLIGHTAWARE_BASE).netloc,
                urlsplit(FLIGHTAWARE_BASE).path.rstrip("/") + "/" + next_parts.path.lstrip("/"),
                next_parts.query,
                "",
            ))
        else:
            next_url = urljoin(url, next_ref)
        parts = urlsplit(next_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["max_pages"] = "1"
        next_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    return arrivals


def daytime_intervals(
    window_start_utc: datetime,
    window_end_utc: datetime,
    tz: ZoneInfo,
) -> list[tuple[datetime, datetime]]:
    """Return portions of the rolling window between 06:00 and 22:00 local."""
    intervals = []
    day = window_start_utc.astimezone(tz).date()
    final_day = window_end_utc.astimezone(tz).date()
    while day <= final_day:
        day_start = datetime.combine(day, datetime_time(6), tzinfo=tz).astimezone(timezone.utc)
        day_end = datetime.combine(day, datetime_time(22), tzinfo=tz).astimezone(timezone.utc)
        start = max(window_start_utc, day_start)
        end = min(window_end_utc, day_end)
        if start < end:
            intervals.append((start, end))
        day += timedelta(days=1)
    return intervals


def local_iso(value: str | None, tz: ZoneInfo) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(tz).isoformat()
    except ValueError:
        return value


def parse_flight(raw: dict, airport: str, tz: ZoneInfo) -> dict:
    """Extract normalized fields from a FlightAware AeroAPI scheduled arrival."""
    num = (raw.get("ident_iata") or raw.get("ident") or "").strip()
    operator = raw.get("operator") or ""
    origin = raw.get("origin") or {}
    arr_utc = raw.get("estimated_in") or raw.get("scheduled_in")
    scheduled_utc = raw.get("scheduled_in")
    arr_local = local_iso(arr_utc, tz)
    sched_local = local_iso(scheduled_utc, tz)
    reg = (raw.get("registration") or "").strip().upper() or None
    modes = (raw.get("hex") or raw.get("mode_s") or "").strip().upper() or None
    model = (raw.get("aircraft_type") or "").strip().upper()
    target_date = (arr_local or arr_utc or "")[:10]
    reg_part = re.sub(r"[\s\-]", "", reg) if reg else "NOREG"
    flight_id = f"{target_date}_{airport.upper()}_{num}_{reg_part}"

    return {
        "id": flight_id,
        "airport": airport.upper(),
        "flight_number": num,
        "airline": {
            "name": operator,
            "iata": raw.get("operator_iata") or "",
            "icao": raw.get("operator_icao") or "",
        },
        "origin": {
            "iata": origin.get("code_iata") or origin.get("code_icao") or "",
            "icao": origin.get("code_icao") or "",
            "name": origin.get("name") or "",
            "city": origin.get("city") or "",
        },
        "arrival": {
            "scheduled_local": sched_local,
            "scheduled_utc": scheduled_utc,
            "revised_local": arr_local if arr_local != sched_local else None,
            "terminal": raw.get("terminal_destination"),
            "gate": raw.get("gate_destination"),
        },
        "aircraft": {
            "reg": reg,
            "modeS": modes,
            "model": model,
            "icao_type": model or None,
        },
        "rarity": "Common",
        "rarity_reason": "",
        "rarity_color": RARITY_COLORS["Common"],
        "livery_or_note": None,
        "plane_alert_match": False,
        "plane_alert_category": None,
        "plane_alert_tags": [],
        "photo": {"url": None, "thumbnail": None, "link": None, "photographer": None},
        "status": raw.get("status") or "Scheduled",
        "fr24_url": f"https://www.flightradar24.com/{num.replace(' ', '')}",
    }


# ---------------------------------------------------------------------------
# Planespotters photo lookup
# ---------------------------------------------------------------------------

def fetch_photo(
    session: requests.Session,
    reg: str | None,
    modes: str | None,
    photo_cache: dict,
) -> dict:
    """Return photo dict from cache or Planespotters API."""
    cache_key = reg or modes
    if cache_key and cache_key in photo_cache:
        cached = photo_cache[cache_key]
        # Return only the photo fields (not cached_at)
        return {k: cached.get(k) for k in ["url", "thumbnail", "link", "photographer"]}

    empty = {"url": None, "thumbnail": None, "link": None, "photographer": None}

    urls_to_try = []
    if reg:
        urls_to_try.append(PLANESPOTTERS_REG.format(reg=reg.replace("-", "")))
    if modes:
        urls_to_try.append(PLANESPOTTERS_HEX.format(hex=modes.lower()))

    for url in urls_to_try:
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                photos = data.get("photos", [])
                if photos:
                    p = photos[0]
                    thumb = p.get("thumbnail_large", {})
                    if not thumb:
                        thumb = p.get("thumbnail", {})
                    result = {
                        "url": thumb.get("src"),
                        "thumbnail": thumb.get("src"),
                        "link": p.get("link"),
                        "photographer": p.get("photographer"),
                    }
                    if cache_key:
                        photo_cache[cache_key] = {**result, "cached_at": datetime.now(timezone.utc).isoformat()}
                    return result
        except Exception as exc:
            log.debug("Photo lookup failed for %s: %s", url, exc)
        time.sleep(0.3)

    return empty


# ---------------------------------------------------------------------------
# ntfy.sh push notifications
# ---------------------------------------------------------------------------

def send_ntfy(
    session: requests.Session,
    ntfy_topic: str,
    flight: dict,
) -> bool:
    """Send a push notification via ntfy.sh. Returns True on success."""
    if not ntfy_topic:
        return False

    rarity = flight["rarity"]
    airline_name = flight["airline"]["name"] or "Unknown Airline"
    operator_iata = flight["airline"].get("iata") or airline_name
    fn = flight["flight_number"]
    airport = flight["airport"]
    icao_type = flight["aircraft"]["icao_type"] or flight["aircraft"]["model"] or "?"
    reg = flight["aircraft"]["reg"] or "Reg TBD"
    rarity_reason = flight["rarity_reason"] or rarity
    origin_iata = flight["origin"]["iata"] or "?"
    origin_city = flight["origin"].get("city") or flight["origin"]["name"] or origin_iata

    arr_local = flight["arrival"]["revised_local"] or flight["arrival"]["scheduled_local"] or "?"
    arr_time_str = arr_local[11:16] if len(arr_local) > 10 else arr_local

    title = f"[{rarity.upper()}] {operator_iata} {fn} -> {airport} ({icao_type})"
    body = (
        f"{icao_type} ({reg}) • {rarity_reason} • "
        f"From: {origin_iata} ({origin_city}) • "
        f"Scheduled arrival at {arr_time_str} local time"
    )

    headers = {
        "Title": title,
        "Priority": RARITY_NTFY_PRIORITY.get(rarity, "default"),
        "Tags": RARITY_NTFY_TAGS.get(rarity, "airplane"),
        "Click": flight["fr24_url"],
    }

    photo_url = flight["photo"].get("thumbnail") or flight["photo"].get("url")
    if photo_url:
        headers["Attach"] = photo_url

    ntfy_url = NTFY_BASE.format(topic=ntfy_topic)
    try:
        resp = session.post(ntfy_url, data=body.encode("utf-8"), headers=headers, timeout=15)
        resp.raise_for_status()
        log.info("ntfy sent: %s", title)
        return True
    except Exception as exc:
        log.error("ntfy failed for %s: %s", fn, exc)
        return False


# ---------------------------------------------------------------------------
# Deduplication helpers
# ---------------------------------------------------------------------------

def prune_seen(seen: dict, days: int = 7) -> dict:
    """Remove entries older than `days` days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    pruned = {}
    for k, v in seen.items():
        if k.startswith("_"):
            pruned[k] = v
            continue
        try:
            ts = datetime.fromisoformat(v)
            if ts >= cutoff:
                pruned[k] = v
        except (ValueError, TypeError):
            # Keep entries we can't parse
            pruned[k] = v
    removed = len(seen) - len(pruned)
    if removed:
        log.info("Pruned %d old seen_flights entries", removed)
    return pruned


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    api_key = os.environ.get("FLIGHTAWARE_API_KEY", "").strip()
    ntfy_topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not api_key:
        log.error("Missing FLIGHTAWARE_API_KEY GitHub Actions secret.")
        sys.exit(1)

    airports_config = load_json(AIRPORTS_JSON, {"active": ["DCA", "IAD"], "timezone_overrides": {}, "presets": []})
    rarity_config = load_json(RARITY_JSON, {"profiles": {}, "icao_type_normalization": {"keywords": []}})
    active_airports = [str(a).upper() for a in airports_config.get("active", ["DCA", "IAD"])[:3]]
    tz_overrides = airports_config.get("timezone_overrides", {})
    if not active_airports:
        log.error("No active airports configured.")
        sys.exit(1)

    ledger = load_json(USAGE_LEDGER_JSON, {})
    session = requests.Session()
    # Keep credentials out of unrelated photo, livery-database, and ntfy requests.
    session.headers.update({"User-Agent": "LootRadar/1.0", "Accept": "application/json"})

    # This no-cost usage read is first; fail closed if it errors or cannot be parsed.
    try:
        month_spend, month = budget_guard(session, {"x-apikey": api_key, "Accept": "application/json"}, ledger)
    except Exception as exc:
        log.error("Usage preflight failed; refusing paid API calls: %s", exc)
        sys.exit(1)
    if month_spend >= HARD_MONTHLY_CAP_USD:
        log.warning("Monthly safety cap ($4.25) reached — skipping API fetch to guarantee $0 billing")
        sys.exit(0)

    seen_flights = load_json(SEEN_JSON, {})
    photo_cache = load_json(PHOTO_CACHE_JSON, {})
    norm_map = build_normalization_map(rarity_config)
    reg_lookup, hex_lookup = download_plane_alert_db(session)
    all_flights = []
    # Use the same rolling 24-hour UTC outlook for all airports, but only query
    # daytime periods (06:00–22:00 in each airport's local timezone).
    window_start_utc = datetime.now(timezone.utc).replace(microsecond=0)
    window_end_utc = window_start_utc + timedelta(hours=24)
    airport_timezones = {
        iata: get_timezone(iata, tz_overrides).key for iata in active_airports
    }
    run_meter = {}
    complete = True
    for iata in active_airports:
        tz = get_timezone(iata, tz_overrides)
        icao = airport_icao(iata, airports_config)
        local_start = window_start_utc.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")
        local_end = window_end_utc.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")
        log.info("Fetching %s (%s) daytime arrivals for next 24 hours: %s to %s (excluding 22:00–06:00 local)", iata, icao, local_start, local_end)
        try:
            raw_arrivals = []
            for interval_start, interval_end in daytime_intervals(window_start_utc, window_end_utc, tz):
                interval_start_local = interval_start.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")
                interval_end_local = interval_end.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")
                log.info("%s requested interval: %s to %s", iata, interval_start_local, interval_end_local)
                raw_arrivals.extend(fetch_arrivals_for_airport(
                    session, iata, icao, interval_start, interval_end,
                    {"x-apikey": api_key, "Accept": "application/json"}, ledger, month, month_spend, run_meter))
                if run_meter.get("incomplete"):
                    break
        except requests.RequestException as exc:
            log.error("FlightAware request failed for %s: %s", iata, exc)
            complete = False
            break
        if run_meter.get("incomplete"):
            complete = False
            log.warning("Budget or API rate limit stopped later airport requests")

        seen_in_batch = set()
        for raw in raw_arrivals:
            flight = parse_flight(raw, iata, tz)
            if not flight["flight_number"] or flight["id"] in seen_in_batch:
                continue
            seen_in_batch.add(flight["id"])
            icao_type = normalize_icao_type(flight["aircraft"]["model"], norm_map) or flight["aircraft"]["model"] or None
            flight["aircraft"]["icao_type"] = icao_type
            pa_entry = lookup_plane_alert(flight["aircraft"]["reg"], flight["aircraft"]["modeS"], reg_lookup, hex_lookup)
            if pa_entry:
                flight["plane_alert_match"] = True
                flight["plane_alert_category"] = pa_entry.get("category")
                flight["plane_alert_tags"] = pa_entry.get("tags", [])
                flight["livery_or_note"] = ", ".join(pa_entry.get("tags", [])) or pa_entry.get("operator") or None
                if not icao_type and pa_entry.get("icao_type"):
                    flight["aircraft"]["icao_type"] = pa_entry["icao_type"]
                    icao_type = pa_entry["icao_type"]
            rarity, reason = classify_rarity(icao_type, pa_entry, iata, rarity_config, flight["airline"])
            flight["rarity"] = rarity
            flight["rarity_reason"] = reason
            flight["rarity_color"] = RARITY_COLORS.get(rarity, "#64748b")
            all_flights.append(flight)
        if run_meter.get("incomplete"):
            break

    # If all airport fetches failed, keep prior data intact rather than replacing it with an empty board.
    if not complete and not all_flights:
        log.error("All arrival requests failed; preserving existing arrivals.json")
        sys.exit(1)

    rarity_counts = {r: 0 for r in RARITY_ORDER}
    for flight in all_flights:
        rarity_counts[flight["rarity"]] = rarity_counts.get(flight["rarity"], 0) + 1
    photo_eligible = [f for f in all_flights if f["rarity"] != "Common"]
    photo_eligible.sort(key=lambda f: RARITY_ORDER.index(f["rarity"]), reverse=True)
    for flight in photo_eligible[:60]:
        flight["photo"] = fetch_photo(session, flight["aircraft"]["reg"], flight["aircraft"]["modeS"], photo_cache)
        time.sleep(0.2)

    seen_flights = prune_seen(seen_flights)
    if ntfy_topic:
        for flight in [f for f in all_flights if f["rarity"] in NOTIFY_RARITIES]:
            if flight["id"] not in seen_flights and send_ntfy(session, ntfy_topic, flight):
                seen_flights[flight["id"]] = datetime.now(timezone.utc).isoformat()
                time.sleep(0.5)

    def chronological_key(flight):
        value = flight["arrival"].get("revised_local") or flight["arrival"].get("scheduled_local") or flight["arrival"].get("scheduled_utc")
        if not value:
            return datetime.max.replace(tzinfo=timezone.utc)
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return datetime.max.replace(tzinfo=timezone.utc)

    all_flights.sort(key=chronological_key)
    now = datetime.now(timezone.utc)
    target_date = window_start_utc.astimezone(get_timezone(active_airports[0], tz_overrides)).strftime("%Y-%m-%d")
    ledger_entry = ledger.get(month, {})
    output = {"_meta": {
        "generated": now.isoformat(), "target_date": target_date, "airports": active_airports,
        "window_hours": 24, "excluded_local_hours": "22:00-06:00", "window_start_utc": window_start_utc.isoformat(),
        "window_end_utc": window_end_utc.isoformat(), "airport_timezones": airport_timezones,
        "total_flights": len(all_flights), "rarity_counts": rarity_counts,
        "last_updated_utc": now.isoformat(), "last_updated_local": datetime.now(ZoneInfo("America/New_York")).isoformat(),
        "is_sample_data": False, "source": "FlightAware AeroAPI v4", "fetch_complete": complete,
        "budget": {"month": month, "estimated_cost_usd": max(month_spend, float(ledger_entry.get("estimated_cost_usd", 0))),
            "monthly_cap_usd": HARD_MONTHLY_CAP_USD, "free_credit_usd": 5.00,
            "result_sets_used": int(ledger_entry.get("result_sets_used", 0)), "rate": "estimate; FlightAware usage can lag"}
    }, "flights": all_flights}
    save_json(ARRIVALS_JSON, output)
    save_json(SEEN_JSON, seen_flights)
    save_json(PHOTO_CACHE_JSON, photo_cache)
    save_json(USAGE_LEDGER_JSON, ledger)
    log.info("Saved %d flights; budget estimate is $%.4f / $%.2f", len(all_flights), output["_meta"]["budget"]["estimated_cost_usd"], HARD_MONTHLY_CAP_USD)


if __name__ == "__main__":
    main()
