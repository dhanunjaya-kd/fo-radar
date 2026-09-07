"""
validate_probability_estimator.py

Real answer to: does the volatility-based probability estimator
(volatility_probability.py) actually predict which of these real,
already-resolved trades won and lost -- or does it not carry real
information at all? No point wiring an untested idea into a live
signal engine before checking that.

METHOD: for every real trade, compute its estimated probability using
ONLY historical closes strictly BEFORE that trade's own entry time --
never using data the trade itself wouldn't have had available yet
(same no-look-ahead discipline as cas_research.py's walk-forward
design earlier tonight). Bucket trades by that estimate, and check the
REAL win rate per bucket. If the estimator carries genuine signal, win
rate should climb from low-probability buckets to high-probability
ones. If it's flat or inconsistent, the estimator isn't actually
predictive for this trade set, regardless of how sound the underlying
math is.

Needs a real volatility_history.json (see fetch_volatility_history.py)
-- will not run against fabricated volatility numbers.
"""
from datetime import datetime

from volatility_probability import historical_volatility, probability_target_before_sl


def _closes_before(volatility_history, symbol, cutoff_dt):
    """Real historical closes for this symbol, strictly before cutoff_dt --
    the no-look-ahead boundary. Returns [] if the symbol has no real
    history saved at all (caller must skip, not substitute a guess)."""
    rows = volatility_history.get(symbol, [])
    dated = []
    for row in rows:
        try:
            d = datetime.strptime(row["date"], "%Y-%m-%d")
        except (KeyError, ValueError):
            continue
        if d < cutoff_dt:
            dated.append((d, row["close"]))
    dated.sort(key=lambda x: x[0])
    return [c for _, c in dated]


def compute_trade_probabilities(trades, volatility_history):
    """
    trades: list of (symbol, action, entry_dt_str, exit_dt_str, entry,
    exit_price, qty, pnl, reason, sl, target) -- REQUIRES the real,
    actual SL and Target levels the live signal used, not an
    approximation. volatility_history: {"SYMBOL": [{"date":
    "YYYY-MM-DD", "close": float}, ...]}

    Sep 6 2026: this used to derive sl/target from the trade's OWN
    realized move (symmetric around entry) rather than the real
    levels -- caught by a failed test, not by inspection: an
    engineered scenario with a genuinely real, detectable relationship
    between probability and outcome came out as a meaningless hump
    instead of a real trend. Root cause: using the outcome itself to
    build a symmetric SL/target window tests a completely different,
    made-up question than what the real signal actually offered (real
    setups have an asymmetric R:R -- target further than stop, not
    equal in both directions). Fixed by requiring the real sl/target
    values as input -- these already exist in this project's own
    signal_logs Excel files (the same "SL", "Target 1/2/3" columns
    backtest_signal_pnl.py already reads), so this isn't asking for
    anything that doesn't already exist for real.

    Returns (results, skipped) -- results is a list of dicts with the
    real trade plus its estimated probability; skipped counts trades
    that couldn't be honestly estimated rather than guessed at.
    """
    results = []
    skipped = {"no_history": 0, "too_little_history": 0, "no_result": 0, "bad_direction": 0}

    for t in trades:
        symbol, action, entry_dt_str, exit_dt_str, entry, exit_price, qty, pnl, reason, sl, target = t
        entry_dt = datetime.strptime(entry_dt_str, "%Y-%m-%d %H:%M")
        exit_dt = datetime.strptime(exit_dt_str, "%Y-%m-%d %H:%M")

        closes = _closes_before(volatility_history, symbol, entry_dt)
        if not closes:
            skipped["no_history"] += 1
            continue

        vol = historical_volatility(closes)
        if vol is None:
            skipped["too_little_history"] += 1
            continue

        horizon_days = max((exit_dt - entry_dt).total_seconds() / 86400, 1 / 24)  # floor at 1 real hour, never zero

        if action not in ("BUY", "SELL") or sl is None or target is None:
            skipped["bad_direction"] += 1
            continue

        prob = probability_target_before_sl(
            current_price=entry, sl=sl, target=target,
            annual_volatility=vol, time_horizon_days=horizon_days,
            n_simulations=5000, seed=hash((symbol, entry_dt_str)) % (2**31),
        )
        if prob is None:
            skipped["no_result"] += 1
            continue

        results.append({
            "symbol": symbol, "action": action, "entry_dt": entry_dt_str,
            "pnl": pnl, "won": pnl > 0, "estimated_probability": prob,
            "historical_volatility": round(vol, 3),
        })

    return results, skipped


def summarize_by_probability_bucket(results, n_buckets=4):
    """Real win rate per probability bucket -- the actual answer to
    'does this estimator carry real information'."""
    if not results:
        return None
    buckets = [[] for _ in range(n_buckets)]
    for r in results:
        idx = min(int(r["estimated_probability"] * n_buckets), n_buckets - 1)
        buckets[idx].append(r)

    summary = []
    for i, bucket in enumerate(buckets):
        lo, hi = i / n_buckets, (i + 1) / n_buckets
        if not bucket:
            summary.append({"range": f"{lo:.2f}-{hi:.2f}", "n": 0, "win_rate": None})
            continue
        wins = sum(1 for r in bucket if r["won"])
        summary.append({
            "range": f"{lo:.2f}-{hi:.2f}", "n": len(bucket),
            "win_rate": round(wins / len(bucket) * 100, 1),
        })
    return summary
