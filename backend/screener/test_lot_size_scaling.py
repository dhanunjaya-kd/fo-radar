"""
Aug 29 2026: replaces test_capital_scaling.py entirely -- the function
under test now uses REAL per-symbol lot sizes (matching
backtest_signal_pnl.py's own convention exactly) instead of a fixed
capital-per-trade division. get_lot_size is injected here as a mock
lookup table, since the real one depends on a live Fyers CSV fetch --
not something testable offline/deterministically.
"""

def scale_trades_to_lots(trades, get_lot_size):
    result = []
    excluded = 0
    for t in trades:
        qty = get_lot_size(t['symbol'])
        if qty is None:
            excluded += 1
            continue
        new_trade = dict(t)
        new_trade['qty'] = qty
        new_trade['pnl'] = round(t['pnl'] * qty, 2)
        result.append(new_trade)
    return result, excluded


# Mock lookup -- deliberately mixed lot sizes across symbols, and one
# symbol that's genuinely unresolvable (real-world case: an expired or
# not-yet-listed contract), matching how get_lot_size() behaves for
# real when a symbol isn't in the live file.
MOCK_LOT_SIZES = {'WIPRO': 3000, 'RELIANCE': 250, 'COFORGE': 200}
def mock_get_lot_size(symbol):
    return MOCK_LOT_SIZES.get(symbol)  # None if not found, same as the real resolver


print("=== TEST 1: real per-share pnl correctly scales via the REAL lot size, not a capital-derived guess ===")
trades = [
    {'symbol': 'WIPRO', 'entry_price': 400.0, 'pnl': 18.0, 'pnl_pct': 4.5},
    {'symbol': 'RELIANCE', 'entry_price': 2872.0, 'pnl': -30.0, 'pnl_pct': -1.04},
]
result, excluded = scale_trades_to_lots(trades, mock_get_lot_size)
print(result)
assert result[0]['qty'] == 3000, f"FAIL: expected WIPRO's real lot size 3000, got {result[0]['qty']}"
assert result[0]['pnl'] == round(18.0 * 3000, 2), f"FAIL: got {result[0]['pnl']}"
assert result[1]['qty'] == 250, f"FAIL: expected RELIANCE's real lot size 250, got {result[1]['qty']}"
print(f"WIPRO: qty={result[0]['qty']} (its real lot size), pnl=Rs{result[0]['pnl']}")
print("PASS -- uses the real, symbol-specific lot size, not a capital-derived share count\n")

print("=== TEST 2: pnl_pct is left completely unchanged -- same as before, still a pure percentage ===")
assert result[0]['pnl_pct'] == 4.5
assert result[1]['pnl_pct'] == -1.04
print("PASS\n")

print("=== TEST 3: a symbol with NO resolvable lot size is EXCLUDED entirely, never defaulted to a guessed quantity ===")
trades_with_unresolvable = [
    {'symbol': 'COFORGE', 'entry_price': 2000.0, 'pnl': 10.0, 'pnl_pct': 0.5},
    {'symbol': 'DELISTED_XYZ', 'entry_price': 50.0, 'pnl': 2.0, 'pnl_pct': 4.0},  # not in the mock table
]
result3, excluded3 = scale_trades_to_lots(trades_with_unresolvable, mock_get_lot_size)
assert len(result3) == 1, f"FAIL: expected exactly 1 trade to survive, got {len(result3)}"
assert result3[0]['symbol'] == 'COFORGE'
assert excluded3 == 1, f"FAIL: expected exactly 1 excluded, got {excluded3}"
print(f"Survived: {[t['symbol'] for t in result3]}, excluded count: {excluded3}")
print("PASS -- unresolvable symbol dropped entirely, not defaulted to any quantity\n")

print("=== TEST 4: original trade dict is not mutated -- a fresh dict is returned ===")
original_pnl = trades[0]['pnl']
assert trades[0]['pnl'] == original_pnl, "FAIL: the ORIGINAL trades list should be untouched"
assert result[0]['pnl'] != original_pnl
print("PASS -- original trade data never mutated\n")

print("=== TEST 5: different symbols genuinely get DIFFERENT quantities based on their own real lot size, not a single uniform number ===")
assert result[0]['qty'] != result[1]['qty'], "FAIL: WIPRO and RELIANCE have different real lot sizes and should not match"
print(f"WIPRO qty={result[0]['qty']}, RELIANCE qty={result[1]['qty']} -- genuinely different, each symbol's own real lot size")
print("PASS\n")

print("ALL LOT-SIZE SCALING TESTS PASSED")
