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
        # Sep 26 2026: unittest.mock.patch('screener.fyers_client.X')
        # requires 'fyers_client' to already exist as an attribute on
        # the 'screener' package -- true once Django's app loading has
        # touched it (e.g. via urls.py importing screener.views), but
        # not guaranteed before that in an isolated test run. Explicit
        # imports here make these tests self-sufficient regardless of
        # what ran before them.
        import screener.fyers_client
        import screener.views

    def test_insufficient_history_returns_none_not_crash(self):
        with patch('screener.fyers_client.get_history', return_value={'candles': [[1, 100, 101, 99, 100, 1000]] * 5}), \
             patch('screener.views._compute_indicators') as mock_compute:
            result = ta.get_technical_snapshot('SOMESTOCK')
        # too few bars (5 < 20) -- must return None, never call the indicator engine on insufficient data
        self.assertIsNone(result)

    def test_history_fetch_exception_returns_none_not_crash(self):
        with patch('screener.fyers_client.get_history', side_effect=RuntimeError("network down")):
            result = ta.get_technical_snapshot('SOMESTOCK')
        self.assertIsNone(result)

    def test_none_candles_returns_none_not_crash(self):
        with patch('screener.fyers_client.get_history', return_value={'candles': None}):
            result = ta.get_technical_snapshot('SOMESTOCK')
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main(verbosity=2)
