#!/usr/bin/env python3
"""
LootRadar — Next-Day Rare Flight & Livery Tracker
Data pipeline: fetches tomorrow's arrivals, assigns Fortnite-style rarity,
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
from datetime import date, datetime, timedelta, timezone
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

# ---------------------------------------------------------------------------
# External constants
# ---------------------------------------------------------------------------
PLANE_ALERT_DB_URL = (
    "https://raw.githubusercontent.com/sdr-enthusiasts/plane-alert-db/main/"
    "plane-alert-db.csv"
)
AERODATABOX_HOST = "aerodatabox.p.rapidapi.com"
AERODATABOX_BASE = f"https://{AERODATABOX_HOST}/flights/airports/iata"
API_MARKET_BASE = "https://prod.api.market/api/v1/aedbx/aerodatabox/flights/airports/iata"
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


def tomorrow_date(tz: ZoneInfo) -> str:
    """Return YYYY-MM-DD for 'tomorrow' in the given timezone."""
    now_local = datetime.now(tz)
    return (now_local + timedelta(days=1)).strftime("%Y-%m-%d")


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

        tags = [
            t for t in [entry.get("Tag 1", ""), entry.get("#Tag 2", ""), entry.get("#Tag 3", "")]
            if t
        ]
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

    tier_names = ["mythic", "legendary", "epic", "rare", "uncommon", "common"]

    for tier_lower in tier_names:
        tier_data = profile.get(tier_lower, {})
        tier_title = tier_lower.capitalize()
        reason = tier_data.get("reason_template", tier_title)

        # 1. ICAO type list match
        if icao_up and icao_up in [t.upper() for t in tier_data.get("icao_types", [])]:
            return tier_title, reason

        # 2. plane-alert-db category match (Mythic/Epic tiers)
        pa_cats = [c.lower() for c in tier_data.get("plane_alert_categories", [])]
        if pa_cats and pa_category:
            if any(c in pa_category for c in pa_cats):
                entry_note = (plane_alert_entry or {}).get("operator", "") or tier_title
                return tier_title, f"{reason} — {entry_note}".strip(" —")

        # 3. plane-alert-db any match for epic tier (special livery)
        if tier_data.get("plane_alert_match") and plane_alert_entry is not None:
            tags_str = ", ".join(plane_alert_entry.get("tags", []))
            operator = plane_alert_entry.get("operator", "")
            livery_note = tags_str or operator or "Special Livery"
            return tier_title, f"{reason} — {livery_note}".strip(" —")

    return "Common", profile.get("common", {}).get("reason_template", "Standard Traffic")


# ---------------------------------------------------------------------------
# AeroDataBox fetching
# ---------------------------------------------------------------------------

def fetch_arrivals_for_airport(
    session: requests.Session,
    iata: str,
    target_date: str,
    api_base: str,
    headers: dict,
) -> list[dict]:
    """Fetch 24h arrivals for one airport in two 12-hour windows."""
    params = {
        "withLeg": "true",
        "direction": "Arrival",
        "withCancelled": "false",
        "withCodeshared": "false",
        "withCargo": "true",
        "withPrivate": "true",
    }

    windows = [("00:00", "11:59"), ("12:00", "23:59")]
    all_arrivals = []

    for start_t, end_t in windows:
        url = f"{api_base}/{iata}/{target_date}T{start_t}/{target_date}T{end_t}"
        log.info("Fetching %s %s–%s …", iata, start_t, end_t)
        try:
            resp = session.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code == 404:
                log.warning("No data for %s %s–%s (404)", iata, start_t, end_t)
                continue
            if resp.status_code == 429:
                log.warning("Rate limited — waiting 60s before retry")
                time.sleep(60)
                resp = session.get(url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            arrivals = data.get("arrivals", [])
            log.info("  Got %d arrivals", len(arrivals))
            all_arrivals.extend(arrivals)
        except requests.RequestException as exc:
            log.error("Error fetching %s %s–%s: %s", iata, start_t, end_t, exc)

        # Polite delay between calls
        time.sleep(1)

    return all_arrivals


def parse_flight(raw: dict, airport: str) -> dict:
    """Extract normalized flight fields from an AeroDataBox arrival item."""
    num = (raw.get("number") or "").strip()
    status = raw.get("status", "Scheduled")

    airline = raw.get("airline") or {}
    airline_name = airline.get("name", "")
    airline_iata = airline.get("iata", "")
    airline_icao = airline.get("icao", "")

    dep = raw.get("departure") or {}
    dep_ap = dep.get("airport") or {}
    origin_iata = dep_ap.get("iata", "")
    origin_icao = dep_ap.get("icao", "")
    origin_name = dep_ap.get("name", "")

    arr = raw.get("arrival") or {}
    arr_times = arr.get("revisedTime") or arr.get("scheduledTime") or {}
    arr_local = arr_times.get("local")
    arr_utc = arr_times.get("utc")
    arr_sched = (arr.get("scheduledTime") or {}).get("local")
    terminal = arr.get("terminal")
    gate = arr.get("gate")

    aircraft = raw.get("aircraft") or {}
    reg = (aircraft.get("reg") or "").strip().upper() or None
    modes = (aircraft.get("modeS") or "").strip().upper() or None
    model = (aircraft.get("model") or "").strip()

    # Build dedup key
    target_date = (arr_local or arr_utc or "")[:10]
    reg_part = re.sub(r"[\s\-]", "", reg) if reg else "NOREG"
    flight_id = f"{target_date}_{airport.upper()}_{num}_{reg_part}"

    return {
        "id": flight_id,
        "airport": airport.upper(),
        "flight_number": num,
        "airline": {
            "name": airline_name,
            "iata": airline_iata,
            "icao": airline_icao,
        },
        "origin": {
            "iata": origin_iata,
            "icao": origin_icao,
            "name": origin_name,
        },
        "arrival": {
            "scheduled_local": arr_sched,
            "scheduled_utc": arr_utc,
            "revised_local": arr_local if arr_local != arr_sched else None,
            "terminal": terminal,
            "gate": gate,
        },
        "aircraft": {
            "reg": reg,
            "modeS": modes,
            "model": model,
            "icao_type": None,  # filled later
        },
        "rarity": "Common",
        "rarity_reason": "",
        "rarity_color": RARITY_COLORS["Common"],
        "livery_or_note": None,
        "plane_alert_match": False,
        "plane_alert_category": None,
        "plane_alert_tags": [],
        "photo": {"url": None, "thumbnail": None, "link": None, "photographer": None},
        "status": status,
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
    fn = flight["flight_number"]
    airport = flight["airport"]
    icao_type = flight["aircraft"]["icao_type"] or flight["aircraft"]["model"] or "?"
    reg = flight["aircraft"]["reg"] or "Reg TBD"
    rarity_reason = flight["rarity_reason"] or rarity
    origin_iata = flight["origin"]["iata"] or "?"
    origin_name = flight["origin"]["name"] or origin_iata

    arr_local = flight["arrival"]["revised_local"] or flight["arrival"]["scheduled_local"] or "?"
    arr_time_str = arr_local[11:16] if len(arr_local) > 10 else arr_local

    title = f"[{rarity.upper()}] {airline_name} {fn} → {airport} ({icao_type})"
    body = (
        f"{icao_type} ({reg}) • {rarity_reason} • "
        f"From: {origin_iata} ({origin_name}) • "
        f"Arriving Tomorrow at {arr_time_str}"
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
    # --- Read secrets from environment ---
    rapidapi_key = os.environ.get("AERODATABOX_API_KEY", "").strip()
    api_market_key = os.environ.get("AERODATABOX_API_MARKET_KEY", "").strip()
    ntfy_topic = os.environ.get("NTFY_TOPIC", "").strip()

    if api_market_key:
        api_base = API_MARKET_BASE
        api_headers = {"x-api-market-key": api_market_key}
        api_provider = "API.Market"
    elif rapidapi_key:
        api_base = AERODATABOX_BASE
        api_headers = {
            "x-rapidapi-key": rapidapi_key,
            "x-rapidapi-host": AERODATABOX_HOST,
        }
        api_provider = "RapidAPI"
    else:
        log.error("No AeroDataBox credential found. Add AERODATABOX_API_MARKET_KEY or AERODATABOX_API_KEY as a GitHub Actions secret.")
        sys.exit(1)

    log.info("Using AeroDataBox via %s", api_provider)

    # --- Load config ---
    airports_config = load_json(AIRPORTS_JSON, {"active": ["DCA", "IAD"], "timezone_overrides": {}, "presets": []})
    rarity_config = load_json(RARITY_JSON, {"profiles": {}, "icao_type_normalization": {"keywords": []}})

    active_airports = airports_config.get("active", [])[:3]  # max 3 to protect free tier
    tz_overrides = airports_config.get("timezone_overrides", {})

    if not active_airports:
        log.error("No active airports configured. Check config/airports.json.")
        sys.exit(1)

    log.info("Active airports: %s", active_airports)

    # --- Load persistent data ---
    seen_flights = load_json(SEEN_JSON, {"_comment": "auto-generated"})
    photo_cache = load_json(PHOTO_CACHE_JSON, {"_comment": "auto-generated"})

    # --- Build normalization map ---
    norm_map = build_normalization_map(rarity_config)

    # --- Create HTTP session ---
    session = requests.Session()
    session.headers.update({"User-Agent": "LootRadar/1.0 (github.com/lootrada)"})

    # --- Download plane-alert-db ---
    reg_lookup, hex_lookup = download_plane_alert_db(session)

    # --- Fetch arrivals for each airport ---
    all_flights: list[dict] = []
    rarity_counts = {r: 0 for r in RARITY_ORDER}

    for iata in active_airports:
        tz = get_timezone(iata, tz_overrides)
        target_date = tomorrow_date(tz)
        log.info("Fetching arrivals for %s on %s (tz: %s)", iata, target_date, tz.key)

        raw_arrivals = fetch_arrivals_for_airport(session, iata, target_date, api_base, api_headers)

        # Deduplicate by flight number within this airport
        seen_in_batch: set = set()

        for raw in raw_arrivals:
            flight = parse_flight(raw, iata)
            fn = flight["flight_number"]

            if fn in seen_in_batch:
                continue
            seen_in_batch.add(fn)

            # Normalize ICAO type
            raw_model = flight["aircraft"]["model"]
            icao_type = normalize_icao_type(raw_model, norm_map)
            flight["aircraft"]["icao_type"] = icao_type

            # plane-alert-db enrichment
            reg = flight["aircraft"]["reg"]
            modes = flight["aircraft"]["modeS"]
            pa_entry = lookup_plane_alert(reg, modes, reg_lookup, hex_lookup)

            if pa_entry:
                flight["plane_alert_match"] = True
                flight["plane_alert_category"] = pa_entry.get("category")
                flight["plane_alert_tags"] = pa_entry.get("tags", [])
                operator = pa_entry.get("operator", "")
                tags_str = ", ".join(t for t in pa_entry.get("tags", []) if t)
                flight["livery_or_note"] = tags_str or operator or None
                # Override icao_type with plane-alert-db if we didn't get one
                if not icao_type and pa_entry.get("icao_type"):
                    flight["aircraft"]["icao_type"] = pa_entry["icao_type"]
                    icao_type = pa_entry["icao_type"]

            # Assign rarity
            rarity, reason = classify_rarity(icao_type, pa_entry, iata, rarity_config)
            flight["rarity"] = rarity
            flight["rarity_reason"] = reason
            flight["rarity_color"] = RARITY_COLORS.get(rarity, "#64748b")
            rarity_counts[rarity] = rarity_counts.get(rarity, 0) + 1

            all_flights.append(flight)

    # --- Photo enrichment for Uncommon+ (cap at 60 to be polite) ---
    notify_flights = [f for f in all_flights if f["rarity"] in NOTIFY_RARITIES]
    photo_eligible = [f for f in all_flights if f["rarity"] != "Common"]
    photo_eligible.sort(key=lambda f: RARITY_ORDER.index(f["rarity"]) if f["rarity"] in RARITY_ORDER else 0, reverse=True)
    photo_eligible = photo_eligible[:60]

    log.info("Fetching photos for %d flights …", len(photo_eligible))
    for flight in photo_eligible:
        reg = flight["aircraft"]["reg"]
        modes = flight["aircraft"]["modeS"]
        photo = fetch_photo(session, reg, modes, photo_cache)
        flight["photo"] = photo
        time.sleep(0.2)  # polite delay

    # --- Push notifications for new Rare+ flights ---
    seen_flights = prune_seen(seen_flights)

    if ntfy_topic:
        for flight in notify_flights:
            fid = flight["id"]
            if fid not in seen_flights:
                sent = send_ntfy(session, ntfy_topic, flight)
                if sent:
                    seen_flights[fid] = datetime.now(timezone.utc).isoformat()
                time.sleep(0.5)
    else:
        log.info("NTFY_TOPIC not set — skipping notifications")

    # --- Sort flights: rarity desc, then arrival time asc ---
    def sort_key(f):
        r_idx = RARITY_ORDER.index(f["rarity"]) if f["rarity"] in RARITY_ORDER else 0
        arr = f["arrival"]["revised_local"] or f["arrival"]["scheduled_local"] or "9999"
        return (-r_idx, arr)

    all_flights.sort(key=sort_key)

    # --- Build metadata ---
    now_utc = datetime.now(timezone.utc)
    # Pick last target date seen (or tomorrow in UTC)
    target_dates = set()
    for f in all_flights:
        d = (f["arrival"]["scheduled_local"] or f["arrival"]["scheduled_utc"] or "")[:10]
        if d:
            target_dates.add(d)
    target_date_str = max(target_dates) if target_dates else (now_utc + timedelta(days=1)).strftime("%Y-%m-%d")

    output = {
        "_meta": {
            "generated": now_utc.isoformat(),
            "target_date": target_date_str,
            "airports": active_airports,
            "total_flights": len(all_flights),
            "rarity_counts": rarity_counts,
            "last_updated_utc": now_utc.isoformat(),
            "last_updated_local": datetime.now(ZoneInfo("America/New_York")).isoformat(),
            "is_sample_data": False,
        },
        "flights": all_flights,
    }

    # --- Save outputs ---
    save_json(ARRIVALS_JSON, output)
    log.info("Wrote %d flights to %s", len(all_flights), ARRIVALS_JSON)

    save_json(SEEN_JSON, seen_flights)
    log.info("Saved seen_flights (%d entries)", len([k for k in seen_flights if not k.startswith("_")]))

    save_json(PHOTO_CACHE_JSON, photo_cache)
    log.info("Saved photo_cache (%d entries)", len([k for k in photo_cache if not k.startswith("_")]))

    log.info("Done! Rarity breakdown: %s", rarity_counts)


if __name__ == "__main__":
    main()
