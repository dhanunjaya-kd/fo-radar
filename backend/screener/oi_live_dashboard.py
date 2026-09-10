"""Live OI Excel dashboard writer.

Uses only the NIFTY/BANKNIFTY snapshot data already fetched by
index_tracker.snapshot_all(); this module makes no extra Fyers requests.

Workbook layout is intentionally close to the supplied NSE Option Chain
Analyzer reference:
  A:M  scrolling live table
  A:D  Open Interest Upper Boundary (call side)
  F:I  Open Interest Lower Boundary (put side)
  E    visual spacer

The first nine table headers use the reference wording exactly. The remaining
four columns are existing project fields retained as clearly labelled bonus
data. The reference tool's exact formula for its top-table Boundary numbers is
not available, so the existing highest call/put OI calculation is preserved.
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

_app = None
_book = None
_warned_once = False
_next_row = {}
_sheet_day_seen = {}
_prev_values = {}
_prev_boundary_oi = {}
_last_panel_rows = {}

_GREEN_FILL = (198, 239, 206)
_RED_FILL = (255, 199, 206)
_AMBER_FILL = (255, 235, 156)
_LABEL_FILL = (226, 240, 217)
_TITLE_FILL = (217, 234, 247)


def _to_k(value):
    return round(value / 1000, 1) if value is not None else None


def compute_itm_ratios(rows, spot, total_ce_oi, total_pe_oi):
    """Return call/put ITM OI ratios; return None when required data is missing."""
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
    """Return the highest-OI call and put strikes as (strike, oi) pairs."""
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
        header.color = (0, 0, 0)
        header.api.WrapText = True
        header.row_height = 36
        widths = {
            "A": 12, "B": 13, "C": 16, "D": 16, "E": 18,
            "F": 20, "G": 20, "H": 11, "I": 11, "J": 20,
            "K": 20, "L": 10, "M": 18,
        }
        for col, width in widths.items():
            sheet.range(f"{col}:{col}").column_width = width
    except Exception as e:
        print(f"[OILiveDashboard] Header formatting skipped: {e}")


def _apply_row_colors(sheet, row_num, values, previous):
    for i, col in enumerate(_COL_LETTERS):
        if i == 0:
            continue
        try:
            cell = sheet.range(f"{col}{row_num}")
            if i == _BIAS_COL_INDEX:
                bias = values[i] or ""
                if "Bullish" in bias:
                    _fill(cell, _GREEN_FILL)
                elif "Bearish" in bias:
                    _fill(cell, _RED_FILL)
            elif i == _PCR_COL_INDEX:
                pcr = values[i]
                if pcr is not None:
                    if pcr > 1.3:
                        _fill(cell, _GREEN_FILL)
                    elif pcr < 0.7:
                        _fill(cell, _RED_FILL)
            elif previous is not None:
                old, new = previous[i], values[i]
                if isinstance(old, (int, float)) and isinstance(new, (int, float)):
                    if new > old:
                        _fill(cell, _GREEN_FILL)
                    elif new < old:
                        _fill(cell, _RED_FILL)
        except Exception as e:
            print(f"[OILiveDashboard] Colour skipped for {col}{row_num}: {e}")


def _prepare_sheet(book, index_name):
    """Use a fresh sheet when the schema/day changes to prevent stale formats."""
    today = datetime.now().strftime("%Y-%m-%d")
    exists = index_name in [s.name for s in book.sheets]
    reset = not exists

    if exists:
        sheet = book.sheets[index_name]
        try:
            current_header = sheet.range("A1").expand("right").value
        except Exception:
            current_header = None
        reset = current_header != _LIVE_LOG_COLUMNS or _sheet_day_seen.get(index_name) != today

    if not reset:
        return book.sheets[index_name]

    old = book.sheets[index_name] if exists else None
    temp_name = f"{index_name}_new" if exists else index_name
    sheet = book.sheets.add(temp_name, after=book.sheets[-1])
    if old is not None:
        old.delete()
        sheet.name = index_name

    sheet.range("A1").value = [_LIVE_LOG_COLUMNS]
    _style_header(sheet)
    _next_row[index_name] = 2
    _sheet_day_seen[index_name] = today
    _prev_values.pop(index_name, None)
    _prev_boundary_oi.pop(index_name, None)
    _last_panel_rows.pop(index_name, None)
    return sheet


def _clear_previous_panel(sheet, index_name):
    old = _last_panel_rows.get(index_name)
    if not old:
        return
    try:
        start, end = old
        sheet.range(f"A{start}:I{end}").clear_contents()
        sheet.range(f"A{start}:I{end}").clear_formats()
    except Exception as e:
        print(f"[OILiveDashboard] Previous panel cleanup skipped: {e}")


def _write_boundary_panel(sheet, index_name, row, start_row):
    """Write the reference-style bottom panel: title + two strikes + status rows."""
    oi_snap = get_last_oi_snapshot(index_name) or {}
    rows = oi_snap.get("rows") or []
    calls, puts = compute_boundary_pairs(rows)

    call1 = calls[0] if calls else (None, None)
    call2 = calls[1] if len(calls) > 1 else (None, None)
    put1 = puts[0] if puts else (None, None)
    put2 = puts[1] if len(puts) > 1 else (None, None)

    _clear_previous_panel(sheet, index_name)

    title = start_row
    r1, r2, r3, r4, r5 = title + 1, title + 2, title + 3, title + 4, title + 5

    for rng, text in (
        (f"A{title}:D{title}", "Open Interest Upper Boundary"),
        (f"F{title}:I{title}", "Open Interest Lower Boundary"),
    ):
        sheet.range(rng).merge()
        first = rng.split(":")[0]
        sheet.range(first).value = text
        sheet.range(first).font.bold = True
        sheet.range(first).api.HorizontalAlignment = -4108
        _fill(sheet.range(first), _TITLE_FILL)

    # Upper boundary / call side.
    upper_rows = [
        (r1, "Strike Price 1", call1[0], "OI (in K)", _to_k(call1[1])),
        (r2, "Strike Price 2", call2[0], "OI (in K)", _to_k(call2[1])),
    ]
    for rr, label1, value1, label2, value2 in upper_rows:
        sheet.range(f"A{rr}").value = label1
        sheet.range(f"B{rr}").value = value1
        sheet.range(f"C{rr}").value = label2
        sheet.range(f"D{rr}").value = value2
        for addr in (f"A{rr}", f"C{rr}"):
            sheet.range(addr).font.bold = True
            _fill(sheet.range(addr), _LABEL_FILL)

    bias = row.get("Bias") or "N/A"
    sheet.range(f"A{r3}").value = "Open Interest"
    sheet.range(f"B{r3}:D{r3}").merge()
    sheet.range(f"B{r3}").value = bias
    sheet.range(f"A{r4}").value = "Call Exits"
    sheet.range(f"B{r4}:D{r4}").merge()
    sheet.range(f"B{r4}").value = "No"
    spot = row.get("Spot")
    call_itm = spot is not None and call1[0] is not None and call1[0] < spot
    sheet.range(f"A{r5}").value = "Call ITM"
    sheet.range(f"B{r5}:D{r5}").merge()
    sheet.range(f"B{r5}").value = "Yes" if call_itm else "No"

    # Lower boundary / put side.
    lower_rows = [
        (r1, "Strike Price 1", put1[0], "OI (in K)", _to_k(put1[1])),
        (r2, "Strike Price 2", put2[0], "OI (in K)", _to_k(put2[1])),
    ]
    for rr, label1, value1, label2, value2 in lower_rows:
        sheet.range(f"F{rr}").value = label1
        sheet.range(f"G{rr}").value = value1
        sheet.range(f"H{rr}").value = label2
        sheet.range(f"I{rr}").value = value2
        for addr in (f"F{rr}", f"H{rr}"):
            sheet.range(addr).font.bold = True
            _fill(sheet.range(addr), _LABEL_FILL)

    pcr = row.get("PCR")
    sheet.range(f"F{r3}").value = "PCR"
    sheet.range(f"G{r3}:I{r3}").merge()
    sheet.range(f"G{r3}").value = pcr
    sheet.range(f"F{r4}").value = "Put Exits"
    sheet.range(f"G{r4}:I{r4}").merge()
    sheet.range(f"G{r4}").value = "No"
    put_itm = spot is not None and put1[0] is not None and put1[0] > spot
    sheet.range(f"F{r5}").value = "Put ITM"
    sheet.range(f"G{r5}:I{r5}").merge()
    sheet.range(f"G{r5}").value = "Yes" if put_itm else "No"

    for addr in (f"A{r3}", f"A{r4}", f"A{r5}", f"F{r3}", f"F{r4}", f"F{r5}"):
        sheet.range(addr).font.bold = True
        _fill(sheet.range(addr), _LABEL_FILL)

    if "Bullish" in bias:
        _fill(sheet.range(f"B{r3}"), _GREEN_FILL)
    elif "Bearish" in bias:
        _fill(sheet.range(f"B{r3}"), _RED_FILL)
    if pcr is not None:
        if pcr > 1.3:
            _fill(sheet.range(f"G{r3}"), _GREEN_FILL)
        elif pcr < 0.7:
            _fill(sheet.range(f"G{r3}"), _RED_FILL)

    panel = sheet.range(f"A{title}:I{r5}")
    panel.api.Borders.LineStyle = 1
    panel.api.WrapText = True
    sheet.range(f"D{r1}:D{r2}").number_format = "0.0"
    sheet.range(f"I{r1}:I{r2}").number_format = "0.0"
    sheet.range(f"G{r3}").number_format = "0.000"

    _last_panel_rows[index_name] = (title, r5)


def write_live_dashboard(results):
    """Append one row per index and refresh its current boundary panel."""
    book = _get_dashboard_book()
    if book is None:
        return

    for index_name, row in (results or {}).items():
        if not row:
            continue
        try:
            sheet = _prepare_sheet(book, index_name)
            total_call = row.get("Total Call OI")
            total_put = row.get("Total Put OI")
            diff = round(total_call - total_put, 2) if total_call is not None and total_put is not None else None
            values = [
                row.get("Time"), row.get("Spot"), _to_k(total_call), _to_k(total_put),
                _to_k(diff), _to_k(row.get("Highest Call OI Value")),
                _to_k(row.get("Highest Put OI Value")), row.get("Call ITM Ratio"),
                row.get("Put ITM Ratio"), row.get("Highest Call OI Strike"),
                row.get("Highest Put OI Strike"), row.get("PCR"), row.get("Bias"),
            ]
            row_num = _next_row.get(index_name, 2)
            sheet.range(f"A{row_num}").value = [values]
            _apply_row_colors(sheet, row_num, values, _prev_values.get(index_name))
            _prev_values[index_name] = values
            _next_row[index_name] = row_num + 1

            _write_boundary_panel(sheet, index_name, row, row_num + 3)
            sheet.range(f"B{row_num}:G{row_num}").number_format = "#,##0.0"
            sheet.range(f"H{row_num}:I{row_num}").number_format = "0.000"
            sheet.range(f"J{row_num}:K{row_num}").number_format = "0"
            sheet.range(f"L{row_num}").number_format = "0.000"
        except Exception as e:
            print(f"[OILiveDashboard] Failed writing {index_name}: {e}")

    try:
        book.save()
    except Exception as e:
        print(f"[OILiveDashboard] Failed saving dashboard: {e}")
