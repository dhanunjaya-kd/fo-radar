"""
Weekly report: rolls up a week's worth of daily signal logs and index
tracker snapshots -- both already being written every day regardless
of this file -- into one consolidated Excel workbook. Doesn't track
anything new; it only reads what excel_logger.py and index_tracker.py
have already saved to disk.

IMPORTANT: reads each file's own header row (row 1), not a fixed
column list -- this project's schema has genuinely changed mid-way
(columns were added to index_tracker.py partway through), and older
days' files have fewer columns than newer ones. index_tracker.py
already guards against corrupting a file's OWN data when the schema
changes mid-day; this reads each day using ITS OWN real header so a
week spanning a schema change doesn't misread older rows under the
wrong column names.

Sheets produced:
  Summary        -- week totals: signal counts, win rate, NIFTY/
                     BANKNIFTY weekly open/close/change/bias mix
  All Signals     -- every signal from every day this week, one table
  NIFTY Daily     -- one row per day, that day's closing snapshot
  BANKNIFTY Daily -- same, for BANKNIFTY
"""
import os
from datetime import datetime, timedelta

try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font, PatternFill
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

from .excel_logger import LOG_DIR as SIGNAL_LOG_DIR, COLUMNS as SIGNAL_COLUMNS_CURRENT
from .index_tracker import LOG_DIR as INDEX_LOG_DIR, COLUMNS as INDEX_COLUMNS_CURRENT


def _week_dates(reference_date=None):
    """Monday through Friday of the week containing reference_date
    (defaults to today)."""
    ref = reference_date or datetime.now().date()
    monday = ref - timedelta(days=ref.weekday())
    return [monday + timedelta(days=i) for i in range(5)]


def _signal_log_path(date_str):
    nested = os.path.join(SIGNAL_LOG_DIR, date_str, f"signals_{date_str}.xlsx")
    if os.path.exists(nested):
        return nested
    flat = os.path.join(SIGNAL_LOG_DIR, f"signals_{date_str}.xlsx")
    return flat if os.path.exists(flat) else None


def _index_log_path(index_name, date_str):
    nested = os.path.join(INDEX_LOG_DIR, date_str, f"index_tracker_{index_name}_{date_str}.xlsx")
    if os.path.exists(nested):
        return nested
    flat = os.path.join(INDEX_LOG_DIR, f"index_tracker_{index_name}_{date_str}.xlsx")
    return flat if os.path.exists(flat) else None


def _read_rows(path, sheet_name):
    """
    Reads a file using ITS OWN row-1 header, not an assumed fixed list
    -- see the module docstring for why this matters. Returns a list
    of dicts keyed by whatever that file's real columns actually are.
    """
    if not path:
        return []
    wb = load_workbook(path, data_only=True)
    ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.active
    header = [c.value for c in ws[1]]
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is None:
            continue
        rows.append(dict(zip(header, row)))
    return rows


def generate_weekly_report(reference_date=None):
    """
    Builds the weekly rollup workbook and saves it to
    signal_logs/weekly_reports/week_<Mon>_to_<Fri>.xlsx. Returns the
    path, or None if openpyxl isn't available.

    Only includes days that actually have log files -- a short week
    (holiday, or generated mid-week) just has fewer rows, not an error.
    """
    if not OPENPYXL_AVAILABLE:
        return None

    dates = _week_dates(reference_date)
    date_strs = [d.strftime("%Y-%m-%d") for d in dates]

    all_signals = []
    for ds in date_strs:
        path = _signal_log_path(ds)
        for row in _read_rows(path, "Signals"):
            row["_date"] = ds
            all_signals.append(row)

    nifty_daily, banknifty_daily = [], []
    for ds in date_strs:
        for index_name, bucket in (("NIFTY", nifty_daily), ("BANKNIFTY", banknifty_daily)):
            path = _index_log_path(index_name, ds)
            rows = _read_rows(path, "Snapshots")
            if rows:
                bucket.append({"date": ds, **rows[-1]})  # last snapshot = closing state

    wb = Workbook()
    wb.active.title = "Summary"
    _write_summary_sheet(wb.active, dates, all_signals, nifty_daily, banknifty_daily)

    _write_all_signals_sheet(wb.create_sheet("All Signals"), all_signals)
    _write_index_daily_sheet(wb.create_sheet("NIFTY Daily"), nifty_daily)
    _write_index_daily_sheet(wb.create_sheet("BANKNIFTY Daily"), banknifty_daily)

    out_dir = os.path.join(SIGNAL_LOG_DIR, "weekly_reports")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"week_{date_strs[0]}_to_{date_strs[-1]}.xlsx")
    wb.save(path)
    return path


def _write_summary_sheet(ws, dates, all_signals, nifty_daily, banknifty_daily):
    ws.append(["F&O Radar — Weekly Report", f"{dates[0]:%d %b %Y} - {dates[-1]:%d %b %Y}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])

    total = len(all_signals)
    buys = sum(1 for s in all_signals if s.get("Action") == "BUY")
    sells = sum(1 for s in all_signals if s.get("Action") == "SELL")
    target_hits = sum(1 for s in all_signals if str(s.get("Outcome") or "").startswith("Target"))
    sl_hits = sum(1 for s in all_signals if s.get("Outcome") == "SL Hit")
    still_open = total - target_hits - sl_hits
    resolved = target_hits + sl_hits
    win_rate = round(100 * target_hits / resolved, 1) if resolved else None

    ws.append(["Signals This Week"])
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
    ws.append(["Total signals", total])
    ws.append(["BUY / SELL", f"{buys} / {sells}"])
    ws.append(["Target hit", target_hits])
    ws.append(["SL hit", sl_hits])
    ws.append(["Still open", still_open])
    ws.append(["Win rate (of resolved)", f"{win_rate}%" if win_rate is not None else "—"])
    ws.append([])

    for label, daily in (("NIFTY", nifty_daily), ("BANKNIFTY", banknifty_daily)):
        ws.append([f"{label} This Week"])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
        if daily:
            open_spot = daily[0].get("Spot")
            close_spot = daily[-1].get("Spot")
            chg_pct = round(100 * (close_spot - open_spot) / open_spot, 2) if open_spot else None
            pcrs = [d.get("PCR") for d in daily if isinstance(d.get("PCR"), (int, float))]
            avg_pcr = round(sum(pcrs) / len(pcrs), 2) if pcrs else None
            bias_counts = {}
            for d in daily:
                b = d.get("Bias")
                if b:
                    bias_counts[b] = bias_counts.get(b, 0) + 1
            ws.append(["Open (start of week)", open_spot])
            ws.append(["Close (latest)", close_spot])
            ws.append(["Week change", f"{chg_pct}%" if chg_pct is not None else "—"])
            ws.append(["Average PCR", avg_pcr if avg_pcr is not None else "—"])
            ws.append(["Bias readings", ", ".join(f"{k}: {v}" for k, v in bias_counts.items()) or "—"])
        else:
            ws.append(["No data logged this week"])
        ws.append([])

    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 28


def _write_all_signals_sheet(ws, all_signals):
    # Current schema as the base column order (newest = most complete,
    # per how this project's schema has evolved -- columns get added,
    # not removed) -- but still include any column only an older file
    # had, so nothing silently disappears from the report.
    seen = list(SIGNAL_COLUMNS_CURRENT)
    for s in all_signals:
        for k in s.keys():
            if k not in seen and k != "_date":
                seen.append(k)

    headers = ["Date"] + seen
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DDDDDD")
    for s in all_signals:
        ws.append([s.get("_date")] + [s.get(c, "") for c in seen])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 14


def _write_index_daily_sheet(ws, daily_rows):
    seen = list(INDEX_COLUMNS_CURRENT)
    for d in daily_rows:
        for k in d.keys():
            if k not in seen and k != "date":
                seen.append(k)

    headers = ["Date"] + seen
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DDDDDD")
    for d in daily_rows:
        ws.append([d.get("date")] + [d.get(c, "") for c in seen])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 14
