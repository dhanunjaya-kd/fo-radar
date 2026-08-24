"""
check_real_mcx_symbols.py

Standalone diagnostic -- pulls Fyers' own authoritative, currently-live
MCX symbol master file directly and filters it to ONLY the GOLD/GOLDM/
SILVER/SILVERM FUTURES contracts (excludes the thousands of option
strikes -- CE/PE -- that buried the useful rows in the first version).

Writes the full match list to real_mcx_gold_silver_futures.txt
(so nothing gets lost in terminal scrollback) AND prints a clean,
sorted summary of just the symbol + expiry to the terminal directly.

Run the same way your other check_*.py scripts run:
    python check_real_mcx_symbols.py
"""
import requests
import csv
import io

URL = "https://public.fyers.in/sym_details/MCX_COM.csv"
BASES = ("GOLD", "GOLDM", "SILVER", "SILVERM")


def main():
    print(f"Fetching {URL} ...\n")
    resp = requests.get(URL, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    content = resp.text
    print(f"Downloaded {len(content):,} bytes.\n")

    reader = csv.reader(io.StringIO(content))
    rows = list(reader)

    # Only real FUTURES rows for these 4 bases -- symbol ticker ends in
    # "FUT" with no strike/option suffix, excludes every CE/PE option
    # strike (that's what buried the useful rows in the first version).
    futures_rows = []
    for r in rows:
        for cell in r:
            cell_str = str(cell).upper()
            if cell_str.endswith("FUT") and any(cell_str.startswith(f"MCX:{b}") for b in BASES):
                futures_rows.append((cell, r))
                break

    with open("real_mcx_gold_silver_futures.txt", "w") as f:
        for symbol, full_row in futures_rows:
            f.write(" | ".join(str(c) for c in full_row) + "\n")

    print(f"Found {len(futures_rows)} real FUTURES contracts (GOLD/GOLDM/SILVER/SILVERM only).")
    print(f"Full raw rows written to: real_mcx_gold_silver_futures.txt\n")
    print("=" * 60)
    print("SYMBOL -> EXPIRY (sorted)")
    print("=" * 60)
    seen = sorted(set(symbol for symbol, _ in futures_rows))
    for s in seen:
        print(f"  {s}")
    print("=" * 60)
    print(f"\n{len(seen)} distinct real, currently-live futures symbols.")
    print("Compare this list directly against what check_gold_silver_symbols.py tried earlier.")


if __name__ == "__main__":
    main()
