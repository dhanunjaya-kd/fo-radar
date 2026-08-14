"""
screener/management/commands/backfill_signal_outcomes.py

Retroactively fills in SL Hit At / Target 1-3 Hit At / Outcome for signal
rows that never got resolved live -- most commonly because the app
restarted while the position was open (excel_logger.py's _open_positions
is a pure in-memory cache that isn't rebuilt from disk on startup, so
check_outcomes() silently stops watching anything open across a restart --
see the separate restart-recovery fix for stopping this going forward).

METHOD: for every row with a blank Outcome and a real Option Symbol, pulls
that contract's real 1-minute historical candles from its entry timestamp
through end of that trading day via Fyers' History API, and replays them
against the row's own LOCKED SL/Target 1/2/3 already stored on the row
(nothing recomputed) -- same crossing rule check_outcomes() uses live:
SL first (candle low <= sl), then furthest target first (candle high >=
t3, then t2, then t1). Writes the result back into the SAME cells on the
SAME row. Never creates a new row, never touches any other cell.

HONEST LIMITATIONS -- read before trusting the output:
- 1-minute OHLC, not tick data. If SL and a target both fall inside one
  candle's high/low range, which genuinely happened first can't be known
  from OHLC alone. That row is marked "AMBIGUOUS" with the candle time
  noted, rather than guessing an order.
- Fyers' History API only serves ACTIVE (non-expired) option contracts --
  confirmed via Fyers' own community/support posts. Once a strike's
  expiry passes, this can no longer backfill it. NSE's current monthly
  F&O expiry is the last Tuesday of the month -- e.g. "26AUG" contracts
  expire Tue 25 Aug 2026. Run this before expiry, not after.
- A row where no crossing is found in that day's candles is left exactly
  as it was (still blank). That is read as a genuine "still open" result,
  not a failure to look -- if you believe a specific row should have
  resolved, check it manually before trusting the blank.
- This only checks the ENTRY day's candles (signals here are same-day/MIS
  style, squared off by market close) -- a position genuinely held
  overnight would need the script extended to pull more than one day.

Usage (from backend/, venv active):
    python manage.py backfill_signal_outcomes --start 2026-08-10 --end 2026-08-14 --dry-run
    python manage.py backfill_signal_outcomes --start 2026-08-10 --end 2026-08-14
"""
import os
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from openpyxl import load_workbook

from screener.excel_logger import COLUMNS, LOG_DIR
from screener.fyers_client import get_history


def _find_log_path(date_str):
    nested = os.path.join(LOG_DIR, date_str, f"signals_{date_str}.xlsx")
    if os.path.exists(nested):
        return nested
    flat = os.path.join(LOG_DIR, f"signals_{date_str}.xlsx")
    if os.path.exists(flat):
        return flat
    return None


def _fetch_candles(option_symbol, date_str):
    """1-min candles for one option symbol, that trading day only."""
    resp = get_history(option_symbol, resolution="1", range_from=date_str, range_to=date_str)
    if not resp or resp.get("s") != "ok":
        return None, (resp.get("message") if resp else "no response")
    return resp.get("candles", []), None


def _replay(candles, entry_dt, sl, t1, t2, t3):
    """Mirrors excel_logger.check_outcomes()'s live crossing rule, applied
    to historical OHLC candles instead of a live LTP."""
    result = {"sl_hit_at": None, "targets_hit": {}, "ambiguous": []}
    furthest = 0
    for c in candles:
        ts, o, h, l, close, vol = c
        candle_dt = datetime.fromtimestamp(ts)
        if candle_dt < entry_dt:
            continue

        sl_touched = l <= sl
        target_touched = None
        for n, level in ((3, t3), (2, t2), (1, t1)):
            if furthest >= n:
                continue
            if h >= level:
                target_touched = n
                break

        if sl_touched and target_touched:
            result["ambiguous"].append(candle_dt.strftime("%Y-%m-%d %H:%M:%S"))
            continue  # can't safely resolve order within one candle

        if sl_touched:
            result["sl_hit_at"] = candle_dt.strftime("%Y-%m-%d %H:%M:%S")
            break  # trade's over

        if target_touched:
            furthest = target_touched
            result["targets_hit"][target_touched] = candle_dt.strftime("%Y-%m-%d %H:%M:%S")
            if target_touched == 3:
                break  # furthest target reached, trade's done

    return result


class Command(BaseCommand):
    help = "Backfill blank SL/Target outcome columns in past signal logs using real Fyers historical option-premium candles."

    def add_arguments(self, parser):
        parser.add_argument("--start", required=True, help="YYYY-MM-DD")
        parser.add_argument("--end", required=True, help="YYYY-MM-DD")
        parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing anything.")

    def handle(self, *args, **options):
        start = datetime.strptime(options["start"], "%Y-%m-%d").date()
        end = datetime.strptime(options["end"], "%Y-%m-%d").date()
        dry_run = options["dry_run"]

        d = start
        while d <= end:
            date_str = d.strftime("%Y-%m-%d")
            path = _find_log_path(date_str)
            if not path:
                d += timedelta(days=1)
                continue

            self.stdout.write(f"\n--- {date_str} ({os.path.basename(path)}) ---")
            wb = load_workbook(path)
            ws = wb["Signals"]
            headers = [c.value for c in ws[1]]
            if headers != COLUMNS:
                self.stdout.write(self.style.WARNING("  Column layout doesn't match current schema -- skipping this file."))
                d += timedelta(days=1)
                continue

            col = {name: i + 1 for i, name in enumerate(COLUMNS)}
            changed = 0
            checked = 0

            for row_num in range(2, ws.max_row + 1):
                outcome = ws.cell(row=row_num, column=col["Outcome"]).value
                opt_symbol = ws.cell(row=row_num, column=col["Option Symbol"]).value
                sl = ws.cell(row=row_num, column=col["SL"]).value
                t1 = ws.cell(row=row_num, column=col["Target 1"]).value
                t2 = ws.cell(row=row_num, column=col["Target 2"]).value
                t3 = ws.cell(row=row_num, column=col["Target 3"]).value
                ts_raw = ws.cell(row=row_num, column=col["Timestamp"]).value

                if outcome or not opt_symbol or None in (sl, t1, t2, t3) or not ts_raw:
                    continue  # already resolved, or not enough stored to check

                try:
                    entry_dt = datetime.strptime(str(ts_raw), "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue

                checked += 1
                candles, err = _fetch_candles(opt_symbol, date_str)
                if not candles:
                    self.stdout.write(f"  row {row_num} ({opt_symbol}): no history ({err or 'empty'}) -- likely expired/invalid, skipped")
                    continue

                result = _replay(candles, entry_dt, sl, t1, t2, t3)

                if result["ambiguous"]:
                    note = f"AMBIGUOUS: SL and target both touched in same 1-min candle at {result['ambiguous'][0]}"
                    self.stdout.write(f"  row {row_num} ({opt_symbol}): {note}")
                    if not dry_run:
                        ws.cell(row=row_num, column=col["Outcome"]).value = note
                    changed += 1
                    continue

                furthest_hit = max(result["targets_hit"]) if result["targets_hit"] else 0
                if result["sl_hit_at"] and not result["targets_hit"]:
                    self.stdout.write(f"  row {row_num} ({opt_symbol}): SL Hit at {result['sl_hit_at']}")
                    if not dry_run:
                        ws.cell(row=row_num, column=col["SL Hit At"]).value = result["sl_hit_at"]
                        ws.cell(row=row_num, column=col["Outcome"]).value = "SL Hit"
                    changed += 1
                elif furthest_hit:
                    hit_time = result["targets_hit"][furthest_hit]
                    self.stdout.write(f"  row {row_num} ({opt_symbol}): Target {furthest_hit} Hit at {hit_time}")
                    if not dry_run:
                        for n, t in result["targets_hit"].items():
                            ws.cell(row=row_num, column=col[f"Target {n} Hit At"]).value = t
                        ws.cell(row=row_num, column=col["Outcome"]).value = f"Target {furthest_hit} Hit"
                    changed += 1
                else:
                    self.stdout.write(f"  row {row_num} ({opt_symbol}): no crossing found -- genuinely still open")

            if changed and not dry_run:
                wb.save(path)
            self.stdout.write(self.style.SUCCESS(f"  {changed}/{checked} rows {'would change' if dry_run else 'updated'}."))

            d += timedelta(days=1)
