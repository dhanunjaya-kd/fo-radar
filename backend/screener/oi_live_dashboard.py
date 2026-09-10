"""Live OI Excel dashboard writer.

Keeps the live data path unchanged: index_tracker.snapshot_all() passes the
already-fetched NIFTY/BANKNIFTY rows here. No additional Fyers polling is done.

The workbook is intentionally separate from the daily tracker workbook because
xlwings/Excel COM and openpyxl should not fight over the same file.

Layout:
  A:M  = scrolling live table
  bottom = two side-by-side boundary panels, matching the supplied reference
           layout (Open Interest Upper Boundary / Open Interest Lower Boundary)

The first nine table headers retain the reference wording exactly. The final
four columns are additional real fields already produced by index_tracker and
are kept with explicit labels rather than being hidden or discarded.

Important: the reference application's exact formula for its top-table
"Call Boundary (in K)" / "Put Boundary (in K)" values is not available to this
project. We therefore continue to write the project's highest call/put OI at
those labels and do not invent a different formula.
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

# Per-process Excel handles and per-index state.
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


def _to_k(value):
    """Convert raw OI count to thousands with one decimal."""
    return round(value / 1000, 1) if value is not None else None


def compute_itm_ratios(rows, spot, total_ce_oi, total_pe_oi):
    """Return (call_itm_ratio, put_itm_ratio) without guessing missing data."""
    if not rows or spot is None:
        return None, None

    call_itm_oi = sum(
        (r.get("ce", {}) or {}).get("oi", 0) or 0
        for r in rows
        if r.get("strike") is not None and r["strike"] < spot
    )
    put_itm_oi = sum(
        (r.get("pe", {}) or {}).get("oi", 0) or 0
        for r in rows
        if r.get("strike") is not None and r["strike"] > spot
    )

    call_ratio = round(call_itm_oi / total_ce_oi, 3) if total_ce_oi else None
    put_ratio = round(put_itm_oi / total_pe_oi, 3) if total_pe_oi else None
    return call_ratio, put_ratio


def compute_boundary_pairs(rows, top_n=2):
    """Return highest-OI call and put strikes as (strike, oi) pairs."""
    if not rows:
        return [], []

    def _pairs(side):
        pairs = [
            (r.get("strike"), (r.get(side, {}) or {}).get("oi"))
            for r in rows
            if r.get("strike") is not None
            and (r.get(side, {}) or {}).get("oi") is not None
        ]
        pairs.sort(key=lambda p: p[1], reverse=True)
        return pairs[:top_n]

    return _pairs("ce"), _pairs("pe")


def _get_dashboard_book():
    """Open/reuse the Excel workbook; fail soft if Excel is unavailable."""
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
            print("[OILiveDashboard] xlwings not installed; live Excel dashboard disabled.")
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
        print(f"[OILiveDashboard] Could not open dashboard workbook: {e}")
        _app = None
        _book = None
        return None


def _set_cell_fill(cell, fill):
    try:
        cell.color = fill
    except Exception:
        pass


def _apply_row_colors(sheet, row_num, values, previous):
    """Color the current row only; historical rows remain untouched."""
    for i, col in enumerate(_COL_LETTERS):
        if i == 0:
            continue
        try:
            cell = sheet.range(f"{col}{row_num}")
            if i == _BIAS_COL_INDEX:
                bias = values[i] or ""
                if "Bullish" in bias:
                    _set_cell_fill(cell, _GREEN_FILL)
                elif "Bearish" in bias:
                    _set_cell_fill(cell, _RED_FILL)
                continue
            if i == _PCR_COL_INDEX:
                pcr = values[i]
                if pcr is not None:
                    if pcr > 1.3:
                        _set_cell_fill(cell, _GREEN_FILL)
                    elif pcr < 0.7:
                        _set_cell_fill(cell, _RED_FILL)
                continue
            if previous is None:
                continue
            old, new = previous[i], values[i]
            if isinstance(old, (int, float)) and isinstance(new, (int, float)):
                if new > old:
                    _set_cell_fill(cell, _GREEN_FILL)
                elif new < old:
                    _set_cell_fill(cell, _RED_FILL)
        except Exception as e:
            print(f"[OILiveDashboard] Row color skipped for {col}{row_num}: {e}")


def _clear_previous_panel(sheet, index_name):
    """Remove the previous bottom panel before moving it below new rows."""
    old = _last_panel_rows.get(index_name)
    if not old:
        return
    try:
        start, end = old
        sheet.range(f"A{start}:I{end}").clear_contents()
        sheet.range(f"A{start}:I{end}").clear_formats()
    except Exception as e:
        print(f"[OILiveDashboard] Previous panel cleanup skipped: {e}")


def _style_header(sheet):
    try:
        header = sheet.range(f"A1:{_COL_LETTERS[-1]}1")
        header.font.bold = True
        header.color = (0, 0, 0)
        header.api.WrapText = True
        header.row_height = 34
        sheet.freeze_panes.freeze_rows(1)
        # Explicit widths prevent the exact truncation/scientific-notation
        # problems seen in the supplied screenshots.
        widths = {
            "A": 12, "B": 13, "C": 16, "D": 16, "E": 18,
            "F": 20, "G": 20, "H": 11, "I": 11, "J": 20,
            "K": 20, "L": 10, "M": 18,
        }
        for col, width in widths.items():
            sheet.range(f"{col}:{col}").column_width = width
    except Exception as e:
        print(f"[OILiveDashboard] Header styling skipped: {e}")


def _get_or_create_sheet(book, index_name):
    """Create a clean sheet for each index and reset it on a new day/schema."""
    today = datetime.now().strftime("%Y-%m-%d")
    names = [s.name for s in book.sheets]
    exists = index_name in names
    reset = not exists

    if exists:
        sheet = book.sheets[index_name]
        try:
            current = sheet.range("A1").expand("right").value
        except Exception:
            current = None
        if current != _LIVE_LOG_COLUMNS or _sheet_day_seen.get(index_name) != today:
            reset = True

    if not reset:
        return book.sheets[index_name]

    old = book.sheets[index_name] if exists else None
    temp = f"{index_name}_new" if exists else index_name
    sheet = book.sheets.add(temp, after=book.sheets[-1])
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


def _write_boundary_panel(sheet, index_name, row, start_row):
    """Write the current boundary state in the bottom reference-style panel."""
    oi_snap = get_last_oi_snapshot(index_name) or {}
    rows_data = oi_snap.get("rows") or []
    call_pairs, put_pairs = compute_boundary_pairs(rows_data)

    call1 = call_pairs[0] if call_pairs else (None, None)
    call2 = call_pairs[1] if len(call_pairs) > 1 else (None, None)
    put1 = put_pairs[0] if put_pairs else (None, None)
    put2 = put_pairs[1] if len(put_pairs) > 1 else (None, None)

    # Clear the old panel first; this keeps only one current-state panel.
    _clear_previous_panel(sheet, index_name)

    title_row = start_row
    r1 = start_row + 1
    r2 = start_row + 2
    r3 = start_row + 3
    r4 = start_row + 4
    r5 = start_row + 5
    r6 = start_row + 6
    r7 = start_row + 7

    # Upper/call block A:D and lower/put block F:I, with E as a visual gap.
    sheet.range(f"A{title_row}:D{title_row}").merge()
    sheet.range(f"F{title_row}:I{title_row}").merge()
    sheet.range(f"A{title_row}").value = "Open Interest Upper Boundary"
    sheet.range(f"F{title_row}").value = "Open Interest Lower Boundary"

    for cell_addr in (f"A{title_row}", f"F{title_row}"):
        cell = sheet.range(cell_addr)
        cell.font.bold = True
        cell.color = (0, 0, 0)
        cell.api.HorizontalAlignment = -4108

    upper = [
        ("Strike Price 1", call1[0]),
        ("OI (in K)", _to_k(call1[1])),
        ("Strike Price 2", call2[0]),
        ("OI (in K)", _to_k(call2[1])),
        ("Open Interest", row.get("Bias")),
        ("Call Exits", None),
        ("Call ITM", None),
    ]
    lower = [
        ("Strike Price 1", put1[0]),
        ("OI (in K)", _to_k(put1[1])),
        ("Strike Price 2", put2[0]),
        ("OI (in K)", _to_k(put2[1])),
        ("PCR", row.get("PCR")),
        ("Put Exits", None),
        ("Put ITM", None),
    ]

    for offset, ((ul, uv), (ll, lv)) in enumerate(zip(upper, lower), 1):
        rr = start_row + offset
        sheet.range(f"A{rr}").value = ul
        sheet.range(f"B{rr}").value = uv
        sheet.range(f"C{rr}").value = "" if offset in (5, 6, 7) else ""
        sheet.range(f"F{rr}").value = ll
        sheet.range(f"G{rr}").value = lv
        for addr in (f"A{rr}", f"F{rr}"):
            sheet.range(addr).font.bold = True
            _set_cell_fill(sheet.range(addr), (226, 240, 217))

    # Use explicit second value columns for OI where the reference has a
    # label/value pair. This preserves a clean four-column block.
    sheet.range(f"C{r1}").value = "OI (in K)"
    sheet.range(f"D{r1}").value = _to_k(call1[1])
    sheet.range(f"C{r2}").value = ""
    sheet.range(f"D{r2}").value = ""
    sheet.range(f"C{r3}").value = "OI (in K)"
    sheet.range(f"D{r3}").value = _to_k(call2[1])
    sheet.range(f"C{r4}").value = ""
    sheet.range(f"D{r4}").value = ""
    sheet.range(f"C{r5}").value = "Open Interest"
    sheet.range(f"D{r5}").value = row.get("Bias")
    sheet.range(f"C{r6}").value = "Call Exits"
    sheet.range(f"D{r6}").value = "No"
    sheet.range(f"C{r7}").value = "Call ITM"
    spot = row.get("Spot")
    call_itm = spot is not None and call1[0] is not None and call1[0] < spot
    sheet.range(f"D{r7}").value = "Yes" if call_itm else "No"

    sheet.range(f"H{r1}").value = "OI (in K)"
    sheet.range(f"I{r1}").value = _to_k(put1[1])
    sheet.range(f"H{r3}").value = "OI (in K)"
    sheet.range(f"I{r3}").value = _to_k(put2[1])
    sheet.range(f"H{r5}").value = "PCR"
    sheet.range(f"I{r5}").value = row.get("PCR")
    sheet.range(f"H{r6}").value = "Put Exits"
    sheet.range(f"I{r6}").value = "No"
    put_itm = spot is not None and put1[0] is not None and put1[0] > spot
    sheet.range(f"H{r7}").value = "Put ITM"
    sheet.range(f"I{r7}").value = "Yes" if put_itm else "No"

    bias = row.get("Bias") or ""
    if "Bullish" in bias:
        _set_cell_fill(sheet.range(f"D{r5}"), _GREEN_FILL)
    elif "Bearish" in bias:
        _set_cell_fill(sheet.range(f"D{r5}"), _RED_FILL)
    pcr = row.get("PCR")
    if pcr is not None:
        if pcr > 1.3:
            _set_cell_fill(sheet.range(f"I{r5}"), _GREEN_FILL)
        elif pcr < 0.7:
            _set_cell_fill(sheet.range(f"I{r5}"), _RED_FILL)

    # Borders + number formats for the panel.
    panel = sheet.range(f"A{title_row}:I{r7}")
    panel.api.Borders.LineStyle = 1
    sheet.range(f"D{r1}:D{r4}").number_format = "0.0"
    sheet.range(f"I{r1}:I{r3}").number_format = "0.0"
    sheet.range(f"I{r5}").number_format = "0.000"
    sheet.range(f"A{title_row}:I{r7}").api.WrapText = True

    _last_panel_rows[index_name] = (title_row, r7)


def write_live_dashboard(results):
    """Append one row per index and refresh its bottom boundary panel."""
    book = _get_dashboard_book()
    if book is None:
        return

    for index_name, row in (results or {}).items():
        if not row:
            continue
        try:
            sheet = _get_or_create_sheet(book, index_name)
            total_call = row.get("Total Call OI")
            total_put = row.get("Total Put OI")
            oi_diff = (
                round(total_call - total_put, 2)
                if total_call is not None and total_put is not None
                else None
            )
            values = [
                row.get("Time"), row.get("Spot"),
                _to_k(total_call), _to_k(total_put), _to_k(oi_diff),
                _to_k(row.get("Highest Call OI Value")),
                _to_k(row.get("Highest Put OI Value")),
                row.get("Call ITM Ratio"), row.get("Put ITM Ratio"),
                row.get("Highest Call OI Strike"),
                row.get("Highest Put OI Strike"),
                row.get("PCR"), row.get("Bias"),
            ]
            row_num = _next_row.get(index_name, 2)
            sheet.range(f"A{row_num}").value = [values]
            _apply_row_colors(sheet, row_num, values, _prev_values.get(index_name))
            _prev_values[index_name] = values
            _next_row[index_name] = row_num + 1

            _write_boundary_panel(sheet, index_name, row, row_num + 3)

            # Number formats: keep OI readable, prices/strikes numeric, PCR/ITM precise.
            sheet.range(f"B{row_num}:G{row_num}").number_format = "#,##0.0"
            sheet.range(f"H{row_num}:I{row_num}").number_format = "0.000"
            sheet.range(f"J{row_num}:K{row_num}").number_format = "0"
            sheet.range(f"L{row_num}").number_format = "0.000"
        except Exception as e:
            print(f"[OILiveDashboard] Failed writing {index_name}: {e}")

    try:
        book.save()
    except Exception as e:
        print(f"[OILiveDashboard] Failed saving live dashboard: {e}")
