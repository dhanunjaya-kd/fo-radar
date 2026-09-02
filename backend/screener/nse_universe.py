"""
nse_universe.py

Full NSE equity symbol universe, sourced 100% from Fyers' own published
symbol master CSV -- NOT Screener.in, NOT any third-party source.
Same "scan every cell for the pattern, don't assume a fixed column
index" technique this project's own check_real_mcx_symbols.py already
uses successfully for MCX_COM.csv -- proven pattern in this exact
project, just applied to NSE_CM.csv instead.
"""
import requests
import csv
import io

NSE_CM_URL = "https://public.fyers.in/sym_details/NSE_CM.csv"


def get_all_nse_equity_symbols():
    """
    Fetches Fyers' live NSE Capital Market symbol master and returns
    every regular EQUITY-series symbol (ends in "-EQ", matching this
    project's own convention used everywhere else -- f"NSE:{sym}-EQ").
    Excludes BE/SM/ETF/other series entirely, not just equity-series
    ones with a naming quirk -- those simply don't match the pattern.

    Returns a sorted list of full Fyers symbols (e.g. "NSE:RELIANCE-EQ"),
    or [] if the fetch fails -- never a guessed/cached fallback list.
    """
    try:
        resp = requests.get(NSE_CM_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    except Exception as e:
        print(f"[NSEUniverse] Failed to fetch symbol master: {e}")
        return []
    return _parse_equity_symbols(resp.text)


def _parse_equity_symbols(csv_text):
    """Separated from the fetch so this can be tested against synthetic
    CSV text without a real network call."""
    reader = csv.reader(io.StringIO(csv_text))
    symbols = set()
    for row in reader:
        for cell in row:
            cell_str = str(cell).upper().strip()
            if cell_str.startswith("NSE:") and cell_str.endswith("-EQ"):
                symbols.add(cell_str)
                break
    return sorted(symbols)
