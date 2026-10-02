"""
screener/pattern_backtest.py

Oct 2 2026: "what usually happened next" -- walk-forward base rates for the patterns the
detector finds, measured on THIS app's own scanned history (about a year of daily candles
per stock), not on a borrowed statistic.

Method (no hindsight):
  * for each symbol, re-run the detector on growing prefixes of its history (every STEP bars);
  * a pattern counts as an instance at the first prefix where it is *Confirmed* with the break
    at most FRESH bars old -- exactly the moment a person looking at the screen would have seen it;
  * entry = that bar's close; target and stop = the levels the detector printed on that prefix;
  * outcome = which of target / stop is touched first within HORIZON sessions (a bar that touches
    both counts as the stop -- conservative); instances whose outcome isn't known yet are dropped,
    not guessed.

Limits worth stating next to any number this produces: ~1 year x one universe is a small sample
(the UI refuses to show a rate under MIN_N instances), outcomes are gross of costs and slippage,
instances from the same market regime are correlated, and entry at the close of the break bar is
more pessimistic than entering at the trigger. Pure Python, unit tested.
"""
from . import chart_patterns as cp

HORIZON = 40
PULLBACK_WINDOW = 10
STEP = 5
MIN_BARS = 120
FRESH = 5            # >= STEP so no break can slip between two cuts
MIN_N = 15


def simulate(direction, entry_i, trigger, target, stop, h, l, c):
    """Outcome after entering at close[entry_i]; None if it can't be resolved yet."""
    n = len(c)
    bull = direction == "Bullish"
    entry = c[entry_i]
    if (bull and (entry >= target or entry <= stop)) or (not bull and (entry <= target or entry >= stop)):
        return None
    height = abs(target - trigger)
    last = min(n - 1, entry_i + HORIZON)
    outcome, bars, pullback, extreme = None, None, False, 0.0
    for j in range(entry_i + 1, last + 1):
        hit_t = h[j] >= target if bull else l[j] <= target
        hit_s = l[j] <= stop if bull else h[j] >= stop
        if j - entry_i <= PULLBACK_WINDOW and (l[j] <= trigger if bull else h[j] >= trigger):
            pullback = True
        fav = (h[j] - trigger) if bull else (trigger - l[j])
        extreme = max(extreme, fav)
        if outcome is None:
            if hit_s:                 # stop wins a same-bar tie
                outcome, bars = "stop", j - entry_i
            elif hit_t:
                outcome, bars = "target", j - entry_i
    if outcome is None:
        if entry_i + HORIZON > n - 1:
            return None               # still running -- don't guess
        outcome = "timeout"
    return {"outcome": outcome, "bars": bars, "pullback": pullback, "double": bool(height and extreme >= 2 * height)}


def instances(symbol, o, h, l, c, v, ts=None):
    """Walk-forward instances for one symbol. Each: name, direction, family, break_i/date, outcome, bars, pullback, double."""
    n = len(c)
    out, seen = [], set()
    for cut in range(MIN_BARS, n - 1, STEP):
        for p in cp.detect(o[:cut], h[:cut], l[:cut], c[:cut], v[:cut] if v else None):
            if p["status"] != "Confirmed" or p["broke_i"] is None or p["target"] is None or p["stop"] is None:
                continue
            if cut - 1 - p["broke_i"] > FRESH:
                continue
            key = (p["name"], p["start_i"])
            if key in seen:
                continue
            seen.add(key)
            res = simulate(p["direction"], cut - 1, p["trigger"], p["target"], p["stop"], h, l, c)
            if res is None:
                continue
            out.append({"symbol": symbol, "name": p["name"], "direction": p["direction"], "family": p["family"],
                        "break_i": p["broke_i"], "entry_i": cut - 1, "score": p["score"], **res})
            if ts:
                import datetime as _dt
                out[-1]["break_date"] = _dt.datetime.fromtimestamp(ts[p["broke_i"]]).strftime("%Y-%m-%d")
    return out


def _stats(items):
    n = len(items)
    hits = [x for x in items if x["outcome"] == "target"]
    bars = sorted(x["bars"] for x in hits)
    return {
        "n": n,
        "hit_target": round(len(hits) / n, 3),
        "hit_stop": round(sum(x["outcome"] == "stop" for x in items) / n, 3),
        "timeout": round(sum(x["outcome"] == "timeout" for x in items) / n, 3),
        "median_bars_to_target": bars[len(bars) // 2] if bars else None,
        "pullback": round(sum(x["pullback"] for x in items) / n, 3),
        "double": round(sum(x["double"] for x in items) / n, 3),
        "horizon": HORIZON,
    }


def aggregate(all_instances):
    """{"<name>|<direction>": stats, "family:<family>|<direction>": stats, "all": stats}"""
    groups = {}
    for x in all_instances:
        groups.setdefault(f"{x['name']}|{x['direction']}", []).append(x)
        groups.setdefault(f"family:{x['family']}|{x['direction']}", []).append(x)
    rates = {k: _stats(v) for k, v in groups.items()}
    if all_instances:
        rates["all"] = _stats(all_instances)
    return rates
