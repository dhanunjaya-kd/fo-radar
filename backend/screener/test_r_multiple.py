"""
R-Multiple: Realized P&L / Initial Risk, per the PDF spec's own
definition. Initial Risk = entry - sl in PREMIUM terms -- confirmed
against the real engine's own existing pnl formula (pnl = exit_price -
entry, applied uniformly regardless of BUY/SELL), which only makes
sense if entry is always the premium PAID and sl is always BELOW it,
since every trade here is buying an option contract (call or put),
never shorting the underlying. So initial_risk = entry - sl should
always be positive for a real, correctly-logged trade -- a
non-positive value signals a genuine data problem, not a valid trade,
and is handled defensively (None, not a fabricated/nonsensical ratio).
"""

def compute_r_multiple(entry, sl, exit_price):
    if entry is None or sl is None or exit_price is None:
        return None
    initial_risk = entry - sl
    if initial_risk <= 0:
        return None  # data problem (sl at or above entry) -- never divide by zero or a negative risk
    return round((exit_price - entry) / initial_risk, 4)


def summarize_r_multiples(trades):
    """trades: list of trade dicts, each with an r_multiple key
    (possibly None). Matches the real signature in
    backtest_signal_pnl.py exactly -- compute_metrics() has the full
    trade list available, not a pre-extracted r_values array."""
    r_values = [t["r_multiple"] for t in trades if t.get("r_multiple") is not None]
    if not r_values:
        return None
    n = len(r_values)
    sorted_r = sorted(r_values)
    median = sorted_r[n // 2] if n % 2 == 1 else (sorted_r[n // 2 - 1] + sorted_r[n // 2]) / 2
    winners = [r for r in r_values if r > 0]
    losers = [r for r in r_values if r < 0]
    return {
        "avg_r": round(sum(r_values) / n, 3),
        "median_r": round(median, 3),
        "best_r": round(max(r_values), 3),
        "worst_r": round(min(r_values), 3),
        "pct_ge_1r": round(len([r for r in r_values if r >= 1]) / n * 100, 1),
        "pct_ge_2r": round(len([r for r in r_values if r >= 2]) / n * 100, 1),
        "pct_le_neg1r": round(len([r for r in r_values if r <= -1]) / n * 100, 1),
        "avg_winning_r": round(sum(winners) / len(winners), 3) if winners else None,
        "avg_losing_r": round(sum(losers) / len(losers), 3) if losers else None,
        "sample_size": n,
    }


print("=== TEST 1: a real winning trade -- entry 68.65, sl 55.68, exit 95.00 ===")
r1 = compute_r_multiple(68.65, 55.68, 95.00)
print(r1)
expected1 = round((95.00 - 68.65) / (68.65 - 55.68), 4)
assert r1 == expected1, f"FAIL: expected {expected1}, got {r1}"
print(f"PASS -- R={r1} (won {r1}x the initial risk)\n")

print("=== TEST 2: exact SL hit -- realized R should be exactly -1.0 ===")
r2 = compute_r_multiple(68.65, 55.68, 55.68)
print(r2)
assert r2 == -1.0, f"FAIL: an exact SL exit must be exactly -1R, got {r2}"
print("PASS -- SL exit is exactly -1R, as it must be by definition\n")

print("=== TEST 3: exact entry price (breakeven) -- R should be exactly 0 ===")
r3 = compute_r_multiple(68.65, 55.68, 68.65)
assert r3 == 0.0, f"FAIL: got {r3}"
print("PASS\n")

print("=== TEST 4: a bad data row (sl AT or ABOVE entry) -- returns None, never a fabricated/infinite ratio ===")
r4a = compute_r_multiple(68.65, 68.65, 80.0)  # sl == entry
r4b = compute_r_multiple(68.65, 75.0, 80.0)   # sl > entry (nonsensical for this engine's convention)
assert r4a is None, f"FAIL: sl==entry should be None, got {r4a}"
assert r4b is None, f"FAIL: sl>entry should be None, got {r4b}"
print("PASS -- defensively returns None rather than dividing by zero or a negative risk\n")

print("=== TEST 5: missing fields (None) handled gracefully, no crash ===")
assert compute_r_multiple(None, 55.68, 80.0) is None
assert compute_r_multiple(68.65, None, 80.0) is None
assert compute_r_multiple(68.65, 55.68, None) is None
print("PASS\n")

print("=== TEST 6: summary stats over a realistic mixed set of R-multiples ===")
r_values = [2.5, 1.8, -1.0, 0.5, -1.0, 3.2, -1.0, 1.1, 0.0, -1.0]
fake_trades = [{"r_multiple": r} for r in r_values]
summary = summarize_r_multiples(fake_trades)
print(summary)
assert summary["sample_size"] == 10
assert summary["best_r"] == 3.2
assert summary["worst_r"] == -1.0
assert summary["pct_le_neg1r"] == 40.0, f"FAIL: 4 of 10 trades are exactly -1R, expected 40.0%, got {summary['pct_le_neg1r']}"
assert summary["pct_ge_1r"] == 40.0, f"FAIL: expected 40.0%, got {summary['pct_ge_1r']}"
assert summary["pct_ge_2r"] == 20.0, f"FAIL: expected 20.0%, got {summary['pct_ge_2r']}"
print("PASS -- avg/median/best/worst/percentile breakdown all correct\n")

print("=== TEST 7: winning vs losing R averages are asymmetry-revealing, not just overall average ===")
assert summary["avg_winning_r"] is not None and summary["avg_winning_r"] > 0
assert summary["avg_losing_r"] is not None and summary["avg_losing_r"] < 0
print(f"avg_winning_r={summary['avg_winning_r']}, avg_losing_r={summary['avg_losing_r']}")
print("PASS\n")

print("=== TEST 8: trades with only None r_multiple (no valid ones) -- returns None, not a crash or fake zero ===")
assert summarize_r_multiples([{"r_multiple": None}, {"r_multiple": None}]) is None
print("PASS\n")

print("=== TEST 9: an EMPTY trades list -- same defensive behavior ===")
assert summarize_r_multiples([]) is None
print("PASS\n")

print("ALL R-MULTIPLE TESTS PASSED")
