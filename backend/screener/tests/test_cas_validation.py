from django.test import SimpleTestCase

from screener.cas_validation import (
    aggregate_day_level,
    lead_time_profile,
    select_non_overlapping_events,
    validate_early_warning,
)


class CASValidationTests(SimpleTestCase):
    def setUp(self):
        self.events = [
            {"index": "NIFTY", "date": "2026-09-03", "event_time": "15:16:00", "momentum_pct": 0.08, "change_pct": 0.30, "max_abs_move_1m_pct": 0.10, "max_abs_move_2m_pct": 0.20, "max_abs_move_3m_pct": 0.30, "max_abs_move_5m_pct": 0.40, "expiry_weekday_candidate": True},
            {"index": "NIFTY", "date": "2026-09-03", "event_time": "15:17:00", "momentum_pct": 0.12, "change_pct": 0.35, "max_abs_move_1m_pct": 0.20, "max_abs_move_2m_pct": 0.30, "max_abs_move_3m_pct": 0.40, "max_abs_move_5m_pct": 0.50, "expiry_weekday_candidate": True},
            {"index": "NIFTY", "date": "2026-09-02", "event_time": "15:16:00", "momentum_pct": 0.01, "change_pct": 0.05, "max_abs_move_1m_pct": 0.05, "max_abs_move_2m_pct": 0.06, "max_abs_move_3m_pct": 0.08, "max_abs_move_5m_pct": 0.10, "expiry_weekday_candidate": False},
        ]

    def test_non_overlapping_selection(self):
        selected = select_non_overlapping_events(self.events, gap_minutes=5)
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0]["date"], "2026-09-03")

    def test_day_level_uses_largest_forward_move(self):
        rows = aggregate_day_level(self.events, threshold=0.25)
        self.assertEqual(len(rows), 2)
        day = next(r for r in rows if r["date"] == "2026-09-03")
        self.assertEqual(day["max_abs_move_5m_pct"], 0.5)
        self.assertTrue(day["large_move"])

    def test_lead_time_profile(self):
        profile = lead_time_profile(self.events, threshold=0.25)
        self.assertEqual([p["horizon_minutes"] for p in profile], [1, 2, 3, 5])
        self.assertEqual(profile[-1]["large_move_count"], 1)

    def test_validation_is_day_level_and_conservative(self):
        result = validate_early_warning(self.events, threshold=0.05, outcome_threshold=0.25)
        self.assertEqual(result["sample_size_days"], 2)
        self.assertEqual(result["outcome_threshold_pct"], 0.25)
        self.assertEqual(result["status"], "insufficient_sample")
