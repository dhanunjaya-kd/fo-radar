"""
backend/fundamentals_research/services/stock_chart.py

Sep 26 2026. Real OHLCV candle fetching for the Fundamental Research
page's chart. Reuses the EXACT proven pattern from screener/views.py's
own OptionHistoryView (auth check, rate-limit check, get_history()
call, resp['s']=='ok' status check) rather than inventing a new one --
that endpoint is real, working, tested-in-production code for this
same underlying Fyers call.

Confirmed real Fyers resolution codes (read directly from
OptionHistoryView's own docstring, not guessed): "5"/"15"/"30"/"60"
for minute candles, "D" for daily. No native weekly resolution is used
anywhere in this project -- "1W" here is built by aggregating daily
candles, a standard, well-defined technique, rather than risking an
unverified Fyers resolution string.

No live/streaming data -- confirmed during the earlier Gamma parity
work that this project has no WebSocket infrastructure anywhere, only
polling. This module is honest about that: every response carries a
real `as_of` timestamp from the actual last candle, never a fabricated
"live" label.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

logger = logging.getLogger('fundamentals_research.stock_chart')

# Sep 27 2026 addition, from investigating a real rate-limit report:
# confirmed via _call()'s own code that Fyers' circuit breaker is a
# genuine, account-wide, shared trip -- not a bug in this file. But
# this endpoint had NO caching at all (unlike technical_analysis.py's
# day-scoped cache), meaning every page load AND every timeframe
# button click fired a fresh Fyers call, adding avoidable pressure on
# top of this app's already-heavy background workers (breadth
# snapshots, Gamma zone warmup) competing for the same account-wide
# budget. Short TTL for intraday timeframes (they genuinely move) and
# a longer, day-scoped TTL for 1d/1w (matching this project's own
# established convention for daily bars).
_candle_cache = {}  # {(symbol, timeframe): {'expires_at': monotonic_time, 'data': result}}
_INTRADAY_CACHE_SECONDS = 300  # 5 minutes -- short enough to stay current, long enough to absorb repeated clicks

# Sep 27 2026: real, confirmed limits from Fyers' own V3 docs (via
# their community forum quoting the docs directly, not guessed):
# intraday resolutions cap at 100 days per single request; daily (1D)
# caps at 366 days per single request. The OLD lookback values below
# (5/10/30 days intraday, 250 days daily) were copied from
# technical_analysis.py's narrow "just enough for one EMA200
# calculation" need, not chosen for a rich, explorable chart -- they
# left most of what Fyers actually supports on the table. Intraday now
# requests close to its real 100-day cap in a single call. Daily/weekly
# target 3 years, which EXCEEDS the 366-day single-request cap, so
# they're fetched via _fetch_daily_batched() below rather than one
# call -- a single call for 3 years would have silently failed or been
# truncated by Fyers' own limit, which is likely why the weekly view
# was ALSO short despite requesting 1095 days.
_MAX_DAYS_PER_REQUEST = {'intraday': 100, 'daily': 366}

# timeframe -> (fyers_resolution, total_calendar_days_wanted)
# total_days here is the OVERALL span wanted, not a per-request size --
# daily/weekly reach it via batched requests, intraday in one request
# (100 days is already the provider's own per-request ceiling).
_TIMEFRAME_MAP = {
    '5m': ('5', 100),
    '15m': ('15', 100),
    '1h': ('60', 100),
    '1d': ('D', 365 * 3),
    '1w': ('D', 365 * 3),  # fetch 3 years of daily bars, then aggregate to weekly below
}

# Sep 27 2026: real, confirmed labeling bug -- 'as_of' was showing the
# LAST candle's START timestamp (e.g. "3:15pm" for a 15m candle
# covering 3:15-3:30), understating freshness by a full candle-width.
# Fixed for intraday timeframes, where the correction is simple and
# well-understood (candle_start + its own known duration). Deliberately
# NOT applied to 1d/1w -- Fyers' exact daily-candle timestamp
# convention (midnight UTC? midnight IST? something else?) was never
# independently verified in this project, and guessing at an offset
# there risks introducing a new timezone bug rather than fixing a
# labeling one.
_INTRADAY_DURATION_SECONDS = {'5m': 5 * 60, '15m': 15 * 60, '1h': 60 * 60}


def _as_of_timestamp(candle_start_time: int, timeframe: str) -> int:
    return candle_start_time + _INTRADAY_DURATION_SECONDS.get(timeframe, 0)


def _fetch_fyers_history_batched(get_history_fn, fyers_symbol: str, resolution: str, total_days: int, max_days_per_request: int) -> list:
    """
    Fetches up to `total_days` of history by walking backward from
    today in chunks no larger than `max_days_per_request` (Fyers'
    documented per-request cap for this resolution class), issuing
    multiple sequential requests when total_days exceeds that cap.
    Stops early if a request returns no candles (very likely means
    the symbol's actual listing/earliest-available date has been
    reached -- no point requesting further back). Deduplicates by
    timestamp (chunk boundaries can overlap by a day) and returns
    candles sorted chronologically.

    Raises on the underlying get_history_fn's own exceptions --
    callers catch this exactly as the old single-request code did.
    """
    all_candles_by_time = {}
    range_to = datetime.now().date()
    remaining_days = total_days

    while remaining_days > 0:
        chunk_days = min(remaining_days, max_days_per_request)
        range_from = range_to - timedelta(days=chunk_days)

        resp = get_history_fn(fyers_symbol, resolution=resolution, range_from=str(range_from), range_to=str(range_to))
        if not resp or resp.get('s') != 'ok' or not resp.get('candles'):
            break  # no more data available further back (e.g. symbol's listing date reached)

        for c in resp['candles']:
            all_candles_by_time[int(c[0])] = c  # dict keyed by timestamp -- naturally deduplicates any chunk-boundary overlap

        remaining_days -= chunk_days
        range_to = range_from  # next chunk continues immediately before this one

    return sorted(all_candles_by_time.values(), key=lambda c: c[0])


# Oct 2 2026: index symbols for the chart workspace's compare panes (NIFTY next to a stock). Same Fyers index
# symbols screener/views.py's FYERS_INDEX_SYMBOLS already uses; yfinance's own index tickers for the fallback.
# Indices carry no volume, so the volume strip is simply empty for them.
_INDEX_FYERS = {'NIFTY': 'NSE:NIFTY50-INDEX', 'NIFTY50': 'NSE:NIFTY50-INDEX', 'BANKNIFTY': 'NSE:NIFTYBANK-INDEX',
                'NIFTYBANK': 'NSE:NIFTYBANK-INDEX', 'SENSEX': 'BSE:SENSEX-INDEX'}
_INDEX_YFINANCE = {'NIFTY': '^NSEI', 'NIFTY50': '^NSEI', 'BANKNIFTY': '^NSEBANK', 'NIFTYBANK': '^NSEBANK', 'SENSEX': '^BSESN'}


def fyers_symbol_for(symbol: str) -> str:
    s = symbol.strip().upper()
    return _INDEX_FYERS.get(s) or f"NSE:{s}-EQ"


def yfinance_symbol_for(symbol: str) -> str:
    s = symbol.strip().upper()
    return _INDEX_YFINANCE.get(s) or f"{s}.NS"


def get_candles(symbol: str, timeframe: str = '1d') -> Dict[str, Any]:
    """
    Returns {'status': 'ok', 'candles': [...], 'as_of': ..., 'resolution_used': ...}
    or {'status': 'error', 'reason': <code>, 'message': <human text>}.
    Never returns fabricated candles -- every error path returns
    status='error' with no 'candles' key at all, so a caller can't
    accidentally render a placeholder as if it were real data.

    reason codes: 'invalid_timeframe', 'not_authenticated', 'rate_limited',
    'fetch_failed', 'no_data'.

    Sep 27 2026: now cached (see _candle_cache above -- real, confirmed
    fix for unnecessary repeated Fyers calls), and falls back to
    yfinance (a genuine, already-proven data source in this project --
    see yfinance_fallback.py) when Fyers is rate-limited or not
    authenticated, per explicit instruction to use a legitimate
    existing alternative source rather than leave the chart blank.
    Fyers stays PRIMARY -- yfinance is only tried after a real Fyers
    failure, never preferred over it.
    """
    if timeframe not in _TIMEFRAME_MAP:
        return {'status': 'error', 'reason': 'invalid_timeframe', 'message': f"Unsupported timeframe '{timeframe}'. Use one of: {', '.join(_TIMEFRAME_MAP.keys())}."}

    import time as _time
    cache_key = (symbol.upper(), timeframe)
    cached = _candle_cache.get(cache_key)
    if cached and cached['expires_at'] > _time.monotonic():
        return cached['data']

    result = _get_candles_from_fyers(symbol, timeframe)

    if result['status'] == 'error' and result['reason'] in ('rate_limited', 'not_authenticated'):
        logger.info(f"Fyers unavailable for {symbol} chart ({result['reason']}) -- trying yfinance fallback.")
        yf_result = _get_candles_from_yfinance(symbol, timeframe)
        if yf_result is not None:
            result = yf_result

    if result['status'] == 'ok':
        ttl = _INTRADAY_CACHE_SECONDS if timeframe in ('5m', '15m', '1h') else 24 * 3600
        _candle_cache[cache_key] = {'expires_at': _time.monotonic() + ttl, 'data': result}

    return result


def _get_candles_from_fyers(symbol: str, timeframe: str) -> Dict[str, Any]:
    try:
        from screener.fyers_client import is_authenticated, _rate_limited_now, get_history
    except ImportError as e:
        logger.warning(f"Could not import Fyers client: {e}")
        return {'status': 'error', 'reason': 'fetch_failed', 'message': 'Chart data service unavailable.'}

    if not is_authenticated():
        return {'status': 'error', 'reason': 'not_authenticated', 'message': 'Not authenticated with Fyers -- no chart data available.'}

    if _rate_limited_now():
        return {'status': 'error', 'reason': 'rate_limited', 'message': 'Fyers is currently rate-limited (account-wide) -- this recovers on its own, try again shortly.'}

    resolution, total_days = _TIMEFRAME_MAP[timeframe]
    fyers_symbol = fyers_symbol_for(symbol)
    is_intraday = timeframe in ('5m', '15m', '1h')
    max_days_per_request = _MAX_DAYS_PER_REQUEST['intraday' if is_intraday else 'daily']

    try:
        raw_candles = _fetch_fyers_history_batched(get_history, fyers_symbol, resolution, total_days, max_days_per_request)
    except Exception as e:
        logger.warning(f"Candle fetch failed for {symbol} ({timeframe}): {e}")
        return {'status': 'error', 'reason': 'fetch_failed', 'message': f'History fetch failed: {e}'}

    if not raw_candles:
        return {'status': 'error', 'reason': 'no_data', 'message': f'No real historical data available for {symbol} right now.'}

    candles = [
        {'time': int(c[0]), 'open': float(c[1]), 'high': float(c[2]), 'low': float(c[3]), 'close': float(c[4]), 'volume': float(c[5])}
        for c in raw_candles
    ]

    if timeframe == '1w':
        candles = _aggregate_to_weekly(candles)
        if not candles:
            return {'status': 'error', 'reason': 'no_data', 'message': f'Not enough daily data to build weekly candles for {symbol}.'}

    latest = candles[-1]
    return {
        'status': 'ok',
        'symbol': symbol.upper(),
        'timeframe': timeframe,
        'candles': candles,
        'as_of': _as_of_timestamp(latest['time'], timeframe),
        'latest_price': latest['close'],
        'resolution_used': resolution,
        'earliest_candle_time': candles[0]['time'],
        'latest_candle_time': latest['time'],
    }


# timeframe -> (yfinance_interval, yfinance_period). yfinance's own
# documented interval/period values -- confirmed via this project's
# already-working yfinance_fallback.py that the package installs and
# runs cleanly here; these specific interval strings are yfinance's
# own standard codes, not guessed.
_YFINANCE_TIMEFRAME_MAP = {
    '5m': ('5m', '5d'), '15m': ('15m', '1mo'), '1h': ('60m', '3mo'),
    '1d': ('1d', '1y'), '1w': ('1wk', '5y'),
}


def _get_candles_from_yfinance(symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
    """
    Real fallback, only tried after a genuine Fyers failure (rate-
    limited or not authenticated) -- never preferred over Fyers.
    Returns None (not an error dict) if yfinance itself has no data
    either, so the caller keeps the ORIGINAL Fyers error message
    (more specific and more actionable) rather than a generic one.
    """
    try:
        import yfinance as yf
    except ImportError:
        return None

    interval, period = _YFINANCE_TIMEFRAME_MAP[timeframe]
    try:
        ticker = yf.Ticker(yfinance_symbol_for(symbol))
        df = ticker.history(period=period, interval=interval)
    except Exception as e:
        logger.warning(f"yfinance candle fallback failed for {symbol}: {e}")
        return None

    if df is None or df.empty:
        return None

    candles = [
        {'time': int(idx.timestamp()), 'open': float(row['Open']), 'high': float(row['High']),
         'low': float(row['Low']), 'close': float(row['Close']), 'volume': float(row['Volume'])}
        for idx, row in df.iterrows()
    ]
    latest = candles[-1]
    return {
        'status': 'ok', 'symbol': symbol.upper(), 'timeframe': timeframe, 'candles': candles,
        'as_of': _as_of_timestamp(latest['time'], timeframe), 'latest_price': latest['close'], 'resolution_used': f'yfinance:{interval}',
        'earliest_candle_time': candles[0]['time'], 'latest_candle_time': latest['time'],
        'source': 'yfinance',  # distinct from a Fyers-sourced response -- frontend can label this differently if it chooses to
    }


def _aggregate_to_weekly(daily_candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Standard OHLCV weekly aggregation from real daily candles:
    open = first trading day's open, close = last trading day's close,
    high = max of the week's highs, low = min of the week's lows,
    volume = sum of the week's volumes. Weeks are grouped by ISO week
    (Mon-Sun), keyed off each candle's own real timestamp -- no
    invented calendar assumptions, no fabricated bars for weeks with
    no trading data (a week simply doesn't appear if no daily candles
    fall in it).
    """
    if not daily_candles:
        return []

    weeks: Dict[tuple, List[Dict[str, Any]]] = {}
    for c in daily_candles:
        dt = datetime.fromtimestamp(c['time'], tz=timezone.utc)
        iso_year, iso_week, _ = dt.isocalendar()
        weeks.setdefault((iso_year, iso_week), []).append(c)

    weekly = []
    for key in sorted(weeks.keys()):
        bucket = weeks[key]
        bucket.sort(key=lambda c: c['time'])
        weekly.append({
            'time': bucket[0]['time'],
            'open': bucket[0]['open'],
            'high': max(c['high'] for c in bucket),
            'low': min(c['low'] for c in bucket),
            'close': bucket[-1]['close'],
            'volume': sum(c['volume'] for c in bucket),
        })
    return weekly
