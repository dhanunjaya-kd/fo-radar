"""Live OI Excel dashboard writer.

Uses only the NIFTY/BANKNIFTY snapshot data already fetched by
index_tracker.snapshot_all(); this module makes no extra Fyers requests.

The workbook is a live dashboard, deliberately modelled on the supplied
NSE Option Chain Analyzer screenshot: a clearly labelled OI table followed by
an Open Interest Upper Boundary / Lower Boundary panel. The existing project's
OI calculations are retained; this module changes presentation, not trading logic.
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
_PRICE_COL_INDEX = _LIVE_LOG_COLUMNS.index("Value")  # this is the index's own spot price -- the one column Change 3 keeps directional colour on

# The panel now sits immediately below the last live row. It moves down by one
# row for every new sample, so there are no artificial blank rows between samples
# and the boundary panel.
_FIRST_PANEL_ROW = 3

_app = None
_book = None
_warned_once = False
_next_row = {}
_sheet_day_seen = {}
_prev_values = {}
_panel_ready = set()
_panel_start_rows = {}

_GREEN_FILL = (198, 239, 206)
_RED_FILL = (255, 199, 206)
_AMBER_FILL = (255, 235, 156)
_HEADER_FILL = (242, 242, 242)
_HEADER_FONT = (0, 0, 0)
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
    """Make the table header readable and close to the reference screenshot."""
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
    """Colour cells according to movement, while retaining the reference look.

    Sep 10 2026: Change 3 -- only Price (this index's own spot move) and
    Bias keep directional green/red. PCR and every OI-derived numeric
    column (Call/Put OI sums, their difference, boundary OI values, ITM
    ratios, boundary strikes) previously got the SAME increase=green/
    decrease=red treatment as Price, via the old generic 'any numeric
    column that changed' branch below. That's the exact misleading
    pattern being fixed: a rising Call OI or a rising PCR isn't
    inherently bullish the way a rising price is -- see this project's
    own options_analytics.py four-quadrant reasoning (OI direction only
    means something combined with price direction, never alone). Those
    columns now get no fill at all, same "keep readable and neutral"
    treatment the task calls for -- the real numbers are unchanged,
    only the implied direction is removed.
    """
    for i, col in enumerate(_COL_LETTERS):
        try:
            cell = sheet.range(f"{col}{row_num}")
            cell.api.HorizontalAlignment = -4108
            cell.api.VerticalAlignment = -4108
            cell.api.Borders.LineStyle = 1

            if i == _BIAS_COL_INDEX:
                bias = values[i] or ""
                if "Bullish" in bias:
                    _fill(cell, _GREEN_FILL)
                elif "Bearish" in bias:
                    _fill(cell, _RED_FILL)
            elif i == _PRICE_COL_INDEX and previous is not None:
                old, new = previous[i], values[i]
                if isinstance(old, (int, float)) and isinstance(new, (int, float)):
                    if new > old:
                        _fill(cell, _GREEN_FILL)
                    elif new < old:
                        _fill(cell, _RED_FILL)
            # PCR and every other numeric column: deliberately no
            # directional fill -- neutral/default, per Change 3.
        except Exception as e:
            print(f"[OILiveDashboard] Row formatting skipped for {col}{row_num}: {e}")


def _prepare_sheet(book, index_name):
    """Prepare a clean daily sheet and place the panel immediately after live rows.

    Sep 10 2026: real fix for TWO confirmed, connected bugs:

    (1) OI EXCEL SAME-DAY RESTART: _sheet_day_seen was pure in-memory
    state. On any backend restart it's empty again, so the OLD check
    (_sheet_day_seen.get(index_name) != today) was True unconditionally
    on the very first call after ANY restart -- wiping today's real,
    already-written snapshot rows even on a same-day restart, not just
    a genuine new day. Confirmed by reading the code directly, not
    assumed.

    (2) OI DASHBOARD PANEL COM ERROR ("Exception occurred",
    -2147352567): _write_boundary_panel()'s merge-setup block gates on
    `index_name not in _panel_ready` -- also pure in-memory, also empty
    after a restart. Once (1) is fixed and the sheet is genuinely
    preserved across a restart, the panel's cells are STILL physically
    merged from before the restart -- but _panel_ready wouldn't know
    that, so it would try to .merge() already-merged/overlapping cells
    every single cycle. That's exactly the class of invalid-operation
    error this HRESULT represents. Fixing (1) properly -- restoring
    _panel_ready along with everything else -- removes the repeated
    re-merge attempt entirely, which is the actual fix for (2). Not
    two separate patches; one root cause.

    Neither _next_row/_panel_start_rows/_panel_ready/_sheet_day_seen
    persists anywhere on disk, so "is this really today's data" is
    inferred from the workbook FILE's own last-modified date (this
    module only ever saves it during a live write gated by
    is_mcx_hours(), so its mtime is a genuine "last real write"
    signal) -- not guessed, and verified against the sheet's own
    content (the panel's known title text) before trusting it; any
    mismatch falls back to the original safe behavior (reset) rather
    than risk writing to a miscalculated row.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    exists = index_name in [s.name for s in book.sheets]
    reset = not exists

    if exists:
        sheet = book.sheets[index_name]
        try:
            current_header = sheet.range("A1").expand("right").value
        except Exception:
            current_header = None
        already_seen_this_run = _sheet_day_seen.get(index_name) == today
        reset = current_header != _LIVE_LOG_COLUMNS

        if not reset and not already_seen_this_run:
            # First call after a restart (or first call ever this
            # process) for a sheet that already has today's real
            # header. Figure out honestly whether the CONTENT is
            # actually from today before trusting it.
            restored = False
            try:
                file_mtime_date = datetime.fromtimestamp(os.path.getmtime(DASHBOARD_PATH)).strftime("%Y-%m-%d")
                if file_mtime_date == today:
                    last_row = sheet.used_range.last_cell.row
                    candidate_panel_row = last_row - 5  # panel is exactly 6 rows: title..title+5
                    title_value = sheet.range(f"A{candidate_panel_row}").value
                    if candidate_panel_row >= _FIRST_PANEL_ROW and title_value == "Open Interest Upper Boundary":
                        _next_row[index_name] = candidate_panel_row
                        _panel_start_rows[index_name] = candidate_panel_row
                        _panel_ready.add(index_name)
                        _sheet_day_seen[index_name] = today
                        restored = True
            except Exception as e:
                print(f"[OILiveDashboard] Could not verify same-day state for {index_name}, will reset: {e}")
            if not restored:
                reset = True
            else:
                reset = False
        elif not reset:
            reset = False

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
    _panel_ready.discard(index_name)
    _panel_start_rows[index_name] = _FIRST_PANEL_ROW
    return sheet


def _style_panel_labels(sheet, title, r1, r2, r3, r4, r5):
    for rr in (r1, r2, r3, r4, r5):
        for addr in (f"A{rr}", f"C{rr}", f"F{rr}", f"H{rr}"):
            sheet.range(addr).font.bold = True
            _fill(sheet.range(addr), _LABEL_FILL)
    for addr in (f"A{r3}", f"A{r4}", f"A{r5}", f"F{r3}", f"F{r4}", f"F{r5}"):
        sheet.range(addr).font.bold = True
        _fill(sheet.range(addr), _LABEL_FILL)
    panel = sheet.range(f"A{title}:I{r5}")
    panel.api.Borders.LineStyle = 1
    panel.api.VerticalAlignment = -4108
    panel.api.WrapText = True


def _write_boundary_panel(sheet, index_name, row):
    """Update the boundary panel in-place at its current dynamic row."""
    oi_snap = get_last_oi_snapshot(index_name) or {}
    rows = oi_snap.get("rows") or []
    calls, puts = compute_boundary_pairs(rows)

    call1 = calls[0] if calls else (None, None)
    call2 = calls[1] if len(calls) > 1 else (None, None)
    put1 = puts[0] if puts else (None, None)
    put2 = puts[1] if len(puts) > 1 else (None, None)

    title = _panel_start_rows.get(index_name, _FIRST_PANEL_ROW)
    r1, r2, r3, r4, r5 = title + 1, title + 2, title + 3, title + 4, title + 5

    if index_name not in _panel_ready:
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

            _style_panel_labels(sheet, title, r1, r2, r3, r4, r5)
            sheet.range(f"D{r1}:D{r2}").number_format = "0.0"
            sheet.range(f"I{r1}:I{r2}").number_format = "0.0"
            sheet.range(f"G{r3}").number_format = "0.000"
            for rr in range(title, r5 + 1):
                sheet.range(f"{rr}:{rr}").row_height = 24
            _panel_ready.add(index_name)
        except Exception as e:
            print(f"[OILiveDashboard] Panel layout setup skipped: {e}")
            return

    sheet.range(f"A{r1}:D{r2}").value = [
        ["Strike Price 1", call1[0], "OI (in K)", _to_k(call1[1])],
        ["Strike Price 2", call2[0], "OI (in K)", _to_k(call2[1])],
    ]
    bias = row.get("Bias") or "N/A"
    sheet.range(f"A{r3}").value = "Open Interest"
    sheet.range(f"B{r3}").value = bias
    sheet.range(f"A{r4}").value = "Call Exits"
    sheet.range(f"B{r4}").value = "No"
    spot = row.get("Spot")
    sheet.range(f"A{r5}").value = "Call ITM"
    sheet.range(f"B{r5}").value = "Yes" if spot is not None and call1[0] is not None and call1[0] < spot else "No"

    sheet.range(f"F{r1}:I{r2}").value = [
        ["Strike Price 1", put1[0], "OI (in K)", _to_k(put1[1])],
        ["Strike Price 2", put2[0], "OI (in K)", _to_k(put2[1])],
    ]
    pcr = row.get("PCR")
    sheet.range(f"F{r3}").value = "PCR"
    sheet.range(f"G{r3}").value = pcr
    sheet.range(f"F{r4}").value = "Put Exits"
    sheet.range(f"G{r4}").value = "No"
    sheet.range(f"F{r5}").value = "Put ITM"
    put_itm = spot is not None and put1[0] is not None and put1[0] > spot
    sheet.range(f"G{r5}").value = "Yes" if put_itm else "No"

    for addr in (f"A{r1}", f"C{r1}", f"A{r2}", f"C{r2}", f"A{r3}", f"A{r4}", f"A{r5}",
                 f"F{r1}", f"H{r1}", f"F{r2}", f"H{r2}", f"F{r3}", f"F{r4}", f"F{r5}"):
        _fill(sheet.range(addr), _LABEL_FILL)

    # Sep 10 2026: Change 3 -- Bias keeps its directional colour
    # (Bullish/Bearish), but Neutral now clears to no-fill instead of
    # amber -- the task's own wording is "Neutral -> neutral/default",
    # not a third implied-meaning colour. PCR no longer gets ANY
    # directional fill here, same reasoning as _style_live_row() above:
    # no clearly-justified PCR-direction interpretation is documented
    # in this file, so it stays neutral rather than implying one.
    _fill(sheet.range(f"B{r3}"), _GREEN_FILL if "Bullish" in bias else _RED_FILL if "Bearish" in bias else None)


def _write_dashboard_row(sheet, index_name, values):
    """Append one live sample immediately before the boundary panel."""
    current_rows = max(0, _next_row.get(index_name, 2) - 2)

    if current_rows == 0:
        row_num = 2
    else:
        panel_row = _panel_start_rows.get(index_name, _FIRST_PANEL_ROW)
        panel_height = 6  # title row + r1..r5 -- see _write_boundary_panel()
        new_panel_row = panel_row + 1
        try:
            # Sep 10 2026: real perf fix -- EntireRow.Insert() here was
            # shifting the ENTIRE row across the whole workbook on every
            # single live update (this is exactly what made Excel
            # visibly slow down as rows accumulated through the day).
            # Replaced with a targeted Cut of just the panel's own small
            # block (already merged/formatted) down by one row -- a
            # much cheaper, localized move that carries the existing
            # merges along automatically (nothing needs re-merging),
            # and leaves every historical row above completely
            # untouched. Same "move, don't insert" principle a manual
            # drag-down-by-one-row in Excel already uses.
            source = sheet.range(f"A{panel_row}:M{panel_row + panel_height - 1}")
            dest = sheet.range(f"A{new_panel_row}:M{new_panel_row + panel_height - 1}")
            source.api.Cut(dest.api)
        except Exception as e:
            print(f"[OILiveDashboard] Could not relocate boundary panel: {e}")
            return None
        row_num = panel_row  # the row the panel just vacated becomes the new data row
        _panel_start_rows[index_name] = new_panel_row

    sheet.range(f"A{row_num}:M{row_num}").value = [values]
    _style_live_row(sheet, row_num, values, _prev_values.get(index_name))
    _prev_values[index_name] = values
    _next_row[index_name] = _next_row.get(index_name, 2) + 1
    return row_num


def write_live_dashboard(results):
    """Append live OI data and keep the boundary panel directly below all live rows."""
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

            if index_name not in _panel_ready:
                _write_boundary_panel(sheet, index_name, row)
            row_num = _write_dashboard_row(sheet, index_name, values)
            if row_num is None:
                continue

            sheet.range(f"B{row_num}:G{row_num}").number_format = "#,##0.0"
            sheet.range(f"H{row_num}:I{row_num}").number_format = "0.000"
            sheet.range(f"J{row_num}:K{row_num}").number_format = "0"
            sheet.range(f"L{row_num}").number_format = "0.000"

            _write_boundary_panel(sheet, index_name, row)
        except Exception as e:
            print(f"[OILiveDashboard] Failed writing {index_name}: {e}")

    try:
        book.save()
    except Exception as e:
        print(f"[OILiveDashboard] Failed saving dashboard: {e}")
