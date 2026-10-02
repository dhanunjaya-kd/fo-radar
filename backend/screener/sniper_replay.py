"""
screener/sniper_replay.py

Replays Sniper v3's STRUCTURAL rules over already-logged signal files so the
effect on call volume and outcome mix can be read off real data before trusting
any of it live.

    cd backend
    python -m screener.sniper_replay                       # every signals_*.xlsx under signal_logs/
    python -m screener.sniper_replay --file path/to/signals_2026-10-01.xlsx

What it can and cannot show -- read this before quoting a number:
  * It replays the SignalBook (symbol day-lock, sector/direction caps, new-call
    budget, entry window, max hold) and the two evidence gates that can be
    evaluated from logged columns (directional RSI, BUY-ADX). Each logged row is
    treated as live from its Timestamp until its Exited At.
  * It CANNOT replay the intraday trigger (no 5m history is logged), the
    cost-to-risk gate (bid/ask is not logged) or relative RVOL. Those are
    measured forward via sniper_v3_trigger_<date>.csv and the per-signal fields
    cost_to_risk / rvol_relative / trigger_state.
  * The RSI/BUY-ADX gates were found on this same data, so their rows are
    IN-SAMPLE. The structural-only table is the cleaner read; the
    "+ evidence gates" table shows what the fitted gates add on top.
  * Rows with no logged Exited At are assumed live for 60 minutes.
  * Outcomes are the tracker's, unchanged: W = Target N hit, L = SL hit,
    E = left the list without either, O = never resolved. Expectancy is gross
    (before spread/slippage) at a Target-1 exit.
"""
import argparse
import glob
import os
import re

import pandas as pd

from . import sniper_v3 as v3

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "signal_logs")


def _res(outcome):
    o = str(outcome)
    return "W" if o.startswith("Target") else "L" if o == "SL Hit" else "E" if o.startswith("Expired") else "O"


def load(paths):
    frames = []
    for p in paths:
        try:
            df = pd.read_excel(p, sheet_name="Signals")
        except Exception as exc:
            print(f"skip {p}: {exc}")
            continue
        m = re.search(r"\d{4}-\d{2}-\d{2}", os.path.basename(p))
        df["day"] = m.group(0) if m else os.path.basename(p)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    d = pd.concat(frames, ignore_index=True)
    d["ts"] = pd.to_datetime(d["Timestamp"], errors="coerce")
    d = d[d["ts"].notna()].copy()
    d["exit"] = pd.to_datetime(d["Exited At"], errors="coerce")
    # Older logs often lack an exit time; assume such a row stayed on the list 60 min.
    d["exit"] = d["exit"].fillna(d["ts"] + pd.Timedelta(minutes=60))
    d["res"] = d["Outcome"].map(_res)
    for c in ("Entry (Premium)", "SL", "Target 1", "RSI", "ADX"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    risk = d["Entry (Premium)"] - d["SL"]
    r1 = (d["Target 1"] - d["Entry (Premium)"]) / risk
    d["r"] = pd.Series([(-1.0 if res == "L" else x) if res in ("W", "L") else None for res, x in zip(d["res"], r1)], index=d.index)
    return d


def replay_day(rows, cfg, use_gates):
    """rows: one day's DataFrame. Returns the kept row indices."""
    book = v3.SignalBook(cfg)
    kept, counted = set(), set()
    rows = rows.sort_values("ts")
    for t in sorted(rows["ts"].unique()):
        now = pd.Timestamp(t).to_pydatetime()
        live = rows[(rows["ts"] <= t) & (rows["exit"] > t)]
        cands = []
        for idx, r in live.iterrows():
            sym, act = r["Symbol"], r["Action"]
            if use_gates and not book.is_active(sym, act, now):
                if not v3.rsi_direction_ok(act, None if pd.isna(r["RSI"]) else float(r["RSI"])):
                    continue
                if not v3.adx_gate_ok(act, None if pd.isna(r["ADX"]) else float(r["ADX"])):
                    continue
            rank, _ = v3.rank_score(act, None if pd.isna(r["ADX"]) else float(r["ADX"]), None, None, None,
                                    None if pd.isna(r["RSI"]) else float(r["RSI"]))
            cands.append({"symbol": sym, "action": act, "sector": r["Sector"], "rank_score": rank, "_idx": idx})
        shown, _ = book.select(cands, now)
        for s in shown:
            # A call that stays on the list across several logged rows is ONE call.
            if "_idx" in s and s["symbol"] not in counted:
                counted.add(s["symbol"])
                kept.add(s["_idx"])
    return kept


def summarize(d, label):
    n = len(d)
    w, l = (d["res"] == "W").sum(), (d["res"] == "L").sum()
    e, o = (d["res"] == "E").sum(), (d["res"] == "O").sum()
    wr = f"{w / (w + l):.0%}" if (w + l) else "n/a"
    exp = f"{d['r'].dropna().mean():+.2f}R" if d["r"].notna().any() else "n/a"
    return f"{label:<34}{n:>6}{w:>6}{l:>6}{e:>6}{o:>6}{wr:>9}{exp:>10}"


def trigger_report(d, log_dir):
    """
    Score the SHADOW intraday trigger against real outcomes: for every logged
    call, take the trigger state in force at its emission time (from
    sniper_v3_trigger_<day>.csv, written on each state change) and tabulate
    results per state. This is the evidence needed before setting
    SNIPER_TRIGGER_MODE=enforce -- TRIGGERED should beat NO_TRIGGER by a margin
    that survives more than one or two sessions.
    """
    rows = []
    for day, g in d.groupby("day"):
        path = os.path.join(log_dir, day, f"sniper_v3_trigger_{day}.csv")
        if not os.path.exists(path):
            continue
        t = pd.read_csv(path)
        t["ts"] = pd.to_datetime(day + " " + t["time"].astype(str))
        for idx, r in g.iterrows():
            m = t[(t["symbol"] == r["Symbol"]) & (t["action"] == r["Action"]) & (t["ts"] <= r["ts"] + pd.Timedelta(minutes=2))]
            rows.append((idx, m.iloc[-1]["state"] if len(m) else "NOT_LOGGED", m.iloc[-1]["type"] if len(m) else None))
    if not rows:
        print("no sniper_v3_trigger_*.csv files found yet -- run a few sessions with SNIPER_TRIGGER_MODE=shadow first")
        return
    tag = pd.DataFrame(rows, columns=["idx", "state", "type"]).set_index("idx")
    j = d.join(tag, how="inner")
    print(f"{'trigger state at emission':<34}{'calls':>6}{'W':>6}{'L':>6}{'E':>6}{'O':>6}{'WR(res)':>9}{'exp@T1':>10}")
    for st, g in j.groupby("state"):
        print(summarize(g, st))
    for st, g in j[j["state"] == "TRIGGERED"].groupby("type"):
        print(summarize(g, f"  TRIGGERED / {st}"))
    print("\nDays covered:", j["day"].nunique(), "-- calls from one day are correlated; judge by days, not by call count.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=LOG_DIR)
    ap.add_argument("--file", action="append")
    ap.add_argument("--trigger-report", action="store_true", help="score the shadow intraday trigger against outcomes")
    a = ap.parse_args()
    paths = a.file or sorted(glob.glob(os.path.join(a.dir, "*", "signals_*.xlsx")))
    d = load(paths)
    if d.empty:
        print("no signal files found")
        return
    if a.trigger_report:
        trigger_report(d, a.dir)
        return
    cfg = dict(v3.CONFIG, ENTRY_START_MIN=9 * 60 + 15)
    header = f"{'':<34}{'calls':>6}{'W':>6}{'L':>6}{'E':>6}{'O':>6}{'WR(res)':>9}{'exp@T1':>10}"
    print(header)
    print(summarize(d, "legacy (every logged row)"))
    for use_gates, label in ((False, "v3 structural only"), (True, "v3 structural + RSI/BUY-ADX*")):
        kept = set()
        for _, day_rows in d.groupby("day"):
            kept |= replay_day(day_rows, cfg, use_gates)
        print(summarize(d.loc[sorted(kept)], label))
    print("* in-sample: those two gates were fitted on this same data.\n")
    print(f"{'day':<12}{'legacy':>8}{'v3 struct':>11}{'v3 + gates':>12}")
    per = []
    for day, rows in d.groupby("day"):
        per.append((day, len(rows), len(replay_day(rows, cfg, False)), len(replay_day(rows, cfg, True))))
    for r in per:
        print(f"{r[0]:<12}{r[1]:>8}{r[2]:>11}{r[3]:>12}")
    print(f"{'median':<12}{int(pd.Series([r[1] for r in per]).median()):>8}"
          f"{int(pd.Series([r[2] for r in per]).median()):>11}{int(pd.Series([r[3] for r in per]).median()):>12}")


if __name__ == "__main__":
    main()
