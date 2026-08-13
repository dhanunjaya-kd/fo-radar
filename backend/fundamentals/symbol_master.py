"""
backend/fundamentals/symbol_master.py

Full NSE equity symbol list, from Fyers' own public symbol master CSV
(no auth needed) -- confirmed real and current via web search:
https://public.fyers.in/sym_details/NSE_CM.csv

Filtered to plain "EQ" series (the NSE main board) by default,
excluding SME board and other thinly-traded series -- both price
history and fundamentals data quality tend to be unreliable for those.
This is a judgment call, not something Fyers or Screener dictates --
pass series=None for the full unfiltered list instead.

HONEST CAVEAT: the column index used below (9, for the Fyers symbol
column) is based on one real example row seen via research, not a
live fetch from this sandbox (no network access to public.fyers.in
here). Run get_nse_equity_symbols() and check the first few results
look like real symbols (e.g. "NSE:RELIANCE-EQ") before trusting it for
a full run across the whole list -- same verify-before-scale approach
as everything else in this project.
"""
import csv
import io
import requests

SYMBOL_MASTER_URL = "https://public.fyers.in/sym_details/NSE_CM.csv"
FYERS_SYMBOL_COLUMN = 9  # e.g. "NSE:TATAMOTORS-EQ" -- verify this live, see caveat above


def get_nse_equity_symbols(series="EQ"):
    """
    Returns a list of Fyers symbols (e.g. "NSE:RELIANCE-EQ") for every
    NSE-listed equity in the symbol master, optionally filtered to one
    series (default "EQ" -- the main board). Pass series=None for the
    full unfiltered list (includes SME board, illiquid/suspended
    series, etc.).

    Returns [] if the symbol master couldn't be fetched -- callers
    must treat that as "no data available right now," not proceed
    silently with an empty or wrong universe.
    """
    try:
        resp = requests.get(SYMBOL_MASTER_URL, timeout=30)
        if resp.status_code != 200:
            return []
    except Exception:
        return []

    symbols = []
    reader = csv.reader(io.StringIO(resp.text))
    for row in reader:
        if len(row) <= FYERS_SYMBOL_COLUMN:
            continue
        fyers_symbol = row[FYERS_SYMBOL_COLUMN]
        if not fyers_symbol.startswith("NSE:"):
            continue
        if series and not fyers_symbol.endswith(f"-{series}"):
            continue
        symbols.append(fyers_symbol)
    return symbols


if __name__ == "__main__":
    # Quick live sanity check -- confirms the column index assumption
    # above before this gets used for a real full-universe run.
    syms = get_nse_equity_symbols()
    print(f"Fetched {len(syms)} EQ symbols. First 10:")
    for s in syms[:10]:
        print(f"  {s}")
    if not syms or not syms[0].startswith("NSE:") or "-EQ" not in syms[0]:
        print("\n>>> WARNING: first symbol doesn't look right -- the column index may need adjusting.")
