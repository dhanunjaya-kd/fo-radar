"""
Run from backend/ with your venv active:
    pip install yfinance
    python debug_yfinance_raw.py RELIANCE

Prints yfinance's ACTUAL current field names for an NSE stock. Yahoo's
own internal API drives these field names directly (yfinance just
passes them through) -- they've changed before and could again, so
this checks reality instead of trusting remembered/documented names.

Unlike the BharatStock script, this doesn't need Django or your .env --
yfinance needs no key at all. Paste the output back and the actual
integration gets built from it, not guessed.
"""
import sys
import json

try:
    import yfinance as yf
except ImportError:
    print("Run: pip install yfinance")
    sys.exit(1)

symbol = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE"
ticker = yf.Ticker(f"{symbol}.NS")  # .NS = NSE; yfinance's real, documented suffix convention

print(f"\n{'='*60}\nRAW .info for {symbol}.NS\n{'='*60}")
try:
    info = ticker.info
    print(json.dumps(info, indent=2, default=str))
    print(f"\nKeys ({len(info)} total): {sorted(info.keys())}")
except Exception as e:
    print(f"FAILED: {e}")

print(f"\n{'='*60}\nRAW .financials (annual income statement)\n{'='*60}")
try:
    fin = ticker.financials
    print(fin.to_string())
    print(f"\nRow labels: {list(fin.index)}")
except Exception as e:
    print(f"FAILED: {e}")

print(f"\n{'='*60}\nRAW .balance_sheet\n{'='*60}")
try:
    bs = ticker.balance_sheet
    print(bs.to_string())
    print(f"\nRow labels: {list(bs.index)}")
except Exception as e:
    print(f"FAILED: {e}")

print(f"\n{'='*60}\nRAW .cashflow\n{'='*60}")
try:
    cf = ticker.cashflow
    print(cf.to_string())
    print(f"\nRow labels: {list(cf.index)}")
except Exception as e:
    print(f"FAILED: {e}")
