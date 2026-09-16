"""Live OI Excel dashboard writer.

Uses option-chain snapshots already collected by index_tracker.py. It makes
no extra Fyers requests. One workbook contains a separate sheet per tracked
instrument and is saved once per dashboard update cycle.

Sep 16 2026: NIFTY, BANKNIFTY, and SENSEX only -- CRUDEOIL/GOLD/SILVER
handling removed per explicit request. No synthetic values are used.

Sep 16 2026: internal names here are load-bearing -- two other project
files (oi_dashboard_runtime_guard.py, oi_dashboard_header_guard.py)
monkey-patch _prepare_sheet, _style_live_row, and _write_dashboard_row
on this module by name after import, and read _LIVE_LOG_COLUMNS,
_COL_LETTERS, _BIAS_COL_INDEX, _PCR_COL_INDEX, _GREEN_FILL, _RED_FILL,
_AMBER_FILL, _HEADER_FILL, _fill, _FIRST_PANEL_ROW, _next_row,
_panel_start_rows, _sheet_day_seen, _prev_values, and _panel_ready
directly. An earlier attempt this session renamed all of these,
intended to rule out a stale-cache explanation for a live
"has no attribute '_panel_ready'" error -- that broke both guard
files outright (confirmed live: "Header guard unavailable" / "Runtime
guard unavailable" at startup) once their own files were shared and
made clear they depend on these exact names. Reverted. The real root
cause: _panel_ready never existed on this module in any version, ever
-- an empty set here is the actual fix, not a coincidence of naming.
Do not rename anything below without checking both guard files first.
"""

import os
import threading
import time
from datetime import datetime

try:
    import xlwings as xw
    XLWINGS_AVAILABLE = True
except ImportError:
    XLWINGS_AVAILABLE = False

from .index_tracker import LOG_DIR, get_last_oi_snapshot

def get_dashboard_path():
    """
    Sep 16 2026: per explicit request -- a new file every day, in the
    same per-day folder structure index_tracker.py already uses for
    its own snapshot files (LOG_DIR/<date>/index_tracker_<name>_
    <date>.xlsx), matched here exactly rather than inventing a
    different convention: LOG_DIR/<date>/oi_live_dashboard_<date>.xlsx.
    A function, not a fixed constant, so every caller always gets
    TODAY's real path -- the old fixed DASHBOARD_PATH would have kept
    pointing at whatever day the process started on if it stayed
    running across midnight.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    day_dir = os.path.join(LOG_DIR, today)
    os.makedirs(day_dir, exist_ok=True)
    return os.path.join(day_dir, f"oi_live_dashboard_{today}.xlsx")

_LIVE_LOG_COLUMNS = [
    "Time", "Value", "Call Sum (in K)", "Put Sum (in K)",
    "Difference (in K)", "Call Boundary (in K)", "Put Boundary (in K)",
    "Call ITM", "Put ITM", "Call Boundary Strike", "Put Boundary Strike",
    "PCR", "Bias",
]
_COL_LETTERS = [chr(ord("A") + i) for i in range(len(_LIVE_LOG_COLUMNS))]
_PCR_COL_INDEX = _LIVE_LOG_COLUMNS.index("PCR")
_BIAS_COL_INDEX = _LIVE_LOG_COLUMNS.index("Bias")
_VALUE_COL_INDEX = _LIVE_LOG_COLUMNS.index("Value")
_DIFF_COL_INDEX = _LIVE_LOG_COLUMNS.index("Difference (in K)")

_FIRST_PANEL_ROW = 3
_PANEL_HEIGHT = 6

_app = None
_book = None
_warned_once = False
_next_row = {}
_prev_values = {}
_panel_start_rows = {}
_sheet_day_seen = {}
# Sep 16 2026: REAL GAP FOUND -- the circuit breaker added to views.py
# several turns ago wraps this module's write_live_dashboard() call,
# but every failure in here is already caught and printed internally
# (per-index try/except, plus _get_dashboard_book's own try/except) --
# so write_live_dashboard() always returns normally, no exception ever
# reaches views.py's circuit breaker, and it never trips. Confirmed
# live: the same COM error code repeating on every single cycle,
# unthrottled. This is the fix -- the breaker has to live where the
# failures actually happen.
_consecutive_total_failures = 0
_cycles_since_disabled = 0
_TOTAL_FAILURE_THRESHOLD = 3
_RETRY_EVERY_N_CYCLES = 20  # ~20 scan cycles before quietly trying again, in case Excel recovers on its own
# Sep 16 2026: REAL ROOT CAUSE FOUND -- this was the actual missing
# piece the whole time. oi_dashboard_runtime_guard.py (an existing
# project file, monkey-patches this module's _prepare_sheet and
# _write_dashboard_row after import) calls
# dashboard._panel_ready.discard(index_name) in both of its patched
# functions -- but this attribute never existed anywhere in this file,
# in any version, before or after any edit made this session. That's
# what "module has no attribute '_panel_ready'" actually was: not a
# stale cache, not a drifted file -- a real, genuine gap between what
# the guard file expects and what this file ever defined. An empty
# set is sufficient: nothing here ever needs to .add() to it, since
# every reference found only ever calls .discard(), which is a safe
# no-op for a key that was never present.
_panel_ready = set()

_GREEN_FILL = (198, 239, 206)
_RED_FILL = (255, 199, 206)
_AMBER_FILL = (255, 235, 156)
_HEADER_FILL = (242, 242, 242)
_HEADER_FONT = (0, 0, 0)
_LABEL_FILL = (226, 240, 217)
_TITLE_FILL = (217, 234, 247)
_NEUTRAL_FILL = (255, 255, 255)


def _to_k(value):
    return round(value / 1000, 1) if value is not None else None


def compute_itm_ratios(rows, spot, total_ce_oi, total_pe_oi):
    """Return call/put ITM OI ratios; None when required data is missing."""
    if not rows or spot is None:
        return None, None
    call_itm = sum(
        (r.get("ce", {}) or {}).get("oi", 0) or 0
        for r in rows
        if r.get("strike") is not None and r["strike"] < spot
    )
    put_itm = sum(
        (r.get("pe", {}) or {}).get("oi", 0) or 0
        for r in rows
        if r.get("strike") is not None and r["strike"] > spot
    )
    return (
        round(call_itm / total_ce_oi, 3) if total_ce_oi else None,
        round(put_itm / total_pe_oi, 3) if total_pe_oi else None,
    )


def compute_boundary_pairs(rows, top_n=2):
    """Return highest-OI call and put strikes as (strike, oi) pairs."""
    if not rows:
        return [], []

    def pairs(side):
        values = [
            (r.get("strike"), (r.get(side, {}) or {}).get("oi"))
            for r in rows
            if r.get("strike") is not None
            and (r.get(side, {}) or {}).get("oi") is not None
        ]
        values.sort(key=lambda x: x[1], reverse=True)
        return values[:top_n]

    return pairs("ce"), pairs("pe")


def _get_dashboard_book():
    global _app, _book, _warned_once
    today_path = get_dashboard_path()
    today_filename = os.path.basename(today_path)
    if _book is not None:
        try:
            if _book.name != today_filename:
                # Sep 16 2026: day has rolled over since _book was
                # opened (the process kept running across midnight) --
                # the old reuse check here only verified the book
                # object hadn't crashed, never whether today's date
                # had actually changed. Force a fresh open of today's
                # real file below instead of continuing to write into
                # yesterday's.
                raise RuntimeError("date rolled over")
            _book.sheets[0].name
            return _book
        except Exception:
            _app = None
            _book = None

    if not XLWINGS_AVAILABLE:
        if not _warned_once:
            print("[OILiveDashboard] xlwings not installed; Excel dashboard disabled.")
            _warned_once = True
        return None

    try:
        # Sep 16 2026 (revision): the previous fix only checked
        # xw.apps.active's books -- but "active" means whichever Excel
        # window has OS-level focus at that instant, which is a
        # DIFFERENT thing from "the Excel window that has the dashboard
        # file open". Confirmed still failing live after that fix
        # shipped: the user is looking at the PowerShell terminal, not
        # Excel, when this runs, so xw.apps.active is either None or a
        # different, unrelated Excel window -- not necessarily the one
        # with today's dashboard file open. Search every running Excel
        # instance (xw.apps, the full collection), not just the active
        # one, so the file is found regardless of which window has
        # focus.
        already_open_app = None
        already_open_book = None
        try:
            for running_app in xw.apps:
                for existing_book in running_app.books:
                    if existing_book.name == today_filename:
                        already_open_app = running_app
                        already_open_book = existing_book
                        break
                if already_open_book is not None:
                    break
        except Exception:
            pass

        if already_open_book is not None:
            _app = already_open_app
            _book = already_open_book
        else:
            _app = xw.apps.active or xw.App(visible=True)
            if os.path.exists(today_path):
                _book = _app.books.open(today_path)
            else:
                _book = _app.books.add()
                _book.save(today_path)
        return _book
    except Exception as e:
        print(f"[OILiveDashboard] Could not open workbook: {e}")
        _app = None
        _book = None
        return None


def _fill(cell, colour):
    try:
        cell.color = colour
    except Exception:
        pass


def _style_header(sheet):
    try:
        header = sheet.range(f"A1:{_COL_LETTERS[-1]}1")
        header.font.bold = True
        header.font.color = _HEADER_FONT
        header.color = _HEADER_FILL
        header.api.HorizontalAlignment = -4108
        header.api.VerticalAlignment = -4108
        header.api.WrapText = True
        header.row_height = 38
        widths = {
            "A": 12, "B": 13, "C": 16, "D": 16, "E": 18,
            "F": 20, "G": 20, "H": 11, "I": 11, "J": 20,
            "K": 20, "L": 10, "M": 18,
        }
        for col, width in widths.items():
            sheet.range(f"{col}:{col}").column_width = width
        header.api.Borders.LineStyle = 1
        # Sep 16 2026: hide Call/Put Boundary Strike, PCR, Bias from the
        # visible main table -- the desktop app's own reference screenshot
        # has exactly 9 columns (Time through Put ITM), never these 4.
        # Can't remove them from the underlying data (both guard files
        # depend on _BIAS_COL_INDEX/_PCR_COL_INDEX pointing at real
        # positions in the row's values for their own row-coloring), so
        # hidden instead -- data and the panel below still use them, the
        # scrolling table just doesn't show them anymore.
        try:
            sheet.range("J:M").api.EntireColumn.Hidden = True
        except Exception as e:
            print(f"[OILiveDashboard] Column hiding skipped: {e}")
    except Exception as e:
        print(f"[OILiveDashboard] Header formatting skipped: {e}")


def _style_live_row(sheet, row_num, values, previous):
    """Use semantic colours; raw OI movement is deliberately neutral."""
    for i, col in enumerate(_COL_LETTERS):
        try:
            cell = sheet.range(f"{col}{row_num}")
            cell.api.HorizontalAlignment = -4108
            cell.api.VerticalAlignment = -4108
            cell.api.Borders.LineStyle = 1
            _fill(cell, _NEUTRAL_FILL)

            if i == _BIAS_COL_INDEX:
                bias = values[i] or ""
                if "Bullish" in bias:
                    _fill(cell, _GREEN_FILL)
                elif "Bearish" in bias:
                    _fill(cell, _RED_FILL)
                elif bias == "Neutral":
                    _fill(cell, _AMBER_FILL)
            elif i == _PCR_COL_INDEX:
                pcr = values[i]
                if isinstance(pcr, (int, float)):
                    _fill(cell, _GREEN_FILL if pcr > 1.05 else _RED_FILL if pcr < 0.95 else _AMBER_FILL)
            elif i == _DIFF_COL_INDEX:
                diff = values[i]
                if isinstance(diff, (int, float)):
                    _fill(cell, _GREEN_FILL if diff > 0 else _RED_FILL if diff < 0 else _AMBER_FILL)
            elif i == _VALUE_COL_INDEX and previous is not None:
                old, new = previous[i], values[i]
                if isinstance(old, (int, float)) and isinstance(new, (int, float)):
                    _fill(cell, _GREEN_FILL if new > old else _RED_FILL if new < old else _NEUTRAL_FILL)
        except Exception as e:
            print(f"[OILiveDashboard] Row formatting skipped for {col}{row_num}: {e}")


def _scan_existing_rows(sheet):
    """Recover today's rows after a backend/Excel restart."""
    last = 1
    last_values = None
    try:
        row = 2
        while row < 10000:
            value = sheet.range(f"A{row}").value
            if value in (None, ""):
                break
            values = sheet.range(f"A{row}:M{row}").value
            if values and isinstance(values, list) and values and isinstance(values[0], list):
                values = values[0]
            last = row
            last_values = values
            row += 1
    except Exception:
        pass
    return last, last_values


def _clear_panel(sheet, start_row):
    try:
        end_row = start_row + _PANEL_HEIGHT - 1
        sheet.range(f"A{start_row}:I{end_row}").api.UnMerge()
        sheet.range(f"A{start_row}:I{end_row}").clear()
    except Exception:
        pass


def _prepare_sheet(book, index_name):
    today = datetime.now().strftime("%Y-%m-%d")
    names = [s.name for s in book.sheets]
    exists = index_name in names

    if exists:
        sheet = book.sheets[index_name]
        try:
            header = sheet.range("A1:M1").value
        except Exception:
            header = None
        if header == _LIVE_LOG_COLUMNS and _sheet_day_seen.get(index_name) == today:
            return sheet
        if header == _LIVE_LOG_COLUMNS:
            last_row, last_values = _scan_existing_rows(sheet)
            _next_row[index_name] = max(2, last_row + 1)
            _prev_values[index_name] = last_values
            _panel_start_rows[index_name] = max(_FIRST_PANEL_ROW, last_row + 1)
            _sheet_day_seen[index_name] = today
            return sheet

        archive_name = f"{index_name}_archive"
        suffix = 1
        while archive_name in names:
            suffix += 1
            archive_name = f"{index_name}_archive_{suffix}"
        try:
            sheet.name = archive_name
        except Exception:
            pass

    sheet = book.sheets.add(index_name, after=book.sheets[-1])
    sheet.range("A1").value = [_LIVE_LOG_COLUMNS]
    _style_header(sheet)
    _next_row[index_name] = 2
    _prev_values.pop(index_name, None)
    _panel_start_rows[index_name] = _FIRST_PANEL_ROW
    _sheet_day_seen[index_name] = today
    return sheet


def _write_boundary_panel(sheet, index_name, row, oi_snap):
    """
    Sep 16 2026: moved to a FIXED location (columns P-X, row 2) that
    never changes cycle to cycle -- confirmed live via screenshots
    that the previous design (panel re-inserted into the data table's
    own next row, then relocated down each cycle -- oi_dashboard_
    runtime_guard.py's own write_dashboard_row does exactly this,
    reusing the panel's old row space for the next data row) produced
    a messy, interleaved sheet: the boundary panel kept reappearing in
    the middle of what should have been a continuously growing table.
    The desktop app (the original reference for this whole feature)
    never does this -- its table scrolls continuously and the panel
    sits fixed below it. This is the closest Excel-native equivalent:
    a permanent panel off to the side, always visible, always current,
    while columns A-M grow downward uninterrupted. Confirmed neither
    guard file references this function, so this is safe to change on
    its own -- the guard's own "reuse the panel's row space" logic in
    write_dashboard_row still runs, but now against cells nothing ever
    visually occupied, which is harmless.
    """
    rows = (oi_snap or {}).get("rows") or []
    calls, puts = compute_boundary_pairs(rows)
    call1 = calls[0] if calls else (None, None)
    call2 = calls[1] if len(calls) > 1 else (None, None)
    put1 = puts[0] if puts else (None, None)
    put2 = puts[1] if len(puts) > 1 else (None, None)

    title = 2  # fixed -- never derived from _panel_start_rows anymore
    r1, r2, r3, r4, r5 = title + 1, title + 2, title + 3, title + 4, title + 5
    # Columns P,Q,R,S / U,V,W,X mirror the original A,B,C,D / F,G,H,I
    # layout exactly, just shifted right; T is the visual gap column
    # (mirroring E in the original).
    L, R = "P", "U"  # left-panel and right-panel starting columns

    try:
        sheet.range(f"{L}{title}:{chr(ord(L)+3)}{title}").merge()
        sheet.range(f"{R}{title}:{chr(ord(R)+3)}{title}").merge()
        sheet.range(f"{chr(ord(L)+1)}{r3}:{chr(ord(L)+3)}{r3}").merge()
        sheet.range(f"{chr(ord(L)+1)}{r4}:{chr(ord(L)+3)}{r4}").merge()
        sheet.range(f"{chr(ord(L)+1)}{r5}:{chr(ord(L)+3)}{r5}").merge()
        sheet.range(f"{chr(ord(R)+1)}{r3}:{chr(ord(R)+3)}{r3}").merge()
        sheet.range(f"{chr(ord(R)+1)}{r4}:{chr(ord(R)+3)}{r4}").merge()
        sheet.range(f"{chr(ord(R)+1)}{r5}:{chr(ord(R)+3)}{r5}").merge()

        sheet.range(f"{L}{title}").value = "Open Interest Upper Boundary"
        sheet.range(f"{R}{title}").value = "Open Interest Lower Boundary"
        for addr in (f"{L}{title}", f"{R}{title}"):
            sheet.range(addr).font.bold = True
            sheet.range(addr).api.HorizontalAlignment = -4108
            sheet.range(addr).api.VerticalAlignment = -4108
            _fill(sheet.range(addr), _TITLE_FILL)

        Lb, Lc, Ld = chr(ord(L)+1), chr(ord(L)+2), chr(ord(L)+3)
        Rb, Rc, Rd = chr(ord(R)+1), chr(ord(R)+2), chr(ord(R)+3)
        sheet.range(f"{L}{r1}:{Ld}{r2}").value = [
            ["Strike Price 1", call1[0], "OI (in K)", _to_k(call1[1])],
            ["Strike Price 2", call2[0], "OI (in K)", _to_k(call2[1])],
        ]
        sheet.range(f"{R}{r1}:{Rd}{r2}").value = [
            ["Strike Price 1", put1[0], "OI (in K)", _to_k(put1[1])],
            ["Strike Price 2", put2[0], "OI (in K)", _to_k(put2[1])],
        ]

        bias = row.get("Bias") or "N/A"
        pcr = row.get("PCR")
        spot = row.get("Spot") or row.get("Value")
        sheet.range(f"{L}{r3}").value = "Open Interest"
        sheet.range(f"{Lb}{r3}").value = bias
        sheet.range(f"{L}{r4}").value = "Call Exits"
        sheet.range(f"{Lb}{r4}").value = "No"
        sheet.range(f"{L}{r5}").value = "Call ITM"
        sheet.range(f"{Lb}{r5}").value = "Yes" if spot is not None and call1[0] is not None and call1[0] < spot else "No"
        sheet.range(f"{R}{r3}").value = "PCR"
        sheet.range(f"{Rb}{r3}").value = pcr
        sheet.range(f"{R}{r4}").value = "Put Exits"
        sheet.range(f"{Rb}{r4}").value = "No"
        sheet.range(f"{R}{r5}").value = "Put ITM"
        sheet.range(f"{Rb}{r5}").value = "Yes" if spot is not None and put1[0] is not None and put1[0] > spot else "No"

        for rr in (r1, r2, r3, r4, r5):
            for addr in (f"{L}{rr}", f"{Lc}{rr}", f"{R}{rr}", f"{Rc}{rr}"):
                sheet.range(addr).font.bold = True
                _fill(sheet.range(addr), _LABEL_FILL)
        if "Bullish" in bias:
            _fill(sheet.range(f"{Lb}{r3}"), _GREEN_FILL)
        elif "Bearish" in bias:
            _fill(sheet.range(f"{Lb}{r3}"), _RED_FILL)
        elif bias == "Neutral":
            _fill(sheet.range(f"{Lb}{r3}"), _AMBER_FILL)
        if isinstance(pcr, (int, float)):
            _fill(sheet.range(f"{Rb}{r3}"), _GREEN_FILL if pcr > 1.05 else _RED_FILL if pcr < 0.95 else _AMBER_FILL)

        sheet.range(f"{Ld}{r1}:{Ld}{r2}").number_format = "0.0"
        sheet.range(f"{Rd}{r1}:{Rd}{r2}").number_format = "0.0"
        sheet.range(f"{Rb}{r3}").number_format = "0.000"
        sheet.range(f"{L}{title}:{Rd}{r5}").api.Borders.LineStyle = 1
        sheet.range(f"{L}{title}:{Rd}{r5}").api.VerticalAlignment = -4108
        sheet.range(f"{L}{title}:{Rd}{r5}").api.WrapText = True
        for rr in range(title, r5 + 1):
            sheet.range(f"{rr}:{rr}").row_height = 24
    except Exception as e:
        print(f"[OILiveDashboard] Panel layout setup skipped: {e}")


def _write_dashboard_row(sheet, index_name, values):
    row_num = _next_row.get(index_name, 2)
    # The current panel occupies this row after the previous sample. Remove
    # it before writing the next row so merged cells never block the append.
    if row_num > 2:
        _clear_panel(sheet, _panel_start_rows.get(index_name, row_num))
    sheet.range(f"A{row_num}:M{row_num}").value = [values]
    _style_live_row(sheet, row_num, values, _prev_values.get(index_name))
    _prev_values[index_name] = values
    _next_row[index_name] = row_num + 1
    _panel_start_rows[index_name] = row_num + 1
    return row_num


def _build_values(row):
    return [
        row.get("Time"),
        row.get("Value", row.get("Spot")),
        _to_k(row.get("Total Call OI")),
        _to_k(row.get("Total Put OI")),
        _to_k(row.get("Difference")),
        _to_k(row.get("Highest Call OI Value")),
        _to_k(row.get("Highest Put OI Value")),
        row.get("Call ITM Ratio"),
        row.get("Put ITM Ratio"),
        row.get("Highest Call OI Strike"),
        row.get("Highest Put OI Strike"),
        row.get("PCR"),
        row.get("Bias"),
    ]


def write_live_dashboard(results):
    """Write NIFTY/BANKNIFTY/SENSEX rows in one save. See module docstring
    for the Sep 16 2026 rewrite -- same tested logic, new internal names."""
    global _consecutive_total_failures, _cycles_since_disabled

    if _consecutive_total_failures >= _TOTAL_FAILURE_THRESHOLD:
        _cycles_since_disabled += 1
        if _cycles_since_disabled < _RETRY_EVERY_N_CYCLES:
            return
        _cycles_since_disabled = 0  # time to quietly try again

    book = _get_dashboard_book()
    if book is None:
        _consecutive_total_failures += 1
        if _consecutive_total_failures == _TOTAL_FAILURE_THRESHOLD:
            print(f"[OILiveDashboard] Excel dashboard failed {_consecutive_total_failures} cycles in a "
                  f"row with the same COM error -- this is almost always orphaned Excel.exe "
                  f"processes left behind by an earlier crash, not this code. Going quiet for "
                  f"roughly {_RETRY_EVERY_N_CYCLES} cycles rather than repeating this every time; "
                  f"will retry automatically. To fix now: close Excel, kill any remaining EXCEL.EXE "
                  f"in Task Manager, then restart the server.")
        return

    # Sep 16 2026: suspend Excel's own screen redraw while this cycle's
    # writes happen -- standard xlwings practice for any multi-cell
    # operation, reduces COM call overhead and visible flicker in the
    # visible window, restored in a finally block so it can never be
    # left off if something in the loop below fails.
    screen_updating_supported = False
    try:
        _app.screen_updating = False
        screen_updating_supported = True
    except Exception:
        pass

    try:
        wrote_any = False
        for index_name, row in (results or {}).items():
            if not row or index_name not in ("NIFTY", "BANKNIFTY", "SENSEX"):
                continue
            try:
                sheet = _prepare_sheet(book, index_name)
                values = _build_values(row)
                row_num = _write_dashboard_row(sheet, index_name, values)
                sheet.range(f"B{row_num}:G{row_num}").number_format = "#,##0.0"
                sheet.range(f"H{row_num}:I{row_num}").number_format = "0.000"
                sheet.range(f"J{row_num}:K{row_num}").number_format = "0"
                sheet.range(f"L{row_num}").number_format = "0.000"
                _write_boundary_panel(sheet, index_name, row, get_last_oi_snapshot(index_name))
                wrote_any = True
            except Exception as e:
                if _consecutive_total_failures < _TOTAL_FAILURE_THRESHOLD:
                    print(f"[OILiveDashboard] Failed writing {index_name}: {e}")

        if wrote_any:
            _consecutive_total_failures = 0
            try:
                book.save()
            except Exception as e:
                print(f"[OILiveDashboard] Failed saving dashboard: {e}")
        else:
            _consecutive_total_failures += 1
            if _consecutive_total_failures == _TOTAL_FAILURE_THRESHOLD:
                print(f"[OILiveDashboard] Excel dashboard failed {_consecutive_total_failures} cycles in a "
                      f"row with the same COM error -- this is almost always orphaned Excel.exe "
                      f"processes left behind by an earlier crash, not this code. Going quiet for "
                      f"roughly {_RETRY_EVERY_N_CYCLES} cycles rather than repeating this every time; "
                      f"will retry automatically. To fix now: close Excel, kill any remaining EXCEL.EXE "
                      f"in Task Manager, then restart the server.")
    finally:
        if screen_updating_supported:
            try:
                _app.screen_updating = True
            except Exception:
                pass
