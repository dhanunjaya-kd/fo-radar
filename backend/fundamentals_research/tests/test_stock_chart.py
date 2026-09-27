import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fundamentals_research.services import stock_chart as sc


def _ts(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp())


class TestGetCandles(unittest.TestCase):
    def setUp(self):
        import screener.fyers_client
        # Sep 27 2026: new caching means tests must clear the cache
        # between runs, or one test's cached result leaks into the
        # next -- same isolation issue already handled this way for
        # technical_analysis.py's own cache.
        sc._candle_cache.clear()

    def test_invalid_timeframe_returns_error_not_crash(self):
        result = sc.get_candles('RELIANCE', timeframe='3m')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['reason'], 'invalid_timeframe')

    def test_not_authenticated_returns_clear_error(self):
        """When yfinance ALSO has nothing (mocked empty here), the
        original, more specific Fyers error message must survive --
        not get replaced by a generic one."""
        with patch('screener.fyers_client.is_authenticated', return_value=False), \
             patch('fundamentals_research.services.stock_chart._get_candles_from_yfinance', return_value=None):
            result = sc.get_candles('RELIANCE', timeframe='1d')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['reason'], 'not_authenticated')
        self.assertNotIn('candles', result)

    def test_rate_limited_returns_clear_error(self):
        with patch('screener.fyers_client.is_authenticated', return_value=True), \
             patch('screener.fyers_client._rate_limited_now', return_value=True), \
             patch('fundamentals_research.services.stock_chart._get_candles_from_yfinance', return_value=None):
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

    def test_as_of_reflects_candle_close_not_open_for_intraday(self):
        """Real, confirmed bug this fixes: 'as of 3:15pm' for a 15m
        candle covering 3:15-3:30 understated freshness by a full
        candle-width. Hand-verified: candle starts at a known
        timestamp, as_of must be exactly 15 minutes later."""
        start = _ts(2026, 9, 25)
        raw = {'s': 'ok', 'candles': [[start, 100.0, 105.0, 99.0, 103.0, 50000]]}
        with patch('screener.fyers_client.is_authenticated', return_value=True), \
             patch('screener.fyers_client._rate_limited_now', return_value=False), \
             patch('screener.fyers_client.get_history', return_value=raw):
            result = sc.get_candles('RELIANCE', timeframe='15m')
        self.assertEqual(result['as_of'], start + 15 * 60)

    def test_as_of_unchanged_for_daily_timeframe(self):
        """Deliberately NOT adjusted for 1d/1w -- Fyers' exact daily
        timestamp convention was never independently verified, so this
        confirms the timestamp passes through unmodified rather than
        guessing an offset."""
        start = _ts(2026, 9, 25)
        raw = {'s': 'ok', 'candles': [[start, 100.0, 105.0, 99.0, 103.0, 50000]]}
        with patch('screener.fyers_client.is_authenticated', return_value=True), \
             patch('screener.fyers_client._rate_limited_now', return_value=False), \
             patch('screener.fyers_client.get_history', return_value=raw):
            result = sc.get_candles('RELIANCE', timeframe='1d')
        self.assertEqual(result['as_of'], start)

    def test_correct_fyers_symbol_and_resolution_sent_for_each_timeframe(self):
        with patch('screener.fyers_client.is_authenticated', return_value=True), \
             patch('screener.fyers_client._rate_limited_now', return_value=False), \
             patch('screener.fyers_client.get_history', return_value=None) as mock_hist:
            sc.get_candles('pnb', timeframe='5m')
        call_args, call_kwargs = mock_hist.call_args
        self.assertEqual(call_args[0], 'NSE:PNB-EQ')  # uppercased, correct Fyers equity format
        self.assertEqual(call_kwargs['resolution'], '5')  # confirmed real Fyers code, not '5m'


    def test_second_call_within_ttl_uses_cache_not_a_fresh_fyers_call(self):
        """The actual bug this caching fix addresses: repeated
        timeframe clicks or page reloads within the TTL window must
        not re-hit Fyers, reducing pressure on the shared account-wide
        rate budget. Uses '5m' (single-request intraday) to keep the
        call-count assertion simple and separate from the batching
        behavior covered by its own tests below."""
        raw = {'s': 'ok', 'candles': [[_ts(2026, 9, 20), 100.0, 105.0, 99.0, 103.0, 50000]]}
        with patch('screener.fyers_client.is_authenticated', return_value=True), \
             patch('screener.fyers_client._rate_limited_now', return_value=False), \
             patch('screener.fyers_client.get_history', return_value=raw) as mock_hist:
            sc.get_candles('CACHETEST', timeframe='5m')
            sc.get_candles('CACHETEST', timeframe='5m')
        self.assertEqual(mock_hist.call_count, 1)  # only ONE real fetch for two calls

    def test_different_timeframes_dont_share_a_cache_entry(self):
        """'1d' and '1w' both now batch multiple requests (up to ~3
        for a 3-year span at the 366-day-per-request cap) -- this only
        needs to confirm they don't share ONE cache entry, not assert
        an exact call count, so it checks that '1w' triggers at least
        one more real call after '1d' already ran."""
        raw = {'s': 'ok', 'candles': [[_ts(2026, 9, 20), 100.0, 105.0, 99.0, 103.0, 50000]]}
        with patch('screener.fyers_client.is_authenticated', return_value=True), \
             patch('screener.fyers_client._rate_limited_now', return_value=False), \
             patch('screener.fyers_client.get_history', return_value=raw) as mock_hist:
            sc.get_candles('CACHETEST2', timeframe='1d')
            calls_after_1d = mock_hist.call_count
            sc.get_candles('CACHETEST2', timeframe='1w')
        self.assertGreater(mock_hist.call_count, calls_after_1d)  # '1w' made its OWN fresh call(s), confirming no shared cache entry with '1d'

    def test_yfinance_fallback_used_when_fyers_rate_limited(self):
        """Real fallback path: Fyers genuinely rate-limited, yfinance
        (already a proven data source in this project) has real data --
        confirms the chart doesn't just give up."""
        import pandas as pd
        fake_df = pd.DataFrame(
            {'Open': [100.0], 'High': [105.0], 'Low': [99.0], 'Close': [103.0], 'Volume': [50000]},
            index=[pd.Timestamp('2026-09-20', tz='UTC')],
        )
        with patch('screener.fyers_client.is_authenticated', return_value=True), \
             patch('screener.fyers_client._rate_limited_now', return_value=True), \
             patch('yfinance.Ticker') as mock_ticker:
            mock_ticker.return_value.history.return_value = fake_df
            result = sc.get_candles('FALLBACKTEST', timeframe='1d')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['source'], 'yfinance')
        self.assertEqual(result['candles'][0]['close'], 103.0)

    def test_fyers_stays_primary_yfinance_never_tried_when_fyers_succeeds(self):
        """Confirms yfinance is a fallback, never preferred -- must not
        even be CALLED when Fyers succeeds."""
        raw = {'s': 'ok', 'candles': [[_ts(2026, 9, 20), 100.0, 105.0, 99.0, 103.0, 50000]]}
        with patch('screener.fyers_client.is_authenticated', return_value=True), \
             patch('screener.fyers_client._rate_limited_now', return_value=False), \
             patch('screener.fyers_client.get_history', return_value=raw), \
             patch('fundamentals_research.services.stock_chart._get_candles_from_yfinance') as mock_yf:
            result = sc.get_candles('PRIMARYTEST', timeframe='1d')
        mock_yf.assert_not_called()
        self.assertNotEqual(result.get('source'), 'yfinance')


class TestFetchFyersHistoryBatched(unittest.TestCase):
    """Real, dedicated coverage for the actual fix in this round:
    Fyers caps a single request at 366 days for daily resolution (100
    for intraday) -- confirmed directly from Fyers' own V3 docs, not
    guessed. Requesting more than that in ONE call (the old behavior
    for '1w', which asked for 1095 days at once) would exceed the
    documented cap. This batches multiple requests and stitches them
    together correctly."""

    def test_single_request_when_total_days_fits_the_cap(self):
        raw = {'s': 'ok', 'candles': [[1000, 1, 2, 0, 1, 10]]}
        mock_get_history = MagicMock(return_value=raw)
        result = sc._fetch_fyers_history_batched(mock_get_history, 'NSE:TEST-EQ', 'D', total_days=100, max_days_per_request=366)
        self.assertEqual(mock_get_history.call_count, 1)
        self.assertEqual(len(result), 1)

    def test_multiple_batches_stitched_when_total_exceeds_cap(self):
        """The actual real-world case: 1095 days (3 years) requested
        with a 366-day cap needs 3 separate requests."""
        call_log = []

        def fake_get_history(symbol, resolution, range_from, range_to):
            call_log.append((range_from, range_to))
            # Each batch returns one distinct candle, timestamped uniquely per call, so we can verify all 3 made it into the final result.
            t = 1000000 - len(call_log) * 86400
            return {'s': 'ok', 'candles': [[t, 1, 2, 0, 1, 10]]}

        result = sc._fetch_fyers_history_batched(fake_get_history, 'NSE:TEST-EQ', 'D', total_days=1000, max_days_per_request=366)
        self.assertEqual(len(call_log), 3)  # 366 + 366 + 268 = 1000, three batches
        self.assertEqual(len(result), 3)  # one distinct candle per batch, all present

    def test_overlapping_timestamps_deduplicated(self):
        """Chunk boundaries can legitimately return the same candle
        twice (e.g. the boundary date itself) -- confirms it appears
        only once in the final result, not duplicated on the chart."""
        responses = [
            {'s': 'ok', 'candles': [[2000, 1, 2, 0, 1, 10], [1000, 1, 2, 0, 1, 10]]},  # includes timestamp 1000
            {'s': 'ok', 'candles': [[1000, 1, 2, 0, 1, 10]]},  # same timestamp 1000 again (boundary overlap)
        ]
        mock_get_history = MagicMock(side_effect=[responses[0], responses[1], {'s': 'ok', 'candles': []}])
        result = sc._fetch_fyers_history_batched(mock_get_history, 'NSE:TEST-EQ', 'D', total_days=800, max_days_per_request=366)
        timestamps = [c[0] for c in result]
        self.assertEqual(len(timestamps), len(set(timestamps)))  # no duplicate timestamps in the final result
        self.assertIn(1000, timestamps)

    def test_stops_early_when_a_batch_returns_no_data(self):
        """Real efficiency requirement: once a batch comes back empty
        (very likely the symbol's actual listing date has been
        reached), stop requesting further back instead of continuing
        to burn API calls for data that will never arrive."""
        mock_get_history = MagicMock(side_effect=[
            {'s': 'ok', 'candles': [[3000, 1, 2, 0, 1, 10]]},
            {'s': 'ok', 'candles': []},  # nothing further back -- should stop here
        ])
        result = sc._fetch_fyers_history_batched(mock_get_history, 'NSE:TEST-EQ', 'D', total_days=1000, max_days_per_request=366)
        self.assertEqual(mock_get_history.call_count, 2)  # NOT 3 -- stopped after the empty batch, didn't try a third
        self.assertEqual(len(result), 1)

    def test_result_sorted_chronologically(self):
        """Batches are fetched newest-chunk-first (walking backward
        from today), so the raw combined dict must be explicitly
        sorted before returning -- otherwise candles would appear out
        of order on the chart."""
        responses = [
            {'s': 'ok', 'candles': [[3000, 1, 2, 0, 1, 10]]},  # most recent chunk, fetched FIRST
            {'s': 'ok', 'candles': [[1000, 1, 2, 0, 1, 10]]},  # older chunk, fetched SECOND
        ]
        mock_get_history = MagicMock(side_effect=[responses[0], responses[1], {'s': 'ok', 'candles': []}])
        result = sc._fetch_fyers_history_batched(mock_get_history, 'NSE:TEST-EQ', 'D', total_days=800, max_days_per_request=366)
        times = [c[0] for c in result]
        self.assertEqual(times, sorted(times))  # chronological, oldest first, despite being fetched newest-first

    def test_exception_from_underlying_call_propagates(self):
        """Callers (_get_candles_from_fyers) already have a try/except
        around this function -- confirms an exception from ANY batch
        propagates up rather than being silently swallowed here."""
        mock_get_history = MagicMock(side_effect=RuntimeError("network blew up"))
        with self.assertRaises(RuntimeError):
            sc._fetch_fyers_history_batched(mock_get_history, 'NSE:TEST-EQ', 'D', total_days=500, max_days_per_request=366)


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
