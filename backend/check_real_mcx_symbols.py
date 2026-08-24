"""
check_real_mcx_symbols.py

Standalone diagnostic -- pulls Fyers' own authoritative, currently-live
MCX symbol master file directly (the same file Fyers itself publishes
and updates daily) and filters it down to GOLD/SILVER entries. This is
the definitive answer to "what does Fyers actually list right now" --
no guessing at candidate symbol strings, no trial and error.

Run the same way your other check_*.py scripts run:
    python check_real_mcx_symbols.py
"""
import requests
import csv
import io

URL = "https://public.fyers.in/sym_details/MCX_COM.csv"

HEADERS = [
    "fytoken", "symbol_details", "exchange_instrument_type", "lot_size",
    "tick_size", "isin", "trading_session", "last_update", "expiry_date",
    "symbol_ticker", "exchange", "segment", "scrip_code", "underlying_symbol",
    "strike_price", "option_type", "extra1", "extra2", "extra3",
]  # best-effort header guess -- the real file may have a slightly
   # different column count; this script prints raw rows if parsing
   # by name fails, so nothing gets silently lost either way.


def main():
    print(f"Fetching {URL} ...\n")
    resp = requests.get(URL, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    content = resp.text
    print(f"Downloaded {len(content):,} bytes, {content.count(chr(10)):,} lines total.\n")

    reader = csv.reader(io.StringIO(content))
    rows = list(reader)

    matches = [r for r in rows if any("GOLD" in str(cell).upper() or "SILVER" in str(cell).upper() for cell in r)]

    print(f"Found {len(matches)} rows mentioning GOLD or SILVER anywhere in the row.\n")
    print("=" * 70)
    for r in matches:
        # Print the whole raw row -- safest option since the exact column
        # order/count isn't confirmed; nothing gets hidden or misparsed.
        print(" | ".join(str(c) for c in r))
    print("=" * 70)
    print(f"\n{len(matches)} real GOLD/SILVER rows currently live on Fyers' own MCX symbol master.")
    print("Compare the symbol strings above against what check_gold_silver_symbols.py tried --")
    print("that'll show directly whether the earlier 'no data' results were a wrong symbol")
    print("format, or genuinely correct (contract not actually listed).")


if __name__ == "__main__":
    main()
