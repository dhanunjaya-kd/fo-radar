"""
screener/backtest_index_bias.py

Answers the question "does our Bias reading actually predict what price
does next?" using REAL data -- every snapshot the Index Tracker has
already been logging to signal_logs/index_tracker_{NIFTY|BANKNIFTY}_
YYYY-MM-DD.xlsx since Round 14. No new data collection needed, this
reads what's already there.

METHOD: for every logged snapshot with a directional Bias (Bullish/
Bearish, Neutral is excluded since it makes no directional claim to
test), look ahead N minutes to the nearest later snapshot and check
whether spot actually moved the direction Bias implied. Aggregate into
a hit rate per Bias category per time horizon.

HONEST LIMITATION: this is only as good as how many days of logs have
accumulated. One day's worth of snapshots is a small, noisy sample --
treat any single-day result as a rough first look, not a verified edge.
The more days this runs, the more this number means something. This
script will tell you your actual current sample size so you're not
misled by a tiny one.

Run as a standalone script:
    cd backend
    venv\\Scripts\\activate
    python -m screener.backtest_index_bias
"""
import os
import glob
from datetime import datetime, timedelta

try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "signal_logs")

DIRECTIONAL_BIASES = ("Bullish", "Bullish (Strong)", "Bearish", "Bearish (Strong)")


def load_all_snapshots(index_name):
    """
    Load and concatenate every daily Index Tracker log for one index,
    sorted chronologically by real datetime (combining each file's date
    -- from the filename -- with each row's Time column).
    """
    pattern = os.path.join(LOG_DIR, f"index_tracker_{index_name}_*.xlsx")
    all_rows = []
    for path in sorted(glob.glob(pattern)):
        if "pre-update" in os.path.basename(path):
            continue  # archived schema-migration files, not part of the real series
        prefix = f"index_tracker_{index_name}_"
        date_str = os.path.basename(path)[len(prefix):-len(".xlsx")]
        try:
            wb = load_workbook(path)
            ws = wb["Snapshots"]
        except Exception as e:
            print(f"  (skipping {os.path.basename(path)}: {e})")
            continue
        headers = [c.value for c in ws[1]]
        if "Time" not in headers or "Spot" not in headers or "Bias" not in headers:
            continue  # older schema without what we need -- skip rather than guess
        for row in ws.iter_rows(min_row=2, values_only=True):
            d = dict(zip(headers, row))
            try:
                dt = datetime.strptime(f"{date_str} {d['Time']}", "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            d["_datetime"] = dt
            all_rows.append(d)
    all_rows.sort(key=lambda r: r["_datetime"])
    return all_rows


def backtest(index_name, horizon_minutes):
    """
    For one index and one look-ahead horizon: returns
    {bias_label: {'correct': n, 'total': n, 'hit_rate': pct}}

    IMPORTANT: only counts NON-OVERLAPPING samples. The first version of
    this counted every single snapshot as an independent test -- but if
    Bias sits at the same value for an extended stretch (e.g. NIFTY
    reading "Bearish" continuously for 2 hours while price just drifts
    down the whole time), that's really ONE continuous move, not dozens
    of separate confirmations. Counting it as dozens inflates the hit
    rate for exactly the reason a flat, suspicious 100% showed up for
    BANKNIFTY Bearish(Strong) across every horizon in testing -- 36
    heavily-overlapping windows from what was likely one sustained trend,
    not 36 independent bets. After using a snapshot as a test point, the
    next eligible one has to be at least `horizon_minutes` later.
    """
    rows = load_all_snapshots(index_name)
    results = {b: {"correct": 0, "total": 0} for b in DIRECTIONAL_BIASES}
    next_eligible_time = None

    for i, row in enumerate(rows):
        bias = row.get("Bias")
        if bias not in DIRECTIONAL_BIASES:
            continue
        if next_eligible_time is not None and row["_datetime"] < next_eligible_time:
            continue  # still inside the previous sample's window -- skip, don't double-count
        spot_now = row.get("Spot")
        if spot_now is None:
            continue

        target_time = row["_datetime"] + timedelta(minutes=horizon_minutes)
        future_row = next((r for r in rows[i + 1:] if r["_datetime"] >= target_time), None)
        if future_row is None:
            continue  # no snapshot far enough ahead yet (e.g. near end of day/data)
        spot_future = future_row.get("Spot")
        if spot_future is None:
            continue

        predicted_up = bias.startswith("Bullish")
        actual_up = spot_future > spot_now
        results[bias]["total"] += 1
        if predicted_up == actual_up:
            results[bias]["correct"] += 1
        next_eligible_time = target_time  # don't reuse anything inside this window again

    for b in results:
        t = results[b]["total"]
        results[b]["hit_rate"] = round(100 * results[b]["correct"] / t, 1) if t else None

    return results, len(rows)


def print_report(index_name, horizons=(15, 30, 60)):
    print(f"\n{'=' * 60}")
    print(f"  {index_name} — Bias backtest")
    print(f"{'=' * 60}")

    _, total_snapshots = backtest(index_name, horizons[0])
    print(f"Total logged snapshots found: {total_snapshots}")
    if total_snapshots < 200:
        print("(That's roughly under a day's worth at a 90s scan interval --")
        print(" treat any hit rate below as a rough first look, not a verified edge.")
        print(" Let this run for more days before trusting it.)")
    print()

    for horizon in horizons:
        results, _ = backtest(index_name, horizon)
        print(f"--- Look-ahead: {horizon} minutes ---")
        for bias, r in results.items():
            if r["total"] == 0:
                print(f"  {bias:18s}: no samples yet")
            else:
                print(f"  {bias:18s}: {r['hit_rate']:5.1f}% correct  ({r['correct']}/{r['total']} samples)")
        print()


if __name__ == "__main__":
    if load_workbook is None:
        print("openpyxl not installed -- pip install openpyxl")
    else:
        print_report("NIFTY")
        print_report("BANKNIFTY")