"""
screener/chart_patterns.py

Oct 2 2026 (Scanner phase 2): geometric chart-pattern detection on DAILY
candles. Pure Python (lists + math) -- no pandas/Django -- so it is unit
testable offline and cheap enough to run over a whole universe.

WHAT IT IS
----------
Structure detection, not prediction. It finds the swing pivots of a price
series (ATR-scaled zigzag), then looks for the geometric shapes textbooks
define on those pivots: double/triple tops and bottoms, head & shoulders,
triangles, wedges, rectangles, channels, flags, pennants, rounded tops and
bottoms, cup & handle. Every pattern carries the exact lines it was fitted
with so the UI can draw them, a shape-quality score (how cleanly the price
fits the definition), and trigger / target / stop levels computed from the
pattern's own geometry (measured moves).

WHAT IT IS NOT
--------------
No success rate is implied. These shapes have NOT been back-tested in this
project (no multi-year history is available offline), and detection on
closes is subjective by nature: two analysts draw different lines. Use it
to find charts worth LOOKING at, not as a signal. test_chart_patterns.py
measures the false-positive rate on pure random walks so the quality
thresholds are at least calibrated against "pattern-shaped noise".

METHOD NOTES
------------
* Bearish/neutral shapes are detected once on the series and once on the
  price-inverted series; the inverted hits are mapped back (Double Top ->
  Double Bottom, Rising Wedge -> Falling Wedge, ...). One set of detectors,
  guaranteed mirror symmetry.
* Pivots must be CONFIRMED (price moved >= PIVOT_ATR x ATR away from them),
  so a pattern appears a few bars later than a human might call it. That
  lag is the price of not repainting.
* Status follows the usual definitions: Forming = no decisive close beyond
  the trigger yet; Confirmed = a close beyond the trigger by >= 0.15 ATR that
  still holds on the latest close; Failed = it broke out then closed back
  inside, or price hit the stop first.
"""
import math

PIVOT_ATR = 2.0          # swing must retrace this many ATRs to count as a pivot
MIN_SCORE = 60           # below this a candidate is not reported
BREAK_ATR = 0.15         # close beyond trigger by this many ATRs = decisive
LABELS = ((88, "Textbook"), (75, "Strong"), (60, "Fair"))

# bearish-frame name -> bullish-frame name (used when detecting on the inverted series)
_MIRROR = {
    "Double Top": "Double Bottom", "Triple Top": "Triple Bottom",
    "Head & Shoulders": "Inverse Head & Shoulders", "Rising Wedge": "Falling Wedge",
    "Descending Triangle": "Ascending Triangle", "Bear Flag": "Bull Flag",
    "Bear Pennant": "Bull Pennant", "Rounded Top": "Rounded Bottom",
    "Symmetrical Triangle": "Symmetrical Triangle", "Ascending Channel": "Descending Channel",
}
_FAMILY = {
    "Double Top": "Reversal", "Double Bottom": "Reversal", "Triple Top": "Reversal", "Triple Bottom": "Reversal",
    "Head & Shoulders": "Reversal", "Inverse Head & Shoulders": "Reversal",
    "Rising Wedge": "Reversal", "Falling Wedge": "Reversal",
    "Descending Triangle": "Continuation", "Ascending Triangle": "Continuation", "Symmetrical Triangle": "Continuation",
    "Bear Flag": "Continuation", "Bull Flag": "Continuation", "Bear Pennant": "Continuation", "Bull Pennant": "Continuation",
    "Rectangle": "Range", "Ascending Channel": "Range", "Descending Channel": "Range",
    "Rounded Top": "Curve & Cup", "Rounded Bottom": "Curve & Cup", "Cup & Handle": "Curve & Cup",
}
FAMILIES = ("Reversal", "Continuation", "Range", "Curve & Cup")


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------
def atr(h, l, c, n=14):
    trs = [h[0] - l[0]]
    for i in range(1, len(c)):
        trs.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    tail = trs[-n:]
    return sum(tail) / len(tail) if tail else 0.0


def zigzag(h, l, thr):
    """Confirmed swing pivots [{'i','p','t'}] (t = 'H' | 'L'), alternating. thr in price units."""
    n = len(h)
    pivots = []
    if n < 3:
        return pivots
    hi_i = lo_i = 0
    trend = 0
    ext = 0
    for i in range(1, n):
        if trend == 0:
            if h[i] > h[hi_i]:
                hi_i = i
            if l[i] < l[lo_i]:
                lo_i = i
            if h[hi_i] - l[lo_i] >= thr and hi_i != lo_i:
                if hi_i > lo_i:
                    pivots.append({"i": lo_i, "p": l[lo_i], "t": "L"})
                    trend, ext = 1, hi_i
                else:
                    pivots.append({"i": hi_i, "p": h[hi_i], "t": "H"})
                    trend, ext = -1, lo_i
        elif trend == 1:
            if h[i] > h[ext]:
                ext = i
            elif h[ext] - l[i] >= thr:
                pivots.append({"i": ext, "p": h[ext], "t": "H"})
                trend, ext = -1, i
        else:
            if l[i] < l[ext]:
                ext = i
            elif h[i] - l[ext] >= thr:
                pivots.append({"i": ext, "p": l[ext], "t": "L"})
                trend, ext = 1, i
    return pivots


def _fit(points):
    """Least-squares line through [(x, y)], returns (m, b, mean_abs_residual)."""
    n = len(points)
    if n < 2:
        return 0.0, points[0][1] if points else 0.0, 0.0
    sx = sum(x for x, _ in points)
    sy = sum(y for _, y in points)
    sxx = sum(x * x for x, _ in points)
    sxy = sum(x * y for x, y in points)
    den = n * sxx - sx * sx
    if abs(den) < 1e-12:
        return 0.0, sy / n, 0.0
    m = (n * sxy - sx * sy) / den
    b = (sy - m * sx) / n
    res = sum(abs(y - (m * x + b)) for x, y in points) / n
    return m, b, res


def _clamp01(x):
    return max(0.0, min(1.0, x))


def _prior_trend(c, idx, a, lookback=25, k=2.5):
    j = max(0, idx - lookback)
    chg = c[idx] - c[j]
    return "up" if chg >= k * a else "down" if chg <= -k * a else "flat"


def _frac_outside(c, i0, i1, upper, lower, tol):
    """Share of closes in [i0, i1] outside the band between two lines (± tol)."""
    out = tot = 0
    for i in range(i0, i1 + 1):
        tot += 1
        if c[i] > upper(i) + tol or c[i] < lower(i) - tol:
            out += 1
    return out / tot if tot else 1.0


def _status(direction, trig, stop, c, from_i, a):
    """
    direction 'bullish'|'bearish'; trig/stop are callables bar-index -> price.
    Returns (status, broke_index|None). Looks at closes AFTER the pattern's last defining bar.
    """
    sign = 1 if direction == "bullish" else -1
    broke = None
    n = len(c)
    for j in range(from_i + 1, n):
        beyond = sign * (c[j] - trig(j)) >= BREAK_ATR * a
        stopped = sign * (c[j] - stop(j)) <= 0
        if broke is None:
            if stopped:
                return "Failed", None
            if beyond:
                broke = j
        else:
            if stopped:
                return "Failed", broke
    if broke is None:
        return "Forming", None
    return ("Confirmed", broke) if sign * (c[-1] - trig(n - 1)) > 0 else ("Failed", broke)


def _label(score):
    for floor, name in LABELS:
        if score >= floor:
            return name
    return None


def _mk(name, direction, score, a, c, end_i, start_i, trig, stop, target_fn, lines, markers, v=None, vol_avg=None, extra=None):
    """Assemble a pattern dict from geometry. trig/stop: callables; target_fn(trigger_value_now) -> price."""
    n = len(c)
    last = n - 1
    if stop is not None:
        # a stop closer than 1 ATR to the trigger is noise-level and produces a meaningless
        # 10:1 R:R (typical when converging lines nearly meet) -- keep at least 1 ATR of room
        raw_stop, sgn = stop, (1 if direction == "bullish" else -1)
        stop = lambda j, raw=raw_stop, sgn=sgn: (min(raw(j), trig(j) - 1.0 * a) if sgn == 1 else max(raw(j), trig(j) + 1.0 * a))
    trig_now = trig(last)
    stop_now = stop(last) if stop else None
    target = target_fn(trig_now) if target_fn else None
    status, broke = _status(direction, trig, stop, c, end_i, a) if stop else ("Forming", None)
    risk = abs(trig_now - stop_now) if stop_now is not None else None
    rr = round(abs(target - trig_now) / risk, 1) if (risk and target is not None) else None
    vol_ok = False
    if broke is not None and v and vol_avg:
        vol_ok = any(v[j] >= 1.5 * vol_avg for j in range(broke, min(n, broke + 3)))
    out = {
        "name": name, "family": _FAMILY[name], "direction": direction.capitalize(),
        "status": status, "score": int(round(score)), "quality": _label(score),
        "start_i": start_i, "end_i": end_i, "bars_ago": last - end_i,
        "trigger": round(trig_now, 2) if trig_now is not None else None,
        "stop": round(stop_now, 2) if stop_now is not None else None,
        "target": round(target, 2) if target is not None else None,
        "rr": rr, "pct_vs_trigger": round((c[-1] / trig_now - 1) * 100, 1) if trig_now else None,
        "volume_confirmed": vol_ok, "broke_i": broke,
        "lines": lines, "markers": markers,
    }
    if extra:
        out.update(extra)
    return out


# ---------------------------------------------------------------------------
# detectors -- all written for the "bearish / neutral" frame
# ---------------------------------------------------------------------------
def _peak_tol(a, price):
    return max(0.7 * a, 0.010 * price)


def _double_top(P, h, l, c, v, a, n, vol_avg):
    out = []
    for k in range(len(P) - 2):
        p0, p1, p2 = P[k], P[k + 1], P[k + 2]
        if not (p0["t"] == "H" and p1["t"] == "L" and p2["t"] == "H"):
            continue
        h1, h2, neck = p0["p"], p2["p"], p1["p"]
        tol = _peak_tol(a, (h1 + h2) / 2)
        depth = (h1 + h2) / 2 - neck
        sep = p2["i"] - p0["i"]
        if abs(h1 - h2) > tol or depth < 3.0 * a or not (10 <= sep <= 80) or n - 1 - p2["i"] > 30:
            continue
        if _prior_trend(c, p0["i"], a) != "up":
            continue
        # neckline must hold between the tops (no close below it)
        if min(c[p0["i"]:p2["i"] + 1]) < neck - 0.3 * a:
            continue
        score = 100 * (0.45 * (1 - _clamp01(abs(h1 - h2) / tol)) + 0.35 * _clamp01(depth / (4 * a)) + 0.20 * _clamp01(sep / 25))
        top = max(h1, h2)
        trig = lambda j, neck=neck: neck
        stop = lambda j, top=top: top + 0.25 * a
        out.append(_mk("Double Top", "bearish", score, a, c, p2["i"], p0["i"], trig, stop,
                       lambda t, depth=depth: t - depth,
                       [{"kind": "trigger", "x1": p0["i"], "y1": neck, "x2": n - 1, "y2": neck},
                        {"kind": "resistance", "x1": p0["i"], "y1": top, "x2": p2["i"], "y2": top}],
                       [{"x": p0["i"], "y": h1, "label": "Top"}, {"x": p2["i"], "y": h2, "label": "Top"}], v, vol_avg))
    return out


def _triple_top(P, h, l, c, v, a, n, vol_avg):
    out = []
    for k in range(len(P) - 4):
        q = P[k:k + 5]
        if [x["t"] for x in q] != ["H", "L", "H", "L", "H"]:
            continue
        hs = [q[0]["p"], q[2]["p"], q[4]["p"]]
        ls = [q[1]["p"], q[3]["p"]]
        tol = _peak_tol(a, sum(hs) / 3)
        if max(hs) - min(hs) > tol * 1.2 or abs(ls[0] - ls[1]) > tol * 1.5:
            continue
        neck = min(ls)
        depth = sum(hs) / 3 - neck
        if depth < 2.0 * a or q[4]["i"] - q[0]["i"] > 100 or n - 1 - q[4]["i"] > 30:
            continue
        if _prior_trend(c, q[0]["i"], a) != "up":
            continue
        score = 100 * (0.5 * (1 - _clamp01((max(hs) - min(hs)) / (tol * 1.2))) + 0.3 * _clamp01(depth / (4 * a)) + 0.2 * (1 - _clamp01(abs(ls[0] - ls[1]) / (tol * 1.5))))
        top = max(hs)
        out.append(_mk("Triple Top", "bearish", score, a, c, q[4]["i"], q[0]["i"], lambda j, neck=neck: neck, lambda j, top=top: top + 0.25 * a,
                       lambda t, depth=depth: t - depth,
                       [{"kind": "trigger", "x1": q[0]["i"], "y1": neck, "x2": n - 1, "y2": neck},
                        {"kind": "resistance", "x1": q[0]["i"], "y1": top, "x2": q[4]["i"], "y2": top}],
                       [{"x": q[0]["i"], "y": hs[0], "label": "Top"}, {"x": q[2]["i"], "y": hs[1], "label": "Top"}, {"x": q[4]["i"], "y": hs[2], "label": "Top"}],
                       v, vol_avg))
    return out


def _head_shoulders(P, h, l, c, v, a, n, vol_avg):
    out = []
    for k in range(len(P) - 4):
        q = P[k:k + 5]
        if [x["t"] for x in q] != ["H", "L", "H", "L", "H"]:
            continue
        ls_, head, rs = q[0]["p"], q[2]["p"], q[4]["p"]
        n1, n2 = q[1], q[3]
        neck_avg = (n1["p"] + n2["p"]) / 2
        height = head - neck_avg
        if height < 2.5 * a or head - max(ls_, rs) < 1.0 * a:
            continue
        if abs(ls_ - rs) > 0.35 * height or abs(n1["p"] - n2["p"]) > 0.4 * height:
            continue
        if q[4]["i"] - q[0]["i"] > 110 or n - 1 - q[4]["i"] > 30 or _prior_trend(c, q[0]["i"], a) != "up":
            continue
        m, b, _ = _fit([(n1["i"], n1["p"]), (n2["i"], n2["p"])])
        neckline = lambda j, m=m, b=b: m * j + b
        head_i = q[2]["i"]
        h_above = head - neckline(head_i)
        sym = 1 - _clamp01(abs(ls_ - rs) / (0.35 * height))
        neck_flat = 1 - _clamp01(abs(n1["p"] - n2["p"]) / (0.4 * height))
        score = 100 * (0.4 * sym + 0.25 * neck_flat + 0.35 * _clamp01(height / (5 * a)))
        out.append(_mk("Head & Shoulders", "bearish", score, a, c, q[4]["i"], q[0]["i"], neckline, lambda j, rs=rs: rs + 0.25 * a,
                       lambda t, hh=h_above: t - hh,
                       [{"kind": "trigger", "x1": n1["i"], "y1": neckline(n1["i"]), "x2": n - 1, "y2": neckline(n - 1)}],
                       [{"x": q[0]["i"], "y": ls_, "label": "LS"}, {"x": head_i, "y": head, "label": "Head"}, {"x": q[4]["i"], "y": rs, "label": "RS"}],
                       v, vol_avg))
    return out


def _line_patterns(P, h, l, c, v, a, n, vol_avg, original_frame):
    """Triangles / wedges / channels / rectangles from the last pivots' fitted trendlines."""
    out = []
    if len(P) < 5:
        return out
    seen = set()
    windows = [(st, en) for en in (len(P), len(P) - 1, len(P) - 2) for st in range(max(0, en - 9), en - 4)]
    for start, end in windows:
        sub = P[start:end]
        if len(sub) < 5:
            continue
        Hs = [(p["i"], p["p"]) for p in sub if p["t"] == "H"]
        Ls = [(p["i"], p["p"]) for p in sub if p["t"] == "L"]
        if len(Hs) < 2 or len(Ls) < 2:
            continue
        i0, i1 = sub[0]["i"], sub[-1]["i"]
        span = i1 - i0
        if not (15 <= span <= 90) or n - 1 - i1 > 20:
            continue
        mu, bu, ru = _fit(Hs)
        ml, bl, rl = _fit(Ls)
        upper = lambda j, mu=mu, bu=bu: mu * j + bu
        lower = lambda j, ml=ml, bl=bl: ml * j + bl
        w0, w1 = upper(i0) - lower(i0), upper(i1) - lower(i1)
        if w0 <= 0.5 * a or w1 <= 0.3 * a:
            continue
        su, sl = mu * span / a, ml * span / a          # total drift over the span, in ATRs
        r = w1 / w0
        frac_out = _frac_outside(c, i0, min(n - 1, i1), upper, lower, 0.3 * a)
        if frac_out > 0.15:
            continue
        if w0 < 3 * a:
            continue                                   # too small to be a pattern rather than noise
        # fit is judged against the band's own width (a 0.5 ATR scatter is fine in a 6 ATR band, not in a 2 ATR one)
        fit_rel = (ru + rl) / 2 / ((w0 + w1) / 2)
        fit_q = 1 - _clamp01(fit_rel / 0.08)
        cont_q = 1 - _clamp01(frac_out / 0.15)
        touch_q = _clamp01((len(Hs) + len(Ls) - 4) / 3)   # 5 pivots -> 0.33, 7+ -> 1.0
        dur_q = _clamp01(span / 40)
        score = 100 * (0.35 * fit_q + 0.25 * cont_q + 0.25 * touch_q + 0.15 * dur_q)
        flat = lambda s: abs(s) <= 1.0
        name = None
        if r <= 0.8:
            if flat(sl) and su < -1.5 and len(Ls) >= 3:      # the flat side must be tested at least 3 times
                name = "Descending Triangle"
            elif su > 2.0 and sl > 2.0 and sl > su and r <= 0.65 and len(Hs) >= 3 and len(Ls) >= 3:
                name = "Rising Wedge"
            elif su < -1.5 and sl > 1.5 and _prior_trend(c, i0, a) == "down":
                name = "Symmetrical Triangle"
        elif 0.85 < r < 1.15 and len(Hs) >= 3 and len(Ls) >= 3:
            if su > 2.0 and sl > 2.0:
                name = "Ascending Channel"
            elif original_frame and flat(su) and flat(sl):
                name = "Rectangle"
        if not name or score < MIN_SCORE:
            continue
        key = (name, i0 // 5, i1 // 5)
        if key in seen:
            continue
        seen.add(key)
        lines = [{"kind": "upper", "x1": i0, "y1": upper(i0), "x2": n - 1, "y2": upper(n - 1)},
                 {"kind": "lower", "x1": i0, "y1": lower(i0), "x2": n - 1, "y2": lower(n - 1)}]
        markers = [{"x": x, "y": y, "label": ""} for x, y in Hs + Ls]
        if name in ("Ascending Channel", "Rectangle"):
            if name == "Rectangle":
                # bias: prior trend decides; flat -> side of the range price is nearer to
                pt = _prior_trend(c, i0, a)
                bear = pt == "down" or (pt == "flat" and c[-1] < (upper(n - 1) + lower(n - 1)) / 2)
                trig = lower if bear else upper
                stop = upper if bear else lower
                sgn = -1 if bear else 1
                stop_off = (0.25 * a) * (1 if bear else -1)
                pat = _mk("Rectangle", "bearish" if bear else "bullish", score, a, c, i1, i0, trig, lambda j, stop=stop, so=stop_off: stop(j) + so,
                          lambda t, w=w0, s=sgn: t + s * w, lines, markers, v, vol_avg, {"unresolved": True})
            else:
                pat = _mk(name, "neutral", score, a, c, i1, i0, lower, None, None, lines, markers, v, vol_avg)
                pat["status"] = "Forming"
            out.append(pat)
            continue
        tgt = lambda t, w=w0: t - w   # wedges and triangles alike: measure the widest part of the pattern
        # stop: beyond the far line, at least max(1 ATR, 35% of the widest width) away, at most 60% of it
        stop_fn = lambda j, upper=upper, lower=lower, w0=w0: lower(j) + min(0.6 * w0, max(1.0 * a, 0.35 * w0, upper(j) - lower(j) + 0.25 * a))
        out.append(_mk(name, "bearish", score, a, c, i1, i0, lower, stop_fn, tgt, lines, markers, v, vol_avg))
    return out


def _flag(P, h, l, c, v, a, n, vol_avg):
    """Bear flag / pennant: sharp drop (pole) then a short counter-trend or converging consolidation."""
    out = []
    for e in range(n - 1 - 4, max(n - 1 - 26, 8), -1):                 # pole low index
        if l[e] > min(l[max(0, e - 3):min(n, e + 4)]) + 1e-9:
            continue
        lo_s = max(0, e - 18)
        window = h[lo_s:e - 2]
        if not window:
            continue
        s = lo_s + window.index(max(window))              # the pole starts at the highest high before its low
        drop = h[s] - l[e]
        if not (drop >= 4 * a and drop / (e - s) >= 0.6 * a and e - s >= 3):
            continue
        best = (s, drop)
        s, drop = best
        L = n - 1 - e
        if not (4 <= L <= 25):
            continue
        if max(h[e + 1:]) - l[e] > 0.55 * drop:
            continue
        hp = [(j, h[j]) for j in range(e + 1, n - 1) if h[j] >= h[j - 1] and h[j] >= h[j + 1]]
        lp = [(j, l[j]) for j in range(e + 1, n - 1) if l[j] <= l[j - 1] and l[j] <= l[j + 1]]
        if len(hp) < 2 or len(lp) < 2 or hp[-1][0] - hp[0][0] < 3 or lp[-1][0] - lp[0][0] < 3:
            continue
        mu, bu, ru = _fit(hp)
        ml, bl, rl = _fit(lp)
        upper = lambda j, mu=mu, bu=bu: mu * j + bu
        lower = lambda j, ml=ml, bl=bl: ml * j + bl
        w0, w1 = upper(e + 1) - lower(e + 1), upper(n - 1) - lower(n - 1)
        if w0 <= 0.3 * a or w1 <= 0.1 * a:
            continue
        su, sl = mu / a, ml / a                                          # ATR per bar
        frac_out = _frac_outside(c, e + 1, n - 1, upper, lower, 0.3 * a)
        if frac_out > 0.2:
            continue
        r = w1 / w0
        if -0.1 <= su <= 0.4 and -0.1 <= sl <= 0.4 and abs(su - sl) <= 0.12 and r > 0.7:
            name = "Bear Flag"
        elif r <= 0.7 and su <= 0.1 and sl >= -0.1:
            name = "Bear Pennant"
        else:
            continue
        resid = (ru + rl) / 2 / a
        score = 100 * (0.35 * _clamp01(drop / (7 * a)) + 0.3 * (1 - _clamp01(resid / 0.6)) + 0.2 * (1 - _clamp01(frac_out / 0.2)) + 0.15 * _clamp01(L / 10))
        if score < MIN_SCORE:
            continue
        out.append(_mk(name, "bearish", score, a, c, n - 1, s, lower, lambda j, upper=upper: upper(j) + 0.25 * a,
                       lambda t, d=drop: t - d,
                       [{"kind": "pole", "x1": s, "y1": h[s], "x2": e, "y2": l[e]},
                        {"kind": "upper", "x1": e + 1, "y1": upper(e + 1), "x2": n - 1, "y2": upper(n - 1)},
                        {"kind": "lower", "x1": e + 1, "y1": lower(e + 1), "x2": n - 1, "y2": lower(n - 1)}],
                       [{"x": s, "y": h[s], "label": ""}, {"x": e, "y": l[e], "label": ""}], v, vol_avg))
        break  # the first (most recent) valid pole is enough
    return out


def _quad_fit(ys):
    """Quadratic least squares y = a x^2 + b x + c over x = 0..n-1 (normalised) -> (a, b, c, r2)."""
    n = len(ys)
    xs = [i / (n - 1) for i in range(n)]
    # normal equations for 3 unknowns, solved by Cramer's rule
    s = [sum(x ** k for x in xs) for k in range(5)]
    t = [sum((x ** k) * y for x, y in zip(xs, ys)) for k in (2, 1, 0)]   # RHS rows match M: x^2 y, x y, y
    M = [[s[4], s[3], s[2]], [s[3], s[2], s[1]], [s[2], s[1], s[0]]]

    def det3(m):
        return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
    d = det3(M)
    if abs(d) < 1e-12:
        return 0, 0, 0, 0
    sol = []
    for col in range(3):
        mm = [row[:] for row in M]
        for r_ in range(3):
            mm[r_][col] = t[r_]
        sol.append(det3(mm) / d)
    a_, b_, c_ = sol
    mean = sum(ys) / n
    ss_tot = sum((y - mean) ** 2 for y in ys)
    ss_res = sum((y - (a_ * x * x + b_ * x + c_)) ** 2 for x, y in zip(xs, ys))
    return a_, b_, c_, (1 - ss_res / ss_tot) if ss_tot > 0 else 0


def _rounded_top(P, h, l, c, v, a, n, vol_avg):
    out = []
    for W in (35, 50, 65, 85):
        if n < W + 1:
            continue
        for off in (0, 5, 10):
            e = n - 1 - off
            s = e - W + 1
            if s < 0:
                continue
            seg = c[s:e + 1]
            qa, qb, qc, r2 = _quad_fit(seg)
            if qa >= 0 or r2 < 0.82:
                continue
            apex_x = -qb / (2 * qa)
            if not (0.3 <= apex_x <= 0.7):
                continue
            apex_i = s + int(round(apex_x * (W - 1)))
            top = max(h[s:e + 1])
            rim_l, rim_r = c[s], c[e]
            rim = min(rim_l, rim_r)
            height = top - rim
            if height < 3 * a or abs(rim_l - rim_r) > 0.5 * height:
                continue
            if _prior_trend(c, s, a, 20, 2.0) == "down":
                continue
            score = 100 * (0.55 * _clamp01((r2 - 0.82) / 0.15) + 0.25 * _clamp01(height / (6 * a)) + 0.2 * (1 - _clamp01(abs(rim_l - rim_r) / (0.5 * height))))
            score = max(score, MIN_SCORE) if score >= MIN_SCORE - 10 and r2 >= 0.9 else score
            if score < MIN_SCORE:
                continue
            curve = [{"x": s + i, "y": (qa * (i / (W - 1)) ** 2 + qb * (i / (W - 1)) + qc)} for i in range(0, W, max(1, W // 12))]
            curve.append({"x": e, "y": qa + qb + qc})
            out.append(_mk("Rounded Top", "bearish", score, a, c, e, s, lambda j, rim=rim: rim, lambda j, top=top: top + 0.25 * a,
                           lambda t, hh=height: t - hh,
                           [{"kind": "trigger", "x1": s, "y1": rim, "x2": n - 1, "y2": rim}],
                           [{"x": apex_i, "y": top, "label": "Top"}, {"x": s, "y": c[s], "label": "L"}, {"x": e, "y": c[e], "label": "R"}],
                           v, vol_avg, {"curve": curve}))
            break
    return out


def _cup_handle(P, h, l, c, v, a, n, vol_avg):
    """Bullish only (original frame). Rounded bottom + small pullback (handle) near the right rim."""
    out = []
    for W in (40, 55, 70):
        for handle in range(3, 21):
            e = n - 1 - handle                       # right rim bar
            s = e - W + 1
            if s < 0:
                continue
            seg = c[s:e + 1]
            qa, qb, qc, r2 = _quad_fit(seg)
            if qa <= 0 or r2 < 0.8:
                continue
            vx = -qb / (2 * qa)
            if not (0.3 <= vx <= 0.7):
                continue
            rim_l, rim_r = max(h[s:s + 4]), max(h[e - 3:e + 1])
            low = min(l[s:e + 1])
            depth = min(rim_l, rim_r) - low
            if depth < 3 * a or abs(rim_l - rim_r) > 0.25 * depth:
                continue
            rim = max(rim_l, rim_r)
            hlow = min(l[e:])
            pull = rim_r - hlow
            if not (1.0 * a <= pull <= 0.5 * depth) or c[-1] < low + 0.5 * depth or max(h[e + 1:]) > rim + 2.5 * a:
                continue
            score = 100 * (0.5 * _clamp01((r2 - 0.8) / 0.15) + 0.25 * _clamp01(depth / (6 * a)) + 0.25 * (1 - _clamp01(abs(rim_l - rim_r) / (0.25 * depth))))
            if score < MIN_SCORE:
                continue
            W1 = W - 1
            curve = [{"x": s + i, "y": (qa * (i / W1) ** 2 + qb * (i / W1) + qc)} for i in range(0, W, max(1, W // 12))]
            curve.append({"x": e, "y": qa + qb + qc})
            out.append(_mk("Cup & Handle", "bullish", score, a, c, e, s, lambda j, rim=rim: rim, lambda j, hl=hlow: hl - 0.25 * a,
                           lambda t, d=depth: t + d,
                           [{"kind": "trigger", "x1": s, "y1": rim, "x2": n - 1, "y2": rim}],
                           [{"x": s, "y": rim_l, "label": "L"}, {"x": e, "y": rim_r, "label": "R"}], v, vol_avg, {"curve": curve}))
            return out
    return out


_BEAR_DETECTORS = (_double_top, _triple_top, _head_shoulders, _flag, _rounded_top)


def _invert(o, h, l, c):
    return [-x for x in o], [-x for x in l], [-x for x in h], [-x for x in c]


def _mirror_pattern(p):
    """Map a pattern found on the inverted series back to real prices."""
    q = dict(p)
    q["name"] = _MIRROR[p["name"]]
    q["family"] = _FAMILY[q["name"]]
    q["direction"] = {"Bearish": "Bullish", "Bullish": "Bearish", "Neutral": "Neutral"}[p["direction"]]
    for k in ("trigger", "stop", "target"):
        if q.get(k) is not None:
            q[k] = round(-q[k], 2)
    q["lines"] = [{**ln, "y1": -ln["y1"], "y2": -ln["y2"]} for ln in p["lines"]]
    q["markers"] = [{**m, "y": -m["y"], "label": {"Top": "Bottom"}.get(m["label"], m["label"])} for m in p["markers"]]
    if p.get("curve"):
        q["curve"] = [{"x": pt["x"], "y": -pt["y"]} for pt in p["curve"]]
    return q


def _overlap(a_, b_):
    lo, hi = max(a_["start_i"], b_["start_i"]), min(a_["end_i"], b_["end_i"])
    if hi <= lo:
        return 0.0
    return (hi - lo) / max(1, min(a_["end_i"] - a_["start_i"], b_["end_i"] - b_["start_i"]))


def detect(o, h, l, c, v=None, min_bars=60):
    """
    All patterns on one daily series (completed candles, oldest first). Returns a list of
    pattern dicts, best first. Geometry is in absolute bar indices of the input series.
    """
    n = len(c)
    if n < min_bars:
        return []
    a = atr(h, l, c)
    if a <= 0 or c[-1] <= 0:
        return []
    vol_avg = (sum(v[-21:-1]) / 20.0) if v and len(v) >= 21 else None
    found = []

    for frame_inverted in (False, True):
        oo, hh, ll, cc = _invert(o, h, l, c) if frame_inverted else (o, h, l, c)
        P = zigzag(hh, ll, PIVOT_ATR * a)
        pats = []
        for det in _BEAR_DETECTORS:
            pats += det(P, hh, ll, cc, v, a, n, vol_avg)
        pats += _line_patterns(P, hh, ll, cc, v, a, n, vol_avg, original_frame=not frame_inverted)
        for p in pats:
            found.append(_mirror_pattern(p) if frame_inverted else p)

    found += _cup_handle(None, h, l, c, v, a, n, vol_avg)

    # a cup with a handle supersedes a plain rounded bottom -- and the two equal rims of a cup
    # also read as a Double Top -- over the same bars
    cups = [p for p in found if p["name"] == "Cup & Handle"]
    if cups:
        found = [p for p in found if not (p["name"] in ("Rounded Bottom", "Double Top") and any(_overlap(cp_, p) > 0.5 for cp_ in cups))]

    found = [p for p in found if p["score"] >= MIN_SCORE]
    found.sort(key=lambda p: -p["score"])
    # a Rectangle/Channel (Range) over bars that already form a reversal pattern is the same
    # prices read twice -- keep the reversal reading
    triples = [p for p in found if p["name"] in ("Triple Top", "Triple Bottom", "Head & Shoulders", "Inverse Head & Shoulders")]
    rects = [p for p in found if p["name"] == "Rectangle"]
    found = [p for p in found
             if not (p["family"] == "Range" and any(_overlap(r_, p) > 0.6 for r_ in triples))
             and not (p["name"] in ("Double Top", "Double Bottom") and any(_overlap(r_, p) > 0.6 for r_ in rects))]
    kept = []
    for p in found:
        if any(_overlap(k, p) > 0.6 for k in kept):   # one best reading per stretch of bars
            continue
        kept.append(p)
    for p in kept:
        p["atr"] = round(a, 3)
    return kept
