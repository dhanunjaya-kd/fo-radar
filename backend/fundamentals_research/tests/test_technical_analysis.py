import os
import sys
import unittest
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fundamentals_research.services import technical_analysis as ta


class TestClassifyTrend(unittest.TestCase):
    def test_confirmed_downtrend(self):
        technicals = {'current_price': 90, 'ema20': 95, 'ema50': 100, 'ema200': 110, 'rsi': 35, 'adx': 28, 'plus_di': 15, 'minus_di': 30}
        result = ta.classify_trend(technicals)
        self.assertEqual(result['classification'], 'Confirmed downtrend')

    def test_weakening_trend(self):
        # Below EMA20/50 but ADX under 20 -- trend losing strength, not confirmed
        technicals = {'current_price': 90, 'ema20': 95, 'ema50': 100, 'ema200': 110, 'rsi': 40, 'adx': 15, 'plus_di': 20, 'minus_di': 22}
        result = ta.classify_trend(technicals)
        self.assertEqual(result['classification'], 'Weakening trend')

    def test_possible_stabilization(self):
        # Reclaimed EMA20, still under EMA50, RSI recovering
        technicals = {'current_price': 98, 'ema20': 95, 'ema50': 100, 'ema200': 110, 'rsi': 48, 'adx': 22, 'plus_di': 22, 'minus_di': 18}
        result = ta.classify_trend(technicals)
        self.assertEqual(result['classification'], 'Possible stabilization')

    def test_potential_recovery_setup(self):
        # Above both EMAs, ADX confirms uptrend, RSI constructive not overbought
        technicals = {'current_price': 110, 'ema20': 105, 'ema50': 100, 'ema200': 95, 'rsi': 58, 'adx': 25, 'plus_di': 28, 'minus_di': 14}
        result = ta.classify_trend(technicals)
        self.assertEqual(result['classification'], 'Potential recovery setup')

    def test_sideways_range_bound(self):
        # Weak ADX, price hugging EMA50
        technicals = {'current_price': 101, 'ema20': 100.5, 'ema50': 100, 'ema200': 100, 'rsi': 50, 'adx': 12, 'plus_di': 20, 'minus_di': 19}
        result = ta.classify_trend(technicals)
        self.assertEqual(result['classification'], 'Sideways / range-bound')

    def test_missing_required_indicator_returns_insufficient_data(self):
        result = ta.classify_trend({'current_price': 100, 'ema20': None, 'ema50': 100, 'rsi': 50, 'adx': 20})
        self.assertEqual(result['classification'], 'Insufficient data')

    def test_empty_technicals_returns_insufficient_data_not_crash(self):
        result = ta.classify_trend({})
        self.assertEqual(result['classification'], 'Insufficient data')
        result2 = ta.classify_trend(None)
        self.assertEqual(result2['classification'], 'Insufficient data')

    def test_never_declares_bottom_just_because_price_is_low(self):
        """Spec explicit: 'Do not declare a bottom merely because a
        stock is significantly below its previous high or appears
        cheap.' A stock far below EMA200 but with no ADX/DI confirmation
        of a genuine reversal must NOT get classified as a recovery."""
        technicals = {'current_price': 50, 'ema20': 90, 'ema50': 100, 'ema200': 150, 'rsi': 45, 'adx': 8, 'plus_di': 20, 'minus_di': 19}
        result = ta.classify_trend(technicals)
        self.assertNotEqual(result['classification'], 'Potential recovery setup')

    def test_every_classification_has_a_stated_reason(self):
        """Spec: never a bare label -- must always explain what
        specific readings drove the classification."""
        cases = [
            {'current_price': 90, 'ema20': 95, 'ema50': 100, 'ema200': 110, 'rsi': 35, 'adx': 28, 'plus_di': 15, 'minus_di': 30},
            {'current_price': 101, 'ema20': 100.5, 'ema50': 100, 'ema200': 100, 'rsi': 50, 'adx': 12, 'plus_di': 20, 'minus_di': 19},
        ]
        for technicals in cases:
            result = ta.classify_trend(technicals)
            self.assertTrue(len(result['reason']) > 10, f"reason too short/missing for {technicals}")


class TestGetTechnicalSnapshot(unittest.TestCase):
    def setUp(self):
        # Sep 26 2026: unittest.mock.patch('screener.views.X') requires
        # 'views' to already exist as an attribute on the 'screener'
        # package -- true once Django's app loading has touched it, but
        # not guaranteed before that in an isolated test run. Explicit
        # import here makes these tests self-sufficient regardless of
        # what ran before them.
        import screener.views

    def _real_shaped_df(self, n_rows=25):
        """Matches screener/views.py's own _fyers_history_df() output
        shape EXACTLY (confirmed by reading that function): columns
        ['ts', 'Open', 'High', 'Low', 'Close', 'Volume'], capitalized --
        the exact shape mismatch that was the real bug here."""
        import pandas as pd
        rows = [[1700000000 + i * 86400, 100 + i, 101 + i, 99 + i, 100 + i, 1000 + i * 10] for i in range(n_rows)]
        return pd.DataFrame(rows, columns=['ts', 'Open', 'High', 'Low', 'Close', 'Volume'])

    def test_insufficient_history_returns_none_not_crash(self):
        with patch('screener.views._fyers_history_df', return_value=self._real_shaped_df(n_rows=5)), \
             patch('screener.views._compute_indicators') as mock_compute:
            result = ta.get_technical_snapshot('SOMESTOCK')
        # too few bars (5 < 20) -- must return None, never call the indicator engine on insufficient data
        self.assertIsNone(result)
        mock_compute.assert_not_called()

    def test_history_fetch_exception_returns_none_not_crash(self):
        with patch('screener.views._fyers_history_df', side_effect=RuntimeError("network down")):
            result = ta.get_technical_snapshot('SOMESTOCK')
        self.assertIsNone(result)

    def test_none_dataframe_returns_none_not_crash(self):
        """_fyers_history_df() itself returns None (not an empty
        DataFrame) when Fyers' response status isn't 'ok' -- confirmed
        from reading that function directly."""
        with patch('screener.views._fyers_history_df', return_value=None):
            result = ta.get_technical_snapshot('SOMESTOCK')
        self.assertIsNone(result)

    def test_real_shaped_dataframe_columns_accessed_correctly(self):
        """The actual bug this rewrite fixes: capitalized column names
        (Close/High/Low/Volume), not lowercase. This test would have
        failed with a KeyError against the old implementation."""
        df = self._real_shaped_df(n_rows=25)
        fake_indicators = {'rsi': 55.0, 'ema20': 110.0, 'ema50': 108.0, 'ema200': None, 'adx': 22.0, 'plus_di': 25.0, 'minus_di': 15.0, 'macd': 1.2, 'atr': 3.0, 'support': 99.0, 'resistance': 130.0, 'volume_avg': 1200.0, 'macd_signal': 1.0, 'macd_histogram': 0.2, 'bb_width_pct': 5.0, 'hist_vol': 20.0, 'vwap': 112.0}
        with patch('screener.views._fyers_history_df', return_value=df), \
             patch('screener.views._compute_indicators', return_value=fake_indicators) as mock_compute:
            result = ta.get_technical_snapshot('SOMESTOCK')

        self.assertIsNotNone(result)
        # confirm _compute_indicators was called with the CORRECT
        # capitalized-column Series, not a KeyError-raising lowercase access
        call_args = mock_compute.call_args[0]
        self.assertEqual(len(call_args), 4)  # close, high, low, volume series
        self.assertEqual(result['current_price'], float(df['Close'].iloc[-1]))
        self.assertEqual(result['rsi'], 55.0)

    def test_calls_fyers_history_with_enough_days_for_ema200(self):
        """EMA200 needs >=200 bars per _compute_indicators' own
        requirement -- confirms this function requests enough calendar
        days to realistically get there (250 calendar days accounts
        for weekends/holidays), not an arbitrarily short window."""
        with patch('screener.views._fyers_history_df', return_value=None) as mock_hist:
            ta.get_technical_snapshot('SOMESTOCK')
        call_args, call_kwargs = mock_hist.call_args
        days_requested = call_kwargs.get('days') or (call_args[1] if len(call_args) > 1 else None)
        self.assertIsNotNone(days_requested)
        self.assertGreaterEqual(days_requested, 200)


if __name__ == '__main__':
    unittest.main(verbosity=2)
