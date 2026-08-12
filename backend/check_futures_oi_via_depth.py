"""
check_futures_oi_via_depth.py

Purpose: check_futures_oi_fields.py already confirmed the Fyers QUOTES API
never returns Futures OI (matches Fyers' own docs — it's simply not there,
under any field name). This script tests the separate MARKET DEPTH API
instead (fyers.depth()), which Fyers' docs say IS where OI lives.

Also tests MCX crude oil (both the mini CRUDEOILM and standard CRUDEOIL
contracts) alongside NIFTY/BANKNIFTY, since the same open question — does
depth() actually return OI — applies to the crude oil dashboard too. If
your Fyers account doesn't have the commodity segment activated, the MCX
symbols below will fail here with an auth/permission-style error in their
own section of the output — that's your confirmation to go check your
Fyers account settings, no separate manual check needed first.

Run from backend/ with venv active — same folder as fyers_auth.json
(the file get_fyers_token.py writes daily).

Two steps:
  1. Validate which futures symbol strings Fyers actually recognizes right
     now (tries a few likely formats per instrument via the cheap quotes()
     call, rather than guessing and risking "invalid symbol").
  2. Call depth() on whatever validates, dump the FULL raw response, and
     recursively flag any field with "oi" in its name so nothing is missed
     even if it's nested or named differently than expected.

Best run during market hours for a meaningful test — NSE F&O is 9:15 AM -
3:30 PM; MCX commodities run later into the evening (roughly 9 AM - 11:30
PM), so a crude oil result checked after 3:30 PM is still valid even
though the NIFTY/BANKNIFTY ones by then won't be live.

Paste the full printed output back for review.
"""

import json
import datetime
from fyers_apiv3 import fyersModel

# ─── Load saved token (same file get_fyers_token.py writes) ───
with open("fyers_auth.json", "r") as f:
    auth = json.load(f)

CLIENT_ID = auth["app_id"]
ACCESS_TOKEN = auth["access_token"]

fyers = fyersModel.FyersModel(
    client_id=CLIENT_ID,
    is_async=False,
    token=ACCESS_TOKEN,
    log_path=""
)


def month_candidates(base, exchange="NSE", months_ahead=0):
    """Build both plausible symbol orderings (YY+MMM and MMM+YY) for a
    given base symbol, N months ahead of today — covers current-month and
    next-month contracts without assuming exact expiry-rollover timing."""
    today = datetime.date.today()
    target = today.replace(day=1)
    for _ in range(months_ahead):
        target = (target.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    yy = target.strftime("%y")
    mmm = target.strftime("%b").upper()
    return [
        f"{exchange}:{base}{yy}{mmm}FUT",   # e.g. NSE:NIFTY26AUGFUT
        f"{exchange}:{base}{mmm}{yy}FUT",   # e.g. NSE:NIFTYAUG26FUT (fallback ordering)
    ]


candidates = []
for base in ["NIFTY", "BANKNIFTY"]:
    candidates += month_candidates(base, "NSE", months_ahead=0)
    candidates += month_candidates(base, "NSE", months_ahead=1)  # in case current month already rolled

# Crude oil on MCX — testing both the mini contract (CRUDEOILM, smaller
# lot size) and the standard contract (CRUDEOIL), since it's not yet
# decided which one the dashboard should actually track and checking
# both here costs nothing extra.
for base in ["CRUDEOILM", "CRUDEOIL"]:
    candidates += month_candidates(base, "MCX", months_ahead=0)
    candidates += month_candidates(base, "MCX", months_ahead=1)

candidates = list(dict.fromkeys(candidates))  # de-dupe, preserve order

print("=" * 70)
print("STEP 1: Validating which candidate symbols Fyers actually recognizes")
print("(NIFTY/BANKNIFTY on NSE, crude oil on MCX)")
print("=" * 70)
print("Candidates:", candidates)

valid_symbols = []
try:
    quote_response = fyers.quotes(data={"symbols": ",".join(candidates)})
    print(json.dumps(quote_response, indent=2))

    if quote_response.get("s") == "ok":
        for item in quote_response.get("d", []):
            v = item.get("v", {}) or {}
            sym = item.get("n") or v.get("symbol")
            # A real, recognized symbol comes back with actual price fields
            # (lp = last price); a bad symbol errors out or omits them.
            if item.get("s") == "ok" and "lp" in v:
                valid_symbols.append(sym)
except Exception as e:
    print(f"ERROR calling quotes(): {e}")
    quote_response = None

print("\nValid symbols found:", valid_symbols if valid_symbols else "NONE — will still try depth() on raw candidates below")


def find_oi_keys(obj, path=""):
    """Recursively hunt for any key containing 'oi' (case-insensitive),
    anywhere in the response, at any nesting depth."""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_path = f"{path}.{k}" if path else k
            if "oi" in k.lower():
                found.append((new_path, v))
            found += find_oi_keys(v, new_path)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += find_oi_keys(v, f"{path}[{i}]")
    return found


print("\n" + "=" * 70)
print("STEP 2: Testing Market Depth (fyers.depth) for OI")
print("=" * 70)

test_symbols = valid_symbols if valid_symbols else candidates

for symbol in test_symbols:
    print(f"\n{'-' * 70}")
    print(f"Testing depth() for: {symbol}")
    print("-" * 70)
    try:
        response = fyers.depth(data={"symbol": symbol, "ohlcv_flag": "1"})
        print(json.dumps(response, indent=2))
        oi_fields = find_oi_keys(response)
        if oi_fields:
            print(f"\n>>> OI-RELATED FIELDS FOUND: {oi_fields}")
        else:
            print("\n>>> No OI-related field found in this response.")
    except Exception as e:
        print(f"ERROR calling depth() for {symbol}: {e}")

print("\n" + "=" * 70)
print("DONE. Paste this full output back for review.")
print("=" * 70)
