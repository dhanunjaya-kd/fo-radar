"""
screener/sniper_v3.py

Sniper v3: noise control + an event-based intraday trigger layer.

WHY THIS EXISTS (evidence from this project's own logs, not opinion)
--------------------------------------------------------------------
Oct 1 2026 produced 38 calls in one session, all SELL. Pooled with the
17 earlier logged days (364 signals, 165 resolved to a Target/SL):

* Every "intraday" indicator the engine uses (RSI14, MACD, ADX, "VWAP")
  is computed on DAILY candles with today's live quote appended as one
  extra row. "VWAP" is therefore a 100-day volume-weighted average, not
  the session VWAP. The qualifying state barely changes during the day,
  so the same stocks re-qualify every cycle and there is no timing
  component at all -- which is why calls arrive in bursts (6 at 09:23)
  and re-appear all day.
* The +15 volume points compare cumulative-so-far volume against a
  FULL-day 20d average, so before late afternoon it can never fire.
  The "score" is effectively a binary gate (ADX>=25 & aligned), grades
  A/B/C carry no information, and the top-8 slice sorts on ties --
  stocks rotate in/out of the list and each rotation is logged as a new
  call. 11 of Oct 1's 38 rows ended as "Expired" simply because they
  fell out of the list within minutes.
* RSI is rewarded in 40-65 for BOTH directions. For SELL the winners sat
  below 50 (RSI<50: 45W/12L = 79%; RSI>=50: 6W/11L = 35%, Fisher
  p=0.002, same sign on most days).
* Signals fired after 14:00 almost never resolve (20% resolution rate,
  47% win rate when they do) and the 15-minute CAS window freezes
  prices after 15:15.
* BUY needs real trend strength. BUY with ADX>35: 22W/7L = 76%, +0.50R
  gross (n=29); BUY with ADX<=35: 28W/34L = 45%, -0.12R (n=62), Fisher
  p=0.007, higher on most days that had both. SELL shows no such split
  (ADX 25-35 already wins 75%). ~10 hypotheses were examined to find
  this, so it is the least certain of the enforced gates -- reversible
  via SNIPER_BUY_MIN_ADX=0.
* R:R is ~0.89 on the option premium (break-even win rate ~53%). The
  allowed bid/ask spread (15% of premium) is about 0.6R of round-trip
  cost against a measured +0.19R gross expectancy per trade. Cost, not
  signal quality, is the largest un-modelled drag.
* BUY side: 56% win rate / +0.09R gross -- indistinguishable from a
  coin flip once spread is paid. SELL side: 69% / +0.31R. (Sample is
  day-clustered -- 18 days, not 165 independent trades -- so treat as a
  reason to measure, not a proof.)

WHAT IS HERE
------------
1. Directional RSI gate + BUY-ADX gate -- enforced (statistically supported).
2. Cost-to-risk gate               -- enforced (arithmetic, not a fit).
3. Universe-relative RVOL          -- fixes the time-of-day volume bug.
4. Event-based intraday trigger    -- session-VWAP + opening-range logic
   on completed 5m candles; SHADOW by default (cannot be back-tested
   offline: no 5m history exists in the repo). Flip with
   SNIPER_TRIGGER_MODE=enforce once the shadow log supports it.
5. SignalBook                      -- sticky slots, per-symbol day lock,
   sector cap, direction cap, entry window, new-call budget. A call
   stays on the list until it resolves (SL / Target 3), times out, or
   is genuinely invalidated -- never because a rank tie re-ordered.

Everything is pure and injectable (no Django, no Fyers imports at module
level) so it is unit-testable offline.
"""
import csv
import os
import threading
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Configuration -- every knob is env-overridable, no code change to revert.
# ---------------------------------------------------------------------------
def _env_bool(name, default):
    return os.environ.get(name, "true" if default else "false").strip().lower() == "true"


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


def _env_hhmm(name, default):
    raw = os.environ.get(name, default)
    try:
        h, m = str(raw).split(":")
        return int(h) * 60 + int(m)
    except (TypeError, ValueError):
        h, m = default.split(":")
        return int(h) * 60 + int(m)


CONFIG = {
    # Master switch for everything in this module that touches live decisions.
    "ENABLED": _env_bool("SNIPER_V3_ENABLED", True),
    # 1. Direction-aware RSI: SELL needs RSI<50, BUY needs RSI>50.
    "REQUIRE_DIRECTIONAL_RSI": _env_bool("SNIPER_REQUIRE_DIRECTIONAL_RSI", True),
    # BUY needs ADX>=this (0 disables). SELL has no ADX floor beyond the legacy 25.
    "BUY_MIN_ADX": _env_float("SNIPER_BUY_MIN_ADX", 35),
    # 2. Round-trip spread as a fraction of 1R (entry-SL). 0.30 ~ spread<=7%.
    "MAX_COST_TO_RISK": _env_float("SNIPER_MAX_COST_TO_RISK", 0.30),
    # 4. Intraday trigger: "off" | "shadow" | "enforce".
    "TRIGGER_MODE": os.environ.get("SNIPER_TRIGGER_MODE", "shadow").strip().lower(),
    "OR_CANDLES": _env_int("SNIPER_OR_CANDLES", 3),            # 3 x 5m = 09:15-09:30 opening range
    "MIN_CANDLES": _env_int("SNIPER_MIN_CANDLES", 4),          # no trigger before ~09:35
    "FRESH_CANDLES": _env_int("SNIPER_FRESH_CANDLES", 3),      # break must be this recent -- no chasing
    "MAX_EXTENSION_ATR": _env_float("SNIPER_MAX_EXTENSION_ATR", 0.6),  # |close-VWAP| / daily ATR
    "MIN_VOL_EXPANSION": _env_float("SNIPER_MIN_VOL_EXPANSION", 1.0),  # last-3 vs session avg 5m volume
    # 5. SignalBook.
    "SAME_DAY_LOCK": _env_bool("SNIPER_SAME_DAY_LOCK", True),
    "MAX_ACTIVE": _env_int("SNIPER_MAX_ACTIVE", 8),
    "MAX_ACTIVE_PER_DIRECTION": _env_int("SNIPER_MAX_ACTIVE_PER_DIRECTION", 6),
    "MAX_ACTIVE_PER_SECTOR": _env_int("SNIPER_MAX_ACTIVE_PER_SECTOR", 2),
    "MAX_NEW_PER_30MIN": _env_int("SNIPER_MAX_NEW_PER_30MIN", 3),
    "ENTRY_START_MIN": _env_hhmm("SNIPER_ENTRY_START", "09:15"),
    "ENTRY_END_MIN": _env_hhmm("SNIPER_ENTRY_END", "14:00"),
    "MAX_HOLD_MIN": _env_int("SNIPER_MAX_HOLD_MIN", 150),
    "MISSING_GRACE_CYCLES": _env_int("SNIPER_MISSING_GRACE_CYCLES", 1),
}


def trigger_enforced():
    return CONFIG["ENABLED"] and CONFIG["TRIGGER_MODE"] == "enforce"


def trigger_active():
    """Whether to evaluate the trigger at all (shadow still evaluates + logs)."""
    return CONFIG["ENABLED"] and CONFIG["TRIGGER_MODE"] in ("shadow", "enforce")


# ---------------------------------------------------------------------------
# 1. Directional RSI
# ---------------------------------------------------------------------------
def rsi_direction_ok(action, rsi):
    """BUY needs RSI>50 (buyers in control), SELL needs RSI<50. None -> True
    (missing data is not evidence; upstream NaN guards already drop bad RSI)."""
    if rsi is None or not (CONFIG["ENABLED"] and CONFIG["REQUIRE_DIRECTIONAL_RSI"]):
        return True
    return rsi > 50 if action == "BUY" else rsi < 50


def adx_gate_ok(action, adx):
    """BUY only with strong trend (ADX>=BUY_MIN_ADX). Disabled when ENABLED is off."""
    if not CONFIG["ENABLED"] or action != "BUY" or adx is None:
        return True
    return adx >= CONFIG["BUY_MIN_ADX"]


# ---------------------------------------------------------------------------
# 2. Cost-to-risk
# ---------------------------------------------------------------------------
def cost_to_risk(bid, ask, entry, sl):
    """
    Round-trip spread cost as a fraction of one unit of risk.

    Buying at the ask and selling at the bid costs the full (ask-bid)
    against a risk unit of (entry-sl). Anything above ~0.3 means a
    third of every stop-out is paid to the market maker before the
    thesis is even tested. Returns None when it cannot be computed.
    """
    try:
        if bid is None or ask is None or entry is None or sl is None:
            return None
        risk = abs(float(entry) - float(sl))
        spread = float(ask) - float(bid)
        if risk <= 0 or spread < 0:
            return None
        return round(spread / risk, 3)
    except (TypeError, ValueError):
        return None


def cost_to_risk_ok(ctr):
    """None (unknown) passes -- the legacy 15% spread gate still guards that path."""
    if ctr is None or not CONFIG["ENABLED"]:
        return True
    return ctr <= CONFIG["MAX_COST_TO_RISK"]


# ---------------------------------------------------------------------------
# 3. Universe-relative RVOL
# ---------------------------------------------------------------------------
def median(values):
    vals = sorted(v for v in values if v is not None)
    n = len(vals)
    if n == 0:
        return None
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2


def relative_rvol(stock_ratio, universe_median_ratio):
    """
    stock cumulative-volume / 20d-avg-daily-volume, divided by the same ratio's
    cross-sectional median across the whole scanned universe RIGHT NOW.

    The median IS the empirical intraday volume curve for today (it already
    contains the open-heavy U shape and any market-wide high/low-volume day),
    so no hard-coded profile is needed. 1.0 = in line with the typical stock
    at this moment; 2.0 = twice as much participation as normal for this time.
    """
    if stock_ratio is None or not universe_median_ratio or universe_median_ratio <= 0:
        return None
    return round(stock_ratio / universe_median_ratio, 2)


# ---------------------------------------------------------------------------
# 4. Intraday trigger (completed 5m candles: [ts, o, h, l, c, v], oldest first)
# ---------------------------------------------------------------------------
def running_vwap(candles):
    """Session VWAP after each candle (typical price weighted by volume)."""
    out, pv, vol = [], 0.0, 0.0
    for c in candles:
        tp = (c[2] + c[3] + c[4]) / 3.0
        pv += tp * c[5]
        vol += c[5]
        out.append(pv / vol if vol > 0 else None)
    return out


def opening_range(candles, n):
    head = candles[:n]
    if len(head) < n:
        return None, None
    return max(c[2] for c in head), min(c[3] for c in head)


def evaluate_trigger(action, candles, daily_atr=None, cfg=None):
    """
    Event-based entry check. Returns a dict:
      state: TRIGGERED | NO_TRIGGER | UNKNOWN
      type : ORB_BREAKDOWN | ORB_BREAKOUT | VWAP_REJECTION | VWAP_RECLAIM | None
      plus the evidence (vwap, or_high, or_low, ext_atr, vol_exp, reason).

    Two events, mirrored for BUY:
      ORB  -- a candle CLOSED beyond the 15-min opening range within the last
              FRESH_CANDLES, and price still holds beyond it.
      VWAP -- a candle probed session VWAP and closed back on the trend side
              (rejection), and a later candle closed beyond that candle's extreme
              (confirmation) within the last FRESH_CANDLES.
    Both need: price on the correct side of session VWAP, not extended from
    VWAP (don't chase), and recent volume not fading.

    The daily bias ("is this stock in a downtrend/uptrend") is NOT decided
    here -- this only answers "is NOW a sensible moment", which the
    daily-candle engine cannot.
    """
    cfg = cfg or CONFIG
    sell = action == "SELL"
    n = len(candles or [])
    if n < cfg["MIN_CANDLES"]:
        return {"state": "UNKNOWN", "type": None, "reason": f"only {n} completed 5m candles"}

    vwaps = running_vwap(candles)
    vwap = vwaps[-1]
    if vwap is None:
        return {"state": "UNKNOWN", "type": None, "reason": "no session volume yet"}
    or_high, or_low = opening_range(candles, cfg["OR_CANDLES"])
    last = candles[-1]
    close = last[4]

    ev = {"vwap": round(vwap, 2), "or_high": or_high, "or_low": or_low}

    on_side = close < vwap if sell else close > vwap
    if not on_side:
        return {**ev, "state": "NO_TRIGGER", "type": None, "reason": "price on wrong side of session VWAP"}

    ext = abs(close - vwap) / daily_atr if daily_atr else None
    ev["ext_atr"] = round(ext, 2) if ext is not None else None
    if ext is not None and ext > cfg["MAX_EXTENSION_ATR"]:
        return {**ev, "state": "NO_TRIGGER", "type": None, "reason": f"extended {ext:.2f} ATR from VWAP -- not chasing"}

    vols = [c[5] for c in candles]
    session_avg = sum(vols) / len(vols) if vols else 0
    recent_avg = sum(vols[-3:]) / min(3, len(vols))
    vol_exp = recent_avg / session_avg if session_avg > 0 else None
    ev["vol_exp"] = round(vol_exp, 2) if vol_exp is not None else None
    if vol_exp is not None and vol_exp < cfg["MIN_VOL_EXPANSION"]:
        return {**ev, "state": "NO_TRIGGER", "type": None, "reason": f"recent volume fading ({vol_exp:.2f}x session avg)"}

    fresh = cfg["FRESH_CANDLES"]
    last_idx = n - 1

    # -- Event A: opening-range break ---------------------------------------
    if or_high is not None and n > cfg["OR_CANDLES"]:
        for i in range(cfg["OR_CANDLES"], n):
            beyond = candles[i][4] < or_low if sell else candles[i][4] > or_high
            if beyond:
                held = close < or_low if sell else close > or_high
                if held and (last_idx - i) < fresh:
                    return {**ev, "state": "TRIGGERED", "type": "ORB_BREAKDOWN" if sell else "ORB_BREAKOUT",
                            "reason": f"closed {'below OR low' if sell else 'above OR high'} {last_idx - i} candle(s) ago"}
                break  # first break found was stale (or not held) -- stop scanning

    # -- Event B: VWAP rejection + confirmation ------------------------------
    for j in range(max(0, n - 1 - fresh), n - 1):
        v = vwaps[j]
        if v is None:
            continue
        c = candles[j]
        if sell:
            probed = c[2] >= v * 0.9995 and c[4] < v and c[4] < c[1]
            confirmed = close < c[3]
        else:
            probed = c[3] <= v * 1.0005 and c[4] > v and c[4] > c[1]
            confirmed = close > c[2]
        if probed and confirmed:
            return {**ev, "state": "TRIGGERED", "type": "VWAP_REJECTION" if sell else "VWAP_RECLAIM",
                    "reason": f"VWAP {'rejection' if sell else 'reclaim'} confirmed {last_idx - j} candle(s) ago"}

    return {**ev, "state": "NO_TRIGGER", "type": None, "reason": "no fresh opening-range break or VWAP rejection"}


# -- 5m candle fetch, cached per completed-candle period (same idea as mtf_trend)
_candle_lock = threading.Lock()
_candle_cache = {}  # {symbol: {"period_key": str, "candles": [...]}}
_LOOKBACK_DAYS = 3


def _period_key(now=None, minutes=5):
    now = now or datetime.now()
    bucket = ((now.hour * 60 + now.minute) // minutes) * minutes
    return f"{now.date()}_{bucket}"


def fetch_session_candles(symbol, now=None, history_fn=None):
    """
    Today's COMPLETED 5m candles for an NSE equity symbol, oldest-first, or
    None on any failure/empty response. One Fyers call per symbol per
    5-minute period; every other call inside the period is a memory lookup.
    `history_fn` is injectable for tests (defaults to fyers_client.get_history).
    """
    now = now or datetime.now()
    pkey = _period_key(now)
    with _candle_lock:
        cached = _candle_cache.get(symbol)
        if cached and cached["period_key"] == pkey:
            return cached["candles"]

    if history_fn is None:
        from .fyers_client import get_history
        history_fn = get_history
    try:
        resp = history_fn(f"NSE:{symbol}-EQ", resolution="5",
                          range_from=str((now - timedelta(days=_LOOKBACK_DAYS)).date()),
                          range_to=str(now.date()))
    except Exception as exc:
        print(f"[SniperV3] {symbol} 5m fetch failed: {exc}")
        return None
    if not resp or resp.get("s") != "ok" or not resp.get("candles"):
        return None

    today = now.date()
    now_epoch = now.timestamp()
    rows = sorted((c for c in resp["candles"] if len(c) >= 6), key=lambda c: c[0])
    candles = [c for c in rows
               if datetime.fromtimestamp(c[0]).date() == today and (c[0] + 300) <= now_epoch]
    with _candle_lock:
        _candle_cache[symbol] = {"period_key": pkey, "candles": candles}
    return candles


def trigger_for(symbol, action, daily_atr, now=None, history_fn=None):
    """fetch + evaluate; any failure is UNKNOWN, never an exception."""
    try:
        candles = fetch_session_candles(symbol, now=now, history_fn=history_fn)
        if candles is None:
            return {"state": "UNKNOWN", "type": None, "reason": "5m candles unavailable"}
        return evaluate_trigger(action, candles, daily_atr)
    except Exception as exc:
        print(f"[SniperV3] {symbol} trigger evaluation failed: {exc}")
        return {"state": "UNKNOWN", "type": None, "reason": f"error: {exc}"}


def trigger_blocks(trigger_result, is_held):
    """
    Whether the trigger should reject this candidate. Never blocks a call
    that is already active (a trigger is an ENTRY event, not a hold condition)
    and fails OPEN on UNKNOWN (a data gap is not information -- same
    principle this project already applies to hysteresis).
    """
    if not trigger_enforced() or is_held:
        return False
    return trigger_result.get("state") == "NO_TRIGGER"


_trigger_log_state = {}  # {(date, symbol, action): last_state}


def log_trigger_evidence(log_dir, symbol, action, result, now=None):
    """
    Append-only CSV so the shadow trigger can be scored against outcomes later
    without touching signals_<date>.xlsx's column layout (changing it makes
    excel_logger archive and restart that day's file). Logs only on state
    CHANGE per (symbol, action) per day to keep it small.
    """
    now = now or datetime.now()
    key = (now.strftime("%Y-%m-%d"), symbol, action)
    state = result.get("state")
    if _trigger_log_state.get(key) == state:
        return
    _trigger_log_state[key] = state
    try:
        day_dir = os.path.join(log_dir, now.strftime("%Y-%m-%d"))
        os.makedirs(day_dir, exist_ok=True)
        path = os.path.join(day_dir, f"sniper_v3_trigger_{now.strftime('%Y-%m-%d')}.csv")
        new_file = not os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if new_file:
                w.writerow(["time", "symbol", "action", "state", "type", "vwap", "or_high", "or_low", "ext_atr", "vol_exp", "reason"])
            w.writerow([now.strftime("%H:%M:%S"), symbol, action, state, result.get("type"),
                        result.get("vwap"), result.get("or_high"), result.get("or_low"),
                        result.get("ext_atr"), result.get("vol_exp"), result.get("reason")])
    except Exception as exc:
        print(f"[SniperV3] trigger log write failed (non-fatal): {exc}")


# ---------------------------------------------------------------------------
# Ranking -- decides who gets a SCARCE slot, never whether a signal exists.
# ---------------------------------------------------------------------------
_TRIGGER_QUALITY = {"ORB_BREAKDOWN": 1.0, "ORB_BREAKOUT": 1.0, "VWAP_REJECTION": 0.8, "VWAP_RECLAIM": 0.8}


def _clamp01(x):
    return max(0.0, min(1.0, x))


def rank_score(action, adx, rvol_rel, ctr, trigger_type, rsi):
    """
    Continuous 0-100 replacement for the old tie-heavy 50/65/85 confidence as
    the ORDERING key. Weights are a reasoned prior, NOT a fit: the only
    components with historical support are ADX (win rate rises 57%->73% across
    quartiles) and RSI side. RVOL/cost/trigger are included on first
    principles and every component is returned so a regression can replace
    these weights once enough resolved calls exist.
    """
    comps = {
        "adx": _clamp01(((adx or 20) - 20) / 30.0),
        "rvol": _clamp01(((rvol_rel if rvol_rel is not None else 1.0) - 0.5) / 2.0),
        "cost": _clamp01(1 - (ctr / 0.5)) if ctr is not None else 0.5,
        "trigger": _TRIGGER_QUALITY.get(trigger_type, 0.4),
        "rsi_room": _clamp01(((50 - rsi) if action == "SELL" else (rsi - 50)) / 25.0) if rsi is not None else 0.0,
    }
    weights = {"adx": 0.25, "rvol": 0.25, "cost": 0.20, "trigger": 0.20, "rsi_room": 0.10}
    score = 100.0 * sum(weights[k] * comps[k] for k in weights)
    return round(score, 1), {k: round(v, 2) for k, v in comps.items()}


# ---------------------------------------------------------------------------
# 5. SignalBook -- sticky slots + correlation-aware admission
# ---------------------------------------------------------------------------
def _minutes(dt):
    return dt.hour * 60 + dt.minute


class SignalBook:
    """
    Holds today's live calls. A candidate list goes in each cycle, the list of
    calls to SHOW comes out.

    State per symbol (one symbol = one slot, either direction):
      ACTIVE -- on the list; stays until resolved / timed out / invalidated.
      CLOSED -- left the list today; locked out for the day when SAME_DAY_LOCK.

    Candidates are plain dicts with at least: symbol, action, sector,
    rank_score; optionally sl_hit / furthest_target_hit (resolution) and
    trigger_state.
    """

    def __init__(self, cfg=None):
        self.cfg = cfg or CONFIG
        self.day = None
        self.slots = {}          # {symbol: {...}}
        self.new_times = []      # datetimes of admissions today

    # -- state -------------------------------------------------------------
    def _roll(self, now):
        today = now.strftime("%Y-%m-%d")
        if self.day != today:
            self.day = today
            self.slots = {}
            self.new_times = []

    def seed(self, rows, now=None):
        """Restart-proofing. rows: dicts {symbol, action, exited_at(datetime|None), created_at}."""
        now = now or datetime.now()
        self._roll(now)
        for r in rows:
            sym = r.get("symbol")
            if not sym or sym in self.slots:
                continue
            active = r.get("exited_at") is None and not r.get("resolved")
            self.slots[sym] = {
                "state": "ACTIVE" if active else "CLOSED", "action": r.get("action"),
                "opened_at": r.get("created_at") or now, "last": None,
                "missing": 0, "closed_reason": None if active else "seeded-closed",
            }

    def is_active(self, symbol, action, now=None):
        self._roll(now or datetime.now())
        s = self.slots.get(symbol)
        return bool(s and s["state"] == "ACTIVE" and s["action"] == action)

    def is_locked(self, symbol, now=None):
        self._roll(now or datetime.now())
        s = self.slots.get(symbol)
        return bool(self.cfg["SAME_DAY_LOCK"] and s and s["state"] == "CLOSED")

    def precheck(self, symbol, action, now=None):
        """
        Cheap early rejection BEFORE any option-chain/MTF/futures-OI call is
        spent on a candidate: returns a reason string, or None to proceed.
        An already-active call always proceeds (it is being held, not entered).
        """
        now = now or datetime.now()
        self._roll(now)
        if self.is_active(symbol, action, now):
            return None
        if self.is_locked(symbol, now):
            return "already had a call today (same-day lock)"
        if not (self.cfg["ENTRY_START_MIN"] <= _minutes(now) <= self.cfg["ENTRY_END_MIN"]):
            return "outside new-entry window"
        return None

    def _close(self, sym, reason):
        s = self.slots[sym]
        s["state"], s["closed_reason"], s["last"] = "CLOSED", reason, None

    # -- main entry --------------------------------------------------------
    def select(self, candidates, now=None, trigger_required=False, is_resolved=None):
        """
        Returns (shown_signals, decisions) -- decisions maps symbol->reason for
        non-admitted/closed. `is_resolved(symbol, action) -> bool` reports a
        call whose SL/Target 3 was hit (excel_logger.is_signal_resolved in
        production); only consulted for calls older than a minute, because a
        just-admitted call has no logged row yet.
        """
        cfg = self.cfg
        now = now or datetime.now()
        self._roll(now)
        by_sym = {}
        for c in candidates:
            # one candidate per symbol; keep the higher-ranked if both directions appear
            prev = by_sym.get(c["symbol"])
            if prev is None or c.get("rank_score", 0) > prev.get("rank_score", 0):
                by_sym[c["symbol"]] = c
        decisions = {}
        shown = []

        # 1. maintain ACTIVE slots
        for sym, s in list(self.slots.items()):
            if s["state"] != "ACTIVE":
                continue
            cand = by_sym.get(sym)
            age_min = (now - s["opened_at"]).total_seconds() / 60.0 if s.get("opened_at") else 0
            if cand is not None and cand["action"] != s["action"]:
                self._close(sym, "direction-flipped")
                decisions[sym] = "closed: direction flipped"
                continue
            if (cand is not None and (cand.get("sl_hit") or (cand.get("furthest_target_hit") or 0) >= 3)) or \
                    (is_resolved is not None and age_min >= 1.0 and is_resolved(sym, s["action"])):
                self._close(sym, "resolved")
                decisions[sym] = "closed: resolved (SL/Target 3)"
                continue
            if age_min > cfg["MAX_HOLD_MIN"]:
                self._close(sym, "time-stop")
                decisions[sym] = f"closed: held >{cfg['MAX_HOLD_MIN']}min"
                continue
            if cand is None:
                s["missing"] += 1
                if s["missing"] > cfg["MISSING_GRACE_CYCLES"] or s["last"] is None:
                    self._close(sym, "invalidated")
                    decisions[sym] = "closed: dropped by upstream gates"
                    continue
                shown.append({**s["last"], "carried_over": True})
                continue
            s["missing"] = 0
            s["last"] = cand
            shown.append(cand)

        # 2. admit new calls
        n_active = len(shown)
        per_dir = {"BUY": 0, "SELL": 0}
        per_sector = {}
        for x in shown:
            per_dir[x["action"]] = per_dir.get(x["action"], 0) + 1
            per_sector[x.get("sector")] = per_sector.get(x.get("sector"), 0) + 1

        mins = _minutes(now)
        window_open = cfg["ENTRY_START_MIN"] <= mins <= cfg["ENTRY_END_MIN"]
        recent_new = [t for t in self.new_times if (now - t).total_seconds() < 1800]

        fresh = [c for sym, c in by_sym.items()
                 if not (sym in self.slots and self.slots[sym]["state"] == "ACTIVE")]
        fresh.sort(key=lambda c: c.get("rank_score", 0), reverse=True)
        for c in fresh:
            sym, act, sec = c["symbol"], c["action"], c.get("sector")
            if sym in decisions:   # closed earlier this very cycle -- keep that reason, don't re-admit
                continue
            if cfg["SAME_DAY_LOCK"] and sym in self.slots and self.slots[sym]["state"] == "CLOSED":
                decisions[sym] = "locked: already had a call today"
            elif not window_open:
                decisions[sym] = "outside entry window"
            elif trigger_required and c.get("trigger_state") == "NO_TRIGGER":
                decisions[sym] = "no intraday trigger yet"
            elif n_active >= cfg["MAX_ACTIVE"]:
                decisions[sym] = "book full"
            elif per_dir.get(act, 0) >= cfg["MAX_ACTIVE_PER_DIRECTION"]:
                decisions[sym] = f"{act} cap reached"
            elif sec is not None and per_sector.get(sec, 0) >= cfg["MAX_ACTIVE_PER_SECTOR"]:
                decisions[sym] = f"sector cap reached ({sec})"
            elif len(recent_new) >= cfg["MAX_NEW_PER_30MIN"]:
                decisions[sym] = "new-call budget used (30 min)"
            else:
                self.slots[sym] = {"state": "ACTIVE", "action": act, "opened_at": now,
                                   "last": c, "missing": 0, "closed_reason": None}
                self.new_times.append(now)
                recent_new.append(now)
                n_active += 1
                per_dir[act] = per_dir.get(act, 0) + 1
                per_sector[sec] = per_sector.get(sec, 0) + 1
                shown.append(c)
        return shown, decisions


_BOOK = SignalBook()


def get_book():
    return _BOOK
