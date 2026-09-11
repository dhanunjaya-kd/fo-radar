"""
backend/check_sensex_symbol.py

One-off diagnostic to confirm SENSEX's real data on Fyers before wiring
a front-month FUTURES resolver into index_tracker.py -- same "confirm
against live data, don't guess" discipline as this project's other
check_*.py scripts (check_real_mcx_symbols.py, find_futures_symbol.py).

The option-chain side (BSE:SENSEX-INDEX) is already wired in and does
NOT need this script to confirm -- it's the same documented symbol
Fyers' own Option Chain UI and community docs use. What's still
unconfirmed is the FUTURES contract: BSE:SENSEX expires on Fridays
(per BSE's own F&O launch material), not NIFTY/BANKNIFTY's NSE +
last-Tuesday pattern, and the exact symbol string Fyers expects for it
has never been tested against this account.

Checks three things:
  1. BSE:SENSEX-INDEX quote -- confirms the account can see BSE data
     at all (if this fails but NIFTY/BANKNIFTY quotes normally work,
     the account likely doesn't have the BSE segment enabled).
  2. BSE:SENSEX-INDEX option chain -- real expiryData straight from
     Fyers, so the actual expiry weekday can be READ, not guessed.
  3. A few candidate futures symbol strings against get_market_depth()
     -- whichever one comes back with a real ltp is the real one.

Run from backend/, venv active, same as get_fyers_token.py:
    python check_sensex_symbol.py

If the DJANGO_SETTINGS_MODULE line below errors, swap in your actual
settings module (check manage.py for the real name) -- fyers_client.py
itself falls back to plain FYERS_APP_ID/FYERS_APP_SECRET env vars if
Django settings aren't available, so this only matters if those aren't
set some other way.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
    import django
    django.setup()
except Exception as e:
    print(f"[check_sensex_symbol] Django setup skipped ({e}) -- continuing on fyers_client.py's env-var fallback.")

from screener.fyers_client import get_quotes, get_market_depth, get_option_chain, is_authenticated


def main():
    print("=" * 70)
    print("SENSEX symbol diagnostic")
    print("=" * 70)

    if not is_authenticated():
        print("NOT AUTHENTICATED -- run get_fyers_token.py first, then retry.")
        return

    print("\n[1] Quote: BSE:SENSEX-INDEX")
    resp = get_quotes(["BSE:SENSEX-INDEX"])
    print(resp)
    if not resp or resp.get("s") != "ok":
        print("  FAILED. If NIFTY/BANKNIFTY quotes normally work fine, this account"
              " likely doesn't have BSE data enabled -- check that in Fyers' app"
              " settings before going further.")

    print("\n[2] Option chain: BSE:SENSEX-INDEX (real expiry dates)")
    chain = get_option_chain("BSE:SENSEX-INDEX", strikecount=5)
    if chain and chain.get("s") == "ok":
        expiries = chain.get("data", {}).get("expiryData", [])
        print(f"  Got {len(expiries)} expiry date(s):")
        for e in expiries[:6]:
            date_str = e.get("date")
            if date_str:
                d = datetime.strptime(date_str, "%d-%m-%Y")
                print(f"    {date_str}  ({d.strftime('%A')})")
    else:
        print(f"  FAILED: {chain}")
        print("  If [1] above worked but this didn't, the account most likely has"
              " BSE cash/index data but not the BSE OPTIONS segment specifically --"
              " that's a separate toggle from plain BSE access.")

    print("\n[3] Futures depth -- trying candidate symbol formats")
    today = datetime.now()
    yy = str(today.year)[2:]
    mon = today.strftime("%b").upper()
    candidates = [
        f"BSE:SENSEX{yy}{mon}FUT",
        f"NSE:SENSEX{yy}{mon}FUT",
        f"BSE:SENSEX-{yy}{mon}-FUT",
    ]
    for sym in candidates:
        depth = get_market_depth(sym)
        ltp = None
        if depth and depth.get("s") == "ok":
            ltp = (depth.get("d", {}) or {}).get(sym, {}).get("ltp")
        print(f"  {sym}: {'WORKS -- ltp=' + str(ltp) if ltp else 'no data'}")

    print("\nDone. Report back whichever candidate (if any) said WORKS, and the")
    print("expiry weekday(s) from [2] -- that confirms what index_tracker.py's")
    print("SENSEX futures resolver gets built against, same as Gold/Silver's")
    print("resolvers were before they got wired in.")


if __name__ == "__main__":
    main()
