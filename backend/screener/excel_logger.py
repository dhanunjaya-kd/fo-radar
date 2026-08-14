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

COLUMNS = [
    "Timestamp", "Symbol", "Action", "Grade", "Confidence",
    "Stock Price", "Change %", "Strike", "Entry (Premium)", "SL", "Target 1",
    "Target 2", "Target 3", "Qty", "R:R", "OI Confirmation", "Pattern",
    "PCR", "IV %", "RSI", "ADX", "Sector", "Option Symbol",
    "SL Hit At", "Target 1 Hit At", "Target 2 Hit At", "Target 3 Hit At",
    "Outcome", "Exited At",
]

_lock = threading.Lock()
# In-memory: {(symbol, action): {'row': N, 'exited_at': datetime|None}}
# 'exited_at' None means currently active. Resets when the date changes
# (new day = new file = fresh tracking).
_row_index = {}
# In-memory: {(symbol, action): {'row', 'option_symbol', 'sl', 't1','t2','t3',
# 'furthest_target': 0-3, 'sl_hit': bool}} -- only for positions still
# being watched for an outcome. A position stops being tracked once SL is
# hit (trade's over) but keeps being tracked after a target hit in case a
# FURTHER target also gets hit later (you'd have scaled out, but it's
# still useful to know the premium kept running).
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
            # Same fix as index_tracker.py: rewriting the header in place
            # would silently shift existing rows' data under the wrong
            # headers whenever a column is inserted anywhere but the very
            # end (tested and confirmed this corrupts data, not fixes
            # it). Archive the old file untouched, start fresh with the
            # current schema.
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
            # Row numbers in _row_index/_open_positions point at rows in
            # the OLD (now archived) file -- meaningless against this
            # fresh one. Clear them; any still-active signals get logged
            # again as "new" on the next cycle, in the new file.
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
    """
    Called by all 4 state-touching consumer functions (log_new_signal,
    mark_exited, sync_active_signals, check_outcomes) before their own
    early-exit checks -- replaces the old _reset_if_new_day().

    That old version wiped _row_index/_open_positions to empty on ANY
    process restart, not just a genuine day change -- because
    _current_date is a fresh None on every process start, the very
    first call after any restart looked identical to a real day
    rollover. Confirmed live (2026-08-10): a same-day restart silently
    orphaned several already-open positions from outcome-tracking, and
    duplicate-logged them on reappearance since get_locked_plan() also
    reads from the wiped _open_positions.

    This version rebuilds both dicts FROM today's existing Excel file
    the first time it's called in a process, instead of discarding
    what's already logged. Cheap after that first call (returns
    immediately once _initialized_today is set), so no behavior change
    for the common case of a server that just keeps running.
    """
    global _current_date, _row_index, _open_positions, _initialized_today
    today = datetime.now().strftime("%Y-%m-%d")

    if _current_date == today and _initialized_today:
        return  # already up to date for today in this process, nothing to do

    if _current_date != today:
        # Genuine day change (or the very first call ever) -- nothing
        # from a previous day carries over regardless of what's rebuilt
        # below.
        _row_index = {}
        _open_positions = {}
        _current_date = today

    _initialized_today = True

    path, _ = _today_path()
    if not os.path.exists(path):
        return  # nothing logged yet today -- empty dicts are already correct

    try:
        wb = load_workbook(path)
        ws = wb["Signals"]
        headers = [c.value for c in ws[1]]
        if headers != COLUMNS:
            return  # schema mismatch -- _get_workbook will archive+start fresh on next write; nothing usable to rebuild from
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

            # Same "stops being tracked" rule as check_outcomes(): once SL
            # is hit, or the furthest target (3) is reached, this position
            # is done -- don't resurrect it into _open_positions.
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
                _open_positions[key] = {
                    "row": row_num, "option_symbol": opt_symbol,
                    "entry": ws.cell(row=row_num, column=col["Entry (Premium)"]).value,
                    "strike": ws.cell(row=row_num, column=col["Strike"]).value,
                    "quantity": ws.cell(row=row_num, column=col["Qty"]).value,
                    "risk_reward": ws.cell(row=row_num, column=col["R:R"]).value,
                    "sl": sl, "t1": t1, "t2": t2, "t3": t3,
                    "sl_hit": False, "furthest_target": furthest_target,
                }
                rebuilt_open += 1

        print(f"[ExcelLog] Rebuilt state from {os.path.basename(path)}: "
              f"{len(_row_index)} row(s) indexed, {rebuilt_open} still open and being watched.")
    except Exception as e:
        print(f"[ExcelLog] Failed to rebuild state from {path}: {e}")


def _write_new_row(ws, signal):
    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        signal.get("symbol"), signal.get("action"), signal.get("grade"),
        signal.get("confidence"), signal.get("price"), signal.get("change_percent"),
        signal.get("strike"), signal.get("entry"), signal.get("sl"),
        signal.get("target1"), signal.get("target2"), signal.get("target3"),
        signal.get("quantity"), signal.get("risk_reward"),
        signal.get("oi_confirmation"), signal.get("pattern"),
        signal.get("pcr"), signal.get("iv"), signal.get("rsi"), signal.get("adx"),
        signal.get("sector"), signal.get("option_symbol"),
        "", "", "", "",  # SL/Target 1/2/3 Hit At -- blank until it happens
        "",  # Outcome
        "",  # Exited At -- blank until it drops out
    ]
    ws.append(row)
    row_num = ws.max_row

    key = (signal.get("symbol"), signal.get("action"))
    opt_sym = signal.get("option_symbol")
    if opt_sym and all(signal.get(f) is not None for f in ("sl", "target1", "target2", "target3")):
        _open_positions[key] = {
            "row": row_num, "option_symbol": opt_sym,
            "entry": signal.get("entry"), "strike": signal.get("strike"),
            "quantity": signal.get("quantity"), "risk_reward": signal.get("risk_reward"),
            "sl": signal["sl"], "t1": signal["target1"], "t2": signal["target2"], "t3": signal["target3"],
            "sl_hit": False, "furthest_target": 0,
        }
    return row_num


def get_locked_plan(symbol, action):
    """
    Returns the FROZEN trade plan (entry/strike/sl/target1-3/quantity/
    risk_reward/option_symbol) for a signal already being tracked today
    (still active or within the reactivation cooldown), or None if this
    would be a genuinely new signal that needs fresh numbers computed.

    This is what _build_all() checks before recomputing entry/SL/target
    from scratch every cycle -- without it, a stock sitting in the live
    signal list for an hour would show a DIFFERENT entry/SL/target every
    90 seconds as price/ATR/premium drift, which is useless to actually
    trade off of. A trade plan has to hold still once it's been shown to
    you; only a genuinely new signal (or one that already resolved and
    later re-qualifies) should get fresh numbers.
    """
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
        }


def log_new_signal(signal):
    """
    Called for a signal that's active this cycle but wasn't in the
    previous cycle's active set. Three cases:
      1. Never seen today -> log a fresh row.
      2. Seen today, exited more than COOLDOWN_MINUTES ago -> log a
         fresh row (this counts as a genuinely new setup).
      3. Seen today, exited within COOLDOWN_MINUTES -> reactivate the
         existing row (clear "Exited At") instead of creating a
         duplicate -- this is what stops a threshold-hovering stock from
         spamming a dozen near-identical rows a few minutes apart.

    Returns True only for case 1/2 (a genuinely fresh row was created).
    Reactivations, already-active no-ops, and write failures all return
    False. Callers use this to know when a signal is worth alerting on
    elsewhere (e.g. Telegram) without re-implementing the same
    new-vs-reactivation distinction -- a reactivated threshold-hoverer
    shouldn't re-alert any more than it should re-log.
    """
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
            return False  # already active and logged, nothing to do

        try:
            wb = _get_workbook(path)
            ws = wb["Signals"]

            if existing and existing["exited_at"] is not None:
                gap_minutes = (datetime.now() - existing["exited_at"]).total_seconds() / 60
                if gap_minutes < COOLDOWN_MINUTES:
                    # Reactivate the same row instead of duplicating.
                    exited_col = COLUMNS.index("Exited At") + 1
                    ws.cell(row=existing["row"], column=exited_col).value = ""
                    wb.save(path)
                    existing["exited_at"] = None
                    return False

            # Fresh row -- either never seen today, or the gap since it
            # last exited was long enough to count as a new setup.
            row_num = _write_new_row(ws, signal)
            wb.save(path)
            _row_index[key] = {"row": row_num, "exited_at": None}
            return True
        except Exception as e:
            print(f"[ExcelLog] Failed to log {key}: {e}")
            return False


def mark_exited(symbol, action):
    """Called when a previously-active signal drops out of the current
    cycle -- fills in the Exited At cell on its existing row (row stays
    tracked in memory so a quick reappearance within the cooldown window
    reactivates it instead of creating a new one)."""
    if not OPENPYXL_AVAILABLE:
        return
    key = (symbol, action)

    with _lock:
        path, today = _today_path()
        _ensure_fresh()
        existing = _row_index.get(key)
        if existing is None or existing["exited_at"] is not None:
            return  # wasn't logged today, or already marked exited

        try:
            wb = _get_workbook(path)
            ws = wb["Signals"]
            exited_col = COLUMNS.index("Exited At") + 1
            now = datetime.now()
            ws.cell(row=existing["row"], column=exited_col).value = now.strftime("%Y-%m-%d %H:%M:%S")
            wb.save(path)
            existing["exited_at"] = now
        except Exception as e:
            print(f"[ExcelLog] Failed to mark exit for {key}: {e}")


def sync_active_signals(current_signals):
    """
    Call once per scan cycle with the full current signal list. Figures
    out what's newly appeared (logs/reactivates it) and what dropped out
    since last cycle (marks it exited) -- this is the only function
    _build_all() needs to call.

    Returns the list of signal dicts that were genuinely new this cycle
    (fresh rows only, not reactivations) -- callers use this to trigger
    something like a Telegram alert without duplicating the new-vs-
    reactivation logic already handled here.
    """
    if not OPENPYXL_AVAILABLE:
        return []
    current_keys = {(s.get("symbol"), s.get("action")) for s in current_signals if s.get("symbol")}

    with _lock:
        path, today = _today_path()
        _ensure_fresh()
        previously_active = {k for k, v in _row_index.items() if v["exited_at"] is None}

    # New signals this cycle (not currently marked active in memory)
    newly_logged = []
    for s in current_signals:
        key = (s.get("symbol"), s.get("action"))
        if key[0] and key not in previously_active:
            if log_new_signal(s):
                newly_logged.append(s)

    # Signals that dropped out since last cycle
    for key in previously_active - current_keys:
        mark_exited(key[0], key[1])

    return newly_logged


def check_outcomes(get_quotes_fn):
    """
    Call once per scan cycle. Batch-fetches live premiums for every
    currently-open (unresolved) position's exact option contract, and
    checks whether SL or any target has been crossed since the last
    check. The moment one is, it's recorded with a timestamp in that
    row -- this is what actually answers "did this signal work" instead
    of just "did it appear".

    get_quotes_fn: pass screener.fyers_client.get_quotes (batches up to
    50 symbols per call). Injected as a parameter rather than imported
    directly so this stays testable with a fake quotes function and
    doesn't create an import-time dependency on the Fyers client.

    Once SL is hit (trade's over) OR Target 3 (the furthest) is reached,
    a position stops being tracked. Between those, tracking continues
    after a lower target hits in case a further one also gets hit later.
    """
    if not OPENPYXL_AVAILABLE:
        return
    with _lock:
        path, today = _today_path()
        _ensure_fresh()
        open_now = dict(_open_positions)  # snapshot; network call happens outside the lock

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
                    del _open_positions[key]

            if changed:
                wb.save(path)
        except Exception as e:
            print(f"[ExcelLog] Failed to update outcomes: {e}")


def get_today_log_path():
    """Path to today's log file, for the download endpoint. Returns None
    if it doesn't exist yet (no signals logged today)."""
    path, _ = _today_path()
    return path if os.path.exists(path) else None


def list_available_dates():
    """Every date that has a signals log, newest first. Checks both the
    new nested layout (signal_logs/YYYY-MM-DD/signals_YYYY-MM-DD.xlsx)
    and the old flat one (signal_logs/signals_YYYY-MM-DD.xlsx, from
    before the folder reorg), so dates from before that change still
    show up alongside newer ones."""
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
    """Path to a specific past day's log file (YYYY-MM-DD), for the
    export-by-date endpoint. Checks the nested layout first, falls back
    to the old flat one. Returns None if that date has no log."""
    nested = os.path.join(LOG_DIR, date_str, f"signals_{date_str}.xlsx")
    if os.path.exists(nested):
        return nested
    flat = os.path.join(LOG_DIR, f"signals_{date_str}.xlsx")
    if os.path.exists(flat):
        return flat
    return None
