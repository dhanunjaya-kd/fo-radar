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
# base name to build that rolling symbol from (see
# _front_month_commodity_symbol below), not a static Fyers symbol like
# INDEX_SYMBOLS holds.
COMMODITY_BASES = {
    "CRUDEOIL": "CRUDEOIL",
    "CRUDEOILM": "CRUDEOILM",
}

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
    "IV %", "VIX", "Support", "Resistance", "Max Pain", "Max Pain Dist %",
    "OI Buildup", "Bias", "Price Confirms Bias",
    "Confirms 5min", "Confirms 30min", "Confirms 60min", "Horizons Confirming",
]

_lock = threading.Lock()
# Cache last snapshot's ATM strike so we can label Put/Call OI CHANGE
# (chg since the last row for this index today), same intraday-buildup
# idea as the reference table's "(High Vol)"/"unwinding" annotations.
_last_snapshot = {}  # {index_name: {'ce_oi': int, 'pe_oi': int}}

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


FLIPS_COLUMNS = ["Date", "Time", "From Bias", "To Bias", "Price", "Price Confirms Bias", "OI Buildup"]


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
    """
    if "Flips" in wb.sheetnames:
        return
    ws = wb.create_sheet("Flips")
    ws.append(FLIPS_COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")


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


def _derive_bias(pcr, oi_buildup):
    """
    Reverted to the original tight Neutral zone (0.95-1.05) on request,
    after a real instance where a genuine ~150-point, hours-long NIFTY
    slide still read Neutral because PCR (0.81-0.86) sat comfortably
    inside the wider 0.7-1.3 band that had replaced this. That wider
    band was adopted specifically because the tight one caused Bias to
    flip Bullish/Bearish constantly on ordinary PCR noise, not real
    regime changes -- reverting trades that stability back for
    sensitivity, deliberately, with that tradeoff understood.

    Only the Neutral zone itself is restored to its documented original
    value. The Strong-tier cutoffs (1.6 / 0.5) are left exactly as they
    were in the wide-band version -- there's no record of those ever
    being different, so this doesn't guess at numbers nobody wrote
    down; it only changes what's actually documented.

    The "Neutral but falling/rising" flag added alongside the wide
    bands (see _price_confirms_bias) stays in place -- it's still
    useful for the narrower window where PCR sits exactly in 0.95-1.05
    while price moves, just triggers less often now that Bias itself
    is more sensitive.

    Aug 14 2026 -- oi_buildup now actually used. It's a plain label from
    options_analytics.analyze_option_chain(): 'CE writing dominant
    (bearish)', 'PE writing dominant (bullish)', or 'Mixed / no clear
    dominance' -- computed from TODAY's chain-wide OI change (fresh
    writing activity since market open), which is a meaningfully
    DIFFERENT signal from PCR (the current absolute OI level, built up
    over however many prior days). PCR can stay "Bullish" purely on old
    put OI that's just sitting there while today's actual writing is
    going the other way -- that gap is exactly what real backtest data
    (Aug 10-14 2026) showed: PCR-alone accuracy was weak-to-below-
    coin-flip. This does NOT touch the PCR tier boundaries above --
    only refines the result using oi_buildup, and only when oi_buildup
    has a clear read:
      - PCR says Neutral, but today's flow leans one way -> surface
        that as a plain (non-Strong) directional read instead of
        staying silent on a real signal, same spirit as the existing
        "Neutral but falling/rising" price-based flag, one layer
        earlier (about OI flow here, not price).
      - PCR is directional but today's flow actively disagrees ->
        soften to Neutral rather than keep asserting a confident
        directional call two of the app's own signals disagree on.
      - Both agree, or oi_buildup is 'Mixed'/None -> PCR's tier is
        used unchanged, Strong included.

    HONEST LIMITATION: oi_buildup itself was never a logged column
    historically (only the ATM-only Put/Call OI Chg columns were), so
    this specific change can't be retroactively verified against past
    data the way the _price_confirms_bias rewrite was -- it can only
    be watched going forward from here.
    """
    if pcr is None:
        return "Neutral"
    if pcr > 1.6:
        pcr_bias = "Bullish (Strong)"
    elif pcr > 1.05:
        pcr_bias = "Bullish"
    elif pcr < 0.5:
        pcr_bias = "Bearish (Strong)"
    elif pcr < 0.95:
        pcr_bias = "Bearish"
    else:
        pcr_bias = "Neutral"

    oi_direction = None
    if oi_buildup == "PE writing dominant (bullish)":
        oi_direction = "bullish"
    elif oi_buildup == "CE writing dominant (bearish)":
        oi_direction = "bearish"
    # 'Mixed / no clear dominance', None, or anything unrecognized -->
    # no clear fresh-flow read to weigh in with, use PCR's tier as-is.
    if oi_direction is None:
        return pcr_bias

    if pcr_bias == "Neutral":
        return "Bullish" if oi_direction == "bullish" else "Bearish"

    pcr_direction = "bullish" if pcr_bias.startswith("Bullish") else "bearish"
    if pcr_direction != oi_direction:
        return "Neutral"

    return pcr_bias


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
    intensity change, not a flip."""
    if not bias:
        return None
    if bias.startswith("Bullish"):
        return "up"
    if bias.startswith("Bearish"):
        return "down"
    return None


def _log_flip_if_changed(wb, name, bias, price, confirms, oi_buildup, date_str, time_str):
    """
    Appends one row to the Flips sheet only when direction genuinely
    changed since the last reading for this name -- Neutral readings
    don't overwrite the remembered direction (same as
    backtest_index_bias.py's flip counting: a dip to Neutral and back
    to the same direction isn't two flips, it's zero). Writes nothing
    on the very first reading for a name in this process (nothing to
    compare against yet) or when the direction is unchanged.
    """
    global _last_direction, _last_bias_string
    new_dir = _bias_direction(bias)
    prev_dir = _last_direction.get(name)
    prev_bias_str = _last_bias_string.get(name)

    if new_dir is not None and new_dir != prev_dir and prev_dir is not None:
        ws = wb["Flips"]
        ws.append([date_str, time_str, prev_bias_str, bias, price, confirms, oi_buildup])

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
    vix: India VIX, same reasoning -- already fetched elsewhere per cycle.
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

    bias = _derive_bias(oi.get("pcr"), oi.get("oi_buildup"))
    # Multi-horizon momentum, NOT the day-cumulative change_percent --
    # see _price_confirms_bias()'s docstring for why. Spot specifically
    # (not Fut), matching the same choice already made in
    # compute_cas_auction_moves() for the same reason: Fut trades
    # through the CAS window differently and isn't the number this
    # confirmation check is meant to be about.
    horizon_changes = _record_and_get_multi_horizon_changes(index_name, oi.get("spot"))
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
        "IV %": oi.get("iv"), "VIX": vix,
        "Support": oi.get("support"), "Resistance": oi.get("resistance"),
        "Max Pain": oi.get("max_pain"), "Max Pain Dist %": oi.get("max_pain_dist_pct"),
        "OI Buildup": oi.get("oi_buildup"),
        "Bias": bias, "Price Confirms Bias": confirms,
        "Confirms 5min": per_horizon_confirms[5],
        "Confirms 30min": per_horizon_confirms[30],
        "Confirms 60min": per_horizon_confirms[60],
        "Horizons Confirming": horizons_summary,
    }

    try:
        path = _today_path(index_name)
        wb = _get_workbook(path)
        ws = wb["Snapshots"]
        ws.append([row[c] for c in COLUMNS])
        _log_flip_if_changed(wb, index_name, bias, row.get("Spot"), confirms, row.get("OI Buildup"), datetime.now().strftime("%Y-%m-%d"), row["Time"])
        wb.save(path)
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
    fut_symbol = _front_month_commodity_symbol(base)

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

    bias = _derive_bias(oi.get("pcr"), oi.get("oi_buildup"))
    # Multi-horizon momentum, same as snapshot_index() -- but Fut here,
    # not Spot, since commodities have no separate spot/cash index (the
    # futures contract IS the underlying, same reasoning as everywhere
    # else in this function).
    horizon_changes = _record_and_get_multi_horizon_changes(name, fut_price)
    confirms = _price_confirms_bias(horizon_changes.get(15), bias)  # unchanged 15min value -- stays comparable to the Aug 14 backtest baseline
    per_horizon_confirms, horizons_summary = _multi_horizon_confirms(horizon_changes, bias)

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
        "IV %": oi.get("iv"), "VIX": None,  # India VIX is an equity-index concept, not applicable here
        "Support": oi.get("support"), "Resistance": oi.get("resistance"),
        "Max Pain": oi.get("max_pain"), "Max Pain Dist %": oi.get("max_pain_dist_pct"),
        "OI Buildup": oi.get("oi_buildup"),
        "Bias": bias, "Price Confirms Bias": confirms,
        "Confirms 5min": per_horizon_confirms[5],
        "Confirms 30min": per_horizon_confirms[30],
        "Confirms 60min": per_horizon_confirms[60],
        "Horizons Confirming": horizons_summary,
    }

    try:
        path = _today_path(name)
        wb = _get_workbook(path)
        ws = wb["Snapshots"]
        ws.append([row[c] for c in COLUMNS])
        _log_flip_if_changed(wb, name, bias, row.get("Fut"), confirms, row.get("OI Buildup"), datetime.now().strftime("%Y-%m-%d"), row["Time"])
        wb.save(path)
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


def get_snapshots_for_date(index_name, date_str, limit=100):
    """Read logged rows for a specific date (YYYY-MM-DD), most recent
    first. Returns [] if nothing was logged that date (a weekend, a
    holiday, or before this started running) rather than erroring."""
    if not OPENPYXL_AVAILABLE or index_name not in TRACKABLE_NAMES:
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
        return list(reversed(rows))[:limit]
    except Exception as e:
        print(f"[IndexTracker] Failed to read {index_name} snapshots for {date_str}: {e}")
        return []


def get_today_snapshots(index_name, limit=100):
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