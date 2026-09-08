"""
screener/lot_size_resolver.py

Aug 27 2026: resolves the REAL, currently-live NSE F&O lot size for
any underlying (stock or index) directly from Fyers' own symbol
master file -- confirmed empirically against 5 known contracts
(BANKNIFTY=30, FINNIFTY=60, HDFCBANK=650, RELIANCE=500, WIPRO=3000,
all sane real-world values) via check_fo_lot_sizes.py before this was
ever built. Same "probe real Fyers data, don't hardcode a table that
goes stale" principle already used for MCX rollover dates and bullion
contract months elsewhere in this project -- NSE periodically revises
lot sizes too (SEBI reviews these based on price bands), so a
hardcoded 208-symbol table would silently drift wrong exactly like
the old MCX day-of-month threshold did.

CONFIRMED REAL COLUMN LAYOUT (NOT what a third-party doc claimed --
that turned out wrong when actually checked against the live file):
  [3]  = lot size (int)
  [9]  = real Fyers symbol ticker, e.g. "NSE:WIPRO26SEPFUT"
  [13] = clean underlying name, e.g. "WIPRO", "BANKNIFTY"
  [16] = option type -- "XX" means this row is a FUTURES contract,
         not an option strike

Sep 9 2026: extended to also cache column [9] (the real futures
ticker) alongside lot size -- same fetch, same cache, same "first row
found per underlying is the near-month expiry" logic already
established for lot size; get_futures_symbol() below is a second
accessor into the SAME table, not a second fetch or a second contract
resolver. Added for stock-level Futures OI confirmation, which needs
the actual tradeable futures symbol to query market depth on
(index_tracker.py's snapshot_index() already does the equivalent for
NIFTY/BANKNIFTY via its own _front_month_futures_symbol() -- that one
stays index-specific and untouched; this is the stock counterpart,
reusing this file's existing infrastructure rather than duplicating
that index-only function or inventing a third resolver).

MATCHING METHOD -- exact equality on column [13] only, NOT substring
matching: the diagnostic run against the real file caught a genuine
bug from an earlier, looser version -- scanning free-text descriptions
for a substring match let "FINNIFTY 29 Sep 26 FUT" get mistaken for a
NIFTY row, because "NIFTY" happens to be a literal substring of
"FINNIFTY" (same trap as "NIFTY" being a substring of "BANKNIFTY",
caught earlier). Column [13] is a clean, purpose-built underlying-name
field -- an EXACT match against it makes this entire bug class
structurally impossible rather than something to keep patching one
collision at a time.

Cached once per day (73k+ rows -- too large to re-fetch every signal
cycle) via the same day-scoped cache pattern used throughout this
project (views.py's _history_cache, index_tracker.py's bullion symbol
caches).
"""
import csv
import io
from datetime import datetime

import requests

SYMBOL_MASTER_URL = "https://public.fyers.in/sym_details/NSE_FO.csv"
FUTURES_OPTION_TYPE = "XX"  # confirmed real value at column [16] for a non-option (futures) row

_lot_size_cache = {"date": None, "table": {}}


def _fetch_and_parse_lot_sizes():
    """
    Real network call -- fetches the live ~13MB symbol master and
    builds {underlying_name: {"lot_size": int, "symbol": str}} from
    FUTURES rows only (column [16] == 'XX', i.e. not a CE/PE option
    strike -- excludes the thousands of option rows that would
    otherwise bury the ~200 useful ones, same principle
    check_real_mcx_symbols.py already uses for MCX). Keeps the FIRST
    futures row found per underlying (near-month expiry, since the
    file appears date-ordered) -- lot size doesn't vary by expiry
    month for a given underlying, so there's no need to prefer a
    specific one; the futures SYMBOL captured alongside it is
    therefore also the near-month contract, which is exactly the
    "nearest valid futures contract" a live OI read should use.

    Returns {} on any failure -- callers must treat an empty/missing
    lookup as "unknown for this symbol right now," never guess a
    number/symbol or fall back to old defaults silently.
    """
    table = {}
    try:
        resp = requests.get(SYMBOL_MASTER_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    except Exception as e:
        print(f"[LotSizeResolver] Failed to fetch symbol master: {e}")
        return table

    reader = csv.reader(io.StringIO(resp.text))
    for row in reader:
        if len(row) < 17:
            continue
        try:
            if row[16] != FUTURES_OPTION_TYPE:
                continue  # a CE/PE option strike, not the futures row we want
            underlying = row[13].strip().upper()
            lot_size = int(row[3])
            fut_symbol = row[9].strip()
            if underlying and lot_size > 0 and underlying not in table:
                table[underlying] = {"lot_size": lot_size, "symbol": fut_symbol or None}
        except (ValueError, IndexError):
            continue  # a malformed row -- skip it rather than let a bad row crash the whole fetch
    return table


def get_lot_size(underlying_symbol):
    """
    Real, live NSE lot size for `underlying_symbol` (e.g. 'WIPRO',
    'NIFTY', 'BANKNIFTY') -- refetches the full symbol master once per
    calendar day, cached in-process for the rest of that day (same
    cost/freshness tradeoff as every other daily-cached resolver in
    this project). Returns None (never a guessed number) if the
    symbol isn't found in the live file, or if today's fetch failed
    AND no previous successful fetch exists to fall back on -- caller
    must handle None explicitly (skip the signal / trade rather than
    silently defaulting to some quantity).

    A failed fetch on a given day does NOT wipe out yesterday's still-
    good table -- only a genuinely successful fetch replaces the
    cache, so a transient network hiccup doesn't suddenly make every
    lot size unresolvable for the rest of that day.
    """
    global _lot_size_cache
    today_str = datetime.now().strftime("%Y-%m-%d")
    if _lot_size_cache["date"] != today_str:
        table = _fetch_and_parse_lot_sizes()
        if table:
            _lot_size_cache = {"date": today_str, "table": table}
        elif not _lot_size_cache["table"]:
            return None  # never had a successful fetch at all -- nothing to fall back to

    entry = _lot_size_cache["table"].get(underlying_symbol.strip().upper())
    return entry["lot_size"] if entry else None


def get_futures_symbol(underlying_symbol):
    """
    Sep 9 2026: the real, live, near-month Fyers futures ticker for
    `underlying_symbol` (e.g. "NSE:WIPRO26SEPFUT") -- second accessor
    into the SAME daily-cached table get_lot_size() already
    maintains, not a second fetch or a second contract resolver. Same
    None-on-unknown contract as get_lot_size(): never guesses a
    symbol, caller must treat None as "can't resolve a futures
    contract for this underlying right now" and skip rather than
    invent one.
    """
    global _lot_size_cache
    today_str = datetime.now().strftime("%Y-%m-%d")
    if _lot_size_cache["date"] != today_str:
        table = _fetch_and_parse_lot_sizes()
        if table:
            _lot_size_cache = {"date": today_str, "table": table}
        elif not _lot_size_cache["table"]:
            return None

    entry = _lot_size_cache["table"].get(underlying_symbol.strip().upper())
    return entry["symbol"] if entry else None


def get_lot_size_table_age():
    """How stale the in-memory table is -- None if never successfully
    fetched. Useful for a status/debug endpoint, not required for the
    core lookup itself."""
    return _lot_size_cache["date"]
