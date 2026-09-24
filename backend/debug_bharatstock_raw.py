"""
Run this from backend/ with your venv active:
    python debug_bharatstock_raw.py PERSISTENT

Prints the RAW response from get_stock() and get_financials() --
before any of this app's own field-name guessing touches it. Paste
the output back so the actual field names can be fixed for real,
instead of guessed again.
"""
import os
import sys
import json
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fno_sniper.settings')
django.setup()

from fundamentals_research.services import bharatstock_client as bsc

symbol = sys.argv[1] if len(sys.argv) > 1 else 'PERSISTENT'

print(f"\n{'='*60}\nRAW get_stock('{symbol}')\n{'='*60}")
try:
    stock = bsc.get_stock(symbol)
    print(json.dumps(stock, indent=2, default=str))
    print(f"\nTop-level keys: {list(stock.keys())}")
except Exception as e:
    print(f"FAILED: {e}")

print(f"\n{'='*60}\nRAW get_financials('{symbol}', 'annual')\n{'='*60}")
try:
    fin = bsc.get_financials(symbol, 'annual')
    print(json.dumps(fin, indent=2, default=str))
    print(f"\nTop-level keys: {list(fin.keys())}")
except Exception as e:
    print(f"FAILED: {e}")
