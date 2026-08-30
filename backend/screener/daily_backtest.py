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
    "stock_pdf": None, "stock_summary": None, "stock_equity_curve": None, "stock_recent_trades": None,
    "stock_range_pdf": None,  # Aug 30 2026: same rich PDF format as stock_pdf, scoped to just this cycle's backfill window
    "nifty_pdf": None, "nifty_summary": None, "nifty_equity_curve": None, "nifty_recent_trades": None,
    "banknifty_pdf": None, "banknifty_summary": None, "banknifty_equity_curve": None, "banknifty_recent_trades": None,
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


def _serialize_equity_curve(curve):
    """Aug 27 2026: JSON-safe version of backtest_signal_pnl.py's
    compute_equity_curve() output -- its 'dt' field is a real Python
    datetime object there (fine for that module's own PDF/matplotlib
    use), which Response()/clean_json() can't serialize directly for
    an API response. Keeps every point, no downsampling -- one day's
    (or even a few weeks') worth of trades is small enough that this
    doesn't need the thinning Index Tracker's dense intraday logs do."""
    return [
        {"date": p["dt"].isoformat(), "cumulative_pnl": p["cumulative_pnl"], "equity": p["equity"]}
        for p in curve
    ]


def _serialize_trades(trades, limit=15):
    """
    Aug 27 2026: JSON-safe view of the most recent N trades (by exit
    date, most recent first) -- powers a Recent Trades table in the
    tab. Uses .get() throughout rather than assuming every field
    exists on every trade record: stock trades (backtest_signal_pnl.py's
    load_all_trades()) and index positional trades (backtest_index_
    positional.py's generate_positional_trades()) aren't guaranteed to
    carry identical fields (e.g. grade/sector are stock-specific
    concepts) -- this only surfaces what's actually there rather than
    fabricating a field that doesn't exist for one of the two sources.
    entry_dt/exit_dt/entry/exit_price/pnl/pnl_pct ARE guaranteed on
    both, though -- they're required inputs to compute_equity_curve()/
    compute_capital_base(), which both trade sources already feed
    successfully elsewhere in this file.
    """
    if not trades:
        return []
    sorted_trades = sorted(trades, key=lambda t: t["exit_dt"], reverse=True)[:limit]
    out = []
    for t in sorted_trades:
        out.append({
            "symbol": t.get("symbol"),
            "action": t.get("action"),
            "entry_dt": t["entry_dt"].isoformat() if t.get("entry_dt") else None,
            "exit_dt": t["exit_dt"].isoformat() if t.get("exit_dt") else None,
            "entry": t.get("entry"),
            "exit_price": t.get("exit_price"),
            "pnl": t.get("pnl"),
            "pnl_pct": t.get("pnl_pct"),
            "exit_reason": t.get("exit_reason"),
            "grade": t.get("grade"),  # None for index positional trades -- frontend just omits the badge when absent
        })
    return out


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

    stock_pdf, stock_summary, stock_equity_curve, stock_recent_trades = None, None, None, None
    stock_range_pdf = None
    try:
        from .backtest_signal_pnl import load_all_trades, compute_capital_base, compute_metrics, compute_equity_curve, write_pdf_report
        trades, excluded = load_all_trades()
        if trades:
            capital_base = compute_capital_base(trades)
            metrics = compute_metrics(trades, capital_base)
            if metrics:
                # Aug 27 2026: summary computed and exposed FIRST, before
                # PDF generation is even attempted -- these two used to
                # be set on the same line, which meant a PDF-only failure
                # (e.g. reportlab not installed) silently took the
                # numeric summary down with it too, even though
                # _summarize() has no PDF dependency at all. Caught live:
                # a real missing-reportlab error left the tab showing
                # "No trades yet" when real, computed trade data existed
                # the whole time. PDF generation now has its OWN
                # try/except so a rendering-library problem only costs
                # the download link, never the numbers themselves.
                stock_summary = _summarize(metrics)
                # Aug 27 2026: equity curve, same no-PDF-dependency
                # treatment -- compute_equity_curve() is pure trade-data
                # math (backtest_signal_pnl.py), no reportlab/matplotlib
                # involved, so it's exposed here unconditionally too.
                stock_equity_curve = _serialize_equity_curve(compute_equity_curve(trades, capital_base))
                # Aug 27 2026: same again for the Recent Trades table --
                # pure trade-data, no PDF dependency, exposed regardless.
                stock_recent_trades = _serialize_trades(trades)
                try:
                    stock_pdf = _run_and_rename(write_pdf_report, trades, metrics, f"signal_pnl_stock_{end_str}.pdf")
                except Exception as e:
                    print(f"[DailyBacktest] stock PDF generation failed (summary still available): {e}")
                    errors.append(f"stock PDF: {e}")

                # Aug 30 2026: ALSO generate a second PDF -- same rich
                # format as stock_pdf above (Scorecard/R-Multiple/Data
                # Quality/every section), scoped to just this cycle's
                # backfill window (start_str to end_str) instead of
                # full history. His own request: get both the complete
                # PDF and a recent-window PDF "in one go," in the same
                # report format, rather than the plain signal-list
                # Excel that window previously only got from the
                # backfill step above. Reuses run_range_report()
                # directly (own try/except, defined later in this same
                # module) rather than re-implementing its filter/
                # compute/write logic here -- the one cost is a second
                # load_all_trades() call, which is local xlsx parsing,
                # not a live Fyers call, so not a rate-limit concern.
                try:
                    stock_range_pdf = run_range_report(start_str, end_str)
                except Exception as e:
                    print(f"[DailyBacktest] stock range PDF generation failed: {e}")
                    errors.append(f"stock range PDF: {e}")
        else:
            print(f"[DailyBacktest] No resolved stock trades yet ({excluded} excluded) -- skipping stock PDF this cycle, not an error.")
    except Exception as e:
        print(f"[DailyBacktest] stock backtest failed: {e}")
        errors.append(f"stock backtest: {e}")

    index_results = {"NIFTY": (None, None, None, None), "BANKNIFTY": (None, None, None, None)}
    try:
        from .backtest_index_positional import generate_positional_trades, DEFAULT_MARGIN_PER_LOT
        from .backtest_signal_pnl import compute_capital_base, compute_metrics, compute_equity_curve, write_pdf_report
        for index_name in ("NIFTY", "BANKNIFTY"):
            try:
                trades, excluded = generate_positional_trades(index_name)
                if not trades:
                    print(f"[DailyBacktest] No {index_name} positional trades yet ({excluded} excluded) -- skipping, not an error.")
                    continue
                capital_base = compute_capital_base(trades, capital_per_trade=DEFAULT_MARGIN_PER_LOT.get(index_name, 200000), use_real_committed=False)  # Aug 30 2026: margin-based futures, not premium-buying -- keep the original flat-slot model, not the new real-committed one
                metrics = compute_metrics(trades, capital_base)
                if metrics:
                    # Same decoupling as the stock section above -- summary,
                    # equity curve, AND recent trades all exposed regardless
                    # of whether PDF rendering succeeds.
                    summary = _summarize(metrics)
                    equity_curve = _serialize_equity_curve(compute_equity_curve(trades, capital_base))
                    recent_trades = _serialize_trades(trades)
                    pdf_path = None
                    try:
                        pdf_path = _run_and_rename(write_pdf_report, trades, metrics, f"index_positional_{index_name}_{end_str}.pdf")
                    except Exception as e:
                        print(f"[DailyBacktest] {index_name} PDF generation failed (summary still available): {e}")
                        errors.append(f"{index_name} PDF: {e}")
                    index_results[index_name] = (pdf_path, summary, equity_curve, recent_trades)
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
        "stock_pdf": stock_pdf, "stock_summary": stock_summary, "stock_equity_curve": stock_equity_curve, "stock_recent_trades": stock_recent_trades,
        "stock_range_pdf": stock_range_pdf,
        "nifty_pdf": index_results["NIFTY"][0], "nifty_summary": index_results["NIFTY"][1], "nifty_equity_curve": index_results["NIFTY"][2], "nifty_recent_trades": index_results["NIFTY"][3],
        "banknifty_pdf": index_results["BANKNIFTY"][0], "banknifty_summary": index_results["BANKNIFTY"][1], "banknifty_equity_curve": index_results["BANKNIFTY"][2], "banknifty_recent_trades": index_results["BANKNIFTY"][3],
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

            # Aug 30 2026: ALSO send the range-scoped stock PDF as a
            # second document in the same cycle, right after the
            # complete-history one -- his own request, "same PDF
            # format, one is complete, other is date range, in one
            # go." Its own try/except: a failure here shouldn't hide
            # the fact that the main PDF above already sent
            # successfully. Uses the same send_document(path, caption)
            # call already confirmed working just above, not a new
            # method.
            if stock_range_pdf:
                try:
                    range_caption = (
                        f"\U0001F4CA <b>F&O Radar \u2014 Last {backfill_days} Days ({start_str} to {end_str})</b>\n"
                        f"Same report format as above, just this window instead of full history."
                    )
                    bot.send_document(stock_range_pdf, caption=range_caption)
                except Exception as e:
                    print(f"[DailyBacktest] stock range PDF Telegram send failed: {e}")
                    errors.append(f"stock range PDF Telegram send: {e}")
        else:
            print("[DailyBacktest] Nothing to send to Telegram this cycle (no reports generated yet).")
    except Exception as e:
        print(f"[DailyBacktest] Telegram summary failed: {e}")

    return result


def _filter_trades_by_range(trades, start_date, end_date):
    """Keep only trades whose EXIT falls within [start_date, end_date]
    (inclusive, by calendar date). Exit date is what
    compute_equity_curve() orders by and what P&L is realized on, so
    filtering by exit (not entry) matches what the resulting chart
    actually shows -- a trade that entered before the window but
    exited inside it is included; one that entered inside but hasn't
    exited yet (still open) is correctly excluded either way, same as
    load_all_trades()'s own "unresolved rows aren't counted" rule."""
    return [t for t in trades if start_date <= t["exit_dt"].date() <= end_date]


def run_range_backtest(start_str, end_str):
    """
    Aug 27 2026: on-demand, date-range-filtered backtest -- powers the
    date-range picker in the Daily Backtest tab, so a specific window
    (e.g. "just this week") can be viewed instead of always seeing
    everything ever logged. Pure read/compute, NO side effects: does
    not write a PDF, does not touch the scheduled cycle's cached
    _last_run, does not send to Telegram -- those stay reserved for
    the real scheduled/manual full cycle (run_daily_backtest_cycle
    above). This is a fast preview computation only, safe to call as
    often as someone drags the date picker.

    Raises ValueError if start_str/end_str aren't valid YYYY-MM-DD --
    caller (the API view) is expected to turn that into a 400, not a
    500.

    Returns {'stock': {...}, 'nifty': {...}, 'banknifty': {...}}, each
    shaped {'summary': ..., 'equity_curve': ..., 'recent_trades': ...}
    (same shapes _summarize()/_serialize_equity_curve()/
    _serialize_trades() already produce elsewhere) with all three None
    if nothing fell inside the requested range.
    """
    try:
        start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise ValueError("start/end must be YYYY-MM-DD")

    result = {
        "stock": {"summary": None, "equity_curve": None, "recent_trades": None},
        "nifty": {"summary": None, "equity_curve": None, "recent_trades": None},
        "banknifty": {"summary": None, "equity_curve": None, "recent_trades": None},
    }

    try:
        from .backtest_signal_pnl import load_all_trades, compute_capital_base, compute_metrics, compute_equity_curve
        all_trades, _ = load_all_trades()
        trades = _filter_trades_by_range(all_trades, start_date, end_date)
        if trades:
            capital_base = compute_capital_base(trades)
            metrics = compute_metrics(trades, capital_base)
            if metrics:
                result["stock"]["summary"] = _summarize(metrics)
                result["stock"]["equity_curve"] = _serialize_equity_curve(compute_equity_curve(trades, capital_base))
                result["stock"]["recent_trades"] = _serialize_trades(trades)
    except Exception as e:
        print(f"[DailyBacktest] range stock backtest failed: {e}")

    try:
        from .backtest_index_positional import generate_positional_trades, DEFAULT_MARGIN_PER_LOT
        from .backtest_signal_pnl import compute_capital_base, compute_metrics, compute_equity_curve
        for index_name, key in (("NIFTY", "nifty"), ("BANKNIFTY", "banknifty")):
            try:
                all_trades, _ = generate_positional_trades(index_name)
                trades = _filter_trades_by_range(all_trades, start_date, end_date)
                if trades:
                    capital_base = compute_capital_base(trades, capital_per_trade=DEFAULT_MARGIN_PER_LOT.get(index_name, 200000), use_real_committed=False)  # Aug 30 2026: margin-based futures, not premium-buying -- keep the original flat-slot model, not the new real-committed one
                    metrics = compute_metrics(trades, capital_base)
                    if metrics:
                        result[key]["summary"] = _summarize(metrics)
                        result[key]["equity_curve"] = _serialize_equity_curve(compute_equity_curve(trades, capital_base))
                        result[key]["recent_trades"] = _serialize_trades(trades)
            except Exception as e:
                print(f"[DailyBacktest] range {index_name} backtest failed: {e}")
    except Exception as e:
        print(f"[DailyBacktest] range index import failed: {e}")

    return result


def run_range_report(start_str, end_str):
    """
    Aug 29 2026: the actual downloadable PDF for a specific date range
    -- the missing piece run_range_backtest() was never meant to be.
    That function is a fast JSON preview only, by its own explicit
    design (see its docstring: "Pure preview computation: no PDF
    written"). This is the real counterpart: filters trades to
    [start, end] with the same already-tested _filter_trades_by_range()
    used above, then runs them through the EXACT SAME compute_metrics()
    / write_pdf_report() pipeline the full daily-cycle stock PDF uses
    -- meaning a range PDF gets the identical Strategy Scorecard/
    R-Multiple/Long vs Short/every other section the full report has,
    not a stripped-down version.

    Does NOT touch the scheduled cycle's cached _last_run and does NOT
    send to Telegram -- same isolation run_range_backtest() already
    keeps for the preview path. The one real side effect a
    *downloadable* report can't avoid is writing a PDF to disk, which
    this does via the same _run_and_rename() collision-fix already
    used elsewhere in this file, under a range-specific filename
    (signal_pnl_stock_<start>_to_<end>.pdf) so it never collides with
    the scheduled cycle's own signal_pnl_stock_<today>.pdf.

    Raises ValueError for a bad date string, same contract as
    run_range_backtest() -- caller (the API view) should turn that
    into a 400. Returns None if there are zero resolved stock trades
    inside the requested range (caller should turn that into a 404,
    not a 500 or a technically-successful empty PDF).
    """
    try:
        start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise ValueError("start/end must be YYYY-MM-DD")

    from .backtest_signal_pnl import load_all_trades, compute_capital_base, compute_metrics, write_pdf_report
    all_trades, _ = load_all_trades()
    trades = _filter_trades_by_range(all_trades, start_date, end_date)
    if not trades:
        return None

    capital_base = compute_capital_base(trades)
    metrics = compute_metrics(trades, capital_base)
    if not metrics:
        return None

    return _run_and_rename(write_pdf_report, trades, metrics, f"signal_pnl_stock_{start_str}_to_{end_str}.pdf")


def run_daily_backtest_cycle_async(trigger="manual", backfill_days=7):
    """Fire-and-forget wrapper for the API-triggered 'Run Now' button --
    the full cycle can take a while (real Fyers history calls per
    unresolved row, real PDF generation), so the endpoint returns
    immediately rather than holding the HTTP request open for it.
    Frontend polls the status endpoint (compare 'started_at') to see
    when it's finished."""
    threading.Thread(target=run_daily_backtest_cycle, args=(trigger, backfill_days), daemon=True).start()
