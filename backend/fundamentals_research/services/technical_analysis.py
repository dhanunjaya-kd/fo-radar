"""
backend/fundamentals_research/services/technical_analysis.py

Sep 26 2026. Reuses screener/views.py's own _compute_indicators()
directly -- confirmed by reading it first that it's a pure function
(pandas Series in, dict out, no side effects), already computing RSI,
EMA20/50/200, ADX+DI, MACD+signal+histogram, support/resistance,
volume average, Bollinger width, historical volatility. Not
reimplemented here; imported and called on one stock's own history
instead of the whole F&O universe it normally runs across.

Deferred (inside-function) import, matching this app's own established
pattern (research_engine.py does the same for the fundamentals/
package) -- avoids a hard import-time dependency on screener's module,
which starts background worker threads at import time; a live request
handler is the right place for this import, not this file's own
top level.

Trend classification below is a fixed, documented rule table -- not an
LLM guess. Matches spec Section 2's own required categories exactly.
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger('fundamentals_research.technical_analysis')

# Sep 26 2026 addition, found during a verification pass: every call
# to get_technical_snapshot() was making a fresh, uncached Fyers call
# -- confirmed by reading _fyers_history_df() directly that it has NO
# internal caching of its own (the caching lives in ITS callers, e.g.
# screener/views.py's _calc_tech() and get_52_week_high_low(), each
# with their own day-scoped cache dict). A UI action as simple as
# clicking "Retry" on just the AI decision summary was re-fetching the
# entire technical snapshot needlessly. Fixed using this project's own
# established convention (a day-scoped {symbol: {'date', 'data'}}
# cache) rather than inventing a different pattern.
_technical_snapshot_cache = {}


def get_technical_snapshot(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Sep 26 2026 REWRITE. The original version of this function had
    THREE real bugs, found by comparing against screener/views.py's
    own proven, working _fyers_history_df() -- confirmed as the root
    cause of "No technical data available" showing for every symbol:
      1. resolution="1D" -- Fyers' API expects exactly "D", not "1D".
         Every other working caller in this project uses "D".
      2. range_from/range_to were never supplied (defaulted to None),
         so the request went out with a null date range -- Fyers'
         API needs real date strings, and this project's own working
         callers always compute and pass them explicitly.
      3. Assumed lowercase DataFrame columns ('close', 'high', ...) --
         the real, established convention in this codebase
         (_fyers_history_df) is capitalized ('Close', 'High', ...).
         Even with bugs 1-2 fixed, this alone would have raised a
         KeyError on the very next line.

    Fixed by reusing _fyers_history_df() directly instead of
    reimplementing history-fetching a second, buggier way -- exactly
    the "reuse existing APIs" instruction this was built against, and
    the reason this rewrite doesn't reintroduce a fourth version of
    the same bug class.

    Day-scoped cached (see _technical_snapshot_cache above) -- added
    in a later verification pass after confirming this was making a
    fresh, uncached Fyers call on every invocation, including simple
    UI actions (a Retry click) that don't need fresh technicals at all.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    cached = _technical_snapshot_cache.get(symbol.upper())
    if cached and cached.get('date') == today_str:
        return cached['data']

    try:
        from screener.views import _fyers_history_df, _compute_indicators
    except ImportError as e:
        logger.warning(f"Could not import screener's indicator engine: {e}")
        return None

    try:
        df = _fyers_history_df(symbol.upper(), days=250)  # 250 calendar days -- enough trading days for EMA200 to compute, matching _compute_indicators' own >=200-bar requirement for that field
    except Exception as e:
        logger.warning(f"Price history fetch failed for {symbol}: {e}")
        return None

    if df is None or len(df) < 20:
        logger.info(f"Insufficient price history for {symbol} ({0 if df is None else len(df)} bars) -- technical snapshot unavailable, not fabricated.")
        return None

    indicators = _compute_indicators(df['Close'], df['High'], df['Low'], df['Volume'])
    if indicators is None:
        logger.info(f"_compute_indicators returned None for {symbol} -- likely a NaN in a computed field; not fabricated.")
        return None

    current_price = float(df['Close'].iloc[-1])
    indicators['current_price'] = current_price
    indicators['as_of_timestamp'] = int(df['ts'].iloc[-1])
    _technical_snapshot_cache[symbol.upper()] = {'date': today_str, 'data': indicators}
    return indicators


def classify_trend(technicals: Dict[str, Any]) -> Dict[str, str]:
    """
    Deterministic classification, per spec Section 2's exact required
    categories:
        Confirmed downtrend / Weakening trend / Possible stabilization /
        Potential recovery setup / Sideways-range-bound / Insufficient data

    Rules are stated explicitly below, not hidden in a scoring
    formula -- every classification traces to specific, visible
    conditions on real indicator values, matching the spec's own
    "explain what each combination means" requirement.
    """
    if not technicals:
        return {'classification': 'Insufficient data', 'reason': 'No technical data available for this symbol.'}

    price = technicals.get('current_price')
    ema20, ema50, ema200 = technicals.get('ema20'), technicals.get('ema50'), technicals.get('ema200')
    rsi = technicals.get('rsi')
    adx = technicals.get('adx')
    plus_di, minus_di = technicals.get('plus_di'), technicals.get('minus_di')

    if price is None or ema20 is None or ema50 is None or rsi is None or adx is None:
        return {'classification': 'Insufficient data', 'reason': 'One or more required indicators unavailable for this symbol.'}

    below_ema20 = price < ema20
    below_ema50 = price < ema50
    below_ema200 = ema200 is not None and price < ema200
    trending_down = adx >= 20 and minus_di is not None and plus_di is not None and minus_di > plus_di
    trending_up = adx >= 20 and minus_di is not None and plus_di is not None and plus_di > minus_di
    weak_trend = adx < 20

    if trending_down and below_ema20 and below_ema50:
        reason = f"Price below both EMA20 ({ema20}) and EMA50 ({ema50}), ADX {adx} with -DI > +DI (confirmed directional selling pressure)."
        return {'classification': 'Confirmed downtrend', 'reason': reason}

    if below_ema20 and below_ema50 and weak_trend:
        reason = f"Price below EMA20/EMA50 but ADX {adx} is under 20 (trend strength weakening, not confirmed)."
        return {'classification': 'Weakening trend', 'reason': reason}

    if not below_ema20 and below_ema50 and rsi is not None and rsi > 40:
        reason = f"Price has reclaimed EMA20 ({ema20}) while still under EMA50 ({ema50}), RSI {rsi} recovering from oversold levels."
        return {'classification': 'Possible stabilization', 'reason': reason}

    if trending_up and not below_ema20 and rsi is not None and 40 < rsi < 70:
        reason = f"Price above EMA20/EMA50, ADX {adx} with +DI > -DI, RSI {rsi} in a constructive (not overbought) range."
        return {'classification': 'Potential recovery setup', 'reason': reason}

    if weak_trend and abs(price - ema50) / ema50 * 100 < 3:
        reason = f"ADX {adx} under 20 (no directional trend) and price within 3% of EMA50 ({ema50})."
        return {'classification': 'Sideways / range-bound', 'reason': reason}

    return {
        'classification': 'Insufficient data',
        'reason': f"Current readings (price {price}, EMA20 {ema20}, EMA50 {ema50}, ADX {adx}, RSI {rsi}) don't clearly match any defined category -- shown as-is rather than forced into one.",
    }
