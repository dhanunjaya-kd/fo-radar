"""
screener/excel_logger.py

Auto-logs every signal to an Excel file the moment it first appears in a
scan cycle, and marks it "EXITED" the moment it drops out of the active
list -- so you get a running record of the whole day's signals (entry
time, entry/SL/targets, and how long each one stayed active) instead of
only ever seeing the current snapshot.

Also tracks OUTCOME: once a signal is logged, its exact option contract
(strike + CE/PE) is polled every scan cycle and checked against the
SL/Target 1/2/3 levels recorded at entry. The moment the live premium
crosses one of those levels, it's recorded -- "SL Hit At <time>" or
"Target N Hit At <time>" (whichever is furthest reached; hitting Target 2
supersedes an earlier Target 1 hit). This is what actually answers "did
this signal work" at the end of the day, not just "did it appear".

One file per trading day: signal_logs/signals_YYYY-MM-DD.xlsx, created
automatically on first use. Safe to call repeatedly -- writes are
append-only plus one-cell updates (marking exit time / outcome), never a
full rewrite of existing rows.

COOLDOWN / REACTIVATION: a stock whose score is hovering right at the
qualifying threshold can cross back and forth every single scan cycle --
each cross used to log a brand new row, which is why the same symbol
(e.g. one sitting at exactly the score cutoff all day) could end up with
a dozen near-identical rows a few minutes apart. If a signal exits and
then reappears (same symbol + same direction) within COOLDOWN_MINUTES,
it's treated as the SAME signal continuing -- the existing row's
"Exited At" cell is cleared instead of a new row being created. Only a
gap longer than the cooldown counts as a genuinely new setup.
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
COOLDOWN_MINUTES = 30

def compute_signal_id(date_str, symbol, action, option_symbol):
    """
    Sep 12 2026: deterministic signal_id -- NOT a random UUID generated
    at write time (which would need its own restart-safe storage and
    could drift if regenerated). Built entirely from values that are
    already stable and already persisted per-row: the calendar date
    this signal first appeared, symbol, action, and its frozen option
    contract. Recomputing this from the SAME row's data after a
    restart yields the IDENTICAL string every time -- nothing to lose,
    nothing to resynchronize, by construction rather than by tracking.

    option_symbol is required (not optional) -- a signal with no
    resolved option contract yet has no stable identity to hash, and
    this project's own rule elsewhere is to skip rather than fabricate
    an identifier for a state that isn't real yet.
    """
    if not option_symbol:
        return None
    return f"{date_str}|{symbol}|{action}|{option_symbol}"


def compute_setup_id(structure_data=None):
    """
    Sep 12 2026: setup_id architecture -- deliberately separate from
    signal_id (which identifies THIS specific signal instance;
    setup_id would identify the STRUCTURAL SETUP TYPE it represents,
    e.g. "breakout retest" vs "range reversal"). No real structure/BOS
    classification exists anywhere in this codebase's live data yet.

    structure_data: reserved for when real structure/BOS data becomes
    available (e.g. {'pattern': 'breakout', 'bos_level': ..., 'tf':
    ...}) -- once populated, this function computes a real deterministic
    id from it (same principle as compute_signal_id: a formula over
    stable real inputs, not a random value). Ready to accept that
    without another rewrite of any caller.

    Until then: returns (None, "UNAVAILABLE_NO_STRUCTURE_DATA") --
    never a guessed or fabricated id.
    """
    if not structure_data:
        return None, "UNAVAILABLE_NO_STRUCTURE_DATA"
    # Real path, unused until a real caller supplies structure_data.
    parts = "|".join(f"{k}={structure_data[k]}" for k in sorted(structure_data))
    return f"setup:{parts}", "AVAILABLE"


# Sep 12 2026: real, evidence-based re-entry classification -- the
# authoritative one. views.py's own classifier explicitly defers
# EXACT_DUPLICATE/SAME_SETUP_RETRIGGER to this file, since only this
# file has the persisted state (existing row + its real exit/cooldown
# timing) needed to actually prove either. GENUINE_REENTRY requires
# real proof the previous relevant trade RESOLVED (a real "Target N
# Hit"/"SL Hit" outcome, not blank or "Expired") before this candidate
# -- never inferred just because the symbol appeared before.
def classify_signal_event(symbol, action, option_symbol):
    """
    Read-only classifier -- makes no writes, safe to call independently
    of log_new_signal() (which still owns the actual write path and its
    own cooldown/reactivation logic; this shares the same underlying
    state rather than duplicating or racing it).

    Returns one of:
      'ACTIVE' -- get_locked_plan() has a plan for (symbol, action)
        right now; this isn't a new event, the same signal continues.
      'EXACT_DUPLICATE' -- a row already exists today for (symbol,
        action) with the IDENTICAL option_symbol, still active
        (exited_at is None) -- would be a true duplicate write of the
        same live contract.
      'SAME_SETUP_RETRIGGER' -- a row exists today that exited less
        than COOLDOWN_MINUTES ago -- log_new_signal() would reactivate
        it rather than write a new row.
      'GENUINE_REENTRY' -- real persisted history (from
        get_symbol_recurrence_info) shows a prior occurrence for this
        symbol whose recorded Outcome is a REAL resolved value ("Target
        N Hit" or "SL Hit") -- proof the earlier trade concluded before
        this candidate. Never returned from an unresolved or ambiguous
        prior state.
      'NEW_SETUP' -- no prior occurrence anywhere (today's state or
        past persisted logs).
      'UNKNOWN' -- a prior occurrence exists, but its resolution isn't
        provably a real win/loss (blank Outcome, or "Expired (no
        SL/Target hit)") -- insufficient evidence for GENUINE_REENTRY,
        and calling it NEW_SETUP would contradict its own history.
    """
    with _lock:
        _ensure_fresh()
        existing = _row_index.get((symbol, action))
        open_pos = _open_positions.get((symbol, action))

    if open_pos is not None:
        return 'ACTIVE'

    if existing is not None:
        if existing["exited_at"] is None:
            # Row still marked active in today's index but no
            # _open_positions entry -- e.g. an option_symbol never
            # resolved to a trackable position. Treat conservatively:
            # a live row exists, this isn't provably a fresh setup.
            return 'EXACT_DUPLICATE' if option_symbol == existing.get("option_symbol") else 'UNKNOWN'
        gap_minutes = (datetime.now() - existing["exited_at"]).total_seconds() / 60
        if gap_minutes < COOLDOWN_MINUTES:
            return 'SAME_SETUP_RETRIGGER'

    real_history = get_symbol_recurrence_info(symbol)
    if real_history is None:
        return 'NEW_SETUP'

    prev_result = real_history.get("previous_result")
    # Sep 12 2026: exact match against the real strings check_outcomes()
    # writes for a genuine resolution -- NOT a substring check. A prior
    # bug here used "Target" in str(prev_result), which incorrectly
    # matched "Expired (no SL/Target hit)" (mark_exited()'s own string
    # for an UNRESOLVED position) as if it were a real win, since that
    # string happens to contain the word "Target" while meaning the
    # opposite. Caught by testing scenario E (unresolved prior signal)
    # before this shipped, not after.
    _REAL_RESOLVED_OUTCOMES = {"Target 1 Hit", "Target 2 Hit", "Target 3 Hit", "SL Hit"}
    if prev_result in _REAL_RESOLVED_OUTCOMES:
        return 'GENUINE_REENTRY'
    return 'UNKNOWN'


COLUMNS = [
    "Timestamp", "Symbol", "Action", "Grade", "Confidence",
    "Stock Price", "Change %", "Strike", "Entry (Premium)", "SL", "Target 1",
    "Target 2", "Target 3", "Qty", "R:R", "OI Confirmation", "Pattern",
    "PCR", "IV %", "RSI", "ADX", "Sector", "Option Symbol",
    "SL Hit At", "Target 1 Hit At", "Target 2 Hit At", "Target 3 Hit At",
    "Outcome", "Exited At",
    "Signal Logic Version", "Base Score (Pre-OI)", "India VIX At Signal", "Stock vs Sector %",
    "Stock vs Index %", "Expiry Date", "MFE Premium", "MAE Premium",
    # Sep 12 2026: SNIPER V2 -- deterministic, restart-safe identity.
    # See compute_signal_id()'s own docstring above for why this is a
    # formula over stable fields already in this row, not a randomly
    # generated value needing its own persistence.
    "Signal ID",
    # Sep 13 2026: raw values needed to test the SNIPER STOCKS filter
    # candidates (today's price action, EMA20/50 trend confirmation,
    # MACD magnitude, volume ratio) discussed but explicitly NOT
    # implemented yet -- none of these were ever persisted anywhere in
    # this project before now, which is exactly why those candidates
    # couldn't be tested against real history. All five are already
    # computed every cycle (tech['macd']/['vwap']/['ema20']/['ema50']/
    # ['volume_avg']) -- this only starts WRITING them, it does not
    # change what qualifies a signal or how it's scored. "VWAP
    # Distance %" and "Volume Ratio" are logged as ratios/percentages
    # rather than raw VWAP/volume, since that's the form the actual
    # candidate experiments need (e.g. "was volume >=1.5x average",
    # "was price >0.5% above VWAP") -- not a new computation, just a
    # more directly usable persisted form of values already on hand.
    "MACD", "VWAP Distance %", "Volume Ratio", "EMA20", "EMA50",
]

_lock = threading.Lock()
_row_index = {}
_open_positions = {}
_current_date = None
_initialized_today = False


def _today_path():
    today = datetime.now().strftime("%Y-%m-%d")
    day_dir = os.path.join(LOG_DIR, today)
    os.makedirs(day_dir, exist_ok=True)
    return os.path.join(day_dir, f"signals_{today}.xlsx"), today


def _get_workbook(path):
    global _row_index, _open_positions
    if os.path.exists(path):
        wb = load_workbook(path)
        ws = wb["Signals"]
        existing_header = [c.value for c in ws[1]]
        if existing_header != COLUMNS:
            archive_path = path.replace(".xlsx", "_pre-update.xlsx")
            if not os.path.exists(archive_path):
                wb.save(archive_path)
                print(f"[ExcelLog] Column layout changed -- archived old data to {os.path.basename(archive_path)}, starting fresh for today")
            wb = Workbook()
            ws = wb.active
            ws.title = "Signals"
            ws.append(COLUMNS)
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
            _row_index = {}
            _open_positions = {}
        return wb
    wb = Workbook()
    ws = wb.active
    ws.title = "Signals"
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
    return wb


def _ensure_fresh():
    global _current_date, _row_index, _open_positions, _initialized_today
    today = datetime.now().strftime("%Y-%m-%d")

    if _current_date == today and _initialized_today:
        return

    if _current_date != today:
        _row_index = {}
        _open_positions = {}
        _current_date = today

    _initialized_today = True

    path, _ = _today_path()
    if not os.path.exists(path):
        return

    try:
        wb = load_workbook(path)
        ws = wb["Signals"]
        headers = [c.value for c in ws[1]]
        if headers != COLUMNS:
            return
        col = {name: i + 1 for i, name in enumerate(headers)}

        rebuilt_open = 0
        for row_num in range(2, ws.max_row + 1):
            symbol = ws.cell(row=row_num, column=col["Symbol"]).value
            action = ws.cell(row=row_num, column=col["Action"]).value
            if not symbol or not action:
                continue
            key = (symbol, action)

            exited_raw = ws.cell(row=row_num, column=col["Exited At"]).value
            exited_at = None
            if exited_raw:
                try:
                    exited_at = datetime.strptime(str(exited_raw), "%Y-%m-%d %H:%M:%S")
                except Exception:
                    exited_at = None
            _row_index[key] = {"row": row_num, "exited_at": exited_at}

            sl_hit_already = bool(ws.cell(row=row_num, column=col["SL Hit At"]).value)
            furthest_target = 0
            for n in (3, 2, 1):
                if ws.cell(row=row_num, column=col[f"Target {n} Hit At"]).value:
                    furthest_target = n
                    break
            if sl_hit_already or furthest_target >= 3:
                continue

            opt_symbol = ws.cell(row=row_num, column=col["Option Symbol"]).value
            sl = ws.cell(row=row_num, column=col["SL"]).value
            t1 = ws.cell(row=row_num, column=col["Target 1"]).value
            t2 = ws.cell(row=row_num, column=col["Target 2"]).value
            t3 = ws.cell(row=row_num, column=col["Target 3"]).value
            if opt_symbol and None not in (sl, t1, t2, t3):
                created_raw = ws.cell(row=row_num, column=col["Timestamp"]).value
                created_at = None
                if created_raw:
                    try:
                        created_at = datetime.strptime(str(created_raw), "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        created_at = None
                # Sep 12 2026: prefer the stored "Signal ID" cell, but
                # fall back to recomputing it deterministically (same
                # formula compute_signal_id() always uses) for any row
                # written before this column existed -- never leaves
                # signal_id blank when it's derivable from data already
                # on this row.
                stored_sig_id = ws.cell(row=row_num, column=col["Signal ID"]).value if "Signal ID" in col else None
                sig_id = stored_sig_id or compute_signal_id(today, symbol, action, opt_symbol)
                _open_positions[key] = {
                    "row": row_num, "option_symbol": opt_symbol, "signal_id": sig_id,
                    "entry": ws.cell(row=row_num, column=col["Entry (Premium)"]).value,
                    "strike": ws.cell(row=row_num, column=col["Strike"]).value,
                    "quantity": ws.cell(row=row_num, column=col["Qty"]).value,
                    "risk_reward": ws.cell(row=row_num, column=col["R:R"]).value,
                    "sl": sl, "t1": t1, "t2": t2, "t3": t3,
                    "sl_hit": False, "furthest_target": furthest_target,
                    "created_at": created_at,
                    "max_premium_seen": ws.cell(row=row_num, column=col["Entry (Premium)"]).value,
                    "min_premium_seen": ws.cell(row=row_num, column=col["Entry (Premium)"]).value,
                }
                rebuilt_open += 1

        print(f"[ExcelLog] Rebuilt state from {os.path.basename(path)}: "
              f"{len(_row_index)} row(s) indexed, {rebuilt_open} still open and being watched.")
    except Exception as e:
        print(f"[ExcelLog] Failed to rebuild state from {path}: {e}")


def _write_new_row(ws, signal):
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    sig_id = compute_signal_id(today_str, signal.get("symbol"), signal.get("action"), signal.get("option_symbol"))
    row = [
        now.strftime("%Y-%m-%d %H:%M:%S"),
        signal.get("symbol"), signal.get("action"), signal.get("grade"),
        signal.get("confidence"), signal.get("price"), signal.get("change_percent"),
        signal.get("strike"), signal.get("entry"), signal.get("sl"),
        signal.get("target1"), signal.get("target2"), signal.get("target3"),
        signal.get("quantity"), signal.get("risk_reward"),
        signal.get("oi_confirmation"), signal.get("pattern"),
        signal.get("pcr"), signal.get("iv"), signal.get("rsi"), signal.get("adx"),
        signal.get("sector"), signal.get("option_symbol"),
        "", "", "", "",
        "",
        "",
        signal.get("signal_logic_version"), signal.get("technical_score"),
        signal.get("india_vix_at_signal"), signal.get("stock_vs_sector_pct"),
        signal.get("stock_vs_index_pct"), signal.get("expiry_date"),
        "", "",
        sig_id,
        signal.get("macd"), signal.get("vwap_distance_pct"), signal.get("volume_ratio"),
        signal.get("ema20"), signal.get("ema50"),
    ]

    key = (signal.get("symbol"), signal.get("action"))

    stale = _open_positions.get(key)
    if stale is not None and not stale.get("sl_hit") and stale.get("furthest_target", 0) < 3:
        try:
            stale_outcome_col = COLUMNS.index("Outcome") + 1
            if not ws.cell(row=stale["row"], column=stale_outcome_col).value:
                ws.cell(row=stale["row"], column=stale_outcome_col).value = "Expired (no SL/Target hit)"
            mfe_col = COLUMNS.index("MFE Premium") + 1
            mae_col = COLUMNS.index("MAE Premium") + 1
            ws.cell(row=stale["row"], column=mfe_col).value = stale.get("max_premium_seen")
            ws.cell(row=stale["row"], column=mae_col).value = stale.get("min_premium_seen")
        except Exception as e:
            print(f"[ExcelLog] Failed to finalize stale position for {key} before re-logging: {e}")

    ws.append(row)
    row_num = ws.max_row

    opt_sym = signal.get("option_symbol")
    if opt_sym and all(signal.get(f) is not None for f in ("sl", "target1", "target2", "target3")):
        _open_positions[key] = {
            "row": row_num, "option_symbol": opt_sym, "signal_id": sig_id,
            "entry": signal.get("entry"), "strike": signal.get("strike"),
            "quantity": signal.get("quantity"), "risk_reward": signal.get("risk_reward"),
            "sl": signal["sl"], "t1": signal["target1"], "t2": signal["target2"], "t3": signal["target3"],
            "sl_hit": False, "furthest_target": 0,
            "created_at": now,
            "max_premium_seen": signal.get("entry"), "min_premium_seen": signal.get("entry"),
        }
    return row_num


def get_locked_plan(symbol, action):
    key = (symbol, action)
    with _lock:
        pos = _open_positions.get(key)
        if pos is None:
            return None
        return {
            "entry": pos.get("entry"), "strike": pos.get("strike"),
            "sl": pos["sl"], "target1": pos["t1"], "target2": pos["t2"], "target3": pos["t3"],
            "quantity": pos.get("quantity"), "risk_reward": pos.get("risk_reward"),
            "option_symbol": pos.get("option_symbol"),
            "created_at": pos.get("created_at"),
            "signal_id": pos.get("signal_id"),
        }


def log_new_signal(signal):
    if not OPENPYXL_AVAILABLE:
        return False
    key = (signal.get("symbol"), signal.get("action"))
    if not key[0]:
        return False

    with _lock:
        path, today = _today_path()
        _ensure_fresh()

        existing = _row_index.get(key)
        if existing and existing["exited_at"] is None:
            return False

        try:
            wb = _get_workbook(path)
            ws = wb["Signals"]

            if existing and existing["exited_at"] is not None:
                gap_minutes = (datetime.now() - existing["exited_at"]).total_seconds() / 60
                if gap_minutes < COOLDOWN_MINUTES:
                    exited_col = COLUMNS.index("Exited At") + 1
                    ws.cell(row=existing["row"], column=exited_col).value = ""
                    wb.save(path)
                    existing["exited_at"] = None
                    return False

            row_num = _write_new_row(ws, signal)
            wb.save(path)
            _row_index[key] = {"row": row_num, "exited_at": None}
            return True
        except Exception as e:
            print(f"[ExcelLog] Failed to log {key}: {e}")
            return False


def mark_exited(symbol, action):
    if not OPENPYXL_AVAILABLE:
        return
    key = (symbol, action)

    with _lock:
        path, today = _today_path()
        _ensure_fresh()
        existing = _row_index.get(key)
        if existing is None or existing["exited_at"] is not None:
            return

        try:
            wb = _get_workbook(path)
            ws = wb["Signals"]
            exited_col = COLUMNS.index("Exited At") + 1
            outcome_col = COLUMNS.index("Outcome") + 1
            now = datetime.now()
            ws.cell(row=existing["row"], column=exited_col).value = now.strftime("%Y-%m-%d %H:%M:%S")
            existing_outcome = ws.cell(row=existing["row"], column=outcome_col).value
            if not existing_outcome:
                ws.cell(row=existing["row"], column=outcome_col).value = "Expired (no SL/Target hit)"
            pos = _open_positions.get(key)
            if pos is not None:
                mfe_col = COLUMNS.index("MFE Premium") + 1
                mae_col = COLUMNS.index("MAE Premium") + 1
                ws.cell(row=existing["row"], column=mfe_col).value = pos.get("max_premium_seen")
                ws.cell(row=existing["row"], column=mae_col).value = pos.get("min_premium_seen")
            wb.save(path)
            existing["exited_at"] = now
        except Exception as e:
            print(f"[ExcelLog] Failed to mark exit for {key}: {e}")


def sync_active_signals(current_signals):
    if not OPENPYXL_AVAILABLE:
        return []
    current_keys = {(s.get("symbol"), s.get("action")) for s in current_signals if s.get("symbol")}

    with _lock:
        path, today = _today_path()
        _ensure_fresh()
        previously_active = {k for k, v in _row_index.items() if v["exited_at"] is None}

    newly_logged = []
    for s in current_signals:
        key = (s.get("symbol"), s.get("action"))
        if key[0] and key not in previously_active:
            if log_new_signal(s):
                newly_logged.append(s)

    for key in previously_active - current_keys:
        mark_exited(key[0], key[1])

    return newly_logged


def check_outcomes(get_quotes_fn):
    if not OPENPYXL_AVAILABLE:
        return
    with _lock:
        path, today = _today_path()
        _ensure_fresh()
        open_now = dict(_open_positions)

    symbols_to_check = {v["option_symbol"]: k for k, v in open_now.items() if v.get("option_symbol")}
    if not symbols_to_check:
        return

    try:
        resp = get_quotes_fn(list(symbols_to_check.keys()))
    except Exception as e:
        print(f"[ExcelLog] Outcome check quotes failed: {e}")
        return
    if not resp or resp.get("s") != "ok":
        return

    ltp_by_symbol = {}
    for item in resp.get("d", []):
        if item.get("s") == "ok":
            v = item.get("v", {}) or {}
            if v.get("lp") is not None:
                ltp_by_symbol[item.get("n")] = v["lp"]

    if not ltp_by_symbol:
        return

    with _lock:
        try:
            wb = _get_workbook(path)
            ws = wb["Signals"]
            changed = False
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            for opt_symbol, key in symbols_to_check.items():
                pos = _open_positions.get(key)
                if pos is None:
                    continue
                ltp = ltp_by_symbol.get(opt_symbol)
                if ltp is None:
                    continue

                pos["max_premium_seen"] = max(pos.get("max_premium_seen", pos["entry"]), ltp)
                pos["min_premium_seen"] = min(pos.get("min_premium_seen", pos["entry"]), ltp)

                if not pos["sl_hit"] and ltp <= pos["sl"]:
                    pos["sl_hit"] = True
                    ws.cell(row=pos["row"], column=COLUMNS.index("SL Hit At") + 1).value = now_str
                    ws.cell(row=pos["row"], column=COLUMNS.index("Outcome") + 1).value = "SL Hit"
                    changed = True

                for n in (3, 2, 1):
                    if pos["furthest_target"] >= n:
                        break
                    if ltp >= pos[f"t{n}"]:
                        pos["furthest_target"] = n
                        ws.cell(row=pos["row"], column=COLUMNS.index(f"Target {n} Hit At") + 1).value = now_str
                        if not pos["sl_hit"]:
                            ws.cell(row=pos["row"], column=COLUMNS.index("Outcome") + 1).value = f"Target {n} Hit"
                        changed = True
                        break

                if pos["sl_hit"] or pos["furthest_target"] >= 3:
                    ws.cell(row=pos["row"], column=COLUMNS.index("MFE Premium") + 1).value = pos.get("max_premium_seen")
                    ws.cell(row=pos["row"], column=COLUMNS.index("MAE Premium") + 1).value = pos.get("min_premium_seen")
                    changed = True
                    del _open_positions[key]

            if changed:
                wb.save(path)
        except Exception as e:
            print(f"[ExcelLog] Failed to update outcomes: {e}")


def get_today_log_path():
    path, _ = _today_path()
    return path if os.path.exists(path) else None


def list_available_dates():
    import glob
    import re
    dates = set()
    date_pattern = re.compile(r'signals_(\d{4}-\d{2}-\d{2})\.xlsx$')

    for path in glob.glob(os.path.join(LOG_DIR, "signals_*.xlsx")):
        m = date_pattern.search(os.path.basename(path))
        if m:
            dates.add(m.group(1))
    for path in glob.glob(os.path.join(LOG_DIR, "*", "signals_*.xlsx")):
        m = date_pattern.search(os.path.basename(path))
        if m:
            dates.add(m.group(1))

    return sorted(dates, reverse=True)


def get_log_path_for_date(date_str):
    nested = os.path.join(LOG_DIR, date_str, f"signals_{date_str}.xlsx")
    if os.path.exists(nested):
        return nested
    flat = os.path.join(LOG_DIR, f"signals_{date_str}.xlsx")
    if os.path.exists(flat):
        return flat
    return None


# ---------------------------------------------------------------------------
# Sep 12 2026: SNIPER V2 -- real cross-date symbol recurrence, built from
# actual past daily logs. This is the durable version of what views.py's
# own in-memory _symbol_recurrence_history (added earlier the same day)
# could not provide on its own -- that tracker only sees symbols since
# the current server process started, with no visibility into anything
# from before a restart. This reads the real, persisted Excel files
# instead, so a genuinely fresh process still knows a symbol's real
# history from yesterday or last week.
#
# Cached once per day, not once per symbol-check -- 200+ stocks get
# evaluated every ~90s scan cycle, and re-scanning every past log file
# for every single one of them would be real, unnecessary disk I/O.
_recurrence_cache = {}  # {symbol: [{'date':..., 'action':..., 'outcome':...}, ...]}
_recurrence_cache_built_date = None
_recurrence_cache_lock = threading.Lock()


def _build_recurrence_cache(lookback_days=60):
    """Scans up to `lookback_days` of past daily logs (STRICTLY BEFORE
    today -- today's own in-progress signals are what _row_index/
    _open_positions already handle live; mixing the two would double-
    count a signal that's still active today) and indexes every row's
    real recorded Outcome by symbol. Built once per day; cheap no-op on
    every subsequent call the same day."""
    global _recurrence_cache, _recurrence_cache_built_date
    today = datetime.now().strftime("%Y-%m-%d")
    with _recurrence_cache_lock:
        if _recurrence_cache_built_date == today:
            return

        cache = {}
        dates = [d for d in list_available_dates() if d < today][:lookback_days]
        for date_str in dates:
            path = get_log_path_for_date(date_str)
            if not path:
                continue
            try:
                wb = load_workbook(path, read_only=True, data_only=True)
                ws = wb["Signals"]
                rows_iter = ws.iter_rows(values_only=True)
                headers = next(rows_iter, None)
                if not headers or "Symbol" not in headers or "Outcome" not in headers:
                    continue
                col = {name: i for i, name in enumerate(headers)}
                for row in rows_iter:
                    symbol = row[col["Symbol"]] if col["Symbol"] < len(row) else None
                    if not symbol:
                        continue
                    cache.setdefault(symbol, []).append({
                        "date": date_str,
                        "action": row[col["Action"]] if col.get("Action", -1) < len(row) else None,
                        "outcome": row[col["Outcome"]] if col.get("Outcome", -1) < len(row) else None,
                        "option_symbol": row[col["Option Symbol"]] if col.get("Option Symbol", -1) < len(row) else None,
                        "signal_id": row[col["Signal ID"]] if "Signal ID" in col and col["Signal ID"] < len(row) else None,
                    })
                wb.close()
            except Exception as e:
                print(f"[ExcelLog] Recurrence cache: skipped {date_str} ({e})")
                continue

        _recurrence_cache = cache
        _recurrence_cache_built_date = today
        print(f"[ExcelLog] Recurrence cache built: {len(cache)} symbol(s) with real history across {len(dates)} prior day(s)")


def get_symbol_recurrence_info(symbol):
    """
    Real cross-date recurrence for one symbol, from actual past logs --
    never fabricated, never session-memory-only. Returns None if this
    symbol has no prior occurrence in the cached lookback window (a
    genuinely new/rare symbol), otherwise a dict with its real history.

    Resolved outcomes only ("Target N Hit" / "SL Hit") count toward
    prior_wins/prior_losses -- "Expired (no SL/Target hit)" and blank
    outcomes are counted in prior_signal_count but not classified as a
    win or loss, since neither genuinely happened. prior_win_rate is
    None (not 0 or a guess) when there aren't any resolved priors to
    compute a rate from.

    Sep 12 2026: added previous_direction/previous_result/
    previous_signal_id (the single most recent real occurrence's own
    values) and days_since_last_signal (real calendar-day gap, computed
    from last_seen_date to today -- never guessed when there's no prior
    occurrence, since the field simply isn't returned at all in that
    case, same "return None, not a fabricated 0" rule as everywhere
    else in this function).
    """
    _build_recurrence_cache()
    occurrences = _recurrence_cache.get(symbol)
    if not occurrences:
        return None

    # Sep 12 2026: exact match, not substring -- "Target" in str(...)
    # incorrectly counted "Expired (no SL/Target hit)" as a win (that
    # string contains the word "Target" while meaning the opposite:
    # no target was ever hit). This bug affected every symbol's
    # prior_wins/prior_win_rate, not just the classifier above -- found
    # and fixed together, same root cause.
    _REAL_WIN_OUTCOMES = {"Target 1 Hit", "Target 2 Hit", "Target 3 Hit"}
    wins = sum(1 for o in occurrences if o["outcome"] in _REAL_WIN_OUTCOMES)
    losses = sum(1 for o in occurrences if o["outcome"] == "SL Hit")
    resolved = wins + losses
    dates = [o["date"] for o in occurrences]
    last_seen = max(dates)
    # Most recent occurrence by date -- if multiple occurrences share
    # the same last_seen date (shouldn't happen given the daily-lock
    # discussion, but real data should never assume it can't), takes
    # the last one encountered for that date rather than guessing an
    # order that isn't actually recorded.
    most_recent = [o for o in occurrences if o["date"] == last_seen][-1]
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        days_since = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(last_seen, "%Y-%m-%d")).days
    except Exception:
        days_since = None

    return {
        "first_seen_date": min(dates),
        "last_seen_date": last_seen,
        "prior_signal_count": len(occurrences),
        "prior_wins": wins,
        "prior_losses": losses,
        "prior_win_rate": round(wins / resolved * 100, 1) if resolved > 0 else None,
        "days_since_last_signal": days_since,
        "previous_direction": most_recent.get("action"),
        "previous_result": most_recent.get("outcome"),
        "previous_signal_id": most_recent.get("signal_id") or compute_signal_id(
            most_recent["date"], symbol, most_recent.get("action"), most_recent.get("option_symbol"),
        ),
    }
