import os
import sys
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fundamentals_research.services import stock_chart as sc


def _ts(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp())


class TestGetCandles(unittest.TestCase):
    def setUp(self):
        import screener.fyers_client

    def test_invalid_timeframe_returns_error_not_crash(self):
        result = sc.get_candles('RELIANCE', timeframe='3m')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['reason'], 'invalid_timeframe')

    def test_not_authenticated_returns_clear_error(self):
        with patch('screener.fyers_client.is_authenticated', return_value=False):
            result = sc.get_candles('RELIANCE', timeframe='1d')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['reason'], 'not_authenticated')
        self.assertNotIn('candles', result)

    def test_rate_limited_returns_clear_error(self):
        with patch('screener.fyers_client.is_authenticated', return_value=True), \
             patch('screener.fyers_client._rate_limited_now', return_value=True):
            result = sc.get_candles('RELIANCE', timeframe='1d')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['reason'], 'rate_limited')

    def test_fyers_error_status_returns_no_data_not_fabricated(self):
        with patch('screener.fyers_client.is_authenticated', return_value=True), \
             patch('screener.fyers_client._rate_limited_now', return_value=False), \
             patch('screener.fyers_client.get_history', return_value={'s': 'error'}):
            result = sc.get_candles('RELIANCE', timeframe='1d')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['reason'], 'no_data')
        self.assertNotIn('candles', result)

    def test_fetch_exception_returns_error_not_crash(self):
        with patch('screener.fyers_client.is_authenticated', return_value=True), \
             patch('screener.fyers_client._rate_limited_now', return_value=False), \
             patch('screener.fyers_client.get_history', side_effect=RuntimeError("boom")):
            result = sc.get_candles('RELIANCE', timeframe='1d')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['reason'], 'fetch_failed')

    def test_successful_daily_fetch_shapes_candles_correctly(self):
        raw = {'s': 'ok', 'candles': [
            [_ts(2026, 9, 20), 100.0, 105.0, 99.0, 103.0, 50000],
            [_ts(2026, 9, 21), 103.0, 108.0, 102.0, 107.0, 60000],
        ]}
        with patch('screener.fyers_client.is_authenticated', return_value=True), \
             patch('screener.fyers_client._rate_limited_now', return_value=False), \
             patch('screener.fyers_client.get_history', return_value=raw):
            result = sc.get_candles('RELIANCE', timeframe='1d')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(len(result['candles']), 2)
        self.assertEqual(result['candles'][0]['open'], 100.0)
        self.assertEqual(result['latest_price'], 107.0)
        self.assertEqual(result['resolution_used'], 'D')

    def test_correct_fyers_symbol_and_resolution_sent_for_each_timeframe(self):
        with patch('screener.fyers_client.is_authenticated', return_value=True), \
             patch('screener.fyers_client._rate_limited_now', return_value=False), \
             patch('screener.fyers_client.get_history', return_value=None) as mock_hist:
            sc.get_candles('pnb', timeframe='5m')
        call_args, call_kwargs = mock_hist.call_args
        self.assertEqual(call_args[0], 'NSE:PNB-EQ')  # uppercased, correct Fyers equity format
        self.assertEqual(call_kwargs['resolution'], '5')  # confirmed real Fyers code, not '5m'


class TestAggregateToWeekly(unittest.TestCase):
    def test_hand_verified_single_week_aggregation(self):
        # A Mon-Wed run, all in the same ISO week
        daily = [
            {'time': _ts(2026, 9, 21), 'open': 100, 'high': 105, 'low': 98, 'close': 102, 'volume': 1000},   # Mon
            {'time': _ts(2026, 9, 22), 'open': 102, 'high': 110, 'low': 101, 'close': 108, 'volume': 1500},  # Tue
            {'time': _ts(2026, 9, 23), 'open': 108, 'high': 109, 'low': 95, 'close': 97, 'volume': 2000},    # Wed
        ]
        weekly = sc._aggregate_to_weekly(daily)
        self.assertEqual(len(weekly), 1)
        w = weekly[0]
        self.assertEqual(w['open'], 100)     # Monday's open
        self.assertEqual(w['close'], 97)     # Wednesday's close
        self.assertEqual(w['high'], 110)     # max across all three days
        self.assertEqual(w['low'], 95)       # min across all three days
        self.assertEqual(w['volume'], 4500)  # sum

    def test_two_separate_weeks_produce_two_bars(self):
        daily = [
            {'time': _ts(2026, 9, 21), 'open': 100, 'high': 105, 'low': 98, 'close': 102, 'volume': 1000},   # week 1
            {'time': _ts(2026, 9, 28), 'open': 103, 'high': 106, 'low': 100, 'close': 104, 'volume': 1200},  # week 2
        ]
        weekly = sc._aggregate_to_weekly(daily)
        self.assertEqual(len(weekly), 2)

    def test_empty_input_returns_empty_not_crash(self):
        self.assertEqual(sc._aggregate_to_weekly([]), [])

    def test_weekly_status_reason_when_aggregation_yields_nothing(self):
        with patch('screener.fyers_client.is_authenticated', return_value=True), \
             patch('screener.fyers_client._rate_limited_now', return_value=False), \
             patch('screener.fyers_client.get_history', return_value={'s': 'ok', 'candles': []}):
            result = sc.get_candles('RELIANCE', timeframe='1w')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['reason'], 'no_data')


if __name__ == '__main__':
    unittest.main(verbosity=2)
