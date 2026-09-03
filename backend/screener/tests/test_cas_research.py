from django.test import SimpleTestCase

from screener.cas_research import _classification_metrics, _pct_move, _expiry_candidate, summarize_cas_events


class CASResearchTests(SimpleTestCase):
    def test_pct_move(self):
        self.assertAlmostEqual(_pct_move(100, 101), 1.0)
        self.assertIsNone(_pct_move(0, 101))

    def test_expiry_weekday_candidates(self):
        # 2026-09-03 is Thursday; 2026-09-02 is Wednesday.
        from datetime import date
        self.assertTrue(_expiry_candidate("NIFTY", date(2026, 9, 3)))
        self.assertTrue(_expiry_candidate("BANKNIFTY", date(2026, 9, 2)))
        self.assertFalse(_expiry_candidate("NIFTY", date(2026, 9, 2)))

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

    def test_summary_does_not_claim_prediction(self):
        events = [
            {"max_abs_move_5m_pct": 0.30, "expiry_weekday_candidate": True},
            {"max_abs_move_5m_pct": 0.10, "expiry_weekday_candidate": False},
            {"max_abs_move_5m_pct": 0.40, "expiry_weekday_candidate": True},
        ]
        result = summarize_cas_events(events, large_move_threshold_pct=0.25)
        self.assertEqual(result["sample_size"], 3)
        self.assertEqual(result["large_move_count"], 2)
        self.assertEqual(result["expiry_candidate_sample"], 2)
        self.assertEqual(result["non_expiry_sample"], 1)
        self.assertEqual(result["status"], "insufficient_sample")
        self.assertIn("simple_threshold_metrics", result)
