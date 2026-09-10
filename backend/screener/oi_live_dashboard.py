"""
screener/oi_live_dashboard.py

Adds two things on top of index_tracker.py's existing snapshot_index()/
snapshot_all(), without changing how those already work:

1. compute_itm_ratios() -- what fraction of each side's chain-wide OI
   sits at strikes already in-the-money right now. Pure function, no
   I/O. REAL CAVEAT, not yet confirmed live: sums OI only across the
   `rows` list get_option_analytics(..., strikecount=10) returns --
   if oi['ce_oi']/oi['pe_oi'] are computed over a wider strike set,
   this under-counts. Directionally should still be meaningful.

2. write_live_dashboard() -- pushes the same row dict snapshot_index()
   already builds into a live-visible Excel window via xlwings.
   Deliberately a SEPARATE workbook (signal_logs/oi_live_dashboard.xlsx),
   never the file _today_path()/_atomic_save() manage -- xlwings (COM)
   and openpyxl (file-level save) fighting over one file is a real
   lock-collision risk given this project's Windows file-lock history.

   Sep 10 2026, several rounds of real fixes based on his actual
   screenshots, in order:
   - Switched from overwrite-in-place to an appended header+row log
     (matches the reference tool's scrolling table).
   - Delete+recreate instead of clear_contents() on reset -- clearing
     values in place left old NUMBER FORMATTING behind (a stale Time
     format silently turned a real Spot price into "01:12:00").
   - Added up/down + threshold-based cell coloring, autofit, and "(K)"
     scaling -- fixed real truncated headers and scientific-notation
     OI numbers ("-1.4E+07") from his screenshots.
   - RENAMED every top-table column to match the reference tool's own
     labels exactly (Time/Value/Call Sum (in K)/Put Sum (in K)/
     Difference (in K)/Call Boundary (in K)/Put Boundary (in K)/Call
     ITM/Put ITM), and split the boundary panel into TWO SIDE-BY-SIDE
     titled blocks ("Open Interest Upper Boundary" / "Open Interest
     Lower Boundary") instead of one flat list -- direct structural
     match to his reference screenshot, not just similarly-shaped.
     Strike/PCR/Bias columns that don't appear in the reference tool's
     top table are kept as trailing bonus columns rather than deleted
     -- still fully available, just placed after the 9 matching ones.

   REAL UNRESOLVED CAVEAT: "Call Boundary (in K)" / "Put Boundary (in
   K)" in the reference tool's top table (values like 34.5-37.9) don't
   match the magnitude of any OI-based number this project can compute
   (raw boundary OI is in the hundreds of thousands). What's written
   here under that exact column name is still Highest Call/Put OI
   Value in K -- the LABEL now matches "ditto", the underlying NUMBER
   may not, since the reference tool's real formula for this specific
   column is still unconfirmed (no source access, screenshot-only).

   Fails soft everywhere: no Excel installed/open, sheet not reachable,
   any write error -- logs once and returns, never raises.

   Requires `pip install xlwings` (pulls in pywin32 automatically on
   Windows) -- not in requirements.txt yet.

Wiring into index_tracker.py (3 small edits, unchanged from before --
see chat history for exact before/after text):
  1. COLUMNS: add "Call ITM Ratio", "Put ITM Ratio".
  2. snapshot_index(): call compute_itm_ratios(...) and add to `row`.
  3. snapshot_all(): call write_live_dashboard(results) before return.
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

# Header row for the append-log layout. First 9 columns are named and
# ordered to match the reference tool's own top table EXACTLY (Time,
# Value, Call Sum (in K), Put Sum (in K), Difference (in K), Call
# Boundary (in K), Put Boundary (in K), Call ITM, Put ITM). The last 4
# (strikes, PCR, Bias) don't appear in the reference tool's top table
# at all -- kept as trailing bonus columns rather than deleted, since
# they're real, tested, useful data.
_LIVE_LOG_COLUMNS = [
    "Time", "Value", "Call Sum (in K)", "Put Sum (in K)", "Difference (in K)",
    "Call Boundary (in K)", "Put Boundary (in K)", "Call ITM", "Put ITM",
    "Call Boundary Strike", "Put Boundary Strike", "PCR", "Bias",
]

_app = None   # cached xlwings App -- init once per process, never reopened every cycle
_book = None  # cached workbook handle
_warned_once = False
_next_row = {}         # {index_name: int} -- next empty row to write to
_sheet_day_seen = {}   # {index_name: 'YYYY-MM-DD'} -- last calendar day this process appended a row for that sheet
_prev_values = {}      # {index_name: [values from the last written row]} -- drives up/down coloring

_GREEN_FILL = (198, 239, 206)  # Excel's own standard "Good" green
_RED_FILL = (255, 199, 206)    # Excel's own standard "Bad" red
_AMBER_FILL = (255, 235, 156)  # Excel's standard "Neutral/Note" amber -- used for Yes flags worth a second look
_COL_LETTERS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M"]
_PCR_COL_INDEX = _LIVE_LOG_COLUMNS.index("PCR")
_BIAS_COL_INDEX = _LIVE_LOG_COLUMNS.index("Bias")

# Boundary summary panel -- TWO side-by-side titled blocks, matching
# the reference tool's "Open Interest Upper Boundary" / "Open Interest
# Lower Boundary" layout exactly, in columns O:P (upper/call) and R:S
# (lower/put) -- both well clear of the log table's A:M columns and of
# each other, so neither the growing log nor either block can collide.
# Overwritten every cycle, never appended (current state only).
_UPPER_LABEL_COL, _UPPER_VALUE_COL = "O", "P"
_LOWER_LABEL_COL, _LOWER_VALUE_COL = "R", "S"
_PANEL_ROWS = {"strike1": 2, "oi1": 3, "strike2": 4, "oi2": 5, "summary": 6, "exits": 7, "itm": 8}
_prev_boundary_oi = {}  # {index_name: {'call': oi, 'put': oi}} -- drives the Exits guess (see compute_boundary_pairs docstring)


def _to_k(value):
    """Raw OI count -> thousands, 1 decimal -- matches the reference
    tool's "(in K)" columns (163.2 instead of 163200). Also sidesteps
    the real bug hit Sep 10: writing raw 7-8 digit counts into an
    unsized column made Excel display them in scientific notation
    ("-1.4E+07") instead of a readable number."""
    return round(value / 1000, 1) if value is not None else None


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


def compute_boundary_pairs(rows, top_n=2):
    """Top-N call-OI strikes and top-N put-OI strikes, each as (strike,
    oi) sorted highest-OI-first -- the reference tool's 'Strike Price
    1/2' + 'OI (in K)' boundary panel. Pure function, no I/O.

    Returns (call_pairs, put_pairs). Either list can be shorter than
    top_n (never padded with fake entries) if `rows` doesn't have that
    many strikes with real OI data."""
    if not rows:
        return [], []

    def _pairs(side):
        pairs = [
            (r.get("strike"), (r.get(side, {}) or {}).get("oi"))
            for r in rows
            if r.get("strike") is not None and (r.get(side, {}) or {}).get("oi") is not None
        ]
        pairs.sort(key=lambda p: p[1], reverse=True)
        return pairs[:top_n]

    return _pairs("ce"), _pairs("pe")


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
    """Bold + light gray fill on the log header row, then auto-size
    EVERY used column (log table AND both boundary blocks) to fit its
    text. Must run AFTER both panels are written, or autofit misses
    whatever wasn't on the sheet yet -- real bug hit Sep 10 when this
    ran before the boundary panel existed, leaving it truncated."""
    try:
        header_range = sheet.range(f"A1:{_COL_LETTERS[-1]}1")
        header_range.font.bold = True
        header_range.color = (242, 242, 242)
        sheet.autofit()
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


def _write_boundary_panel_labels(sheet):
    """Field labels for both boundary blocks -- written once when the
    sheet is (re)created. Matches the reference tool's exact grouping:
    Open Interest + Call Exits + Call ITM sit under the Upper/call
    block; PCR + Put Exits + Put ITM sit under the Lower/put block."""
    try:
        sheet.range(f"{_UPPER_LABEL_COL}1").value = "Open Interest Upper Boundary"
        sheet.range(f"{_LOWER_LABEL_COL}1").value = "Open Interest Lower Boundary"
        sheet.range(f"{_UPPER_LABEL_COL}1:{_UPPER_VALUE_COL}1").font.bold = True
        sheet.range(f"{_LOWER_LABEL_COL}1:{_LOWER_VALUE_COL}1").font.bold = True

        upper_labels = {
            "strike1": "Strike Price 1", "oi1": "OI (in K)",
            "strike2": "Strike Price 2", "oi2": "OI (in K)",
            "summary": "Open Interest", "exits": "Call Exits", "itm": "Call ITM",
        }
        lower_labels = {
            "strike1": "Strike Price 1", "oi1": "OI (in K)",
            "strike2": "Strike Price 2", "oi2": "OI (in K)",
            "summary": "PCR", "exits": "Put Exits", "itm": "Put ITM",
        }
        for key, r in _PANEL_ROWS.items():
            sheet.range(f"{_UPPER_LABEL_COL}{r}").value = upper_labels[key]
            sheet.range(f"{_LOWER_LABEL_COL}{r}").value = lower_labels[key]
    except Exception as e:
        print(f"[OILiveDashboard] Boundary panel labels skipped: {e}")


def _write_boundary_panel(sheet, index_name, row):
    """Overwrites both boundary blocks in place -- current state only,
    never logged/appended (that's what the A:M table is for). Pulls
    per-strike rows via get_last_oi_snapshot() (already built into
    index_tracker.py to avoid a second Fyers fetch), the same `rows`
    snapshot_index() itself just used this cycle."""
    try:
        oi_snap = get_last_oi_snapshot(index_name)
        rows_data = (oi_snap or {}).get("rows")
        spot = row.get("Spot")
        call_pairs, put_pairs = compute_boundary_pairs(rows_data)
        call1 = call_pairs[0] if len(call_pairs) > 0 else (None, None)
        call2 = call_pairs[1] if len(call_pairs) > 1 else (None, None)
        put1 = put_pairs[0] if len(put_pairs) > 0 else (None, None)
        put2 = put_pairs[1] if len(put_pairs) > 1 else (None, None)

        r = _PANEL_ROWS
        sheet.range(f"{_UPPER_VALUE_COL}{r['strike1']}").value = call1[0]
        sheet.range(f"{_UPPER_VALUE_COL}{r['oi1']}").value = _to_k(call1[1])
        sheet.range(f"{_UPPER_VALUE_COL}{r['strike2']}").value = call2[0]
        sheet.range(f"{_UPPER_VALUE_COL}{r['oi2']}").value = _to_k(call2[1])
        sheet.range(f"{_LOWER_VALUE_COL}{r['strike1']}").value = put1[0]
        sheet.range(f"{_LOWER_VALUE_COL}{r['oi1']}").value = _to_k(put1[1])
        sheet.range(f"{_LOWER_VALUE_COL}{r['strike2']}").value = put2[0]
        sheet.range(f"{_LOWER_VALUE_COL}{r['oi2']}").value = _to_k(put2[1])

        bias = row.get("Bias") or ""
        oi_cell = sheet.range(f"{_UPPER_VALUE_COL}{r['summary']}")
        oi_cell.value = bias
        oi_cell.color = _GREEN_FILL if "Bullish" in bias else (_RED_FILL if "Bearish" in bias else None)

        pcr = row.get("PCR")
        pcr_cell = sheet.range(f"{_LOWER_VALUE_COL}{r['summary']}")
        pcr_cell.value = pcr
        if pcr is not None:
            pcr_cell.color = _GREEN_FILL if pcr > 1.3 else (_RED_FILL if pcr < 0.7 else None)

        # Exits: best-effort read, not a confirmed match to the
        # reference tool -- "Yes" means the #1 boundary strike's OI
        # dropped versus last cycle (writers unwinding there).
        prev = _prev_boundary_oi.get(index_name, {})
        call1_oi, put1_oi = call1[1], put1[1]
        call_exit = prev.get("call") is not None and call1_oi is not None and call1_oi < prev["call"]
        put_exit = prev.get("put") is not None and put1_oi is not None and put1_oi < prev["put"]
        call_exit_cell = sheet.range(f"{_UPPER_VALUE_COL}{r['exits']}")
        call_exit_cell.value = "Yes" if call_exit else "No"
        call_exit_cell.color = _AMBER_FILL if call_exit else None
        put_exit_cell = sheet.range(f"{_LOWER_VALUE_COL}{r['exits']}")
        put_exit_cell.value = "Yes" if put_exit else "No"
        put_exit_cell.color = _AMBER_FILL if put_exit else None
        _prev_boundary_oi[index_name] = {"call": call1_oi, "put": put1_oi}

        # ITM: unambiguous -- is the #1 boundary strike itself ITM
        # right now (call ITM when strike < spot, put ITM when strike > spot).
        call_itm = spot is not None and call1[0] is not None and call1[0] < spot
        put_itm = spot is not None and put1[0] is not None and put1[0] > spot
        call_itm_cell = sheet.range(f"{_UPPER_VALUE_COL}{r['itm']}")
        call_itm_cell.value = "Yes" if call_itm else "No"
        call_itm_cell.color = _AMBER_FILL if call_itm else None
        put_itm_cell = sheet.range(f"{_LOWER_VALUE_COL}{r['itm']}")
        put_itm_cell.value = "Yes" if put_itm else "No"
        put_itm_cell.color = _AMBER_FILL if put_itm else None
    except Exception as e:
        print(f"[OILiveDashboard] Boundary panel write skipped for {index_name}: {e}")


def _get_or_create_sheet(book, index_name):
    """Returns a sheet whose header row is guaranteed to match
    _LIVE_LOG_COLUMNS exactly and whose data starts fresh for today.

    Real bug found Sep 10 (live, in his actual workbook): an earlier
    version's in-place clear_contents() removed cell VALUES but left
    NUMBER FORMATTING behind -- a stale Time-formatted cell silently
    turned a real Spot price into "01:12:00". Fix: never clear-in-
    place. If the sheet doesn't exist, or its row-1 header doesn't
    exactly match today's _LIVE_LOG_COLUMNS (catches both a leftover
    old-schema sheet and a new calendar day), DELETE the sheet and add
    a fresh one instead -- a freshly added sheet's cells start at
    Excel's true default format, so this whole bug class can't recur.
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
    _write_boundary_panel_labels(sheet)  # must run BEFORE _style_header's autofit, so O:S gets sized too
    _style_header(sheet)
    _next_row[index_name] = 2
    _sheet_day_seen[index_name] = today_str
    _prev_values.pop(index_name, None)
    _prev_boundary_oi.pop(index_name, None)
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
                _to_k(total_call), _to_k(total_put), _to_k(oi_diff),
                _to_k(row.get("Highest Call OI Value")), _to_k(row.get("Highest Put OI Value")),
                row.get("Call ITM Ratio"), row.get("Put ITM Ratio"),
                row.get("Highest Call OI Strike"), row.get("Highest Put OI Strike"),
                row.get("PCR"), row.get("Bias"),
            ]
            r = _next_row.get(index_name, 2)
            sheet.range(f"A{r}").value = [values]
            _apply_row_colors(sheet, r, values, _prev_values.get(index_name))
            _prev_values[index_name] = values
            _next_row[index_name] = r + 1

            _write_boundary_panel(sheet, index_name, row)
        except Exception as e:
            print(f"[OILiveDashboard] Failed writing {index_name} live row: {e}")
            # Deliberately continues to the other index rather than
            # returning -- one sheet failing shouldn't block the other.

    try:
        book.save()
    except Exception as e:
        print(f"[OILiveDashboard] Failed saving live dashboard: {e}")
