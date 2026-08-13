"""
backend/fundamentals/price_levels.py

52-week high/low for a symbol, using the get_history() function
already wired into this project (screener/fyers_client.py) -- no new
Fyers integration needed, just a new use of an existing one.

Returns the real high/low across the trailing ~365 days of DAILY
candles, plus how far the latest close sits from each -- the "very
low levels" half of the watchlist criteria (the other half, real
fundamentals, lives in parser.py).
"""
from datetime import datetime, timedelta

# fundamentals/ sits as a sibling to screener/ under backend/, not
# inside it -- import from the screener package explicitly.
from screener.fyers_client import get_history


def get_52week_range(symbol):
    """
    Returns a dict with 52-week high/low and how far the latest close
    sits from each, or None if history couldn't be fetched (bad
    symbol, Fyers not authenticated, no candles returned, etc.) --
    callers must treat None as "no data," never substitute a guess.

    symbol: full Fyers symbol, e.g. "NSE:RELIANCE-EQ"

    NOTE: Fyers' daily-resolution History API may cap how many days a
    single request can span -- not yet confirmed against a real call
    (day_format was verified elsewhere in this project, but not this
    specific 365-day range). If a live test comes back short of a
    year, this needs to loop over multiple smaller date windows and
    combine them instead of one call.
    """
    today = datetime.now().date()
    range_from = (today - timedelta(days=365)).strftime("%Y-%m-%d")
    range_to = today.strftime("%Y-%m-%d")

    resp = get_history(symbol, resolution="D", range_from=range_from, range_to=range_to)
    if not resp or resp.get("s") != "ok":
        return None
    candles = resp.get("candles", [])
    if not candles:
        return None

    # Each candle: [timestamp, open, high, low, close, volume]
    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]
    latest_close = candles[-1][4]

    week52_high = max(highs)
    week52_low = min(lows)

    pct_off_high = ((latest_close - week52_high) / week52_high * 100) if week52_high else None
    pct_above_low = ((latest_close - week52_low) / week52_low * 100) if week52_low else None

    return {
        "latest_close": latest_close,
        "week52_high": week52_high,
        "week52_low": week52_low,
        "pct_off_52w_high": round(pct_off_high, 2) if pct_off_high is not None else None,
        "pct_above_52w_low": round(pct_above_low, 2) if pct_above_low is not None else None,
        "candle_count": len(candles),
    }
