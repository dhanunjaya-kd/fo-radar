"""
screener/backtest_signal_pnl.py

Replays every RESOLVED signal from the daily signal_logs (signals_YYYY-
MM-DD.xlsx) at a fixed hypothetical position size, and produces a full
Excel performance report -- Net P&L, CAGR, Max Drawdown, Sharpe/Sortino/
Calmar, Profit Factor, Win Rate, an equity curve, a drawdown chart, a
daily-return histogram, monthly performance, and a worst-drawdowns
table. Modeled directly on a real TradeTron strategy report he shared
as the reference for what "good" looks like.

CAPITAL: every trade is sized at ~Rs 50,000 (DEFAULT_CAPITAL_PER_TRADE
below), overriding whatever "Qty" was actually logged live -- this
isn't a new number invented for backtesting, it's the exact same
qty = max(1, int(50000 / entry)) fallback already used in views.py.
Using it UNIFORMLY for every trade here (rather than trusting whatever
Qty happened to be live at signal time) isolates the strategy's real
quality from position-sizing variance -- standard backtesting practice.

HONEST METHODOLOGY NOTE, worth reading before trusting the output:
this is a signal-by-signal strategy (many trades a day, not one
continuously-compounding position), not a single equity curve the way
a single strategy on one instrument would have. This report treats
"capital base" as 50000 x (the real maximum number of trades open
simultaneously anywhere in the backtest, computed from actual entry/
exit timestamps) -- an honest, non-arbitrary number, not a guessed
round figure. CAGR/Sharpe/Sortino/Calmar are all computed against that
base. The equity curve is built by processing every trade's REALIZED
P&L in chronological exit order -- a real, defensible curve, though it
doesn't model intraday margin usage the way a live broker statement
would.

Outcome strings are parsed EXACTLY as check_outcomes() (excel_logger.py)
and backfill_signal_outcomes.py write them -- "SL Hit", "Target N Hit",
the EOD-estimate strings ("Closed up ~28.4 (+6.2% from entry, EOD
estimate)"), or anything else (e.g. the zero-volume "unresolved" note)
is treated as NOT having a real exit price and excluded from P&L
entirely -- same "skip rather than fabricate" rule as every other
script in this project. A trade with no Outcome at all (still open,
or never resolved) is also excluded, not counted as a loss or a win.

Run as a standalone script:
    cd backend
    venv\\Scripts\\activate
    python -m screener.backtest_signal_pnl
"""
import os
import re
import glob
from datetime import datetime, timedelta
from collections import defaultdict

try:
    from openpyxl import load_workbook, Workbook
except ImportError:
    load_workbook = None

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "signal_logs")
DEFAULT_CAPITAL_PER_TRADE = 50000  # matches views.py's existing qty = max(1, int(50000/entry)) fallback

_TARGET_RE = re.compile(r'^Target (\d) Hit$')
_EOD_ESTIMATE_RE = re.compile(r'^Closed (?:up|down|flat) ~([\d.]+) \([+-][\d.]+% from entry(?:, EOD estimate)?\)$')


def parse_outcome(outcome_str, sl, target1, target2, target3):
    """
    Turns the exact Outcome string this project's own logging already
    writes into a concrete exit price. Returns (exit_price, reason) --
    exit_price is None if this trade genuinely has no real exit price
    to compute P&L from (still open, or an unresolved/no-data note);
    callers must exclude those from P&L, never substitute a guess.
    """
    if not outcome_str:
        return None, "no outcome recorded (still open or unresolved)"

    if outcome_str == "SL Hit":
        return sl, "SL Hit"

    m = _TARGET_RE.match(outcome_str)
    if m:
        n = int(m.group(1))
        target = {1: target1, 2: target2, 3: target3}.get(n)
        return target, f"Target {n} Hit"

    m = _EOD_ESTIMATE_RE.match(outcome_str)
    if m:
        return float(m.group(1)), outcome_str

    # Anything else (e.g. the zero-volume "No trade data..." note) --
    # genuinely nothing real to price this trade's exit from.
    return None, outcome_str


def list_signal_log_dates():
    """Every date with a real signals log, newest first. Checks both
    layouts (nested signal_logs/YYYY-MM-DD/ and the old flat one),
    same as excel_logger.py's own list_available_dates() -- kept as a
    separate copy here rather than importing it, since this file is
    designed to also run as a fully standalone script without needing
    the Django app importable (matches backtest_index_bias.py's own
    standalone-first design)."""
    dates = set()
    pattern = re.compile(r'signals_(\d{4}-\d{2}-\d{2})\.xlsx$')
    for path in glob.glob(os.path.join(LOG_DIR, "signals_*.xlsx")):
        m = pattern.search(os.path.basename(path))
        if m:
            dates.add(m.group(1))
    for path in glob.glob(os.path.join(LOG_DIR, "*", "signals_*.xlsx")):
        m = pattern.search(os.path.basename(path))
        if m:
            dates.add(m.group(1))
    return sorted(dates, reverse=True)


def _resolve_exit_datetime(row, outcome_str, date_str):
    """Best real timestamp available for when a trade actually closed.
    SL/Target hits have their own logged timestamp -- use that exactly.
    An EOD estimate has no such timestamp (nothing was actually
    crossed); fall back to "Exited At" if the row has one, otherwise
    to a fixed 15:30 IST end-of-day time for that date -- a documented
    approximation, not a real logged moment, since none exists for
    that case."""
    if outcome_str == "SL Hit" and row.get("SL Hit At"):
        try:
            return datetime.strptime(str(row["SL Hit At"]), "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    m = _TARGET_RE.match(outcome_str or "")
    if m:
        col = f"Target {m.group(1)} Hit At"
        if row.get(col):
            try:
                return datetime.strptime(str(row[col]), "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
    if row.get("Exited At"):
        try:
            return datetime.strptime(str(row["Exited At"]), "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    # Last resort: fixed EOD time on the trade's own date -- only
    # reached for EOD-estimate rows with no logged exit timestamp at all.
    try:
        return datetime.strptime(f"{date_str} 15:30:00", "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def load_all_trades(capital_per_trade=DEFAULT_CAPITAL_PER_TRADE):
    """
    Reads every signals_YYYY-MM-DD.xlsx, and for every row with a real,
    priceable Outcome, builds one trade dict:
      {symbol, action, entry_dt, exit_dt, entry, exit_price, qty,
       pnl, pnl_pct, exit_reason, grade}

    Rows with no real exit price (still open, or an unresolved/no-data
    note) are silently excluded from the returned list -- NOT counted
    as a loss, a win, or a breakeven. Returns (trades, excluded_count)
    so callers can report how many rows existed vs how many actually
    had something to measure.
    """
    if load_workbook is None:
        return [], 0

    trades = []
    excluded = 0

    for date_str in list_signal_log_dates():
        nested = os.path.join(LOG_DIR, date_str, f"signals_{date_str}.xlsx")
        flat = os.path.join(LOG_DIR, f"signals_{date_str}.xlsx")
        path = nested if os.path.exists(nested) else flat
        if not os.path.exists(path):
            continue
        try:
            wb = load_workbook(path)
            ws = wb["Signals"]
        except Exception as e:
            print(f"  (skipping {os.path.basename(path)}: {e})")
            continue

        headers = [c.value for c in ws[1]]
        required = {"Timestamp", "Symbol", "Action", "Entry (Premium)", "SL", "Target 1", "Target 2", "Target 3", "Outcome"}
        if not required.issubset(headers):
            continue  # older/different schema -- skip rather than guess at missing columns

        for raw in ws.iter_rows(min_row=2, values_only=True):
            row = dict(zip(headers, raw))
            outcome_str = row.get("Outcome")
            entry = row.get("Entry (Premium)")
            sl, t1, t2, t3 = row.get("SL"), row.get("Target 1"), row.get("Target 2"), row.get("Target 3")

            if entry is None or entry <= 0:
                excluded += 1
                continue

            exit_price, reason = parse_outcome(outcome_str, sl, t1, t2, t3)
            if exit_price is None:
                excluded += 1
                continue

            try:
                entry_dt = datetime.strptime(str(row["Timestamp"]), "%Y-%m-%d %H:%M:%S")
            except Exception:
                excluded += 1
                continue
            exit_dt = _resolve_exit_datetime(row, outcome_str, date_str)
            if exit_dt is None:
                excluded += 1
                continue

            qty = max(1, int(capital_per_trade / entry))
            pnl = round(qty * (exit_price - entry), 2)
            pnl_pct = round((exit_price - entry) / entry * 100, 2)

            trades.append({
                "symbol": row.get("Symbol"), "action": row.get("Action"), "grade": row.get("Grade"),
                "entry_dt": entry_dt, "exit_dt": exit_dt,
                "entry": entry, "exit_price": exit_price, "qty": qty,
                "pnl": pnl, "pnl_pct": pnl_pct, "exit_reason": reason,
            })

    trades.sort(key=lambda t: t["exit_dt"])
    return trades, excluded


def compute_capital_base(trades, capital_per_trade=DEFAULT_CAPITAL_PER_TRADE):
    """
    The 'Margin' figure everything else (CAGR/Sharpe/Sortino/Calmar) is
    measured against. Rather than guess a round number, this is
    max_concurrent_positions x capital_per_trade -- the real peak
    number of trades that were open at the same moment anywhere in the
    backtest, computed from actual entry/exit timestamps. Honest and
    non-arbitrary: it's exactly enough capital to have actually run
    every trade this data shows, no more, no less.
    """
    if not trades:
        return capital_per_trade  # nothing to measure against -- one trade's worth as a floor
    events = []
    for t in trades:
        events.append((t["entry_dt"], 1))
        events.append((t["exit_dt"], -1))
    events.sort(key=lambda e: (e[0], e[1]))  # on a tie, process the -1 (exit) before +1 (entry) -- doesn't inflate concurrency for a same-instant flip
    running, peak = 0, 0
    for _, delta in events:
        running += delta
        peak = max(peak, running)
    return max(1, peak) * capital_per_trade


def compute_equity_curve(trades, capital_base):
    """Chronological (by exit time) running equity -- starts at
    capital_base, moves by each trade's realized P&L as it resolves.
    Returns a list of {date, cumulative_pnl, equity} points, one per
    trade exit (not one per calendar day -- multiple trades exiting
    the same day each get their own point)."""
    curve = []
    cum = 0.0
    for t in trades:
        cum += t["pnl"]
        curve.append({"dt": t["exit_dt"], "cumulative_pnl": round(cum, 2), "equity": round(capital_base + cum, 2)})
    return curve


def compute_drawdown_periods(equity_curve):
    """
    Walks the equity curve and identifies every distinct peak->trough
    ->recovery cycle. A period that never recovers by the end of the
    data is marked 'Ongoing' rather than force-closed -- matches the
    reference report's own 'Currently underwater' concept.

    Returns a list of {peak_equity, peak_dt, trough_equity, trough_dt,
    depth (Rs), depth_pct, recovered_dt (or None), status}, one per
    distinct drawdown period, oldest first.
    """
    if not equity_curve:
        return []

    periods = []
    peak_equity, peak_dt = equity_curve[0]["equity"], equity_curve[0]["dt"]
    in_drawdown = False
    trough_equity, trough_dt = None, None

    for point in equity_curve:
        if point["equity"] >= peak_equity:
            if in_drawdown:
                # Recovered -- close out this period.
                depth = trough_equity - peak_equity
                periods.append({
                    "peak_equity": peak_equity, "peak_dt": peak_dt,
                    "trough_equity": trough_equity, "trough_dt": trough_dt,
                    "depth": round(depth, 2), "depth_pct": round(depth / peak_equity * 100, 2),
                    "recovered_dt": point["dt"], "status": "Recovered",
                })
                in_drawdown = False
            peak_equity, peak_dt = point["equity"], point["dt"]
        else:
            if not in_drawdown:
                in_drawdown = True
                trough_equity, trough_dt = point["equity"], point["dt"]
            elif point["equity"] < trough_equity:
                trough_equity, trough_dt = point["equity"], point["dt"]

    if in_drawdown:
        # Still underwater at the end of the data.
        depth = trough_equity - peak_equity
        periods.append({
            "peak_equity": peak_equity, "peak_dt": peak_dt,
            "trough_equity": trough_equity, "trough_dt": trough_dt,
            "depth": round(depth, 2), "depth_pct": round(depth / peak_equity * 100, 2),
            "recovered_dt": None, "status": "Ongoing",
        })

    return periods


def compute_daily_pnl(trades):
    """Groups every trade's P&L by its exit CALENDAR DATE (not
    timestamp) -- {date_str: total_pnl_that_day}. This is the series
    Sharpe/Sortino and the daily-return histogram/calendar are built
    from, matching how the reference report frames 'daily return'."""
    daily = defaultdict(float)
    for t in trades:
        daily[t["exit_dt"].strftime("%Y-%m-%d")] += t["pnl"]
    return dict(sorted(daily.items()))


def compute_monthly_pnl(trades):
    """Groups by exit YYYY-MM -> {'pnl', 'trade_count'}."""
    monthly = defaultdict(lambda: {"pnl": 0.0, "trades": 0})
    for t in trades:
        key = t["exit_dt"].strftime("%Y-%m")
        monthly[key]["pnl"] += t["pnl"]
        monthly[key]["trades"] += 1
    for v in monthly.values():
        v["pnl"] = round(v["pnl"], 2)
    return dict(sorted(monthly.items()))


def compute_metrics(trades, capital_base):
    """The full statistics suite, modeled on the reference TradeTron
    report. Every ratio that can legitimately divide by zero (Calmar
    with no drawdown ever, Profit Factor with no losing trades, Sharpe/
    Sortino with fewer than 2 days of data) returns None rather than
    crashing or printing a fabricated infinity -- callers show 'N/A'
    for those, an honest signal that there isn't enough data yet, same
    pattern as every other backtest script in this project."""
    if not trades:
        return None

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    flats = [t for t in trades if t["pnl"] == 0]

    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = sum(t["pnl"] for t in losses)  # negative
    net_pnl = round(gross_profit + gross_loss, 2)

    equity_curve = compute_equity_curve(trades, capital_base)
    drawdown_periods = compute_drawdown_periods(equity_curve)
    max_dd = min(drawdown_periods, key=lambda d: d["depth"]) if drawdown_periods else None

    daily_pnl = compute_daily_pnl(trades)
    daily_returns_pct = [v / capital_base * 100 for v in daily_pnl.values()]

    first_dt = min(t["entry_dt"] for t in trades)
    last_dt = max(t["exit_dt"] for t in trades)
    total_days = max(1, (last_dt - first_dt).days)

    ending_equity = capital_base + net_pnl
    cagr = None
    if total_days >= 7 and capital_base > 0 and ending_equity > 0:  # need at least a genuine week -- annualizing a 1-2 day sample produces meaningless, wildly inflated numbers
        cagr = round(((ending_equity / capital_base) ** (365.0 / total_days) - 1) * 100, 2)

    sharpe = sortino = None
    if len(daily_returns_pct) >= 2:
        mean_r = sum(daily_returns_pct) / len(daily_returns_pct)
        variance = sum((r - mean_r) ** 2 for r in daily_returns_pct) / (len(daily_returns_pct) - 1)
        std_r = variance ** 0.5
        if std_r > 0:
            sharpe = round(mean_r / std_r * (252 ** 0.5), 2)
        downside = [min(r, 0) for r in daily_returns_pct]
        downside_dev = (sum(d ** 2 for d in downside) / len(downside)) ** 0.5
        if downside_dev > 0:
            sortino = round(mean_r / downside_dev * (252 ** 0.5), 2)

    calmar = None
    if cagr is not None and max_dd is not None and max_dd["depth_pct"] != 0:
        calmar = round(cagr / abs(max_dd["depth_pct"]), 2)

    profit_factor = None
    if gross_loss != 0:
        profit_factor = round(gross_profit / abs(gross_loss), 2)

    ongoing_dd = next((d for d in drawdown_periods if d["status"] == "Ongoing"), None)

    return {
        "net_pnl": net_pnl,
        "net_pnl_pct": round(net_pnl / capital_base * 100, 2) if capital_base else None,
        "capital_base": capital_base,
        "total_trades": len(trades), "wins": len(wins), "losses": len(losses), "flats": len(flats),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 1) if trades else None,
        "gross_profit": round(gross_profit, 2), "gross_loss": round(gross_loss, 2),
        "profit_factor": profit_factor,
        "best_trade": max((t["pnl"] for t in trades), default=None),
        "worst_trade": min((t["pnl"] for t in trades), default=None),
        "best_day": max(daily_pnl.items(), key=lambda kv: kv[1]) if daily_pnl else None,
        "worst_day": min(daily_pnl.items(), key=lambda kv: kv[1]) if daily_pnl else None,
        "cagr_pct": cagr,
        "max_drawdown": max_dd,
        "sharpe": sharpe, "sortino": sortino, "calmar": calmar,
        "currently_underwater": ongoing_dd,
        "total_days_span": total_days,
        "equity_curve": equity_curve,
        "drawdown_periods": drawdown_periods,
        "daily_pnl": daily_pnl,
        "monthly_pnl": compute_monthly_pnl(trades),
    }


def _bin_daily_returns(daily_pnl, capital_base, num_bins=12):
    """Buckets daily P&L (as % of capital_base) into num_bins equal-width
    bins for the histogram chart. Returns (bin_labels, bin_counts)."""
    if not daily_pnl:
        return [], []
    returns_pct = [v / capital_base * 100 for v in daily_pnl.values()]
    lo, hi = min(returns_pct), max(returns_pct)
    if lo == hi:
        return [f"{lo:.2f}%"], [len(returns_pct)]
    width = (hi - lo) / num_bins
    counts = [0] * num_bins
    for r in returns_pct:
        idx = min(num_bins - 1, int((r - lo) / width))
        counts[idx] += 1
    labels = [f"{(lo + i * width):.2f}%" for i in range(num_bins)]
    return labels, counts


def write_report(trades, metrics, capital_per_trade=DEFAULT_CAPITAL_PER_TRADE):
    """
    Builds the full Excel report -- Summary (headline stats + equity
    curve + drawdown charts), Trades (every trade, one row each),
    Monthly Performance (with a bar chart), Worst Drawdowns, and Daily
    Returns (with a histogram). Saved to
    signal_logs/backtest_reports/signal_pnl_backtest_<today>.xlsx.
    Returns the path, or None if there's nothing to report yet.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.chart import LineChart, BarChart, Reference

    if metrics is None:
        return None

    wb = Workbook()
    header_font = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="DDDDDD")

    # ---- Summary sheet ----
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = "Signal P&L Backtest -- Summary"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Capital base: Rs {metrics['capital_base']:,.0f}  (each trade sized at Rs {capital_per_trade:,.0f}, matching views.py's own qty=max(1,int(50000/entry)) convention)"
    ws["A3"] = f"Period: {metrics['total_days_span']} days  |  {metrics['total_trades']} resolved trades ({metrics['wins']} wins, {metrics['losses']} losses, {metrics['flats']} flat)"

    def na(v, suffix=""):
        return "N/A" if v is None else f"{v}{suffix}"

    rows = [
        ("", ""),
        ("Net P&L", f"Rs {metrics['net_pnl']:,.0f} ({na(metrics['net_pnl_pct'], '%')})"),
        ("CAGR (annualised)", na(metrics['cagr_pct'], '%')),
        ("Max Drawdown", f"{na(metrics['max_drawdown']['depth_pct'] if metrics['max_drawdown'] else None, '%')}" + (f"  (Rs {metrics['max_drawdown']['depth']:,.0f})" if metrics['max_drawdown'] else "")),
        ("Calmar Ratio (CAGR / MaxDD)", na(metrics['calmar'])),
        ("Sharpe (annualised)", na(metrics['sharpe'])),
        ("Sortino (annualised)", na(metrics['sortino'])),
        ("Win Rate", na(metrics['win_rate_pct'], '%')),
        ("Profit Factor", na(metrics['profit_factor'])),
        ("Best trade", f"Rs {metrics['best_trade']:,.0f}" if metrics['best_trade'] is not None else "N/A"),
        ("Worst trade", f"Rs {metrics['worst_trade']:,.0f}" if metrics['worst_trade'] is not None else "N/A"),
        ("Best day", f"{metrics['best_day'][0]}  Rs {metrics['best_day'][1]:,.0f}" if metrics['best_day'] else "N/A"),
        ("Worst day", f"{metrics['worst_day'][0]}  Rs {metrics['worst_day'][1]:,.0f}" if metrics['worst_day'] else "N/A"),
        ("Currently underwater", (f"Rs {metrics['currently_underwater']['depth']:,.0f} ({metrics['currently_underwater']['depth_pct']}%) since {metrics['currently_underwater']['peak_dt'].strftime('%Y-%m-%d')}" if metrics['currently_underwater'] else "No -- at or above the last peak")),
    ]
    start_row = 5
    for i, (label, value) in enumerate(rows):
        ws.cell(row=start_row + i, column=1, value=label).font = Font(bold=bool(label))
        ws.cell(row=start_row + i, column=2, value=value)
    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 55

    # Equity curve data (hidden-ish helper columns, D/E) + chart
    ec_row0 = 5
    ws.cell(row=ec_row0 - 1, column=4, value="Trade #").font = header_font
    ws.cell(row=ec_row0 - 1, column=5, value="Equity").font = header_font
    ws.cell(row=ec_row0 - 1, column=6, value="Drawdown %").font = header_font
    for i, point in enumerate(metrics["equity_curve"]):
        ws.cell(row=ec_row0 + i, column=4, value=i + 1)
        ws.cell(row=ec_row0 + i, column=5, value=point["equity"])
    # Drawdown % per point, recomputed against the running peak for the chart
    running_peak = metrics["capital_base"]
    for i, point in enumerate(metrics["equity_curve"]):
        running_peak = max(running_peak, point["equity"])
        dd_pct = round((point["equity"] - running_peak) / running_peak * 100, 2)
        ws.cell(row=ec_row0 + i, column=6, value=dd_pct)

    n_points = len(metrics["equity_curve"])
    if n_points >= 2:
        eq_chart = LineChart()
        eq_chart.title = "Equity Curve"
        eq_chart.y_axis.title = "Equity (Rs)"
        eq_chart.x_axis.title = "Trade #"
        data = Reference(ws, min_col=5, min_row=ec_row0 - 1, max_row=ec_row0 + n_points - 1)
        cats = Reference(ws, min_col=4, min_row=ec_row0, max_row=ec_row0 + n_points - 1)
        eq_chart.add_data(data, titles_from_data=True)
        eq_chart.set_categories(cats)
        eq_chart.height, eq_chart.width = 8, 16
        ws.add_chart(eq_chart, "H5")

        dd_chart = LineChart()
        dd_chart.title = "Drawdown %"
        dd_chart.y_axis.title = "% from peak"
        dd_chart.x_axis.title = "Trade #"
        dd_data = Reference(ws, min_col=6, min_row=ec_row0 - 1, max_row=ec_row0 + n_points - 1)
        dd_chart.add_data(dd_data, titles_from_data=True)
        dd_chart.set_categories(cats)
        dd_chart.height, dd_chart.width = 8, 16
        ws.add_chart(dd_chart, "H21")

    # ---- Trades sheet ----
    ws2 = wb.create_sheet("Trades")
    headers = ["Symbol", "Action", "Grade", "Entry Time", "Exit Time", "Entry", "Exit Price", "Qty", "P&L (Rs)", "P&L %", "Exit Reason"]
    ws2.append(headers)
    for cell in ws2[1]:
        cell.font = header_font
        cell.fill = header_fill
    for t in trades:
        ws2.append([
            t["symbol"], t["action"], t.get("grade"),
            t["entry_dt"].strftime("%Y-%m-%d %H:%M:%S"), t["exit_dt"].strftime("%Y-%m-%d %H:%M:%S"),
            t["entry"], t["exit_price"], t["qty"], t["pnl"], t["pnl_pct"], t["exit_reason"],
        ])
    for col in ws2.columns:
        max_len = max((len(str(c.value)) for c in col if c.value is not None), default=10)
        ws2.column_dimensions[col[0].column_letter].width = max(max_len + 2, 10)

    # ---- Monthly Performance sheet ----
    ws3 = wb.create_sheet("Monthly Performance")
    ws3.append(["Month", "P&L (Rs)", "Trades"])
    for cell in ws3[1]:
        cell.font = header_font
        cell.fill = header_fill
    for month, v in metrics["monthly_pnl"].items():
        ws3.append([month, v["pnl"], v["trades"]])
    n_months = len(metrics["monthly_pnl"])
    if n_months >= 1:
        m_chart = BarChart()
        m_chart.title = "Monthly P&L"
        m_chart.y_axis.title = "Rs"
        m_data = Reference(ws3, min_col=2, min_row=1, max_row=1 + n_months)
        m_cats = Reference(ws3, min_col=1, min_row=2, max_row=1 + n_months)
        m_chart.add_data(m_data, titles_from_data=True)
        m_chart.set_categories(m_cats)
        m_chart.height, m_chart.width = 8, 16
        ws3.add_chart(m_chart, "E2")
    for col in ws3.columns:
        ws3.column_dimensions[col[0].column_letter].width = 14

    # ---- Worst Drawdowns sheet ----
    ws4 = wb.create_sheet("Worst Drawdowns")
    ws4.append(["#", "Depth (Rs)", "Depth %", "Peak Date", "Trough Date", "Recovered", "Status"])
    for cell in ws4[1]:
        cell.font = header_font
        cell.fill = header_fill
    sorted_dd = sorted(metrics["drawdown_periods"], key=lambda d: d["depth"])[:5]
    for i, d in enumerate(sorted_dd, 1):
        ws4.append([
            i, d["depth"], d["depth_pct"],
            d["peak_dt"].strftime("%Y-%m-%d %H:%M"), d["trough_dt"].strftime("%Y-%m-%d %H:%M"),
            d["recovered_dt"].strftime("%Y-%m-%d %H:%M") if d["recovered_dt"] else "--",
            d["status"],
        ])
    for col in ws4.columns:
        max_len = max((len(str(c.value)) for c in col if c.value is not None), default=10)
        ws4.column_dimensions[col[0].column_letter].width = max(max_len + 2, 10)

    # ---- Daily Returns sheet (with histogram) ----
    ws5 = wb.create_sheet("Daily Returns")
    ws5.append(["Date", "P&L (Rs)", "P&L % of capital"])
    for cell in ws5[1]:
        cell.font = header_font
        cell.fill = header_fill
    for date_str, pnl in metrics["daily_pnl"].items():
        ws5.append([date_str, round(pnl, 2), round(pnl / metrics["capital_base"] * 100, 3)])
    for col in ws5.columns:
        ws5.column_dimensions[col[0].column_letter].width = 16

    bin_labels, bin_counts = _bin_daily_returns(metrics["daily_pnl"], metrics["capital_base"])
    if bin_counts:
        hist_start = len(metrics["daily_pnl"]) + 3
        ws5.cell(row=hist_start, column=1, value="Bin (daily return %)").font = header_font
        ws5.cell(row=hist_start, column=2, value="Days").font = header_font
        for i, (label, count) in enumerate(zip(bin_labels, bin_counts)):
            ws5.cell(row=hist_start + 1 + i, column=1, value=label)
            ws5.cell(row=hist_start + 1 + i, column=2, value=count)
        h_chart = BarChart()
        h_chart.title = "Daily Return Distribution"
        h_chart.y_axis.title = "Days"
        h_data = Reference(ws5, min_col=2, min_row=hist_start, max_row=hist_start + len(bin_counts))
        h_cats = Reference(ws5, min_col=1, min_row=hist_start + 1, max_row=hist_start + len(bin_counts))
        h_chart.add_data(h_data, titles_from_data=True)
        h_chart.set_categories(h_cats)
        h_chart.height, h_chart.width = 8, 16
        ws5.add_chart(h_chart, "E2")

    out_dir = os.path.join(LOG_DIR, "backtest_reports")
    os.makedirs(out_dir, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(out_dir, f"signal_pnl_backtest_{today}.xlsx")
    wb.save(path)
    return path


def print_summary(metrics, excluded_count):
    if metrics is None:
        print("No resolved trades with a real exit price yet -- nothing to report.")
        print(f"({excluded_count} rows were still open or had no priceable outcome, and were correctly excluded rather than guessed at.)")
        return
    print(f"\n{'=' * 60}")
    print("  Signal P&L Backtest -- Summary")
    print(f"{'=' * 60}")
    print(f"Capital base: Rs {metrics['capital_base']:,.0f}  |  {metrics['total_trades']} resolved trades  |  {excluded_count} excluded (still open / no priceable outcome)")
    if metrics['total_trades'] < 20:
        print("(That's a genuinely small sample -- treat everything below as a rough first look,")
        print(" not a verified edge. Same caution as every other backtest in this project.)")
    print()
    print(f"Net P&L:        Rs {metrics['net_pnl']:,.0f} ({metrics['net_pnl_pct']}%)")
    print(f"Win Rate:       {metrics['win_rate_pct']}%  ({metrics['wins']}W / {metrics['losses']}L / {metrics['flats']} flat)")
    print(f"Profit Factor:  {metrics['profit_factor'] if metrics['profit_factor'] is not None else 'N/A'}")
    print(f"CAGR:           {metrics['cagr_pct'] if metrics['cagr_pct'] is not None else 'N/A (need at least a week of data)'}")
    print(f"Max Drawdown:   {metrics['max_drawdown']['depth_pct'] if metrics['max_drawdown'] else 'N/A (no drawdown yet)'}%")
    print(f"Sharpe:         {metrics['sharpe'] if metrics['sharpe'] is not None else 'N/A'}")
    print(f"Sortino:        {metrics['sortino'] if metrics['sortino'] is not None else 'N/A'}")
    print(f"Calmar:         {metrics['calmar'] if metrics['calmar'] is not None else 'N/A'}")


if __name__ == "__main__":
    if load_workbook is None:
        print("openpyxl not installed -- pip install openpyxl")
    else:
        trades, excluded = load_all_trades()
        capital_base = compute_capital_base(trades)
        metrics = compute_metrics(trades, capital_base)
        print_summary(metrics, excluded)
        if metrics:
            path = write_report(trades, metrics)
            print(f"\nFull report written to: {path}")
