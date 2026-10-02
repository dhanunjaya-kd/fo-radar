"""
screener/scanner_levels.py

Oct 2 2026: Scanner card levels (Breakout / Target / Stop / R:R) drawn on the
card's mini candlestick chart.

HONEST SCOPE -- this is a 20-day RANGE breakout setup, not chart-pattern
detection. It does not claim a wedge, flag or channel; those need a real
pattern engine (planned as phase 2). What it does claim is arithmetic on the
last 20 COMPLETED daily candles:

  range      = highest high / lowest low of the last `lookback` candles
  BULLISH    breakout = range high, target = breakout + range height (the
             standard measured move), stop = breakout - max(1 ATR, 35% of the
             range height), never beyond the range low
  BEARISH    mirrored: breakdown = range low, target = breakdown - range height,
             stop = breakdown + max(1 ATR, 35% of height), never beyond the range high
  The 35%-of-height floor stops a tight daily ATR from producing a
  meaningless 8:1 R:R on a tall range; resulting R:R is naturally ~1.0-2.9.
  NEUTRAL    no levels (only the range box is drawn) -- the card's own
             score/direction already decided there is no clear lean.

Status is about where the LIVE price sits relative to the trigger:
  BROKE_OUT   price is beyond the trigger
  NEAR        within `near_atr` ATR before the trigger
  WATCHING    further away
It never says "confirmed": confirmation needs a daily CLOSE beyond the level,
and the live price is intraday.

Pure function, no pandas/Django -- unit-testable offline.
"""


def range_setup(candles, price, direction, atr, lookback=20, near_atr=1.0):
    """
    candles: completed daily candles, oldest first, each (open, high, low, close).
    price:   live price. direction: 'BULLISH' | 'BEARISH' | 'NEUTRAL' (anything else = NEUTRAL).
    atr:     daily ATR (> 0) or None.
    Returns None when there isn't enough data to say anything honest.
    """
    if not candles or len(candles) < max(5, lookback // 2) or price is None:
        return None
    window = candles[-lookback:]
    hi = max(c[1] for c in window)
    lo = min(c[2] for c in window)
    height = hi - lo
    if height <= 0:
        return None

    out = {
        "kind": "RANGE_20D", "range_high": round(hi, 2), "range_low": round(lo, 2),
        "lookback": len(window), "direction": direction if direction in ("BULLISH", "BEARISH") else "NEUTRAL",
        "breakout": None, "target": None, "stop": None, "rr": None, "status": "WATCHING", "pct_vs_trigger": None,
    }
    if out["direction"] == "NEUTRAL" or not atr or atr <= 0:
        return out

    stop_dist = max(atr, 0.35 * height)
    if out["direction"] == "BULLISH":
        trigger = hi
        stop = max(lo, trigger - stop_dist)
        target = trigger + height
        beyond = price > trigger
        gap_atr = (trigger - price) / atr
    else:
        trigger = lo
        stop = min(hi, trigger + stop_dist)
        target = trigger - height
        beyond = price < trigger
        gap_atr = (price - trigger) / atr

    risk = abs(trigger - stop)
    reward = abs(target - trigger)
    out.update({
        "breakout": round(trigger, 2), "stop": round(stop, 2), "target": round(target, 2),
        "rr": round(reward / risk, 1) if risk > 0 else None,
        "pct_vs_trigger": round((price / trigger - 1) * 100, 1),
        "status": "BROKE_OUT" if beyond else ("NEAR" if gap_atr <= near_atr else "WATCHING"),
    })
    return out
