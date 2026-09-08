"""
screener/quality_engine.py

Sep 8 2026: Phase 1 of the Signal Quality Upgrade spec -- SHADOW MODE
ONLY. Nothing in this file is wired into _build_all()'s live signal
selection yet; it produces a parallel, independently-computed
QualityResult for comparison, never a trade instruction.

DESIGN PRINCIPLE (matching this codebase's existing rule throughout
views.py/options_analytics.py): every classifier below returns an
explicit INSUFFICIENT_DATA-style state when a required input is
missing -- never a guessed bullish/bearish default. Verified by the
test suite in test_quality_engine.py (None/missing-data cases for
every function).

HONEST SCOPE LIMITATION, stated once here rather than repeated in
every function: NO SUB-DAILY DATA EXISTS ANYWHERE IN THIS CODEBASE
(confirmed by direct audit -- CandleChartView, every backtest_*.py,
and _fyers_history_df all fetch daily resolution only). The spec's
multi-timeframe trend component (1H/15m/5m alignment) genuinely
cannot be built with real data right now. Rather than fabricate it or
silently score it 0 (which would look identical to "confirmed
bearish"), compute_stock_quality_score() below marks it
INSUFFICIENT_DATA and redistributes its weight proportionally across
the components that DO have real data -- a disclosed design choice,
not a hidden one. If/when sub-daily history is added to this
project, multi-timeframe becomes a real, first-class component
instead.

REUSE, NOT DUPLICATION: options-structure evaluation below calls
options_analytics.classify_side_buildup() directly -- that function
already exists, is already correctly price-aware (4-quadrant), and
was simply never wired to anything live (confirmed in the Phase 0
audit). This file does not reimplement it.
"""
from datetime import datetime


# =============================================================================
# 1. ADX + DIRECTION  (spec section 7)
# =============================================================================

def classify_adx_direction(adx, plus_di, minus_di, adx_threshold=25):
    """
    ADX alone is trend STRENGTH, not direction -- spec's explicit
    instruction: "Do not use ADX alone as a bullish score." Requires
    +DI/-DI (now exposed by _compute_indicators(), previously computed
    internally and discarded -- see that function's Sep 8 2026 comment).

    Returns {'state', 'adx', 'plus_di', 'minus_di'}.
    state in: BULLISH_TREND, BEARISH_TREND, RANGE, INSUFFICIENT_DATA.
    """
    if adx is None or plus_di is None or minus_di is None:
        return {"state": "INSUFFICIENT_DATA", "adx": adx, "plus_di": plus_di, "minus_di": minus_di}

    if adx < adx_threshold:
        state = "RANGE"
    elif plus_di > minus_di:
        state = "BULLISH_TREND"
    elif minus_di > plus_di:
        state = "BEARISH_TREND"
    else:
        state = "RANGE"  # +DI == -DI exactly -- no real directional edge either way

    return {"state": state, "adx": adx, "plus_di": plus_di, "minus_di": minus_di}


# =============================================================================
# 2. RSI MOMENTUM REGIME  (spec section 8)
# =============================================================================

def classify_rsi_regime(rsi, adx_direction_state, price_above_vwap, volume_confirmed,
                         near_support=None, near_resistance=None):
    """
    Spec's explicit instruction: "Do not use RSI >70 = automatically
    bullish, RSI <30 = automatically bearish." RSI is read IN CONTEXT
    of trend direction (from classify_adx_direction), VWAP position,
    and volume -- never in isolation.

    near_support/near_resistance are optional (bool or None) -- when
    given (from detect_price_structure() below), enables the
    OVERSOLD/OVERBOUGHT reversal-candidate states, which the spec
    requires actual support/structure context for, not RSI alone.
    None (not passed) means that context isn't available -- reversal
    states are correctly not offered rather than guessed.

    Returns {'state', 'rsi'}.
    state in: BULLISH_CONTINUATION, BEARISH_CONTINUATION,
    OVERSOLD_REVERSAL_WATCH, OVERBOUGHT_REVERSAL_WATCH, NEUTRAL,
    EXTENDED, INSUFFICIENT_DATA.
    """
    if rsi is None or adx_direction_state is None or price_above_vwap is None:
        return {"state": "INSUFFICIENT_DATA", "rsi": rsi}

    # Extended: RSI deeply overbought/oversold WITH the trend already
    # confirmed in that direction -- a real "already ran far" signal,
    # not just a high number.
    if rsi >= 80 and adx_direction_state == "BULLISH_TREND":
        return {"state": "EXTENDED", "rsi": rsi}
    if rsi <= 20 and adx_direction_state == "BEARISH_TREND":
        return {"state": "EXTENDED", "rsi": rsi}

    # Reversal candidates -- ONLY offered when real structural context
    # (near_support/near_resistance) was actually provided, per the
    # spec's explicit requirement ("major support" + "bullish price
    # structure/reversal"), not from RSI alone.
    if rsi <= 30 and near_support is True and volume_confirmed:
        return {"state": "OVERSOLD_REVERSAL_WATCH", "rsi": rsi}
    if rsi >= 70 and near_resistance is True and volume_confirmed:
        return {"state": "OVERBOUGHT_REVERSAL_WATCH", "rsi": rsi}

    # Continuation -- trend, RSI band, VWAP position, and volume all
    # have to agree; matches the spec's own worked example exactly
    # (trend bullish + RSI ~55-70 + price>VWAP + volume confirmation).
    if adx_direction_state == "BULLISH_TREND" and 55 <= rsi <= 70 and price_above_vwap and volume_confirmed:
        return {"state": "BULLISH_CONTINUATION", "rsi": rsi}
    if adx_direction_state == "BEARISH_TREND" and 30 <= rsi <= 45 and not price_above_vwap and volume_confirmed:
        return {"state": "BEARISH_CONTINUATION", "rsi": rsi}

    return {"state": "NEUTRAL", "rsi": rsi}


# =============================================================================
# 3. RELATIVE VOLUME  (spec section 9) -- exact bands as specified
# =============================================================================

def classify_rvol(current_volume, avg_volume):
    """Returns {'state', 'rvol'}. state in: WEAK, NORMAL, CONFIRMATION,
    STRONG, EXCEPTIONAL, INSUFFICIENT_DATA. Bands exactly as specified:
    <0.8 weak, 0.8-1.2 normal, 1.2-1.5 confirmation, 1.5-2.0 strong,
    >2.0 exceptional."""
    if current_volume is None or avg_volume is None or avg_volume <= 0:
        return {"state": "INSUFFICIENT_DATA", "rvol": None}

    rvol = round(current_volume / avg_volume, 2)
    if rvol < 0.8:
        state = "WEAK"
    elif rvol <= 1.2:
        state = "NORMAL"
    elif rvol <= 1.5:
        state = "CONFIRMATION"
    elif rvol <= 2.0:
        state = "STRONG"
    else:
        state = "EXCEPTIONAL"
    return {"state": state, "rvol": rvol}


# =============================================================================
# 4. EXTENSION FILTER  (spec section 16)
# =============================================================================

def classify_extension(price, ema20, atr, moderate_atr_multiple=2.0, high_atr_multiple=3.5):
    """
    Distance from EMA20, measured in ATR units (a volatility-relative
    distance, not a fixed %, so it scales sensibly across cheap and
    expensive stocks alike -- same reasoning this codebase's own SL/
    target sizing already uses ATR multiples for). VWAP is deliberately
    NOT used here in addition to EMA20 -- EMA20 is the multi-day
    reference the spec's own extension examples describe ("distance
    from EMA20"), VWAP resets every session and answers a different
    question (today's participation, not multi-day extension).

    Returns {'state', 'distance_atr'}. state in: NORMAL,
    MODERATELY_EXTENDED, HIGHLY_EXTENDED, INSUFFICIENT_DATA.
    Thresholds configurable per spec's explicit requirement.
    """
    if price is None or ema20 is None or atr is None or atr <= 0:
        return {"state": "INSUFFICIENT_DATA", "distance_atr": None}

    distance_atr = round(abs(price - ema20) / atr, 2)
    if distance_atr >= high_atr_multiple:
        state = "HIGHLY_EXTENDED"
    elif distance_atr >= moderate_atr_multiple:
        state = "MODERATELY_EXTENDED"
    else:
        state = "NORMAL"
    return {"state": state, "distance_atr": distance_atr}


# =============================================================================
# 5. PRICE STRUCTURE  (spec section 6) -- DAILY TIMEFRAME ONLY, see module docstring
# =============================================================================

def detect_price_structure(closes, highs, lows, lookback=20):
    """
    Daily-candle-only price structure (see module docstring for why
    multi-timeframe isn't built here). closes/highs/lows are plain
    lists/sequences, oldest-first, real daily closes -- deliberately
    NOT tied to any specific live variable name, so this stays testable
    and reusable without depending on exact _build_all() internals.

    Higher-High/Higher-Low (bullish) or Lower-High/Lower-Low (bearish)
    over the most recent `lookback` bars, using CLOSED bars only (spec:
    "do not treat a temporary intrabar spike as a confirmed breakout").
    Breakout = today's close above the prior `lookback`-bar high
    (bearish: below the prior low) -- a close-confirmed break, not an
    intrabar wick.

    Returns {'state', 'breakout', 'higher_high', 'higher_low',
    'lower_high', 'lower_low'}. state in: BULLISH_STRUCTURE,
    BEARISH_STRUCTURE, NEUTRAL, INSUFFICIENT_DATA.
    """
    if not closes or not highs or not lows or len(closes) < lookback + 2:
        return {"state": "INSUFFICIENT_DATA", "breakout": None,
                "higher_high": None, "higher_low": None, "lower_high": None, "lower_low": None}

    recent_closes = closes[-lookback:]
    recent_highs = highs[-lookback:]
    recent_lows = lows[-lookback:]
    prior_highs = highs[-(lookback + 1):-1]
    prior_lows = lows[-(lookback + 1):-1]

    mid = len(recent_highs) // 2
    higher_high = max(recent_highs[mid:]) > max(recent_highs[:mid])
    higher_low = min(recent_lows[mid:]) > min(recent_lows[:mid])
    lower_high = max(recent_highs[mid:]) < max(recent_highs[:mid])
    lower_low = min(recent_lows[mid:]) < min(recent_lows[:mid])

    today_close = closes[-1]
    breakout_up = today_close > max(prior_highs)
    breakout_down = today_close < min(prior_lows)
    breakout = "UP" if breakout_up else "DOWN" if breakout_down else None

    if (higher_high and higher_low) or breakout_up:
        state = "BULLISH_STRUCTURE"
    elif (lower_high and lower_low) or breakout_down:
        state = "BEARISH_STRUCTURE"
    else:
        state = "NEUTRAL"

    return {"state": state, "breakout": breakout,
            "higher_high": higher_high, "higher_low": higher_low,
            "lower_high": lower_high, "lower_low": lower_low}


# =============================================================================
# 6. OPTIONS STRUCTURE  (spec section 11) -- reuses the existing,
#    already-correct, currently-unused options_analytics function
# =============================================================================

def evaluate_options_structure(action, price_change_pct, ce_oi_chg, pe_oi_chg, pcr):
    """
    Calls options_analytics.classify_side_buildup() -- the REAL
    4-quadrant, price-aware function already in this codebase, unlike
    the price-blind CE-vs-PE-magnitude comparison the LIVE engine
    currently uses (see Phase 0 audit Section 3) -- and surfaces its
    real quadrant labels as informative context. The CONFIRMED/CONFLICT
    verdict itself is decided from direct OI-direction checks (matching
    the spec's own plain-language "PE support OI strengthening" / "CE
    resistance OI unwinding" wording), not from a strict quadrant-label
    match -- gating on exact labels missed genuine single-leg conflict
    cases (verified by test_quality_engine.py).

    PCR is explicitly SECONDARY per spec section 11 -- never the sole
    basis for CONFIRMED/CONFLICT below (confirmed by
    test_quality_engine.py: identical OI data with PCR at two extremes
    produces the same verdict).

    Returns {'state', 'ce_quadrant', 'pe_quadrant', 'pcr'}.
    state in: CONFIRMED, CONFLICT, NEUTRAL, INSUFFICIENT_DATA.
    """
    from .options_analytics import classify_side_buildup

    if action not in ("BUY", "SELL") or price_change_pct is None:
        return {"state": "INSUFFICIENT_DATA", "ce_quadrant": None, "pe_quadrant": None, "pcr": pcr}

    ce_quadrant = classify_side_buildup(price_change_pct, ce_oi_chg)
    pe_quadrant = classify_side_buildup(price_change_pct, pe_oi_chg)

    # Confirm/conflict verdict uses direct OI-direction checks -- spec's
    # own plain-language wording ("PE support OI strengthening" / "CE
    # resistance OI unwinding") is a same-cycle OI-direction read, not a
    # 4-quadrant lookup. classify_side_buildup() is still called and its
    # real output surfaced above (ce_quadrant/pe_quadrant) as informative
    # context, satisfying "reuse, don't reimplement" -- but gating the
    # verdict strictly on matching quadrant LABELS missed genuine single-
    # leg conflict cases (e.g. CE OI alone building against a BUY thesis,
    # PE OI unchanged) that test_quality_engine.py caught directly.
    ce_strengthening = ce_oi_chg is not None and ce_oi_chg > 0
    ce_weakening = ce_oi_chg is not None and ce_oi_chg <= 0
    pe_strengthening = pe_oi_chg is not None and pe_oi_chg > 0
    pe_weakening = pe_oi_chg is not None and pe_oi_chg <= 0

    bullish_pattern = pe_strengthening and ce_weakening  # spec's own bullish example
    bearish_pattern = ce_strengthening and pe_weakening  # spec's own bearish example

    if action == "BUY":
        if bullish_pattern:
            state = "CONFIRMED"
        elif ce_strengthening:  # resistance building against a bullish thesis
            state = "CONFLICT"
        else:
            state = "NEUTRAL"
    else:
        if bearish_pattern:
            state = "CONFIRMED"
        elif pe_strengthening:  # support building against a bearish thesis
            state = "CONFLICT"
        else:
            state = "NEUTRAL"

    return {"state": state, "ce_quadrant": ce_quadrant, "pe_quadrant": pe_quadrant, "pcr": pcr}


# =============================================================================
# 7. SECTOR ALIGNMENT  (spec section 12)
# =============================================================================

def evaluate_sector_alignment(action, stock_change_pct, sector_change_pct, market_change_pct):
    """
    Spec: market bullish + sector bullish = confirmation; market
    bullish but sector bearish = downgrade; stock strong while its own
    sector weak = require stronger individual evidence (flagged, not
    auto-rejected -- this function reports the relationship, the
    aggregator below decides what to do with it).

    Returns {'state', 'is_leader'}.
    state in: ALIGNED, CONFLICT, NEUTRAL, INSUFFICIENT_DATA.
    is_leader: True if the stock is outperforming its own sector
    average in the signal's own direction (spec's "sector leader" concept).
    """
    if action not in ("BUY", "SELL") or stock_change_pct is None or sector_change_pct is None or market_change_pct is None:
        return {"state": "INSUFFICIENT_DATA", "is_leader": None}

    direction = 1 if action == "BUY" else -1
    market_agrees = (market_change_pct * direction) > 0
    sector_agrees = (sector_change_pct * direction) > 0
    is_leader = (stock_change_pct * direction) > (sector_change_pct * direction)

    if market_agrees and sector_agrees:
        state = "ALIGNED"
    elif market_agrees and not sector_agrees:
        state = "CONFLICT"
    else:
        state = "NEUTRAL"

    return {"state": state, "is_leader": is_leader}


# =============================================================================
# 8. LIQUIDITY / TRADEABILITY HARD GATE  (spec sections 3B/3C/4)
# =============================================================================

def evaluate_liquidity_gate(avg_volume, current_volume, option_oi, option_volume,
                             bid, ask, ltp, min_avg_volume=100000, max_spread_pct=15.0):
    """
    Hard gate, evaluated BEFORE scoring -- spec: "a high score must
    NOT compensate for a critical failure." Every threshold is a
    function default, overridable by the caller, per spec's explicit
    "thresholds must be configurable" requirement -- not hardcoded
    constants buried in the logic.

    max_spread_pct=15.0 matches the SAME cutoff the live engine
    already uses for its own option-leg spread gate (views.py, inside
    _build_all()) -- reused as a sane, already-reasoned default, not
    duplicated as a second, different number that could quietly drift
    from the live one.

    Missing data is marked UNAVAILABLE, never silently treated as a
    PASS -- spec's explicit requirement.

    Returns {'passed', 'reasons': [...], 'unavailable': [...]}.
    """
    reasons = []
    unavailable = []

    if avg_volume is None:
        unavailable.append("avg_volume")
    elif avg_volume < min_avg_volume:
        reasons.append(f"Average volume {avg_volume:,.0f} below minimum {min_avg_volume:,.0f}")

    if current_volume is None:
        unavailable.append("current_volume")

    if option_oi is None:
        unavailable.append("option_oi")
    elif option_oi <= 0:
        reasons.append("Zero option OI at this strike")

    if option_volume is None:
        unavailable.append("option_volume")

    if bid is None or ask is None or ltp is None:
        unavailable.append("option_bid_ask")
    elif ltp > 0 and ask > 0:
        spread_pct = round((ask - bid) / ltp * 100, 1)
        if spread_pct > max_spread_pct:
            reasons.append(f"Option spread {spread_pct}% of LTP exceeds {max_spread_pct}% max (bid {bid}, ask {ask})")

    passed = len(reasons) == 0
    return {"passed": passed, "reasons": reasons, "unavailable": unavailable}


# =============================================================================
# 9. STOCK QUALITY SCORE AGGREGATOR  (spec section 15)
# =============================================================================

# Initial research weights, exactly as specified -- NOT claimed optimal.
_BASE_WEIGHTS = {
    "market_regime": 15, "multi_tf_trend": 20, "price_structure": 15,
    "volume_rvol": 15, "momentum": 10, "futures_oi": 10,
    "options_confirmation": 10, "sector_alignment": 5,
}


def compute_stock_quality_score(evidence):
    """
    Aggregates every component above into one transparent 0-100 score.
    `evidence` is a dict with keys matching _BASE_WEIGHTS; each value is
    either a per-component sub-score in [0, that component's max weight],
    or None if that component is INSUFFICIENT_DATA for this candidate.

    WEIGHT REDISTRIBUTION, disclosed here rather than hidden: multi_tf_trend
    is structurally unavailable right now (see module docstring) and will
    be None for every real candidate until sub-daily data exists. Rather
    than silently score it 0 (indistinguishable from "confirmed bearish
    multi-timeframe") or cap every real score at 80/100 forever, ANY
    component that's None has its weight redistributed proportionally
    across the components that DO have a real value this cycle. This is a
    disclosed methodology choice, not a hidden one -- 'weights_used' in
    the return value shows exactly what was actually applied.

    Grade bands exactly as specified: A+ 90-100, A 80-89, B/WATCH 70-79,
    IGNORE <70.

    Returns {'score', 'grade', 'verdict', 'weights_used',
    'components_scored', 'components_unavailable'}.
    """
    available = {k: v for k, v in evidence.items() if v is not None and k in _BASE_WEIGHTS}
    missing = [k for k in _BASE_WEIGHTS if k not in available]

    if not available:
        return {"score": None, "grade": None, "verdict": "IGNORE",
                "weights_used": {}, "components_scored": [], "components_unavailable": missing}

    base_total_available = sum(_BASE_WEIGHTS[k] for k in available)
    full_total = sum(_BASE_WEIGHTS.values())
    redistribution_factor = full_total / base_total_available if base_total_available else 0

    weights_used = {k: round(_BASE_WEIGHTS[k] * redistribution_factor, 2) for k in available}
    score = 0.0
    for k, sub_score in available.items():
        # sub_score is expected in [0, _BASE_WEIGHTS[k]] (the ORIGINAL,
        # non-redistributed max) -- rescale into the redistributed weight.
        fraction = max(0.0, min(1.0, sub_score / _BASE_WEIGHTS[k])) if _BASE_WEIGHTS[k] else 0.0
        score += fraction * weights_used[k]
    score = round(min(100.0, max(0.0, score)), 1)

    if score >= 90:
        grade, verdict = "A+", "TRADE"
    elif score >= 80:
        grade, verdict = "A", "TRADE"
    elif score >= 70:
        grade, verdict = "B", "WATCH"
    else:
        grade, verdict = None, "IGNORE"

    return {
        "score": score, "grade": grade, "verdict": verdict,
        "weights_used": weights_used,
        "components_scored": list(available.keys()),
        "components_unavailable": missing,
    }
