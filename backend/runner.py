"""
backend/runner.py

Combines all four fundamentals/ pieces into one full-universe run: for
every NSE main-board stock, fetch real fundamentals (via Screener.in)
and the real 52-week price range (via Fyers), and save the combined
result to disk as it goes.

Lives in backend/ (NOT inside fundamentals/) for the same reason
test_price_levels.py does -- running a script directly only puts its
OWN folder on the import path, and this needs to reach the
fundamentals package as a sibling, so it has to sit next to it.

DELIBERATELY SLOW, ON PURPOSE: ~2,466 stocks x several requests each
to Screener.in adds up fast, and hammering their servers isn't
acceptable just because this data happens to be reachable through
their own Export feature. A deliberate pause between each stock keeps
this respectful -- expect a full run to take a couple of HOURS, not
minutes. That's fine: this is meant to run occasionally in the
background (weekly, matching how often fundamentals actually change),
not on demand while someone's waiting on it.

RESUMABLE: saves progress to fundamentals_data.json every 20 stocks,
and skips any symbol already present in that file on a re-run -- so
stopping partway through (or a crash) doesn't mean starting over.

Run a SMALL test first, not the full list -- pass a limit:
    python runner.py 5
Then, once that looks right, run the real thing with no limit:
    python runner.py
"""
import json
import os
import sys
import time
from datetime import datetime

from fundamentals.symbol_master import get_nse_equity_symbols
from fundamentals.screener_client import get_session, fetch_export_bytes, SessionExpiredError
from fundamentals.parser import parse_fundamentals
from fundamentals.price_levels import get_52week_range

OUTPUT_FILE = "fundamentals_data.json"
PAUSE_SECONDS = 2.0  # between each stock's Screener.in requests -- a politeness pause, not a rate-limit workaround. Adjust if this turns out too slow or too fast once you see it running.


def load_existing():
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(data):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def run(limit=None):
    symbols = get_nse_equity_symbols()
    if not symbols:
        print("ERROR: couldn't fetch the NSE symbol list -- aborting. (Check your internet connection, or that public.fyers.in is reachable.)")
        return
    if limit:
        symbols = symbols[:limit]
        print(f"TEST RUN -- limited to the first {limit} symbols.")

    results = load_existing()
    session = get_session()

    print(f"Starting: {len(symbols)} symbols to check, {len(results)} already done from a previous run.")
    for i, fyers_symbol in enumerate(symbols):
        if fyers_symbol in results:
            continue  # already have this one -- resuming, not restarting

        # e.g. "NSE:RELIANCE-EQ" -> "RELIANCE" for the Screener search
        screener_symbol = fyers_symbol.replace("NSE:", "").replace("-EQ", "")

        try:
            xlsx_bytes = fetch_export_bytes(session, screener_symbol)
            fundamentals = parse_fundamentals(xlsx_bytes) if xlsx_bytes else None
        except SessionExpiredError as e:
            print(f"\n{'=' * 70}")
            print("STOPPING -- Screener session has expired.")
            print("=" * 70)
            print(str(e))
            save_progress(results)
            print(f"\nProgress so far ({len(results)} stocks) has been saved to {OUTPUT_FILE}.")
            print("Refresh screener_session.txt, then rerun this same command -- already-completed stocks will be skipped automatically.")
            return
        except Exception as e:
            print(f"[{i + 1}/{len(symbols)}] {fyers_symbol}: fundamentals fetch failed: {e}")
            fundamentals = None

        try:
            price_data = get_52week_range(fyers_symbol)
        except Exception as e:
            print(f"[{i + 1}/{len(symbols)}] {fyers_symbol}: price fetch failed: {e}")
            price_data = None

        results[fyers_symbol] = {
            "fundamentals": fundamentals,
            "price_levels": price_data,
            "fetched_at": datetime.now().isoformat(),
        }

        status = "OK" if (fundamentals and price_data) else "PARTIAL" if (fundamentals or price_data) else "FAILED"
        print(f"[{i + 1}/{len(symbols)}] {fyers_symbol}: {status}")

        if (i + 1) % 20 == 0:
            save_progress(results)
            print(f"  -- progress saved ({len(results)} total so far)")

        time.sleep(PAUSE_SECONDS)

    save_progress(results)
    print(f"\nDone. {len(results)} symbols processed, saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(limit=limit)
