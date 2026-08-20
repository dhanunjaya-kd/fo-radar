"""
check_gold_silver_symbols.py

Standalone diagnostic -- NOT part of the app, run manually once.

Purpose: Gold/Silver on MCX do NOT trade in every calendar month the way
CRUDEOIL does (confirmed pattern from market reports: contracts show up
in scattered specific months, not a near-monthly cycle). Blindly reusing
_front_month_commodity_symbol()'s "just roll to next calendar month"
logic for Gold/Silver risks constructing a symbol for a month that has
NO listed contract at all -- Fyers would return nothing for it, same
empty-response failure just fixed for Crude, but for a more fundamental
reason (no contract exists that month, not just "rolled 3 days late").

This script tries the standard MCX symbol format already confirmed
working for Crude (MCX:{base}{yy}{mon}FUT) against GOLD, GOLDM (Gold
Mini), SILVER, and SILVERM (Silver Mini) for the current month plus the
next 4 months, and reports which ones Fyers actually returns live data
for RIGHT NOW -- so the real active contract months get confirmed from
Fyers itself, not guessed from general web results.

Run this the same way the project's other check_*.py scripts run
(same venv, same directory this project already runs them from) --
needs a live authenticated Fyers session, same as any other live check.
"""
from datetime import datetime

# Adjust this import if your other check_*.py scripts bootstrap Django
# differently -- this assumes the same relative import fyers_client.py
# is used with elsewhere in the project (from .fyers_client import ...
# inside the app; standalone scripts outside the app typically need a
# django.setup() call first if fyers_client.py touches settings/env).
try:
    import django
    import os
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
    django.setup()
except Exception as e:
    print(f"[setup] django.setup() skipped or failed ({e}) -- if the "
          f"import below fails, run this the same way your other "
          f"check_*.py scripts run instead.")

from screener.fyers_client import get_market_depth

CANDIDATE_BASES = ["GOLD", "GOLDM", "SILVER", "SILVERM"]


def month_symbol(base, year, month):
    yy = str(year)[2:]
    mon = datetime(year, month, 1).strftime("%b").upper()
    return f"MCX:{base}{yy}{mon}FUT"


def next_n_months(n):
    today = datetime.now()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def main():
    months = next_n_months(5)  # this month + next 4
    print(f"Checking {len(CANDIDATE_BASES)} bases x {len(months)} months "
          f"= {len(CANDIDATE_BASES) * len(months)} symbols against live Fyers...\n")

    live_by_base = {b: [] for b in CANDIDATE_BASES}

    for base in CANDIDATE_BASES:
        for (y, m) in months:
            sym = month_symbol(base, y, m)
            try:
                resp = get_market_depth(sym)
            except Exception as e:
                print(f"  {sym:28s} -> EXCEPTION: {e}")
                continue
            ok = bool(resp and resp.get("s") == "ok")
            ltp = None
            if ok:
                d = (resp.get("d", {}) or {}).get(sym, {})
                ltp = d.get("ltp")
            status = f"LIVE (ltp={ltp})" if (ok and ltp) else f"no data (s={resp.get('s') if resp else None})"
            print(f"  {sym:28s} -> {status}")
            if ok and ltp:
                live_by_base[base].append(sym)

    print("\n" + "=" * 60)
    print("SUMMARY -- which months are actually live right now:")
    for base, syms in live_by_base.items():
        if syms:
            print(f"  {base}: {', '.join(syms)}")
        else:
            print(f"  {base}: NOTHING live in the checked window -- "
                  f"either the base name is wrong or needs a wider month range")


if __name__ == "__main__":
    main()
