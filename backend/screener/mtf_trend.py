"""
screener/mtf_trend.py

Sep 9 2026: real multi-timeframe trend confirmation (5m/15m/1h) from
actual completed Fyers candles.

Reuses, rather than reinvents, three pieces of already-proven
infrastructure:

1. fyers_client.get_history()'s intraday resolution convention --
   "5"/"15"/"60" and the 5-calendar-day lookback window -- copied
   directly from views.py's OptionHistoryView, an existing endpoint
   already using these exact resolutions in production. Not a fresh
   guess at Fyers' resolution strings.

2. The candle-sort fix already discovered and applied in that same
   view: "Fyers' raw candle order isn't guaranteed to be chronological
   here" -- this file sorts by timestamp too, for the same reason
   (both determining which candle is still forming, and running trend
   classification, depend on real chronological order).

3. quality_engine.detect_price_structure() for the actual trend
   classification (HH/HL vs LH/LL + close-confirmed breakout) --
   already built and tested for daily-timeframe stock price structure
   earlier this project; the underlying logic (given a chronological
   OHLC sequence, is structure bullish/bearish/neutral) doesn't care
   what timeframe the bars represent. Reused verbatim, not
   reimplemented for intraday.

STILL-FORMING CANDLE EXCLUSION (the spec's explicit requirement): a
candle starting at timestamp `ts` covers [ts, ts + resolution*60). It
is only complete once real wall-clock time has passed that window.
The most recent candle Fyers returns during an active session is
therefore usually still forming and is explicitly dropped before any
classification happens -- matching the same principle this project's
daily _cached_history_df() already uses for the current day's row.

CACHING respects real candle completion, not a fixed TTL: cached per
(symbol, resolution) keyed by which candle PERIOD "now" currently
falls in. A second call within the same still-forming period returns
the cached trend with zero new Fyers traffic; once a new period
starts, the next call naturally refetches. This directly implements
the explicit requirement: "5M -> refresh when a new 5M candle
completes" etc.

futures_oi_status-style honesty: every return value is 'BULLISH' /
'BEARISH' / 'NEUTRAL' / None. None always means genuinely unknown
(fetch failed, or not enough completed candles) -- never guessed or
defaulted to NEUTRAL as a stand-in for missing data.
"""
import time
import threading
from datetime import datetime, timedelta

RESOLUTIONS = {"5m": ("5", 5), "15m": ("15", 15), "1h": ("60", 60)}
LOOKBACK_DAYS = 5  # same window views.py's OptionHistoryView already uses for these exact resolutions
MIN_COMPLETED_CANDLES = 15  # detect_price_structure() itself requires lookback+2; this is comfortably above that floor

_cache_lock = threading.Lock()
_mtf_cache = {}  # {(symbol, resolution_key): {'period_key': ..., 'trend': ..., 'fetched_at': ...}}


def _candle_period_key(resolution_minutes, now=None):
    """
    Which candle period `now` currently falls inside, for a given
    resolution -- e.g. resolution_minutes=5 at 10:23 -> period key
    covering 10:20-10:25 (the period still forming right now). Used
    as the cache key so the cache naturally invalidates exactly when
    a new candle of that resolution starts, rather than guessing a
    TTL that drifts out of sync with real candle boundaries.
    """
    now = now or datetime.now()
    total_minutes = now.hour * 60 + now.minute
    bucket_start = (total_minutes // resolution_minutes) * resolution_minutes
    return f"{now.date()}_{bucket_start}"


def _fetch_completed_candles(symbol, resolution_str, resolution_minutes):
    """
    Real Fyers intraday fetch -- same resolution convention and
    5-day lookback window already proven in views.py's
    OptionHistoryView, same [ts, o, h, l, c, v] candle shape, same
    chronological sort fix. Drops any candle whose period hasn't
    fully elapsed yet. Returns a list of (close, high, low) tuples,
    oldest-first, completed candles only -- or None on any failure
    (no live response, malformed data, or no candles at all).
    """
    from .fyers_client import get_history

    range_to = datetime.now().date()
    range_from = range_to - timedelta(days=LOOKBACK_DAYS)
    try:
        resp = get_history(symbol, resolution=resolution_str,
                            range_from=str(range_from), range_to=str(range_to))
    except Exception as e:
        print(f"[MTFTrend] {symbol} {resolution_str} fetch failed: {e}")
        return None

    if not resp or resp.get("s") != "ok" or not resp.get("candles"):
        return None

    candles = resp.get("candles", [])
    parsed = [c for c in candles if len(c) >= 6]
    if not parsed:
        return None
    parsed.sort(key=lambda c: c[0])  # same real ordering bug already found and fixed for this exact API elsewhere in this project

    now_epoch = time.time()
    period_seconds = resolution_minutes * 60
    completed = [c for c in parsed if (c[0] + period_seconds) <= now_epoch]

    if len(completed) < MIN_COMPLETED_CANDLES:
        return None

    return [(c[4], c[2], c[3]) for c in completed]  # (close, high, low), oldest-first


def _classify_trend_from_candles(candles):
    """
    Reuses quality_engine.detect_price_structure() -- same HH/HL vs
    LH/LL + close-confirmed-breakout logic already built and tested
    for daily stock price structure. Maps its 4-state output onto the
    simpler BULLISH/BEARISH/NEUTRAL/None this module exposes.
    """
    if not candles:
        return None
    from . import quality_engine as qe

    closes = [c[0] for c in candles]
    highs = [c[1] for c in candles]
    lows = [c[2] for c in candles]
    result = qe.detect_price_structure(closes, highs, lows, lookback=min(20, len(candles) - 2))

    mapping = {"BULLISH_STRUCTURE": "BULLISH", "BEARISH_STRUCTURE": "BEARISH", "NEUTRAL": "NEUTRAL"}
    return mapping.get(result["state"])  # INSUFFICIENT_DATA (or any unmapped state) -> None


def get_completed_candle_trend(symbol, timeframe, force_refresh=False):
    """
    Real trend for `symbol` (a plain Fyers equity symbol, e.g.
    "NSE:WIPRO-EQ") at `timeframe` ('5m'/'15m'/'1h'), from actual
    completed candles only. Cached per real candle-period boundary --
    see module docstring. Returns 'BULLISH'/'BEARISH'/'NEUTRAL'/None.
    """
    if timeframe not in RESOLUTIONS:
        return None
    resolution_str, resolution_minutes = RESOLUTIONS[timeframe]
    period_key = _candle_period_key(resolution_minutes)
    cache_key = (symbol, timeframe)

    with _cache_lock:
        cached = _mtf_cache.get(cache_key)
        if not force_refresh and cached and cached["period_key"] == period_key:
            return cached["trend"]

    candles = _fetch_completed_candles(symbol, resolution_str, resolution_minutes)
    trend = _classify_trend_from_candles(candles)

    with _cache_lock:
        _mtf_cache[cache_key] = {"period_key": period_key, "trend": trend, "fetched_at": time.monotonic()}
    return trend


def get_mtf_trend(symbol):
    """
    All three timeframes for one symbol, each independently cached
    per its own real candle-period boundary. Returns {'mtf_5m',
    'mtf_15m', 'mtf_1h'} -- each 'BULLISH'/'BEARISH'/'NEUTRAL'/None.
    """
    return {
        "mtf_5m": get_completed_candle_trend(symbol, "5m"),
        "mtf_15m": get_completed_candle_trend(symbol, "15m"),
        "mtf_1h": get_completed_candle_trend(symbol, "1h"),
    }
