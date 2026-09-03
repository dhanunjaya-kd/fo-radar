from unittest.mock import patch

from django.test import SimpleTestCase

from screener.cas_radar import _microstructure_capabilities, get_cas_radar


class CASRadarTests(SimpleTestCase):
    def test_microstructure_fields_are_not_invented(self):
        result = _microstructure_capabilities([{"Spot": 25000, "PCR": 1.1}])
        self.assertFalse(result["available"])
        self.assertFalse(result["iep"])
        self.assertFalse(result["imbalance"])

    def test_microstructure_capabilities_detect_real_aliases(self):
        result = _microstructure_capabilities([{"IEP": 24980, "Imbalance": -1200}])
        self.assertTrue(result["available"])
        self.assertTrue(result["iep"])
        self.assertTrue(result["imbalance"])
        self.assertFalse(result["buy_quantity"])

    @patch("screener.index_tracker.compute_cas_auction_moves", return_value=[])
    @patch("screener.index_tracker.get_today_snapshots", return_value=[{"Spot": 25000, "Change %": 0.4, "PCR": 1.0}])
    def test_payload_is_research_only(self, _snapshots, _history):
        result = get_cas_radar("NIFTY")
        self.assertEqual(result["index"], "NIFTY")
        self.assertEqual(result["prediction"]["status"], "research_only")
        self.assertIsNone(result["prediction"]["direction"])
        self.assertIsNone(result["prediction"]["large_move_probability"])

    def test_invalid_index_rejected(self):
        with self.assertRaises(ValueError):
            get_cas_radar("SENSEX")
