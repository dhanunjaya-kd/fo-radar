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
from typing import Optional, Dict, Any

logger = logging.getLogger('fundamentals_research.technical_analysis')


def get_technical_snapshot(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Fetches real daily price history for one stock and runs it through
    the EXISTING, already-proven indicator engine. Returns None (never
    a fabricated snapshot) if history is unavailable or too short --
    _compute_indicators() itself already requires >=20 bars and
    returns None below that; this function passes that through rather
    than working around it.
    """
    try:
        from screener.fyers_client import get_history
        from screener.views import _compute_indicators
        import pandas as pd
    except ImportError as e:
        logger.warning(f"Could not import screener's indicator engine: {e}")
        return None

    fyers_symbol = f"NSE:{symbol.upper()}-EQ"
    try:
        hist = get_history(fyers_symbol, resolution="1D")
    except Exception as e:
        logger.warning(f"Price history fetch failed for {symbol}: {e}")
        return None

    candles = (hist or {}).get('candles')
    if not candles or len(candles) < 20:
        logger.info(f"Insufficient price history for {symbol} ({len(candles) if candles else 0} bars) -- technical snapshot unavailable, not fabricated.")
        return None

    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    indicators = _compute_indicators(df['close'], df['high'], df['low'], df['volume'])
    if indicators is None:
        return None

    current_price = float(df['close'].iloc[-1])
    indicators['current_price'] = current_price
    indicators['as_of_timestamp'] = int(df['timestamp'].iloc[-1])
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
