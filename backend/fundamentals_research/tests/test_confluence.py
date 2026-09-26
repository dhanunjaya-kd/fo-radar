import os
import sys
import unittest
from unittest.mock import MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fundamentals_research.services import confluence as cf


class TestBuildConfluence(unittest.TestCase):
    def _fake_snapshot(self, revenue_growth=None, pat_growth=None, cfo_to_pat=None, debt_equity=None, pe=None, distance_52w=None):
        snapshot = MagicMock()
        fin = MagicMock()
        fin.revenue_growth_yoy_pct = revenue_growth
        fin.pat_growth_yoy_pct = pat_growth
        snapshot.financials.order_by.return_value.first.return_value = fin if any(v is not None for v in [revenue_growth, pat_growth]) else None

        bs = MagicMock()
        bs.debt_equity = debt_equity
        snapshot.balance_sheets.order_by.return_value.first.return_value = bs

        cash_flow = MagicMock()
        cash_flow.cfo_to_pat = cfo_to_pat
        snapshot.cash_flows.order_by.return_value.first.return_value = cash_flow

        val = MagicMock()
        val.pe = pe
        val.distance_from_52w_high_pct = distance_52w
        snapshot.valuation = val if pe is not None else None
        if pe is None:
            del snapshot.valuation

        return snapshot

    def test_never_returns_a_combined_score_key(self):
        """Spec explicit: no combined/weighted score anywhere."""
        snapshot = self._fake_snapshot(revenue_growth=10, pat_growth=15, cfo_to_pat=0.9, debt_equity=0.3, pe=20)
        technicals = {'rsi': 55, 'volume_avg': 1000000}
        trend = {'classification': 'Potential recovery setup', 'reason': 'test'}
        result = cf.build_confluence(snapshot, technicals, trend)

        for forbidden_key in ('score', 'combined_score', 'overall_score', 'weighted_score', 'rating'):
            self.assertNotIn(forbidden_key, result)

    def test_strong_fundamentals_all_positive_signals(self):
        snapshot = self._fake_snapshot(revenue_growth=10, pat_growth=15, cfo_to_pat=0.9, debt_equity=0.3)
        result = cf.build_confluence(snapshot, None, None)
        self.assertEqual(result['fundamental_quality']['assessment'], 'Strong')

    def test_weak_fundamentals_all_negative_signals(self):
        snapshot = self._fake_snapshot(revenue_growth=-5, pat_growth=-10, cfo_to_pat=0.3, debt_equity=1.5)
        result = cf.build_confluence(snapshot, None, None)
        self.assertEqual(result['fundamental_quality']['assessment'], 'Weak')

    def test_mixed_fundamentals_shown_as_mixed_not_hidden(self):
        """Spec: 'Do not hide conflicting evidence.' Positive revenue
        growth but negative PAT growth must show as Mixed, not
        silently averaged into Strong or Weak."""
        snapshot = self._fake_snapshot(revenue_growth=10, pat_growth=-10, cfo_to_pat=0.9, debt_equity=0.3)
        result = cf.build_confluence(snapshot, None, None)
        self.assertEqual(result['fundamental_quality']['assessment'], 'Mixed')

    def test_combination_note_states_both_sides_explicitly(self):
        """The spec's own example shape: 'strong fundamentals + bearish
        technicals' -- both halves must be visible in the note, not
        collapsed."""
        snapshot = self._fake_snapshot(revenue_growth=10, pat_growth=15, cfo_to_pat=0.9, debt_equity=0.3)
        trend = {'classification': 'Confirmed downtrend', 'reason': 'test'}
        result = cf.build_confluence(snapshot, {'rsi': 50, 'volume_avg': 1000}, trend)
        self.assertIn('Strong', result['combination_note'])
        self.assertIn('confirmed downtrend', result['combination_note'])

    def test_missing_technicals_shows_insufficient_data_not_crash(self):
        snapshot = self._fake_snapshot(revenue_growth=10, pat_growth=15)
        result = cf.build_confluence(snapshot, None, None)
        self.assertEqual(result['technical_trend']['assessment'], 'Insufficient data')
        self.assertEqual(result['momentum']['assessment'], 'Insufficient data')
        self.assertIsNone(result['combination_note'])  # can't state a combination without both sides

    def test_valuation_never_claims_cheap_or_expensive_without_benchmark(self):
        """No sector P/E benchmark is wired -- must never CLAIM 'cheap'
        or 'expensive' as a verdict. It's fine (and correct) for the
        disclaimer itself to mention those words while explicitly
        saying no judgment is being made -- checked here by requiring
        the disclaiming phrase, not a bare absence of the words."""
        snapshot = self._fake_snapshot(pe=15, distance_52w=-20)
        result = cf.build_confluence(snapshot, None, None)
        reason_lower = result['valuation_context']['reason'].lower()
        self.assertIn('no sector p/e benchmark available', reason_lower)
        self.assertNotIn('is cheap', reason_lower)
        self.assertNotIn('is expensive', reason_lower)
        self.assertNotIn('undervalued', reason_lower)
        self.assertNotIn('overvalued', reason_lower)

    def test_overbought_and_oversold_momentum_labels(self):
        snapshot = self._fake_snapshot()
        result_high = cf.build_confluence(snapshot, {'rsi': 75, 'volume_avg': 1000}, None)
        self.assertEqual(result_high['momentum']['assessment'], 'Overbought')
        result_low = cf.build_confluence(snapshot, {'rsi': 25, 'volume_avg': 1000}, None)
        self.assertEqual(result_low['momentum']['assessment'], 'Oversold')

    def test_sector_alignment_honestly_unavailable(self):
        """No sector benchmark wired -- must say so, not fabricate an assessment."""
        snapshot = self._fake_snapshot()
        result = cf.build_confluence(snapshot, None, None)
        self.assertEqual(result['sector_alignment']['assessment'], 'Not available')


if __name__ == '__main__':
    unittest.main(verbosity=2)
