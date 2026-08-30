"""
screener/check_nifty_banknifty_expiries.py

One-off diagnostic -- fetches the REAL, live raw option chain for
NIFTY and BANKNIFTY and prints the full expiryData list exactly as
Fyers returns it, so the weekly-expiry positional tracker gets built
against CONFIRMED real data instead of an assumed field name, order,
or format.

Real questions this answers, none of which the code alone can:
  - Does NIFTY (and/or BANKNIFTY) currently have a genuine WEEKLY
    expiry listed at all right now -- SEBI has changed which indices
    carry weekly index options more than once.
  - What does each expiryData entry actually look like (field names,
    whether "expiry" really is an epoch timestamp suitable for
    get_option_chain()'s own timestamp= parameter).
  - Is expiryData genuinely sorted nearest-first, the way
    get_nearest_expiry_days() already assumes elsewhere in this
    project (worth confirming independently, not re-trusting the same
    assumption twice).

Uses get_option_chain() directly (NOT get_option_analytics(), which
never passes a timestamp at all) with a small strikecount, since only
expiryData is needed here -- not the full chain.

Run as a standalone script:
    cd backend
    venv\\Scripts\\activate
    python -m screener.check_nifty_banknifty_expiries
"""
from .fyers_client import get_option_chain, is_authenticated

# Confirmed Fyers symbols from this project's own existing code
# (views.py's index-quote fetch), not guessed here.
SYMBOLS = {"NIFTY": "NSE:NIFTY50-INDEX", "BANKNIFTY": "NSE:NIFTYBANK-INDEX"}


def main():
    if not is_authenticated():
        print("Not authenticated -- run get_fyers_token.py first, then re-run this.")
        return

    for name, symbol in SYMBOLS.items():
        print(f"\n{'=' * 60}\n{name} ({symbol})\n{'=' * 60}")
        raw = get_option_chain(symbol, strikecount=2)  # small strikecount -- only expiryData matters here
        if not raw:
            print("  Fetch returned nothing (network/auth issue) -- see the [Fyers] error line above.")
            continue
        if raw.get("s") != "ok":
            print(f"  Response not ok: {raw}")
            continue

        expiry_data = (raw.get("data") or {}).get("expiryData", [])
        if not expiry_data:
            print("  No expiryData in the response at all -- raw response:")
            print(f"  {raw}")
            continue

        print(f"  {len(expiry_data)} expiries returned, in this EXACT order Fyers sent them:")
        for i, e in enumerate(expiry_data):
            print(f"    [{i}] {e}")

        print(f"\n  Days-to-expiry, if [0] is treated as nearest:")
        try:
            from datetime import datetime
            first_date = expiry_data[0].get("date")
            parsed = datetime.strptime(first_date, "%d-%m-%Y").date()
            days = (parsed - datetime.now().date()).days
            print(f"    [0]'s date ({first_date}) is {days} day(s) from today")
        except Exception as e:
            print(f"    Could not parse [0]'s date field: {e}")


if __name__ == "__main__":
    main()
