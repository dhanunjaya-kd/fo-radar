"""
screener/index_agreement_logger.py

Sep 9 2026: tracks real episodes where index_tracker.py's Bias and the
OI Signal quadrant (the same badge just added to IndexTracker.jsx/
MarketView.jsx) agree or disagree for NIFTY/BANKNIFTY, with real future
price outcome tracking -- built directly from a real disagreement the
user found live in their own running app (11:02:20 IST, 09 Sep 2026:
Bias read Bullish while every OI Signal reading in that window read
Short Buildup).

Deliberately a SEPARATE file from shadow_logger.py, not a forced fit
into its schema -- that file compares v3.0's decision to
quality_engine's decision for a STOCK candidate (entry/SL-adjacent
concepts); this compares two already-computed INDEX-level reads
against each other. Same PROVEN PATTERNS reused directly, not
reimplemented: the day-folder xlsx layout, the archive-and-restart
schema-migration protection, and the real-quote-based multi-horizon
outcome tracking -- copied from shadow_logger.py's own real, tested
logic, not rebuilt from scratch.

EPISODE-based logging, not per-snapshot: this loop runs roughly every
60-120s, and the same agreement/disagreement state routinely holds for
many consecutive snapshots (confirmed directly in the user's own
screenshot -- Short Buildup showed on every row from 10:52 to 11:23).
Logging every snapshot would flood the log with near-duplicate rows
telling you nothing new. Instead, a new row is written only when the
agreement STATE actually changes for that index -- "here's when this
episode started," then real future prices are tracked from that one
reference point, same as shadow_logger.py already does per candidate.

The quadrant itself is NOT recomputed here -- it reuses
options_analytics.classify_side_buildup() directly, the exact same
function quality_engine.py's evaluate_futures_oi_structure() already
calls, and the exact same logic the frontend badge (IndexTracker.jsx/
MarketView.jsx) mirrors for display. One real implementation, read
from three places.
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

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "signal_logs")

HORIZONS_MINUTES = [5, 15, 30, 60]

COLUMNS = [
    "Timestamp", "Index", "Bias", "OI Signal", "Change %", "Fut OI Chg %",
    "Reference Price", "Agreement",
    "Price +5m", "Price +15m", "Price +30m", "Price +60m", "Price EOD",
    "MFE %", "MAE %",
]

BULLISH_BIAS = {"Bullish", "Bullish (Strong)"}
BEARISH_BIAS = {"Bearish", "Bearish (Strong)"}
BULLISH_QUADRANTS = {"Long Buildup", "Short Covering"}
BEARISH_QUADRANTS = {"Short Buildup", "Long Unwinding"}

_lock = threading.Lock()
# Own state, not shared with shadow_logger.py or anything else.
# {index_name: {'agreement': 'AGREE'/'DISAGREE'/'NEUTRAL_BIAS', 'row': N,
#  'date': 'YYYY-MM-DD', 'reference_price': float, 'entry_dt': datetime,
#  'resolved': {'5m': bool, ...}}}
_current_episode = {}


def classify_agreement(bias, quadrant):
    """
    Real classification, not a guess -- Neutral bias genuinely doesn't
    confirm or contradict either OI direction, so it's its own state
    rather than being force-fit into AGREE or DISAGREE. Missing bias
    or quadrant also lands here rather than a fabricated default.

    Returns 'AGREE' / 'DISAGREE' / 'NEUTRAL_BIAS'.
    """
    if bias in BULLISH_BIAS and quadrant in BULLISH_QUADRANTS:
        return "AGREE"
    if bias in BEARISH_BIAS and quadrant in BEARISH_QUADRANTS:
        return "AGREE"
    if bias in BULLISH_BIAS and quadrant in BEARISH_QUADRANTS:
        return "DISAGREE"
    if bias in BEARISH_BIAS and quadrant in BULLISH_QUADRANTS:
        return "DISAGREE"
    return "NEUTRAL_BIAS"


def _today_path():
    today = datetime.now().strftime("%Y-%m-%d")
    day_dir = os.path.join(LOG_DIR, today)
    os.makedirs(day_dir, exist_ok=True)
    return os.path.join(day_dir, f"index_agreement_{today}.xlsx"), today


def _get_workbook(path):
    """Same archive-and-restart schema-migration protection
    shadow_logger.py already uses -- a mid-day COLUMNS change archives
    the old file instead of silently misaligning rows under the wrong
    headers."""
    if os.path.exists(path):
        wb = load_workbook(path)
        ws = wb["Agreement"]
        existing_header = [c.value for c in ws[1]]
        if existing_header != COLUMNS:
            archive_path = path.replace(".xlsx", "_pre-update.xlsx")
            if not os.path.exists(archive_path):
                wb.save(archive_path)
                print(f"[IndexAgreementLog] Column layout changed -- archived old data to {os.path.basename(archive_path)}")
            wb = Workbook()
            ws = wb.active
            ws.title = "Agreement"
            ws.append(COLUMNS)
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
        return wb
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Agreement"
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
    return wb


def log_agreement_state(index_name, bias, change_pct, fut_oi_chg_pct, price):
    """
    Call every cycle for each index -- silently does nothing unless
    the agreement state has genuinely CHANGED since the last logged
    row for this index (a new episode). price is the index's own Spot
    (or Fut, caller's choice, but must be consistent with whatever
    check_agreement_outcomes() fetches quotes for) -- frozen as the
    episode's Reference Price once written, never updated afterward.

    Returns True if a new episode row was written, False otherwise
    (state unchanged, or openpyxl/inputs unavailable).
    """
    if not OPENPYXL_AVAILABLE or price is None:
        return False

    from .options_analytics import classify_side_buildup
    quadrant = classify_side_buildup(change_pct, fut_oi_chg_pct) if change_pct is not None and fut_oi_chg_pct is not None else None
    agreement = classify_agreement(bias, quadrant)

    today = datetime.now().strftime("%Y-%m-%d")
    with _lock:
        existing = _current_episode.get(index_name)
        if existing and existing.get("date") == today and existing.get("agreement") == agreement:
            return False  # same episode still running -- not a new row

        path, _ = _today_path()
        try:
            wb = _get_workbook(path)
            ws = wb["Agreement"]
            now = datetime.now()
            row = [
                now.strftime("%Y-%m-%d %H:%M:%S"), index_name, bias, quadrant,
                change_pct, fut_oi_chg_pct, price, agreement,
                None, None, None, None, None,
                0.0, 0.0,
            ]
            ws.append(row)
            row_num = ws.max_row
            wb.save(path)

            _current_episode[index_name] = {
                "agreement": agreement, "row": row_num, "date": today,
                "reference_price": price, "entry_dt": now,
                "resolved": {"5m": False, "15m": False, "30m": False, "60m": False, "eod": False},
            }
            return True
        except Exception as e:
            print(f"[IndexAgreementLog] Failed to log {index_name}: {e}")
            return False


def _is_eod():
    """Same 3:40 PM NSE derivatives close used throughout this
    project."""
    now = datetime.now()
    return now.hour > 15 or (now.hour == 15 and now.minute >= 40)


def check_agreement_outcomes(get_quotes_fn):
    """
    Same real-quote, real-elapsed-time horizon resolution as
    shadow_logger.check_shadow_outcomes() -- a horizon that isn't due
    yet, or whose fetch fails, is left unresolved until a later cycle,
    never backfilled with an estimate. MFE/MAE are NOT direction-
    adjusted here (unlike shadow_logger's BUY/SELL-aware version) --
    an index episode doesn't have a stated direction the way a stock
    candidate does, so this simply tracks the raw % move from the
    episode's reference price; a positive MFE always means price rose,
    regardless of whether Bias/OI Signal were bullish or bearish at
    the time. Read Bias/OI Signal alongside MFE/MAE to judge which
    read the eventual move correctly.
    """
    if not OPENPYXL_AVAILABLE:
        return
    with _lock:
        open_indices = [k for k, v in _current_episode.items() if not v["resolved"]["eod"]]
    if not open_indices:
        return

    now = datetime.now()
    due = {}
    for index_name in open_indices:
        with _lock:
            state = _current_episode.get(index_name)
        if not state:
            continue
        elapsed_min = (now - state["entry_dt"]).total_seconds() / 60
        horizons_due = [f"{h}m" for h in HORIZONS_MINUTES if elapsed_min >= h and not state["resolved"][f"{h}m"]]
        if _is_eod() and not state["resolved"]["eod"]:
            horizons_due.append("eod")
        if horizons_due:
            due[index_name] = horizons_due

    if not due:
        return

    symbol_map = {"NIFTY": "NSE:NIFTY50-INDEX", "BANKNIFTY": "NSE:NIFTYBANK-INDEX"}
    fyers_symbols = [symbol_map[i] for i in due if i in symbol_map]
    try:
        resp = get_quotes_fn(fyers_symbols)
    except Exception as e:
        print(f"[IndexAgreementLog] Outcome quote fetch failed: {e}")
        return

    ltp_by_index = {}
    if resp and resp.get("s") == "ok":
        for item in resp.get("d", []):
            if item.get("s") == "ok":
                v = item.get("v", {}) or {}
                if v.get("lp") is not None:
                    sym = item.get("n") or ""
                    for idx_name, fyers_sym in symbol_map.items():
                        if sym == fyers_sym:
                            ltp_by_index[idx_name] = v["lp"]

    path, _ = _today_path()
    with _lock:
        try:
            wb = _get_workbook(path)
            ws = wb["Agreement"]
            col = {name: i + 1 for i, name in enumerate(COLUMNS)}
            changed = False
            horizon_col = {"5m": "Price +5m", "15m": "Price +15m", "30m": "Price +30m", "60m": "Price +60m", "eod": "Price EOD"}

            for index_name, horizons_due in due.items():
                ltp = ltp_by_index.get(index_name)
                if ltp is None:
                    continue
                state = _current_episode[index_name]
                row_num = state["row"]
                ref_price = state["reference_price"]

                for label in horizons_due:
                    ws.cell(row=row_num, column=col[horizon_col[label]]).value = ltp
                    state["resolved"][label] = True
                    changed = True

                move_pct = round((ltp - ref_price) / ref_price * 100, 2) if ref_price else 0.0
                mfe = ws.cell(row=row_num, column=col["MFE %"]).value or 0.0
                mae = ws.cell(row=row_num, column=col["MAE %"]).value or 0.0
                ws.cell(row=row_num, column=col["MFE %"]).value = round(max(mfe, move_pct), 2)
                ws.cell(row=row_num, column=col["MAE %"]).value = round(min(mae, move_pct), 2)

            if changed:
                wb.save(path)
        except Exception as e:
            print(f"[IndexAgreementLog] Failed to write outcomes: {e}")


def get_today_agreement_log():
    """JSON-safe list of today's episodes, newest first -- [] (never
    raises) if nothing's logged yet today."""
    if not OPENPYXL_AVAILABLE:
        return []
    path, _ = _today_path()
    if not os.path.exists(path):
        return []
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb["Agreement"]
        headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        rows = []
        for raw in ws.iter_rows(min_row=2, values_only=True):
            row = dict(zip(headers, raw))
            ts = row.get("Timestamp")
            row["Timestamp"] = str(ts) if ts is not None else None
            rows.append(row)
        rows.reverse()
        return rows
    except Exception as e:
        print(f"[IndexAgreementLog] Failed to read today's log: {e}")
        return []
