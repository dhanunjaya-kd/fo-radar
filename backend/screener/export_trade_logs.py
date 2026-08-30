"""
screener/export_trade_logs.py

Two real deliverables, per explicit request:
  1. complete_trade_log.xlsx -- every resolved trade, every outcome
     type (SL Hit, Target N Hit, and the "Closed up/down/flat" EOD
     estimates), same universe as the PDF's own Trade Log page.
  2. sl_target_hits_only.xlsx -- the SAME trades, filtered down to
     ONLY genuine SL/Target hits -- excludes every "Closed
     up/down/flat" (EOD estimate) row, since those never actually
     crossed a real level and were flagged as a separate, less
     certain category of outcome.

Both reuse backtest_signal_pnl.py's own already-tested
load_all_trades() (now carrying target1/target2/target3, added
alongside this script) and categorize_exit_reason() (already tested
for the PDF's own Exit Analysis page) rather than re-parsing the raw
signal logs a second time with new, unverified logic.

Run as a standalone script:
    cd backend
    venv\\Scripts\\activate
    python -m screener.export_trade_logs
"""
import os
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from .backtest_signal_pnl import load_all_trades, categorize_exit_reason, list_signal_log_dates, LOG_DIR

try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None

OUT_DIR = os.path.join(LOG_DIR, "trade_log_exports")

COLUMNS = [
    "Symbol", "Action", "Grade", "Sector", "OI Confirmation", "Pattern",
    "Entry Time", "Exit Time", "Entry", "SL", "Target 1", "Target 2", "Target 3",
    "Exit", "Qty", "P&L (Rs)", "P&L %", "R-Multiple", "Reason",
]

UNRESOLVED_COLUMNS = [
    "Entry Time", "Symbol", "Action", "Grade", "Sector", "Entry (Premium)",
    "SL", "Target 1", "Target 2", "Target 3", "Option Symbol", "Exited At", "Status",
]


def _row_for(t):
    return [
        t["symbol"], t["action"], t["grade"], t["sector"], t["oi_confirmation"], t["pattern"],
        t["entry_dt"].strftime("%Y-%m-%d %H:%M:%S"), t["exit_dt"].strftime("%Y-%m-%d %H:%M:%S"),
        t["entry"], t["sl"], t.get("target1"), t.get("target2"), t.get("target3"),
        t["exit_price"], t["qty"], t["pnl"], t["pnl_pct"], t["r_multiple"], t["exit_reason"],
    ]


def _unresolved_row_for(r):
    return [
        r["entry_time"], r["symbol"], r["action"], r["grade"], r["sector"],
        r["entry"], r["sl"], r["target1"], r["target2"], r["target3"],
        r["option_symbol"], r["exited_at"], r["status"],
    ]


def _write_workbook(items, path, title, columns, row_fn):
    wb = Workbook()
    ws = wb.active
    ws.title = title
    ws.append(columns)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
    for item in items:
        ws.append(row_fn(item))
    for col_cells in ws.columns:
        values = [str(c.value) for c in col_cells if c.value is not None]
        max_len = max((len(v) for v in values), default=10)
        ws.column_dimensions[col_cells[0].column_letter].width = max(max_len + 2, 10)
    os.makedirs(OUT_DIR, exist_ok=True)
    wb.save(path)
    return path


def is_real_sl_or_target_hit(trade):
    """True only for a genuine SL/Target 1/2/3 crossing -- excludes
    the 'Closed up/down/flat' EOD-estimate category and anything else
    categorize_exit_reason() doesn't recognize as one of those two.
    Reuses that same function rather than re-matching the exit_reason
    string with new regex here."""
    return categorize_exit_reason(trade["exit_reason"]) in ("SL", "T1", "T2", "T3")


def load_unresolved_rows():
    """
    Every row with a blank Outcome, across every logged day --
    signals load_all_trades() deliberately EXCLUDES (that function's
    whole job is resolved trades only), so this reads the raw
    signals_*.xlsx files directly rather than trying to coax them out
    of a function built to filter them away.

    Distinguishes two real, differently-actionable cases via a
    "Status" column:
      "Still Open"            -- Exited At is also blank. Either
        genuinely still an open position right now, or (a real,
        documented failure mode in this project) the process
        restarted while it was open and lost track of it.
      "Exited, Not Backfilled" -- Exited At has a real value but
        Outcome never got filled in. This is exactly what
        backfill_signal_outcomes.py exists to resolve.

    Returns a list of dicts, oldest first. Rows missing a Symbol are
    skipped (blank/malformed row, not a real signal).
    """
    if load_workbook is None:
        return []
    rows = []
    for date_str in list_signal_log_dates():
        nested = os.path.join(LOG_DIR, date_str, f"signals_{date_str}.xlsx")
        flat = os.path.join(LOG_DIR, f"signals_{date_str}.xlsx")
        path = nested if os.path.exists(nested) else flat
        if not os.path.exists(path):
            continue
        try:
            wb = load_workbook(path, read_only=True, data_only=True)
            ws = wb["Signals"]
            headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
            col = {name: i for i, name in enumerate(headers)}
            required = {"Symbol", "Action", "Grade", "Entry (Premium)", "SL", "Target 1",
                        "Target 2", "Target 3", "Outcome", "Exited At", "Timestamp"}
            if not required.issubset(col.keys()):
                print(f"  (skipping {os.path.basename(path)}: missing required column(s))")
                continue
            for raw in ws.iter_rows(min_row=2, values_only=True):
                symbol = raw[col["Symbol"]]
                outcome = raw[col["Outcome"]]
                if not symbol or outcome:
                    continue  # no symbol (blank row), or already resolved -- not what this pulls
                exited_at = raw[col["Exited At"]]
                rows.append({
                    "entry_time": raw[col["Timestamp"]], "symbol": symbol, "action": raw[col["Action"]],
                    "grade": raw[col["Grade"]], "sector": raw[col.get("Sector", -1)] if "Sector" in col else None,
                    "entry": raw[col["Entry (Premium)"]], "sl": raw[col["SL"]],
                    "target1": raw[col["Target 1"]], "target2": raw[col["Target 2"]], "target3": raw[col["Target 3"]],
                    "option_symbol": raw[col.get("Option Symbol", -1)] if "Option Symbol" in col else None,
                    "exited_at": exited_at,
                    "status": "Exited, Not Backfilled" if exited_at else "Still Open",
                })
        except Exception as e:
            print(f"  (skipping {os.path.basename(path)}: {e})")
            continue
    return rows


def main():
    trades, excluded = load_all_trades()
    print(f"Loaded {len(trades)} resolved trades ({excluded} rows excluded -- unresolved/unparseable/no lot size).")

    if trades:
        complete_path = os.path.join(OUT_DIR, "complete_trade_log.xlsx")
        _write_workbook(trades, complete_path, "Complete Trade Log", COLUMNS, _row_for)
        print(f"Wrote {len(trades)} trades -> {complete_path}")

        hits_only = [t for t in trades if is_real_sl_or_target_hit(t)]
        hits_path = os.path.join(OUT_DIR, "sl_target_hits_only.xlsx")
        _write_workbook(hits_only, hits_path, "SL and Target Hits Only", COLUMNS, _row_for)
        print(f"Wrote {len(hits_only)} trades (SL/Target hits only, {len(trades) - len(hits_only)} EOD-estimate/other rows excluded) -> {hits_path}")
    else:
        print("No resolved trades -- skipping complete_trade_log.xlsx and sl_target_hits_only.xlsx.")

    unresolved = load_unresolved_rows()
    if unresolved:
        still_open = sum(1 for r in unresolved if r["status"] == "Still Open")
        not_backfilled = len(unresolved) - still_open
        unresolved_path = os.path.join(OUT_DIR, "unresolved_signals.xlsx")
        _write_workbook(unresolved, unresolved_path, "Unresolved Signals", UNRESOLVED_COLUMNS, _unresolved_row_for)
        print(f"Wrote {len(unresolved)} unresolved rows ({still_open} Still Open, {not_backfilled} Exited but Not Backfilled) -> {unresolved_path}")
    else:
        print("No unresolved (blank-Outcome) rows found -- skipping unresolved_signals.xlsx.")


if __name__ == "__main__":
    main()
