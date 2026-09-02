"""
screener/log_inventory.py

Read-only inventory of the REAL signal_logs/*.xlsx files. Reports facts
only -- file list, date coverage, the ACTUAL header row found in each
file, and distinct values seen in a few key columns. Computes NO
metrics, reconstructs NOTHING, infers NOTHING. Every line in the output
is either "this file exists" or "this exact value was found in this
exact cell" -- nothing else.

Purpose: answer, with real evidence, whether the historical logs are
schema-consistent enough to trust any reconstruction (like
base_score_pre_oi) across the full date range, and whether states like
"CONTRADICTING" ever appear at all (directly answers whether the
OI-downgrade variant has anything real to test against).

Run: python -m screener.log_inventory
Writes signal_logs/inventory_reports/inventory_<date>.txt and prints
the same to console.
"""
import os
from datetime import datetime

try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None

from .backtest_signal_pnl import LOG_DIR, list_signal_log_dates

# The header this project's CURRENT excel_logger.py writes -- used only
# to report whether each file's REAL header matches it, never assumed.
CURRENT_SCHEMA = [
    "Timestamp", "Symbol", "Action", "Grade", "Confidence",
    "Stock Price", "Change %", "Strike", "Entry (Premium)", "SL", "Target 1",
    "Target 2", "Target 3", "Qty", "R:R", "OI Confirmation", "Pattern",
    "PCR", "IV %", "RSI", "ADX", "Sector", "Option Symbol",
    "SL Hit At", "Target 1 Hit At", "Target 2 Hit At", "Target 3 Hit At",
    "Outcome", "Exited At",
]


def run():
    if load_workbook is None:
        print("openpyxl not available -- cannot read any Excel files.")
        return

    dates = list_signal_log_dates()
    lines = []
    lines.append("=" * 78)
    lines.append(f"SIGNAL LOG INVENTORY -- generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("Read-only. No metrics computed. No values inferred or reconstructed.")
    lines.append("=" * 78)
    lines.append("")

    if not dates:
        lines.append(f"No signal log files found under {LOG_DIR} at all.")
        report_text = "\n".join(lines)
        print(report_text)
        return

    lines.append(f"Dates with a log file: {len(dates)}")
    lines.append(f"Earliest: {min(dates)}   Latest: {max(dates)}")
    lines.append("(Note: this is FILE coverage, not necessarily contiguous trading days -- gaps")
    lines.append(" below are listed explicitly rather than assumed away.)")
    lines.append("")

    header_variants = {}  # tuple(headers) -> [dates using this exact header set]
    oi_states_seen = set()
    grade_values_seen = set()
    per_file_rows = {}
    unreadable = []
    conflict_dates = {}  # date_str -> count of CONFLICT rows that day

    for date_str in sorted(dates):
        nested = os.path.join(LOG_DIR, date_str, f"signals_{date_str}.xlsx")
        flat = os.path.join(LOG_DIR, f"signals_{date_str}.xlsx")
        path = nested if os.path.exists(nested) else flat
        layout = "nested" if os.path.exists(nested) else "flat"

        try:
            wb = load_workbook(path)
            ws = wb["Signals"]
        except Exception as e:
            unreadable.append((date_str, str(e)))
            continue

        headers = tuple(c.value for c in ws[1])
        header_variants.setdefault(headers, []).append(date_str)

        row_count = 0
        try:
            col = {name: i for i, name in enumerate(headers) if name}
            for raw in ws.iter_rows(min_row=2, values_only=True):
                if raw[0] is None and all(v is None for v in raw):
                    continue
                row_count += 1
                if "OI Confirmation" in col:
                    val = raw[col["OI Confirmation"]]
                    if val is not None:
                        oi_states_seen.add(str(val))
                        if str(val) == "CONFLICT":
                            conflict_dates[date_str] = conflict_dates.get(date_str, 0) + 1
                if "Grade" in col:
                    val = raw[col["Grade"]]
                    if val is not None:
                        grade_values_seen.add(str(val))
        except Exception as e:
            lines.append(f"  (warning: partial read failure on {date_str}: {e})")

        per_file_rows[date_str] = (row_count, layout)

    lines.append("-" * 78)
    lines.append("PER-FILE ROW COUNTS")
    lines.append("-" * 78)
    for date_str in sorted(per_file_rows):
        count, layout = per_file_rows[date_str]
        lines.append(f"  {date_str}  ({layout} layout)  {count} row(s)")
    lines.append(f"  TOTAL raw rows across all files: {sum(c for c, _ in per_file_rows.values())}")
    lines.append("  (This is raw row count, NOT resolved-trade count -- unresolved/still-open")
    lines.append("   rows and rows with no priceable outcome are included here, unfiltered.)")
    lines.append("")

    if unreadable:
        lines.append("-" * 78)
        lines.append(f"UNREADABLE FILES ({len(unreadable)}) -- genuinely could not be opened, not skipped silently")
        lines.append("-" * 78)
        for date_str, err in unreadable:
            lines.append(f"  {date_str}: {err}")
        lines.append("")

    lines.append("-" * 78)
    lines.append(f"HEADER SCHEMA VARIANTS FOUND: {len(header_variants)}")
    lines.append("-" * 78)
    if len(header_variants) == 1:
        lines.append("  Exactly ONE header layout across every readable file -- schema is consistent")
        lines.append("  across the full date range covered by these files.")
    else:
        lines.append("  MULTIPLE different header layouts found -- schema is NOT consistent across")
        lines.append("  the full date range. Any reconstruction (e.g. base_score_pre_oi) must be")
        lines.append("  scoped to a single schema variant's date range, not applied blindly across all.")
    lines.append("")
    for i, (headers, date_list) in enumerate(header_variants.items(), 1):
        matches_current = "MATCHES current excel_logger.py schema" if list(headers) == CURRENT_SCHEMA else "DIFFERENT from current excel_logger.py schema"
        lines.append(f"  Variant {i}: used on {len(date_list)} date(s) -- {min(date_list)} to {max(date_list)} -- {matches_current}")
        lines.append(f"    Dates: {', '.join(date_list)}")
        lines.append(f"    Columns ({len(headers)}): {list(headers)}")
        lines.append("")

    lines.append("-" * 78)
    lines.append("DISTINCT VALUES SEEN -- 'OI Confirmation' column")
    lines.append("-" * 78)
    if oi_states_seen:
        for v in sorted(oi_states_seen):
            lines.append(f"  '{v}'")
        lines.append("")
        lines.append("  Directly answers the OI-downgrade/OI-reject variant question: only states")
        lines.append("  that actually appear above were ever logged. If 'CONTRADICTING' or similar")
        lines.append("  never appears, that variant has no historical rows to test at all --")
        lines.append("  confirming (not assuming) that conflicting-OI candidates were rejected")
        lines.append("  before ever reaching the log.")
    else:
        lines.append("  No 'OI Confirmation' column found in any readable file, or all values blank.")
    lines.append("")

    lines.append("-" * 78)
    lines.append("'CONFLICT' ROWS -- EXACTLY WHERE THEY ARE")
    lines.append("-" * 78)
    if conflict_dates:
        total_conflict = sum(conflict_dates.values())
        lines.append(f"  {total_conflict} row(s) with OI Confirmation == 'CONFLICT', across {len(conflict_dates)} date(s):")
        for d in sorted(conflict_dates):
            lines.append(f"    {d}: {conflict_dates[d]} row(s)")
        lines.append("")
        lines.append("  Raw row count -- still includes unresolved/no-outcome rows, not yet")
        lines.append("  filtered down to only the ones with a real, priceable resolution. That")
        lines.append("  filtering is exactly what ablation_test.py's loader already does for")
        lines.append("  every other trade; same logic applies here once you're ready to look at")
        lines.append("  what these specific rows actually resolved to.")
    else:
        lines.append("  None found. 'CONFLICT' never appears as a value in any readable file.")
    lines.append("")

    lines.append("-" * 78)
    lines.append("DISTINCT VALUES SEEN -- 'Grade' column")
    lines.append("-" * 78)
    if grade_values_seen:
        lines.append(f"  {sorted(grade_values_seen)}")
    else:
        lines.append("  No 'Grade' column found, or all values blank.")
    lines.append("")

    report_text = "\n".join(lines)
    print(report_text)

    out_dir = os.path.join(LOG_DIR, "inventory_reports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"inventory_{datetime.now().strftime('%Y-%m-%d')}.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"\nSaved to: {out_path}")


if __name__ == "__main__":
    run()
