"""
backend/screener/fetch_volatility_history.py

Companion to volatility_probability.py -- fetches REAL historical daily
closes for exactly the symbols that appear in a real trade log, so
historical_volatility() has genuine data to compute from, not a guess.

Run this ON YOUR MACHINE (real Fyers access needed), not in any
sandbox -- it uses the project's own already-working fyers_client.py
and respects the existing rate-limit circuit breaker (paced calls,
same discipline as eod_scanner.py's own history fetch).

USAGE:
    cd backend
    venv\\Scripts\\activate
    python -m screener.fetch_volatility_history

Writes: backend/signal_logs/volatility_history.json
    {"SYMBOL": [{"date": "YYYY-MM-DD", "close": 123.45}, ...], ...}

Only fetches symbols not already in that file (safe to re-run --
won't re-fetch what's already there, same "don't waste real API calls"
discipline as eod_scanner.py's own freshness check).
"""
import json
import os
import time
from datetime import datetime, timedelta

# The exact 94 real symbols from the real 30-day trade log this was
# built to validate -- edit this list directly if validating a
# different date range with different symbols.
SYMBOLS = [
    'ABB', 'ANGELONE', 'ASTRAL', 'AUBANK', 'AUROPHARMA', 'BAJAJ-AUTO', 'BAJAJFINSV',
    'BAJAJHLDNG', 'BAJFINANCE', 'BANDHANBNK', 'BHARATFORG', 'BHARTIARTL', 'BHEL',
    'BIOCON', 'BOSCHLTD', 'BSE', 'CGPOWER', 'CHOLAFIN', 'COFORGE', 'COLPAL',
    'CROMPTON', 'CUMMINSIND', 'DIVISLAB', 'DIXON', 'DMART', 'DRREDDY', 'FEDERALBNK',
    'FORTIS', 'GODFRYPHLP', 'GODREJCP', 'GODREJPROP', 'GRASIM', 'GVT&D', 'HAVELLS',
    'HCLTECH', 'HDFCBANK', 'HEROMOTOCO', 'HINDALCO', 'HINDZINC', 'HYUNDAI', 'ICICIGI',
    'IDEA', 'IDFCFIRSTB', 'INDUSTOWER', 'INOXWIND', 'ITC', 'JINDALSTEL', 'JSWSTEEL',
    'JUBLFOOD', 'KALYANKJIL', 'KAYNES', 'KEI', 'KOTAKBANK', 'KPITTECH', 'LAURUSLABS',
    'LICHSGFIN', 'LODHA', 'M&M', 'MARICO', 'MAXHEALTH', 'MAZDOCK', 'MCX', 'MFSL',
    'MOTHERSON', 'MOTILALOFS', 'NATIONALUM', 'NAUKRI', 'NHPC', 'NYKAA', 'OIL',
    'PATANJALI', 'PAYTM', 'PFC', 'PGEL', 'PHOENIXLTD', 'PNB', 'PNBHOUSING',
    'PREMIERENE', 'RADICO', 'SIEMENS', 'SONACOMS', 'SUZLON', 'TCS', 'TECHM', 'TITAN',
    'TMPV', 'TVSMOTOR', 'UNIONBANK', 'UNITDSPR', 'UNOMINDA', 'VBL', 'VMM',
    'WAAREEENER', 'ZYDUSLIFE',
]

OUTPUT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "signal_logs", "volatility_history.json")
DAYS_BACK = 90  # comfortably more than enough for a stable historical_volatility() estimate


def run():
    from .fyers_client import get_history
    from .fyers_client import is_authenticated

    if not is_authenticated():
        print("Not authenticated with Fyers -- run get_fyers_token.py first, same as any other morning.")
        return

    existing = {}
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)

    to_fetch = [s for s in SYMBOLS if s not in existing]
    print(f"{len(existing)} symbols already have real history saved -- fetching the remaining {len(to_fetch)}.")

    range_to = datetime.now().date()
    range_from = range_to - timedelta(days=DAYS_BACK)

    for i, symbol in enumerate(to_fetch):
        fyers_symbol = f"NSE:{symbol}-EQ"
        resp = get_history(fyers_symbol, resolution="1D", range_from=str(range_from), range_to=str(range_to))
        if not resp or resp.get("s") != "ok" or not resp.get("candles"):
            print(f"  [{i+1}/{len(to_fetch)}] {symbol}: no real data available right now -- skipped honestly, not fabricated.")
            continue
        closes = [
            {"date": datetime.fromtimestamp(c[0]).strftime("%Y-%m-%d"), "close": c[4]}
            for c in resp["candles"] if len(c) >= 5
        ]
        closes.sort(key=lambda r: r["date"])  # same real ordering lesson from tonight's OptionHistoryView fix
        existing[symbol] = closes
        print(f"  [{i+1}/{len(to_fetch)}] {symbol}: {len(closes)} real daily closes saved.")

        # Same pacing discipline as eod_scanner.py's own history fetch --
        # don't hammer the API just because the circuit breaker would
        # technically allow it call-by-call.
        time.sleep(0.5)

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f)
    print(f"\nSaved real history for {len(existing)} symbols to {OUTPUT_FILE}")


if __name__ == "__main__":
    run()
