import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fundamentals_research.services import entry_setup as es


class TestBuildEntrySetup(unittest.TestCase):
    def test_confirmed_setup_hand_verified(self):
        # price=101, EMA20=100, EMA50=95, ATR=5, ADX=25, +DI>-DI, RSI=50, support=90
        technicals = {
            'current_price': 101, 'ema20': 100, 'ema50': 95, 'atr': 5,
            'adx': 25, 'plus_di': 28, 'minus_di': 15, 'rsi': 50, 'support': 90,
        }
        result = es.build_entry_setup(technicals)
        self.assertEqual(result['status'], 'setup_confirmed')

        # entry zone = 100 +/- 0.5*5 = [97.5, 102.5]
        self.assertEqual(result['entry_zone']['low'], 97.5)
        self.assertEqual(result['entry_zone']['high'], 102.5)

        # stop_from_atr = 100 - 1.5*5 = 92.5; support=90 < entry_mid(100) -> max(92.5, 90) = 92.5
        self.assertEqual(result['stop_loss'], 92.5)

        # risk = entry_mid(100) - stop(92.5) = 7.5
        self.assertEqual(result['risk_per_share'], 7.5)
        # target_1 = 100 + 1.5*7.5 = 111.25 ; target_2 = 100 + 3*7.5 = 122.5
        self.assertEqual(result['target_1'], 111.25)
        self.assertEqual(result['target_2'], 122.5)
        self.assertEqual(result['reward_to_risk_target_1'], 1.5)
        self.assertEqual(result['reward_to_risk_target_2'], 3.0)

    def test_support_tighter_than_atr_stop_is_used(self):
        # support (98) is closer to entry_mid (100) than the ATR-based stop (92.5) -- should use 98
        technicals = {
            'current_price': 101, 'ema20': 100, 'ema50': 95, 'atr': 5,
            'adx': 25, 'plus_di': 28, 'minus_di': 15, 'rsi': 50, 'support': 98,
        }
        result = es.build_entry_setup(technicals)
        self.assertEqual(result['stop_loss'], 98)  # tighter (closer to entry) than 92.5

    def test_no_setup_when_trend_not_confirmed(self):
        # price below EMA50 -- not an uptrend at all
        technicals = {
            'current_price': 90, 'ema20': 95, 'ema50': 100, 'atr': 5,
            'adx': 25, 'plus_di': 28, 'minus_di': 15, 'rsi': 50, 'support': 85,
        }
        result = es.build_entry_setup(technicals)
        self.assertEqual(result['status'], 'no_setup')
        self.assertEqual(result['message'], 'No validated entry setup currently available.')
        self.assertFalse(result['conditions_checked']['confirmed_uptrend'])

    def test_no_setup_when_price_too_far_from_ema20(self):
        # uptrend confirmed but price is 20 points above EMA20 with ATR only 5 -- not a pullback
        technicals = {
            'current_price': 120, 'ema20': 100, 'ema50': 90, 'atr': 5,
            'adx': 25, 'plus_di': 28, 'minus_di': 15, 'rsi': 50, 'support': 85,
        }
        result = es.build_entry_setup(technicals)
        self.assertEqual(result['status'], 'no_setup')
        self.assertFalse(result['conditions_checked']['pullback_to_ema20'])

    def test_no_setup_when_rsi_overbought(self):
        technicals = {
            'current_price': 101, 'ema20': 100, 'ema50': 90, 'atr': 5,
            'adx': 25, 'plus_di': 28, 'minus_di': 15, 'rsi': 80, 'support': 85,
        }
        result = es.build_entry_setup(technicals)
        self.assertEqual(result['status'], 'no_setup')
        self.assertFalse(result['conditions_checked']['rsi_constructive_not_extended'])

    def test_never_declares_setup_just_because_price_is_low(self):
        """Spec explicit: 'Do not declare a bottom merely because a
        stock is significantly below its previous high.' Price far
        below EMA200-scale levels with NO ADX/DI confirmation must
        never produce a confirmed setup."""
        technicals = {
            'current_price': 50, 'ema20': 90, 'ema50': 100, 'atr': 5,
            'adx': 10, 'plus_di': 20, 'minus_di': 19, 'rsi': 30, 'support': 45,
        }
        result = es.build_entry_setup(technicals)
        self.assertNotEqual(result['status'], 'setup_confirmed')

    def test_missing_technicals_returns_unavailable_not_crash(self):
        result = es.build_entry_setup({})
        self.assertEqual(result['status'], 'unavailable')
        result2 = es.build_entry_setup(None)
        self.assertEqual(result2['status'], 'unavailable')

    def test_missing_one_required_field_returns_unavailable(self):
        technicals = {'current_price': 101, 'ema20': 100, 'ema50': 95, 'atr': None, 'adx': 25, 'plus_di': 28, 'minus_di': 15, 'rsi': 50}
        result = es.build_entry_setup(technicals)
        self.assertEqual(result['status'], 'unavailable')

    def test_setup_always_states_its_method(self):
        """Spec: every level must trace to a documented method -- never
        a bare number with no stated calculation."""
        technicals = {
            'current_price': 101, 'ema20': 100, 'ema50': 95, 'atr': 5,
            'adx': 25, 'plus_di': 28, 'minus_di': 15, 'rsi': 50, 'support': 90,
        }
        result = es.build_entry_setup(technicals)
        self.assertIn('method', result)
        self.assertTrue(len(result['method']) > 20)
        self.assertIn('invalidation_condition', result)

    def test_no_setup_response_includes_which_conditions_failed(self):
        technicals = {
            'current_price': 90, 'ema20': 95, 'ema50': 100, 'atr': 5,
            'adx': 25, 'plus_di': 28, 'minus_di': 15, 'rsi': 50, 'support': 85,
        }
        result = es.build_entry_setup(technicals)
        self.assertIn('confirmed_uptrend', result['reason'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
