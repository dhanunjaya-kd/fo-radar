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

    # Deferred import -- same convention used throughout this project
    # (index_tracker.py's fyers_client imports, etc.) to avoid any
    # circular-import risk between modules that reference each other
    # indirectly, rather than a module-level import up top.
    from .lot_size_resolver import get_lot_size

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

            # Aug 27 2026: real, live-resolved NSE lot size (one real
            # tradeable lot, not int(capital_per_trade/entry)) --
            # REPLACES the old Rs 50,000-based quantity entirely. That
            # old math gave a cheap-premium stock a wildly oversized
            # position purely because it was cheap (e.g. a Rs 4
            # premium got ~12,400 units vs an Rs 11.60 premium getting
            # ~4,300 -- same Rs 50k budget, wildly different real
            # exposure, nothing to do with the strategy being better
            # on the cheap one). One real lot is what a trader actually
            # holds, and removes that distortion from every downstream
            # metric (Net P&L%, Profit Factor, Sharpe) at once, since
            # they're all built from these same per-trade P&L figures.
            #
            # No confirmed live lot size for this symbol -> exclude the
            # trade entirely (same "don't guess, don't fabricate" rule
            # every other exclusion in this loop already follows) --
            # deliberately NOT falling back to the old capital-based
            # math, which would silently mix two different sizing
            # methodologies within the same backtest run.
            qty = get_lot_size(row.get("Symbol"))
            if qty is None:
                excluded += 1
                continue

            pnl = round(qty * (exit_price - entry), 2)
            pnl_pct = round((exit_price - entry) / entry * 100, 2)

            trades.append({
                "symbol": row.get("Symbol"), "action": row.get("Action"), "grade": row.get("Grade"),
                "sector": row.get("Sector") or "Unknown",
                "oi_confirmation": row.get("OI Confirmation") or "Unknown",
                "pattern": row.get("Pattern") or "None",
                "entry_dt": entry_dt, "exit_dt": exit_dt,
                "entry": entry, "sl": sl, "exit_price": exit_price, "qty": qty,
                "pnl": pnl, "pnl_pct": pnl_pct, "exit_reason": reason,
                "r_multiple": compute_r_multiple(entry, sl, exit_price),
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


def compute_segment_breakdown(trades, segment_key):
    """
    Groups trades by a field (grade / sector / oi_confirmation / pattern)
    and computes basic per-segment stats. This is the real next step
    after noticing an overall win rate or Sharpe that doesn't say WHY --
    shows whether losses are concentrated in one Grade/Sector/pattern or
    genuinely spread evenly, which is a real, data-backed lead rather
    than a guess about what to fix.

    Returns a list of dicts sorted by net P&L descending (best segment
    first): {segment, count, wins, losses, win_rate_pct, net_pnl,
    avg_pnl, profit_factor}. profit_factor is None (not a fabricated
    infinity) when a segment has zero losing trades, same rule
    compute_metrics() already follows for the whole-portfolio version.
    """
    groups = defaultdict(list)
    for t in trades:
        groups[t.get(segment_key) or "Unknown"].append(t)

    results = []
    for seg, seg_trades in groups.items():
        wins = [t for t in seg_trades if t["pnl"] > 0]
        losses = [t for t in seg_trades if t["pnl"] < 0]
        net_pnl = round(sum(t["pnl"] for t in seg_trades), 2)
        gross_profit = sum(t["pnl"] for t in wins)
        gross_loss = sum(t["pnl"] for t in losses)
        results.append({
            "segment": seg,
            "count": len(seg_trades),
            "wins": len(wins), "losses": len(losses),
            "win_rate_pct": round(len(wins) / len(seg_trades) * 100, 1) if seg_trades else None,
            "net_pnl": net_pnl,
            "avg_pnl": round(net_pnl / len(seg_trades), 2) if seg_trades else None,
            "profit_factor": round(gross_profit / abs(gross_loss), 2) if gross_loss != 0 else None,
        })
    results.sort(key=lambda r: r["net_pnl"], reverse=True)
    return results


def generate_key_findings(trades, min_trades_for_a_finding=10):
    """
    Plain-language callouts for the standout segment in each category --
    the thing that's easy to miss buried in 4 separate tables (like
    Grade C quietly outperforming Grade A). Deliberately factual and
    narrow: names the best/worst segment and its real numbers, never a
    speculative WHY -- this project doesn't have enough signal yet to
    say why Grade C wins, only that it does. A segment with fewer than
    min_trades_for_a_finding trades is never surfaced as a finding, even
    if its win rate looks extreme -- same small-sample rule as
    everywhere else here, just enforced automatically instead of relying
    on someone reading the caution note.

    Returns a list of plain sentences (strings), empty if nothing in the
    real data clears the minimum sample size.
    """
    findings = []
    labels = {"grade": "Grade", "oi_confirmation": "OI Confirmation", "pattern": "Pattern"}
    for key, label in labels.items():
        segs = [s for s in compute_segment_breakdown(trades, key) if s["count"] >= min_trades_for_a_finding]
        if len(segs) < 2:
            continue  # need at least 2 real segments to compare -- one segment alone isn't a "best vs worst" finding
        best, worst = segs[0], segs[-1]
        if best["segment"] == worst["segment"]:
            continue
        if worst["net_pnl"] < 0 <= best["net_pnl"]:
            findings.append(
                f"{label} \"{best['segment']}\" is your best performer (Rs {best['net_pnl']:,.0f} net, "
                f"{best['win_rate_pct']}% win rate, {best['count']} trades) while \"{worst['segment']}\" is "
                f"actually losing money (Rs {worst['net_pnl']:,.0f} net, {worst['count']} trades)."
            )
        else:
            findings.append(
                f"{label} \"{best['segment']}\" outperforms \"{worst['segment']}\" by Rs {best['net_pnl'] - worst['net_pnl']:,.0f} "
                f"net ({best['count']} vs {worst['count']} trades)."
            )
    return findings


def compute_r_multiple(entry, sl, exit_price):
    """
    Aug 29 2026: R-Multiple = Realized P&L / Initial Risk, per the PDF
    upgrade spec's own definition. Initial Risk = entry - sl in
    PREMIUM terms -- confirmed against this engine's own existing pnl
    formula (pnl = exit_price - entry, applied uniformly regardless of
    BUY/SELL), which only makes sense if entry is always the premium
    paid and sl is always BELOW it: every trade here buys an option
    contract (call or put), never shorts the underlying. So
    initial_risk = entry - sl should always be positive for a real,
    correctly-logged trade -- a non-positive value signals a genuine
    data problem, not a valid trade, and is handled defensively (None,
    not a fabricated or infinite ratio).

    Tested in test_r_multiple.py (9 cases) before being wired in here.
    """
    if entry is None or sl is None or exit_price is None:
        return None
    initial_risk = entry - sl
    if initial_risk <= 0:
        return None
    return round((exit_price - entry) / initial_risk, 4)


def summarize_r_multiples(trades):
    """Average/median/best/worst R, winner-distribution percentiles,
    and winning-vs-losing R asymmetry -- the full breakdown the PDF
    spec's R-Multiple table asks for. Trades whose r_multiple is None
    (missing or bad SL data) are excluded from the sample, not treated
    as 0R. Returns None if there's no valid sample at all, same
    "don't fabricate" pattern every other metric here follows."""
    r_values = [t["r_multiple"] for t in trades if t.get("r_multiple") is not None]
    if not r_values:
        return None
    n = len(r_values)
    sorted_r = sorted(r_values)
    median = sorted_r[n // 2] if n % 2 == 1 else (sorted_r[n // 2 - 1] + sorted_r[n // 2]) / 2
    winners = [r for r in r_values if r > 0]
    losers = [r for r in r_values if r < 0]
    return {
        "avg_r": round(sum(r_values) / n, 3),
        "median_r": round(median, 3),
        "best_r": round(max(r_values), 3),
        "worst_r": round(min(r_values), 3),
        "pct_ge_1r": round(len([r for r in r_values if r >= 1]) / n * 100, 1),
        "pct_ge_2r": round(len([r for r in r_values if r >= 2]) / n * 100, 1),
        "pct_le_neg1r": round(len([r for r in r_values if r <= -1]) / n * 100, 1),
        "avg_winning_r": round(sum(winners) / len(winners), 3) if winners else None,
        "avg_losing_r": round(sum(losers) / len(losers), 3) if losers else None,
        "sample_size": n,
    }


def compute_long_short_breakdown(trades):
    """
    Splits trades by Action (BUY/SELL) into complete scorecards -- P0
    upgrade spec item. Deliberately a SEPARATE function from
    compute_segment_breakdown() (used for Grade/Sector/OI/Pattern)
    rather than an extension of it: those four already-shipped,
    already-tested tables don't need Average R or Average Holding
    Time, and extending a shared function to carry fields only one
    caller needs risks changing their output shape for no reason.

    Returns {action: {count, wins, losses, win_rate_pct, net_pnl,
    expectancy, profit_factor, avg_r, avg_holding_minutes}} for every
    real Action value present in the trades (normally just "BUY" and
    "SELL" -- this project only ever buys option premium, long calls
    for BUY / long puts for SELL, never shorts the underlying, so
    "Long vs Short" here means bullish-vs-bearish bias, not a literal
    short position).

    avg_r is None for a side with no trade carrying a valid
    r_multiple; avg_holding_minutes is computed from real entry_dt/
    exit_dt, never estimated. Same "exclude rather than fabricate"
    rule as summarize_r_multiples().
    """
    groups = defaultdict(list)
    for t in trades:
        groups[t.get("action") or "Unknown"].append(t)

    result = {}
    for action, group_trades in groups.items():
        wins = [t for t in group_trades if t["pnl"] > 0]
        losses = [t for t in group_trades if t["pnl"] < 0]
        net_pnl = round(sum(t["pnl"] for t in group_trades), 2)
        gross_profit = sum(t["pnl"] for t in wins)
        gross_loss = sum(t["pnl"] for t in losses)
        r_values = [t["r_multiple"] for t in group_trades if t.get("r_multiple") is not None]
        holding_minutes = [(t["exit_dt"] - t["entry_dt"]).total_seconds() / 60 for t in group_trades]
        result[action] = {
            "count": len(group_trades),
            "wins": len(wins), "losses": len(losses),
            "win_rate_pct": round(len(wins) / len(group_trades) * 100, 1) if group_trades else None,
            "net_pnl": net_pnl,
            "expectancy": round(net_pnl / len(group_trades), 2) if group_trades else None,
            "profit_factor": round(gross_profit / abs(gross_loss), 2) if gross_loss != 0 else None,
            "avg_r": round(sum(r_values) / len(r_values), 3) if r_values else None,
            "avg_holding_minutes": round(sum(holding_minutes) / len(holding_minutes), 1) if holding_minutes else None,
        }
    return result


def compute_scorecard_status(metrics, min_sample_size=20):
    """
    Promising / Weak / Insufficient Sample -- P0 upgrade spec item.
    Fixed, disclosed rule, confirmed with him Aug 29 2026 (chose the
    "strict" option over a looser PF-only alternative):

      Insufficient Sample -- fewer than min_sample_size (20) resolved
      trades. Not a new number: the SAME 20-trade floor this file's
      own small-sample warning banner already uses elsewhere.

      Promising -- Profit Factor >= 1.5 AND Win Rate >= 45%, both.

      Weak -- clears the sample floor but doesn't clear both bars
      above. "Weak" means "hasn't cleared the Promising bar yet," not
      "definitely losing" -- a strategy can be net profitable and
      still be Weak here if it's under 1.5 PF or under 45% win rate.

    A None profit_factor (gross_loss == 0 -- zero realized losing
    trades) is treated as CLEARING the PF bar, not failing it: it
    means no losses recorded yet, not missing data, so scoring it as
    a failure against >=1.5 would be backwards.

    Returns (status_str, reason_str) -- reason_str names the exact
    numbers that decided it, so the status is never an unexplained
    label.
    """
    total = metrics["total_trades"]
    if total < min_sample_size:
        return ("Insufficient Sample",
                f"Only {total} resolved trades -- below the {min_sample_size}-trade floor to trust a verdict either way.")

    pf = metrics["profit_factor"]
    wr = metrics["win_rate_pct"]
    pf_ok = pf is None or pf >= 1.5
    wr_ok = wr is not None and wr >= 45

    if pf_ok and wr_ok:
        pf_str = "no losing trades yet" if pf is None else f"PF {pf}"
        return ("Promising", f"{pf_str}, Win Rate {wr}% -- both clear the bar (PF >= 1.5, Win Rate >= 45%).")

    failed = []
    if not pf_ok:
        failed.append(f"PF {pf} is below 1.5")
    if not wr_ok:
        failed.append(f"Win Rate {wr}% is below 45%")
    return ("Weak", f"Doesn't clear the Promising bar yet: {'; '.join(failed)}.")


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
    # A week wasn't nearly enough -- confirmed by a real test case: a
    # genuinely strong 17-day run (68% period return) annualized to
    # 6,812,180%. That's the CAGR formula working exactly as defined,
    # not a bug in the math -- exponential annualization of a short,
    # punchy window is inherently unstable, not just "needs a bigger
    # day-count floor." Two guards now: a real month minimum before
    # attempting it at all, AND treating a result that's still absurd
    # even past that floor as equally untrustworthy as too-little-data
    # -- None either way, same "don't show a number you can't stand
    # behind" rule this whole engine already follows for Sharpe/Sortino/
    # Calmar/Profit Factor.
    if total_days >= 30 and capital_base > 0 and ending_equity > 0:
        raw_cagr = ((ending_equity / capital_base) ** (365.0 / total_days) - 1) * 100
        if abs(raw_cagr) <= 500:  # beyond this, a short/volatile window is being over-extrapolated, not genuinely measured
            cagr = round(raw_cagr, 2)

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

    # Strategy Scorecard secondary metrics -- P0 upgrade spec item.
    # avg_loss stays negative (same sign convention as gross_loss
    # above) rather than reporting a magnitude that'd need a label to
    # explain which direction it means.
    avg_win = round(gross_profit / len(wins), 2) if wins else None
    avg_loss = round(gross_loss / len(losses), 2) if losses else None
    winning_days = len([v for v in daily_pnl.values() if v > 0])
    losing_days = len([v for v in daily_pnl.values() if v < 0])
    holding_minutes = [(t["exit_dt"] - t["entry_dt"]).total_seconds() / 60 for t in trades]
    avg_holding_minutes = round(sum(holding_minutes) / len(holding_minutes), 1) if holding_minutes else None

    metrics = {
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
        "r_multiple": summarize_r_multiples(trades),
        "long_short": compute_long_short_breakdown(trades),
        "avg_win": avg_win, "avg_loss": avg_loss,
        "winning_days": winning_days, "losing_days": losing_days,
        "avg_holding_minutes": avg_holding_minutes,
        "expectancy": round(net_pnl / len(trades), 2) if trades else None,
    }
    metrics["scorecard_status"], metrics["scorecard_status_reason"] = compute_scorecard_status(metrics)
    return metrics


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


def _mpl_style_axes(ax, spine_color="#E5E7EB"):
    """Shared cleanup applied to every chart -- removes the boxed-in
    look matplotlib defaults to, keeps only light horizontal gridlines,
    matches the airy, uncluttered feel of the reference report rather
    than a default matplotlib figure."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_color(spine_color)
    ax.tick_params(colors="#6B7280", labelsize=9)
    ax.yaxis.grid(True, color="#F3F4F6", linewidth=1)
    ax.set_axisbelow(True)
    ax.xaxis.set_ticks_position("none")
    ax.yaxis.set_ticks_position("none")


def _chart_equity_curve(metrics, out_path):
    """Equity curve with a soft gradient fill underneath, matching the
    reference report's look -- a smooth blue line, light fill below it,
    a dashed reference line at the starting capital so a glance shows
    whether the account is above or below where it started."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    curve = metrics["equity_curve"]
    x = list(range(1, len(curve) + 1))
    y = [p["equity"] for p in curve]

    fig, ax = plt.subplots(figsize=(9, 3.4), dpi=80)
    ax.plot(x, y, color="#2563EB", linewidth=2, solid_capstyle="round")
    ax.fill_between(x, y, metrics["capital_base"], where=[v >= metrics["capital_base"] for v in y],
                     color="#2563EB", alpha=0.08, interpolate=True)
    ax.fill_between(x, y, metrics["capital_base"], where=[v < metrics["capital_base"] for v in y],
                     color="#DC2626", alpha=0.08, interpolate=True)
    ax.axhline(metrics["capital_base"], color="#9CA3AF", linewidth=1, linestyle="--")
    ax.set_xlabel("Trade #", color="#6B7280", fontsize=9)
    ax.set_ylabel("Equity (Rs)", color="#6B7280", fontsize=9)
    _mpl_style_axes(ax)
    fig.tight_layout()
    fig.savefig(out_path, facecolor="white")
    plt.close(fig)


def _chart_drawdown(metrics, out_path):
    """Underwater/drawdown chart -- filled red area below zero, same
    visual language as the reference's own drawdown panel."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    curve = metrics["equity_curve"]
    x = list(range(1, len(curve) + 1))
    running_peak = metrics["capital_base"]
    dd_pct = []
    for p in curve:
        running_peak = max(running_peak, p["equity"])
        dd_pct.append(round((p["equity"] - running_peak) / running_peak * 100, 2))

    fig, ax = plt.subplots(figsize=(9, 2.6), dpi=80)
    ax.fill_between(x, dd_pct, 0, color="#DC2626", alpha=0.25)
    ax.plot(x, dd_pct, color="#DC2626", linewidth=1.2)
    ax.set_xlabel("Trade #", color="#6B7280", fontsize=9)
    ax.set_ylabel("% from peak", color="#6B7280", fontsize=9)
    _mpl_style_axes(ax)
    fig.tight_layout()
    fig.savefig(out_path, facecolor="white")
    plt.close(fig)


def _chart_daily_histogram(metrics, out_path):
    """Daily return distribution -- green bars for winning days, red
    for losing days, matching the reference's own red/green split."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    bin_labels, bin_counts = _bin_daily_returns(metrics["daily_pnl"], metrics["capital_base"])
    if not bin_counts:
        return False
    colors = ["#DC2626" if float(lbl.rstrip('%')) < 0 else "#16A34A" for lbl in bin_labels]

    fig, ax = plt.subplots(figsize=(9, 3), dpi=80)
    ax.bar(range(len(bin_counts)), bin_counts, color=colors, width=0.85)
    ax.set_xticks(range(len(bin_labels)))
    ax.set_xticklabels(bin_labels, rotation=45, ha="right", fontsize=7)
    ax.set_ylabel("Days", color="#6B7280", fontsize=9)
    ax.set_xlabel("Daily return, % of capital", color="#6B7280", fontsize=9)
    _mpl_style_axes(ax)
    fig.tight_layout()
    fig.savefig(out_path, facecolor="white")
    plt.close(fig)
    return True


def _chart_monthly_pnl(metrics, out_path):
    """Monthly P&L bars, green/red by sign."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    months = list(metrics["monthly_pnl"].keys())
    pnls = [v["pnl"] for v in metrics["monthly_pnl"].values()]
    if not months:
        return False
    colors = ["#16A34A" if p >= 0 else "#DC2626" for p in pnls]

    fig, ax = plt.subplots(figsize=(9, 2.8), dpi=80)
    ax.bar(months, pnls, color=colors, width=0.6)
    ax.set_ylabel("Rs", color="#6B7280", fontsize=9)
    ax.tick_params(axis="x", rotation=0)
    _mpl_style_axes(ax)
    fig.tight_layout()
    fig.savefig(out_path, facecolor="white")
    plt.close(fig)
    return True


def _chart_long_short_comparison(breakdown, out_path):
    """Side-by-side BUY vs SELL bars for Win Rate % and Net P&L -- the
    two numbers that most directly answer the spec's own framing:
    'do not assume the same edge exists in both directions.' Returns
    False (writes nothing) if either side has zero trades -- a
    comparison needs two real bars to mean anything, not one real bar
    next to a fabricated zero."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    buy, sell = breakdown.get("BUY"), breakdown.get("SELL")
    if not buy or not sell:
        return False

    actions = ["BUY", "SELL"]
    bar_colors = ["#2563EB", "#D97706"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9, 3))
    ax1.bar(actions, [buy["win_rate_pct"], sell["win_rate_pct"]], color=bar_colors, width=0.5)
    ax1.set_ylabel("Win Rate %", color="#6B7280", fontsize=9)
    ax1.set_ylim(0, 100)
    _mpl_style_axes(ax1)

    ax2.bar(actions, [buy["net_pnl"], sell["net_pnl"]], color=bar_colors, width=0.5)
    ax2.set_ylabel("Net P&L (Rs)", color="#6B7280", fontsize=9)
    ax2.axhline(0, color="#9CA3AF", linewidth=1)
    _mpl_style_axes(ax2)

    fig.tight_layout()
    fig.savefig(out_path, facecolor="white")
    plt.close(fig)
    return True


def _fmt_holding(minutes):
    """Minutes -> 'Xh Ym' / 'Ym' for display. None -> 'N/A', same
    convention as every other missing-value case in this file."""
    if minutes is None:
        return "N/A"
    total_min = round(minutes)
    hours, mins = divmod(total_min, 60)
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def _esc(text):
    """reportlab's Paragraph parses its text as a small XML/HTML-like
    markup language -- a raw & is interpreted as the start of an entity
    reference (which is why "P&L" rendered as "P&L;" with a stray
    semicolon in an early test, confirmed both in extracted PDF text
    and the actual rendered page before this fix). Every string that
    goes into a Paragraph needs this, not just the ones with an
    obviously visible & -- applied at every call site below, not just
    the ones a quick grep for a literal & would catch (label/
    explanation strings get built dynamically and passed as
    parameters, which a source-text grep misses entirely -- exactly
    how the "Net P&L" KPI card label slipped through the first pass)."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _kpi_card(label, value_str, explanation, bg_hex, text_hex):
    """One color-coded KPI card as a small nested reportlab Table --
    label, big value, one-line plain-language explanation. Several of
    these get arranged side by side in an outer table to form the
    dashboard grid."""
    from reportlab.platypus import Table, TableStyle, Paragraph
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.units import mm

    label_style = ParagraphStyle("kpi_label", fontName="Helvetica-Bold", fontSize=8, textColor=rl_colors.HexColor(text_hex))
    value_style = ParagraphStyle("kpi_value", fontName="Helvetica-Bold", fontSize=17, textColor=rl_colors.HexColor(text_hex), spaceBefore=2, spaceAfter=2)
    exp_style = ParagraphStyle("kpi_exp", fontName="Helvetica-Oblique", fontSize=6.5, textColor=rl_colors.HexColor(text_hex), leading=8)

    inner = Table(
        [[Paragraph(_esc(label.upper()), label_style)],
         [Paragraph(_esc(value_str), value_style)],
         [Paragraph(_esc(explanation), exp_style)]],
        colWidths=[41 * mm],
    )
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), rl_colors.HexColor(bg_hex)),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return inner


def _rating_hex(value, good_threshold, ok_threshold, higher_is_better=True):
    GREEN, GREEN_T = "#DCFCE7", "#166534"
    AMBER, AMBER_T = "#FEF9C3", "#854D0E"
    RED, RED_T = "#FEE2E2", "#991B1B"
    GREY, GREY_T = "#F3F4F6", "#4B5563"
    if value is None:
        return GREY, GREY_T
    good = value >= good_threshold if higher_is_better else value <= good_threshold
    ok = value >= ok_threshold if higher_is_better else value <= ok_threshold
    if good:
        return GREEN, GREEN_T
    if ok:
        return AMBER, AMBER_T
    return RED, RED_T


def _pos_neg_hex(value):
    if value is None:
        return "#F3F4F6", "#4B5563"
    if value > 0:
        return "#DCFCE7", "#166534"
    if value < 0:
        return "#FEE2E2", "#991B1B"
    return "#F3F4F6", "#374151"


def write_pdf_report(trades, metrics, capital_per_trade=DEFAULT_CAPITAL_PER_TRADE):
    """
    Builds the full PDF report -- styled toward the TradeTron reference
    he shared: smooth gradient-filled equity curve, a red underwater/
    drawdown chart, color-coded KPI cards with plain-language
    explanations, a daily-return histogram, monthly performance, worst
    drawdowns, and the full trade log. Charts are matplotlib PNGs
    embedded into a reportlab Platypus document -- reportlab alone
    can't produce chart-quality graphics, matplotlib alone can't lay
    out a multi-page document, so this uses each for what it's
    actually good at.

    Saved to signal_logs/backtest_reports/signal_pnl_backtest_<today>.pdf.
    Returns the path, or None if there's nothing to report yet.
    """
    import tempfile
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                     Image as RLImage, PageBreak)

    if metrics is None:
        return None

    def na(v, suffix=""):
        return "N/A" if v is None else f"{v}{suffix}"

    def r_str(v):
        return "N/A" if v is None else f"{v:+.2f}R"

    out_dir = os.path.join(LOG_DIR, "backtest_reports")
    os.makedirs(out_dir, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    pdf_path = os.path.join(out_dir, f"signal_pnl_backtest_{today}.pdf")

    with tempfile.TemporaryDirectory() as tmp:
        eq_png = os.path.join(tmp, "equity.png")
        dd_png = os.path.join(tmp, "drawdown.png")
        hist_png = os.path.join(tmp, "histogram.png")
        monthly_png = os.path.join(tmp, "monthly.png")
        ls_png = os.path.join(tmp, "long_short.png")

        _chart_equity_curve(metrics, eq_png)
        _chart_drawdown(metrics, dd_png)
        has_hist = _chart_daily_histogram(metrics, hist_png)
        has_monthly = _chart_monthly_pnl(metrics, monthly_png)
        has_ls_chart = _chart_long_short_comparison(metrics.get("long_short") or {}, ls_png)

        styles = getSampleStyleSheet()
        h1 = ParagraphStyle("h1", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=20, textColor=rl_colors.white, spaceAfter=2)
        sub = ParagraphStyle("sub", fontName="Helvetica", fontSize=9, textColor=rl_colors.HexColor("#9CA3AF"))
        h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13, textColor=rl_colors.HexColor("#111827"), spaceBefore=14, spaceAfter=6)
        caption = ParagraphStyle("caption", fontName="Helvetica-Oblique", fontSize=8, textColor=rl_colors.HexColor("#6B7280"), spaceAfter=6)
        warn = ParagraphStyle("warn", fontName="Helvetica-Oblique", fontSize=8.5, textColor=rl_colors.HexColor("#854D0E"), backColor=rl_colors.HexColor("#FEF9C3"))

        story = []

        # ---- Header banner ----
        header_tbl = Table(
            [[Paragraph(_esc("F&O Sniper -- Signal P&L Backtest"), h1)],
             [Paragraph(_esc(f"Capital base Rs {metrics['capital_base']:,.0f}  |  {metrics['total_trades']} resolved trades "
                        f"({metrics['wins']}W / {metrics['losses']}L / {metrics['flats']} flat)  |  "
                        f"{metrics['total_days_span']} day span  |  generated {today}"), sub)]],
            colWidths=[180 * mm],
        )
        header_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), rl_colors.HexColor("#1F2937")),
            ("LEFTPADDING", (0, 0), (-1, -1), 12), ("TOPPADDING", (0, 0), (-1, 0), 10),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
        ]))
        story.append(header_tbl)
        story.append(Spacer(1, 4 * mm))

        if metrics["total_trades"] < 20:
            story.append(Paragraph(_esc(
                "⚠ Small sample -- treat everything below as a rough first look, not a verified edge. "
                "Same caution as every other backtest in this project."), warn))
            story.append(Spacer(1, 3 * mm))

        # ---- Strategy Scorecard -- P0 upgrade spec item, added Aug 29
        # 2026. Status rule (Promising: PF >= 1.5 AND Win Rate >= 45%;
        # Insufficient Sample: below 20 trades, same floor the small-
        # sample warning above already uses) was confirmed with him
        # directly, over a looser PF-only alternative. The full
        # disclosed logic lives in compute_scorecard_status() -- this
        # block only renders metrics["scorecard_status"]. ----
        story.append(Paragraph(_esc("Strategy Scorecard"), h2))

        status = metrics["scorecard_status"]
        status_colors = {
            "Promising": "#16A34A",
            "Weak": "#D97706",
            "Insufficient Sample": "#6B7280",
        }
        status_bg = status_colors.get(status, "#6B7280")
        status_h_style = ParagraphStyle("status_h", fontName="Helvetica-Bold", fontSize=15, textColor=rl_colors.white, spaceAfter=2)
        status_r_style = ParagraphStyle("status_r", fontName="Helvetica", fontSize=8.5, textColor=rl_colors.white, leading=11)
        status_tbl = Table(
            [[Paragraph(_esc(f"STATUS: {status.upper()}"), status_h_style)],
             [Paragraph(_esc(metrics["scorecard_status_reason"]), status_r_style)]],
            colWidths=[180 * mm],
        )
        status_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), rl_colors.HexColor(status_bg)),
            ("LEFTPADDING", (0, 0), (-1, -1), 12), ("TOPPADDING", (0, 0), (-1, 0), 8),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
        ]))
        story.append(status_tbl)
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(_esc(
            "Fixed, disclosed rule: Promising needs Profit Factor >= 1.5 AND Win Rate >= 45%, both. Below 20 "
            "resolved trades it's always Insufficient Sample, regardless of how good the numbers look -- not "
            "enough data yet to trust a verdict either way."), caption))

        dd_rs = f"{metrics['max_drawdown']['depth']:,.0f}" if metrics["max_drawdown"] else "N/A"
        dd_pct = f"{metrics['max_drawdown']['depth_pct']}%" if metrics["max_drawdown"] else "N/A"

        headline_rows = [
            ["Starting Capital (Rs)", f"{metrics['capital_base']:,.0f}"],
            ["Net P&L (Rs)", f"{metrics['net_pnl']:,.0f}"],
            ["Return %", na(metrics["net_pnl_pct"], "%")],
            ["Trades", str(metrics["total_trades"])],
            ["Win Rate", na(metrics["win_rate_pct"], "%")],
            ["Profit Factor", na(metrics["profit_factor"])],
            ["Expectancy/Trade (Rs)", na(metrics["expectancy"])],
            ["Max Drawdown (Rs / %)", f"{dd_rs} / {dd_pct}"],
        ]
        headline_table = Table(headline_rows, colWidths=[75 * mm, 105 * mm])
        headline_style_cmds = [
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#E5E7EB")),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [rl_colors.white, rl_colors.HexColor("#F9FAFB")]),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]
        # Sign-colored only where sign is meaningful: Net P&L, Return %,
        # Expectancy (green/red), and Max Drawdown (always red when it
        # exists -- a drawdown is never a positive number worth
        # coloring green). Trades/Win Rate/Profit Factor/Starting
        # Capital stay neutral, same reasoning as every other table
        # in this report.
        for row_idx, key in [(1, "net_pnl"), (2, "net_pnl_pct"), (6, "expectancy")]:
            _, text_hex = _pos_neg_hex(metrics[key])
            headline_style_cmds.append(("TEXTCOLOR", (1, row_idx), (1, row_idx), rl_colors.HexColor(text_hex)))
        if metrics["max_drawdown"]:
            headline_style_cmds.append(("TEXTCOLOR", (1, 7), (1, 7), rl_colors.HexColor("#991B1B")))
        headline_table.setStyle(TableStyle(headline_style_cmds))
        story.append(headline_table)
        story.append(Spacer(1, 5 * mm))

        secondary_rows = [
            ["Average Win (Rs)", na(metrics["avg_win"])],
            ["Average Loss (Rs)", na(metrics["avg_loss"])],
            ["Winning Days", str(metrics["winning_days"])],
            ["Losing Days", str(metrics["losing_days"])],
            ["Average Holding Time", _fmt_holding(metrics["avg_holding_minutes"])],
        ]
        secondary_table = Table(secondary_rows, colWidths=[75 * mm, 105 * mm])
        secondary_style_cmds = [
            ("FONTNAME", (0, 0), (0, -1), "Helvetica"),
            ("TEXTCOLOR", (0, 0), (0, -1), rl_colors.HexColor("#6B7280")),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#F3F4F6")),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]
        _, win_t = _pos_neg_hex(metrics["avg_win"])
        secondary_style_cmds.append(("TEXTCOLOR", (1, 0), (1, 0), rl_colors.HexColor(win_t)))
        _, loss_t = _pos_neg_hex(metrics["avg_loss"])
        secondary_style_cmds.append(("TEXTCOLOR", (1, 1), (1, 1), rl_colors.HexColor(loss_t)))
        secondary_table.setStyle(TableStyle(secondary_style_cmds))
        story.append(secondary_table)
        story.append(Spacer(1, 4 * mm))

        story.append(PageBreak())

        # ---- KPI card grid, 4 across, 2 rows ----
        pf_bg, pf_t = _rating_hex(metrics["profit_factor"], 1.5, 1.0)
        wr_bg, wr_t = _rating_hex(metrics["win_rate_pct"], 60, 45)
        dd_bg, dd_t = ("#FEE2E2", "#991B1B") if metrics["max_drawdown"] else ("#F3F4F6", "#4B5563")
        pnl_bg, pnl_t = _pos_neg_hex(metrics["net_pnl"])
        sharpe_bg, sharpe_t = _rating_hex(metrics["sharpe"], 1.0, 0.0)
        sortino_bg, sortino_t = _rating_hex(metrics["sortino"], 1.5, 0.0)
        calmar_bg, calmar_t = _rating_hex(metrics["calmar"], 3.0, 1.0)
        cagr_bg, cagr_t = _pos_neg_hex(metrics["cagr_pct"])

        row1 = [
            _kpi_card("Net P&L", f"Rs {metrics['net_pnl']:,.0f}",
                      f"{na(metrics['net_pnl_pct'], '%')} of capital deployed -- the bottom line everything else here explains.",
                      pnl_bg, pnl_t),
            _kpi_card("Win Rate", f"{metrics['win_rate_pct']}%" if metrics['win_rate_pct'] is not None else "N/A",
                      f"{metrics['wins']} of {metrics['total_trades']} trades profitable. A low win rate can still be profitable -- check Profit Factor too.",
                      wr_bg, wr_t),
            _kpi_card("Profit Factor", na(metrics["profit_factor"]),
                      "Total Rs won / total Rs lost. Above 1 = profitable overall, above 1.5 is solid.",
                      pf_bg, pf_t),
            _kpi_card("Max Drawdown", f"{metrics['max_drawdown']['depth_pct']}%" if metrics['max_drawdown'] else "N/A",
                      "The single worst peak-to-trough decline anywhere in this data -- the real pain of the roughest stretch.",
                      dd_bg, dd_t),
        ]
        row2 = [
            _kpi_card("Sharpe Ratio", na(metrics["sharpe"]),
                      "Return per unit of total volatility. Above 1 is good, above 2 very good. Needs 2+ days of data.",
                      sharpe_bg, sharpe_t),
            _kpi_card("Sortino Ratio", na(metrics["sortino"]),
                      "Like Sharpe, but only penalizes downside swings. Usually reads higher than Sharpe.",
                      sortino_bg, sortino_t),
            _kpi_card("Calmar Ratio", na(metrics["calmar"]),
                      "Annual return relative to the worst drawdown -- return earned for the pain endured.",
                      calmar_bg, calmar_t),
            _kpi_card("CAGR (Annualised)", na(metrics["cagr_pct"], '%'),
                      "What this rate would compound to over a year. N/A under a week of data -- too short to annualize honestly.",
                      cagr_bg, cagr_t),
        ]
        grid = Table([row1, [Spacer(1, 3 * mm)] * 4, row2], colWidths=[45 * mm] * 4)
        grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(grid)
        story.append(Spacer(1, 6 * mm))

        # ---- Profit vs Loss Breakdown -- Net P&L above only shows the
        # NETTED number. This makes both sides explicit: how much was
        # actually won vs actually lost, not just the difference between
        # them, plus the single best/worst trade and day either way. ----
        story.append(Paragraph(_esc("Profit vs Loss Breakdown"), h2))
        story.append(Paragraph(_esc(
            "Net P&L above is profit minus loss combined into one number. This breaks both sides out separately, "
            "so the losses aren't hidden inside the net figure."), caption))

        best_trade_str = f"Rs {metrics['best_trade']:,.0f}" if metrics['best_trade'] is not None else "N/A"
        worst_trade_str = f"Rs {metrics['worst_trade']:,.0f}" if metrics['worst_trade'] is not None else "N/A"
        best_day_str = f"{metrics['best_day'][0]}  Rs {metrics['best_day'][1]:,.0f}" if metrics['best_day'] else "N/A"
        worst_day_str = f"{metrics['worst_day'][0]}  Rs {metrics['worst_day'][1]:,.0f}" if metrics['worst_day'] else "N/A"
        underwater_str = (f"Rs {metrics['currently_underwater']['depth']:,.0f} ({metrics['currently_underwater']['depth_pct']}%) "
                           f"since {metrics['currently_underwater']['peak_dt'].strftime('%Y-%m-%d')}") if metrics['currently_underwater'] else "No -- at or above the last peak"

        breakdown_rows = [
            ["Gross Profit (all winning trades)", f"Rs {metrics['gross_profit']:,.0f}"],
            ["Gross Loss (all losing trades)", f"Rs {metrics['gross_loss']:,.0f}"],
            ["Best single trade", best_trade_str],
            ["Worst single trade", worst_trade_str],
            ["Best single day", best_day_str],
            ["Worst single day", worst_day_str],
            ["Currently underwater", underwater_str],
        ]
        breakdown_table = Table(breakdown_rows, colWidths=[75 * mm, 105 * mm])
        style_cmds = [
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#E5E7EB")),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [rl_colors.white, rl_colors.HexColor("#F9FAFB")]),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            # Green text for the profit/best rows, red for the loss/worst rows -- the actual fix for
            # "only showing profit" -- loss figures are now their own visible, clearly-labeled rows.
            ("TEXTCOLOR", (1, 0), (1, 0), rl_colors.HexColor("#166534")),
            ("TEXTCOLOR", (1, 1), (1, 1), rl_colors.HexColor("#991B1B")),
            ("TEXTCOLOR", (1, 2), (1, 2), rl_colors.HexColor("#166534")),
            ("TEXTCOLOR", (1, 3), (1, 3), rl_colors.HexColor("#991B1B")),
            ("TEXTCOLOR", (1, 4), (1, 4), rl_colors.HexColor("#166534")),
            ("TEXTCOLOR", (1, 5), (1, 5), rl_colors.HexColor("#991B1B")),
        ]
        if metrics["currently_underwater"]:
            style_cmds.append(("TEXTCOLOR", (1, 6), (1, 6), rl_colors.HexColor("#854D0E")))
        breakdown_table.setStyle(TableStyle(style_cmds))
        story.append(breakdown_table)
        story.append(Spacer(1, 6 * mm))

        # ---- Equity + Drawdown charts ----
        story.append(Paragraph(_esc("Equity Curve"), h2))
        story.append(Paragraph(_esc(
            "Running account value after every trade, in the order each one actually closed. The dashed line marks "
            "where you started (the capital base above) -- above it means net ahead overall, below means net behind."), caption))
        story.append(RLImage(eq_png, width=180 * mm, height=180 * mm * (3.4 / 9)))
        story.append(Paragraph(_esc("Drawdown %"), h2))
        story.append(Paragraph(_esc(
            "How far below the highest point reached so far the account was at each moment, as a %. Always zero or "
            "negative -- 0 means sitting at a new high, a deep dip means a real losing stretch that hadn't recovered yet."), caption))
        story.append(RLImage(dd_png, width=180 * mm, height=180 * mm * (2.6 / 9)))

        # ---- R-Multiple Analysis -- P0 upgrade spec item, added Aug 29
        # 2026. Measures setup quality independent of rupee sizing:
        # Realized R = P&L / Initial Risk (Entry - SL), already computed
        # and tested per-trade in compute_r_multiple() / load_all_trades(),
        # and already summarized by summarize_r_multiples() into
        # metrics["r_multiple"]. This block only renders that existing
        # dict -- no new computation happens here. ----
        story.append(Paragraph(_esc("R-Multiple Analysis"), h2))
        story.append(Paragraph(_esc(
            "How many multiples of initial risk (Entry minus SL) each trade returned, independent of position "
            "size or premium level -- a Rs 5-risk trade that made Rs 15 is +3R the same as a Rs 50-risk trade "
            "that made Rs 150. This is what actually measures setup quality; rupee P&L above doesn't."), caption))

        rm = metrics.get("r_multiple")
        if rm is None:
            story.append(Paragraph(_esc(
                "N/A -- no trade in this backtest had a valid Entry/SL pair to compute Initial Risk from."), warn))
        else:
            rm_rows = [
                ["Average R", r_str(rm["avg_r"])],
                ["Median R", r_str(rm["median_r"])],
                ["Best single trade", r_str(rm["best_r"])],
                ["Worst single trade", r_str(rm["worst_r"])],
                ["Trades \u2265 +1R", f"{rm['pct_ge_1r']}%"],
                ["Trades \u2265 +2R", f"{rm['pct_ge_2r']}%"],
                ["Trades \u2264 -1R", f"{rm['pct_le_neg1r']}%"],
                ["Average winning R", r_str(rm["avg_winning_r"])],
                ["Average losing R", r_str(rm["avg_losing_r"])],
            ]
            rm_table = Table(rm_rows, colWidths=[75 * mm, 105 * mm])
            rm_style_cmds = [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#E5E7EB")),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [rl_colors.white, rl_colors.HexColor("#F9FAFB")]),
                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]
            # Sign-based coloring only on the actual R-value rows (0-3,
            # 7-8) -- the % rows (4-6) are always non-negative by
            # definition, so coloring them by raw sign would be
            # meaningless at best and backwards at worst: a HIGH
            # "Trades <= -1R" is a BAD result, not a green one.
            for row_idx, key in [(0, "avg_r"), (1, "median_r"), (2, "best_r"), (3, "worst_r"),
                                  (7, "avg_winning_r"), (8, "avg_losing_r")]:
                _, text_hex = _pos_neg_hex(rm[key])
                rm_style_cmds.append(("TEXTCOLOR", (1, row_idx), (1, row_idx), rl_colors.HexColor(text_hex)))
            rm_table.setStyle(TableStyle(rm_style_cmds))
            story.append(rm_table)
            story.append(Spacer(1, 2 * mm))
            story.append(Paragraph(_esc(
                f"Based on {rm['sample_size']} of {metrics['total_trades']} resolved trades with a valid Entry/SL "
                f"pair to compute Initial Risk from."), caption))

        story.append(PageBreak())

        # ---- Long vs Short -- P0 upgrade spec item, added Aug 29 2026.
        # "Long vs Short" here means bullish-vs-bearish bias (BUY/SELL
        # on the Action field), not a literal short position -- this
        # engine only ever buys option premium (calls for BUY, puts
        # for SELL), never shorts the underlying, same note as
        # compute_long_short_breakdown()'s own docstring. ----
        story.append(Paragraph(_esc("Long vs Short"), h2))
        story.append(Paragraph(_esc(
            "The same trades split by direction (BUY = bullish, SELL = bearish). Two strategies can share one "
            "blended win rate while one side is doing all the work -- this checks whether the edge genuinely "
            "holds in both directions rather than assuming it does."), caption))

        ls = metrics.get("long_short") or {}
        buy_ls, sell_ls = ls.get("BUY"), ls.get("SELL")
        known_count = (buy_ls["count"] if buy_ls else 0) + (sell_ls["count"] if sell_ls else 0)
        stray_count = metrics["total_trades"] - known_count
        if stray_count > 0:
            story.append(Paragraph(_esc(
                f"Note: {stray_count} trade(s) carried an Action value other than BUY/SELL and are excluded from "
                f"this comparison rather than guessed into one side."), warn))
            story.append(Spacer(1, 2 * mm))

        def g(side, key):
            return side.get(key) if side else None

        def rs(v):
            return "N/A" if v is None else f"{v:,.0f}"

        ls_rows = [
            ["Metric", "BUY", "SELL"],
            ["Trades", str(g(buy_ls, "count") or 0), str(g(sell_ls, "count") or 0)],
            ["Win Rate", na(g(buy_ls, "win_rate_pct"), "%"), na(g(sell_ls, "win_rate_pct"), "%")],
            ["Net P&L (Rs)", rs(g(buy_ls, "net_pnl")), rs(g(sell_ls, "net_pnl"))],
            ["Profit Factor", na(g(buy_ls, "profit_factor")), na(g(sell_ls, "profit_factor"))],
            ["Expectancy/Trade (Rs)", rs(g(buy_ls, "expectancy")), rs(g(sell_ls, "expectancy"))],
            ["Average R", r_str(g(buy_ls, "avg_r")), r_str(g(sell_ls, "avg_r"))],
            ["Avg Holding Time", _fmt_holding(g(buy_ls, "avg_holding_minutes")), _fmt_holding(g(sell_ls, "avg_holding_minutes"))],
        ]
        ls_table = Table(ls_rows, colWidths=[55 * mm, 62.5 * mm, 62.5 * mm], repeatRows=1)
        ls_style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#1F2937")),
            ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#E5E7EB")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [rl_colors.white, rl_colors.HexColor("#F9FAFB")]),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]
        # Sign-based coloring only where sign is actually meaningful --
        # Net P&L (row 3), Expectancy (row 5), Average R (row 6). Win
        # Rate/Profit Factor/Trades/Holding Time are left neutral, same
        # reasoning as the R-Multiple table above.
        for row_idx, key in [(3, "net_pnl"), (5, "expectancy"), (6, "avg_r")]:
            for col_idx, side in [(1, buy_ls), (2, sell_ls)]:
                _, text_hex = _pos_neg_hex(g(side, key))
                ls_style_cmds.append(("TEXTCOLOR", (col_idx, row_idx), (col_idx, row_idx), rl_colors.HexColor(text_hex)))
        ls_table.setStyle(TableStyle(ls_style_cmds))
        story.append(ls_table)
        story.append(Spacer(1, 5 * mm))

        if has_ls_chart:
            story.append(RLImage(ls_png, width=180 * mm, height=180 * mm * (3 / 9)))
        else:
            story.append(Paragraph(_esc(
                "No comparison chart -- one side has zero resolved trades."), caption))

        story.append(PageBreak())

        # ---- Performance by Segment -- the real answer to "why does
        # the overall number look the way it does." Shows whether
        # losses are concentrated in one Grade/Sector/OI-state/Pattern
        # or genuinely spread evenly, using real data rather than a
        # guess about what to fix. ----
        story.append(Paragraph(_esc("Performance by Segment"), h2))
        story.append(Paragraph(_esc(
            "The same trades, split by Grade, Sector, OI Confirmation, and Pattern -- shows WHERE performance is "
            "concentrated instead of one blended number. A segment with very few trades (2-3) isn't a reliable "
            "read yet, even if its win rate looks extreme -- same small-sample caution as everywhere else in this report."), caption))

        key_findings = generate_key_findings(trades)
        if key_findings:
            findings_style = ParagraphStyle("finding", fontName="Helvetica", fontSize=9, textColor=rl_colors.HexColor("#1E3A8A"), leading=13, spaceAfter=4)
            finding_rows = [[Paragraph(_esc(f"\u2022 {f}"), findings_style)] for f in key_findings]
            findings_table = Table(finding_rows, colWidths=[180 * mm])
            findings_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), rl_colors.HexColor("#EFF6FF")),
                ("BOX", (0, 0), (-1, -1), 1, rl_colors.HexColor("#BFDBFE")),
                ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            story.append(Spacer(1, 2 * mm))
            story.append(findings_table)
        story.append(Spacer(1, 4 * mm))

        def _segment_table(title, rows, max_rows=None):
            story.append(Paragraph(_esc(title), ParagraphStyle("seg_h3", fontName="Helvetica-Bold", fontSize=10, textColor=rl_colors.HexColor("#374151"), spaceBefore=8, spaceAfter=3)))
            if not rows:
                story.append(Paragraph(_esc("No data."), caption))
                return
            shown = rows[:max_rows] if max_rows else rows
            table_rows = [["Segment", "Trades", "Win Rate", "Net P&L (Rs)", "Profit Factor"]]
            for r in shown:
                table_rows.append([
                    str(r["segment"]), str(r["count"]), f"{r['win_rate_pct']}%",
                    f"{r['net_pnl']:,.0f}", na(r["profit_factor"]),
                ])
            t = Table(table_rows, colWidths=[45*mm, 22*mm, 22*mm, 35*mm, 30*mm])
            style_cmds = [
                ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#1F2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#E5E7EB")),
            ]
            for i, r in enumerate(shown, start=1):
                bg = "#DCFCE7" if r["net_pnl"] > 0 else ("#FEE2E2" if r["net_pnl"] < 0 else "#F3F4F6")
                style_cmds.append(("BACKGROUND", (3, i), (3, i), rl_colors.HexColor(bg)))
            t.setStyle(TableStyle(style_cmds))
            story.append(t)
            story.append(Spacer(1, 4 * mm))

        _segment_table("By Grade", compute_segment_breakdown(trades, "grade"))
        _segment_table("By OI Confirmation", compute_segment_breakdown(trades, "oi_confirmation"))
        _segment_table("By Pattern", compute_segment_breakdown(trades, "pattern"))

        sector_results = compute_segment_breakdown(trades, "sector")
        if len(sector_results) > 20:
            # Genuinely top 10 + bottom 10 by net P&L, not just the
            # first 10 in sorted order -- the title says top/bottom,
            # this makes that actually true rather than misleading.
            sector_shown = sector_results[:10] + sector_results[-10:]
            _segment_table(f"By Sector (top 10 and bottom 10 of {len(sector_results)} by net P&L)", sector_shown)
        else:
            _segment_table("By Sector", sector_results)

        story.append(PageBreak())

        # ---- Worst Drawdowns table ----
        story.append(Paragraph(_esc("Worst Drawdowns"), h2))
        story.append(Paragraph(_esc(
            "The 5 deepest peak-to-trough declines in account value, worst first. 'Recovered' shows when "
            "equity climbed back to the pre-drawdown peak -- '--' means it hasn't yet."), caption))
        dd_rows = [["#", "Depth (Rs)", "Depth %", "Peak Date", "Trough Date", "Recovered", "Status"]]
        sorted_dd = sorted(metrics["drawdown_periods"], key=lambda d: d["depth"])[:5]
        for i, d in enumerate(sorted_dd, 1):
            dd_rows.append([
                str(i), f"{d['depth']:,.0f}", f"{d['depth_pct']}%",
                d["peak_dt"].strftime("%Y-%m-%d %H:%M"), d["trough_dt"].strftime("%Y-%m-%d %H:%M"),
                d["recovered_dt"].strftime("%Y-%m-%d %H:%M") if d["recovered_dt"] else "--",
                d["status"],
            ])
        if len(dd_rows) > 1:
            dd_table = Table(dd_rows, colWidths=[10*mm, 25*mm, 20*mm, 32*mm, 32*mm, 32*mm, 22*mm], repeatRows=1)
            style_cmds = [
                ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#1F2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#E5E7EB")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [rl_colors.white, rl_colors.HexColor("#F9FAFB")]),
            ]
            for i in range(1, len(dd_rows)):
                if dd_rows[i][-1] == "Ongoing":
                    style_cmds.append(("BACKGROUND", (-1, i), (-1, i), rl_colors.HexColor("#FEF9C3")))
            dd_table.setStyle(TableStyle(style_cmds))
            story.append(dd_table)
        else:
            story.append(Paragraph(_esc("No drawdown periods yet."), caption))
        story.append(Spacer(1, 6 * mm))

        # ---- Daily Return Distribution ----
        if has_hist:
            story.append(Paragraph(_esc("Daily Return Distribution"), h2))
            story.append(Paragraph(_esc(
                "How many days landed in each return range. Red bars = losing days, green = winning days. A cluster "
                "of tall bars near zero with a few scattered further out is normal -- most days small, a few days big."), caption))
            story.append(RLImage(hist_png, width=180 * mm, height=180 * mm * (3 / 9)))

        # ---- Monthly Performance ----
        if has_monthly:
            story.append(Paragraph(_esc("Monthly Performance"), h2))
            story.append(Paragraph(_esc(
                "Total P&L for each calendar month. A month can only show one bar even if it had both winning and "
                "losing days inside it -- see Daily Return Distribution above for the day-by-day win/loss split."), caption))
            story.append(RLImage(monthly_png, width=180 * mm, height=180 * mm * (2.8 / 9)))
            month_rows = [["Month", "P&L (Rs)", "Trades"]]
            for month, v in metrics["monthly_pnl"].items():
                month_rows.append([month, f"{v['pnl']:,.0f}", str(v["trades"])])
            month_table = Table(month_rows, colWidths=[40*mm, 40*mm, 30*mm], repeatRows=1)
            month_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#1F2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#E5E7EB")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [rl_colors.white, rl_colors.HexColor("#F9FAFB")]),
            ]))
            story.append(Spacer(1, 3 * mm))
            story.append(month_table)

        story.append(PageBreak())

        # ---- Full Trade Log -- Platypus paginates this automatically
        # across as many pages as needed, header repeats on each page. ----
        story.append(Paragraph(_esc("Trade Log"), h2))
        story.append(Paragraph(_esc(f"All {len(trades)} resolved trades, most recent first."), caption))
        trade_rows = [["Symbol", "Action", "Entry Time", "Exit Time", "Entry", "Exit", "Qty", "P&L (Rs)", "Reason"]]
        for t in reversed(trades):
            trade_rows.append([
                t["symbol"], t["action"], t["entry_dt"].strftime("%Y-%m-%d %H:%M"), t["exit_dt"].strftime("%Y-%m-%d %H:%M"),
                f"{t['entry']:.2f}", f"{t['exit_price']:.2f}", str(t["qty"]), f"{t['pnl']:,.0f}", t["exit_reason"][:22],
            ])
        trade_table = Table(trade_rows, colWidths=[20*mm, 15*mm, 26*mm, 26*mm, 16*mm, 16*mm, 14*mm, 22*mm, 30*mm], repeatRows=1)
        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#1F2937")),
            ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#E5E7EB")),
            # Aug 23 2026: was 1 BACKGROUND style command PER TRADE here
            # (210 of them on his real data) -- that count grows every
            # single day as more trades resolve, and was very likely the
            # dominant real cause of "the PDF is very very laggy," more
            # than the charts. ROWBACKGROUNDS is a single native command
            # that alternates row shading regardless of table size --
            # same visual readability, cost doesn't scale with trade
            # count anymore. The Profit vs Loss Breakdown and Performance
            # by Segment pages already carry the green/red semantic
            # coloring; this table's job is complete reference detail,
            # not a second pass at visual pattern-scanning.
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [rl_colors.white, rl_colors.HexColor("#F9FAFB")]),
        ]
        trade_table.setStyle(TableStyle(style_cmds))
        story.append(trade_table)

        doc = SimpleDocTemplate(pdf_path, pagesize=A4, topMargin=12*mm, bottomMargin=12*mm, leftMargin=15*mm, rightMargin=15*mm)
        try:
            doc.build(story)
        except PermissionError:
            # Windows locks a file that's open in a viewer (Acrobat/Edge/
            # etc) against being overwritten -- a very real, very likely
            # thing to hit given the natural workflow here is regenerating
            # this same file repeatedly while keeping the previous version
            # open to compare against. Rather than crash and lose all the
            # real computation that already succeeded above, fall back to
            # a timestamped filename instead.
            alt_path = os.path.join(out_dir, f"signal_pnl_backtest_{today}_{datetime.now().strftime('%H%M%S')}.pdf")
            print(f"'{os.path.basename(pdf_path)}' is locked (probably still open in a PDF viewer) -- "
                  f"writing to '{os.path.basename(alt_path)}' instead.")
            doc = SimpleDocTemplate(alt_path, pagesize=A4, topMargin=12*mm, bottomMargin=12*mm, leftMargin=15*mm, rightMargin=15*mm)
            doc.build(story)
            pdf_path = alt_path

    return pdf_path


def write_report(trades, metrics, capital_per_trade=DEFAULT_CAPITAL_PER_TRADE):
    """
    Builds the full Excel report. Six sheets: Dashboard (a colorful
    landing page -- big color-coded KPI cards each with a plain-
    language explanation, plus the equity curve and drawdown charts),
    Summary (the same stats as a clean text table, for anyone who wants
    to read/copy the raw numbers), Trades (every trade, with a
    conditional-formatting P&L heatmap), Monthly Performance, Worst
    Drawdowns, and Daily Returns (with a histogram).

    Aug 23 2026 rewrite: the first version's charts had a real bug --
    openpyxl leaves the "vary colors by point" chart setting
    unspecified, and Excel's own default for that turned out to be ON,
    so every single data point got its own color AND its own legend
    entry (a trade number, or a bin percentage) instead of one
    consistent line/bar with one legend entry for the whole series.
    Confirmed by inspecting the raw chart XML in a minimal repro before
    touching anything -- every chart below now explicitly sets
    varyColors = False. The underlying NUMBERS were never wrong, only
    this rendering setting was.

    Saved to signal_logs/backtest_reports/signal_pnl_backtest_<today>.xlsx.
    Returns the path, or None if there's nothing to report yet.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.chart import LineChart, BarChart, Reference
    from openpyxl.formatting.rule import DataBarRule, CellIsRule
    from openpyxl.utils import get_column_letter

    if metrics is None:
        return None

    def na(v, suffix=""):
        return "N/A" if v is None else f"{v}{suffix}"

    wb = Workbook()

    # ---- shared style constants ----
    DARK = "1F2937"       # banner background
    GREEN = "C6EFCE"      # positive fill
    GREEN_FONT = "006100"
    RED = "FFC7CE"        # negative / risk fill
    RED_FONT = "9C0006"
    AMBER = "FFEB9C"      # neutral/caution fill
    AMBER_FONT = "9C6500"
    GREY = "F3F4F6"       # neutral card background
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor=DARK)
    thin_border = Border(*[Side(style="thin", color="D1D5DB")] * 4)

    def pos_neg_fill(value):
        if value is None:
            return PatternFill("solid", fgColor=GREY), Font(color="6B7280")
        if value > 0:
            return PatternFill("solid", fgColor=GREEN), Font(bold=True, color=GREEN_FONT)
        if value < 0:
            return PatternFill("solid", fgColor=RED), Font(bold=True, color=RED_FONT)
        return PatternFill("solid", fgColor=GREY), Font(bold=True, color="374151")

    def style_chart(chart, title, y_title, x_title="Trade #"):
        chart.title = title
        chart.y_axis.title = y_title
        chart.x_axis.title = x_title
        chart.varyColors = False  # THE fix -- one consistent color per series, one legend entry
        chart.legend = None       # a legend showing just one entry ("Equity") adds nothing -- drop it
        chart.height, chart.width = 9, 18
        return chart

    # =====================================================================
    # DASHBOARD -- the landing page. Big color-coded KPI cards, each with
    # a one-line plain-language explanation, so the numbers mean something
    # without needing to already know what Sharpe/Sortino/Calmar are.
    # =====================================================================
    dash = wb.active
    dash.title = "Dashboard"
    dash.sheet_view.showGridLines = False

    dash.merge_cells("A1:H2")
    dash["A1"] = "  F&O Sniper -- Signal P&L Backtest"
    dash["A1"].font = Font(bold=True, size=18, color="FFFFFF")
    dash["A1"].fill = PatternFill("solid", fgColor=DARK)
    dash["A1"].alignment = Alignment(vertical="center")
    for col in range(1, 9):
        dash.cell(row=1, column=col).fill = PatternFill("solid", fgColor=DARK)
        dash.cell(row=2, column=col).fill = PatternFill("solid", fgColor=DARK)

    dash.merge_cells("A3:H3")
    dash["A3"] = (f"Capital base Rs {metrics['capital_base']:,.0f}  |  {metrics['total_trades']} resolved trades "
                  f"({metrics['wins']}W / {metrics['losses']}L / {metrics['flats']} flat)  |  {metrics['total_days_span']} day span")
    dash["A3"].font = Font(italic=True, color="6B7280")

    if metrics['total_trades'] < 20:
        dash.merge_cells("A4:H4")
        dash["A4"] = "⚠ Small sample -- treat everything below as a rough first look, not a verified edge. Same caution as every other backtest in this project."
        dash["A4"].font = Font(italic=True, color=AMBER_FONT, size=10)
        dash["A4"].fill = PatternFill("solid", fgColor=AMBER)

    def kpi_card(row, col, label, value_str, explanation, fill_hex, font_hex):
        """A 2-column-wide, 4-row-tall colored card: label, big value, explanation."""
        cl = get_column_letter(col)
        cl2 = get_column_letter(col + 1)
        dash.merge_cells(f"{cl}{row}:{cl2}{row}")
        dash.merge_cells(f"{cl}{row+1}:{cl2}{row+2}")
        dash.merge_cells(f"{cl}{row+3}:{cl2}{row+4}")
        dash[f"{cl}{row}"] = label
        dash[f"{cl}{row}"].font = Font(bold=True, size=10, color=font_hex)
        dash[f"{cl}{row+1}"] = value_str
        dash[f"{cl}{row+1}"].font = Font(bold=True, size=20, color=font_hex)
        dash[f"{cl}{row+1}"].alignment = Alignment(vertical="center")
        dash[f"{cl}{row+3}"] = explanation
        dash[f"{cl}{row+3}"].font = Font(size=9, color=font_hex, italic=True)
        dash[f"{cl}{row+3}"].alignment = Alignment(wrap_text=True, vertical="top")
        for r in range(row, row + 5):
            for c in (col, col + 1):
                dash.cell(row=r, column=c).fill = PatternFill("solid", fgColor=fill_hex)

    def rating_color(value, good_threshold, ok_threshold, higher_is_better=True):
        if value is None:
            return GREY, "6B7280"
        if higher_is_better:
            if value >= good_threshold:
                return GREEN, GREEN_FONT
            if value >= ok_threshold:
                return AMBER, AMBER_FONT
            return RED, RED_FONT
        else:
            if value <= good_threshold:
                return GREEN, GREEN_FONT
            if value <= ok_threshold:
                return AMBER, AMBER_FONT
            return RED, RED_FONT

    row0 = 6
    pnl_fill, pnl_font = pos_neg_fill(metrics['net_pnl'])
    kpi_card(row0, 1, "NET P&L",
              f"Rs {metrics['net_pnl']:,.0f}",
              f"{metrics['net_pnl_pct']}% of capital deployed. This is the bottom line -- everything else on this page explains HOW it got here.",
              pnl_fill.fgColor.rgb[2:], pnl_font.color.rgb[2:])

    wr_fill, wr_font = rating_color(metrics['win_rate_pct'], 60, 45)
    kpi_card(row0, 3, "WIN RATE",
              f"{metrics['win_rate_pct']}%" if metrics['win_rate_pct'] is not None else "N/A",
              f"{metrics['wins']} of {metrics['total_trades']} trades profitable. A LOW win rate can still be profitable if winners are much bigger than losers -- check Profit Factor too.",
              wr_fill, wr_font)

    pf_fill, pf_font = rating_color(metrics['profit_factor'], 1.5, 1.0)
    kpi_card(row0, 5, "PROFIT FACTOR",
              na(metrics['profit_factor']),
              "Total Rs won / total Rs lost. Above 1 = profitable overall. Above 1.5 is solid. This is often more telling than win rate alone.",
              pf_fill, pf_font)

    dd_fill, dd_font = (RED, RED_FONT) if metrics['max_drawdown'] else (GREY, "6B7280")
    kpi_card(row0, 7, "MAX DRAWDOWN",
              f"{metrics['max_drawdown']['depth_pct']}%" if metrics['max_drawdown'] else "N/A",
              "The single worst peak-to-trough decline in account value anywhere in this data. This is the real pain you'd have felt holding through the roughest stretch.",
              dd_fill, dd_font)

    row1 = row0 + 6
    sharpe_fill, sharpe_font = rating_color(metrics['sharpe'], 1.0, 0.0)
    kpi_card(row1, 1, "SHARPE RATIO",
              na(metrics['sharpe']),
              "Return earned per unit of TOTAL volatility (up and down swings both count against it). Above 1 is good, above 2 is very good. N/A needs at least 2 days of data.",
              sharpe_fill, sharpe_font)

    sortino_fill, sortino_font = rating_color(metrics['sortino'], 1.5, 0.0)
    kpi_card(row1, 3, "SORTINO RATIO",
              na(metrics['sortino']),
              "Like Sharpe, but only penalizes DOWNSIDE swings -- ignores the upside volatility that Sharpe unfairly punishes. Usually reads higher than Sharpe for the same data.",
              sortino_fill, sortino_font)

    calmar_fill, calmar_font = rating_color(metrics['calmar'], 3.0, 1.0)
    kpi_card(row1, 5, "CALMAR RATIO",
              na(metrics['calmar']),
              "Annual return relative to the worst drawdown. Higher means better return for the pain endured. N/A if there's been no real drawdown yet to divide by.",
              calmar_fill, calmar_font)

    cagr_fill, cagr_font = pos_neg_fill(metrics['cagr_pct'])
    kpi_card(row1, 7, "CAGR (ANNUALISED)",
              na(metrics['cagr_pct'], '%'),
              "What this rate of return would compound to over a full year, if it continued exactly as-is. N/A until there's at least a week of real data -- shorter periods give wildly misleading annualized numbers.",
              cagr_fill.fgColor.rgb[2:], cagr_font.color.rgb[2:])

    for r in range(row0, row1 + 5):
        dash.row_dimensions[r].height = 15 if r not in (row0 + 1, row0 + 2, row1 + 1, row1 + 2) else 18
    for c in range(1, 9):
        dash.column_dimensions[get_column_letter(c)].width = 15

    # Equity curve + drawdown data, built fresh here (not reused from
    # Summary) so the Dashboard sheet is fully self-contained.
    chart_row0 = row1 + 7
    dash.cell(row=chart_row0, column=1, value="Trade #").font = header_font
    dash.cell(row=chart_row0, column=1).fill = header_fill
    dash.cell(row=chart_row0, column=2, value="Equity").font = header_font
    dash.cell(row=chart_row0, column=2).fill = header_fill
    dash.cell(row=chart_row0, column=3, value="Drawdown %").font = header_font
    dash.cell(row=chart_row0, column=3).fill = header_fill

    running_peak = metrics["capital_base"]
    for i, point in enumerate(metrics["equity_curve"]):
        dash.cell(row=chart_row0 + 1 + i, column=1, value=i + 1)
        dash.cell(row=chart_row0 + 1 + i, column=2, value=point["equity"])
        running_peak = max(running_peak, point["equity"])
        dd_pct = round((point["equity"] - running_peak) / running_peak * 100, 2)
        dash.cell(row=chart_row0 + 1 + i, column=3, value=dd_pct)

    n_points = len(metrics["equity_curve"])
    if n_points >= 2:
        eq_chart = style_chart(LineChart(), "Equity Curve", "Equity (Rs)")
        data = Reference(dash, min_col=2, min_row=chart_row0, max_row=chart_row0 + n_points)
        cats = Reference(dash, min_col=1, min_row=chart_row0 + 1, max_row=chart_row0 + n_points)
        eq_chart.add_data(data, titles_from_data=True)
        eq_chart.set_categories(cats)
        dash.add_chart(eq_chart, f"E{chart_row0}")

        dd_chart = style_chart(LineChart(), "Drawdown %", "% from peak")
        dd_data = Reference(dash, min_col=3, min_row=chart_row0, max_row=chart_row0 + n_points)
        dd_chart.add_data(dd_data, titles_from_data=True)
        dd_chart.set_categories(cats)
        dash.add_chart(dd_chart, f"E{chart_row0 + 19}")

    # =====================================================================
    # SUMMARY -- the same numbers as clean text, for anyone who wants to
    # read or copy the raw figures without the card layout.
    # =====================================================================
    ws = wb.create_sheet("Summary")
    ws["A1"] = "Signal P&L Backtest -- Summary"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Capital base: Rs {metrics['capital_base']:,.0f}  (each trade sized at Rs {capital_per_trade:,.0f}, matching views.py's own qty=max(1,int(50000/entry)) convention)"
    ws["A3"] = f"Period: {metrics['total_days_span']} days  |  {metrics['total_trades']} resolved trades ({metrics['wins']} wins, {metrics['losses']} losses, {metrics['flats']} flat)"

    summary_rows = [
        ("Net P&L", f"Rs {metrics['net_pnl']:,.0f} ({na(metrics['net_pnl_pct'], '%')})", metrics['net_pnl']),
        ("CAGR (annualised)", na(metrics['cagr_pct'], '%'), metrics['cagr_pct']),
        ("Max Drawdown", f"{na(metrics['max_drawdown']['depth_pct'] if metrics['max_drawdown'] else None, '%')}" + (f"  (Rs {metrics['max_drawdown']['depth']:,.0f})" if metrics['max_drawdown'] else ""), (metrics['max_drawdown']['depth_pct'] if metrics['max_drawdown'] else None)),
        ("Calmar Ratio (CAGR / MaxDD)", na(metrics['calmar']), metrics['calmar']),
        ("Sharpe (annualised)", na(metrics['sharpe']), metrics['sharpe']),
        ("Sortino (annualised)", na(metrics['sortino']), metrics['sortino']),
        ("Win Rate", na(metrics['win_rate_pct'], '%'), None),
        ("Profit Factor", na(metrics['profit_factor']), None),
        ("Best trade", f"Rs {metrics['best_trade']:,.0f}" if metrics['best_trade'] is not None else "N/A", metrics['best_trade']),
        ("Worst trade", f"Rs {metrics['worst_trade']:,.0f}" if metrics['worst_trade'] is not None else "N/A", metrics['worst_trade']),
        ("Best day", f"{metrics['best_day'][0]}  Rs {metrics['best_day'][1]:,.0f}" if metrics['best_day'] else "N/A", metrics['best_day'][1] if metrics['best_day'] else None),
        ("Worst day", f"{metrics['worst_day'][0]}  Rs {metrics['worst_day'][1]:,.0f}" if metrics['worst_day'] else "N/A", metrics['worst_day'][1] if metrics['worst_day'] else None),
        ("Currently underwater", (f"Rs {metrics['currently_underwater']['depth']:,.0f} ({metrics['currently_underwater']['depth_pct']}%) since {metrics['currently_underwater']['peak_dt'].strftime('%Y-%m-%d')}" if metrics['currently_underwater'] else "No -- at or above the last peak"), None),
    ]
    start_row = 5
    for i, (label, value, color_by) in enumerate(summary_rows):
        r = start_row + i
        ws.cell(row=r, column=1, value=label).font = Font(bold=True)
        vcell = ws.cell(row=r, column=2, value=value)
        if color_by is not None:
            fill, font = pos_neg_fill(color_by)
            vcell.fill = fill
            vcell.font = font
    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 55

    # =====================================================================
    # TRADES -- every trade, with a conditional-formatting P&L heatmap
    # (data bars) instead of a chart -- robust, no rendering-quirk risk,
    # and genuinely easier to scan a long list with than a line chart
    # would be anyway.
    # =====================================================================
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

    if trades:
        last_row = len(trades) + 1
        pnl_range = f"I2:I{last_row}"
        ws2.conditional_formatting.add(pnl_range, DataBarRule(start_type="min", end_type="max", color="63BE7B", showValue=True, minLength=None, maxLength=None))
        ws2.conditional_formatting.add(pnl_range, CellIsRule(operator="lessThan", formula=["0"], fill=PatternFill("solid", fgColor=RED)))
        ws2.conditional_formatting.add(pnl_range, CellIsRule(operator="greaterThan", formula=["0"], fill=PatternFill("solid", fgColor=GREEN)))

    # =====================================================================
    # MONTHLY PERFORMANCE
    # =====================================================================
    ws3 = wb.create_sheet("Monthly Performance")
    ws3.append(["Month", "P&L (Rs)", "Trades"])
    for cell in ws3[1]:
        cell.font = header_font
        cell.fill = header_fill
    for month, v in metrics["monthly_pnl"].items():
        r = ws3.max_row + 1
        ws3.append([month, v["pnl"], v["trades"]])
        fill, font = pos_neg_fill(v["pnl"])
        ws3.cell(row=r, column=2).fill = fill
        ws3.cell(row=r, column=2).font = font
    n_months = len(metrics["monthly_pnl"])
    if n_months >= 1:
        m_chart = style_chart(BarChart(), "Monthly P&L", "Rs", x_title="Month")
        m_data = Reference(ws3, min_col=2, min_row=1, max_row=1 + n_months)
        m_cats = Reference(ws3, min_col=1, min_row=2, max_row=1 + n_months)
        m_chart.add_data(m_data, titles_from_data=True)
        m_chart.set_categories(m_cats)
        ws3.add_chart(m_chart, "E2")
    for col in ws3.columns:
        ws3.column_dimensions[col[0].column_letter].width = 14

    # =====================================================================
    # WORST DRAWDOWNS
    # =====================================================================
    ws4 = wb.create_sheet("Worst Drawdowns")
    ws4["A1"] = "The 5 deepest peak-to-trough declines in account value, worst first. 'Recovered' shows when equity climbed back to the pre-drawdown peak -- '--' means it hasn't yet."
    ws4["A1"].font = Font(italic=True, size=9, color="6B7280")
    ws4.merge_cells("A1:G1")
    ws4.append(["#", "Depth (Rs)", "Depth %", "Peak Date", "Trough Date", "Recovered", "Status"])
    for cell in ws4[2]:
        cell.font = header_font
        cell.fill = header_fill
    sorted_dd = sorted(metrics["drawdown_periods"], key=lambda d: d["depth"])[:5]
    for i, d in enumerate(sorted_dd, 1):
        r = ws4.max_row + 1
        ws4.append([
            i, d["depth"], d["depth_pct"],
            d["peak_dt"].strftime("%Y-%m-%d %H:%M"), d["trough_dt"].strftime("%Y-%m-%d %H:%M"),
            d["recovered_dt"].strftime("%Y-%m-%d %H:%M") if d["recovered_dt"] else "--",
            d["status"],
        ])
        ws4.cell(row=r, column=2).fill = PatternFill("solid", fgColor=RED)
        ws4.cell(row=r, column=2).font = Font(color=RED_FONT)
        ws4.cell(row=r, column=3).fill = PatternFill("solid", fgColor=RED)
        ws4.cell(row=r, column=3).font = Font(color=RED_FONT)
        if d["status"] == "Ongoing":
            ws4.cell(row=r, column=7).fill = PatternFill("solid", fgColor=AMBER)
            ws4.cell(row=r, column=7).font = Font(bold=True, color=AMBER_FONT)
    # ws4.columns would include the merged A1:G1 explanatory cell --
    # MergedCell objects there lack .column_letter and break the usual
    # "iterate ws.columns" width-sizing pattern used on the other
    # sheets. Explicit column-index loop instead, skipping row 1.
    for col_idx in range(1, 8):
        col_letter = get_column_letter(col_idx)
        max_len = max((len(str(ws4.cell(row=r, column=col_idx).value)) for r in range(2, ws4.max_row + 1) if ws4.cell(row=r, column=col_idx).value is not None), default=10)
        ws4.column_dimensions[col_letter].width = max(max_len + 2, 10)

    # =====================================================================
    # DAILY RETURNS -- with the (now-fixed) histogram
    # =====================================================================
    ws5 = wb.create_sheet("Daily Returns")
    ws5.append(["Date", "P&L (Rs)", "P&L % of capital"])
    for cell in ws5[1]:
        cell.font = header_font
        cell.fill = header_fill
    for date_str, pnl in metrics["daily_pnl"].items():
        r = ws5.max_row + 1
        ws5.append([date_str, round(pnl, 2), round(pnl / metrics["capital_base"] * 100, 3)])
        fill, font = pos_neg_fill(pnl)
        ws5.cell(row=r, column=2).fill = fill
        ws5.cell(row=r, column=2).font = font
    for col in ws5.columns:
        ws5.column_dimensions[col[0].column_letter].width = 16

    bin_labels, bin_counts = _bin_daily_returns(metrics["daily_pnl"], metrics["capital_base"])
    if bin_counts:
        hist_start = len(metrics["daily_pnl"]) + 3
        ws5.cell(row=hist_start, column=1, value="Bin (daily return %)").font = header_font
        ws5.cell(row=hist_start, column=1).fill = header_fill
        ws5.cell(row=hist_start, column=2, value="Days").font = header_font
        ws5.cell(row=hist_start, column=2).fill = header_fill
        for i, (label, count) in enumerate(zip(bin_labels, bin_counts)):
            ws5.cell(row=hist_start + 1 + i, column=1, value=label)
            ws5.cell(row=hist_start + 1 + i, column=2, value=count)
        h_chart = style_chart(BarChart(), "Daily Return Distribution", "Days", x_title="Daily return %")
        h_data = Reference(ws5, min_col=2, min_row=hist_start, max_row=hist_start + len(bin_counts))
        h_cats = Reference(ws5, min_col=1, min_row=hist_start + 1, max_row=hist_start + len(bin_counts))
        h_chart.add_data(h_data, titles_from_data=True)
        h_chart.set_categories(h_cats)
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
            # Aug 23 2026: switched to PDF by default -- Excel's native
            # chart engine has a real ceiling on how polished it can
            # look (confirmed against his own reference screenshots),
            # PDF (matplotlib for charts + reportlab for page layout)
            # gets much closer. write_report() (the Excel version) is
            # still here, just not called automatically -- swap the
            # line below if Excel is ever wanted again.
            try:
                path = write_pdf_report(trades, metrics)
                print(f"\nFull PDF report written to: {path}")
            except ImportError as e:
                print(f"\nPDF generation needs matplotlib and reportlab -- pip install matplotlib reportlab")
                print(f"({e})")