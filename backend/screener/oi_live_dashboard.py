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

try:
    import xlwings as xw
    XLWINGS_AVAILABLE = True
except ImportError:
    XLWINGS_AVAILABLE = False

from .index_tracker import LOG_DIR

DASHBOARD_PATH = os.path.join(LOG_DIR, "oi_live_dashboard.xlsx")

# Fixed cell layout per index sheet -- overwritten every cycle, not
# appended (that's what the openpyxl Snapshots log is already for).
_FIELD_ROWS = [
    ("Time", 2), ("Spot", 3),
    ("Total Call OI", 4), ("Total Put OI", 5), ("OI Diff", 6),
    ("Highest Call OI Strike", 7), ("Highest Call OI Value", 8),
    ("Highest Put OI Strike", 9), ("Highest Put OI Value", 10),
    ("Call ITM Ratio", 11), ("Put ITM Ratio", 12),
    ("PCR", 13), ("Bias", 14),
]

_app = None   # cached xlwings App -- init once per process, never reopened every cycle
_book = None  # cached workbook handle
_warned_once = False


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


def _get_or_create_sheet(book, index_name):
    if index_name in [s.name for s in book.sheets]:
        return book.sheets[index_name]
    sheet = book.sheets.add(index_name, after=book.sheets[-1])
    sheet.range("A1").value = "Field"
    sheet.range("B1").value = "Value"
    for label, row in _FIELD_ROWS:
        sheet.range(f"A{row}").value = label
    return sheet


def write_live_dashboard(results):
    """results: the same {'NIFTY': row_or_None, 'BANKNIFTY': row_or_None}
    dict snapshot_all() already returns -- no new Fyers fetch, just a
    second write of data already in hand. Call from the end of
    snapshot_all(). Never raises -- any failure here must not affect
    the caller's return value."""
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
            values = {
                "Time": row.get("Time"), "Spot": row.get("Spot"),
                "Total Call OI": total_call, "Total Put OI": total_put,
                "OI Diff": oi_diff,
                "Highest Call OI Strike": row.get("Highest Call OI Strike"),
                "Highest Call OI Value": row.get("Highest Call OI Value"),
                "Highest Put OI Strike": row.get("Highest Put OI Strike"),
                "Highest Put OI Value": row.get("Highest Put OI Value"),
                "Call ITM Ratio": row.get("Call ITM Ratio"),
                "Put ITM Ratio": row.get("Put ITM Ratio"),
                "PCR": row.get("PCR"), "Bias": row.get("Bias"),
            }
            for label, cell_row in _FIELD_ROWS:
                sheet.range(f"B{cell_row}").value = values.get(label)
        except Exception as e:
            print(f"[OILiveDashboard] Failed writing {index_name} live view: {e}")
            # Deliberately continues to the other index rather than
            # returning -- one sheet failing shouldn't block the other.

    try:
        book.save()
    except Exception as e:
        print(f"[OILiveDashboard] Failed saving live dashboard: {e}")
