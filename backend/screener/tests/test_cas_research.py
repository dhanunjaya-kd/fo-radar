from datetime import date

from django.test import SimpleTestCase

from screener.cas_research import _classification_metrics, _expiry_candidate, _last_tuesday, _pct_move, summarize_cas_events


class CASResearchTests(SimpleTestCase):
    def test_pct_move(self):
        self.assertAlmostEqual(_pct_move(100, 101), 1.0)
        self.assertIsNone(_pct_move(0, 101))

    def test_nifty_weekly_expiry_is_tuesday(self):
        self.assertTrue(_expiry_candidate("NIFTY", date(2026, 9, 1)))
        self.assertFalse(_expiry_candidate("NIFTY", date(2026, 9, 2)))
        self.assertFalse(_expiry_candidate("NIFTY", date(2026, 9, 3)))

    def test_banknifty_only_last_tuesday_of_month(self):
        self.assertTrue(_expiry_candidate("BANKNIFTY", date(2026, 9, 29)))
        self.assertFalse(_expiry_candidate("BANKNIFTY", date(2026, 9, 22)))
        self.assertFalse(_expiry_candidate("BANKNIFTY", date(2026, 9, 30)))

    def test_last_tuesday_for_every_month_of_2026(self):
        expected = {
            1: date(2026, 1, 27), 2: date(2026, 2, 24), 3: date(2026, 3, 31),
            4: date(2026, 4, 28), 5: date(2026, 5, 26), 6: date(2026, 6, 30),
            7: date(2026, 7, 28), 8: date(2026, 8, 25), 9: date(2026, 9, 29),
            10: date(2026, 10, 27), 11: date(2026, 11, 24), 12: date(2026, 12, 29),
        }
        for month, expected_date in expected.items():
            self.assertEqual(_last_tuesday(2026, month), expected_date)

    def test_threshold_metrics(self):
        events = [
            {"momentum_pct": 0.08, "max_abs_move_5m_pct": 0.30},
            {"momentum_pct": 0.01, "max_abs_move_5m_pct": 0.10},
            {"momentum_pct": -0.09, "max_abs_move_5m_pct": 0.40},
            {"momentum_pct": -0.01, "max_abs_move_5m_pct": 0.05},
        ]
        result = _classification_metrics(events, "momentum_pct", 0.05)
        self.assertEqual(result["sample_size"], 4)
        self.assertEqual(result["tp"], 2)
        self.assertEqual(result["fp"], 0)
        self.assertEqual(result["fn"], 0)
        self.assertEqual(result["tn"], 2)
        self.assertEqual(result["precision_pct"], 100.0)
        self.assertEqual(result["recall_pct"], 100.0)
        self.assertEqual(result["outcome_threshold_pct"], 0.25)

    def test_custom_outcome_threshold_is_honored(self):
        events = [
            {"momentum_pct": 0.08, "max_abs_move_5m_pct": 0.30},
            {"momentum_pct": 0.01, "max_abs_move_5m_pct": 0.20},
        ]
        result = _classification_metrics(events, "momentum_pct", 0.05, outcome_threshold=0.35)
        self.assertEqual(result["outcome_threshold_pct"], 0.35)
        self.assertEqual(result["tp"], 0)
        self.assertEqual(result["fp"], 1)
        self.assertEqual(result["fn"], 0)
        self.assertEqual(result["tn"], 1)

    def test_summary_does_not_claim_prediction(self):
        events = [
            {"date": "2026-09-01", "event_time": "15:16:00", "momentum_pct": 0.08, "change_pct": 0.30, "max_abs_move_5m_pct": 0.30, "expiry_weekday_candidate": True},
            {"date": "2026-09-02", "event_time": "15:17:00", "momentum_pct": 0.01, "change_pct": 0.10, "max_abs_move_5m_pct": 0.10, "expiry_weekday_candidate": False},
            {"date": "2026-09-03", "event_time": "15:18:00", "momentum_pct": -0.09, "change_pct": 0.40, "max_abs_move_5m_pct": 0.40, "expiry_weekday_candidate": False},
        ]
        result = summarize_cas_events(events, large_move_threshold_pct=0.25)
        self.assertEqual(result["sample_size"], 3)
        self.assertEqual(result["large_move_count"], 2)
        self.assertEqual(result["expiry_candidate_sample"], 1)
        self.assertEqual(result["non_expiry_sample"], 2)
        self.assertEqual(result["status"], "insufficient_sample")
        self.assertIn("simple_threshold_metrics", result)
        self.assertEqual(result["simple_threshold_metrics"][0]["outcome_threshold_pct"], 0.25)
