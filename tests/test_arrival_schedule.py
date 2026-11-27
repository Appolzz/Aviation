import os
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from scripts import update_arrivals
from scripts.arrival_schedule import arrivals_are_fresh, is_refresh_window, target_date_for


class ArrivalScheduleTests(unittest.TestCase):
    def test_target_date_stays_on_service_day_until_six_local(self):
        timezone = ZoneInfo("America/New_York")
        self.assertEqual(
            target_date_for(datetime.fromisoformat("2026-11-28T10:59:00+00:00"), timezone).isoformat(),
            "2026-11-28",
        )
        self.assertEqual(
            target_date_for(datetime.fromisoformat("2026-11-28T11:00:00+00:00"), timezone).isoformat(),
            "2026-11-29",
        )

    def test_window_and_target_dates_follow_daylight_saving_time(self):
        timezone = ZoneInfo("America/New_York")
        before_spring_forward = datetime.fromisoformat("2026-03-08T06:30:00+00:00")
        after_spring_forward = datetime.fromisoformat("2026-03-08T07:30:00+00:00")
        self.assertEqual(target_date_for(before_spring_forward, timezone).isoformat(), "2026-03-08")
        self.assertEqual(target_date_for(after_spring_forward, timezone).isoformat(), "2026-03-08")
        self.assertTrue(is_refresh_window(datetime.fromisoformat("2026-11-27T03:17:00+00:00"), timezone))
        self.assertFalse(is_refresh_window(datetime.fromisoformat("2026-11-27T11:17:00+00:00"), timezone))
        first_fall_back_hour = datetime.fromisoformat("2026-11-01T05:17:00+00:00")
        repeated_fall_back_hour = datetime.fromisoformat("2026-11-01T06:17:00+00:00")
        self.assertTrue(is_refresh_window(first_fall_back_hour, timezone))
        self.assertFalse(is_refresh_window(repeated_fall_back_hour, timezone))

    def test_freshness_requires_complete_matching_airport_dates(self):
        snapshot = {
            "_meta": {
                "fetch_complete": True,
                "airports": ["DCA", "IAD"],
                "target_date": "2026-11-28",
                "airport_flight_counts": {"DCA": 1, "IAD": 1},
            }
        }
        targets = {"DCA": "2026-11-28", "IAD": "2026-11-28"}
        self.assertTrue(arrivals_are_fresh(snapshot, ["DCA", "IAD"], targets))
        snapshot["_meta"]["fetch_complete"] = False
        self.assertFalse(arrivals_are_fresh(snapshot, ["DCA", "IAD"], targets))
        snapshot["_meta"]["fetch_complete"] = True
        self.assertFalse(
            arrivals_are_fresh(snapshot, ["DCA", "IAD"], {"DCA": "2026-11-28", "IAD": "2026-11-29"})
        )

    def test_complete_snapshot_exits_before_api_key_or_requests(self):
        config = {"active": ["DCA"], "timezone_overrides": {"DCA": "America/New_York"}}
        now = datetime.now(ZoneInfo("America/New_York"))
        target = target_date_for(now, ZoneInfo("America/New_York")).isoformat()
        snapshot = {
            "_meta": {
                "fetch_complete": True,
                "airports": ["DCA"],
                "target_date": target,
                "airport_flight_counts": {"DCA": 1},
            }
        }
        with patch.object(update_arrivals, "load_json", side_effect=[config, snapshot]):
            with patch.dict(os.environ, {}, clear=True):
                update_arrivals.main()


if __name__ == "__main__":
    unittest.main()
