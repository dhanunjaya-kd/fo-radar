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

Aug 14 2026 UPDATE -- two additions:

1. EOD CLOSING ESTIMATE for rows where neither SL nor any Target was
   crossed. A "no crossing" result used to just stay blank forever, which
   is honest but incomplete once the trading day is actually over -- the
   position DID end up somewhere, it just never hit either threshold.
   Now, for any such row on a day that has fully closed, this looks up
   the closing candle (at the row's own "Exited At" time if that's known,
   otherwise the day's last available candle as an end-of-day estimate)
   and writes a descriptive Outcome noting it's an estimate, e.g.
   "Closed up ~28.4 (+6.2% from entry, EOD estimate)". Still never
   touches SL Hit At / Target N Hit At -- neither was actually crossed,
   so those columns correctly stay blank.

2. COMPLETE REPORT: after processing the date range, builds ONE
   consolidated workbook covering every signal in that range (not just
   the ones that were blank) -- Date/Symbol/Action/Entry/Outcome/P&L%,
   one row per signal -- saved to signal_logs/backfill_reports/. P&L% is
   computed uniformly: from SL/Target's stored level vs Entry for rows
   resolved that way (live or backfilled), from the EOD estimate above
   for closed-flat rows, and left blank (labeled, not guessed) for
   anything that still has no resolution at all (e.g. Fyers had no
   candles for that symbol).

HONEST LIMITATIONS:
- 1-minute OHLC, not tick data. If SL and a target both fall inside the
  same candle's range, which came first genuinely can't be known from
  OHLC alone -- the row is marked "AMBIGUOUS (see note)" rather than
  guessing, with both candidate times recorded in a note column.
- Fyers' History API only serves ACTIVE (non-expired) contracts. Once a
  strike's expiry passes, this can no longer backfill it -- run this
  before expiry, not after.
- The EOD closing estimate is exactly that -- an ESTIMATE from the last
  available candle (or the candle nearest a known exit time), not a
  live-confirmed exit price. Every such row says "EOD estimate" in the
  Outcome text so it's never confused with a real tracked exit.
- This only checks the ENTRY day's candles (signals here are same-day/MIS
  style, squared off by market close) -- a position genuinely held
  overnight would need the script extended to pull more than one day.

Usage:
    cd backend
    venv\\Scripts\\activate
    python manage.py backfill_signal_outcomes --start 2026-08-10 --end 2026-08-14 --dry-run
    python manage.py backfill_signal_outcomes --start 2026-08-10 --end 2026-08-14
"""
import os
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, PatternFill

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


def _closing_estimate(candles, entry_dt, entry_price, exited_dt=None):
    """When no SL/Target crossing was found: the closing candle at (or
    just before) the row's own Exited At time if known, otherwise the
    day's last available candle as an end-of-day estimate. Returns
    (close_price, pct_from_entry, is_estimate) or (None, None, None) if
    there's nothing usable to compute from."""
    usable = [c for c in candles if datetime.fromtimestamp(c[0]) >= entry_dt]
    if not usable or not entry_price:
        return None, None, None
    if exited_dt is not None:
        before = [c for c in usable if datetime.fromtimestamp(c[0]) <= exited_dt]
        chosen = before[-1] if before else usable[-1]
        is_estimate = not bool(before)
    else:
        chosen = usable[-1]
        is_estimate = True
    close_price = chosen[4]
    pct = round((close_price - entry_price) / entry_price * 100, 2)
    return close_price, pct, is_estimate


def _pnl_pct_from_outcome(outcome, entry, sl, t1, t2, t3):
    """For the complete report: derive a numeric P&L% from whatever the
    Outcome cell says, uniformly, whether it was resolved live, by an
    earlier backfill run, or by this run's new EOD-estimate logic. Never
    recomputes anything not already implied by stored, locked values --
    just reads what "SL Hit" / "Target N Hit" / the EOD-estimate text
    already commit to."""
    if not outcome or not entry:
        return None
    if outcome == "SL Hit":
        return round((sl - entry) / entry * 100, 2) if sl else None
    if outcome.startswith("Target"):
        try:
            n = int(outcome.split()[1])
        except Exception:
            return None
        level = {1: t1, 2: t2, 3: t3}.get(n)
        return round((level - entry) / entry * 100, 2) if level else None
    if "% from entry" in outcome:
        try:
            frag = outcome.split("(")[1].split("%")[0].replace("+", "")
            return round(float(frag), 2)
        except Exception:
            return None
    return None  # AMBIGUOUS, or anything else not confidently parseable


class Command(BaseCommand):
    help = "Backfill blank SL/Target outcome columns using real Fyers historical candles, estimate EOD close for anything that never crossed either level, and build one consolidated report for the date range."

    def add_arguments(self, parser):
        parser.add_argument("--start", required=True, help="YYYY-MM-DD")
        parser.add_argument("--end", required=True, help="YYYY-MM-DD")
        parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing anything to the signal logs (the complete report is still generated as a preview).")

    def handle(self, *args, **options):
        start = datetime.strptime(options["start"], "%Y-%m-%d").date()
        end = datetime.strptime(options["end"], "%Y-%m-%d").date()
        dry_run = options["dry_run"]

        report_rows = []  # collected across every day for the final consolidated report

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
            closed_flat = 0

            for row_num in range(2, ws.max_row + 1):
                symbol = ws.cell(row=row_num, column=col["Symbol"]).value
                action = ws.cell(row=row_num, column=col["Action"]).value
                grade = ws.cell(row=row_num, column=col["Grade"]).value
                outcome = ws.cell(row=row_num, column=col["Outcome"]).value
                opt_symbol = ws.cell(row=row_num, column=col["Option Symbol"]).value
                entry = ws.cell(row=row_num, column=col["Entry (Premium)"]).value
                sl = ws.cell(row=row_num, column=col["SL"]).value
                t1 = ws.cell(row=row_num, column=col["Target 1"]).value
                t2 = ws.cell(row=row_num, column=col["Target 2"]).value
                t3 = ws.cell(row=row_num, column=col["Target 3"]).value
                ts_raw = ws.cell(row=row_num, column=col["Timestamp"]).value
                exited_raw = ws.cell(row=row_num, column=col["Exited At"]).value

                if not symbol:
                    continue

                needs_backfill = not outcome and opt_symbol and None not in (sl, t1, t2, t3, entry) and ts_raw
                if needs_backfill:
                    entry_dt = None
                    try:
                        entry_dt = datetime.strptime(str(ts_raw), "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        pass

                    if entry_dt:
                        checked += 1
                        candles, err = _fetch_candles(opt_symbol, date_str)
                        if candles is None:
                            # Real fetch failure -- expired/invalid symbol, bad request, etc.
                            # Genuinely nothing to backfill from; left blank as before.
                            self.stdout.write(f"  row {row_num} ({opt_symbol}): fetch failed ({err or 'no response'}) -- likely expired/invalid, skipped")
                        elif not candles:
                            # Fyers responded fine but with zero candles -- the contract had
                            # no trades after entry (e.g. entered on a burst of volume that
                            # never repeated that day). There's no OHLC to estimate a close
                            # from, so this can't get a real EOD-estimate price -- but it
                            # shouldn't sit silently blank forever either.
                            note = "No trade data after entry (0 candles) -- likely zero volume, unresolved"
                            self.stdout.write(f"  row {row_num} ({opt_symbol}): {note}")
                            if not dry_run:
                                ws.cell(row=row_num, column=col["Outcome"]).value = note
                            changed += 1
                            outcome = note
                        else:
                            result = _replay(candles, entry_dt, sl, t1, t2, t3)

                            if result["ambiguous"]:
                                note = f"AMBIGUOUS: SL and target both touched in same 1-min candle at {result['ambiguous'][0]}"
                                self.stdout.write(f"  row {row_num} ({opt_symbol}): {note}")
                                if not dry_run:
                                    ws.cell(row=row_num, column=col["Outcome"]).value = note
                                changed += 1
                                outcome = note

                            else:
                                furthest_hit = max(result["targets_hit"]) if result["targets_hit"] else 0
                                if result["sl_hit_at"] and not result["targets_hit"]:
                                    self.stdout.write(f"  row {row_num} ({opt_symbol}): SL Hit at {result['sl_hit_at']}")
                                    if not dry_run:
                                        ws.cell(row=row_num, column=col["SL Hit At"]).value = result["sl_hit_at"]
                                        ws.cell(row=row_num, column=col["Outcome"]).value = "SL Hit"
                                    changed += 1
                                    outcome = "SL Hit"
                                elif furthest_hit:
                                    hit_time = result["targets_hit"][furthest_hit]
                                    self.stdout.write(f"  row {row_num} ({opt_symbol}): Target {furthest_hit} Hit at {hit_time}")
                                    if not dry_run:
                                        for n, t in result["targets_hit"].items():
                                            ws.cell(row=row_num, column=col[f"Target {n} Hit At"]).value = t
                                        ws.cell(row=row_num, column=col["Outcome"]).value = f"Target {furthest_hit} Hit"
                                    changed += 1
                                    outcome = f"Target {furthest_hit} Hit"
                                else:
                                    # No crossing at all -- estimate the EOD close instead
                                    # of leaving this ambiguously blank, now that the day
                                    # is fully closed.
                                    exited_dt = None
                                    if exited_raw:
                                        try:
                                            exited_dt = datetime.strptime(str(exited_raw), "%Y-%m-%d %H:%M:%S")
                                        except Exception:
                                            pass
                                    close_price, pct, is_estimate = _closing_estimate(candles, entry_dt, entry, exited_dt)
                                    if close_price is not None:
                                        label = "Closed flat" if abs(pct) < 0.5 else ("Closed up" if pct > 0 else "Closed down")
                                        suffix = ", EOD estimate" if is_estimate else ""
                                        note = f"{label} ~{close_price} ({pct:+.1f}% from entry{suffix})"
                                        self.stdout.write(f"  row {row_num} ({opt_symbol}): {note}")
                                        if not dry_run:
                                            ws.cell(row=row_num, column=col["Outcome"]).value = note
                                        changed += 1
                                        closed_flat += 1
                                        outcome = note
                                    else:
                                        self.stdout.write(f"  row {row_num} ({opt_symbol}): no crossing and no closing price available -- left blank")

                report_rows.append({
                    "date": date_str, "symbol": symbol, "action": action, "grade": grade,
                    "entry": entry, "outcome": outcome,
                    "pnl_pct": _pnl_pct_from_outcome(outcome, entry, sl, t1, t2, t3),
                })

            if changed and not dry_run:
                wb.save(path)
            self.stdout.write(self.style.SUCCESS(
                f"  {changed}/{checked} rows {'would change' if dry_run else 'updated'} "
                f"({closed_flat} of those newly closed-flat via EOD estimate)."
            ))

            d += timedelta(days=1)

        self._write_complete_report(report_rows, options["start"], options["end"], dry_run)

    def _write_complete_report(self, report_rows, start_str, end_str, dry_run):
        wb = Workbook()
        ws = wb.active
        ws.title = "Complete Report"
        headers = ["Date", "Symbol", "Action", "Grade", "Entry (Premium)", "Outcome", "P&L %"]
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")

        resolved, unresolved = 0, 0
        pnl_values = []
        for r in report_rows:
            ws.append([r["date"], r["symbol"], r["action"], r["grade"], r["entry"], r["outcome"] or "Unresolved (no data)", r["pnl_pct"]])
            if r["outcome"]:
                resolved += 1
            else:
                unresolved += 1
            if r["pnl_pct"] is not None:
                pnl_values.append(r["pnl_pct"])

        for col_cells in ws.columns:
            max_len = max(len(str(c.value)) for c in col_cells)
            ws.column_dimensions[col_cells[0].column_letter].width = max(max_len + 2, 10)

        out_dir = os.path.join(LOG_DIR, "backfill_reports")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"complete_report_{start_str}_to_{end_str}.xlsx")
        wb.save(path)

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"  Complete report: {len(report_rows)} signals, {resolved} resolved, {unresolved} still unresolved")
        if pnl_values:
            avg_pnl = round(sum(pnl_values) / len(pnl_values), 2)
            wins = sum(1 for v in pnl_values if v > 0)
            self.stdout.write(f"  Avg P&L% (of {len(pnl_values)} rows with a computable figure): {avg_pnl:+.2f}%, {wins}/{len(pnl_values)} positive")
        self.stdout.write(f"  Saved: {path}")
        self.stdout.write(f"{'=' * 60}")

        if dry_run:
            self.stdout.write("  (dry run -- not sending to Telegram; the signal logs weren't actually updated either)")
            return

        try:
            from trading.telegram_bot import TelegramBot
            bot = TelegramBot()
            caption = (
                f"📊 <b>F&O Radar — Backfill Complete Report</b>\n"
                f"{os.path.basename(path)}\n"
                f"{len(report_rows)} signals, {resolved} resolved, {unresolved} unresolved"
            )
            result = bot.send_document(path, caption=caption)
            if result and result.get("ok"):
                self.stdout.write(self.style.SUCCESS("Sent to Telegram."))
            else:
                self.stdout.write(self.style.WARNING(f"Report saved but Telegram send didn't confirm success: {result}"))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Report saved but Telegram send failed: {e}"))