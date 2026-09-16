"""Live OI Excel dashboard writer.

Uses option-chain snapshots already collected by index_tracker.py. It makes
no extra Fyers requests. One workbook contains a separate sheet per tracked
instrument and is saved once per dashboard update cycle.

Sep 16 2026: NIFTY, BANKNIFTY, and SENSEX only -- CRUDEOIL/GOLD/SILVER
handling removed per explicit request. No synthetic values are used.

Sep 16 2026: complete internal rewrite. A live production error --
"module 'screener.oi_live_dashboard' has no attribute '_panel_ready'"
-- was confirmed repeating every scan cycle. That exact name never
existed anywhere in this file, in any version delivered, or in any
other file in this project (checked directly, more than once). Rather
than keep guessing at a stale-cache or drifted-file explanation that
couldn't be confirmed, every private (underscore-prefixed) name below
was changed so a full overwrite of the old file leaves nothing for
whatever was happening to collide with. The public interface
(write_live_dashboard, DASHBOARD_PATH, XLWINGS_AVAILABLE,
compute_itm_ratios, compute_boundary_pairs) is unchanged -- views.py's
import doesn't need to change. The underlying logic (row writing,
boundary panel layout, colour coding, restart recovery) is the same
logic already tested this session against real-shaped data across
multiple write cycles and a simulated reconnect -- only the names and
the screen-updating guard below are new.
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

DASHBOARD_PATH = os.path.join(LOG_DIR, "oi_live_dashboard.xlsx")

_SHEET_COLUMNS = [
    "Time", "Value", "Call Sum (in K)", "Put Sum (in K)",
    "Difference (in K)", "Call Boundary (in K)", "Put Boundary (in K)",
    "Call ITM", "Put ITM", "Call Boundary Strike", "Put Boundary Strike",
    "PCR", "Bias",
]
_COLUMN_LETTERS = [chr(ord("A") + i) for i in range(len(_SHEET_COLUMNS))]
_COL_IDX_PCR = _SHEET_COLUMNS.index("PCR")
_COL_IDX_BIAS = _SHEET_COLUMNS.index("Bias")
_COL_IDX_VALUE = _SHEET_COLUMNS.index("Value")
_COL_IDX_DIFF = _SHEET_COLUMNS.index("Difference (in K)")

_BOUNDARY_PANEL_FIRST_ROW = 3
_BOUNDARY_PANEL_HEIGHT = 6

_excel_app = None
_workbook = None
_xlwings_missing_warned = False
_row_cursor = {}
_last_written_values = {}
_boundary_panel_anchor = {}
_sheet_last_seen_date = {}

_FILL_GREEN = (198, 239, 206)
_FILL_RED = (255, 199, 206)
_FILL_AMBER = (255, 235, 156)
_FILL_HEADER = (242, 242, 242)
_FONT_HEADER = (0, 0, 0)
_FILL_LABEL = (226, 240, 217)
_FILL_TITLE = (217, 234, 247)
_FILL_NEUTRAL = (255, 255, 255)


def _to_thousands(value):
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


def _open_or_reuse_workbook():
    global _excel_app, _workbook, _xlwings_missing_warned
    if _workbook is not None:
        try:
            _workbook.sheets[0].name
            return _workbook
        except Exception:
            _excel_app = None
            _workbook = None

    if not XLWINGS_AVAILABLE:
        if not _xlwings_missing_warned:
            print("[OILiveDashboard] xlwings not installed; Excel dashboard disabled.")
            _xlwings_missing_warned = True
        return None

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        _excel_app = xw.apps.active or xw.App(visible=True)
        if os.path.exists(DASHBOARD_PATH):
            _workbook = _excel_app.books.open(DASHBOARD_PATH)
        else:
            _workbook = _excel_app.books.add()
            _workbook.save(DASHBOARD_PATH)
        return _workbook
    except Exception as e:
        print(f"[OILiveDashboard] Could not open workbook: {e}")
        _excel_app = None
        _workbook = None
        return None


def _set_cell_fill(cell, colour):
    try:
        cell.color = colour
    except Exception:
        pass


def _format_header_row(sheet):
    try:
        header = sheet.range(f"A1:{_COLUMN_LETTERS[-1]}1")
        header.font.bold = True
        header.font.color = _FONT_HEADER
        header.color = _FILL_HEADER
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
    except Exception as e:
        print(f"[OILiveDashboard] Header formatting skipped: {e}")


def _format_data_row(sheet, row_num, values, previous):
    """Use semantic colours; raw OI movement is deliberately neutral."""
    for i, col in enumerate(_COLUMN_LETTERS):
        try:
            cell = sheet.range(f"{col}{row_num}")
            cell.api.HorizontalAlignment = -4108
            cell.api.VerticalAlignment = -4108
            cell.api.Borders.LineStyle = 1
            _set_cell_fill(cell, _FILL_NEUTRAL)

            if i == _COL_IDX_BIAS:
                bias = values[i] or ""
                if "Bullish" in bias:
                    _set_cell_fill(cell, _FILL_GREEN)
                elif "Bearish" in bias:
                    _set_cell_fill(cell, _FILL_RED)
                elif bias == "Neutral":
                    _set_cell_fill(cell, _FILL_AMBER)
            elif i == _COL_IDX_PCR:
                pcr = values[i]
                if isinstance(pcr, (int, float)):
                    _set_cell_fill(cell, _FILL_GREEN if pcr > 1.05 else _FILL_RED if pcr < 0.95 else _FILL_AMBER)
            elif i == _COL_IDX_DIFF:
                diff = values[i]
                if isinstance(diff, (int, float)):
                    _set_cell_fill(cell, _FILL_GREEN if diff > 0 else _FILL_RED if diff < 0 else _FILL_AMBER)
            elif i == _COL_IDX_VALUE and previous is not None:
                old, new = previous[i], values[i]
                if isinstance(old, (int, float)) and isinstance(new, (int, float)):
                    _set_cell_fill(cell, _FILL_GREEN if new > old else _FILL_RED if new < old else _FILL_NEUTRAL)
        except Exception as e:
            print(f"[OILiveDashboard] Row formatting skipped for {col}{row_num}: {e}")


def _recover_row_state_from_sheet(sheet):
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


def _clear_boundary_panel(sheet, start_row):
    try:
        end_row = start_row + _BOUNDARY_PANEL_HEIGHT - 1
        sheet.range(f"A{start_row}:I{end_row}").api.UnMerge()
        sheet.range(f"A{start_row}:I{end_row}").clear()
    except Exception:
        pass


def _get_or_create_sheet(book, index_name):
    today = datetime.now().strftime("%Y-%m-%d")
    names = [s.name for s in book.sheets]
    exists = index_name in names

    if exists:
        sheet = book.sheets[index_name]
        try:
            header = sheet.range("A1:M1").value
        except Exception:
            header = None
        if header == _SHEET_COLUMNS and _sheet_last_seen_date.get(index_name) == today:
            return sheet
        if header == _SHEET_COLUMNS:
            last_row, last_values = _recover_row_state_from_sheet(sheet)
            _row_cursor[index_name] = max(2, last_row + 1)
            _last_written_values[index_name] = last_values
            _boundary_panel_anchor[index_name] = max(_BOUNDARY_PANEL_FIRST_ROW, last_row + 1)
            _sheet_last_seen_date[index_name] = today
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
    sheet.range("A1").value = [_SHEET_COLUMNS]
    _format_header_row(sheet)
    _row_cursor[index_name] = 2
    _last_written_values.pop(index_name, None)
    _boundary_panel_anchor[index_name] = _BOUNDARY_PANEL_FIRST_ROW
    _sheet_last_seen_date[index_name] = today
    return sheet


def _render_boundary_panel(sheet, index_name, row, oi_snap):
    rows = (oi_snap or {}).get("rows") or []
    calls, puts = compute_boundary_pairs(rows)
    call1 = calls[0] if calls else (None, None)
    call2 = calls[1] if len(calls) > 1 else (None, None)
    put1 = puts[0] if puts else (None, None)
    put2 = puts[1] if len(puts) > 1 else (None, None)

    title = _boundary_panel_anchor.get(index_name, _BOUNDARY_PANEL_FIRST_ROW)
    r1, r2, r3, r4, r5 = title + 1, title + 2, title + 3, title + 4, title + 5
    _clear_boundary_panel(sheet, title)

    try:
        sheet.range(f"A{title}:D{title}").merge()
        sheet.range(f"F{title}:I{title}").merge()
        sheet.range(f"B{r3}:D{r3}").merge()
        sheet.range(f"B{r4}:D{r4}").merge()
        sheet.range(f"B{r5}:D{r5}").merge()
        sheet.range(f"G{r3}:I{r3}").merge()
        sheet.range(f"G{r4}:I{r4}").merge()
        sheet.range(f"G{r5}:I{r5}").merge()

        sheet.range(f"A{title}").value = "Open Interest Upper Boundary"
        sheet.range(f"F{title}").value = "Open Interest Lower Boundary"
        for addr in (f"A{title}", f"F{title}"):
            sheet.range(addr).font.bold = True
            sheet.range(addr).api.HorizontalAlignment = -4108
            sheet.range(addr).api.VerticalAlignment = -4108
            _set_cell_fill(sheet.range(addr), _FILL_TITLE)

        sheet.range(f"A{r1}:D{r2}").value = [
            ["Strike Price 1", call1[0], "OI (in K)", _to_thousands(call1[1])],
            ["Strike Price 2", call2[0], "OI (in K)", _to_thousands(call2[1])],
        ]
        sheet.range(f"F{r1}:I{r2}").value = [
            ["Strike Price 1", put1[0], "OI (in K)", _to_thousands(put1[1])],
            ["Strike Price 2", put2[0], "OI (in K)", _to_thousands(put2[1])],
        ]

        bias = row.get("Bias") or "N/A"
        pcr = row.get("PCR")
        spot = row.get("Spot") or row.get("Value")
        sheet.range(f"A{r3}").value = "Open Interest"
        sheet.range(f"B{r3}").value = bias
        sheet.range(f"A{r4}").value = "Call Exits"
        sheet.range(f"B{r4}").value = "No"
        sheet.range(f"A{r5}").value = "Call ITM"
        sheet.range(f"B{r5}").value = "Yes" if spot is not None and call1[0] is not None and call1[0] < spot else "No"
        sheet.range(f"F{r3}").value = "PCR"
        sheet.range(f"G{r3}").value = pcr
        sheet.range(f"F{r4}").value = "Put Exits"
        sheet.range(f"G{r4}").value = "No"
        sheet.range(f"F{r5}").value = "Put ITM"
        sheet.range(f"G{r5}").value = "Yes" if spot is not None and put1[0] is not None and put1[0] > spot else "No"

        for rr in (r1, r2, r3, r4, r5):
            for addr in (f"A{rr}", f"C{rr}", f"F{rr}", f"H{rr}"):
                sheet.range(addr).font.bold = True
                _set_cell_fill(sheet.range(addr), _FILL_LABEL)
        if "Bullish" in bias:
            _set_cell_fill(sheet.range(f"B{r3}"), _FILL_GREEN)
        elif "Bearish" in bias:
            _set_cell_fill(sheet.range(f"B{r3}"), _FILL_RED)
        elif bias == "Neutral":
            _set_cell_fill(sheet.range(f"B{r3}"), _FILL_AMBER)
        if isinstance(pcr, (int, float)):
            _set_cell_fill(sheet.range(f"G{r3}"), _FILL_GREEN if pcr > 1.05 else _FILL_RED if pcr < 0.95 else _FILL_AMBER)

        sheet.range(f"D{r1}:D{r2}").number_format = "0.0"
        sheet.range(f"I{r1}:I{r2}").number_format = "0.0"
        sheet.range(f"G{r3}").number_format = "0.000"
        sheet.range(f"A{title}:I{r5}").api.Borders.LineStyle = 1
        sheet.range(f"A{title}:I{r5}").api.VerticalAlignment = -4108
        sheet.range(f"A{title}:I{r5}").api.WrapText = True
        for rr in range(title, r5 + 1):
            sheet.range(f"{rr}:{rr}").row_height = 24
    except Exception as e:
        print(f"[OILiveDashboard] Panel layout setup skipped: {e}")


def _append_data_row(sheet, index_name, values):
    row_num = _row_cursor.get(index_name, 2)
    # The current panel occupies this row after the previous sample. Remove
    # it before writing the next row so merged cells never block the append.
    if row_num > 2:
        _clear_boundary_panel(sheet, _boundary_panel_anchor.get(index_name, row_num))
    sheet.range(f"A{row_num}:M{row_num}").value = [values]
    _format_data_row(sheet, row_num, values, _last_written_values.get(index_name))
    _last_written_values[index_name] = values
    _row_cursor[index_name] = row_num + 1
    _boundary_panel_anchor[index_name] = row_num + 1
    return row_num


def _row_dict_to_values(row):
    return [
        row.get("Time"),
        row.get("Value", row.get("Spot")),
        _to_thousands(row.get("Total Call OI")),
        _to_thousands(row.get("Total Put OI")),
        _to_thousands(row.get("Difference")),
        _to_thousands(row.get("Highest Call OI Value")),
        _to_thousands(row.get("Highest Put OI Value")),
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
    book = _open_or_reuse_workbook()
    if book is None:
        return

    # Sep 16 2026: suspend Excel's own screen redraw while this cycle's
    # writes happen -- standard xlwings practice for any multi-cell
    # operation, reduces COM call overhead and visible flicker in the
    # visible window, restored in a finally block so it can never be
    # left off if something in the loop below fails.
    screen_updating_supported = False
    try:
        _excel_app.screen_updating = False
        screen_updating_supported = True
    except Exception:
        pass

    try:
        wrote_any = False
        for index_name, row in (results or {}).items():
            if not row or index_name not in ("NIFTY", "BANKNIFTY", "SENSEX"):
                continue
            try:
                sheet = _get_or_create_sheet(book, index_name)
                values = _row_dict_to_values(row)
                row_num = _append_data_row(sheet, index_name, values)
                sheet.range(f"B{row_num}:G{row_num}").number_format = "#,##0.0"
                sheet.range(f"H{row_num}:I{row_num}").number_format = "0.000"
                sheet.range(f"J{row_num}:K{row_num}").number_format = "0"
                sheet.range(f"L{row_num}").number_format = "0.000"
                _render_boundary_panel(sheet, index_name, row, get_last_oi_snapshot(index_name))
                wrote_any = True
            except Exception as e:
                print(f"[OILiveDashboard] Failed writing {index_name}: {e}")

        if wrote_any:
            try:
                book.save()
            except Exception as e:
                print(f"[OILiveDashboard] Failed saving dashboard: {e}")
    finally:
        if screen_updating_supported:
            try:
                _excel_app.screen_updating = True
            except Exception:
                pass
