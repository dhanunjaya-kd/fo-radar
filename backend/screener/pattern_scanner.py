"""
screener/pattern_scanner.py

Oct 2 2026 (Scanner phase 2): universe-wide chart-pattern scan on top of chart_patterns.py.

A scan walks a universe one symbol at a time, pulls each symbol's daily history through an
injected `history_fn` (views.py passes its paced, once-per-day-cached Fyers fetch -- so a cold
scan costs one governed History call per symbol and a warm one costs nothing), runs the
detector, and keeps a compact, drawable payload per pattern. State lives in memory and is
persisted to runtime/chart_patterns_<universe>.json so the tab is usable immediately after a
restart. Scans are explicit (user presses "Scan again"), single-flight, and cancel-safe.

Everything here is Django-free and Fyers-free so it can be unit tested with a fake history_fn.
"""
import json
import os
import threading
import time
from datetime import datetime

from . import chart_patterns as cp

RUNTIME_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "runtime")
CONTEXT_BARS = 8          # candles of context drawn before a pattern starts
MIN_HISTORY = 60

_lock = threading.Lock()
_state = {}               # {universe: {...}}
_threads = {}             # {universe: Thread}


def _path(universe):
    return os.path.join(RUNTIME_DIR, f"chart_patterns_{universe}.json")


def _date(ts):
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except Exception:
        return None


def payloads_for_symbol(symbol, o, h, l, c, v, ts):
    """Detect and return drawable pattern payloads for one symbol (completed daily candles, oldest first)."""
    if len(c) < MIN_HISTORY:
        return None  # not enough history -- distinct from "scanned, nothing found" ([])
    found = cp.detect(o, h, l, c, v)
    n = len(c)
    out = []
    for p in found:
        w0 = max(0, p["start_i"] - CONTEXT_BARS)
        r2 = lambda x: round(x, 2)
        item = {
            "id": f"{symbol}-{p['name'].replace(' ', '')}-{p['end_i']}",
            "symbol": symbol, "name": p["name"], "family": p["family"], "direction": p["direction"],
            "status": p["status"], "score": p["score"], "quality": p["quality"],
            "bars_ago": p["bars_ago"], "span_bars": p["end_i"] - p["start_i"] + 1,
            "trigger": p["trigger"], "stop": p["stop"], "target": p["target"], "rr": p["rr"],
            "pct_vs_trigger": p["pct_vs_trigger"], "volume_confirmed": p["volume_confirmed"],
            "unresolved": bool(p.get("unresolved")), "atr": p.get("atr"),
            "last_close": r2(c[-1]), "day_change_pct": round((c[-1] / c[-2] - 1) * 100, 2) if n > 1 and c[-2] else None,
            "end_date": _date(ts[p["end_i"]]) if ts else None, "data_through": _date(ts[-1]) if ts else None,
            "window_start": _date(ts[w0]) if ts else None,
            "candles": [[r2(o[i]), r2(h[i]), r2(l[i]), r2(c[i])] for i in range(w0, n)],
            "lines": [{"kind": ln["kind"], "x1": ln["x1"] - w0, "y1": r2(ln["y1"]), "x2": ln["x2"] - w0, "y2": r2(ln["y2"])} for ln in p["lines"]],
            "markers": [{"x": m["x"] - w0, "y": r2(m["y"]), "label": m["label"]} for m in p["markers"]],
        }
        if p.get("curve"):
            item["curve"] = [{"x": pt["x"] - w0, "y": r2(pt["y"])} for pt in p["curve"]]
        if p.get("broke_i") is not None:
            item["broke_x"] = p["broke_i"] - w0
        out.append(item)
    return out


def status(universe):
    with _lock:
        st = _state.get(universe)
        if st is None:
            st = _load_locked(universe)
        return {k: v for k, v in (st or {}).items() if k != "patterns"} or {"universe": universe, "state": "never", "scanned": 0, "total": 0}


def patterns(universe):
    with _lock:
        st = _state.get(universe) or _load_locked(universe)
        return list((st or {}).get("patterns", []))


def _load_locked(universe):
    try:
        with open(_path(universe), "r", encoding="utf-8") as fh:
            st = json.load(fh)
        st["state"] = "done" if st.get("finished_at") else "partial"
        _state[universe] = st
        return st
    except (OSError, ValueError):
        return None


def _save(universe, st):
    try:
        os.makedirs(RUNTIME_DIR, exist_ok=True)
        tmp = _path(universe) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(st, fh, separators=(",", ":"))
        os.replace(tmp, _path(universe))
    except OSError as exc:
        print(f"[PatternScan] could not persist {universe}: {exc}")


def run_scan(universe, symbols, history_fn, should_pause=None, sleep=time.sleep, max_pause_s=120):
    """
    Synchronous scan body (the thread wraps this). history_fn(symbol) -> (o,h,l,c,v,ts) lists or None.
    should_pause() -> True while the data source is rate-limited; the scan waits instead of burning calls.
    """
    started = time.time()
    st = {"universe": universe, "state": "running", "total": len(symbols), "scanned": 0, "with_patterns": 0,
          "failed": 0, "skipped_short": 0, "started_at": datetime.now().isoformat(timespec="seconds"),
          "finished_at": None, "elapsed_s": 0, "data_through": None, "patterns": []}
    with _lock:
        _state[universe] = st
    for k, sym in enumerate(symbols):
        waited = 0
        while should_pause and should_pause() and waited < max_pause_s:
            sleep(3)
            waited += 3
        try:
            series = history_fn(sym)
        except Exception as exc:
            print(f"[PatternScan] {sym} history failed: {exc}")
            series = None
        with _lock:
            st["scanned"] = k + 1
            st["elapsed_s"] = int(time.time() - started)
            if series is None:
                st["failed"] += 1
                continue
            try:
                found = payloads_for_symbol(sym, *series)
            except Exception as exc:
                print(f"[PatternScan] {sym} detection failed: {exc}")
                st["failed"] += 1
                continue
            if found is None:
                st["skipped_short"] += 1
                continue
            if found:
                st["with_patterns"] += 1
                st["patterns"].extend(found)
                st["data_through"] = max(filter(None, [st["data_through"], found[0]["data_through"]]), default=None)
        if (k + 1) % 150 == 0:
            with _lock:
                snap = dict(st, state="partial")
            _save(universe, snap)
    with _lock:
        st["state"] = "done"
        st["finished_at"] = datetime.now().isoformat(timespec="seconds")
        st["elapsed_s"] = int(time.time() - started)
        snap = dict(st)
    _save(universe, snap)
    return st


def start_scan(universe, symbols, history_fn, should_pause=None):
    """Single-flight per universe AND globally (each scan is a paced stream of Fyers calls). Returns (started, reason)."""
    with _lock:
        if any(t.is_alive() for t in _threads.values()):
            return False, "another scan is already running"
        t = threading.Thread(target=run_scan, args=(universe, symbols, history_fn, should_pause), daemon=True, name=f"pattern-scan-{universe}")
        _threads[universe] = t
    t.start()
    return True, "started"


# ---------------------------------------------------------------------------
# query side
# ---------------------------------------------------------------------------
QUALITY_RANK = {"Fair": 1, "Strong": 2, "Textbook": 3}


def composite(p):
    """Ordering key: shape quality, with a bonus for fresh patterns and for ones already confirmed."""
    return p["score"] * 0.7 + max(0, 30 - p["bars_ago"]) + (8 if p["status"] == "Confirmed" else 0)


def query(items, family=None, direction=None, status=None, quality=None, within=None, volume=False, text=None, sort="composite"):
    out = []
    for p in items:
        if family and p["family"] != family:
            continue
        if direction and p["direction"] != direction:
            continue
        if status and p["status"] != status:
            continue
        if quality and QUALITY_RANK.get(p["quality"], 0) < QUALITY_RANK.get(quality, 0):
            continue
        if within is not None and p["bars_ago"] > within:
            continue
        if volume and not p["volume_confirmed"]:
            continue
        if text and text not in p["symbol"].lower() and text not in (p.get("company") or "").lower():
            continue
        out.append(p)
    if sort == "recent":
        out.sort(key=lambda p: (p["bars_ago"], -p["score"]))
    elif sort == "cleanest":
        out.sort(key=lambda p: (-p["score"], p["bars_ago"]))
    else:
        out.sort(key=lambda p: -composite(p))
    return out


def facets(items):
    f = {"family": {}, "direction": {}, "status": {}, "quality": {}}
    for p in items:
        for key, val in (("family", p["family"]), ("direction", p["direction"]), ("status", p["status"]), ("quality", p["quality"])):
            f[key][val] = f[key].get(val, 0) + 1
    return f
