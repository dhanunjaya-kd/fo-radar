"""
screener/index_signal.py

Aug 27 2026: turns a confirmed Index Tracker Bias (NIFTY/BANKNIFTY) into
an actual tradeable options call -- which strike, PE or CE, Entry/SL/
Target1-3 in real premium terms, same shape as the existing per-stock
Live Signals.

Deliberately a SEPARATE module from index_tracker.py (owns Bias/
snapshot logging) and from views.py's stock-signal engine in
_build_all() -- but reuses that engine's EXACT SL/Target math: an
ATR-sized move on the underlying, translated to premium via the
option's own delta, with SL weighted 1.4x (theta/gamma work against an
adverse move too, so straight delta alone understates real option
risk). Same math, so index calls and stock calls behave consistently --
just re-derived here rather than importing from views.py, since that
module's version is entangled with per-stock scoring/OI-confirmation
logic this doesn't need.

Keeps its own much simpler freeze-on-first-appearance cache rather than
routing through excel_logger.py's stock-specific (symbol, action)
locking, which is built around a 200+ symbol universe. An index call
only ever has 2 possible names (NIFTY/BANKNIFTY), so a small dict
scoped to just this module is simpler and doesn't risk the
already-working stock-locking logic.

STRIKE SELECTION (per explicit request, Aug 27 2026): NOT the ATM
strike Index Tracker itself already snapshots -- the OI WALL the vote-
based Bias just confirmed. Bearish -> PE at Resistance (the highest
Call-OI strike, where call writers are actively defending);
Bullish -> CE at Support (the highest Put-OI strike). The bet is on
rejection from the wall the OI is defending, not a plain at-the-money
bet.

HONEST LIMITATIONS:
- Strike selection was chosen at the trader's explicit direction, not
  derived/backtested -- same "watch and retune" status as the Bias vote
  system it sits on top of. A wall can sit meaningfully far from spot,
  meaning a deep-OTM strike with small delta and a cheap premium (and
  correspondingly small absolute SL/Target Rupee amounts) -- the delta
  floor below (0.05) keeps the math from blowing up, but doesn't make
  a deep-OTM bet the same risk profile as a near-ATM one.
- This can't be retroactively backtested against past logged data --
  needs real accumulated calls, watched going forward from here, same
  as everything else new in this project.
"""
from datetime import datetime

# {index_name: {...locked call dict...}} -- see module docstring for why
# this is separate from both index_tracker.py's flip-tracking dicts and
# excel_logger.py's stock-signal locking.
_locked_calls = {}


def _bias_action(bias):
    """Bullish family -> BUY (CE side), Bearish family -> SELL (PE
    side). Neutral, None, or unrecognized -> None, no call."""
    if not bias:
        return None
    if bias.startswith("Bullish"):
        return "BUY"
    if bias.startswith("Bearish"):
        return "SELL"
    return None


def generate_index_call(index_name, bias, oi, spot_or_fut, atr):
    """
    Builds (or returns the already-locked) trade call for one index
    this cycle. Returns None if Bias is Neutral, or if the target wall
    strike has no live premium/delta in the option chain right now --
    never guesses a price.

    oi: the SAME option-chain analytics dict index_tracker.py's
    snapshot_index()/snapshot_commodity() already fetched this cycle
    (read via get_last_oi_snapshot() -- no second Fyers call here).
    Needs oi['rows'] (per-strike ltp/delta already enriched by
    options_analytics.enrich_rows_with_iv_greeks), oi['support'],
    oi['resistance'].

    spot_or_fut: current index price (Spot for NIFTY/BANKNIFTY).

    atr: the index's own ATR in points, computed the same way
    views.py's _compute_indicators() computes it for stocks. Caller's
    responsibility to fetch/cache this -- kept out of this function so
    it stays a pure, easily-testable transform with no Fyers calls of
    its own.
    """
    action = _bias_action(bias)
    if action is None:
        _locked_calls.pop(index_name, None)
        return None

    locked = _locked_calls.get(index_name)
    if locked and locked.get("action") == action and not locked.get("sl_hit") and locked.get("furthest_target_hit", 0) < 3:
        return locked

    opt_side = "PE" if action == "SELL" else "CE"
    strike = oi.get("resistance") if action == "SELL" else oi.get("support")
    if strike is None:
        return None

    row = next((r for r in oi.get("rows", []) if r["strike"] == strike), None)
    leg = (row or {}).get(opt_side.lower()) if row else None
    if not leg or not leg.get("ltp"):
        return None

    premium_entry = leg["ltp"]
    delta_for_premium = leg.get("delta")
    if delta_for_premium is None or atr is None or spot_or_fut is None:
        return None

    if action == "BUY":
        idx_sl = spot_or_fut - atr * 0.4
        idx_t1 = spot_or_fut + atr * 0.5
        idx_t2 = spot_or_fut + atr * 0.8
        idx_t3 = spot_or_fut + atr * 1.2
    else:
        idx_sl = spot_or_fut + atr * 0.4
        idx_t1 = spot_or_fut - atr * 0.5
        idx_t2 = spot_or_fut - atr * 0.8
        idx_t3 = spot_or_fut - atr * 1.2

    d = max(abs(delta_for_premium), 0.05)
    entry = round(premium_entry, 2)
    sl = round(max(0.05, premium_entry - d * abs(spot_or_fut - idx_sl) * 1.4), 2)
    t1 = round(premium_entry + d * abs(idx_t1 - spot_or_fut), 2)
    t2 = round(premium_entry + d * abs(idx_t2 - spot_or_fut), 2)
    t3 = round(premium_entry + d * abs(idx_t3 - spot_or_fut), 2)

    # Quantity is an exchange-defined number of units per lot. Never derive
    # it from an arbitrary Rs 50,000 capital assumption. The resolver reads
    # the current NSE contract file and therefore tracks lot-size revisions.
    try:
        from .lot_size_resolver import get_lot_size
        lot_size = get_lot_size(index_name)
    except Exception as exc:
        print(f"[IndexSignal] Lot-size lookup failed for {index_name}: {exc}")
        lot_size = None
    if not lot_size or lot_size <= 0:
        # No real lot size -> no tradeable quantity. Do not silently replace
        # it with a fabricated unit count.
        print(f"[IndexSignal] No valid lot size for {index_name}; skipping call")
        return None
    qty = int(lot_size)

    risk = abs(entry - sl)
    rr = round(abs(t1 - entry) / risk, 2) if risk else 1.5

    call = {
        "index": index_name, "action": action,
        "recommendation": f"{action} {opt_side} — ₹{strike} STRIKE",
        "strike": strike, "opt_side": opt_side,
        "wall_type": "Resistance" if action == "SELL" else "Support",
        "entry": entry, "sl": sl,
        "target1": t1, "target2": t2, "target3": t3,
        "quantity": qty, "lot_size": lot_size, "risk_reward": rr,
        "option_symbol": leg.get("symbol"),
        "bias": bias, "spot_at_entry": spot_or_fut,
        "sl_hit": False, "furthest_target_hit": 0,
        "outcome_status": "Open",
        "generated_at": datetime.now().isoformat(),
    }
    _locked_calls[index_name] = call
    return call


def check_call_outcome(index_name, current_premium):
    """
    Same SL/Target-hit tracking concept the stock engine's
    excel_logger.check_outcomes() already does, scoped to just the one
    locked call per index. Call each cycle with the current LTP for the
    locked call's exact option_symbol -- caller's responsibility to
    fetch that (this function does no fetching itself, pure state
    update). Mutates and returns the updated call, or None/the
    unmodified call if nothing's locked or no premium was given.

    NOTE: this is always a BOUGHT option regardless of BUY/SELL
    direction (BUY->CE bought, SELL->PE bought) -- so premium always
    falls toward SL on an adverse move and rises toward targets on a
    favorable one, same check either way. No action-based branching
    needed here, unlike generate_index_call()'s SL/Target sizing above.
    """
    call = _locked_calls.get(index_name)
    if not call or current_premium is None:
        return call

    if current_premium <= call["sl"]:
        call["sl_hit"] = True
    else:
        for i, t in enumerate([call["target1"], call["target2"], call["target3"]], start=1):
            if current_premium >= t:
                call["furthest_target_hit"] = i

    call["outcome_status"] = (
        "SL Hit" if call["sl_hit"]
        else (f"Target {call['furthest_target_hit']} Hit" if call["furthest_target_hit"] else "Open")
    )
    return call


def get_locked_call(index_name):
    """Read-only accessor -- None if nothing's currently locked for this
    index (Bias is Neutral, or nothing's fired yet this session)."""
    return _locked_calls.get(index_name)
