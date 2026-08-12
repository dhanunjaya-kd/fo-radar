"""
check_crude_oil_options.py

Purpose: NIFTY/BANKNIFTY's option chain (PCR, Max Pain, support/
resistance) uses the INDEX itself as the underlying symbol
(NSE:NIFTY50-INDEX). Commodities may not work the same way -- MCX
options are options on the FUTURES contract, not a spot/cash index, so
the correct underlying symbol to pass to Fyers' optionchain() is not
yet confirmed for crude oil.

Tries several candidate underlying symbols (bare commodity name, and
the confirmed-working futures contract symbols) and reports which one
(if any) returns a real option chain.

Run from backend/ with venv active, same as the other diagnostics.
Best run during MCX hours (roughly 9 AM - 11:30 PM) for a meaningful
test.

Paste the full printed output back for review.
"""

import json
from fyers_client import get_option_chain

candidates = [
    "MCX:CRUDEOIL",
    "MCX:CRUDEOILM",
    "MCX:CRUDEOIL26AUGFUT",       # confirmed-valid futures symbol from the earlier depth test
    "MCX:CRUDEOILM26AUGFUT",      # confirmed-valid mini futures symbol
]

for symbol in candidates:
    print("=" * 70)
    print(f"Testing option chain for: {symbol}")
    print("=" * 70)
    try:
        resp = get_option_chain(symbol, strikecount=10)
        if resp is None:
            print(">>> get_option_chain returned None (exception was printed above, if any)")
            continue
        print(json.dumps(resp, indent=2)[:3000])  # first 3000 chars -- option chains are long
        if resp.get("s") == "ok":
            print(f"\n>>> SUCCESS -- {symbol} returned a real option chain")
        else:
            print(f"\n>>> FAILED -- status: {resp.get('s')}, message: {resp.get('message')}")
    except Exception as e:
        print(f"ERROR testing {symbol}: {e}")
    print()

print("DONE. Paste this full output back for review.")
