"""
index_bias_forensics.py

Phase 1 of the Index Bias audit's recommended plan (Section 14) --
reconstructs real historical Bias states from the actual logged Index
Tracker snapshots, attributes flips to the specific factors that
changed, measures each factor's real forward accuracy, and tests the
correlated-evidence claim empirically. Read-only analysis -- does NOT
touch _derive_bias() or any live Bias computation, matching the same
"research before rewrite" boundary this project already holds on the
F&O side (see ablation_test.py).

RECONSTRUCTION FIDELITY, stated plainly:
- PCR, OI Buildup, ATM balance, Max Pain: FULL fidelity -- exact
  logged columns, fed directly into the REAL _pcr_vote/
  _oi_buildup_vote/_atm_balance_vote/_max_pain_vote functions, not
  reimplemented separately.
- Momentum, VIX trend: APPROXIMATED. The live code computes both from
  a confirmed 15-minute rolling window (momentum_pct=
  horizon_changes.get(15); vix_change_pct via
  _VIX_TREND_LOOKBACK_MINUTES=15), but that in-memory rolling history
  resets on every restart and was never persisted, so this
  reconstructs the same 15-minute window from LOGGED snapshots
  instead, using nearest-available-match with a stated tolerance
  (_find_lookback_row). Close to, not guaranteed pixel-identical to,
  what the live code saw at that exact instant.

VALIDATION FIRST: before trusting anything built on this,
reconstructed Bias is compared against the REAL logged Bias column
across every available row. That agreement rate is reported first,
prominently -- if it isn't high, everything downstream should be
read with real skepticism, not quietly trusted.
"""
from datetime import datetime, timedelta
import statistics

from .index_tracker import (
    list_available_dates, get_snapshots_for_date,
    _pcr_vote, _oi_buildup_vote, _atm_balance_vote, _max_pain_vote,
    _vix_trend_vote, _momentum_vote,
    BIAS_VOTE_MARGIN_FOR_DIRECTION, BIAS_VOTE_MARGIN_FOR_STRONG,
)

LOOKBACK_MINUTES = 15  # confirmed exact match to the live code's own momentum/VIX-trend window
LOOKBACK_TOLERANCE_MINUTES = 3  # how far off "15 minutes ago" a logged row can be and still count


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_all_snapshots(index_name, start_date=None, end_date=None):
    """
    Pulls every real logged snapshot for index_name across all
    available dates (or a bounded range), parsed into clean typed
    dicts, sorted chronologically (oldest first) -- get_snapshots_for_
    date() itself returns newest-first per day, so this reverses each
    day's rows before concatenating.

    Adds one field not in the raw log: '_dt', a real datetime combining
    that row's date and Time column, needed for every forward-looking/
    lookback calculation below. A row whose Time can't be parsed is
    dropped entirely (not kept with a guessed timestamp).
    """
    dates = list_available_dates(index_name)
    if start_date:
        dates = [d for d in dates if d >= start_date]
    if end_date:
        dates = [d for d in dates if d <= end_date]

    all_rows = []
    for date_str in sorted(dates):  # oldest date first
        day_rows = get_snapshots_for_date(index_name, date_str)
        day_rows = list(reversed(day_rows))  # this function returns newest-first; flip to chronological
        for row in day_rows:
            time_str = row.get("Time")
            if not time_str:
                continue
            try:
                dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                continue
            row = dict(row)
            row["_dt"] = dt
            all_rows.append(row)

    return all_rows


def _find_lookback_row(rows, idx, minutes=LOOKBACK_MINUTES, tolerance=LOOKBACK_TOLERANCE_MINUTES):
    """Searches backward from rows[idx] for the row closest to `minutes`
    before it, accepting anything within +-tolerance minutes of that
    target. Returns None (never a guess) if nothing in range -- e.g.
    near the start of a day's log, or across a gap where logging
    wasn't running."""
    target = rows[idx]["_dt"] - timedelta(minutes=minutes)
    best, best_diff = None, None
    for j in range(idx - 1, -1, -1):
        diff = abs((rows[j]["_dt"] - target).total_seconds() / 60)
        if diff > minutes + tolerance + 5:  # far enough past any plausible match -- stop scanning further back
            break
        if diff <= tolerance and (best_diff is None or diff < best_diff):
            best, best_diff = rows[j], diff
    return best


def reconstruct_votes(rows, idx):
    """
    Returns {factor_name: 'bullish'|'bearish'|None} for all 6 factors
    at rows[idx], using the REAL vote functions on real logged values
    wherever the column is directly available, and the 15-min-lookback
    approximation for momentum/VIX (see module docstring). Also
    returns the reconstructed overall Bias string, using the EXACT
    same margin logic _derive_bias() itself uses.
    """
    row = rows[idx]
    pcr = _to_float(row.get("PCR"))
    spot = _to_float(row.get("Spot")) or _to_float(row.get("Fut"))
    max_pain = _to_float(row.get("Max Pain"))
    pe_oi = _to_float(row.get("Put OI (ATM)"))
    ce_oi = _to_float(row.get("Call OI (ATM)"))
    vix = _to_float(row.get("VIX"))

    lookback = _find_lookback_row(rows, idx)
    momentum_pct, vix_change_pct = None, None
    if lookback is not None:
        lb_spot = _to_float(lookback.get("Spot")) or _to_float(lookback.get("Fut"))
        if spot is not None and lb_spot:
            momentum_pct = (spot - lb_spot) / lb_spot * 100
        lb_vix = _to_float(lookback.get("VIX"))
        if vix is not None and lb_vix:
            vix_change_pct = (vix - lb_vix) / lb_vix * 100

    votes = {
        "pcr": _pcr_vote(pcr),
        "oi_buildup": _oi_buildup_vote(row.get("OI Buildup")),
        "atm_balance": _atm_balance_vote(pe_oi, ce_oi),
        "max_pain": _max_pain_vote(spot, max_pain),
        "vix_trend": _vix_trend_vote(vix_change_pct),
        "momentum": _momentum_vote(momentum_pct),
    }

    bullish = sum(1 for v in votes.values() if v == "bullish")
    bearish = sum(1 for v in votes.values() if v == "bearish")
    margin = bullish - bearish
    if abs(margin) < BIAS_VOTE_MARGIN_FOR_DIRECTION:
        reconstructed_bias = "Neutral"
    else:
        direction = "Bullish" if margin > 0 else "Bearish"
        reconstructed_bias = f"{direction} (Strong)" if abs(margin) >= BIAS_VOTE_MARGIN_FOR_STRONG else direction

    return votes, reconstructed_bias, (momentum_pct, vix_change_pct)


def validate_reconstruction(rows):
    """
    THE step to run and read first. Compares reconstructed Bias
    against the REAL logged Bias column across every row with enough
    history to reconstruct from (needs a lookback row -- the first
    ~15 minutes of each day can't be checked, honestly excluded
    rather than guessed). Reports exact-match rate and
    same-direction-different-strength rate separately, since a
    Bullish-vs-Bullish(Strong) mismatch is a much smaller problem than
    a Bullish-vs-Bearish one.
    """
    exact_match = 0
    same_direction = 0
    mismatch = 0
    checked = 0
    mismatches_detail = []

    for idx in range(len(rows)):
        real_bias = rows[idx].get("Bias")
        if not real_bias:
            continue
        _, reconstructed, _ = reconstruct_votes(rows, idx)
        if reconstructed is None:
            continue
        checked += 1
        if reconstructed == real_bias:
            exact_match += 1
        elif reconstructed.split(" ")[0] == real_bias.split(" ")[0]:
            same_direction += 1
        else:
            mismatch += 1
            if len(mismatches_detail) < 20:  # keep a sample, not every single one
                mismatches_detail.append({
                    "time": rows[idx]["_dt"].isoformat(), "real": real_bias, "reconstructed": reconstructed,
                })

    return {
        "checked": checked,
        "exact_match": exact_match, "exact_match_pct": round(exact_match / checked * 100, 1) if checked else None,
        "same_direction_diff_strength": same_direction,
        "genuine_mismatch": mismatch, "genuine_mismatch_pct": round(mismatch / checked * 100, 1) if checked else None,
        "sample_mismatches": mismatches_detail,
    }


def find_flips(rows):
    """
    Real flips, using the REAL logged Bias direction (not the
    reconstruction -- ground truth for WHEN a flip happened).
    Direction only (Bullish/Bullish(Strong) both count as "bullish"
    for flip purposes -- a strength change alone isn't a flip).
    Attributes each flip to which of the 6 reconstructed factors
    actually changed vote between the row just before and the row at
    the flip -- reconstruction is only used for attribution, never
    for detecting whether/when the flip itself happened.
    """
    def direction(bias_str):
        if not bias_str or bias_str == "Neutral":
            return "neutral"
        return "bullish" if bias_str.startswith("Bullish") else "bearish"

    flips = []
    last_dir = None
    last_votes = None
    for idx in range(len(rows)):
        real_bias = rows[idx].get("Bias")
        if not real_bias:
            continue
        d = direction(real_bias)
        votes, _, _ = reconstruct_votes(rows, idx)
        if last_dir is not None and d != last_dir and d != "neutral" and last_dir != "neutral":
            changed_factors = [f for f in votes if last_votes and votes[f] != last_votes.get(f)]
            flips.append({
                "time": rows[idx]["_dt"].isoformat(),
                "from": last_dir, "to": d,
                "changed_factors": changed_factors,
            })
        last_dir = d
        last_votes = votes

    return flips


def measure_flip_stats(rows):
    """Flips/day, average state duration (minutes), and a false-flip
    rate -- a flip that reverses back again within 15 minutes, which
    looks a lot more like noise than a genuine regime change."""
    flips = find_flips(rows)
    if not flips:
        return {"flips": 0, "flips_per_day": None, "avg_state_duration_minutes": None, "false_flip_rate_pct": None}

    days = len(set(r["_dt"].date() for r in rows))
    flip_times = [datetime.fromisoformat(f["time"]) for f in flips]
    durations = [(flip_times[i + 1] - flip_times[i]).total_seconds() / 60 for i in range(len(flip_times) - 1)]

    false_flips = sum(1 for d in durations if d <= 15)

    return {
        "flips": len(flips),
        "flips_per_day": round(len(flips) / days, 2) if days else None,
        "avg_state_duration_minutes": round(statistics.mean(durations), 1) if durations else None,
        "median_state_duration_minutes": round(statistics.median(durations), 1) if durations else None,
        "false_flip_rate_pct": round(false_flips / len(durations) * 100, 1) if durations else None,
        "false_flip_definition": "reversed again within 15 minutes",
    }


def measure_forward_accuracy(rows, horizons=(5, 15, 30, 60)):
    """
    Per-factor, per-horizon forward accuracy -- does THIS factor's own
    vote (in isolation, regardless of what the other 5 said) predict
    the direction price actually moved over each horizon? Only ever
    looks FORWARD from a row's own timestamp, never backward -- no
    lookahead bias. A row where a horizon's forward data doesn't exist
    yet (near the end of a day's log) is excluded from that horizon,
    not guessed.
    """
    results = {factor: {h: {"correct": 0, "wrong": 0} for h in horizons}
               for factor in ["pcr", "oi_buildup", "atm_balance", "max_pain", "vix_trend", "momentum"]}

    for idx in range(len(rows)):
        votes, _, _ = reconstruct_votes(rows, idx)
        spot_now = _to_float(rows[idx].get("Spot")) or _to_float(rows[idx].get("Fut"))
        if spot_now is None:
            continue

        for h in horizons:
            target_time = rows[idx]["_dt"] + timedelta(minutes=h)
            future_row = None
            for j in range(idx + 1, len(rows)):
                if rows[j]["_dt"] >= target_time:
                    future_row = rows[j]
                    break
            if future_row is None:
                continue
            spot_future = _to_float(future_row.get("Spot")) or _to_float(future_row.get("Fut"))
            if spot_future is None:
                continue
            actual_direction = "bullish" if spot_future > spot_now else "bearish" if spot_future < spot_now else None
            if actual_direction is None:
                continue

            for factor, vote in votes.items():
                if vote is None:
                    continue
                if vote == actual_direction:
                    results[factor][h]["correct"] += 1
                else:
                    results[factor][h]["wrong"] += 1

    summary = {}
    for factor, by_horizon in results.items():
        summary[factor] = {}
        for h, counts in by_horizon.items():
            total = counts["correct"] + counts["wrong"]
            summary[factor][h] = {
                "sample_size": total,
                "accuracy_pct": round(counts["correct"] / total * 100, 1) if total else None,
                "small_sample": total < 20,
            }
    return summary


def measure_factor_correlation(rows):
    """
    Directly tests the audit's Section 3 claim: how often do PAIRS of
    factors agree vs disagree, among rows where BOTH actually voted
    (abstentions excluded from that pair's count, not treated as
    disagreement). High agreement between a pair is evidence they may
    be capturing the same underlying move rather than independent
    information -- the empirical version of what the audit argued
    conceptually.
    """
    factors = ["pcr", "oi_buildup", "atm_balance", "max_pain", "vix_trend", "momentum"]
    pair_stats = {}
    for i in range(len(factors)):
        for j in range(i + 1, len(factors)):
            pair_stats[(factors[i], factors[j])] = {"agree": 0, "disagree": 0}

    for idx in range(len(rows)):
        votes, _, _ = reconstruct_votes(rows, idx)
        for (fa, fb), counts in pair_stats.items():
            va, vb = votes[fa], votes[fb]
            if va is None or vb is None:
                continue
            if va == vb:
                counts["agree"] += 1
            else:
                counts["disagree"] += 1

    summary = {}
    for pair, counts in pair_stats.items():
        total = counts["agree"] + counts["disagree"]
        summary[pair] = {
            "sample_size": total,
            "agreement_pct": round(counts["agree"] / total * 100, 1) if total else None,
            "small_sample": total < 20,
        }
    return summary


def run_full_report(index_name, start_date=None, end_date=None):
    rows = load_all_snapshots(index_name, start_date, end_date)
    lines = []
    lines.append("=" * 78)
    lines.append(f"INDEX BIAS FORENSICS -- {index_name}")
    lines.append(f"{len(rows)} real logged snapshots loaded"
                  + (f", {start_date} to {end_date}" if start_date or end_date else ", all available dates"))
    lines.append("=" * 78)
    lines.append("")

    if len(rows) < 50:
        lines.append("Not enough logged data yet for a meaningful report (fewer than 50 real snapshots).")
        return "\n".join(lines)

    lines.append("-" * 78)
    lines.append("STEP 0 -- VALIDATION (read this first)")
    lines.append("-" * 78)
    val = validate_reconstruction(rows)
    lines.append(f"Checked: {val['checked']} rows with enough history to reconstruct")
    lines.append(f"Exact match to real logged Bias: {val['exact_match']} ({val['exact_match_pct']}%)")
    lines.append(f"Same direction, different strength label: {val['same_direction_diff_strength']}")
    lines.append(f"Genuine mismatch (different direction entirely): {val['genuine_mismatch']} ({val['genuine_mismatch_pct']}%)")
    if val["genuine_mismatch_pct"] and val["genuine_mismatch_pct"] > 10:
        lines.append("")
        lines.append("WARNING: mismatch rate above 10% -- treat everything below with real skepticism.")
        lines.append("Sample mismatches:")
        for m in val["sample_mismatches"][:5]:
            lines.append(f"  {m['time']}: real={m['real']!r} reconstructed={m['reconstructed']!r}")
    lines.append("")

    lines.append("-" * 78)
    lines.append("STEP 1 -- FLIP STATISTICS (real logged Bias, not reconstructed)")
    lines.append("-" * 78)
    flip_stats = measure_flip_stats(rows)
    for k, v in flip_stats.items():
        lines.append(f"  {k}: {v}")
    lines.append("")

    lines.append("-" * 78)
    lines.append("STEP 2 -- PER-FACTOR FORWARD ACCURACY")
    lines.append("-" * 78)
    accuracy = measure_forward_accuracy(rows)
    for factor, by_horizon in accuracy.items():
        row_str = f"  {factor:<15}"
        for h, stats in by_horizon.items():
            flag = "*" if stats["small_sample"] else " "
            row_str += f" {h}m: {stats['accuracy_pct']}%{flag}(n={stats['sample_size']})"
        lines.append(row_str)
    lines.append("  (* = below 20-sample floor, treat as a first look, not a verified figure)")
    lines.append("")

    lines.append("-" * 78)
    lines.append("STEP 3 -- FACTOR CORRELATION (Section 3's claim, tested empirically)")
    lines.append("-" * 78)
    corr = measure_factor_correlation(rows)
    for pair, stats in sorted(corr.items(), key=lambda x: -(x[1]["agreement_pct"] or 0)):
        flag = "*" if stats["small_sample"] else " "
        lines.append(f"  {pair[0]:<15} vs {pair[1]:<15}: {stats['agreement_pct']}%{flag} agreement (n={stats['sample_size']})")
    lines.append("  (* = below 20-sample floor)")
    lines.append("")

    return "\n".join(lines)
