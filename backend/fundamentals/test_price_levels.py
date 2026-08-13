"""
backend/test_price_levels.py

Quick live test of price_levels.py against one real symbol -- run this
BEFORE trusting it for a full run across the whole NSE list.

Lives directly in backend/ (NOT inside fundamentals/) on purpose: when
Python runs a script directly, it only adds the script's OWN folder to
the import path, not the folder you launched it from. From inside
fundamentals/, that means the fundamentals package itself (one level
up) isn't visible. Sitting in backend/ instead, right next to both
fundamentals/ and screener/, sidesteps that entirely -- both import
correctly with no special flags needed.

    cd backend
    python test_price_levels.py
"""
from fundamentals.price_levels import get_52week_range

TEST_SYMBOL = "NSE:RELIANCE-EQ"

print(f"Testing 52-week range for {TEST_SYMBOL}...")
result = get_52week_range(TEST_SYMBOL)

if result is None:
    print("FAILED -- get_52week_range() returned None. Common causes:")
    print("  - Fyers not authenticated right now (check fyers_auth.json is fresh -- run get_fyers_token.py again if unsure)")
    print("  - get_history() itself failed -- look above for a printed '[Fyers] History error' line")
    print("  - The 365-day range may exceed what a single daily-resolution request allows")
else:
    for k, v in result.items():
        print(f"  {k:20s}: {v}")
    print()
    in_range = result["week52_low"] <= result["latest_close"] <= result["week52_high"]
    print(f"Sanity check -- week52_low <= latest_close <= week52_high: {in_range}")
