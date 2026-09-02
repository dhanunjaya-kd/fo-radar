"""
screener/index_tracker.py

Time-series tracker for NIFTY and BANKNIFTY index option chains only
(per explicit request -- not individual stocks). Every scan cycle, takes
a snapshot of each index's option-chain analytics (PCR, ATM/adjacent
Put & Call OI with writing/unwinding status, chain-wide Total Put/Call
OI, IV, support/resistance, Max Pain, a derived directional Bias, and
whether the index's actual price move agrees with that Bias) and appends
it as a new row to a daily Excel file -- same "auto-log, one file per
day" pattern as excel_logger.py, so you get a running intraday history
instead of only the current snapshot.

Now also tracks crude oil (CRUDEOIL standard + CRUDEOILM mini, on MCX)
the same way, via snapshot_commodity()/snapshot_all_commodities() below
-- structurally different from the index path above, since commodities
have no separate spot/cash index: the front-month FUTURES contract
itself is both the option chain's underlying AND the OI/price source,
one symbol doing both jobs (confirmed via check_crude_oil_options.py --
bare "MCX:CRUDEOIL" fails, the actual futures contract symbol works).
Spot and VIX are left blank for commodities rather than faked. Also
runs on its own longer MCX session (roughly 9 AM-11:30 PM) via
is_mcx_hours() below, independent of market_hours.py's NSE-only
is_market_hours() -- deliberately a separate, local check rather than
modifying that shared file, since several other things already depend
on its exact NSE-only behavior.

FUTURES PRICE + OI: symbol format empirically confirmed via
find_futures_symbol.py against a live session (NSE:{INDEX}{YY}{MON}FUT,
e.g. NSE:NIFTY26AUGFUT) -- not guessed. Price used to come from a
separate quotes() call; Open Interest genuinely isn't exposed there
(confirmed live, matches Fyers' own docs) -- so "Fut OI Chg" was left
out rather than faked, until now.

Both are now sourced from ONE get_market_depth() call instead: Fyers'
Market Depth API returns ltp (price), oi (current), pdoi (previous
day's OI), and oipercent (day-over-day OI change %) together -- so this
also replaces the old separate price-only quotes() call, one FEWER API
call per snapshot rather than one more. Confirmed live via
check_futures_oi_via_depth.py before wiring in.

Fut OI Chg uses Fyers' own oipercent (vs previous day's close) rather
than an intraday snapshot-to-snapshot delta -- deliberately different
from Put OI Chg / Call OI Chg below, which ARE intraday deltas (that's
the only baseline the option-chain endpoint gives for those). Day-over-
day is the more standard "OI Chg" reading and what reference platforms
actually show.
"""
import os
import threading
import tempfile
import zipfile
from datetime import datetime, timedelta

try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font, PatternFill
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "signal_logs")

INDEX_SYMBOLS = {
    "NIFTY": "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
}

# Commodities (MCX) work differently from the indices above -- there's
# no separate spot/cash index symbol to give an option chain; the
# front-month FUTURES contract IS the underlying. So this is just the
# base name to build that rolling symbol from, not a static Fyers
# symbol like INDEX_SYMBOLS holds.
COMMODITY_BASES = {
    "CRUDEOIL": "CRUDEOIL",
    "CRUDEOILM": "CRUDEOILM",
    "GOLD": "GOLD",
    "GOLDM": "GOLDM",
    "SILVER": "SILVER",
    "SILVERM": "SILVERM",
}

# Aug 20 2026: Crude trades in (almost) every calendar month, so a
# simple day-of-month rollover works for it (_front_month_commodity_
# symbol below). Gold/Silver do NOT -- confirmed empirically via
# check_gold_silver_symbols.py against live Fyers data, same day:
#   GOLD:    Oct/Dec live, Aug/Sep/Nov not  -- roughly bi-monthly
#   GOLDM:   Sep/Oct/Nov/Dec all live       -- roughly monthly
#   SILVER:  Sep/Dec live, Aug/Oct/Nov not  -- irregular
#   SILVERM: Aug/Nov live, Sep/Oct/Dec not  -- irregular, different
#            pattern from SILVER despite the name similarity
# None of the four match Crude's pattern, and SILVER/SILVERM don't even
# match each other -- a static "valid months" table would need separate,
# hand-confirmed entries per base and would still go stale exactly like
# Crude's hardcoded threshold did. _front_month_bullion_symbol() below
# probes live Fyers data instead of guessing.
_NEAR_MONTHLY_BASES = {"CRUDEOIL", "CRUDEOILM"}

# Every name the frontend/views.py is allowed to ask this module about --
# single source of truth so a new commodity/index added here doesn't
# also require hunting down every hardcoded ("NIFTY", "BANKNIFTY") tuple
# elsewhere in the project.
TRACKABLE_NAMES = tuple(INDEX_SYMBOLS) + tuple(COMMODITY_BASES)


def _last_thursday(year, month):
    """Last Thursday of the month -- NSE's monthly F&O expiry day."""
    if month == 12:
        next_month_first = datetime(year + 1, 1, 1)
    else:
        next_month_first = datetime(year, month + 1, 1)
    d = next_month_first - timedelta(days=1)
    while d.weekday() != 3:  # Thursday
        d -= timedelta(days=1)
    return d


def _front_month_futures_symbol(index_name):
    """Confirmed-working format: NSE:{INDEX}{YY}{MON}FUT. Rolls to next
    month automatically once the current month's contract has expired."""
    today = datetime.now()
    expiry = _last_thursday(today.year, today.month)
    if today > expiry:
        y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    else:
        y, m = today.year, today.month
    yy = str(y)[2:]
    mon = datetime(y, m, 1).strftime("%b").upper()
    return f"NSE:{index_name}{yy}{mon}FUT"


def _front_month_commodity_symbol(base):
    """Approximate rollover for MCX commodities -- unlike NSE indices
    (always the last Thursday of the month, a fixed rule), MCX contract
    expiry days vary by commodity and follow the underlying's
    international contract calendar (crude oil specifically expires
    ~19th-20th most months, a few working days ahead of the NYMEX WTI
    contract it tracks). A fixed day-of-month is not a real MCX
    holiday-aware expiry calendar, but it's safe in the sense that it
    rolls AFTER crude oil's contract has actually expired, not before.

    Aug 20 2026: was hardcoded to 20 based on "usually the 19th-20th" --
    but THIS month's real, confirmed expiry was 17-Aug-2026, three days
    earlier than that generic assumption. That gap meant Crude showed
    zero for three real days (18th-20th) -- the code kept requesting
    the already-expired August contract, which Fyers correctly returns
    nothing for. Moved the threshold to 17 to match what's now actually
    confirmed. This is still a per-month approximation, not a real MCX
    holiday-aware calendar -- re-check next month whether 17 still
    holds or needs adjusting again, same as this comment already said
    for a different commodity."""
    today = datetime.now()
    if today.day > 17:
        y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    else:
        y, m = today.year, today.month
    yy = str(y)[2:]
    mon = datetime(y, m, 1).strftime("%b").upper()
    return f"MCX:{base}{yy}{mon}FUT"


_bullion_symbol_cache = {}  # {base: {'date': 'YYYY-MM-DD', 'symbol': str|None}}


def _front_month_bullion_symbol(base):
    """
    GOLD/GOLDM/SILVER/SILVERM front-month resolution -- structurally
    different from _front_month_commodity_symbol() above because these
    don't trade in every calendar month (see COMMODITY_BASES' comment
    for the real confirmed data). A day-of-month threshold can't
    represent "this month simply has no contract at all," so this
    probes candidate months forward from today via a real Fyers
    get_market_depth() call and uses whichever is actually confirmed
    live -- empirical, not guessed.

    Cached per base for the rest of the calendar day (contract-month
    validity doesn't change intraday, so there's no need to re-probe on
    every snapshot cycle -- same spirit as every other cache in this
    file, just keyed by date instead of a TTL). Tries up to 6 months
    forward before giving up; that comfortably covers every gap seen in
    the real Aug 20 2026 data (the widest was GOLD's Aug-to-Oct, a
    2-month gap).

    Returns None (not a guessed symbol) if nothing live turns up in
    that window -- callers must treat None as "can't snapshot this
    right now," never invent a placeholder price.
    """
    from .fyers_client import get_market_depth
    today_str = datetime.now().strftime("%Y-%m-%d")
    cached = _bullion_symbol_cache.get(base)
    if cached and cached.get("date") == today_str:
        return cached.get("symbol")

    today = datetime.now()
    y, m = today.year, today.month
    for _ in range(6):
        yy = str(y)[2:]
        mon = datetime(y, m, 1).strftime("%b").upper()
        candidate = f"MCX:{base}{yy}{mon}FUT"
        try:
            resp = get_market_depth(candidate)
            if resp and resp.get("s") == "ok":
                d = (resp.get("d", {}) or {}).get(candidate, {})
                if d.get("ltp"):
                    _bullion_symbol_cache[base] = {"date": today_str, "symbol": candidate}
                    return candidate
        except Exception as e:
            print(f"[IndexTracker] {base} front-month probe failed for {candidate}: {e}")
        m += 1
        if m > 12:
            m = 1
            y += 1

    print(f"[IndexTracker] {base}: no live contract found in the next 6 months -- "
          f"re-run check_gold_silver_symbols.py to confirm what's actually listed")
    _bullion_symbol_cache[base] = {"date": today_str, "symbol": None}
    return None


_bullion_options_symbol_cache = {}  # {base: {'date': 'YYYY-MM-DD', 'symbol': str|None}} -- separate cache from _bullion_symbol_cache, deliberately not shared (see docstring below)


def _front_month_bullion_symbol_with_options(base):
    """
    Aug 24 2026: stricter sibling of _front_month_bullion_symbol() above,
    built after a real bug: that function's validation is "does
    get_market_depth() return an LTP" -- which is NOT sufficient to
    confirm a contract is genuinely tradeable. An EXPIRED contract can
    still return a stale last-known LTP without erroring (confirmed
    live: MCX:GOLD26AUGFUT returned LTP=145234 today even though the
    real Fyers symbol master shows August Gold has already rolled off
    -- only Oct/Dec are actually current). Since options chains don't
    exist for expired futures, this was the exact root cause of
    OptionAnalyticsView returning "No option chain returned" for GOLD/
    GOLDM despite a "live-looking" resolved symbol.

    This variant additionally requires get_option_analytics() to
    return real rows for the SAME candidate -- not just a futures
    price. Deliberately a SEPARATE function (not a modification of the
    one above) because index_tracker.py's own snapshot_commodity()
    only ever needed futures price, never options -- tightening the
    shared resolver's validation would have been a real risk of
    breaking that already-working caller for a problem it doesn't have.
    Only OptionAnalyticsView (views.py), which actually needs a usable
    options chain, should call this one.

    Same cached-per-day, none-if-nothing-found contract as the sibling
    function -- separate cache dict since a symbol valid for futures-
    only purposes may not be valid here, and vice versa in principle.
    """
    from .fyers_client import get_market_depth, get_option_analytics
    today_str = datetime.now().strftime("%Y-%m-%d")
    cached = _bullion_options_symbol_cache.get(base)
    if cached and cached.get("date") == today_str:
        return cached.get("symbol")

    today = datetime.now()
    y, m = today.year, today.month
    for _ in range(6):
        yy = str(y)[2:]
        mon = datetime(y, m, 1).strftime("%b").upper()
        candidate = f"MCX:{base}{yy}{mon}FUT"
        try:
            depth = get_market_depth(candidate)
            has_ltp = bool(depth and depth.get("s") == "ok" and (depth.get("d", {}) or {}).get(candidate, {}).get("ltp"))
            if has_ltp:
                oi = get_option_analytics(candidate, strikecount=2)  # small strikecount -- this call only needs to confirm rows exist, not the full chain
                if oi and oi.get("rows"):
                    _bullion_options_symbol_cache[base] = {"date": today_str, "symbol": candidate}
                    return candidate
        except Exception as e:
            print(f"[IndexTracker] {base} front-month+options probe failed for {candidate}: {e}")
        m += 1
        if m > 12:
            m = 1
            y += 1

    print(f"[IndexTracker] {base}: no contract with a real options chain found in the next 6 months")
    _bullion_options_symbol_cache[base] = {"date": today_str, "symbol": None}
    return None


def is_mcx_hours():
    """MCX commodities trade well past NSE's close -- roughly 9 AM to
    11:30 PM, vs NSE F&O's 9:15 AM-3:30 PM. Deliberately a separate,
    local check rather than modifying market_hours.py's is_market_hours()
    -- several other things already depend on that function's exact
    NSE-only behavior, and this doesn't need to touch it. Same
    approximation spirit as is_market_hours() (doesn't know MCX-specific
    holidays, only weekends) -- good enough to avoid an out-of-hours
    snapshot being logged as if real, not a full trading calendar."""
    now = datetime.now()
    if now.weekday() >= 5:  # Saturday/Sunday
        return False
    start = now.replace(hour=9, minute=0, second=0, microsecond=0)
    end = now.replace(hour=23, minute=30, second=0, microsecond=0)
    return start <= now <= end


COLUMNS = [
    "Time", "Spot", "Change %", "CAS Auction", "Fut", "Fut OI", "Fut OI Chg %", "PCR", "ATM Strike",
    "Put OI (ATM)", "Put OI Chg", "Put Status",
    "Call OI (ATM)", "Call OI Chg", "Call Status",
    "Total Put OI", "Total Call OI",
    "Highest Put OI Strike", "Highest Put OI Value",
    "Highest Call OI Strike", "Highest Call OI Value",
    "IV %", "IV %ile", "VIX", "Support", "Resistance", "Max Pain", "Max Pain Dist %",
    "OI Buildup", "Bias", "Price Confirms Bias",
    "Confirms 5min", "Confirms 30min", "Confirms 60min", "Horizons Confirming",
    # Sep 2 2026: Section 17 of the Index Bias audit -- surfaces the
    # vote breakdown _derive_bias() already computes internally but
    # previously discarded, plus the exact raw Momentum %/VIX Change %
    # values that vote used. Two purposes: (1) directly answers "show
    # confidence and evidence domains," (2) makes FUTURE forensic
    # analysis exact instead of approximated -- index_bias_forensics.py
    # currently has to reconstruct momentum/VIX-change from a 15-min
    # snapshot lookback since neither was persisted; from here forward,
    # both are logged directly, no approximation needed.
    "PCR Vote", "OI Buildup Vote", "ATM Balance Vote", "Max Pain Vote", "VIX Trend Vote", "Momentum Vote",
    "Momentum %", "VIX Change %",
    # Sep 2 2026: Phase 2 of the Index Bias audit -- decorrelated
    # engine, logged in PARALLEL for future comparison only. Never
    # read by any live signal-selection code; "Bias" above remains the
    # only value anything downstream acts on. See derive_bias_v2()'s
    # own docstring for the full evidence and honest caveats.
    "Bias V2", "Positioning Vote (V2)", "Structure Vote (V2)",
]

_lock = threading.Lock()
# Cache last snapshot's ATM strike so we can label Put/Call OI CHANGE
# (chg since the last row for this index today), same intraday-buildup
# idea as the reference table's "(High Vol)"/"unwinding" annotations.
_last_snapshot = {}  # {index_name: {'ce_oi': int, 'pe_oi': int}}

# Aug 27 2026: latest FULL option-chain analytics dict per name -- the
# same `oi` this module already fetches every cycle in snapshot_index()/
# snapshot_commodity() below, just also kept here so index_signal.py (a
# separate module -- turns a confirmed Bias into an actual tradeable
# call) can read live per-strike premium/delta data via
# get_last_oi_snapshot() WITHOUT a second option-chain fetch. Avoids
# exactly the kind of redundant-fetch rate-limit risk this project
# already hit once for real (the Aug 20 2026 429 incident).
_last_oi_snapshot = {}  # {name: oi_dict}


def get_last_oi_snapshot(name):
    """Read-only accessor for the latest full option-chain analytics
    dict snapshotted this process -- None if nothing's been snapshotted
    yet (right after a restart, or outside trading hours)."""
    return _last_oi_snapshot.get(name)

# Aug 28 2026: (name, date_str) pairs whose snapshot file is CONFIRMED
# genuinely corrupted (a real zipfile.BadZipFile, not "doesn't exist
# yet" or a transient lock) -- once get_snapshots_for_date() below hits
# this for real, remember it so the recurring lookback scans that read
# many past dates every cycle (compute_iv_percentile() checks the last
# 30 days, EVERY snapshot cycle -- confirmed live: a real corrupted
# Aug 26 CRUDEOIL/CRUDEOILM file was being re-attempted and re-logged
# roughly once a minute, all day, for no benefit) stop retrying and
# re-logging a file already known broken. Cleared only by a process
# restart -- if the file gets manually replaced/fixed, a restart picks
# that up, same convention every other in-memory cache in this file
# already follows.
_known_corrupted_dates = set()  # {(name, date_str), ...}

# Direction memory for the flip log below -- {index_name: 'up'|'down'}.
# Same no-explicit-day-reset convention as _last_snapshot above: relies
# on the daily process restart to naturally clear it, exactly like that
# cache already does. In the rare case the server runs across a
# midnight boundary without restarting, the very first flip check of
# the new day compares against the previous day's last direction --
# same accepted tradeoff _last_snapshot already has, not a new one.
_last_direction = {}
# Exact previous Bias STRING (not just direction) per name -- purely
# for an accurate "From Bias" label in the Flips sheet (e.g. "Bearish
# (Strong)", not just "Bearish"). Updated on the same condition as
# _last_direction above (directional readings only, Neutral doesn't
# overwrite it) so the two stay in sync -- "From Bias" always shows the
# last real directional reading, not an intervening Neutral dip that
# happened to sit between it and the actual flip.
_last_bias_string = {}

# Aug 24 2026: latest commodity day-change% per base, populated at the
# end of snapshot_commodity() below. Feeds _get_cross_asset_snapshot()
# so a NIFTY/BANKNIFTY flip can log what Crude/Gold/Silver were doing
# at that moment -- an approximation of "global cues" using data this
# project already fetches live, since true external data (SGX/Dow
# futures) isn't available on this Fyers account (see
# check_gift_nifty.py, built Aug 23, never yet run). Same
# no-explicit-day-reset convention as _last_snapshot/_last_direction
# above.
_last_commodity_readings = {}  # {base: {'change_pct': float, 'fut': float}}
_CROSS_ASSET_BASES = ["CRUDEOIL", "GOLD", "SILVER"]  # Standard contracts only -- the Mini variants (CRUDEOILM/GOLDM/SILVERM) track the same underlying price, so they'd just duplicate this signal


def _get_cross_asset_snapshot():
    """
    Latest logged day-change% for Crude/Gold/Silver, read from this
    process's own in-memory cache -- NOT a fresh Fyers fetch. Log-only
    consumer (see _log_flip_if_changed): a NIFTY/BANKNIFTY flip records
    whatever's in this cache at that instant, nothing gates on it yet.

    Staleness note: snapshot_all() (NIFTY/BANKNIFTY) and
    snapshot_all_commodities() run back-to-back in the same
    _index_snapshot_worker() cycle (views.py), commodities second -- so
    the FIRST flip logged after a restart may still see empty/stale
    commodity readings from the previous ~60s cycle, same reuse-not-
    refetch tradeoff already accepted for `vix` being passed into
    snapshot_index() rather than re-fetched. Returns None per base if
    nothing's been snapshotted yet this process (right after a restart,
    or genuinely outside MCX hours).
    """
    with _lock:
        return {base: _last_commodity_readings.get(base, {}).get("change_pct") for base in _CROSS_ASSET_BASES}

# Rolling in-memory price history, used by _price_confirms_bias() via
# _record_and_get_multi_horizon_changes() below -- REPLACES the old
# previous-close-based Change % as that function's input. {name:
# [(datetime, price), ...]}, oldest first, pruned to _MAX_WINDOW_MINUTES
# on every write. Real production data (Aug 10-14 2026) showed why this
# was needed: the old day-cumulative check missed a genuine ~55-65pt
# NIFTY intraday move because the day's NET change (from previous
# close) happened to be small -- a real divergence during a real swing,
# invisible to a check that only sees where the day nets out. Resets on
# restart -- same honest "no comparison yet" window as Put/Call OI Chg
# already has on the first row after any (re)start.
_recent_prices = {}

# Aug 27 2026: rolling in-memory VIX history, same pattern as
# _recent_prices above but ONE shared series (not per-index) since
# India VIX is a single market-wide number, not per-symbol. Feeds the
# VIX-trend vote in _derive_bias() below -- see that function's
# docstring for why this was added.
_recent_vix = []  # [(datetime, value), ...]
_VIX_TREND_LOOKBACK_MINUTES = 15

# Aug 20 2026: multi-horizon confirmation (accuracy backlog #5). Instead
# of one ~15-min price-vs-Bias check, compute the SAME confirmation at
# several lookback windows and show them together -- a move that agrees
# across the fast AND slow horizon is real signal; a move that only
# shows up on the fastest horizon and vanishes on longer ones is noise,
# not a genuine trend. Directly answers a real question raised live:
# does a faster snapshot cadence give "more accuracy" than a slower one
# (no to both, on their own -- same underlying live data either way,
# just more exposed to noise at short intervals or more lag at long
# ones). Multi-horizon gets the benefit of both without picking one
# cadence over the other.
#
# 15min is kept as its own unchanged "Price Confirms Bias" column (same
# thresholds, same calculation as before) so the Aug 14 backtest
# baseline stays directly comparable -- the new horizons are additions
# alongside it, not a replacement.
CONFIRMATION_HORIZONS = [5, 15, 30, 60]  # minutes
_MAX_WINDOW_MINUTES = max(CONFIRMATION_HORIZONS)  # how much history to retain -- covers every horizon above


def _date_path(index_name, date_str):
    """Same file-naming pattern used for daily logging, for any date --
    read-only, doesn't create the directory (a missing folder just
    means nothing was logged that date, not an error)."""
    return os.path.join(LOG_DIR, date_str, f"index_tracker_{index_name}_{date_str}.xlsx")


def _today_path(index_name):
    today = datetime.now().strftime("%Y-%m-%d")
    os.makedirs(os.path.join(LOG_DIR, today), exist_ok=True)  # only the write path needs to create the folder
    return _date_path(index_name, today)


FLIPS_COLUMNS = ["Date", "Time", "From Bias", "To Bias", "Price", "Price Confirms Bias", "OI Buildup", "Crude Chg %", "Gold Chg %", "Silver Chg %"]


def _ensure_flips_sheet(wb):
    """
    Aug 20 2026: persistent flip/state-change log, one row per genuine
    directional change (Bullish-family <-> Bearish-family, or Neutral
    into a direction) -- NOT every Bias string change (Bullish ->
    Bullish (Strong) is an intensity change, not a flip, same
    distinction backtest_index_bias.py's DIRECTIONAL_BIASES/direction()
    logic already draws). Replaces having to reconstruct this by hand
    from raw snapshots (done manually via a one-off script earlier this
    project) with something that's just there going forward, and feeds
    directly into re-testing the flip-reversal hypothesis once enough
    real flips accumulate.

    Called from _get_workbook() so this sheet exists in all three cases
    that function handles: a brand new file, a schema-migrated fresh
    file, and -- importantly -- a file that already existed from BEFORE
    this feature shipped, which would otherwise have a valid Snapshots
    sheet but no Flips sheet, and crash the first time something tries
    to read it.

    Aug 24 2026: also migrates the Flips sheet IN PLACE if its own
    header doesn't match the current FLIPS_COLUMNS (e.g. today's file
    already has a Flips sheet from before the 3 cross-asset columns
    were added). Deliberately does NOT go through _get_workbook()'s
    full-workbook archive-and-reset -- that path exists for a Snapshots
    mismatch and would ALSO wipe today's entire Snapshots history
    (hundreds of rows by early afternoon) over an unrelated Flips-only
    column change, silently reopening the exact history-gap this
    project just fixed. Flips itself is tiny by comparison (real flips
    are rare -- 1 NIFTY, 0 BANKNIFTY in the first backtest run), so
    instead: rename the old sheet to "Flips_pre-update" (kept, not
    discarded) and create a fresh "Flips" with the current header. Only
    renames once per day -- if "Flips_pre-update" already exists from an
    earlier mismatch today, the stale "Flips" is dropped rather than
    overwriting that already-archived copy (same don't-clobber rule
    _get_workbook's archive_path check already follows).
    """
    if "Flips" in wb.sheetnames:
        ws = wb["Flips"]
        existing_header = [c.value for c in ws[1]] if ws.max_row >= 1 else []
        if existing_header == FLIPS_COLUMNS:
            return
        if "Flips_pre-update" not in wb.sheetnames:
            ws.title = "Flips_pre-update"
            print("[IndexTracker] Flips column layout changed -- archived old Flips rows to 'Flips_pre-update' sheet, starting fresh")
        else:
            wb.remove(ws)
    ws = wb.create_sheet("Flips")
    ws.append(FLIPS_COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")


def _atomic_save(wb, path):
    """
    Aug 28 2026: saves the workbook safely -- write to a temp file in
    the SAME directory first, then atomically swap it into place via
    os.replace(), rather than wb.save(path) writing directly to the
    real target.

    REAL bug this fixes: openpyxl (like any zip writer) writes a
    file's central directory LAST, at the very end of the save -- if
    the process gets interrupted anywhere before that (a crash, a
    Windows file-lock collision, auto_sync.py grabbing the file
    mid-write), the result is a file that LOOKS zip-like enough for
    Excel's lenient repair tool to offer to salvage it, but fails
    Python's stricter zipfile check outright with "File is not a zip
    file". Confirmed live: a real corrupted CRUDEOIL/CRUDEOILM file
    from Aug 26 showed exactly this signature -- Excel offered to
    recover it, openpyxl couldn't open it at all.

    os.replace() is atomic on both POSIX and Windows -- the real
    target path is either the complete OLD file or the complete NEW
    file at every instant, never a partially-written one, regardless
    of when an interruption happens. The temp file lives in the SAME
    directory as the target specifically because atomic replace only
    holds within one filesystem -- a temp file on a different drive
    would silently fall back to copy+delete, losing exactly the
    guarantee this exists to provide.
    """
    directory = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(suffix=".xlsx.tmp", dir=directory)
    os.close(fd)  # openpyxl needs a path to write to, not an open fd -- mkstemp is only used for its atomic unique-name creation
    try:
        wb.save(tmp_path)
        os.replace(tmp_path, path)
    except BaseException:
        # BaseException, not Exception -- a real interruption
        # (KeyboardInterrupt, or the process being killed via a signal
        # Python can still trap) needs this cleanup too, not just
        # ordinary exceptions. Safe to catch this broadly here
        # specifically because the ONLY action taken is deleting a
        # leftover temp file, and the original exception/interrupt is
        # ALWAYS re-raised unchanged right after -- this never
        # swallows or alters how the interruption propagates, it just
        # tidies up first. Caught live via this file's own test suite:
        # a simulated KeyboardInterrupt mid-write left an orphaned
        # .tmp file behind under the narrower `except Exception`.
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass  # best-effort cleanup -- don't let a cleanup failure mask the real error above
        raise


def _get_workbook(path):
    if os.path.exists(path):
        wb = load_workbook(path)
        ws = wb["Snapshots"]
        existing_header = [c.value for c in ws[1]]
        if existing_header != COLUMNS:
            # A code update changed the column layout since this file was
            # first created today (exactly what happened when Change %/
            # Total Put OI/Total Call OI/Price Confirms Bias were added
            # mid-session). Rewriting the header in place would silently
            # shift every existing row's data under the WRONG new headers
            # whenever a column was inserted anywhere but the very end --
            # tested this and confirmed it corrupts old rows rather than
            # fixing anything. Safer: archive the old file untouched and
            # start a fresh one with the current schema, rather than risk
            # quietly corrupting already-logged data.
            archive_path = path.replace(".xlsx", "_pre-update.xlsx")
            if not os.path.exists(archive_path):
                wb.save(archive_path)
                print(f"[IndexTracker] Column layout changed -- archived old data to {os.path.basename(archive_path)}, starting fresh for today")
            wb = Workbook()
            ws = wb.active
            ws.title = "Snapshots"
            ws.append(COLUMNS)
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
        _ensure_flips_sheet(wb)
        return wb
    wb = Workbook()
    ws = wb.active
    ws.title = "Snapshots"
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
    _ensure_flips_sheet(wb)
    return wb


def _record_and_get_vix_trend(vix, now=None):
    """
    Aug 27 2026: % change in VIX vs the reading from roughly
    _VIX_TREND_LOOKBACK_MINUTES ago -- one shared rolling series for
    the whole market (there's only one VIX number, not per-index),
    same prune-on-write pattern as _record_and_get_multi_horizon_
    changes() below uses for price. Rising VIX = rising fear = a
    bearish-leaning vote; falling VIX = calm = bullish-leaning. Feeds
    _derive_bias() as one of several independent votes -- see that
    function's docstring for the full context on why this was added.

    Returns None until there's a reading old enough to compare against
    (freshly (re)started, or fewer than the lookback minutes since
    market open) -- same honest "not enough history yet" signal every
    other rolling-window helper in this file already gives, rather
    than comparing against a too-recent or missing reading.
    """
    global _recent_vix
    if vix is None:
        return None
    now = now or datetime.now()
    with _lock:
        cutoff = now - timedelta(minutes=_VIX_TREND_LOOKBACK_MINUTES * 4)  # keep a bit more than strictly needed -- cheap, avoids edge-of-window misses
        while _recent_vix and _recent_vix[0][0] < cutoff:
            _recent_vix.pop(0)
        snapshot = list(_recent_vix)
        _recent_vix.append((now, vix))

    horizon_cutoff = now - timedelta(minutes=_VIX_TREND_LOOKBACK_MINUTES)
    oldest = next((entry for entry in snapshot if entry[0] >= horizon_cutoff), None)
    if oldest is None or not oldest[1]:
        return None
    return round((vix - oldest[1]) / oldest[1] * 100, 3)


# Aug 27 2026: margins for the vote-based Bias below. Need to LEAD by
# at least this many votes (out of up to 7) to call a direction at all
# -- a close split (e.g. 4 vs 3) stays Neutral rather than picking a
# side, same principle a reference NIFTY-tracking tool was seen using
# live (its own 7-factor vote: Bullish 3 / Bearish 4 -> Neutral, not
# Bearish). BIAS_VOTE_MARGIN_FOR_STRONG is a second, wider threshold
# for the "(Strong)" tag -- most votes agreeing, not just enough to
# clear the Neutral bar.
#
# HONEST LIMITATION: both numbers are a reasonable first cut, not
# empirically tuned -- same "watch and retune" status as every other
# threshold already documented in this file (the 0.05%/0.3% price-
# confirmation bands, the MCX day-17 rollover, etc.). The SHAPE of the
# fix (several independent votes, Neutral on a close split) is the
# actual correction; the exact margin numbers need real logged data
# before they can be trusted, not a single comparison point.
BIAS_VOTE_MARGIN_FOR_DIRECTION = 2
BIAS_VOTE_MARGIN_FOR_STRONG = 4  # was 5 out of 7 votes; 4 out of 6 holds roughly the same "most votes agree" proportion -- see _derive_bias()'s Aug 27 follow-up note for why the vote count dropped


def _pcr_vote(pcr):
    """Same tier boundaries the old single-signal version used, but
    now just ONE vote among several rather than the sole word on
    direction. Neutral zone (0.95-1.05) abstains rather than voting
    either way."""
    if pcr is None:
        return None
    if pcr > 1.05:
        return "bullish"
    if pcr < 0.95:
        return "bearish"
    return None


def _oi_buildup_vote(oi_buildup):
    """options_analytics.analyze_option_chain()'s plain label for
    TODAY's fresh chain-wide writing activity -- a meaningfully
    different signal from PCR (built-up OI over however many prior
    days) for the same reason the old version already used this as a
    modifier: PCR can stay 'Bullish' on old put OI just sitting there
    while today's actual writing goes the other way."""
    if oi_buildup == "PE writing dominant (bullish)":
        return "bullish"
    if oi_buildup == "CE writing dominant (bearish)":
        return "bearish"
    return None


def _atm_balance_vote(pe_oi, ce_oi):
    """Localized read at just the ATM strike -- deliberately separate
    from whole-chain PCR above, same 'today's flow vs built-up
    position' spirit as the PCR-vs-oi_buildup split already had.
    Requires a real +-10% imbalance to vote, not just any lean, so
    this doesn't fire on noise when the two sides are close to level."""
    if pe_oi is None or ce_oi is None or (pe_oi + ce_oi) == 0:
        return None
    diff_pct = (pe_oi - ce_oi) / (pe_oi + ce_oi)
    if diff_pct > 0.10:
        return "bullish"
    if diff_pct < -0.10:
        return "bearish"
    return None


def _max_pain_vote(price, max_pain):
    """Price tends to gravitate toward Max Pain by expiry -- price
    meaningfully ABOVE it implies downward pull (bearish vote),
    meaningfully BELOW implies upward pull (bullish vote). Real
    simplification, stated plainly: this doesn't weight by days-to-
    expiry, even though the pull is genuinely stronger close to
    expiry -- same everywhere in the cycle for now."""
    if price is None or max_pain is None or max_pain == 0:
        return None
    dist_pct = (price - max_pain) / max_pain * 100
    if dist_pct > 0.15:
        return "bearish"
    if dist_pct < -0.15:
        return "bullish"
    return None


def _vix_trend_vote(vix_change_pct):
    """Rising VIX = rising fear = bearish lean; falling VIX = calm =
    bullish lean. Index-only in practice -- VIX is left None for
    commodities (see snapshot_commodity), so this vote simply abstains
    there rather than being force-fit onto an instrument it doesn't
    apply to."""
    if vix_change_pct is None:
        return None
    if vix_change_pct > 3:
        return "bearish"
    if vix_change_pct < -3:
        return "bullish"
    return None


def _momentum_vote(recent_change_pct):
    """Same +-0.05% threshold _price_confirms_bias() already used --
    reused here as ONE vote among several, not the sole word on
    direction the way a single PCR tier crossing effectively was in
    the old version."""
    if recent_change_pct is None:
        return None
    if recent_change_pct > 0.05:
        return "bullish"
    if recent_change_pct < -0.05:
        return "bearish"
    return None


def _derive_bias(pcr, oi_buildup, pe_oi=None, ce_oi=None, price=None, max_pain=None,
                  vix_change_pct=None, momentum_pct=None):
    """
    Aug 27 2026: rebuilt as a genuine multi-factor vote, REPLACING the
    old "PCR tier, refined by one OI modifier" approach entirely. Real
    trigger: compared live against a reference NIFTY tool that runs its
    own 7-factor vote (seen live: Bullish 3 / Bearish 4 -> Neutral, on
    that thin a margin) -- this project was calling the SAME moment
    "Bearish" outright, because a single PCR tier crossing (0.5-0.95)
    was enough to fully commit, with no concept of how close the
    underlying signals actually were. Checked directly: both PCR
    readings (0.63 there, 0.69 here) sat well inside that tier, so the
    old code was doing exactly what it was written to do -- the GAP was
    the missing concept of confidence/margin, not a wrong PCR read.

    This does NOT try to reverse-engineer that other tool's exact
    internal factors or weights -- not possible from a screenshot of
    its output alone. It's a genuine, independent vote system built
    from data this project already fetches every cycle, using the same
    real principle: several independent reads have to agree before
    committing to a direction; a close split stays Neutral rather than
    picking a side. Any factor without enough data simply abstains
    (counts toward neither side) rather than being guessed.

    Aug 27 2026 (SAME DAY FOLLOW-UP): originally shipped with a 7th
    vote, _oi_price_combo_vote(fut_oi_chg_pct, price_change_pct) --
    REMOVED after a real live session showed Bias stuck Bearish for
    the ENTIRE day (09:31 through 14:01+) despite the new vote system
    being confirmed live and running. Root cause, found by tracing the
    actual logic rather than re-guessing thresholds: that vote's 4
    branches ALL reduced to just price_change_pct's sign -- OI's sign
    never actually changed the bullish/bearish verdict, only the
    buildup/covering LABEL underneath it (the standard 4-quadrant
    reading genuinely works that way: Long Buildup AND Short Covering
    are both "price up" quadrants and both read bullish; Short Buildup
    AND Long Unwinding are both "price down" and both read bearish).
    So it was silently a redundant twin of the momentum vote -- worse,
    it was fed change_percent (the day's CUMULATIVE change, not a
    rolling window), and Fut OI Chg is fetched from Fyers as
    oipercent (also day-over-day, not intraday -- see this file's
    Fut-OI-Chg comment further up; no rolling OI baseline is exposed
    to build a real intraday version from). Combined with PCR (which
    also barely moves intraday in a stable regime), that gave 2 votes
    that could hit the margin bar together and never let go for hours,
    regardless of what the other 5 actually said -- undermining the
    entire point of this rebuild. No genuinely independent replacement
    was available from data Fyers actually exposes, so it's dropped
    rather than kept in a still-redundant or still-day-sticky form.
    Down to 6 votes; BIAS_VOTE_MARGIN_FOR_STRONG adjusted from 5 to 4
    to hold roughly the same "most votes agree" proportion (5/7 -> 4/6).

    HONEST LIMITATION: the remaining 6 factors and the two margin
    thresholds are still a reasonable first cut, not empirically
    tuned -- same "watch and retune" status as every other threshold
    in this file. Can't be retroactively verified against already-
    logged Bias values (computed under one of two now-superseded
    versions) -- only watched going forward from here.
    """
    votes = [
        _pcr_vote(pcr),
        _oi_buildup_vote(oi_buildup),
        _atm_balance_vote(pe_oi, ce_oi),
        _max_pain_vote(price, max_pain),
        _vix_trend_vote(vix_change_pct),
        _momentum_vote(momentum_pct),
    ]
    bullish = votes.count("bullish")
    bearish = votes.count("bearish")
    margin = bullish - bearish

    if abs(margin) < BIAS_VOTE_MARGIN_FOR_DIRECTION:
        return "Neutral"
    direction = "Bullish" if margin > 0 else "Bearish"
    if abs(margin) >= BIAS_VOTE_MARGIN_FOR_STRONG:
        return f"{direction} (Strong)"
    return direction


def get_bias_vote_breakdown(pcr, oi_buildup, pe_oi=None, ce_oi=None, price=None, max_pain=None,
                             vix_change_pct=None, momentum_pct=None):
    """
    Sep 2 2026: Section 17 of the Index Bias audit -- "show Confidence
    and the evidence domains supporting it," "show the top reasons for
    the current state and the strongest conflicting evidence." Same
    exact inputs and same exact vote sub-functions _derive_bias()
    itself uses -- this doesn't change or duplicate any decision
    logic, it just returns what _derive_bias() already computes
    internally and then discards (it only ever returned the final
    string). Deliberately a SEPARATE function, not a signature change
    to _derive_bias() -- every existing caller of that function keeps
    working exactly as before, untouched.
    """
    return {
        "pcr": _pcr_vote(pcr),
        "oi_buildup": _oi_buildup_vote(oi_buildup),
        "atm_balance": _atm_balance_vote(pe_oi, ce_oi),
        "max_pain": _max_pain_vote(price, max_pain),
        "vix_trend": _vix_trend_vote(vix_change_pct),
        "momentum": _momentum_vote(momentum_pct),
    }


BIAS_V2_MARGIN_FOR_DIRECTION = 2
BIAS_V2_MARGIN_FOR_STRONG = 3  # out of 4 effective votes -- same "reasonable first cut, not empirically tuned" status as every threshold in this file; needs a future Phase 1 run on real V2 data before being trusted

# Sep 2 2026: real, evidence-based Phase 2 of the Index Bias audit.
# index_bias_forensics.py's actual run against 4,204 real NIFTY/
# BANKNIFTY snapshots confirmed Section 3's correlated-evidence claim
# concretely -- PCR vs OI Buildup agreed 95.9%/58.0% of the time, ATM
# Balance vs Max Pain agreed 94.5%/66.6% -- each pair voting as
# essentially ONE opinion counted twice. This combines each pair into
# a single effective vote instead. VIX-trend and Momentum stay
# separate -- they weren't found strongly correlated with the pair
# members.
#
# HONEST CAVEAT, stated as plainly as possible: the SAME forensics run
# showed every one of the 4 fully-reliable factors individually near
# 44-53% forward accuracy -- statistically indistinguishable from a
# coin flip. Decorrelating removes DOUBLE-COUNTING and the resulting
# false confidence of an inflated "Strong" label; it does NOT invent
# predictive power that wasn't in the underlying factors to begin
# with. Do not read a V2 "Strong" label as more likely to be right --
# only as less likely to be an illusion of 4 independent opinions that
# was really 2.
#
# DELIBERATELY NOT LIVE: computed and logged alongside the real Bias,
# never replacing it, never read by any live signal-selection code.
# Same "build in parallel, validate before switching" rule already
# held everywhere on the F&O side of this project. Earns the right to
# matter only once a FUTURE index_bias_forensics.py run can show V2's
# own real forward accuracy against real data -- something that
# doesn't exist yet, since V2 has never generated a single historical
# reading.


def _combine_correlated_pair(vote_a, vote_b):
    """Two votes shown to be highly correlated -> one effective vote.
    Both agree -> that direction (this is the normal, expected case
    given how often they actually agree). They genuinely disagree ->
    abstain, not an arbitrary pick -- given how rarely that happens
    for real, a real disagreement is treated as real uncertainty, not
    resolved by favoring either side. One abstains, the other has an
    opinion -> use the one real opinion available."""
    if vote_a is None:
        return vote_b
    if vote_b is None:
        return vote_a
    if vote_a == vote_b:
        return vote_a
    return None  # genuine disagreement between two usually-agreeing factors -- treated as real uncertainty


def derive_bias_v2(pcr, oi_buildup, pe_oi=None, ce_oi=None, price=None, max_pain=None,
                    vix_change_pct=None, momentum_pct=None):
    """
    The decorrelated engine -- 4 effective votes (Positioning =
    combined PCR+OI Buildup, Structure = combined ATM Balance+Max
    Pain, VIX trend, Momentum) instead of 6 raw ones. Same margin-
    then-Neutral-then-Strong shape as _derive_bias(), recalibrated for
    4 votes instead of 6. See this function's module-level comment
    block above for the full evidence and the honest caveat about
    what this does and doesn't fix.

    Returns (bias_v2_string, breakdown_dict) -- breakdown includes
    both the 4 effective votes AND the original 6 raw ones, so a
    future comparison can see exactly which raw factors drove each
    effective vote, not just the combined result.
    """
    raw_votes = get_bias_vote_breakdown(
        pcr, oi_buildup, pe_oi=pe_oi, ce_oi=ce_oi, price=price, max_pain=max_pain,
        vix_change_pct=vix_change_pct, momentum_pct=momentum_pct,
    )

    positioning = _combine_correlated_pair(raw_votes["pcr"], raw_votes["oi_buildup"])
    structure = _combine_correlated_pair(raw_votes["atm_balance"], raw_votes["max_pain"])

    effective_votes = {
        "positioning": positioning,
        "structure": structure,
        "vix_trend": raw_votes["vix_trend"],
        "momentum": raw_votes["momentum"],
    }

    bullish = sum(1 for v in effective_votes.values() if v == "bullish")
    bearish = sum(1 for v in effective_votes.values() if v == "bearish")
    margin = bullish - bearish

    if abs(margin) < BIAS_V2_MARGIN_FOR_DIRECTION:
        bias_v2 = "Neutral"
    else:
        direction = "Bullish" if margin > 0 else "Bearish"
        bias_v2 = f"{direction} (Strong)" if abs(margin) >= BIAS_V2_MARGIN_FOR_STRONG else direction

    return bias_v2, {"effective_votes": effective_votes, "raw_votes": raw_votes}


def _status_label(oi_chg):
    """'Writing' (OI building up) vs 'Unwinding' (OI coming off) -- the
    reference table's own vocabulary."""
    if oi_chg is None:
        return "—"
    return "Writing" if oi_chg > 0 else "Unwinding" if oi_chg < 0 else "Flat"


def _bias_direction(bias):
    """Same direction-only reading backtest_index_bias.py's flip
    analysis already uses -- Bullish/Bullish (Strong) -> 'up',
    Bearish/Bearish (Strong) -> 'down', Neutral/None -> None. Deliberately
    collapses Strong vs plain into the same direction, since a tier
    change within one direction (Bullish -> Bullish (Strong)) is an
    intensity change, not a flip. Unaffected by the Aug 27 Bias rewrite
    above -- still just reads the resulting string's prefix, same as
    always."""
    if not bias:
        return None
    if bias.startswith("Bullish"):
        return "up"
    if bias.startswith("Bearish"):
        return "down"
    return None


def _log_flip_if_changed(wb, name, bias, price, confirms, oi_buildup, date_str, time_str, cross_asset=None):
    """
    Appends one row to the Flips sheet only when direction genuinely
    changed since the last reading for this name -- Neutral readings
    don't overwrite the remembered direction (same as
    backtest_index_bias.py's flip counting: a dip to Neutral and back
    to the same direction isn't two flips, it's zero). Writes nothing
    on the very first reading for a name in this process (nothing to
    compare against yet) or when the direction is unchanged.

    Aug 24 2026: also logs Crude/Gold/Silver's own day change% at the
    moment of the flip (cross_asset, from _get_cross_asset_snapshot())
    -- LOG-ONLY, nothing reads or gates on this yet. First step toward
    testing whether these (this project's stand-in for "global cues",
    since true SGX/Dow data isn't available here) actually correlate
    with which flips hold vs. reverse. Real flips are still rare (1
    NIFTY, 0 BANKNIFTY as of the first backtest run Aug 23) -- needs
    real accumulated flips before backtest_index_positional.py can be
    meaningfully re-run with vs. without this as a filter, not
    something a thin sample can answer yet.
    """
    global _last_direction, _last_bias_string
    new_dir = _bias_direction(bias)
    prev_dir = _last_direction.get(name)
    prev_bias_str = _last_bias_string.get(name)

    if new_dir is not None and new_dir != prev_dir and prev_dir is not None:
        ws = wb["Flips"]
        cross_asset = cross_asset or {}
        ws.append([
            date_str, time_str, prev_bias_str, bias, price, confirms, oi_buildup,
            cross_asset.get("CRUDEOIL"), cross_asset.get("GOLD"), cross_asset.get("SILVER"),
        ])

    if new_dir is not None:
        _last_direction[name] = new_dir
        _last_bias_string[name] = bias


def _record_and_get_multi_horizon_changes(name, price, now=None):
    """
    Appends (now, price) to `name`'s rolling window, prunes anything
    older than _MAX_WINDOW_MINUTES, and returns the %% change for EVERY
    horizon in CONFIRMATION_HORIZONS at once -- {5: pct_or_None,
    15: pct_or_None, 30: pct_or_None, 60: pct_or_None}. A horizon reads
    None until there's at least one reading that old still in the
    window (freshly (re)started, or fewer than that many minutes since
    market open) -- same honest "not enough data yet" signal
    _price_confirms_bias() already treats as "--", now per-horizon
    instead of just once.

    One retained history list per name serves every horizon -- 60min of
    retention covers the 5/15/30min windows as shorter slices of the
    exact same data, not four separate lists to maintain.

    HONEST LIMITATION, same growing-window behavior the original single-
    window version always had: each horizon compares against the OLDEST
    reading still on file within that horizon's cutoff, not a reading
    that's genuinely that many minutes old. Early in a session (right
    after market open or a restart), that means the 5/15/30/60min
    horizons can all end up comparing against the same single oldest
    entry and read similarly, since there simply isn't enough real
    history yet to tell them apart -- they diverge into genuinely
    different, meaningful readings as the session goes on and real
    5-min-old, 15-min-old, etc. data actually accumulates. Not a bug;
    same tradeoff the 15min-only version already accepted, just visible
    across 4 horizons now instead of 1.

    Always records the price first, even when every horizon returns
    None, so each window starts filling in from the very first call
    rather than waiting for some later trigger.
    """
    if price is None:
        return {h: None for h in CONFIRMATION_HORIZONS}
    now = now or datetime.now()
    with _lock:
        history = _recent_prices.setdefault(name, [])
        cutoff = now - timedelta(minutes=_MAX_WINDOW_MINUTES)
        while history and history[0][0] < cutoff:
            history.pop(0)
        # Snapshot BEFORE appending the current reading -- each horizon's
        # "oldest reading in window" must come from readings already on
        # file, never the point we're computing change FOR. Matches the
        # original single-horizon function's exact ordering (capture
        # oldest, THEN append) -- getting this backwards was caught live
        # by this feature's own test: it made the very first-ever reading
        # compare against itself (0.0% instead of the correct None).
        snapshot = list(history)
        history.append((now, price))

    changes = {}
    for horizon in CONFIRMATION_HORIZONS:
        horizon_cutoff = now - timedelta(minutes=horizon)
        oldest = next((entry for entry in snapshot if entry[0] >= horizon_cutoff), None)
        if oldest is None or not oldest[1]:
            changes[horizon] = None
        else:
            changes[horizon] = round((price - oldest[1]) / oldest[1] * 100, 3)
    return changes


def _multi_horizon_confirms(changes_by_horizon, bias):
    """Applies the existing single-horizon _price_confirms_bias() check
    to each horizon separately (same thresholds, same verdicts -- this
    doesn't change what "confirms" means, just checks it at more than
    one lookback window), plus a plain "X/Y" summary of how many
    horizons that HAD enough data actually confirmed. Horizons that
    read "--" (not enough history yet) are excluded from the Y count
    too, not treated as a non-confirm -- an honest "still filling in"
    rather than a false negative early in the day or right after a
    restart."""
    per_horizon = {h: _price_confirms_bias(changes_by_horizon.get(h), bias) for h in CONFIRMATION_HORIZONS}
    with_data = [v for v in per_horizon.values() if v != "—"]
    confirming = [v for v in with_data if v == "✓ Confirmed"]
    summary = f"{len(confirming)}/{len(with_data)}" if with_data else "—"
    return per_horizon, summary


def _price_confirms_bias(recent_change_pct, bias):
    """Same confirmation concept already used for individual stock
    signals (Round 3), applied here: does the index's actual price move
    agree with what the OI positioning implies? This is the extra
    confirmation layer -- OI can say 'Bullish' while price is actually
    falling (a real warning sign, not a contradiction to ignore).

    Aug 14 2026: `recent_change_pct` is now a ROLLING window (see
    _record_and_get_multi_horizon_changes above), not the day's
    cumulative Change % from previous close. Real production data
    showed the previous-close version could miss a genuine, sizable
    intraday divergence whenever the day happened to net out small --
    a swing that was real and checkable got invisible simply because
    price round-tripped back near its open. A rolling window catches
    the swing itself, not just where the day ends up relative to
    yesterday.

    Aug 20 2026: this function itself is unchanged -- still one
    threshold check against one recent_change_pct value. What changed
    is the caller: snapshot_index()/snapshot_commodity() now call this
    once per horizon (5/15/30/60min) instead of once, via
    _multi_horizon_confirms() below, so the same verdict logic applies
    at every horizon rather than just the original 15min.

    Aug 27 2026: also now, separately, ONE of the 7 votes _derive_bias()
    uses (via _momentum_vote(), same +-0.05% threshold) to help COMPUTE
    Bias in the first place -- this function's own job is unchanged
    though: it still just checks momentum against whatever Bias came
    out, as an after-the-fact consistency read, same as always.

    Also flags the Neutral case specifically: PCR sitting in the
    Neutral band doesn't mean price itself is standing still -- a
    real, sustained move can happen while OI positioning just hasn't
    caught up yet. Uses a wider +-0.3% threshold than the +-0.05% used
    for Bullish/Bearish confirmation above, on purpose -- this is meant
    to catch a genuinely notable divergence, not flag on every
    few-minute wobble while Bias sits Neutral, which would fire
    constantly and stop being useful.

    Both thresholds (0.05% / 0.3%) are carried over UNCHANGED from the
    previous-close version -- they were already judgment calls, not
    rigorously derived numbers, and there's no data yet on what they
    should be against a 15-minute window specifically (likely more
    sensitive for the 0.05% Bullish/Bearish check now, since a 15-min
    move clears 0.05% more easily than a full day used to; the 0.3%
    Neutral-divergence check may now under-fire, since 0.3% inside 15
    minutes is a much bigger ask than 0.3% across a whole day). Watch
    both in practice and retune -- same approach already taken with
    the original Neutral-band width elsewhere in this file.
    """
    if recent_change_pct is None or bias is None:
        return "—"
    if recent_change_pct > 0.05 and bias.startswith("Bullish"):
        return "✓ Confirmed"
    if recent_change_pct < -0.05 and bias.startswith("Bearish"):
        return "✓ Confirmed"
    if recent_change_pct > 0.05 and bias.startswith("Bearish"):
        return "⚠ Conflict"
    if recent_change_pct < -0.05 and bias.startswith("Bullish"):
        return "⚠ Conflict"
    if bias == "Neutral" and recent_change_pct <= -0.3:
        return "⚠ Neutral but falling"
    if bias == "Neutral" and recent_change_pct >= 0.3:
        return "⚠ Neutral but rising"
    return "—"


def snapshot_index(index_name, change_percent=None, vix=None):
    """
    Fetch one live snapshot for NIFTY or BANKNIFTY and append it as a
    new row to today's tracker file for that index. Returns the row dict
    (for the API endpoint to serve without re-reading the file), or None
    if Fyers has nothing to give us right now.

    change_percent: the index's own day change%, passed in from
    _build_all() (which already fetches it for the top banner) rather
    than making a second API call for the same number.
    vix: India VIX, same index for both rows (it's one number, not
    per-index) -- reused from data already fetched elsewhere per cycle.
    """
    if not OPENPYXL_AVAILABLE or index_name not in INDEX_SYMBOLS:
        return None

    from .market_hours import is_market_hours, is_cas_auction_window
    if not is_market_hours():
        return None

    from .fyers_client import get_option_analytics, get_market_depth
    fyers_symbol = INDEX_SYMBOLS[index_name]

    try:
        oi = get_option_analytics(fyers_symbol, strikecount=10)
    except Exception as e:
        print(f"[IndexTracker] {index_name} fetch failed: {e}")
        return None
    if not oi:
        return None
    with _lock:
        _last_oi_snapshot[index_name] = oi

    # Futures price + OI -- ONE depth() call gives both (confirmed live:
    # ltp for price, oi/pdoi/oipercent for OI), replacing what used to be
    # a separate quotes() call for price alone. Failure here shouldn't
    # kill the whole snapshot, just leaves these fields blank.
    fut_price = None
    fut_oi = None
    fut_oi_chg_pct = None
    try:
        fut_symbol = _front_month_futures_symbol(index_name)
        depth_resp = get_market_depth(fut_symbol)
        if depth_resp and depth_resp.get("s") == "ok":
            fut_data = (depth_resp.get("d", {}) or {}).get(fut_symbol, {})
            fut_price = fut_data.get("ltp")
            fut_oi = fut_data.get("oi")
            fut_oi_chg_pct = fut_data.get("oipercent")
    except Exception as e:
        print(f"[IndexTracker] {index_name} futures price/OI fetch failed: {e}")

    atm_strike = oi.get("atm_strike")
    rows = oi.get("rows", [])
    atm_row = next((r for r in rows if r["strike"] == atm_strike), None)
    pe_oi = (atm_row or {}).get("pe", {}).get("oi") if atm_row else None
    ce_oi = (atm_row or {}).get("ce", {}).get("oi") if atm_row else None

    # oi['support']/oi['resistance'] are already the highest-PE-OI and
    # highest-CE-OI strikes (from options_analytics.compute_support_
    # resistance) -- look up the actual OI VALUE at those strikes too,
    # so the table can show "24600 (75.5L)" not just the bare strike.
    highest_put_strike = oi.get("support")
    highest_call_strike = oi.get("resistance")
    put_wall_row = next((r for r in rows if r["strike"] == highest_put_strike), None)
    call_wall_row = next((r for r in rows if r["strike"] == highest_call_strike), None)
    highest_put_value = (put_wall_row or {}).get("pe", {}).get("oi") if put_wall_row else None
    highest_call_value = (call_wall_row or {}).get("ce", {}).get("oi") if call_wall_row else None

    with _lock:
        prev = _last_snapshot.get(index_name, {})
        pe_chg = (pe_oi - prev["pe_oi"]) if (pe_oi is not None and "pe_oi" in prev) else None
        ce_chg = (ce_oi - prev["ce_oi"]) if (ce_oi is not None and "ce_oi" in prev) else None
        _last_snapshot[index_name] = {"pe_oi": pe_oi, "ce_oi": ce_oi}

    # Aug 27 2026: momentum + VIX-trend now computed BEFORE Bias -- they
    # feed _derive_bias() as two of its votes, not just a post-hoc
    # confirmation check the way the single 15min "Price Confirms Bias"
    # value below still is. Recording still happens exactly once per
    # cycle either way, just earlier in this function now.
    horizon_changes = _record_and_get_multi_horizon_changes(index_name, oi.get("spot"))
    vix_trend_pct = _record_and_get_vix_trend(vix)

    bias = _derive_bias(
        oi.get("pcr"), oi.get("oi_buildup"),
        pe_oi=pe_oi, ce_oi=ce_oi,
        price=oi.get("spot"), max_pain=oi.get("max_pain"),
        vix_change_pct=vix_trend_pct, momentum_pct=horizon_changes.get(15),
    )
    vote_breakdown = get_bias_vote_breakdown(
        oi.get("pcr"), oi.get("oi_buildup"),
        pe_oi=pe_oi, ce_oi=ce_oi,
        price=oi.get("spot"), max_pain=oi.get("max_pain"),
        vix_change_pct=vix_trend_pct, momentum_pct=horizon_changes.get(15),
    )
    # Sep 2 2026: parallel, logged-only -- see derive_bias_v2()'s own
    # docstring. `bias` above (not bias_v2) is the only value anything
    # downstream of this function reads.
    bias_v2, v2_breakdown = derive_bias_v2(
        oi.get("pcr"), oi.get("oi_buildup"),
        pe_oi=pe_oi, ce_oi=ce_oi,
        price=oi.get("spot"), max_pain=oi.get("max_pain"),
        vix_change_pct=vix_trend_pct, momentum_pct=horizon_changes.get(15),
    )
    confirms = _price_confirms_bias(horizon_changes.get(15), bias)  # unchanged 15min value -- stays comparable to the Aug 14 backtest baseline
    per_horizon_confirms, horizons_summary = _multi_horizon_confirms(horizon_changes, bias)
    # Flagged separately rather than suppressing/altering Change % or
    # Price Confirms Bias -- those numbers are real, computed the same
    # way regardless of when the snapshot was taken. This just gives
    # the context that a reading during 3:15-3:35 PM coincides with
    # the documented freeze-then-jump behavior of the CAS auction
    # itself (see market_hours.py), so a big move here can be read
    # correctly rather than mistaken for a normal intraday move.
    cas_auction = is_cas_auction_window()

    # See compute_iv_percentile()'s docstring for the real, honest
    # limitation here -- thin sample until more real days accumulate.
    iv_percentile, _iv_sample_size = compute_iv_percentile(index_name, oi.get("iv"))

    row = {
        "Time": datetime.now().strftime("%H:%M:%S"),
        "Spot": oi.get("spot"),
        "Fut": fut_price,
        "Fut OI": fut_oi,
        "Fut OI Chg %": fut_oi_chg_pct,
        "Change %": change_percent,
        "CAS Auction": cas_auction,
        "PCR": oi.get("pcr"),
        "ATM Strike": atm_strike,
        "Put OI (ATM)": pe_oi, "Put OI Chg": pe_chg, "Put Status": _status_label(pe_chg),
        "Call OI (ATM)": ce_oi, "Call OI Chg": ce_chg, "Call Status": _status_label(ce_chg),
        # Chain-wide totals (across all fetched strikes), not just the
        # ATM one -- gives the macro positioning picture alongside the
        # at-the-money micro view above.
        "Total Put OI": oi.get("pe_oi"), "Total Call OI": oi.get("ce_oi"),
        "Highest Put OI Strike": highest_put_strike, "Highest Put OI Value": highest_put_value,
        "Highest Call OI Strike": highest_call_strike, "Highest Call OI Value": highest_call_value,
        "IV %": oi.get("iv"), "IV %ile": iv_percentile, "VIX": vix,
        "Support": oi.get("support"), "Resistance": oi.get("resistance"),
        "Max Pain": oi.get("max_pain"), "Max Pain Dist %": oi.get("max_pain_dist_pct"),
        "OI Buildup": oi.get("oi_buildup"),
        "Bias": bias, "Price Confirms Bias": confirms,
        "Confirms 5min": per_horizon_confirms[5],
        "Confirms 30min": per_horizon_confirms[30],
        "Confirms 60min": per_horizon_confirms[60],
        "Horizons Confirming": horizons_summary,
        "PCR Vote": vote_breakdown["pcr"], "OI Buildup Vote": vote_breakdown["oi_buildup"],
        "ATM Balance Vote": vote_breakdown["atm_balance"], "Max Pain Vote": vote_breakdown["max_pain"],
        "VIX Trend Vote": vote_breakdown["vix_trend"], "Momentum Vote": vote_breakdown["momentum"],
        "Momentum %": horizon_changes.get(15), "VIX Change %": vix_trend_pct,
        "Bias V2": bias_v2,
        "Positioning Vote (V2)": v2_breakdown["effective_votes"]["positioning"],
        "Structure Vote (V2)": v2_breakdown["effective_votes"]["structure"],
    }

    try:
        path = _today_path(index_name)
        wb = _get_workbook(path)
        ws = wb["Snapshots"]
        ws.append([row[c] for c in COLUMNS])
        _log_flip_if_changed(wb, index_name, bias, row.get("Spot"), confirms, row.get("OI Buildup"), datetime.now().strftime("%Y-%m-%d"), row["Time"], cross_asset=_get_cross_asset_snapshot())
        _atomic_save(wb, path)
    except Exception as e:
        print(f"[IndexTracker] Failed to log {index_name} snapshot: {e}")

    return row


def snapshot_all(change_percents=None, vix=None):
    """Called once per scan cycle -- snapshots both NIFTY and BANKNIFTY.
    change_percents: optional {'NIFTY': pct, 'BANKNIFTY': pct}.
    vix: India VIX value, same index for both rows (it's one number, not
    per-index) -- reused from data already fetched elsewhere per cycle.

    Runs both fetches in PARALLEL (was sequential -- NIFTY's full
    fetch+write completing before BANKNIFTY's even started, adding both
    indices' network round-trip time back-to-back onto every single scan
    cycle). Threaded the same way the stock scanner already fetches data
    elsewhere in this project.

    Returns {'NIFTY': row_or_None, 'BANKNIFTY': row_or_None}."""
    from concurrent.futures import ThreadPoolExecutor
    change_percents = change_percents or {}
    results = {}
    with ThreadPoolExecutor(max_workers=len(INDEX_SYMBOLS)) as ex:
        futures = {ex.submit(snapshot_index, name, change_percents.get(name), vix): name for name in INDEX_SYMBOLS}
        for fut in futures:
            name = futures[fut]
            try:
                results[name] = fut.result()
            except Exception as e:
                print(f"[IndexTracker] {name} snapshot thread failed: {e}")
                results[name] = None
    return results


def snapshot_commodity(name, base):
    """
    Fetch one live snapshot for a commodity (crude oil, etc.) and append
    it as a new row to today's tracker file. Structurally different from
    snapshot_index() above: there's no separate spot/cash index, so the
    front-month FUTURES contract is both the option chain's underlying
    AND the OI/price source -- one symbol doing both jobs, one depth()
    call giving price + OI + this instrument's own day change% together
    (chp), rather than change% being passed in externally the way
    NIFTY/BANKNIFTY get theirs from a separate index quote. Spot and VIX
    are left blank rather than faked -- neither concept applies here.

    Gates on is_mcx_hours() (not market_hours.py's NSE-only check) since
    MCX runs a longer session than NSE F&O.
    """
    if not OPENPYXL_AVAILABLE:
        return None
    if not is_mcx_hours():
        return None

    from .fyers_client import get_option_analytics, get_market_depth
    # Crude uses the simple day-of-month rollover (near-monthly
    # contracts); Gold/Silver use the probe-based resolver instead,
    # since they skip calendar months entirely -- see COMMODITY_BASES'
    # comment and _front_month_bullion_symbol()'s docstring for why.
    if base in _NEAR_MONTHLY_BASES:
        fut_symbol = _front_month_commodity_symbol(base)
    else:
        # Aug 24 2026: switched from the plain _front_month_bullion_
        # symbol() to the options-aware variant -- this function calls
        # get_option_analytics() on fut_symbol right below and bails
        # with None (nothing logged at all) if that comes back empty.
        # The plain resolver validates only a futures LTP, which an
        # EXPIRED contract can still return (confirmed live: August
        # Gold) -- exactly why Gold's snapshot table was staying
        # completely empty while Silver's (whose resolved contract
        # happened to still be genuinely current) kept working. Same
        # root cause, same fix, as OptionAnalyticsView in views.py.
        fut_symbol = _front_month_bullion_symbol_with_options(base)
        if fut_symbol is None:
            return None  # no live contract found in the probe window -- nothing to snapshot, not a guess

    fut_price = None
    fut_oi = None
    fut_oi_chg_pct = None
    change_percent = None
    try:
        depth_resp = get_market_depth(fut_symbol)
        if depth_resp and depth_resp.get("s") == "ok":
            fut_data = (depth_resp.get("d", {}) or {}).get(fut_symbol, {})
            fut_price = fut_data.get("ltp")
            fut_oi = fut_data.get("oi")
            fut_oi_chg_pct = fut_data.get("oipercent")
            change_percent = fut_data.get("chp")
    except Exception as e:
        print(f"[IndexTracker] {name} futures price/OI fetch failed: {e}")

    try:
        oi = get_option_analytics(fut_symbol, strikecount=10)
    except Exception as e:
        print(f"[IndexTracker] {name} option chain fetch failed: {e}")
        return None
    if not oi:
        return None
    with _lock:
        _last_oi_snapshot[name] = oi

    atm_strike = oi.get("atm_strike")
    rows = oi.get("rows", [])
    atm_row = next((r for r in rows if r["strike"] == atm_strike), None)
    pe_oi = (atm_row or {}).get("pe", {}).get("oi") if atm_row else None
    ce_oi = (atm_row or {}).get("ce", {}).get("oi") if atm_row else None

    highest_put_strike = oi.get("support")
    highest_call_strike = oi.get("resistance")
    put_wall_row = next((r for r in rows if r["strike"] == highest_put_strike), None)
    call_wall_row = next((r for r in rows if r["strike"] == highest_call_strike), None)
    highest_put_value = (put_wall_row or {}).get("pe", {}).get("oi") if put_wall_row else None
    highest_call_value = (call_wall_row or {}).get("ce", {}).get("oi") if call_wall_row else None

    with _lock:
        prev = _last_snapshot.get(name, {})
        pe_chg = (pe_oi - prev["pe_oi"]) if (pe_oi is not None and "pe_oi" in prev) else None
        ce_chg = (ce_oi - prev["ce_oi"]) if (ce_oi is not None and "ce_oi" in prev) else None
        _last_snapshot[name] = {"pe_oi": pe_oi, "ce_oi": ce_oi}

    # Aug 27 2026: momentum computed BEFORE Bias -- feeds _derive_bias()
    # as one of its votes, same reordering as snapshot_index() above.
    # No VIX-trend vote for commodities (VIX doesn't apply -- left None
    # below, same as the row's own "VIX" field always has been).
    horizon_changes = _record_and_get_multi_horizon_changes(name, fut_price)

    bias = _derive_bias(
        oi.get("pcr"), oi.get("oi_buildup"),
        pe_oi=pe_oi, ce_oi=ce_oi,
        price=fut_price, max_pain=oi.get("max_pain"),
        vix_change_pct=None, momentum_pct=horizon_changes.get(15),
    )
    vote_breakdown = get_bias_vote_breakdown(
        oi.get("pcr"), oi.get("oi_buildup"),
        pe_oi=pe_oi, ce_oi=ce_oi,
        price=fut_price, max_pain=oi.get("max_pain"),
        vix_change_pct=None, momentum_pct=horizon_changes.get(15),
    )
    bias_v2, v2_breakdown = derive_bias_v2(
        oi.get("pcr"), oi.get("oi_buildup"),
        pe_oi=pe_oi, ce_oi=ce_oi,
        price=fut_price, max_pain=oi.get("max_pain"),
        vix_change_pct=None, momentum_pct=horizon_changes.get(15),
    )
    confirms = _price_confirms_bias(horizon_changes.get(15), bias)  # unchanged 15min value -- stays comparable to the Aug 14 backtest baseline
    per_horizon_confirms, horizons_summary = _multi_horizon_confirms(horizon_changes, bias)

    # See compute_iv_percentile()'s docstring for the honest limitation.
    iv_percentile, _iv_sample_size = compute_iv_percentile(name, oi.get("iv"))

    row = {
        "Time": datetime.now().strftime("%H:%M:%S"),
        "Spot": None,  # no separate spot/cash index for a commodity -- left blank, not faked
        "Fut": fut_price,
        "Fut OI": fut_oi,
        "Fut OI Chg %": fut_oi_chg_pct,
        "Change %": change_percent,
        "CAS Auction": None,  # CAS is an NSE cash-market mechanism -- doesn't apply to MCX commodities at all
        "PCR": oi.get("pcr"),
        "ATM Strike": atm_strike,
        "Put OI (ATM)": pe_oi, "Put OI Chg": pe_chg, "Put Status": _status_label(pe_chg),
        "Call OI (ATM)": ce_oi, "Call OI Chg": ce_chg, "Call Status": _status_label(ce_chg),
        "Total Put OI": oi.get("pe_oi"), "Total Call OI": oi.get("ce_oi"),
        "Highest Put OI Strike": highest_put_strike, "Highest Put OI Value": highest_put_value,
        "Highest Call OI Strike": highest_call_strike, "Highest Call OI Value": highest_call_value,
        "IV %": oi.get("iv"), "IV %ile": iv_percentile, "VIX": None,  # India VIX is an equity-index concept, not applicable here
        "Support": oi.get("support"), "Resistance": oi.get("resistance"),
        "Max Pain": oi.get("max_pain"), "Max Pain Dist %": oi.get("max_pain_dist_pct"),
        "OI Buildup": oi.get("oi_buildup"),
        "Bias": bias, "Price Confirms Bias": confirms,
        "Confirms 5min": per_horizon_confirms[5],
        "Confirms 30min": per_horizon_confirms[30],
        "Confirms 60min": per_horizon_confirms[60],
        "Horizons Confirming": horizons_summary,
        "PCR Vote": vote_breakdown["pcr"], "OI Buildup Vote": vote_breakdown["oi_buildup"],
        "ATM Balance Vote": vote_breakdown["atm_balance"], "Max Pain Vote": vote_breakdown["max_pain"],
        "VIX Trend Vote": vote_breakdown["vix_trend"], "Momentum Vote": vote_breakdown["momentum"],
        "Momentum %": horizon_changes.get(15), "VIX Change %": None,  # no VIX for commodities, same as the row's VIX field above
        "Bias V2": bias_v2,
        "Positioning Vote (V2)": v2_breakdown["effective_votes"]["positioning"],
        "Structure Vote (V2)": v2_breakdown["effective_votes"]["structure"],
    }

    # Aug 24 2026: feeds _get_cross_asset_snapshot() -- see that
    # function's docstring. Updated here (not just used) so a
    # NIFTY/BANKNIFTY flip later in the same or a following cycle can
    # read what this commodity was doing.
    with _lock:
        _last_commodity_readings[name] = {"change_pct": row.get("Change %"), "fut": row.get("Fut")}

    try:
        path = _today_path(name)
        wb = _get_workbook(path)
        ws = wb["Snapshots"]
        ws.append([row[c] for c in COLUMNS])
        _log_flip_if_changed(wb, name, bias, row.get("Fut"), confirms, row.get("OI Buildup"), datetime.now().strftime("%Y-%m-%d"), row["Time"], cross_asset=_get_cross_asset_snapshot())
        _atomic_save(wb, path)
    except Exception as e:
        print(f"[IndexTracker] Failed to log {name} snapshot: {e}")

    return row


def snapshot_all_commodities():
    """Same threaded pattern as snapshot_all() above, for commodities.
    No change_percents/vix params needed -- snapshot_commodity() sources
    both itself from the single depth() call. Returns {'CRUDEOIL':
    row_or_None, 'CRUDEOILM': row_or_None}."""
    from concurrent.futures import ThreadPoolExecutor
    results = {}
    with ThreadPoolExecutor(max_workers=len(COMMODITY_BASES)) as ex:
        futures = {ex.submit(snapshot_commodity, name, base): name for name, base in COMMODITY_BASES.items()}
        for fut in futures:
            name = futures[fut]
            try:
                results[name] = fut.result()
            except Exception as e:
                print(f"[IndexTracker] {name} snapshot thread failed: {e}")
                results[name] = None
    return results


def get_snapshots_for_date(index_name, date_str, limit=None):
    """Read logged rows for a specific date (YYYY-MM-DD), most recent
    first. Returns [] if nothing was logged that date (a weekend, a
    holiday, or before this started running) rather than erroring.

    Aug 24 2026: limit used to default to 100, which silently truncated
    to only the newest 100 snapshots -- at the real ~60s-ish logging
    cadence, a full trading day easily logs 250+ rows, so by early
    afternoon anything before roughly mid-morning was already being cut
    off both here and in Index Tracker's own full-density view (both
    read through this same function). limit=None now means "return
    everything logged that day"; callers that genuinely want just a
    handful (e.g. the IV-percentile lookback's limit=1 for a day's
    closing snapshot) still pass an explicit limit."""
    if not OPENPYXL_AVAILABLE or index_name not in TRACKABLE_NAMES:
        return []
    key = (index_name, date_str)
    if key in _known_corrupted_dates:
        # Already confirmed broken earlier this session -- don't retry
        # opening it, don't re-log the same error again. See
        # _known_corrupted_dates' own comment for why this matters.
        return []
    path = _date_path(index_name, date_str)
    if not os.path.exists(path):
        return []
    try:
        wb = load_workbook(path)
        ws = wb["Snapshots"]
        # Zip against the file's OWN header row, not the current in-memory
        # COLUMNS constant -- a column added since that date's file was
        # written means an already-written file's real column order can
        # legitimately differ from what COLUMNS says right now. Zipping
        # against the constant silently shifted every value after the
        # change point onto the wrong new label for older rows (caught
        # live). Reading the file's actual header keeps old rows correct.
        file_columns = [c.value for c in ws[1]]
        rows = []
        for r in ws.iter_rows(min_row=2, values_only=True):
            rows.append(dict(zip(file_columns, r)))
        rows = list(reversed(rows))
        return rows[:limit] if limit is not None else rows
    except zipfile.BadZipFile as e:
        # A genuinely, permanently corrupted file (confirmed live: an
        # interrupted write left one exactly like this for a real
        # CRUDEOIL/CRUDEOILM file on Aug 26 2026) -- this isn't a
        # transient issue that might succeed on the very next attempt,
        # so remember it and stop retrying this date for the rest of
        # this process's life. Deliberately a narrower except clause
        # than the general one below -- a transient error (e.g. a
        # momentary Windows file lock, a PermissionError) is NOT
        # cached here, since that genuinely might succeed next cycle
        # and shouldn't be permanently written off.
        print(f"[IndexTracker] {index_name} snapshots for {date_str} are corrupted (not a valid file) -- will not retry this date again this session: {e}")
        _known_corrupted_dates.add(key)
        return []
    except Exception as e:
        print(f"[IndexTracker] Failed to read {index_name} snapshots for {date_str}: {e}")
        return []


def get_today_snapshots(index_name, limit=None):
    """Read today's logged rows for the frontend table (most recent
    first). Returns [] if nothing logged yet today."""
    today = datetime.now().strftime("%Y-%m-%d")
    return get_snapshots_for_date(index_name, today, limit=limit)


def list_available_dates(index_name):
    """Which dates actually have logged data for this index, newest
    first -- scans signal_logs/ for date-named subfolders containing
    this index's file, rather than assuming every date since logging
    started has data (weekends, holidays, and days before the server
    was running won't)."""
    if not os.path.isdir(LOG_DIR):
        return []
    dates = [d for d in os.listdir(LOG_DIR) if os.path.exists(_date_path(index_name, d))]
    return sorted(dates, reverse=True)


def get_today_log_path(index_name):
    path = _today_path(index_name)
    return path if os.path.exists(path) else None


def compute_iv_percentile(index_name, current_iv, lookback_days=30):
    """
    IV Percentile: what percentage of the last `lookback_days` trading
    days had a closing IV LOWER than today's current IV. Standard
    definition (not IV Rank, which instead measures where today sits
    between the lookback's min/max) -- this is what "IV%ile" means on
    the reference tool this column was matched against. Tells a trader
    whether current IV is cheap or expensive relative to its OWN recent
    history -- something the raw IV number alone can't say.

    Uses each day's LAST logged snapshot as that day's closing IV.
    Reads real logged history via list_available_dates() +
    get_snapshots_for_date() -- the exact same historical-read pattern
    already used by compute_cas_auction_moves() and the Bias backtest.
    No new Fyers calls, no new data source.

    HONEST LIMITATION: IV Percentile conventionally uses ~252 trading
    days (about a year). This project has only been logging Index
    Tracker snapshots for a few weeks. Returns (percentile,
    sample_size) so the caller can see exactly how thin the sample
    still is, rather than a young number presented with false
    confidence -- same "don't trust a thin sample" pattern this
    project's backtest work already follows throughout. Will keep
    becoming more meaningful as more real trading days accumulate;
    nothing to fix, just needs time.
    """
    if current_iv is None:
        return None, 0

    dates = list_available_dates(index_name)
    today_str = datetime.now().strftime("%Y-%m-%d")
    past_dates = [d for d in dates if d != today_str][:lookback_days]

    closing_ivs = []
    for d in past_dates:
        day_rows = get_snapshots_for_date(index_name, d, limit=1)  # most-recent-first -- [0] is that day's closing snapshot
        if day_rows:
            iv = day_rows[0].get("IV %")
            if iv is not None:
                closing_ivs.append(iv)

    if not closing_ivs:
        return None, 0

    below = sum(1 for iv in closing_ivs if iv < current_iv)
    percentile = round(100 * below / len(closing_ivs), 1)
    return percentile, len(closing_ivs)


def compute_cas_auction_moves(index_name):
    """
    Day-by-day price move specifically attributable to the CAS
    auction: the last snapshot BEFORE the 3:15 PM auction start, vs
    the first snapshot AFTER it resolves (>3:35 PM) -- isolates the
    auction's effect from ordinary intraday movement, using real
    logged data, not an estimate. Uses Spot specifically (the actual
    index/cash value CAS affects), not Fut -- futures trade
    continuously through 3:40 PM and aren't subject to the auction
    mechanism the same way.

    Reuses the same historical snapshot loading as the Bias backtest
    (backtest_index_bias.load_all_snapshots) -- same underlying data,
    a different question asked of it.

    HONEST LIMITATION: days before Aug 13, 2026 (when market_hours.py
    still cut off at 3:30 PM, before the auction resolved) won't have
    a valid post-auction reading and are correctly skipped here, not
    guessed at. Real data only starts accumulating from today forward.

    Returns a list of {date, pre_auction_time, pre_auction_price,
    post_auction_time, post_auction_price, move_abs, move_pct},
    newest day first.
    """
    from .backtest_index_bias import load_all_snapshots
    from datetime import time as _time

    rows = load_all_snapshots(index_name)

    by_day = {}
    for row in rows:
        dt = row["_datetime"]
        if dt.weekday() >= 5:
            continue  # Sat/Sun -- shouldn't have real data at all; any row here is stale/leftover, not a genuine trading-day reading
        day = dt.strftime("%Y-%m-%d")
        by_day.setdefault(day, []).append(row)

    auction_start = _time(15, 15)
    auction_end = _time(15, 35)
    # A genuine pre-auction reading should be reasonably close to
    # 3:15 PM -- with ~60s snapshot cadence, a real trading day always
    # has one within the last hour. A genuine post-auction reading
    # should show up reasonably soon after 3:35 PM too (derivatives
    # close 3:40 PM, post-close session ends 4:00 PM). Caught live:
    # without these bounds, a day with sparse/stale data (e.g. leftover
    # rows from before proper weekend/hours gating existed) could match
    # a "last before / first after" reading from hours away -- a real
    # instance showed 12:09 PM as "pre" and 8:26 PM as "post," neither
    # anywhere near the actual auction. Skipping the day entirely here
    # is the same honest choice as skipping an incomplete one below.
    pre_earliest = _time(14, 30)
    post_latest = _time(15, 55)

    results = []
    for day, day_rows in by_day.items():
        day_rows.sort(key=lambda r: r["_datetime"])

        pre = None
        for r in day_rows:
            if r["_datetime"].time() < auction_start:
                pre = r
            else:
                break
        if pre is not None and pre["_datetime"].time() < pre_earliest:
            pre = None  # too far from the auction to trust as "the pre-auction reading"

        post = None
        for r in day_rows:
            if r["_datetime"].time() > auction_end:
                post = r
                break
        if post is not None and post["_datetime"].time() > post_latest:
            post = None  # too far from the auction to trust as "the post-auction reading"

        if pre is None or post is None:
            continue  # incomplete or untrustworthy day -- skip, don't guess

        pre_price = pre.get("Spot")
        post_price = post.get("Spot")
        if pre_price is None or post_price is None:
            continue

        move_abs = post_price - pre_price
        move_pct = (move_abs / pre_price * 100) if pre_price else None

        results.append({
            "date": day,
            "pre_auction_time": pre["Time"],
            "pre_auction_price": pre_price,
            "post_auction_time": post["Time"],
            "post_auction_price": post_price,
            "move_abs": round(move_abs, 2),
            "move_pct": round(move_pct, 3) if move_pct is not None else None,
        })

    return sorted(results, key=lambda r: r["date"], reverse=True)


# ---------------------------------------------------------------------------
# Trend & Momentum -- pure price-action second opinion, Sep 2 2026
# ---------------------------------------------------------------------------
# Genuine second read alongside the options-derived Bias above -- SAME
# multi-factor-vote, abstain-on-missing-data, require-real-agreement
# philosophy as _derive_bias(), built from classic price-action inputs
# (RSI, distance from SMA, short-term momentum) instead of OI/PCR/max
# pain. Deliberately never called "Bias" on its own, to avoid any
# confusion with, or risk of overwriting, the read that's already been
# tuned against real backtesting.
#
# Daily-frequency data (RSI/SMA/ATR/pivot don't change intraday) --
# cached once per day, NOT logged into the ~60s-cadence Snapshots
# sheet, which would mean hundreds of duplicate rows a day for numbers
# that only actually update once.
#
# HONEST NOTE on "Expected Daily Range": inferred as roughly ATR/2 from
# a single reference example (ATR 158.17 -> range +-78.31, a ~0.495
# ratio) -- a reasonable, common convention, but reverse-engineered
# from one data point, not confirmed as anyone's exact documented rule.
# Everything else here (RSI/SMA/ATR/pivot formulas, volatility bands)
# is standard, textbook technical analysis, not reverse-engineered from
# the screenshot at all.

import statistics

TECH_BIAS_MARGIN_FOR_DIRECTION = 2
TECH_BIAS_MARGIN_FOR_STRONG = 3

_daily_history_cache = {}  # {index_name: {'date': 'YYYY-MM-DD', 'candles': [...]}}


def compute_rsi(closes, period=14):
    """Wilder's RSI -- the standard, original smoothed-average formula,
    same one virtually every charting platform defaults to. Needs
    period+1 closes minimum, else None (never a guessed value)."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_gain == 0 and avg_loss == 0:
        return 50.0  # genuinely flat market -- neutral, not maximally bullish
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def compute_sma(closes, period=20):
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 2)


def compute_atr(candles, period=14):
    """candles: list of {'high','low','close'}, oldest first. Wilder's
    smoothed True Range average -- same smoothing convention as RSI
    above, for consistency."""
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h, l, prev_c = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    atr = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
    return round(atr, 2)


def compute_pivot_levels(prev_high, prev_low, prev_close):
    """Classic pivot point formula, using the most recent COMPLETE
    day's H/L/C -- P=(H+L+C)/3, R1=2P-L, S1=2P-H. Deliberately named
    pivot_resistance/pivot_support wherever this is consumed, never
    just Support/Resistance -- this file already has OI-wall-based
    Support/Resistance fields that mean something entirely different."""
    pivot = (prev_high + prev_low + prev_close) / 3
    r1 = round(2 * pivot - prev_low, 2)
    s1 = round(2 * pivot - prev_high, 2)
    return r1, s1


def compute_annualized_volatility(closes):
    """Std dev of daily returns, annualized via sqrt(252) trading days
    -- the standard convention."""
    if len(closes) < 2:
        return None
    returns = [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))]
    if len(returns) < 2:
        return None
    daily_std = statistics.stdev(returns)
    return round(daily_std * (252 ** 0.5) * 100, 2)


def classify_volatility_environment(annualized_vol_pct):
    """Bands are standard, widely-used conventions for index
    volatility -- not thresholds fitted to this project's own data.
    Same "reasonable, not validated" status as every other non-
    strategy-specific threshold in this project."""
    if annualized_vol_pct is None:
        return None
    if annualized_vol_pct < 10:
        return "Low (Complacent)"
    elif annualized_vol_pct < 18:
        return "Normal"
    elif annualized_vol_pct < 28:
        return "Elevated"
    return "High (Stressed)"


def _fetch_daily_history(index_name, days_back=60):
    """Cached per index per calendar day -- same caching principle as
    _front_month_bullion_symbol above (this data doesn't change
    intraday, no reason to re-fetch every ~60s snapshot cycle).
    Returns a list of {'date','open','high','low','close'} dicts,
    oldest first, or [] if the fetch fails or Fyers has nothing."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    cached = _daily_history_cache.get(index_name)
    if cached and cached["date"] == today_str:
        return cached["candles"]

    from .fyers_client import get_history
    fyers_symbol = INDEX_SYMBOLS.get(index_name)
    if not fyers_symbol:
        return []

    range_to = datetime.now().strftime("%Y-%m-%d")
    range_from = (datetime.now() - timedelta(days=days_back * 2)).strftime("%Y-%m-%d")
    try:
        resp = get_history(fyers_symbol, resolution="1D", range_from=range_from, range_to=range_to)
    except Exception as e:
        print(f"[IndexTracker] {index_name} daily history fetch failed: {e}")
        return []
    if not resp or resp.get("s") != "ok":
        return []

    candles = []
    for c in resp.get("candles", []):
        if len(c) < 5:
            continue
        candles.append({
            "date": datetime.fromtimestamp(c[0]).strftime("%Y-%m-%d"),
            "open": c[1], "high": c[2], "low": c[3], "close": c[4],
        })
    candles.sort(key=lambda x: x["date"])
    if len(candles) > days_back:
        candles = candles[-days_back:]

    _daily_history_cache[index_name] = {"date": today_str, "candles": candles}
    return candles


def _tech_bias_vote_rsi(rsi):
    if rsi is None:
        return "abstain"
    if rsi >= 55:
        return "bullish"
    if rsi <= 45:
        return "bearish"
    return "abstain"


def _tech_bias_vote_sma_distance(distance_pct):
    if distance_pct is None:
        return "abstain"
    if distance_pct >= 0.5:
        return "bullish"
    if distance_pct <= -0.5:
        return "bearish"
    return "abstain"


def _tech_bias_vote_momentum(closes, lookback=5):
    if len(closes) < lookback + 1:
        return "abstain"
    change_pct = (closes[-1] / closes[-1 - lookback] - 1) * 100
    if change_pct >= 0.3:
        return "bullish"
    if change_pct <= -0.3:
        return "bearish"
    return "abstain"


def _derive_technical_bias(rsi, sma_distance_pct, closes):
    """3-vote version of _derive_bias()'s exact philosophy -- abstain
    on missing data, require a real margin before committing to a
    direction, a wider margin still for "Strong". Never returns
    "Bias" as a label -- always "Technical Bias" wherever consumed."""
    votes = [
        _tech_bias_vote_rsi(rsi),
        _tech_bias_vote_sma_distance(sma_distance_pct),
        _tech_bias_vote_momentum(closes),
    ]
    bullish = votes.count("bullish")
    bearish = votes.count("bearish")
    margin = bullish - bearish
    if abs(margin) < TECH_BIAS_MARGIN_FOR_DIRECTION:
        return "Neutral"
    direction = "Bullish" if margin > 0 else "Bearish"
    if abs(margin) >= TECH_BIAS_MARGIN_FOR_STRONG:
        return f"{direction} (Strong)"
    return direction


def compute_market_regime(technical_bias, volatility_environment):
    """
    Sep 2 2026: real Regime Engine ingredient -- combines the two
    things already built today (Technical Bias for trend direction,
    Volatility Environment for volatility level) into one label.
    Deliberately informational only, same boundary as every other
    classification added today -- this does NOT gate live signal
    selection. Whether a regime label actually predicts anything for
    THIS strategy is a real question, but it's a "wait for enough
    real accumulated data" question (same one already blocking the
    base-score-floor and OI-handling ablation variants), not a "build
    more code" question -- there's nothing further to build here
    until that data exists.

    Returns None if either input is missing, never a guessed regime.
    """
    if not technical_bias or not volatility_environment:
        return None

    is_bullish = technical_bias.startswith("Bullish")
    is_bearish = technical_bias.startswith("Bearish")
    is_calm = volatility_environment.startswith("Low") or volatility_environment == "Normal"

    if is_bullish:
        return "Trending Bullish (Calm)" if is_calm else "Volatile Bullish"
    elif is_bearish:
        return "Trending Bearish (Calm)" if is_calm else "Volatile Bearish"
    else:
        return "Range-Bound / Consolidating" if is_calm else "Choppy / Directionless"


def get_trend_momentum_card(index_name, current_spot=None):
    """
    Sep 2 2026: the actual "Trend & Momentum" card -- pure price-action
    read (RSI/SMA/ATR/pivot S-R/volatility/Technical Bias), completely
    separate from the options-derived snapshot above. Works for any
    name in INDEX_SYMBOLS (NIFTY and BANKNIFTY both), matching this
    file's existing symmetric-handling convention rather than
    singling either one out.

    current_spot: pass in today's live price from the same source the
    main snapshot already uses (oi.get('spot')) -- reused, not a
    second fetch. Falls back to the last daily close if not given.

    Returns None if there isn't enough real daily history to compute
    from (Fyers History API unavailable, or fewer than 21 candles) --
    never a guessed card.
    """
    candles = _fetch_daily_history(index_name)
    if len(candles) < 21:
        return None

    closes = [c["close"] for c in candles]
    rsi = compute_rsi(closes, period=14)
    sma = compute_sma(closes, period=20)
    atr = compute_atr(candles, period=14)
    annualized_vol = compute_annualized_volatility(closes)
    vol_environment = classify_volatility_environment(annualized_vol)

    prev_day = candles[-1]
    r1, s1 = compute_pivot_levels(prev_day["high"], prev_day["low"], prev_day["close"])

    spot = current_spot if current_spot is not None else closes[-1]
    distance_from_sma_pct = round((spot - sma) / sma * 100, 2) if sma else None

    technical_bias = _derive_technical_bias(rsi, distance_from_sma_pct, closes)

    return {
        "index_name": index_name,
        "closing_price": spot,
        "technical_bias": technical_bias,
        "daily_atr": atr,
        "rsi_14": rsi,
        "sma_20": sma,
        "distance_from_sma_pct": distance_from_sma_pct,
        "annualized_volatility_pct": annualized_vol,
        "pivot_resistance_r1": r1,
        "pivot_support_s1": s1,
        "expected_daily_range": round(atr / 2, 2) if atr is not None else None,
        "volatility_environment": vol_environment,
        "market_regime": compute_market_regime(technical_bias, vol_environment),
        "sample_size": len(candles),
    }
