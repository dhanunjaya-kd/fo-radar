"""Live OI Excel dashboard writer.

Uses option-chain snapshots already collected by index_tracker.py. It makes
no extra Fyers requests. One workbook contains a separate sheet per tracked
instrument and is saved once per dashboard update cycle.

Sep 16 2026: NIFTY, BANKNIFTY, and SENSEX only -- CRUDEOIL/GOLD/SILVER
handling removed per explicit request. No synthetic values are used.
"""

import os
from datetime import datetime

try:
    import xlwings as xw
    XLWINGS_AVAILABLE = True
except ImportError:
    XLWINGS_AVAILABLE = False

from .index_tracker import LOG_DIR, get_last_oi_snapshot

DASHBOARD_PATH = os.path.join(LOG_DIR, "oi_live_dashboard.xlsx")

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
    if _book is not None:
        try:
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
        os.makedirs(LOG_DIR, exist_ok=True)
        _app = xw.apps.active or xw.App(visible=True)
        if os.path.exists(DASHBOARD_PATH):
            _book = _app.books.open(DASHBOARD_PATH)
        else:
            _book = _app.books.add()
            _book.save(DASHBOARD_PATH)
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
    rows = (oi_snap or {}).get("rows") or []
    calls, puts = compute_boundary_pairs(rows)
    call1 = calls[0] if calls else (None, None)
    call2 = calls[1] if len(calls) > 1 else (None, None)
    put1 = puts[0] if puts else (None, None)
    put2 = puts[1] if len(puts) > 1 else (None, None)

    title = _panel_start_rows.get(index_name, _FIRST_PANEL_ROW)
    r1, r2, r3, r4, r5 = title + 1, title + 2, title + 3, title + 4, title + 5
    _clear_panel(sheet, title)

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
            _fill(sheet.range(addr), _TITLE_FILL)

        sheet.range(f"A{r1}:D{r2}").value = [
            ["Strike Price 1", call1[0], "OI (in K)", _to_k(call1[1])],
            ["Strike Price 2", call2[0], "OI (in K)", _to_k(call2[1])],
        ]
        sheet.range(f"F{r1}:I{r2}").value = [
            ["Strike Price 1", put1[0], "OI (in K)", _to_k(put1[1])],
            ["Strike Price 2", put2[0], "OI (in K)", _to_k(put2[1])],
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
                _fill(sheet.range(addr), _LABEL_FILL)
        if "Bullish" in bias:
            _fill(sheet.range(f"B{r3}"), _GREEN_FILL)
        elif "Bearish" in bias:
            _fill(sheet.range(f"B{r3}"), _RED_FILL)
        elif bias == "Neutral":
            _fill(sheet.range(f"B{r3}"), _AMBER_FILL)
        if isinstance(pcr, (int, float)):
            _fill(sheet.range(f"G{r3}"), _GREEN_FILL if pcr > 1.05 else _RED_FILL if pcr < 0.95 else _AMBER_FILL)

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


def _row_from_snapshot(name, oi_snap):
    """Build a dashboard row from a cached option-chain snapshot only."""
    if not oi_snap:
        return None
    rows = oi_snap.get("rows") or []
    spot = oi_snap.get("spot")
    total_call = oi_snap.get("ce_oi")
    total_put = oi_snap.get("pe_oi")
    if total_call is None and total_put is None and not rows:
        return None

    calls, puts = compute_boundary_pairs(rows)
    call_wall = calls[0] if calls else (None, None)
    put_wall = puts[0] if puts else (None, None)
    call_itm, put_itm = compute_itm_ratios(rows, spot, total_call, total_put)
    diff = round(total_call - total_put, 2) if total_call is not None and total_put is not None else None
    return {
        "Time": datetime.now().strftime("%H:%M:%S"),
        "Spot": spot,
        "Value": spot,
        "Total Call OI": total_call,
        "Total Put OI": total_put,
        "Difference": diff,
        "Highest Call OI Value": call_wall[1],
        "Highest Put OI Value": put_wall[1],
        "Call ITM Ratio": call_itm,
        "Put ITM Ratio": put_itm,
        "Highest Call OI Strike": call_wall[0],
        "Highest Put OI Strike": put_wall[0],
        "PCR": oi_snap.get("pcr"),
        "Bias": oi_snap.get("bias") or "N/A",
    }


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
    """Write NIFTY/BANKNIFTY/SENSEX rows in one save.

    Sep 16 2026: removed CRUDEOIL/GOLD/SILVER entirely, per explicit
    request -- this function no longer reads cached commodity snapshots
    or writes commodity sheets at all. Also fixed a real bug found
    while making this change: SENSEX was already present in `results`
    (snapshot_all() in index_tracker.py returns NIFTY/BANKNIFTY/SENSEX
    together) but the old allowed-names check only listed
    ("NIFTY", "BANKNIFTY") plus the commodities -- SENSEX was silently
    dropped here even though it was already being computed upstream.
    """
    book = _get_dashboard_book()
    if book is None:
        return

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
            print(f"[OILiveDashboard] Failed writing {index_name}: {e}")

    if wrote_any:
        try:
            book.save()
        except Exception as e:
            print(f"[OILiveDashboard] Failed saving dashboard: {e}")
