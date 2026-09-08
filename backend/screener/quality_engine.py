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


def compute_stock_quality_score(evidence, hard_gate_failures=None):
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

    hard_gate_failures: Sep 8 2026 addition -- optional list of reason
    strings from hard gates evaluated BEFORE scoring (typically
    evaluate_liquidity_gate()'s own 'reasons' list). Spec section 3,
    stated as plainly as anything in the whole document: "Hard gates
    must be evaluated BEFORE the score. A high score must NOT
    compensate for a critical failure." When non-empty, verdict is
    FORCED to IGNORE regardless of the computed score -- the score
    itself is still computed and returned (useful for comparison: "how
    good would this have looked if liquidity weren't a problem"), but
    it can never override a real gate failure. This was a real,
    genuine gap until this change: evaluate_liquidity_gate() existed
    and was tested in isolation but was never actually wired to affect
    a verdict anywhere.

    Grade bands exactly as specified: A+ 90-100, A 80-89, B/WATCH 70-79,
    IGNORE <70.

    Returns {'score', 'grade', 'verdict', 'weights_used',
    'components_scored', 'components_unavailable', 'hard_gate_failures'}.
    """
    hard_gate_failures = hard_gate_failures or []
    available = {k: v for k, v in evidence.items() if v is not None and k in _BASE_WEIGHTS}
    missing = [k for k in _BASE_WEIGHTS if k not in available]

    if not available:
        return {"score": None, "grade": None, "verdict": "IGNORE",
                "weights_used": {}, "components_scored": [], "components_unavailable": missing,
                "hard_gate_failures": hard_gate_failures}

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

    if hard_gate_failures:
        # The literal spec requirement -- score/grade are left visible
        # above for comparison, but the verdict itself cannot be
        # rescued by a good score once a real hard gate has failed.
        verdict = "IGNORE"
        grade = None

    return {
        "score": score, "grade": grade, "verdict": verdict,
        "weights_used": weights_used,
        "components_scored": list(available.keys()),
        "components_unavailable": missing,
        "hard_gate_failures": hard_gate_failures,
    }


# =============================================================================
# 10. INDEX QUALITY ENGINE  (spec section 13) -- 5 evidence groups, 100 points
# =============================================================================

# Initial research weights, exactly as specified -- NOT claimed optimal.
_INDEX_WEIGHTS = {
    "price_structure": 25, "futures_oi": 20, "options_structure": 25,
    "breadth": 15, "vix": 15,
}


def evaluate_index_breadth(index_direction, advances_pct, declines_pct):
    """
    Spec section 13, BREADTH: strong index move + weak breadth ->
    downgrade; strong index move + strong breadth -> confirmation.
    index_direction: 'UP' or 'DOWN' (the index's own move this cycle).

    Returns {'state'}. state in: CONFIRMED, WEAK, NEUTRAL, INSUFFICIENT_DATA.
    """
    if index_direction not in ("UP", "DOWN") or advances_pct is None or declines_pct is None:
        return {"state": "INSUFFICIENT_DATA"}

    if index_direction == "UP":
        if advances_pct >= 60:
            return {"state": "CONFIRMED"}
        if advances_pct <= 40:
            return {"state": "WEAK"}
    else:
        if declines_pct >= 60:
            return {"state": "CONFIRMED"}
        if declines_pct <= 40:
            return {"state": "WEAK"}
    return {"state": "NEUTRAL"}


def evaluate_index_vix(index_direction, vix_change_pct):
    """
    Spec section 13, VIX: context/risk modifier, never a standalone
    direction signal -- this function only ever describes the
    ENVIRONMENT (healthy vs cautionary), never BULLISH/BEARISH itself.

    Returns {'state'}. state in: SUPPORTIVE, CAUTION, NEUTRAL, INSUFFICIENT_DATA.
    SUPPORTIVE: VIX falling/stable while trending with the index's move
    (spec's "bullish index + falling/stable VIX -> healthier environment",
    and symmetrically for a bearish move with volatility expansion, which
    the spec calls "stronger risk-off context" -- also treated as
    supportive of THAT direction, not of trading in general).
    CAUTION: VIX expanding sharply against a bullish move.
    """
    if index_direction not in ("UP", "DOWN") or vix_change_pct is None:
        return {"state": "INSUFFICIENT_DATA"}

    if index_direction == "UP":
        if vix_change_pct <= 2.0:
            return {"state": "SUPPORTIVE"}
        if vix_change_pct >= 8.0:
            return {"state": "CAUTION"}
    else:
        if vix_change_pct >= 5.0:
            return {"state": "SUPPORTIVE"}  # spec: volatility expansion = stronger risk-off context
    return {"state": "NEUTRAL"}


def compute_index_quality_score(evidence, hard_gate_failures=None):
    """
    Aggregates the 5 index evidence groups (spec section 13). Same
    disclosed-redistribution methodology as compute_stock_quality_score()
    above -- any component that's None (genuinely unavailable this
    cycle, e.g. futures_oi before index_tracker.py's exact snapshot
    field names are confirmed) has its weight redistributed
    proportionally across the components that DO have a real value,
    shown explicitly in 'weights_used'.

    `evidence` keys match _INDEX_WEIGHTS; each value is a sub-score in
    [0, that component's max weight], or None if unavailable.

    hard_gate_failures: same mechanism as compute_stock_quality_score()
    -- optional list of reason strings; when non-empty, forces verdict
    to IGNORE regardless of score. No index-specific hard gate is
    wired to this yet (nothing calls this with a real list currently),
    added now for interface consistency with the stock engine so a
    future index liquidity/data-quality gate has somewhere real to
    plug into rather than needing this signature changed later.

    Output states per spec: BULLISH/BEARISH/MIXED/RANGE/HIGH_VOLATILITY
    determined by the caller from price_structure/regime context (this
    function only produces the numeric verdict) -- 'direction' here is
    passed through from the caller's own evidence, not re-derived.

    Spec: "a directional BUY CE/PE should require strong multi-factor
    confirmation, preferably at least 4 of 5 evidence groups aligned."
    confirmations_count in the return value makes that checkable
    directly -- counts components that scored >=70% of their own max
    weight, out of the 5 groups (not just the ones with real data this
    cycle, so a candidate with 2 missing groups can never silently
    reach 4/5 by only being judged against the 3 it has).

    Returns {'score', 'grade', 'verdict', 'confirmations_count',
    'weights_used', 'components_scored', 'components_unavailable',
    'hard_gate_failures'}. Grade bands identical to the stock engine
    (A+ 90-100, A 80-89, B/WATCH 70-79, IGNORE <70) -- verdict
    TRADE/WATCH/IGNORE, same as the stock engine; the caller maps
    TRADE to BUY CE/BUY PE using the direction it already knows (this
    function doesn't guess a side).
    """
    hard_gate_failures = hard_gate_failures or []
    available = {k: v for k, v in evidence.items() if v is not None and k in _INDEX_WEIGHTS}
    missing = [k for k in _INDEX_WEIGHTS if k not in available]

    confirmations_count = sum(
        1 for k in _INDEX_WEIGHTS
        if evidence.get(k) is not None and evidence[k] >= _INDEX_WEIGHTS[k] * 0.7
    )

    if not available:
        return {"score": None, "grade": None, "verdict": "IGNORE", "confirmations_count": 0,
                "weights_used": {}, "components_scored": [], "components_unavailable": missing,
                "hard_gate_failures": hard_gate_failures}

    base_total_available = sum(_INDEX_WEIGHTS[k] for k in available)
    full_total = sum(_INDEX_WEIGHTS.values())
    redistribution_factor = full_total / base_total_available if base_total_available else 0

    weights_used = {k: round(_INDEX_WEIGHTS[k] * redistribution_factor, 2) for k in available}
    score = 0.0
    for k, sub_score in available.items():
        fraction = max(0.0, min(1.0, sub_score / _INDEX_WEIGHTS[k])) if _INDEX_WEIGHTS[k] else 0.0
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

    # Spec's explicit "prefer >=4 of 5" requirement -- downgrade a
    # would-be TRADE that hasn't actually cleared that bar, rather than
    # letting a high score from few-but-strong components alone issue
    # a directional call the spec says needs broader confirmation.
    if verdict == "TRADE" and confirmations_count < 4:
        verdict = "WATCH"

    if hard_gate_failures:
        verdict = "IGNORE"
        grade = None

    return {
        "score": score, "grade": grade, "verdict": verdict,
        "confirmations_count": confirmations_count,
        "weights_used": weights_used,
        "components_scored": list(available.keys()),
        "components_unavailable": missing,
        "hard_gate_failures": hard_gate_failures,
    }


# =============================================================================
# 11. MARKET REGIME ENGINE  (spec section 2) -- top of the INDEX -> MARKET
#     REGIME -> SECTOR -> STOCK cascade
# =============================================================================

def classify_market_regime(adx_state, price_structure_state, price_above_vwap, price_above_ema20,
                            breadth_advances_pct, breadth_declines_pct, vix_change_pct,
                            high_vol_threshold=10.0, min_aligned_factors=3):
    """
    Multi-factor regime classification for a benchmark index (real
    usage: NIFTY). Spec's explicit anti-pattern, quoted directly:
    "Do not classify the market as bullish merely because NIFTY is
    green." -- this requires genuine alignment across independent
    factors (real trend strength+direction from ADX+DI, real price
    structure, VWAP/EMA20 positioning, and F&O-universe breadth),
    never a single input deciding the regime alone.

    adx_state: output of classify_adx_direction()['state'].
    price_structure_state: output of detect_price_structure()['state'].
    price_above_vwap/price_above_ema20: bool or None.
    breadth_advances_pct/breadth_declines_pct: from _compute_breadth(),
    already scoped to the real F&O universe this project actually
    tracks -- NOT full-market breadth (that doesn't exist in this
    codebase), disclosed here rather than silently assumed broader.
    vix_change_pct: today's VIX % change.

    HIGH_VOLATILITY takes priority over any trend read -- spec: "When
    volatility expands significantly, reduce confidence/quality and
    apply stricter confirmation," which only makes sense as an
    override, not something a strong trend read can mask.

    min_aligned_factors=3 (of up to 4 possible: adx_direction,
    price_structure, vwap, ema20, plus breadth as a 5th when
    available) is a configurable default, not a claimed-optimal
    number, matching spec's explicit "thresholds must be configurable"
    requirement everywhere else in this file.

    Returns {'state', 'aligned_factors', 'conflicting_factors'}.
    state in: TREND_UP, TREND_DOWN, RANGE, HIGH_VOLATILITY, MIXED,
    INSUFFICIENT_DATA.
    """
    if adx_state is None or price_structure_state is None or price_above_vwap is None or price_above_ema20 is None:
        return {"state": "INSUFFICIENT_DATA", "aligned_factors": [], "conflicting_factors": []}

    if vix_change_pct is not None and vix_change_pct >= high_vol_threshold:
        return {"state": "HIGH_VOLATILITY", "aligned_factors": [], "conflicting_factors": []}

    if adx_state == "RANGE":
        # Spec: "If trend strength is weak and price is oscillating
        # around VWAP/EMA structure, avoid aggressive momentum
        # signals" -- weak ADX alone is sufficient to call RANGE,
        # regardless of what the other factors individually show,
        # since there's no real trend STRENGTH underneath any of them.
        return {"state": "RANGE", "aligned_factors": [], "conflicting_factors": []}

    bullish, bearish = [], []
    if adx_state == "BULLISH_TREND":
        bullish.append("adx_direction")
    elif adx_state == "BEARISH_TREND":
        bearish.append("adx_direction")

    if price_structure_state == "BULLISH_STRUCTURE":
        bullish.append("price_structure")
    elif price_structure_state == "BEARISH_STRUCTURE":
        bearish.append("price_structure")

    (bullish if price_above_vwap else bearish).append("vwap")
    (bullish if price_above_ema20 else bearish).append("ema20")

    if breadth_advances_pct is not None and breadth_advances_pct >= 55:
        bullish.append("breadth")
    elif breadth_declines_pct is not None and breadth_declines_pct >= 55:
        bearish.append("breadth")

    if len(bullish) >= min_aligned_factors and len(bullish) > len(bearish):
        return {"state": "TREND_UP", "aligned_factors": bullish, "conflicting_factors": bearish}
    if len(bearish) >= min_aligned_factors and len(bearish) > len(bullish):
        return {"state": "TREND_DOWN", "aligned_factors": bearish, "conflicting_factors": bullish}

    dominant, other = (bullish, bearish) if len(bullish) >= len(bearish) else (bearish, bullish)
    return {"state": "MIXED", "aligned_factors": dominant, "conflicting_factors": other}


# =============================================================================
# 12. SECTOR LEADER/LAGGARD RANKING  (spec section 12) -- "rank stocks
#     within strong sectors... for bullish trades prefer leaders, for
#     bearish trades prefer laggards"
# =============================================================================

def rank_sector_peers(sector_stocks_change_pcts, leader_pct=0.3, laggard_pct=0.3):
    """
    Ranks EVERY stock in one sector by today's change_percent,
    independent of any specific trade's direction -- spec: "Rank
    stocks within strong sectors... Identify: SECTOR LEADERS / SECTOR
    NEUTRAL / SECTOR LAGGARDS." The direction-specific "prefer leaders
    for bullish, laggards for bearish" judgment is applied separately
    by evaluate_sector_leadership() below -- this function only
    produces the objective, direction-agnostic ranking.

    sector_stocks_change_pcts: {symbol: change_percent} for every
    stock in ONE sector this cycle (the caller groups by sector; this
    function doesn't know or care what the sector is called).

    Requires >=3 stocks to produce a meaningful ranking -- a "top 30%"
    of 2 stocks isn't real leadership, it's just "the one that's up
    more." Fewer than that, every stock gets INSUFFICIENT_DATA rather
    than a rank that would look precise but isn't meaningful.

    leader_pct/laggard_pct=0.3 (top/bottom 30% by change_percent) are
    configurable defaults, not claimed-optimal, same as every other
    threshold in this file.

    Returns {symbol: {'state', 'rank', 'total_in_sector', 'percentile'}}
    for every symbol given. state in: LEADER, NEUTRAL, LAGGARD,
    INSUFFICIENT_DATA. rank=1 means the single biggest gainer in the
    sector today (highest change_percent), regardless of whether
    that's ultimately useful for a BUY or a SELL -- direction is
    applied downstream, not baked into the rank number itself.
    """
    total = len(sector_stocks_change_pcts)
    if total < 3:
        return {sym: {"state": "INSUFFICIENT_DATA", "rank": None, "total_in_sector": total, "percentile": None}
                for sym in sector_stocks_change_pcts}

    ranked = sorted(sector_stocks_change_pcts.items(), key=lambda kv: kv[1], reverse=True)
    leader_cutoff = max(1, round(total * leader_pct))
    laggard_cutoff = max(1, round(total * laggard_pct))

    result = {}
    for i, (sym, _chg) in enumerate(ranked):
        rank = i + 1
        percentile = round((total - rank) / (total - 1) * 100, 1) if total > 1 else 50.0
        if rank <= leader_cutoff:
            state = "LEADER"
        elif rank > total - laggard_cutoff:
            state = "LAGGARD"
        else:
            state = "NEUTRAL"
        result[sym] = {"state": state, "rank": rank, "total_in_sector": total, "percentile": percentile}
    return result


def evaluate_sector_leadership(action, sector_rank_state):
    """
    Direction-aware read of ONE stock's already-computed sector rank
    (from rank_sector_peers() above) -- spec's exact wording: "For
    bullish trades prefer leaders. For bearish trades prefer
    laggards." A LAGGARD is the strongest bearish candidate (already
    showing the most relative weakness in its own sector today), same
    logic mirrored for a LEADER on the bullish side.

    Returns {'state'}. state in: PREFERRED, ACCEPTABLE, AVOID, INSUFFICIENT_DATA.
    """
    if sector_rank_state is None or sector_rank_state == "INSUFFICIENT_DATA":
        return {"state": "INSUFFICIENT_DATA"}

    if action == "BUY":
        if sector_rank_state == "LEADER":
            return {"state": "PREFERRED"}
        if sector_rank_state == "LAGGARD":
            return {"state": "AVOID"}
        return {"state": "ACCEPTABLE"}
    else:
        if sector_rank_state == "LAGGARD":
            return {"state": "PREFERRED"}
        if sector_rank_state == "LEADER":
            return {"state": "AVOID"}
        return {"state": "ACCEPTABLE"}
