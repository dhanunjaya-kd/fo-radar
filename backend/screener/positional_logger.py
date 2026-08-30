"""
screener/positional_logger.py

Live positional tracking for the stock universe -- the SAME signals
that already fire intraday (views.py's _build_all()), logged a SECOND
time with WIDER SL/Target sized for a multi-day hold, and tracked
across as many real days as it takes to resolve. Deliberately built
alongside excel_logger.py, not as a modification of it -- that
module's whole design (in-memory state that resets "when the date
changes") is correct for same-day tracking and wrong for this.

SL/Target SIZING -- NOT premium +/- ATR*multiplier directly. The real
intraday engine never moves premium by a flat ATR amount: it moves
the STOCK price by an ATR-sized amount, then translates THAT into a
premium move via the option's own delta (SL weighted 1.4x, since
theta/gamma work against an adverse move too) -- see views.py's
_build_all(), the exact block computing entry/sl/t1/t2/t3 for the
option. This module reuses that identical translation, just with
WIDER stock-side multipliers: SL 1.5x ATR, Targets 2x/3x/4x ATR
instead of the intraday 0.4x/0.5x/0.8x/1.2x. Those specific numbers
aren't a new guess -- they're the exact multi-day-sized multipliers
this codebase's own stock engine used BEFORE being deliberately
replaced with the current intraday sizing (that file's own comment:
"sized for a multi-day swing, not an intraday option trade").

The stock's own ATR isn't stored anywhere in the signal dict, but
stock_sl is, and stock_sl = price -/+ atr*0.4 is an exact formula --
so ATR gets reconstructed from it below rather than requiring a new
field to be threaded through from views.py.

ONE persistent file, not one-per-day (deliberately different from
excel_logger.py's daily-file convention): signal_logs/
positional_signals.xlsx, one row per positional trade, updated in
place over however many real days it takes to resolve.

EXPIRY is a real, hard wall here, not a chosen safety cap -- unlike
backtest_index_positional.py's MAX_HOLD_DAYS (an assumption applied
to already-logged history), a live option contract genuinely stops
trading at its own expiry date. Expiry is computed and LOCKED at
entry time (same _last_thursday() NSE monthly-expiry rule
index_tracker.py already uses), and a position still open on/after
that date is force-closed at its last known quote, Outcome "Expired"
-- never left open against a contract that no longer exists.

INTEGRATION (not done by this file -- see the accompanying note for
the exact 2-line hook into views.py):
  log_new_positional_signals(newly_logged) -- call with EXACTLY what
    excel_logger.sync_active_signals() already returns as newly
    logged this cycle. Not the full active-signal list -- that would
    open a new positional row every cycle a signal merely stays
    active, not just when it's genuinely new.
  check_positional_outcomes(get_quotes_fn) -- call once per scan
    cycle, same cadence as excel_logger.check_outcomes().
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
PATH = os.path.join(LOG_DIR, "positional_signals.xlsx")

COLUMNS = [
    "Entry Timestamp", "Symbol", "Action", "Grade", "Sector",
    "Entry (Premium)", "SL", "Target 1", "Target 2", "Target 3", "Qty",
    "Option Symbol", "Expiry Date",
    "SL Hit At", "Target 1 Hit At", "Target 2 Hit At", "Target 3 Hit At",
    "Outcome", "Exit Price", "Exited At",
]

_lock = threading.Lock()


def compute_positional_levels(signal):
    """
    Wider multi-day SL/Target for one intraday signal dict -- see this
    module's own docstring for exactly why this goes through the same
    stock-move -> delta -> premium translation the intraday engine
    uses, not a direct ATR-on-premium shortcut.

    Returns (sl, t1, t2, t3), or None if the signal is missing
    something this can't safely be computed without (delta, price,
    stock_sl) -- never a guessed/estimated level.
    """
    price = signal.get("price")
    action = signal.get("action")
    premium_entry = signal.get("entry")
    delta = signal.get("delta")
    stock_sl = signal.get("stock_sl")
    if None in (price, action, premium_entry, delta, stock_sl):
        return None

    atr = abs(price - stock_sl) / 0.4
    if atr <= 0:
        return None
    d = max(abs(delta), 0.05)  # same floor the intraday engine uses -- deep-OTM delta shouldn't zero out the math

    if action == "BUY":
        stock_sl_pos = price - atr * 1.5
        stock_t1_pos = price + atr * 2
        stock_t2_pos = price + atr * 3
        stock_t3_pos = price + atr * 4
    else:
        stock_sl_pos = price + atr * 1.5
        stock_t1_pos = price - atr * 2
        stock_t2_pos = price - atr * 3
        stock_t3_pos = price - atr * 4

    sl = round(max(0.05, premium_entry - d * abs(price - stock_sl_pos) * 1.4), 2)
    t1 = round(premium_entry + d * abs(stock_t1_pos - price), 2)
    t2 = round(premium_entry + d * abs(stock_t2_pos - price), 2)
    t3 = round(premium_entry + d * abs(stock_t3_pos - price), 2)
    return sl, t1, t2, t3


def _expiry_date_for(entry_dt):
    """Locked at entry time -- same NSE monthly-expiry rule
    index_tracker.py's _last_thursday() already uses. Deferred import:
    this is a shared NSE-calendar fact, not index-specific logic, but
    kept deferred to match this project's existing convention for
    avoiding import-time coupling between modules."""
    from .index_tracker import _last_thursday
    expiry = _last_thursday(entry_dt.year, entry_dt.month)
    if entry_dt.date() > expiry.date():
        y, m = (entry_dt.year + 1, 1) if entry_dt.month == 12 else (entry_dt.year, entry_dt.month + 1)
        expiry = _last_thursday(y, m)
    return expiry


def _get_workbook():
    if os.path.exists(PATH):
        wb = load_workbook(PATH)
        ws = wb["Positional"]
        existing_header = [c.value for c in ws[1]]
        if existing_header != COLUMNS:
            # Same archive-and-restart pattern excel_logger.py and
            # index_tracker.py already use for a schema change --
            # rewriting the header in place would shift existing rows'
            # data under the wrong columns.
            archive_path = PATH.replace(".xlsx", "_pre-update.xlsx")
            if not os.path.exists(archive_path):
                wb.save(archive_path)
                print(f"[PositionalLog] Column layout changed -- archived old data to {os.path.basename(archive_path)}, starting fresh")
            wb = Workbook()
            ws = wb.active
            ws.title = "Positional"
            ws.append(COLUMNS)
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
        return wb
    os.makedirs(LOG_DIR, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Positional"
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
    return wb


def log_new_positional_signals(newly_logged_signals):
    """
    One new row per genuinely-new intraday signal this cycle -- pass
    exactly what excel_logger.sync_active_signals() already returns,
    not the full active-signal list (that would open a duplicate
    positional row every cycle a signal merely stays active).

    Silently skips any signal compute_positional_levels() can't
    safely price (missing delta/price/stock_sl), or with no
    'quantity' already resolved -- same real-lot-size the intraday
    signal itself already carries, not re-resolved here, since it's
    the same contract either way. Never fabricates a quantity or a
    price level.

    Returns how many rows were actually written.
    """
    if not OPENPYXL_AVAILABLE or not newly_logged_signals:
        return 0

    written = 0
    with _lock:
        wb = _get_workbook()
        ws = wb["Positional"]
        now = datetime.now()

        for s in newly_logged_signals:
            symbol = s.get("symbol")
            action = s.get("action")
            option_symbol = s.get("option_symbol")
            qty = s.get("quantity")
            if not symbol or not action or not option_symbol or not qty:
                continue

            levels = compute_positional_levels(s)
            if levels is None:
                continue
            sl, t1, t2, t3 = levels
            expiry = _expiry_date_for(now)

            ws.append([
                now.strftime("%Y-%m-%d %H:%M:%S"), symbol, action, s.get("grade"), s.get("sector"),
                s.get("entry"), sl, t1, t2, t3, qty, option_symbol, expiry.strftime("%Y-%m-%d"),
                None, None, None, None, None, None, None,
            ])
            written += 1

        if written:
            wb.save(PATH)
    return written


def check_positional_outcomes(get_quotes_fn):
    """
    Call once per scan cycle, same cadence as
    excel_logger.check_outcomes(). Checks every currently-OPEN
    positional row's real live premium against its own SL/Target
    1/2/3 -- same crossing rule used throughout this project (SL
    first, then furthest target). A row on or past its own locked
    Expiry Date gets force-closed at its last known quote, Outcome
    "Expired" -- a real option contract stops trading at expiry, this
    is not a chosen safety cap.

    get_quotes_fn: same injectable-quotes convention
    excel_logger.check_outcomes() already uses (pass
    screener.fyers_client.get_quotes) -- kept as a parameter so this
    stays testable with a fake quotes function, no import-time
    dependency on the real Fyers client.
    """
    if not OPENPYXL_AVAILABLE:
        return
    if not os.path.exists(PATH):
        return

    with _lock:
        wb = _get_workbook()
        ws = wb["Positional"]
        headers = [c.value for c in ws[1]]
        col = {name: i + 1 for i, name in enumerate(headers)}

        open_rows = []
        for row_num in range(2, ws.max_row + 1):
            if ws.cell(row=row_num, column=col["Outcome"]).value:
                continue  # already resolved
            opt_symbol = ws.cell(row=row_num, column=col["Option Symbol"]).value
            if not opt_symbol:
                continue
            open_rows.append(row_num)

        if not open_rows:
            return
        symbols_to_check = {ws.cell(row=r, column=col["Option Symbol"]).value: r for r in open_rows}

    try:
        resp = get_quotes_fn(list(symbols_to_check.keys()))
    except Exception as e:
        print(f"[PositionalLog] Outcome check quotes failed: {e}")
        resp = None

    ltp_by_symbol = {}
    if resp and resp.get("s") == "ok":
        for item in resp.get("d", []):
            if item.get("s") == "ok":
                v = item.get("v", {}) or {}
                if v.get("lp") is not None:
                    ltp_by_symbol[item.get("n")] = v["lp"]

    today_str = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _lock:
        wb = _get_workbook()
        ws = wb["Positional"]
        headers = [c.value for c in ws[1]]
        col = {name: i + 1 for i, name in enumerate(headers)}
        changed = False

        for opt_symbol, row_num in symbols_to_check.items():
            if ws.cell(row=row_num, column=col["Outcome"]).value:
                continue  # resolved by an earlier symbol sharing a row number this pass -- shouldn't happen, defensive only
            ltp = ltp_by_symbol.get(opt_symbol)
            sl = ws.cell(row=row_num, column=col["SL"]).value
            t1 = ws.cell(row=row_num, column=col["Target 1"]).value
            t2 = ws.cell(row=row_num, column=col["Target 2"]).value
            t3 = ws.cell(row=row_num, column=col["Target 3"]).value
            expiry_str = ws.cell(row=row_num, column=col["Expiry Date"]).value

            resolved_this_row = False
            if ltp is not None:
                # Long option premium either way (BUY->call bought,
                # SELL->put bought) -- premium falls toward SL on an
                # adverse move, rises toward targets on a favorable
                # one, same check regardless of action. Same
                # convention index_signal.py's check_call_outcome()
                # already uses for exactly this reason.
                if sl is not None and ltp <= sl:
                    ws.cell(row=row_num, column=col["SL Hit At"]).value = now_str
                    ws.cell(row=row_num, column=col["Outcome"]).value = "SL Hit"
                    ws.cell(row=row_num, column=col["Exit Price"]).value = ltp
                    ws.cell(row=row_num, column=col["Exited At"]).value = now_str
                    changed = True
                    resolved_this_row = True
                else:
                    for n, level in ((3, t3), (2, t2), (1, t1)):
                        if level is not None and ltp >= level:
                            ws.cell(row=row_num, column=col[f"Target {n} Hit At"]).value = now_str
                            ws.cell(row=row_num, column=col["Outcome"]).value = f"Target {n} Hit"
                            ws.cell(row=row_num, column=col["Exit Price"]).value = ltp
                            ws.cell(row=row_num, column=col["Exited At"]).value = now_str
                            changed = True
                            resolved_this_row = True
                            break

            if not resolved_this_row and expiry_str and today_str >= str(expiry_str):
                ws.cell(row=row_num, column=col["Outcome"]).value = "Expired"
                if ltp is not None:
                    ws.cell(row=row_num, column=col["Exit Price"]).value = ltp
                ws.cell(row=row_num, column=col["Exited At"]).value = now_str
                changed = True

        if changed:
            wb.save(PATH)


def get_positional_log_path():
    """Path to the positional log, for a download endpoint -- None if
    nothing's been logged yet."""
    return PATH if os.path.exists(PATH) else None
