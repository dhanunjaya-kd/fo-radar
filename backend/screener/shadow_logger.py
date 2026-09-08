"""
screener/shadow_logger.py

Sep 8 2026: SHADOW MODE logging -- for every candidate _build_all()
already evaluates this cycle, records BOTH v3.0's real decision AND
quality_engine's independent assessment, side by side, then tracks
REAL future price observations at several horizons so the two can
eventually be compared on real outcomes, not assumption.

Deliberately OWN, SEPARATE state from excel_logger.py's
_row_index/_open_positions and index_signal.py's _locked_calls --
per the Phase 0 audit's explicit finding: sharing either would risk
corrupting live signal tracking, which nothing in this file is
allowed to touch. This module never reads or writes excel_logger.py's
or index_signal.py's state, and _build_all()'s existing signal
selection is never altered by anything here -- this is a pure
observer, logging what ALREADY happened, never influencing it.

ONE row per (symbol, action) per calendar day -- same "first genuinely
new setup today" concept excel_logger.py already uses, own separate
dict so a symbol staying qualified across many 90s cycles doesn't spam
duplicate rows. Once logged, a row's Reference Price is FROZEN (same
"a plan has to hold still once shown" principle used throughout this
project) -- outcome tracking measures against that one frozen number,
never a moving target.

Reference price is the STOCK's own price at signal time, not the
option premium -- the research question here is "was the underlying
setup good," independent of which specific strike/contract v3.0 chose
(that's a separate, already-gated concern -- liquidity/spread/lot-size
gates already exist in the live engine). MFE/MAE are tracked in the
SAME direction as the shadow candidate's action (BUY -> favorable is
up, SELL -> favorable is down), matching how a real trader would read
"favorable" for that side.

HORIZONS: 5/15/30/60 minutes + EOD, per spec section 20. A horizon is
recorded once elapsed time crosses its threshold, using a REAL fetched
quote -- never estimated, never backfilled with a guess if the fetch
fails (that horizon just stays unresolved until the next successful
check).
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
PATH = os.path.join(LOG_DIR, "shadow_signals.xlsx")

HORIZONS_MINUTES = [5, 15, 30, 60]  # EOD handled separately, see _is_eod()

COLUMNS = [
    "Timestamp", "Symbol", "Action",
    "V3 Decision", "V3 Score", "V3 Grade", "V3 Reason",
    "Quality Verdict", "Quality Score", "Quality Grade",
    "Quality Components Scored", "Quality Components Unavailable",
    "Reference Price",
    "Price +5m", "Price +15m", "Price +30m", "Price +60m", "Price EOD",
    "MFE %", "MAE %",
    "Agreement",  # "AGREE" / "V3_ONLY" / "QUALITY_ONLY" / "DISAGREE" -- both said no-trade differently, etc.
    "Reasons",  # Sep 8 2026: spec section 18, "Explainable Signals" -- semicolon-joined plain-English reasons/warnings
]

_lock = threading.Lock()
# Own state, NOT shared with excel_logger.py or index_signal.py.
# {(symbol, action): {'row': N, 'date': 'YYYY-MM-DD', 'reference_price': float,
#  'entry_dt': datetime, 'resolved': {'5m': bool, '15m': bool, ...}}}
_shadow_row_index = {}


def _today_path():
    today = datetime.now().strftime("%Y-%m-%d")
    day_dir = os.path.join(LOG_DIR, today)
    os.makedirs(day_dir, exist_ok=True)
    return os.path.join(day_dir, f"shadow_signals_{today}.xlsx"), today


def _get_workbook(path):
    """
    Sep 8 2026: added the same archive-and-restart schema-change
    protection positional_logger.py already uses -- this file didn't
    have it before, a real gap (a mid-day COLUMNS change, like adding
    "Reasons" today, would otherwise silently misalign existing rows
    under the wrong headers instead of failing loudly or migrating
    cleanly).
    """
    if os.path.exists(path):
        wb = load_workbook(path)
        ws = wb["Shadow"]
        existing_header = [c.value for c in ws[1]]
        if existing_header != COLUMNS:
            archive_path = path.replace(".xlsx", "_pre-update.xlsx")
            if not os.path.exists(archive_path):
                wb.save(archive_path)
                print(f"[ShadowLog] Column layout changed -- archived old data to {os.path.basename(archive_path)}, starting fresh")
            wb = Workbook()
            ws = wb.active
            ws.title = "Shadow"
            ws.append(COLUMNS)
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
        return wb
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Shadow"
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
    return wb


def _agreement_label(v3_decision, quality_verdict):
    """v3_decision: 'SIGNAL' (v3.0 produced a live signal) or 'NO_TRADE'
    (v3.0 rejected the candidate at any gate). quality_verdict: 'TRADE'/
    'WATCH'/'IGNORE' from compute_stock_quality_score()."""
    v3_trade = v3_decision == "SIGNAL"
    quality_trade = quality_verdict == "TRADE"
    if v3_trade and quality_trade:
        return "AGREE"
    if v3_trade and not quality_trade:
        return "V3_ONLY"
    if not v3_trade and quality_trade:
        return "QUALITY_ONLY"
    return "AGREE"  # both said no-trade -- also real agreement, not a conflict


def log_shadow_candidate(symbol, action, price, v3_decision, v3_score, v3_grade, v3_reason,
                          quality_result, reasons=None):
    """
    Logs one row for a genuinely new (symbol, action) today, or
    silently does nothing if already logged today (same symbol stays
    qualified across many 90s cycles -- this isn't a duplicate log).

    v3_decision: 'SIGNAL' or 'NO_TRADE'. v3_score/v3_grade/v3_reason:
    whatever v3.0 actually computed/decided this cycle -- v3_reason is
    the no_trade_log reason string when v3_decision is 'NO_TRADE', or
    None when it's a real signal.
    quality_result: the dict returned by
    quality_engine.compute_stock_quality_score().
    reasons: Sep 8 2026 addition, spec section 18 "Explainable
    Signals" -- optional list of plain-English strings (e.g. "RSI
    bullish continuation", "Sector laggard -- avoid for a BUY")
    explaining WHY, built by the caller from the same evidence it
    already computed for scoring. Optional and defaults to None/empty
    for backward compatibility with any caller not yet passing it.

    Returns True if a new row was written, False otherwise (already
    logged today, or openpyxl unavailable, or price is None).
    """
    if not OPENPYXL_AVAILABLE or price is None:
        return False

    key = (symbol, action)
    today = datetime.now().strftime("%Y-%m-%d")

    with _lock:
        existing = _shadow_row_index.get(key)
        if existing and existing.get("date") == today:
            return False  # already logged today, not a new candidate

        path, _ = _today_path()
        try:
            wb = _get_workbook(path)
            ws = wb["Shadow"]
            now = datetime.now()

            agreement = _agreement_label(v3_decision, quality_result.get("verdict"))
            row = [
                now.strftime("%Y-%m-%d %H:%M:%S"), symbol, action,
                v3_decision, v3_score, v3_grade, v3_reason,
                quality_result.get("verdict"), quality_result.get("score"), quality_result.get("grade"),
                ",".join(quality_result.get("components_scored", [])),
                ",".join(quality_result.get("components_unavailable", [])),
                price,
                None, None, None, None, None,  # horizon prices, filled in later
                0.0, 0.0,  # MFE/MAE start at 0 (no observation yet)
                agreement,
                "; ".join(reasons) if reasons else None,
            ]
            ws.append(row)
            row_num = ws.max_row
            wb.save(path)

            _shadow_row_index[key] = {
                "row": row_num, "date": today, "reference_price": price,
                "action": action, "entry_dt": now,
                "resolved": {"5m": False, "15m": False, "30m": False, "60m": False, "eod": False},
            }
            return True
        except Exception as e:
            print(f"[ShadowLog] Failed to log {key}: {e}")
            return False


def _is_eod():
    """Same 3:40 PM NSE derivatives close this project already uses
    elsewhere (market_hours.py's is_market_hours()) -- deliberately not
    importing that function here to avoid any import-order coupling
    with this being a background-thread-called module; the exact same
    cutoff time, kept as a local constant instead."""
    now = datetime.now()
    return now.hour > 15 or (now.hour == 15 and now.minute >= 40)


def check_shadow_outcomes(get_quotes_fn):
    """
    Call once per scan cycle, same injectable-quotes convention
    positional_logger.py already uses. For every open (symbol, action)
    still being watched, checks whether enough real time has elapsed to
    resolve the next horizon, fetches ONE batched quote for everything
    that needs checking this cycle, and records real price + running
    MFE/MAE. A horizon that isn't due yet, or whose fetch fails, is
    simply left unresolved until a later cycle -- never backfilled with
    an estimate.
    """
    if not OPENPYXL_AVAILABLE:
        return
    with _lock:
        open_keys = [k for k, v in _shadow_row_index.items() if not v["resolved"]["eod"]]
    if not open_keys:
        return

    now = datetime.now()
    due = {}  # key -> list of horizon labels due this cycle
    for key in open_keys:
        with _lock:
            state = _shadow_row_index.get(key)
        if not state:
            continue
        elapsed_min = (now - state["entry_dt"]).total_seconds() / 60
        horizons_due = []
        for h in HORIZONS_MINUTES:
            label = f"{h}m"
            if elapsed_min >= h and not state["resolved"][label]:
                horizons_due.append(label)
        if _is_eod() and not state["resolved"]["eod"]:
            horizons_due.append("eod")
        if horizons_due:
            due[key] = horizons_due

    if not due:
        return

    symbols_needed = list({k[0] for k in due})
    fyers_symbols = [f"NSE:{s}-EQ" for s in symbols_needed]
    try:
        resp = get_quotes_fn(fyers_symbols)
    except Exception as e:
        print(f"[ShadowLog] Outcome quote fetch failed: {e}")
        return

    ltp_by_symbol = {}
    if resp and resp.get("s") == "ok":
        for item in resp.get("d", []):
            if item.get("s") == "ok":
                v = item.get("v", {}) or {}
                if v.get("lp") is not None:
                    sym = (item.get("n") or "").replace("NSE:", "").replace("-EQ", "")
                    ltp_by_symbol[sym] = v["lp"]

    path, _ = _today_path()
    with _lock:
        try:
            wb = _get_workbook(path)
            ws = wb["Shadow"]
            col = {name: i + 1 for i, name in enumerate(COLUMNS)}
            changed = False

            horizon_col = {"5m": "Price +5m", "15m": "Price +15m", "30m": "Price +30m",
                            "60m": "Price +60m", "eod": "Price EOD"}

            for key, horizons_due in due.items():
                symbol, action = key
                ltp = ltp_by_symbol.get(symbol)
                if ltp is None:
                    continue  # this symbol's fetch didn't come back clean this cycle -- try again next cycle
                state = _shadow_row_index[key]
                row_num = state["row"]
                ref_price = state["reference_price"]

                for label in horizons_due:
                    ws.cell(row=row_num, column=col[horizon_col[label]]).value = ltp
                    state["resolved"][label] = True
                    changed = True

                # Running MFE/MAE, direction-aware (BUY: favorable=up,
                # SELL: favorable=down) -- computed from every real price
                # observed so far, INCLUDING this one, never estimated.
                direction = 1 if action == "BUY" else -1
                move_pct = round((ltp - ref_price) / ref_price * 100 * direction, 2) if ref_price else 0.0
                mfe = ws.cell(row=row_num, column=col["MFE %"]).value or 0.0
                mae = ws.cell(row=row_num, column=col["MAE %"]).value or 0.0
                ws.cell(row=row_num, column=col["MFE %"]).value = round(max(mfe, move_pct), 2)
                ws.cell(row=row_num, column=col["MAE %"]).value = round(min(mae, move_pct), 2)

            if changed:
                wb.save(path)
        except Exception as e:
            print(f"[ShadowLog] Failed to write outcomes: {e}")


def get_shadow_log_path():
    """Path to today's shadow log, for a download endpoint -- None if
    nothing's been logged yet today."""
    path, _ = _today_path()
    return path if os.path.exists(path) else None


def get_today_shadow_signals(limit=200):
    """
    JSON-safe list of today's shadow rows, newest first -- powers
    ShadowSignalsView. Returns [] (never raises) if nothing's been
    logged yet today or the file can't be read -- same "an empty
    result is not an error" convention NoTradeLogView already uses.
    Reads directly from the real xlsx (source of truth), not from
    _shadow_row_index (in-memory, wiped on restart) -- so this stays
    correct even right after a server restart mid-day.
    """
    if not OPENPYXL_AVAILABLE:
        return []
    path, _ = _today_path()
    if not os.path.exists(path):
        return []
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb["Shadow"]
        headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        rows = []
        for raw in ws.iter_rows(min_row=2, values_only=True):
            row = dict(zip(headers, raw))
            # openpyxl gives back real datetime objects for the
            # Timestamp cell -- stringify for JSON, never guess a format.
            ts = row.get("Timestamp")
            row["Timestamp"] = str(ts) if ts is not None else None
            rows.append(row)
        rows.reverse()  # newest first, matching NoTradeLogView's own freshness-first convention
        return rows[:limit]
    except Exception as e:
        print(f"[ShadowLog] Failed to read today's log: {e}")
        return []
