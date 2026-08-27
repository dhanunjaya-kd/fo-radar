"""
check_fo_lot_sizes.py

Standalone diagnostic -- pulls Fyers' own authoritative, currently-live
NSE F&O symbol master file directly and inspects its real structure
before anything gets built on top of an assumed column layout.

Same reasoning as check_real_mcx_symbols.py already used for MCX
contract months: an unofficial third-party doc (a broker-headers
reference project) claims the column order is roughly

  fyToken, isin, exSymbol, symDetails, symTicker, exchange, segment,
  exSymName, exInstType, optType, strikePrice, minLotSize, tickSize,
  expiryDate, underFyToken, underExSymbol

-- but that's someone else's documentation of Fyers' format, not a
verified read of THIS project's actual live file. This script fetches
the real thing, prints raw sample rows for a few known FUTURES
contracts (WIPRO, HDFCBANK, NIFTY, BANKNIFTY) with each field's INDEX
labeled, so the real lot-size column can be confirmed by eye before
any resolver trusts it.

Filters to FUTURES rows only (symbol ending in "FUT") for a a small
set of known underlyings -- same "exclude the thousands of option
strikes that bury the useful rows" approach check_real_mcx_symbols.py
already uses for MCX, applied here to NSE F&O instead. A stock's
options share the same lot size as its own futures contract, so one
FUT row per underlying is enough to get that underlying's real lot
size -- no need to wade through every strike's CE/PE row separately.

Run the same way the other check_*.py scripts run:
    python check_fo_lot_sizes.py
"""
import requests
import csv
import io

URL = "https://public.fyers.in/sym_details/NSE_FO.csv"

# A deliberately small, known sample -- enough to confirm the column
# layout by eye (does the lot-size-looking column actually hold a
# sane integer for these specific, well-known contracts?), not an
# attempt to build the full resolver in this diagnostic.
SAMPLE_UNDERLYINGS = ("WIPRO", "HDFCBANK", "RELIANCE", "NIFTY", "BANKNIFTY")


def _find_underlying(symbol_str, underlyings):
    """Longest-match-first substring check -- guards against a shorter
    underlying's name being a literal substring of a longer one (e.g.
    'NIFTY' is contained inside 'BANKNIFTY': 'NIFTY' in 'BANKNIFTY' is
    True). A naive first-match check over the tuple in its written
    order would mislabel every BANKNIFTY row as NIFTY, since NIFTY
    happens to come first in SAMPLE_UNDERLYINGS above -- caught by
    testing this script's logic against a synthetic file before ever
    running it against the real one. Sorting candidates longest-first
    means the more specific name always wins."""
    upper = symbol_str.upper()
    for u in sorted(underlyings, key=len, reverse=True):
        if u in upper:
            return u
    return None


def main():
    print(f"Fetching {URL} ...\n")
    resp = requests.get(URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    content = resp.text
    print(f"Downloaded {len(content):,} bytes.\n")

    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    print(f"Total rows: {len(rows):,}")
    if rows:
        print(f"Columns in first row: {len(rows[0])}\n")

    # Raw look at the very first row, unfiltered -- confirms whether
    # this file actually has a header row or starts straight into data
    # (earlier Fyers community posts suggest NO header row -- worth
    # confirming directly rather than assuming).
    print("=" * 70)
    print("RAW FIRST ROW (to check for a header row):")
    print("=" * 70)
    if rows:
        for i, val in enumerate(rows[0]):
            print(f"  [{i}] {val}")
    print()

    # Only FUTURES rows (symbol ends in "FUT") for the sample underlyings
    # above -- excludes every CE/PE option strike, same as
    # check_real_mcx_symbols.py's approach for MCX.
    matches = []
    for r in rows:
        for cell in r:
            cell_str = str(cell).upper()
            if cell_str.endswith("FUT") and _find_underlying(cell_str, SAMPLE_UNDERLYINGS):
                matches.append((cell, r))
                break

    with open("real_nse_fo_lot_sample.txt", "w") as f:
        for symbol, full_row in matches:
            f.write(" | ".join(str(c) for c in full_row) + "\n")

    print(f"Found {len(matches)} FUTURES rows matching the sample underlyings.")
    print("Full raw rows written to: real_nse_fo_lot_sample.txt\n")

    print("=" * 70)
    print("SAMPLE ROWS -- every field printed with its index:")
    print("=" * 70)
    seen_underlyings = set()
    for symbol, full_row in matches:
        # Only show the FIRST (nearest-expiry, since the file appears
        # date-sorted per underlying in practice) match per underlying --
        # enough to confirm the column layout without a wall of output.
        underlying_tag = _find_underlying(symbol, SAMPLE_UNDERLYINGS) or symbol
        if underlying_tag in seen_underlyings:
            continue
        seen_underlyings.add(underlying_tag)
        print(f"\n--- {symbol} ---")
        for i, val in enumerate(full_row):
            print(f"  [{i}] {val}")
    print("\n" + "=" * 70)
    print(f"\nShowed {len(seen_underlyings)} of {len(SAMPLE_UNDERLYINGS)} sample underlyings.")
    print("Missing ones (if any) may mean the near-expiry FUT contract wasn't")
    print("found by this simple string match -- check real_nse_fo_lot_sample.txt")
    print("directly for anything that got missed.")
    print("\nShare this terminal output back -- once the real lot-size column")
    print("index is confirmed by eye, the actual resolver gets built against it.")


if __name__ == "__main__":
    main()
