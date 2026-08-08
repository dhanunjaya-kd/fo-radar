"""
find_futures_symbol.py

Read-only diagnostic -- tries several candidate NIFTY/BANKNIFTY futures
symbol formats against Fyers' quotes endpoint and reports which ones
actually return real data. No orders placed, nothing written anywhere,
completely safe to run.

Place this file in your backend/ folder, next to manage.py.

HOW TO RUN:
    cd backend
    venv\\Scripts\\activate      (Windows)  or  source venv/bin/activate (Mac/Linux)
    python find_futures_symbol.py

Paste me whatever it prints and I'll wire up Fut OI properly using
whichever symbol(s) actually worked.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fno_sniper.settings")
import django
django.setup()

from screener.fyers_client import get_quotes, is_authenticated


def last_thursday(year, month):
    """Last Thursday of the month -- NSE's monthly F&O expiry day."""
    if month == 12:
        next_month_first = date(year + 1, 1, 1)
    else:
        next_month_first = date(year, month + 1, 1)
    d = next_month_first - timedelta(days=1)
    while d.weekday() != 3:  # Monday=0 ... Thursday=3
        d -= timedelta(days=1)
    return d


def candidate_months():
    """This month and next month's (year, month, 3-letter code) --
    covers both 'still in front month' and 'already rolled' cases."""
    today = date.today()
    expiry = last_thursday(today.year, today.month)
    if today > expiry:
        y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    else:
        y, m = today.year, today.month
    months = [(y, m)]
    y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
    months.append((y2, m2))
    return [(yy, mm, date(yy, mm, 1).strftime("%b").upper()) for yy, mm in months]


def main():
    if not is_authenticated():
        print("NOT AUTHENTICATED -- run get_fyers_token.py first, then re-run this script.")
        return

    months = candidate_months()
    print(f"Checking candidate months: {[f'{mon}{y}' for y, m, mon in months]}\n")

    candidates = []
    for base in ("NIFTY", "BANKNIFTY"):
        for y, m, mon in months:
            yy = str(y)[2:]
            candidates.append(f"NSE:{base}{yy}{mon}FUT")

    print("Trying these symbols against Fyers quotes:\n")
    for c in candidates:
        print(" ", c)
    print()

    resp = get_quotes(candidates)
    if not resp:
        print("No response at all from Fyers -- check your connection/token.")
        return

    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    if resp.get("s") != "ok":
        print("Fyers rejected the whole batch:", resp)
        return

    found_any = False
    for item in resp.get("d", []):
        sym = item.get("n")
        if item.get("s") == "ok":
            v = item.get("v", {}) or {}
            lp = v.get("lp")
            print(f"CONFIRMED WORKS: {sym}  ->  LTP={lp}  OI={v.get('oi', 'n/a')}")
            found_any = True
        else:
            print(f"failed: {sym}  ->  {item}")

    print()
    if found_any:
        print("Copy the 'CONFIRMED WORKS' line(s) above and send them to me -- that's")
        print("the real, confirmed symbol format. I'll wire up Fut OI using it.")
    else:
        print("None of the candidates worked. Paste this entire output to me")
        print("and I'll try a different approach.")


if __name__ == "__main__":
    main()
