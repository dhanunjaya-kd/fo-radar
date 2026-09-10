"""
screener/oi_live_dashboard.py

Adds two things on top of index_tracker.py's existing snapshot_index()/
snapshot_all(), without changing how those already work:

1. compute_itm_ratios() -- a metric index_tracker.py doesn't have yet:
   what fraction of each side's chain-wide OI (oi.get('ce_oi')/oi.get('pe_oi'))
   sits at strikes already in-the-money right now. Pure function, no I/O
   -- tested standalone against synthetic rows before this file was
   written (call ratio 0.135, put ratio 0.31 on a 5-strike synthetic
   chain, edge cases -- missing spot, empty rows, zero total -- all
   return None instead of a fake 0).

   REAL CAVEAT, not yet confirmed live: this sums OI only across the
   `rows` list get_option_analytics(..., strikecount=10) returns. If
   that's a narrower strike window than whatever options_analytics.py
   uses internally to compute oi['ce_oi']/oi['pe_oi'] (the chain-wide
   totals "Total Call OI"/"Total Put OI" already log), the ratio will
   under-count and read artificially low -- same "confirmed live, not
   guessed" discipline the rest of this project holds itself to.
   Directionally (rising/falling over the day) should still be
   meaningful either way. Worth one check against options_analytics.py
   (not available when this was written) before trusting the absolute
   numbers.

2. write_live_dashboard() -- pushes the SAME row dict snapshot_index()
   already builds into a live-visible Excel window via xlwings, instead
   of only appending to the openpyxl-managed daily log. Deliberately a
   SEPARATE small workbook (signal_logs/oi_live_dashboard.xlsx), never
   the same file _today_path()/_get_workbook()/_atomic_save() manage --
   xlwings (COM, keeps Excel open) and openpyxl (file-level read-modify-
   save-close) fighting over one file would be a real lock-collision
   risk given this project's actual history with Windows file-lock
   issues (see index_tracker.py's own _atomic_save()).

   Sep 10 2026: switched from a fixed Field/Value layout (overwritten
   every cycle) to a header + APPENDED row per cycle -- same scrolling-
   table shape as the reference NSE-Option-Chain-Analyzer screenshot
   this whole feature was modeled on, so trend-by-eye (is the boundary
   strike shifting, is OI Diff climbing) actually works, not just "what's
   true right now." Row position is tracked in a Python-side dict
   (_next_row) rather than re-derived from Excel's used-range each
   cycle -- more reliable than xlwings' .end()/current_region, which
   can behave unexpectedly around gaps or fresh sheets.

   Grows across the day (~60s cadence -> a few hundred rows by close,
   trivial for Excel), then gets cleared back to just the header on the
   first write of a NEW calendar day -- the file persists across
   restarts even though _next_row/_sheet_day_seen (in-memory) don't, so
   this only actually fires once, right after each morning's fresh
   startup. Same "no explicit day reset, relies on the daily restart"
   convention as several of index_tracker.py's own caches.

   Fails soft everywhere: no Excel installed/open, sheet not reachable,
   any write error -- logs once and returns, never raises. Must not be
   able to take down the scan cycle that calls it.

   Requires `pip install xlwings` (pulls in pywin32 automatically on
   Windows) -- not in requirements.txt yet.

Wiring into index_tracker.py (3 small edits, see chat for exact
before/after text):
  1. COLUMNS: add "Call ITM Ratio", "Put ITM Ratio" after the existing
     "Highest Call OI Strike"/"Highest Call OI Value" pair.
  2. snapshot_index(): after highest_call_value is computed, call
     compute_itm_ratios(rows, oi.get("spot"), oi.get("ce_oi"), oi.get("pe_oi"))
     and add the two results to the `row` dict under the same two keys.
  3. snapshot_all(): call write_live_dashboard(results) right before
     `return results`, wrapped in try/except so a dashboard failure
     never breaks the real return value the rest of the app depends on.
"""
import os
from datetime import datetime

try:
    import xlwings as xw
    XLWINGS_AVAILABLE = True
except ImportError:
    XLWINGS_AVAILABLE = False

from .index_tracker import LOG_DIR

DASHBOARD_PATH = os.path.join(LOG_DIR, "oi_live_dashboard.xlsx")

# Header row for the append-log layout -- one row per cycle underneath
# this, same column order as the reference tool's scrolling table.
_LIVE_LOG_COLUMNS = [
    "Time", "Spot", "Total Call OI", "Total Put OI", "OI Diff",
    "Call Boundary Strike", "Call Boundary OI",
    "Put Boundary Strike", "Put Boundary OI",
    "Call ITM Ratio", "Put ITM Ratio", "PCR", "Bias",
]

_app = None   # cached xlwings App -- init once per process, never reopened every cycle
_book = None  # cached workbook handle
_warned_once = False
_next_row = {}         # {index_name: int} -- next empty row to write to
_sheet_day_seen = {}   # {index_name: 'YYYY-MM-DD'} -- last calendar day this process appended a row for that sheet
_prev_values = {}      # {index_name: [values from the last written row]} -- drives up/down coloring

_GREEN_FILL = (198, 239, 206)  # Excel's own standard "Good" green
_RED_FILL = (255, 199, 206)    # Excel's own standard "Bad" red
_COL_LETTERS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M"]
_PCR_COL_INDEX = _LIVE_LOG_COLUMNS.index("PCR")
_BIAS_COL_INDEX = _LIVE_LOG_COLUMNS.index("Bias")


def compute_itm_ratios(rows, spot, total_ce_oi, total_pe_oi):
    """Fraction of each side's chain-wide OI already in-the-money right
    now. Calls are ITM when strike < spot; puts are ITM when strike >
    spot. Returns (call_itm_ratio, put_itm_ratio) -- either is None if
    a required input is missing, never a guessed 0.

    See this module's docstring for the real caveat about `rows`
    coverage vs total_ce_oi/total_pe_oi's own strike population.
    """
    if not rows or spot is None:
        return None, None

    call_itm_oi = sum(
        (r.get("ce", {}) or {}).get("oi", 0) or 0
        for r in rows if r.get("strike") is not None and r["strike"] < spot
    )
    put_itm_oi = sum(
        (r.get("pe", {}) or {}).get("oi", 0) or 0
        for r in rows if r.get("strike") is not None and r["strike"] > spot
    )

    call_ratio = round(call_itm_oi / total_ce_oi, 3) if total_ce_oi else None
    put_ratio = round(put_itm_oi / total_pe_oi, 3) if total_pe_oi else None
    return call_ratio, put_ratio


def _get_dashboard_book():
    """Cached: opens Excel + the dashboard workbook once per process,
    reuses the same handle every cycle after. Returns None (not an
    exception) on any failure -- callers must treat that as "can't
    write right now," same convention as index_tracker.py's own fetch
    failures (e.g. snapshot_index() returning None on a Fyers error)."""
    global _app, _book, _warned_once
    if _book is not None:
        try:
            _book.sheets[0].name  # cheap liveness check -- throws if the user closed Excel
            return _book
        except Exception:
            _app = None
            _book = None  # fall through and reopen below

    if not XLWINGS_AVAILABLE:
        if not _warned_once:
            print("[OILiveDashboard] xlwings not installed -- live dashboard disabled, daily log unaffected. `pip install xlwings` to enable.")
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
        print(f"[OILiveDashboard] Could not open live dashboard workbook: {e}")
        _app = None
        _book = None
        return None


def _style_header(sheet):
    """Bold + light gray fill on the header row -- cosmetic only, wrapped
    like everything else so a styling failure never blocks real data
    from being written."""
    try:
        header_range = sheet.range(f"A1:{_COL_LETTERS[-1]}1")
        header_range.font.bold = True
        header_range.color = (242, 242, 242)
    except Exception as e:
        print(f"[OILiveDashboard] Header styling skipped: {e}")


def _apply_row_colors(sheet, r, values, prev_values):
    """Colors the row just written -- never touches any earlier row, so
    colors accumulate down the sheet the same way the reference tool's
    do. Two different rules depending on column:

    - PCR: colored by his own stated thresholds (Bullish >1.3, Bearish
      <0.7, from nse-scanner.md/_derive_bias's PCR vote) rather than
      up/down tick -- a threshold he's already defined is a more
      meaningful read than "did it move since last cycle."
    - Bias: colored by its own label (Bullish/Bearish substring) --
      it's already a category, not a number to compare.
    - Everything else numeric: green if it rose vs the immediately
      previous cycle, red if it fell, left uncolored if unchanged or
      if there's no previous row yet (first row of the day)."""
    for i, col in enumerate(_COL_LETTERS):
        if i == 0:  # Time -- never colored
            continue
        cell = sheet.range(f"{col}{r}")
        try:
            if i == _BIAS_COL_INDEX:
                bias = values[i] or ""
                if "Bullish" in bias:
                    cell.color = _GREEN_FILL
                elif "Bearish" in bias:
                    cell.color = _RED_FILL
                continue
            if i == _PCR_COL_INDEX:
                pcr = values[i]
                if pcr is not None:
                    if pcr > 1.3:
                        cell.color = _GREEN_FILL
                    elif pcr < 0.7:
                        cell.color = _RED_FILL
                continue
            if prev_values is None:
                continue
            old, new = prev_values[i], values[i]
            if old is None or new is None:
                continue
            if new > old:
                cell.color = _GREEN_FILL
            elif new < old:
                cell.color = _RED_FILL
        except Exception as e:
            print(f"[OILiveDashboard] Coloring {col}{r} skipped: {e}")


def _get_or_create_sheet(book, index_name):
    """Returns a sheet whose header row is guaranteed to match
    _LIVE_LOG_COLUMNS exactly and whose data starts fresh for today.

    Real bug found Sep 10 (live, in his actual workbook): the earlier
    version's in-place clear_contents() removes cell VALUES but leaves
    NUMBER FORMATTING behind. The old fixed-cell layout had written a
    Time value into B2; clearing the value later didn't clear that
    Time format, so the new code's raw Spot price landing in that same
    cell displayed as a nonsense time ("01:12:00") instead of a price
    -- and row 1 still read "Field"/"Value" because the header was
    only ever written on a BRAND-NEW sheet, never re-checked against
    an existing one.

    Fix: never clear-in-place. If the sheet doesn't exist, or its row-1
    header doesn't exactly match today's _LIVE_LOG_COLUMNS (catches
    both a leftover old-schema sheet like this one, and a new
    calendar day), DELETE the sheet and add a fresh one instead. A
    freshly added sheet's cells start at Excel's true default format,
    so this whole bug class can't recur regardless of what schema
    lived there before.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    existing = index_name in [s.name for s in book.sheets]

    needs_reset = not existing
    if existing:
        sheet = book.sheets[index_name]
        try:
            current_header = sheet.range("A1").expand("right").value
        except Exception:
            current_header = None
        if current_header != _LIVE_LOG_COLUMNS:
            needs_reset = True
        elif _sheet_day_seen.get(index_name) != today_str:
            needs_reset = True

    if not needs_reset:
        return book.sheets[index_name]

    old_sheet = book.sheets[index_name] if existing else None
    # Add the new sheet under a temp name FIRST, then delete the old one
    # -- avoids both "can't delete the workbook's last remaining sheet"
    # and "duplicate sheet name" if done in the other order.
    temp_name = f"{index_name}_new" if existing else index_name
    sheet = book.sheets.add(temp_name, after=book.sheets[-1])
    if old_sheet is not None:
        old_sheet.delete()
        sheet.name = index_name

    sheet.range("A1").value = [_LIVE_LOG_COLUMNS]
    _style_header(sheet)
    _next_row[index_name] = 2
    _sheet_day_seen[index_name] = today_str
    _prev_values.pop(index_name, None)
    return sheet


def write_live_dashboard(results):
    """results: the same {'NIFTY': row_or_None, 'BANKNIFTY': row_or_None}
    dict snapshot_all() already returns -- no new Fyers fetch, just a
    second write of data already in hand, appended as one new row per
    index per cycle. Call from the end of snapshot_all(). Never raises
    -- any failure here must not affect the caller's return value."""
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
                if total_call is not None and total_put is not None else None
            )
            values = [
                row.get("Time"), row.get("Spot"),
                total_call, total_put, oi_diff,
                row.get("Highest Call OI Strike"), row.get("Highest Call OI Value"),
                row.get("Highest Put OI Strike"), row.get("Highest Put OI Value"),
                row.get("Call ITM Ratio"), row.get("Put ITM Ratio"),
                row.get("PCR"), row.get("Bias"),
            ]
            r = _next_row.get(index_name, 2)
            sheet.range(f"A{r}").value = [values]
            _apply_row_colors(sheet, r, values, _prev_values.get(index_name))
            _prev_values[index_name] = values
            _next_row[index_name] = r + 1
        except Exception as e:
            print(f"[OILiveDashboard] Failed writing {index_name} live row: {e}")
            # Deliberately continues to the other index rather than
            # returning -- one sheet failing shouldn't block the other.

    try:
        book.save()
    except Exception as e:
        print(f"[OILiveDashboard] Failed saving live dashboard: {e}")
