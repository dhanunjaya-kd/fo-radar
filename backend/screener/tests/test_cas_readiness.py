from django.test import SimpleTestCase
from unittest.mock import patch

from screener.cas_readiness import build_cas_readiness


class CASReadinessTests(SimpleTestCase):
    @patch("screener.cas_readiness.list_available_dates", return_value=["2026-09-03", "2026-09-02"])
    @patch("screener.cas_readiness.get_snapshots_for_date")
    def test_counts_only_days_with_two_early_warning_samples(self, get_rows, _dates):
        def rows(index_name, date_value, *args, **kwargs):
            if str(date_value) == "2026-09-03":
                return [{"Time": "15:16:00"}, {"Time": "15:18:00"}]
            return [{"Time": "15:17:00"}]

        get_rows.side_effect = rows
        result = build_cas_readiness("NIFTY")
        self.assertEqual(result["logged_days"], 2)
        self.assertEqual(result["usable_early_warning_days"], 1)
        self.assertEqual(result["remaining_usable_days"], 29)
        self.assertEqual(result["status"], "collecting")

    @patch("screener.cas_readiness.list_available_dates", return_value=[])
    def test_empty_dataset_is_collecting(self, _dates):
        result = build_cas_readiness("BANKNIFTY")
        self.assertEqual(result["logged_days"], 0)
        self.assertEqual(result["usable_early_warning_days"], 0)
        self.assertEqual(result["status"], "collecting")

    def test_invalid_index(self):
        with self.assertRaises(ValueError):
            build_cas_readiness("SENSEX")
