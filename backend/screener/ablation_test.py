"""
screener/ablation_test.py

Offline ablation testing for signal-SELECTION logic (not scoring math
itself) -- compares the CURRENT production selection rule against
alternative candidate rules, using ONLY real historical signal_logs/*.xlsx
data. Never simulates an outcome for a signal that was never actually
logged with a real entry/SL/target and a real resolution.

=============================================================================
FEASIBILITY -- checked against the real logging pipeline BEFORE writing
any comparison logic (see views.py's actual code, quoted below):

    quality_signals = [
        s for s in signals
        if int(s['confidence'].replace('%', '')) >= 85
        and s.get('oi_confirmation') == 'CONFIRMED'
    ][:15]
    ...
    newly_logged = sync_active_signals(quality_signals)

Only this narrow, already-filtered pool ever reaches
excel_logger.py -- a candidate that was REJECTED (score < 50, OI
conflict, no confirmed option chain, no confirmed lot size) never gets
a row: no entry, no SL/target, no logged outcome. There is nothing to
replay for it.

TESTABLE from existing logs (this file implements these):
  - baseline            : current production logic, exactly as logged
  - floor_60/70/80       : RAISING the qualifying bar above whatever was
                            already applied that day. Uses each trade's
                            RECONSTRUCTED pre-OI base score -- same
                            reconstruction method this project's own
                            check_oi_confirmation_score_bias.py already
                            used: base_score_pre_oi = Confidence - (20 if
                            CONFIRMED else 0) - (5 if the PCR secondary
                            bonus condition was met else 0). One honest
                            imprecision: total_score is clamped to 100
                            before being logged as Confidence, so any
                            row with Confidence == 100 has a genuinely
                            ambiguous reconstruction (the true pre-clamp
                            sum could have been 100-105) -- these rows
                            are flagged, not silently guessed at.
                            CANNOT test LOWERING the bar below what was
                            already applied -- candidates that never
                            qualified were never logged, so a looser
                            floor can't recover them from history.
  - top3_per_day/top5_per_day : re-ranks WITHIN each day's already-logged
                            qualifying pool (already capped at 15/day)
                            by Confidence, keeps only the top N. This is
                            NOT the full proposed ~20-40-candidate
                            ranking pipeline -- non-qualifying candidates
                            were never logged, so this is a second-order
                            re-rank of an already-narrow pool, not the
                            complete redesign. Stated plainly as that
                            scope, not oversold as the full pipeline.

NOT TESTABLE from existing logs (would need data that was never
captured -- flagged, not faked):
  - OI contradiction = downgrade : contradicting-OI candidates were
    REJECTED and never logged -- no entry/SL/target/outcome exists to
    replay. Needs forward shadow-logging before this can ever be
    evaluated.
  - OI contradiction = reject : this IS the current baseline behavior
    already (the existing `continue` on conflict) -- not a distinct
    variant to test, it's identical to "baseline".
  - Market-regime gating : no historical regime classification
    (Bull/Bear/Range/etc.) was ever computed or stored for past
    trading days. Per the explicit instruction this was only worth
    testing "if the historical data supports it" -- it doesn't.
=============================================================================

Run directly: python -m screener.ablation_test
Writes a text report to signal_logs/ablation_reports/ablation_<date>.txt
and prints the same content to the console.
"""
import os
import statistics
from datetime import datetime

try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None

from .backtest_signal_pnl import (
    LOG_DIR, list_signal_log_dates, parse_outcome, _resolve_exit_datetime,
    compute_r_multiple, compute_metrics, filter_rule_resolved, categorize_exit_reason,
)

MIN_TRUSTWORTHY_SAMPLE = 20  # same floor used everywhere else in this project


# ---------------------------------------------------------------------------
# 1. Load real historical trades, WITH the extra fields (Confidence, PCR)
#    needed for base-score reconstruction. Deliberately a separate loader
#    from backtest_signal_pnl.load_all_trades() -- reuses every helper
#    function that one already uses (parse_outcome, _resolve_exit_datetime,
#    compute_r_multiple), but doesn't modify that function at all, since
#    it's used by the live production PDF pipeline.
# ---------------------------------------------------------------------------

def load_trades_with_scoring():
    """Same row-reading/exclusion logic as load_all_trades(), extended to
    also capture confidence (int) and pcr (float|None) per trade -- needed
    to reconstruct base_score_pre_oi. Returns (trades, excluded_count)."""
    if load_workbook is None:
        return [], 0

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
            continue

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

            qty = get_lot_size(row.get("Symbol"))
            if qty is None:
                excluded += 1
                continue

            pnl = round(qty * (exit_price - entry), 2)
            pnl_pct = round((exit_price - entry) / entry * 100, 2)

            confidence_raw = row.get("Confidence")
            try:
                confidence = int(str(confidence_raw).replace('%', '').strip())
            except (ValueError, TypeError):
                confidence = None  # can't reconstruct base score for this row -- flagged downstream, never guessed

            trades.append({
                "symbol": row.get("Symbol"), "action": row.get("Action"), "grade": row.get("Grade"),
                "sector": row.get("Sector") or "Unknown",
                "oi_confirmation": row.get("OI Confirmation") or "Unknown",
                "confidence": confidence,
                "pcr": row.get("PCR"),
                "pattern": row.get("Pattern") or "None",
                "entry_dt": entry_dt, "exit_dt": exit_dt, "date_str": date_str,
                "entry": entry, "sl": sl, "exit_price": exit_price, "qty": qty,
                "target1": t1, "target2": t2, "target3": t3,
                "pnl": pnl, "pnl_pct": pnl_pct, "exit_reason": reason,
                "r_multiple": compute_r_multiple(entry, sl, exit_price),
            })

    trades.sort(key=lambda t: t["exit_dt"])
    return trades, excluded


# ---------------------------------------------------------------------------
# 2. Reconstruct each trade's pre-OI base score -- same method this
#    project's own check_oi_confirmation_score_bias.py already used.
# ---------------------------------------------------------------------------

def reconstruct_base_score_pre_oi(trade):
    """Returns (base_score, is_ambiguous). is_ambiguous=True means
    Confidence was logged as 100 -- the true pre-clamp total could have
    been 100-105, so the reconstructed base score is a lower-bound
    estimate, not an exact figure, for that one row only."""
    if trade["confidence"] is None:
        return None, False

    oi_bonus = 20 if trade["oi_confirmation"] == "CONFIRMED" else 0

    pcr_bonus = 0
    pcr_val = trade.get("pcr")
    if pcr_val is not None:
        if trade["action"] == "BUY" and pcr_val > 1.0:
            pcr_bonus = 5
        elif trade["action"] == "SELL" and pcr_val < 0.7:
            pcr_bonus = 5

    base = trade["confidence"] - oi_bonus - pcr_bonus
    is_ambiguous = (trade["confidence"] == 100)
    return base, is_ambiguous


# ---------------------------------------------------------------------------
# 3. Variant definitions -- each takes the full trade list, returns a
#    (subset, note) tuple. "note" carries any caveat that belongs on THIS
#    variant's report section specifically.
# ---------------------------------------------------------------------------

def variant_baseline(trades):
    return list(trades), None


def variant_score_floor(trades, floor):
    kept = []
    ambiguous_count = 0
    unreconstructable_count = 0
    for t in trades:
        base, ambiguous = reconstruct_base_score_pre_oi(t)
        if base is None:
            unreconstructable_count += 1
            continue
        if ambiguous:
            ambiguous_count += 1
        if base >= floor:
            kept.append(t)
    note = (f"{unreconstructable_count} trade(s) had no usable Confidence value and were dropped from this "
            f"variant entirely (not counted either direction). {ambiguous_count} trade(s) had Confidence "
            f"logged at the 100 clamp ceiling -- their reconstructed base score is a lower-bound estimate, "
            f"included here since it can only ever be an UNDER-estimate, never inflate the count kept.")
    return kept, note


def variant_top_n_per_day(trades, n):
    by_day = {}
    for t in trades:
        by_day.setdefault(t["date_str"], []).append(t)
    kept = []
    unranked_count = 0
    for day, day_trades in by_day.items():
        rankable = [t for t in day_trades if t["confidence"] is not None]
        unrankable = [t for t in day_trades if t["confidence"] is None]
        unranked_count += len(unrankable)
        rankable.sort(key=lambda t: t["confidence"], reverse=True)
        kept.extend(rankable[:n])
    note = (f"Re-ranks WITHIN each day's already-logged qualifying pool (already capped at 15/day by the "
            f"live filter) -- NOT the full proposed ~20-40-candidate pipeline, since non-qualifying "
            f"candidates were never logged at all. {unranked_count} trade(s) had no usable Confidence and "
            f"were excluded from ranking (not kept, not counted as rejected).")
    return kept, note


VARIANTS = {
    "baseline": ("Current baseline (as actually logged)", lambda trades: variant_baseline(trades)),
    "floor_60": ("Base-score floor >= 60 (Doc's 'Developing' cutoff)", lambda trades: variant_score_floor(trades, 60)),
    "floor_70": ("Base-score floor >= 70 (Doc's 'Qualified' cutoff)", lambda trades: variant_score_floor(trades, 70)),
    "floor_80": ("Base-score floor >= 80 (Doc's 'Strong candidate' cutoff)", lambda trades: variant_score_floor(trades, 80)),
    "top3_per_day": ("Ranking-based Top-3/day", lambda trades: variant_top_n_per_day(trades, 3)),
    "top5_per_day": ("Ranking-based Top-5/day", lambda trades: variant_top_n_per_day(trades, 5)),
}

NOT_TESTABLE = {
    "oi_downgrade": "OI contradiction = downgrade -- contradicting-OI candidates were REJECTED and never logged; no entry/SL/target/outcome exists to replay. Needs forward shadow-logging first.",
    "oi_reject": "OI contradiction = reject -- this IS the current baseline behavior already (the existing `continue` on conflict). Not a distinct variant; identical to 'baseline'.",
    "regime_gating": "Market-regime gating -- no historical regime classification (Bull/Bear/Range/etc.) was ever computed or stored for past trading days. Not testable from what exists.",
}


# ---------------------------------------------------------------------------
# 4. Metrics per variant -- everything requested, computed once and
#    reused across the blended/rule-resolved/EOD/long-short/OI-group cuts.
# ---------------------------------------------------------------------------

def _median_r(trades):
    r_values = [t["r_multiple"] for t in trades if t.get("r_multiple") is not None]
    return round(statistics.median(r_values), 3) if r_values else None


def _avg_r(trades):
    r_values = [t["r_multiple"] for t in trades if t.get("r_multiple") is not None]
    return round(sum(r_values) / len(r_values), 3) if r_values else None


def _expectancy_r(trades):
    """Expectancy expressed in R, not rupees -- (avg R of wins * win rate)
    minus (avg |R| of losses * loss rate), same concept the review
    documents ask for specifically as a currency-independent figure."""
    r_values = [t["r_multiple"] for t in trades if t.get("r_multiple") is not None]
    if not r_values:
        return None
    return round(sum(r_values) / len(r_values), 3)  # mathematically identical to avg R -- kept as a separate name since the two are conceptually distinct asks


def summarize_group(trades, label):
    """One block of every requested stat for a given trade list -- reused
    for the full set, rule-resolved-only, EOD-only, long-only, short-only,
    and each OI-confirmation group."""
    if not trades:
        return {"label": label, "count": 0}
    capital_base = max((t["entry"] * t["qty"] for t in trades), default=DEFAULT_CAPITAL_PER_TRADE if False else 50000)
    m = compute_metrics(trades, capital_base)
    gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss = sum(t["pnl"] for t in trades if t["pnl"] < 0)
    return {
        "label": label,
        "count": len(trades),
        "small_sample": len(trades) < MIN_TRUSTWORTHY_SAMPLE,
        "win_rate_pct": m["win_rate_pct"] if m else None,
        "profit_factor": m["profit_factor"] if m else None,
        "expectancy_rs": m["expectancy"] if m else None,
        "expectancy_r": _expectancy_r(trades),
        "avg_r": _avg_r(trades),
        "median_r": _median_r(trades),
        "max_drawdown_pct": (m["max_drawdown"]["depth_pct"] if m and m.get("max_drawdown") else None),
        "gross_profit_rs": round(gross_profit, 2),
        "gross_loss_rs": round(gross_loss, 2),
        "net_pnl_rs": m["net_pnl"] if m else None,
    }


def full_report_for_variant(trades):
    """Every cut the request asked for, for one variant's trade list."""
    rule_resolved = filter_rule_resolved(trades)
    eod_only = [t for t in trades if categorize_exit_reason(t["exit_reason"]) == "Closed (EOD/manual)"]
    longs = [t for t in trades if t["action"] == "BUY"]
    shorts = [t for t in trades if t["action"] == "SELL"]
    oi_groups = {}
    for state in ("CONFIRMED", "NEUTRAL", "NO_DATA", "Unknown"):
        group = [t for t in trades if t["oi_confirmation"] == state]
        if group:
            oi_groups[state] = summarize_group(group, f"OI {state}")

    return {
        "all": summarize_group(trades, "All trades (blended)"),
        "rule_resolved": summarize_group(rule_resolved, "Rule-resolved only"),
        "eod_only": summarize_group(eod_only, "EOD/manual only"),
        "long": summarize_group(longs, "Long (BUY)"),
        "short": summarize_group(shorts, "Short (SELL)"),
        "oi_groups": oi_groups,
    }


# ---------------------------------------------------------------------------
# 5. Verdict -- explicitly NOT "pick the highest P&L". Looks for
#    consistency across independent cuts and adequate sample size before
#    calling anything supported.
# ---------------------------------------------------------------------------

def build_verdict(variant_reports):
    """
    A variant is called SUPPORTED only if:
      - its "all" sample is >= MIN_TRUSTWORTHY_SAMPLE, AND
      - its rule-resolved-only Profit Factor is ALSO >= baseline's
        (not just the blended figure, which EOD trades can distort), AND
      - it doesn't win purely by shrinking the sample so much that the
        remaining trades are noise (checked via the small_sample flag).
    Anything that only wins on the blended P&L, or wins on a sample too
    small to trust, is called out as NOT supported, explicitly.
    """
    baseline = variant_reports.get("baseline")
    if not baseline or baseline["all"]["count"] == 0:
        return ["No baseline data to compare against -- nothing to verdict."]

    lines = []
    base_pf_all = baseline["all"]["profit_factor"]
    base_pf_rr = baseline["rule_resolved"]["profit_factor"]
    lines.append(f"Baseline: {baseline['all']['count']} trades, blended PF {base_pf_all}, rule-resolved-only PF {base_pf_rr}.")
    lines.append("")

    for key, report in variant_reports.items():
        if key == "baseline":
            continue
        all_stats, rr_stats = report["all"], report["rule_resolved"]
        if all_stats["count"] == 0:
            lines.append(f"{key}: no trades survive this filter -- can't evaluate.")
            continue

        reasons_against = []
        if all_stats["small_sample"]:
            reasons_against.append(f"only {all_stats['count']} trades (below the {MIN_TRUSTWORTHY_SAMPLE}-trade floor)")
        if rr_stats["count"] > 0 and base_pf_rr is not None and rr_stats["profit_factor"] is not None:
            if rr_stats["profit_factor"] < base_pf_rr:
                reasons_against.append(f"rule-resolved-only PF ({rr_stats['profit_factor']}) is actually WORSE than baseline's ({base_pf_rr}), even though the blended number may look better")
        elif rr_stats["count"] == 0:
            reasons_against.append("zero rule-resolved trades survive -- can't confirm the edge is real vs. just EOD-mark noise")

        if reasons_against:
            lines.append(f"{key}: NOT supported -- {'; '.join(reasons_against)}.")
        else:
            lines.append(f"{key}: SUPPORTED -- {all_stats['count']} trades, blended PF {all_stats['profit_factor']}, "
                         f"rule-resolved-only PF {rr_stats['profit_factor']} (>= baseline's {base_pf_rr}), "
                         f"consistent across both cuts.")
    return lines


DEFAULT_CAPITAL_PER_TRADE = 50000


# ---------------------------------------------------------------------------
# 6. Report writer
# ---------------------------------------------------------------------------

def _fmt_group(g):
    if g["count"] == 0:
        return "    (no trades)"
    flag = "  ⚠ SMALL SAMPLE" if g.get("small_sample") else ""
    return (f"    {g['label']}: n={g['count']}{flag}\n"
            f"      Win rate {g['win_rate_pct']}% | PF {g['profit_factor']} | "
            f"Expectancy Rs {g['expectancy_rs']} ({g['expectancy_r']}R) | Avg R {g['avg_r']} | Median R {g['median_r']}\n"
            f"      Max DD {g['max_drawdown_pct']}% | Gross profit Rs {g['gross_profit_rs']} | "
            f"Gross loss Rs {g['gross_loss_rs']} | Net P&L Rs {g['net_pnl_rs']}")


def run():
    trades, excluded = load_trades_with_scoring()
    print(f"Loaded {len(trades)} resolved trades ({excluded} excluded -- still open or no priceable outcome).\n")
    if not trades:
        print("No trades to analyze.")
        return

    out_dir = os.path.join(LOG_DIR, "ablation_reports")
    os.makedirs(out_dir, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    out_path = os.path.join(out_dir, f"ablation_{today}.txt")

    lines = []
    lines.append("=" * 78)
    lines.append(f"OFFLINE ABLATION TEST -- {today}")
    lines.append(f"{len(trades)} resolved trades loaded, {excluded} excluded (unpriceable/still open)")
    lines.append("=" * 78)
    lines.append("")
    lines.append("NOT TESTABLE from existing logs (data was never captured -- not faked):")
    for key, reason in NOT_TESTABLE.items():
        lines.append(f"  - {key}: {reason}")
    lines.append("")

    variant_reports = {}
    for key, (desc, fn) in VARIANTS.items():
        subset, note = fn(trades)
        lines.append("-" * 78)
        lines.append(f"VARIANT: {key} -- {desc}")
        if note:
            lines.append(f"  Note: {note}")
        report = full_report_for_variant(subset)
        variant_reports[key] = report
        lines.append("  Overall:")
        lines.append(_fmt_group(report["all"]))
        lines.append("  Rule-resolved only:")
        lines.append(_fmt_group(report["rule_resolved"]))
        lines.append("  EOD/manual only:")
        lines.append(_fmt_group(report["eod_only"]))
        lines.append("  Long (BUY):")
        lines.append(_fmt_group(report["long"]))
        lines.append("  Short (SELL):")
        lines.append(_fmt_group(report["short"]))
        lines.append("  By OI confirmation state:")
        for state, g in report["oi_groups"].items():
            lines.append(_fmt_group(g))
        lines.append("")

    lines.append("=" * 78)
    lines.append("VERDICT -- which change is actually supported by the data")
    lines.append("(NOT simply the variant with the highest P&L -- see build_verdict()'s")
    lines.append(" own docstring for the exact criteria applied)")
    lines.append("=" * 78)
    lines.extend(build_verdict(variant_reports))

    report_text = "\n".join(lines)
    print(report_text)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"\nSaved to: {out_path}")


if __name__ == "__main__":
    run()
