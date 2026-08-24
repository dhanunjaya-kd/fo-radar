"""
check_gold_resolver_live.py

Standalone diagnostic -- tests the EXACT code path OptionAnalyticsView
now uses for GOLD/GOLDM, step by step, so we know definitively what's
happening rather than guessing at a second fix blind:
  1. What does _front_month_bullion_symbol() actually resolve GOLD/
     GOLDM to right now?
  2. Does get_market_depth() on that resolved symbol return a real
     price (confirms the FUTURES contract itself is genuinely live)?
  3. Does get_option_analytics() on that same symbol return a real
     option chain (confirms OPTIONS are actually listed against it --
     a live futures contract doesn't automatically mean options exist
     for it too)?

Run the same way your other check_*.py scripts run:
    python check_gold_resolver_live.py
"""
import os
try:
    import django
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fno_sniper.settings")
    django.setup()
except Exception as e:
    print(f"[setup] django.setup() skipped or failed ({e})")

from screener.index_tracker import _front_month_bullion_symbol
from screener.fyers_client import get_market_depth, get_option_analytics


def check(base):
    print(f"--- {base} ---")
    symbol = _front_month_bullion_symbol(base)
    print(f"  Resolved symbol: {symbol}")
    if not symbol:
        print("  -> No live symbol found by the resolver itself. That IS the actual problem -- the")
        print("     resolver's 6-month probe found nothing live, not an options-chain-specific issue.\n")
        return

    try:
        depth = get_market_depth(symbol)
        ltp = (depth.get("d", {}) or {}).get(symbol, {}).get("ltp") if depth else None
        print(f"  Futures LTP: {ltp}  (confirms the futures contract itself is live, separate from options)")
    except Exception as e:
        print(f"  get_market_depth EXCEPTION: {e}")

    try:
        oi = get_option_analytics(symbol, strikecount=10)
        if oi and oi.get("rows"):
            print(f"  Option chain: {len(oi['rows'])} strikes returned, spot={oi.get('spot')} -- REAL DATA, this should work")
        else:
            print(f"  Option chain: EMPTY/None -- the futures contract may be live, but no options are listed against it.")
            print(f"  Raw response: {oi}")
    except Exception as e:
        print(f"  get_option_analytics EXCEPTION: {e}")
    print()


if __name__ == "__main__":
    check("GOLD")
    check("GOLDM")
