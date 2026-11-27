#!/usr/bin/env python3
"""Local-time scheduling and freshness checks for the arrivals refresh."""

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).parent.parent


def target_date_for(now: datetime, tz: ZoneInfo) -> date:
    """Return today's service date overnight, otherwise the next local date."""
    local_now = now.astimezone(tz)
    if local_now.hour < 6:
        return local_now.date()
    return local_now.date() + timedelta(days=1)


def is_refresh_window(now: datetime, tz: ZoneInfo) -> bool:
    """Refresh after 10 p.m. and before 6 a.m. in the selected local timezone."""
    local_now = now.astimezone(tz)
    if local_now.fold:
        return False
    return local_now.hour >= 22 or local_now.hour < 6


def arrivals_are_fresh(
    arrivals: dict,
    airports: list[str],
    airport_target_dates: dict[str, str],
) -> bool:
    """Check that the complete snapshot covers the configured airports and dates."""
    meta = arrivals.get("_meta", {})
    configured_airports = [airport.upper() for airport in airports]
    if meta.get("fetch_complete") is not True:
        return False
    if meta.get("airports") != configured_airports:
        return False

    saved_target_dates = meta.get("airport_target_dates")
    if saved_target_dates is not None:
        if saved_target_dates != airport_target_dates:
            return False
    elif len(set(airport_target_dates.values())) != 1:
        return False

    primary_target = airport_target_dates[configured_airports[0]]
    if meta.get("target_date") != primary_target:
        return False
    airport_counts = meta.get("airport_flight_counts", {})
    return all(airport in airport_counts for airport in configured_airports)


def main() -> None:
    config = json.loads((ROOT / "config" / "airports.json").read_text(encoding="utf-8"))
    arrivals = json.loads((ROOT / "data" / "arrivals.json").read_text(encoding="utf-8"))
    airports = [str(airport).upper() for airport in config.get("active", [])[:3]]
    if not airports:
        raise ValueError("No active airports configured")

    timezone_overrides = config.get("timezone_overrides", {})
    airport_timezones = {
        airport: ZoneInfo(timezone_overrides.get(airport, "UTC"))
        for airport in airports
    }
    now = datetime.now(timezone.utc)
    primary_timezone = airport_timezones[airports[0]]
    target_dates = {
        airport: target_date_for(now, tz).isoformat()
        for airport, tz in airport_timezones.items()
    }

    fresh = arrivals_are_fresh(arrivals, airports, target_dates)
    in_window = is_refresh_window(now, primary_timezone)
    should_run = in_window and not fresh
    if should_run:
        reason = f"Refreshing arrivals for {target_dates[airports[0]]}."
    elif fresh:
        reason = f"Complete arrivals for {target_dates[airports[0]]} are already present; skipping the refresh."
    else:
        reason = "Outside the primary airport's 10 p.m.–6 a.m. local refresh window."
    print(f"run_update={'true' if should_run else 'false'}", file=sys.stdout)
    print(reason, file=sys.stderr)


if __name__ == "__main__":
    main()
