import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fundamentals_research.services import freshness as fr


class TestAssessFreshness(unittest.TestCase):
    def test_none_timestamp_is_unavailable(self):
        result = fr.assess_freshness(None, 'financial_statement')
        self.assertEqual(result['status'], fr.Freshness.UNAVAILABLE)
        self.assertIsNone(result['age_hours'])

    def test_recent_financial_statement_is_fresh(self):
        ts = datetime.now(timezone.utc) - timedelta(days=2)
        result = fr.assess_freshness(ts, 'financial_statement')
        self.assertEqual(result['status'], fr.Freshness.FRESH)

    def test_old_financial_statement_beyond_14_days_is_stale(self):
        ts = datetime.now(timezone.utc) - timedelta(days=20)
        result = fr.assess_freshness(ts, 'financial_statement')
        self.assertEqual(result['status'], fr.Freshness.STALE)

    def test_quarterly_financials_not_falsely_stale_within_window(self):
        """Spec explicit: 'Do not treat historical quarterly financial
        statements as stale merely because they are not updated
        daily.' A statement fetched 5 days ago must be Fresh, not
        Stale, even though the underlying fiscal quarter itself is
        months old."""
        ts = datetime.now(timezone.utc) - timedelta(days=5)
        result = fr.assess_freshness(ts, 'financial_statement')
        self.assertEqual(result['status'], fr.Freshness.FRESH)

    def test_price_stale_after_one_day(self):
        ts = datetime.now(timezone.utc) - timedelta(hours=30)
        result = fr.assess_freshness(ts, 'market_price')
        self.assertEqual(result['status'], fr.Freshness.STALE)

    def test_price_fresh_within_one_day(self):
        ts = datetime.now(timezone.utc) - timedelta(hours=5)
        result = fr.assess_freshness(ts, 'market_price')
        self.assertEqual(result['status'], fr.Freshness.FRESH)

    def test_ownership_fresh_within_one_quarter(self):
        ts = datetime.now(timezone.utc) - timedelta(days=60)
        result = fr.assess_freshness(ts, 'ownership')
        self.assertEqual(result['status'], fr.Freshness.FRESH)

    def test_ownership_stale_beyond_one_quarter(self):
        ts = datetime.now(timezone.utc) - timedelta(days=150)
        result = fr.assess_freshness(ts, 'ownership')
        self.assertEqual(result['status'], fr.Freshness.STALE)

    def test_unrecognized_category_returns_period_not_verified_not_guessed(self):
        ts = datetime.now(timezone.utc)
        result = fr.assess_freshness(ts, 'some_made_up_category')
        self.assertEqual(result['status'], fr.Freshness.PERIOD_NOT_VERIFIED)

    def test_naive_datetime_handled_without_crash(self):
        """A timestamp with no tzinfo (possible from some DB backends)
        must not crash the comparison."""
        ts = datetime.now() - timedelta(hours=2)
        result = fr.assess_freshness(ts, 'market_price')
        self.assertIn(result['status'], [fr.Freshness.FRESH, fr.Freshness.STALE])

    def test_future_timestamp_flagged_not_silently_fresh(self):
        """A retrieved_at in the future is a real data problem --
        must not be silently clamped to 'fresh'."""
        ts = datetime.now(timezone.utc) + timedelta(hours=5)
        result = fr.assess_freshness(ts, 'market_price')
        self.assertEqual(result['status'], fr.Freshness.PERIOD_NOT_VERIFIED)

    def test_stale_label_is_human_readable(self):
        ts = datetime.now(timezone.utc) - timedelta(hours=30)
        result = fr.assess_freshness(ts, 'market_price')
        self.assertIn('h old', result['label'])

        ts2 = datetime.now(timezone.utc) - timedelta(days=10)
        result2 = fr.assess_freshness(ts2, 'market_price')
        self.assertIn('d old', result2['label'])


class TestAssessSnapshotFreshness(unittest.TestCase):
    def test_handles_snapshot_with_no_related_rows_at_all(self):
        """A snapshot where nothing has been persisted yet for some
        sections (e.g. ownership never available for this source) must
        not crash -- every section should degrade to UNAVAILABLE."""
        from unittest.mock import MagicMock
        fake_snapshot = MagicMock()
        fake_snapshot.financials.order_by.return_value.first.return_value = None
        fake_snapshot.balance_sheets.order_by.return_value.first.return_value = None
        fake_snapshot.cash_flows.order_by.return_value.first.return_value = None
        del fake_snapshot.valuation
        del fake_snapshot.ownership

        result = fr.assess_snapshot_freshness(fake_snapshot)
        for section in ('financials', 'balance_sheet', 'cash_flow', 'valuation', 'ownership'):
            self.assertEqual(result[section]['status'], fr.Freshness.UNAVAILABLE)


if __name__ == '__main__':
    unittest.main(verbosity=2)
