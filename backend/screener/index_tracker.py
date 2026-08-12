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


COLUMNS = [
    "Time", "Spot", "Change %", "Fut", "Fut OI", "Fut OI Chg %", "PCR", "ATM Strike",
    "Put OI (ATM)", "Put OI Chg", "Put Status",
    "Call OI (ATM)", "Call OI Chg", "Call Status",
    "Total Put OI", "Total Call OI",
    "Highest Put OI Strike", "Highest Put OI Value",
    "Highest Call OI Strike", "Highest Call OI Value",
    "IV %", "VIX", "Support", "Resistance", "Max Pain", "Max Pain Dist %",
    "Bias", "Price Confirms Bias",
]

_lock = threading.Lock()
# Cache last snapshot's ATM strike so we can label Put/Call OI CHANGE
# (chg since the last row for this index today), same intraday-buildup
# idea as the reference table's "(High Vol)"/"unwinding" annotations.
_last_snapshot = {}  # {index_name: {'ce_oi': int, 'pe_oi': int}}


def _today_path(index_name):
    today = datetime.now().strftime("%Y-%m-%d")
    day_dir = os.path.join(LOG_DIR, today)
    os.makedirs(day_dir, exist_ok=True)
    return os.path.join(day_dir, f"index_tracker_{index_name}_{today}.xlsx")


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
        return wb
    wb = Workbook()
    ws = wb.active
    ws.title = "Snapshots"
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
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
    """
    if pcr is None:
        return "Neutral"
    if pcr > 1.6:
        return "Bullish (Strong)"
    if pcr > 1.05:
        return "Bullish"
    if pcr < 0.5:
        return "Bearish (Strong)"
    if pcr < 0.95:
        return "Bearish"
    return "Neutral"


def _status_label(oi_chg):
    """'Writing' (OI building up) vs 'Unwinding' (OI coming off) -- the
    reference table's own vocabulary."""
    if oi_chg is None:
        return "—"
    return "Writing" if oi_chg > 0 else "Unwinding" if oi_chg < 0 else "Flat"


def _price_confirms_bias(change_percent, bias):
    """Same confirmation concept already used for individual stock
    signals (Round 3), applied here: does the index's actual price move
    agree with what the OI positioning implies? This is the extra
    confirmation layer -- OI can say 'Bullish' while price is actually
    falling (a real warning sign, not a contradiction to ignore).

    Also flags the Neutral case specifically: PCR sitting in the wide
    middle band (0.7-1.3) doesn't mean price itself is standing still --
    a real, sustained move can happen while OI positioning just hasn't
    caught up yet. Uses a wider +-0.3% threshold than the +-0.05% used
    for Bullish/Bearish confirmation above, on purpose -- this is meant
    to catch a genuinely notable divergence (a sustained slide/rally),
    not flag on every few-minute wobble while Bias sits Neutral, which
    would fire constantly and stop being useful. 0.3% is a judgment
    call, not a rigorously derived number -- adjust it if it fires too
    often or too rarely once it's been watched in practice.
    """
    if change_percent is None or bias is None:
        return "—"
    if change_percent > 0.05 and bias.startswith("Bullish"):
        return "✓ Confirmed"
    if change_percent < -0.05 and bias.startswith("Bearish"):
        return "✓ Confirmed"
    if change_percent > 0.05 and bias.startswith("Bearish"):
        return "⚠ Conflict"
    if change_percent < -0.05 and bias.startswith("Bullish"):
        return "⚠ Conflict"
    if bias == "Neutral" and change_percent <= -0.3:
        return "⚠ Neutral but falling"
    if bias == "Neutral" and change_percent >= 0.3:
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

    from .market_hours import is_market_hours
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
    confirms = _price_confirms_bias(change_percent, bias)

    row = {
        "Time": datetime.now().strftime("%H:%M:%S"),
        "Spot": oi.get("spot"),
        "Fut": fut_price,
        "Fut OI": fut_oi,
        "Fut OI Chg %": fut_oi_chg_pct,
        "Change %": change_percent,
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
        "Bias": bias, "Price Confirms Bias": confirms,
    }

    try:
        path = _today_path(index_name)
        wb = _get_workbook(path)
        ws = wb["Snapshots"]
        ws.append([row[c] for c in COLUMNS])
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


def get_today_snapshots(index_name, limit=100):
    """Read today's logged rows for the frontend table (most recent
    first). Returns [] if nothing logged yet today."""
    if not OPENPYXL_AVAILABLE or index_name not in INDEX_SYMBOLS:
        return []
    path = _today_path(index_name)
    if not os.path.exists(path):
        return []
    try:
        wb = load_workbook(path)
        ws = wb["Snapshots"]
        # Zip against the file's OWN header row, not the current in-memory
        # COLUMNS constant -- a column added mid-day (like this one) means
        # an already-written file's real column order can legitimately
        # differ from what COLUMNS says right now. Zipping against the
        # constant silently shifted every value after the change point
        # onto the wrong new label for any row written before the change
        # (caught live: PCR/ATM Strike/VIX/etc. all showing garbage after
        # Fut OI / Fut OI Chg % were inserted). Reading the file's actual
        # header keeps older rows correctly labeled regardless.
        file_columns = [c.value for c in ws[1]]
        rows = []
        for r in ws.iter_rows(min_row=2, values_only=True):
            rows.append(dict(zip(file_columns, r)))
        return list(reversed(rows))[:limit]
    except Exception as e:
        print(f"[IndexTracker] Failed to read {index_name} snapshots: {e}")
        return []


def get_today_log_path(index_name):
    path = _today_path(index_name)
    return path if os.path.exists(path) else None