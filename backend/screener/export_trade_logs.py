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

from .backtest_signal_pnl import load_all_trades, categorize_exit_reason, LOG_DIR

OUT_DIR = os.path.join(LOG_DIR, "trade_log_exports")

COLUMNS = [
    "Symbol", "Action", "Grade", "Sector", "OI Confirmation", "Pattern",
    "Entry Time", "Exit Time", "Entry", "SL", "Target 1", "Target 2", "Target 3",
    "Exit", "Qty", "P&L (Rs)", "P&L %", "R-Multiple", "Reason",
]


def _row_for(t):
    return [
        t["symbol"], t["action"], t["grade"], t["sector"], t["oi_confirmation"], t["pattern"],
        t["entry_dt"].strftime("%Y-%m-%d %H:%M:%S"), t["exit_dt"].strftime("%Y-%m-%d %H:%M:%S"),
        t["entry"], t["sl"], t.get("target1"), t.get("target2"), t.get("target3"),
        t["exit_price"], t["qty"], t["pnl"], t["pnl_pct"], t["r_multiple"], t["exit_reason"],
    ]


def _write_workbook(trades, path, title):
    wb = Workbook()
    ws = wb.active
    ws.title = title
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
    for t in trades:
        ws.append(_row_for(t))
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


def main():
    trades, excluded = load_all_trades()
    print(f"Loaded {len(trades)} resolved trades ({excluded} rows excluded -- unresolved/unparseable/no lot size).")
    if not trades:
        print("Nothing to export.")
        return

    complete_path = os.path.join(OUT_DIR, "complete_trade_log.xlsx")
    _write_workbook(trades, complete_path, "Complete Trade Log")
    print(f"Wrote {len(trades)} trades -> {complete_path}")

    hits_only = [t for t in trades if is_real_sl_or_target_hit(t)]
    hits_path = os.path.join(OUT_DIR, "sl_target_hits_only.xlsx")
    _write_workbook(hits_only, hits_path, "SL and Target Hits Only")
    print(f"Wrote {len(hits_only)} trades (SL/Target hits only, {len(trades) - len(hits_only)} EOD-estimate/other rows excluded) -> {hits_path}")


if __name__ == "__main__":
    main()
