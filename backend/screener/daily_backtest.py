"""
screener/daily_backtest.py

Aug 27 2026: the full checklist (backfill -> stock signal P&L backtest
-> NIFTY positional backtest -> BANKNIFTY positional backtest) as ONE
callable cycle, instead of running each script by hand. Runs
automatically twice a day via a new background worker thread in
views.py (matches the existing daemon-thread pattern already used for
the stock scanner, index snapshots, and news alerts -- no Celery/Redis
needed here either), and can also be triggered on demand via a new API
endpoint for a genuine single-click run.

Reuses every script's REAL, already-tested functions directly -- no
subprocess calls, no re-implementation. backfill_signal_outcomes is a
Django management Command, invoked via call_command() (the standard
way to run one programmatically); backtest_signal_pnl.py and
backtest_index_positional.py are plain importable modules, called the
same way their own __main__ blocks already do.

FILE-COLLISION FIX: backtest_signal_pnl.py's write_pdf_report() always
targets the SAME 'signal_pnl_backtest_{today}.pdf' path regardless of
caller -- correct for its normal single-run use, but calling it 3
times in one cycle here (stock, NIFTY positional, BANKNIFTY
positional) would otherwise have each call silently overwrite the
previous one's PDF (no exception -- SimpleDocTemplate happily
overwrites an existing unlocked file). _run_and_rename() below calls
it, then immediately renames the output to a distinct, stable filename
BEFORE the next call starts -- a pure orchestration-level fix; nothing
in the already-tested engine itself needed to change.
"""
import os
import shutil
import threading
from datetime import datetime, timedelta

from django.core.management import call_command

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "signal_logs")

_lock = threading.Lock()
# Latest cycle's results -- read by DailyBacktestStatusView and the
# frontend tab. A None *_pdf field means that piece genuinely produced
# nothing this cycle (e.g. no NIFTY flips logged yet -- expected early
# on, not an error); check 'errors' for real failures.
_last_run = {
    "started_at": None, "finished_at": None, "trigger": None,  # 'scheduled-close' | 'scheduled-morning' | 'manual'
    "backfill_range": None,
    "stock_pdf": None, "stock_summary": None,
    "nifty_pdf": None, "nifty_summary": None,
    "banknifty_pdf": None, "banknifty_summary": None,
    "errors": [],
}


def get_last_run():
    """Read-only snapshot of the latest cycle's results."""
    with _lock:
        return dict(_last_run)


def _run_and_rename(write_fn, trades, metrics, final_name):
    """See module docstring's FILE-COLLISION FIX note. write_fn is
    always backtest_signal_pnl.write_pdf_report, passed in rather than
    imported at module level so this stays easily testable against a
    stub."""
    raw_path = write_fn(trades, metrics)
    final_path = os.path.join(os.path.dirname(raw_path), final_name)
    if os.path.exists(final_path):
        os.remove(final_path)  # overwrite same-day re-run (2nd run today) or yesterday's leftover -- want the freshest
    shutil.move(raw_path, final_path)
    return final_path


def _summarize(metrics):
    """Small subset of metrics for the status endpoint/tab -- enough
    for an at-a-glance card, not the full PDF. Only reads keys
    print_summary() (backtest_signal_pnl.py) already confirms exist."""
    if not metrics:
        return None
    return {
        "total_trades": metrics.get("total_trades"),
        "net_pnl": metrics.get("net_pnl"),
        "net_pnl_pct": metrics.get("net_pnl_pct"),
        "win_rate_pct": metrics.get("win_rate_pct"),
        "profit_factor": metrics.get("profit_factor"),
        "sharpe": metrics.get("sharpe"),
    }


def run_daily_backtest_cycle(trigger="manual", backfill_days=7):
    """
    The full checklist, in order:
      1. backfill_signal_outcomes for the last `backfill_days` days --
         catches anything a missed/restarted day left unresolved
         before generating reports off of it (this project's own
         earlier "43 excluded" lesson: backfill has to run BEFORE the
         backtests, not after).
      2. Stock signal P&L backtest.
      3. NIFTY positional backtest.
      4. BANKNIFTY positional backtest.

    Each step is wrapped independently -- one step failing (or
    genuinely having nothing to report yet, e.g. no NIFTY flips logged
    so far) doesn't block the others. Real exceptions are caught and
    recorded in the result's 'errors' list rather than raised -- this
    runs inside a daemon worker thread; an uncaught exception there
    would silently kill background snapshotting/signal-generation too,
    not just this cycle.
    """
    started_at = datetime.now()
    errors = []

    end_str = started_at.strftime("%Y-%m-%d")
    start_str = (started_at - timedelta(days=backfill_days)).strftime("%Y-%m-%d")

    try:
        call_command("backfill_signal_outcomes", start=start_str, end=end_str)
    except Exception as e:
        print(f"[DailyBacktest] backfill failed: {e}")
        errors.append(f"backfill: {e}")

    stock_pdf, stock_summary = None, None
    try:
        from .backtest_signal_pnl import load_all_trades, compute_capital_base, compute_metrics, write_pdf_report
        trades, excluded = load_all_trades()
        if trades:
            capital_base = compute_capital_base(trades)
            metrics = compute_metrics(trades, capital_base)
            if metrics:
                stock_pdf = _run_and_rename(write_pdf_report, trades, metrics, f"signal_pnl_stock_{end_str}.pdf")
                stock_summary = _summarize(metrics)
        else:
            print(f"[DailyBacktest] No resolved stock trades yet ({excluded} excluded) -- skipping stock PDF this cycle, not an error.")
    except Exception as e:
        print(f"[DailyBacktest] stock backtest failed: {e}")
        errors.append(f"stock backtest: {e}")

    index_results = {"NIFTY": (None, None), "BANKNIFTY": (None, None)}
    try:
        from .backtest_index_positional import generate_positional_trades, DEFAULT_MARGIN_PER_LOT
        from .backtest_signal_pnl import compute_capital_base, compute_metrics, write_pdf_report
        for index_name in ("NIFTY", "BANKNIFTY"):
            try:
                trades, excluded = generate_positional_trades(index_name)
                if not trades:
                    print(f"[DailyBacktest] No {index_name} positional trades yet ({excluded} excluded) -- skipping, not an error.")
                    continue
                capital_base = compute_capital_base(trades, capital_per_trade=DEFAULT_MARGIN_PER_LOT.get(index_name, 200000))
                metrics = compute_metrics(trades, capital_base)
                if metrics:
                    pdf_path = _run_and_rename(write_pdf_report, trades, metrics, f"index_positional_{index_name}_{end_str}.pdf")
                    index_results[index_name] = (pdf_path, _summarize(metrics))
            except Exception as e:
                print(f"[DailyBacktest] {index_name} positional backtest failed: {e}")
                errors.append(f"{index_name} positional: {e}")
    except Exception as e:
        print(f"[DailyBacktest] index positional import failed: {e}")
        errors.append(f"index positional import: {e}")

    result = {
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now().isoformat(),
        "trigger": trigger,
        "backfill_range": f"{start_str} to {end_str}",
        "stock_pdf": stock_pdf, "stock_summary": stock_summary,
        "nifty_pdf": index_results["NIFTY"][0], "nifty_summary": index_results["NIFTY"][1],
        "banknifty_pdf": index_results["BANKNIFTY"][0], "banknifty_summary": index_results["BANKNIFTY"][1],
        "errors": errors,
    }
    with _lock:
        global _last_run
        _last_run = result

    # Aug 27 2026: same Telegram-document pattern already confirmed
    # working elsewhere in this project (WeeklyReportView, backfill's
    # own complete-report send) -- send whichever PDF came out of this
    # cycle FIRST, with a combined caption covering all three, rather
    # than 3 separate Telegram messages. Only uses TelegramBot's
    # already-confirmed send_document(path, caption) signature -- not
    # guessing at a send_message() method this project's TelegramBot
    # was never shown to have.
    try:
        first_pdf = stock_pdf or index_results["NIFTY"][0] or index_results["BANKNIFTY"][0]
        if first_pdf:
            caption_lines = [f"\U0001F4CA <b>F&O Radar \u2014 Daily Backtest ({trigger})</b>"]
            if stock_summary:
                caption_lines.append(f"Stock: {stock_summary['total_trades']} trades, Net {stock_summary['net_pnl_pct']}%, Win {stock_summary['win_rate_pct']}%")
            for name in ("NIFTY", "BANKNIFTY"):
                s = index_results[name][1]
                if s:
                    caption_lines.append(f"{name}: {s['total_trades']} trades, Net {s['net_pnl_pct']}%, Win {s['win_rate_pct']}%")
            if errors:
                caption_lines.append(f"\u26A0 {len(errors)} step(s) had errors \u2014 check server logs.")
            from trading.telegram_bot import TelegramBot
            bot = TelegramBot()
            bot.send_document(first_pdf, caption="\n".join(caption_lines))
        else:
            print("[DailyBacktest] Nothing to send to Telegram this cycle (no reports generated yet).")
    except Exception as e:
        print(f"[DailyBacktest] Telegram summary failed: {e}")

    return result


def run_daily_backtest_cycle_async(trigger="manual", backfill_days=7):
    """Fire-and-forget wrapper for the API-triggered 'Run Now' button --
    the full cycle can take a while (real Fyers history calls per
    unresolved row, real PDF generation), so the endpoint returns
    immediately rather than holding the HTTP request open for it.
    Frontend polls the status endpoint (compare 'started_at') to see
    when it's finished."""
    threading.Thread(target=run_daily_backtest_cycle, args=(trigger, backfill_days), daemon=True).start()
