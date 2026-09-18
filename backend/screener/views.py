import os
import sys
import time
import threading
from datetime import datetime, timedelta
from datetime import time as dt_time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import pandas as pd
import numpy as np
from rest_framework.views import APIView
from rest_framework.response import Response

import math

def safe_json(val):
    """Kill NaN/Inf before JSON sees it"""
    if val is None:
        return None
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            return None
    return val

try:
    from .fyers_client import is_authenticated, get_quotes, get_option_analytics, get_history, CLIENT_ID
except ImportError:
    is_authenticated = lambda: False
    get_quotes = lambda x: None
    get_option_analytics = lambda symbol, strikecount=10: None
    get_history = lambda symbol, resolution="D", range_from=None, range_to=None: None
    CLIENT_ID = ""

try:
    from .options_analytics import estimate_option_premium
except ImportError:
    estimate_option_premium = lambda spot, strike, days, iv, opt_type, risk_free_rate=0.07: None

# ============================================================
# CACHES
# ============================================================
_stock_cache = {}
_index_cache = {}
# Sep 16 2026: circuit breaker for the OI live dashboard writer -- an
# unexplained "module has no attribute '_panel_ready'" error was
# confirmed live, repeating every ~90s scan cycle and flooding the
# terminal without ever actually writing data. Root cause not yet
# found (that exact name appears nowhere in this project's source),
# so rather than keep retrying and spamming the log every cycle while
# it's investigated, this stops retrying after a few consecutive
# failures and reports it ONCE -- the rest of the app (signals,
# scanning, everything else) was never affected by this; only the
# dashboard mirror itself was failing.
_dashboard_consecutive_failures = 0
_dashboard_disabled_this_session = False
_DASHBOARD_MAX_CONSECUTIVE_FAILURES = 3
_index_cache_updated_at = 0.0  # Aug 20 2026: lets _build_all() below reuse whatever
# _index_snapshot_worker's faster 60s loop already fetched instead of
# independently re-fetching the same NIFTY/BANKNIFTY/VIX quotes -- see
# both functions for why this mattered (confirmed live 429 rate-limiting
# on Fyers' /quotes endpoint, and this redundant double-fetch was a real,
# substantial, previously-accepted-as-lightweight contributor to that).
_signal_cache = []
# Sep 2 2026: manually-bumped marker for the live SCORING/QUALIFICATION
# logic specifically -- distinct from backtest_signal_pnl.py's own
# STRATEGY_RULE_VERSION, which describes that file's report format,
# not this. Exists because of a real, confirmed gap: the Aug 3-7
# window's actual formula (CONFLICT was a -15 penalty, not a reject)
# was only recoverable by combining git history with a comment left
# in the code -- there was no direct record on the trades themselves.
# Bump this by hand whenever the score/oi_adjustment/quality_signals
# logic changes, so a future review never has to repeat that
# archaeology. Persisted per-signal below, not just held in this one
# global -- a global alone would only tell you TODAY's version, not
# which version generated a signal logged weeks ago.
SIGNAL_LOGIC_VERSION = "v1 (2026-09-02)"

# Sep 2 2026: Section 9's "position sizing from real risk," done
# correctly this time -- adds a lot-count MULTIPLIER on top of the
# real, exchange-defined lot_size, never a replacement for it. The
# Aug 27 fix elsewhere in this file (real lot size instead of
# int(50000/entry)) exists specifically because deriving quantity from
# rupees directly gave absurd, signal-quality-unrelated position sizes
# -- this doesn't repeat that mistake, it only decides HOW MANY of the
# real lot to take. Unset (None) is strictly opt-in -- returns exactly
# today's unchanged 1-lot behavior, byte for byte, until a user
# actually configures a budget. If even 1 real lot's risk exceeds the
# configured budget, returns None with a reason -- skips the trade
# rather than silently overriding the user's own stated risk limit.
USER_SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "user_settings.json")


def get_risk_budget_rupees():
    """Reads the persisted risk-budget-per-trade setting, or None if
    never configured (the default, unchanged-behavior state)."""
    import json
    try:
        if not os.path.exists(USER_SETTINGS_FILE):
            return None
        with open(USER_SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        val = data.get("risk_budget_rupees")
        return float(val) if val is not None else None
    except Exception:
        return None  # corrupt/unreadable settings file -- fall back to unset, never crash the scanner over this


def compute_qty_with_risk_budget(lot_size, entry, sl, risk_budget_rupees):
    """Returns (qty, skip_reason). qty is None (with a real reason) if
    the configured budget can't cover even 1 real lot -- never a
    fabricated smaller-than-a-lot quantity."""
    if risk_budget_rupees is None:
        return lot_size, None
    risk_per_lot = abs(entry - sl) * lot_size
    if risk_per_lot <= 0:
        return lot_size, None
    num_lots = int(risk_budget_rupees // risk_per_lot)
    if num_lots < 1:
        return None, f"1 lot risk (Rs {risk_per_lot:,.0f}) exceeds configured risk budget (Rs {risk_budget_rupees:,.0f})"
    return num_lots * lot_size, None


_no_trade_cache = []  # Aug 31 2026: P0-6 -- rejected candidates this cycle, with reasons
_tech_cache = {}
_cache_lock = threading.Lock()

# Sep 3 2026: hysteresis for live signal-list inclusion -- built after
# real evidence from a full historical analysis (22 real trading days,
# 463 logged signals): 59.6% of every signal ever logged was a same-day
# repeat of a symbol that already fired that day, and repeats were
# measurably WORSE trades (Target-hit 24.7% vs 31.5% for first signals;
# closed unresolved-down at EOD 37.1% vs 23.1%). Root cause: the score
# gate below used to be a single flat cutoff recomputed fresh every
# cycle with zero memory -- a stock sitting at 49/51/49/51 would blink
# in and out of the live list every single cycle.
#
# This is a SEPARATE mechanism from excel_logger.py's own 30-minute
# reactivation cooldown -- that one only merges duplicate SPREADSHEET
# rows for very fast (<30min) flicker and has no effect on which
# stocks actually appear in the live list. Confirmed it wasn't the
# fix: the historical repeats' median gap was 44 minutes, already past
# that 30-min window, so most of what got measured wasn't even
# touched by it.
#
# ENTRY_SCORE_THRESHOLD (50) is unchanged -- same bar as always to
# first qualify. EXIT_SCORE_THRESHOLD (35) is deliberately LOWER --
# once a stock is already "in" today, it stays in until its score
# drops meaningfully, not just back below 50. The 15-point gap is a
# reasoned starting default (a standard hysteresis-band width), NOT
# something backtested to an exact optimum -- there's no granular
# historical score-history logged to validate the precise number
# against, only the entry/exit snapshot at qualification time. The
# DIRECTION (hysteresis beats a flat cutoff here) is what's actually
# evidence-backed; this exact number is a place to start, tunable
# later once real data accumulates under it.
#
# In-memory only, resets on server restart -- same honest limitation
# already true of every other cache in this file (_stock_cache,
# _signal_cache, etc.), not a new one introduced here. A restart mid-
# day means a stock sitting between 35-49 (already qualified, in the
# hysteresis band) needs to re-cross 50 fresh afterward, same as if it
# had never qualified today.
_qualification_state = {}  # {(symbol, action): {'date': 'YYYY-MM-DD', 'qualified': bool}}
ENTRY_SCORE_THRESHOLD = 50
EXIT_SCORE_THRESHOLD = 35


# Sep 18 2026: REAL ROOT CAUSE FOUND for a live, confirmed bug -- the
# Fyers rate-limit circuit breaker (fyers_client.py) was tripping
# constantly, skipping the large majority of real calls every cycle.
# fyers_client.py's own request governor (_REQUEST_MIN_INTERVAL=0.32s,
# a threading.Lock()-protected pace limit) already exists specifically
# to stay under Fyers' rate limit -- but a threading.Lock() only
# synchronizes threads WITHIN one process. Django's own runserver
# autoreloader (the default, used throughout this whole project's
# development) launches a PARENT "watcher" process that imports this
# entire module (and everything below, including the three
# threading.Thread(...).start() calls a few hundred/thousand lines
# down) to validate the app, THEN spawns a separate CHILD process that
# actually serves requests -- and neither process was ever checked to
# see which one this is. Both were independently starting the same
# background scan loop, each with its own separate, unshared
# _rate_limit_state and _request_lock (plain module-level Python
# objects, not shared across OS processes) -- meaning two independent
# scanners, each self-throttling to ~3 req/s, but TOGETHER hitting
# Fyers at up to ~6+ req/s combined, which explains the repeated 429s
# far better than "the limit itself is too strict." This does not
# touch the circuit breaker's own logic or thresholds at all -- it
# stops the actual double-execution that was overloading it.
#
# Correctly handles every real deployment shape, not just the common
# case: RUN_MAIN is set to 'true' ONLY in runserver's child process,
# never in its parent/watcher -- but RUN_MAIN is *also* absent in a
# production ASGI/WSGI server (uvicorn/gunicorn, per this project's
# own README) and in `runserver --noreload`, where there is no
# separate watcher process at all and starting is exactly correct.
# Only the genuine watcher-vs-child ambiguity (plain `runserver`,
# autoreload enabled, which is the default) needs resolving here.
_IS_RELOADER_WATCHER_PROCESS = (
    "runserver" in sys.argv
    and "--noreload" not in sys.argv
    and os.environ.get("RUN_MAIN") != "true"
)


def _is_qualified_with_hysteresis(symbol, action, score, state_dict=None, today=None):
    """
    Whether (symbol, action) should be included as a live signal THIS
    cycle. Pure enough to unit test directly -- state_dict/today are
    injectable (default to the real module state / real today) so a
    test can pass its own dict and fixed date without touching global
    state or depending on wall-clock time.

    Mutates state_dict as a side effect -- call exactly once per
    (symbol, action) per cycle, same call-once contract the rest of
    this file's per-cycle logic already follows.
    """
    if state_dict is None:
        state_dict = _qualification_state
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")

    key = (symbol, action)
    state = state_dict.get(key)
    if state is None or state.get('date') != today:
        state = {'date': today, 'qualified': False}
        state_dict[key] = state

    if state['qualified']:
        if score < EXIT_SCORE_THRESHOLD:
            state['qualified'] = False
    else:
        if score >= ENTRY_SCORE_THRESHOLD:
            state['qualified'] = True

    return state['qualified']


# Sep 12 2026: hysteresis for quality_engine's aggregate verdict, same
# shape and same evidence-backed reasoning as _is_qualified_with_
# hysteresis() above for the technical score -- compute_stock_quality_
# score() gets recomputed fresh every cycle, same "blinks every cycle
# on a score right at the boundary" risk that function already fixed
# for the base technical score. Root motivation: a real logged trade
# hit SL after entering on a signal that had already flickered off/on
# in the live list before entry -- the technical score's own hysteresis
# was never the problem there; oi_confirmation (recomputed fresh, no
# memory) was.
#
# Separate dict, separate function from _qualification_state above --
# different key semantics (bool confirmed/not, not a score threshold),
# and this one also needs to distinguish a REAL contradiction from
# ordinary noise, which the technical-score version doesn't need to.
_quality_confirmation_state = {}  # {(symbol, action): {'date': 'YYYY-MM-DD', 'confirmed': bool}}


def _is_quality_confirmed_with_hysteresis(symbol, action, quality_result, state_dict=None, today=None):
    """
    Whether (symbol, action) should count as quality_engine-confirmed
    THIS cycle. Same injectable state_dict/today pattern as
    _is_qualified_with_hysteresis() above, same reason (pure enough to
    unit test directly, no dependency on wall-clock time or global
    state in a test).

    Sep 17 2026: per the Zero-Signal Forensic Audit and explicit,
    scoped approval -- entry bar changed from requiring THIS cycle's
    verdict to be TRADE (score>=80) to requiring score>=70 (TRADE OR
    WATCH tier -- both are real, already-defined verdicts from the
    same quality_engine.py grading, this isn't a new threshold being
    invented). Everything else below is unchanged: the scoring
    formula, weights, and every hard gate this function's OWN
    docstring already documented are exactly as they were.

    Asymmetric by DESIGN, not by a tuned number:
      - ENTRY requires this cycle's OWN score to be >= 70, no grace
        on the way in -- same "no grace on entry" shape as the
        technical score's ENTRY_SCORE_THRESHOLD.
      - EXIT is immediate ONLY on a real, confirmed contradiction --
        quality_result['conflict_gate_triggered'] (options structure
        or market regime actively fighting this direction, not a mere
        score dip) -- same "excluded entirely, not just penalized"
        principle the live oi_confirmation check already applies to a
        fresh CONFLICT reading.
      - Everything else that drops out (a score dip below 70 with no
        active conflict, a thin-data cycle, or quality_result itself
        being None because _evaluate_and_log_shadow() itself raised)
        is held through, not exited -- same "don't drop on noise or on
        a data gap" principle as EXIT_SCORE_THRESHOLD's own gap gives
        the base score one level up, and the same "a failed fetch
        isn't new information" reasoning already used everywhere else
        in this project for a transient failure.

    Mutates state_dict as a side effect -- call exactly once per
    (symbol, action) per cycle, same call-once contract as the
    technical-score version.
    """
    if state_dict is None:
        state_dict = _quality_confirmation_state
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")

    key = (symbol, action)
    state = state_dict.get(key)
    if state is None or state.get('date') != today:
        state = {'date': today, 'confirmed': False}
        state_dict[key] = state

    conflict = bool(quality_result and quality_result.get('conflict_gate_triggered'))
    score = quality_result.get('score') if quality_result else None

    if state['confirmed']:
        if conflict:
            state['confirmed'] = False
        # else: hold through a score dip below 70, a thin-data cycle,
        # or a computation failure -- see docstring above.
    else:
        if score is not None and score >= 70 and not conflict:
            state['confirmed'] = True

    return state['confirmed']


# Sep 12 2026 (later same day): hysteresis for oi_confirmation ITSELF --
# the actual root-cause field. Adding quality_confirmed's own
# persistence above did NOT fix the real reported bug (a signal
# flickering off/on before a real logged loss on ANGELONE 295 PE),
# because quality_signals' final filter ANDs oi_confirmation=='CONFIRMED'
# together with quality_confirmed -- oi_confirmation was still being
# recomputed fresh every cycle from a 1.2x CE/PE-ratio check with no
# floor, no memory, completely unprotected by either hysteresis
# function above. A signal could still drop out purely because THIS
# field read NEUTRAL for one cycle, regardless of what quality_confirmed
# said. This is the fix for the actual, evidenced problem.
_oi_confirmation_state = {}  # {(symbol, action): {'date': 'YYYY-MM-DD', 'confirmed': bool}}


def _is_oi_confirmed_with_hysteresis(symbol, action, oi_confirmation_reading, state_dict=None, today=None):
    """
    Same asymmetric shape as the two hysteresis functions above, applied
    to the oi_confirmation field itself (CONFIRMED/NEUTRAL/NO_DATA on an
    appended signal -- CONFLICT never reaches this function at all, see
    below).

    ENTRY: only from a fresh CONFIRMED reading this cycle, no grace.

    EXIT: this function only ever sees CONFIRMED/NEUTRAL/NO_DATA -- a
    CONFLICT reading causes an immediate `continue` in the caller BEFORE
    a signal is even built for this cycle (see the oi_confirmation
    computation block above), so there's no "reading" to hand this
    function for that case. The caller explicitly clears this state to
    False in that CONFLICT branch instead -- a real, confirmed
    contradiction exits immediately, same principle as the other two
    hysteresis functions' conflict handling, just enforced at the call
    site here rather than inside this function, because the CONFLICT
    candidate is dropped before reaching this point in the loop.

    Everything else (NEUTRAL or NO_DATA this cycle) holds whatever the
    state already was -- the exact 1.2x-ratio wobble this exists to
    absorb.
    """
    if state_dict is None:
        state_dict = _oi_confirmation_state
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")

    key = (symbol, action)
    state = state_dict.get(key)
    if state is None or state.get('date') != today:
        state = {'date': today, 'confirmed': False}
        state_dict[key] = state

    if oi_confirmation_reading == 'CONFIRMED':
        state['confirmed'] = True
    # else: NEUTRAL or NO_DATA this cycle -- hold, don't newly enter and
    # don't drop out either. See docstring above for why CONFLICT is
    # handled by the caller clearing this state directly instead.

    return state['confirmed']


# Sep 12 2026: same off-switch pattern tasks.py already uses for its
# own disabled duplicate scanner (_DUPLICATE_SCANNER_ENABLED) -- this
# gate is new and its real effect on list size hasn't been observed
# live yet (multi_tf_trend/futures_oi are often INSUFFICIENT_DATA for
# stocks today, so how often TRADE is actually reachable is currently
# unknown). Default ON since it was explicitly requested, but instantly
# reversible via env var with no code change if it turns out to
# strangle the list more than intended -- quality_confirmed/score/
# verdict/reasons stay attached to every signal either way, so the
# gate's would-be effect is always visible even while it's toggled off.
_QUALITY_GATE_ENABLED = os.environ.get("ENABLE_QUALITY_CONFIRMATION_GATE", "true").lower() == "true"


# ---------------------------------------------------------------------------
# Sep 12 2026: SNIPER V2 -- central configuration.
#
# IMPORTANT SCOPE NOTE: the forensic audit's Change 1 (restart-proof
# duplicate guard) and the durable half of cross-date OUTCOME history
# both belong to excel_logger.py's get_locked_plan() +
# get_symbol_recurrence_info(), which already implement real, tested
# (see excel_logger.py's own restart-simulation tests), persisted
# per-(symbol,action) state. Nothing here duplicates that -- this
# section adds what excel_logger.py does NOT already provide: a
# same-day-scoped observation counter, and the classification/shadow/
# config layer sitting on top of both data sources.
#
# All flags default to OFF or observation-only, per explicit
# instruction: the Sep 5-12 forensic audit found ZERO genuine same-day
# repeat signals to test a lock against, and the cross-date recurrence
# gap (50% first-occurrence vs 11% later, n=8/9) is too small to act on
# yet.
SNIPER_V2_CONFIG = {
    "DUPLICATE_GUARD": True,  # excel_logger.py's get_locked_plan()/cooldown -- always on, already proven
    "SAME_DAY_SYMBOL_LOCK": os.environ.get("ENABLE_SAME_DAY_SYMBOL_LOCK", "false").lower() == "true",
    "RECURRENCE_TRACKING": os.environ.get("ENABLE_RECURRENCE_TRACKING", "true").lower() == "true",
    "RECURRENCE_PENALTY": os.environ.get("ENABLE_RECURRENCE_PENALTY", "false").lower() == "true",
    "SHADOW_MODE": os.environ.get("SNIPER_V2_SHADOW_MODE", "true").lower() == "true",
    "MARKET_FILTER": False,     # no market-regime data source wired in yet
    "SECTOR_FILTER": False,     # no sector-regime data source wired in yet
    "OI_FILTER": False,         # oi_confirmation exists and already gates via _is_oi_confirmed_with_hysteresis -- this flag is for a SEPARATE, not-yet-built recurrence-style OI filter, not a duplicate of the existing one
    "STRUCTURE_FILTER": False,  # no real BOS/structure classification data source exists
    "TIME_FILTER": False,       # no time-of-day filter built -- forensic audit's own data had no timestamp column to validate one against
    "LIQUIDITY_FILTER": False,  # no option liquidity/spread data source wired in yet
    "REENTRY_MODE": "SAFE",     # "SAFE" = classify as UNKNOWN rather than guess NEW_SETUP/GENUINE_REENTRY without real structure data
    # Sep 13 2026: ADX (trend strength) currently only ever adds +20 to
    # score -- a stock can still qualify (RSI+Volume+direction alone =
    # 60 >= the 50 threshold) with ZERO trend strength, which directly
    # contradicts ADX's own stated reason for being added here in the
    # first place ("a stock can look great on RSI/volume/VWAP/MACD and
    # still be going nowhere" -- see the Aug 31 comment right above the
    # score computation). Default False: this is a real, defensible
    # reading of ADX's own established purpose, but NOT validated
    # against real historical outcomes -- the audited 41-signal sample
    # has no per-signal ADX recorded, so I cannot show this improves
    # results, only that it closes a real gap between stated intent and
    # actual enforcement. Same discipline as every other switch here:
    # ready, not silently activated.
    "REQUIRE_ADX_TREND_STRENGTH": os.environ.get("REQUIRE_ADX_TREND_STRENGTH", "false").lower() == "true",
    # Sep 17 2026 (Zero-Signal Forensic Audit, continued): the OI
    # CONFLICT hard-exclude below used to trigger off a SINGLE narrow
    # measure -- options_analytics.analyze_option_chain()'s chain-wide
    # CE/PE OI-change ratio (1.2x cutoff, no price reference, no
    # futures OI at all). That's exactly the "rigid single-pattern
    # gate" risk this audit's Phase 4/8 asked about. futures_oi_data
    # is already fetched every cycle for shortlisted candidates
    # (previously shadow-mode only) and there's already a real, tested
    # 4-quadrant classifier for it (quality_engine.
    # evaluate_futures_oi_structure(), reused verbatim here, not
    # reimplemented). Default True: before excluding a candidate
    # entirely on the options-chain reading alone, also check whether
    # futures OI independently agrees it's a genuine conflict. Only a
    # CORROBORATED conflict (both agree) still excludes; an
    # uncorroborated one (futures OI unavailable, neutral, or itself
    # supportive) is scored down instead of killed outright. NOT
    # validated against real historical outcomes yet -- same
    # "heuristic, not proven" labeling REQUIRE_ADX_TREND_STRENGTH
    # above already uses. Flip to "false" via env var to restore the
    # original any-conflict-excludes behavior with no code change.
    "OI_CONFLICT_REQUIRES_FUTURES_CORROBORATION": os.environ.get("OI_CONFLICT_REQUIRES_FUTURES_CORROBORATION", "true").lower() == "true",
}
# Back-compat module-level names some earlier code in this session already
# reads directly -- same values, single source of truth is the dict above.
ENABLE_RECURRENCE_TRACKING = SNIPER_V2_CONFIG["RECURRENCE_TRACKING"]
ENABLE_SAME_DAY_SYMBOL_LOCK = SNIPER_V2_CONFIG["SAME_DAY_SYMBOL_LOCK"]
ENABLE_RECURRENCE_PENALTY = SNIPER_V2_CONFIG["RECURRENCE_PENALTY"]

# Sep 12 2026: standardized block-reason vocabulary. Defined here as the
# shared vocabulary for any FUTURE blocking rule to use -- does NOT
# retrofit the ~15 existing free-text no_trade_log.append() call sites
# elsewhere in this file (that's a much bigger, separately-risky change,
# and every one of them already works). Nothing currently blocks using
# these values, since every filter that would is still disabled above.
BLOCK_REASON_CODES = (
    "DUPLICATE_SIGNAL", "SAME_SETUP_RETRIGGER", "SYMBOL_COOLDOWN", "RECURRENT_SYMBOL",
    "MARKET_CONFLICT", "SECTOR_CONFLICT", "OI_CONFLICT", "WEAK_STRUCTURE", "RANGE_PINNED",
    "LOW_LIQUIDITY", "LATE_ENTRY", "LOW_SCORE", "UNKNOWN", "OTHER",
)

# Sep 12 2026: signal state machine -- CANDIDATE/VALIDATED/EMITTED/
# ACTIVE/RESOLVED already exists, implemented in excel_logger.py, not
# reimplemented here (per "do not rebuild existing working
# functionality"): a candidate that reaches signals.append() and gets
# logged IS "EMITTED"; get_locked_plan() returning a plan IS "ACTIVE";
# the Outcome column being set to "Target N Hit"/"SL Hit"/"Expired (no
# SL/Target hit)" IS "RESOLVED" with its specific outcome -- and this
# whole chain is already proven restart-safe (excel_logger.py's own
# _ensure_fresh() rebuild, tested against a real simulated restart).
# "CANCELLED" is the one state with no current equivalent -- nothing in
# this codebase explicitly cancels an already-emitted signal today.

# {symbol: {'date': 'YYYY-MM-DD', 'signals_fired_today': int,
#           'first_signal_time': iso_str, 'latest_signal_time': iso_str}}
# Resets when the date rolls over, same check-and-replace pattern as
# _qualification_state/_oi_confirmation_state/_quality_confirmation_state
# above. This is the one piece excel_logger.py doesn't already track
# (it counts ROWS, not "how many times did a fresh setup fire today"
# as a same-day-scoped running count).
_symbol_daily_state = {}

# {symbol: {'occurrences': [{'date':..., 'action':..., 'option_symbol':...}, ...]}}
# Session-lifetime supplement to excel_logger.get_symbol_recurrence_info()
# -- catches a symbol firing multiple times TODAY before excel_logger's
# own once-per-day cache would reflect it (that cache only covers
# STRICTLY PRIOR days). Wiped on restart, same accepted limitation as
# every in-memory dict in this file; excel_logger's own persisted
# history is the durable source of truth for anything more than a day old.
_symbol_recurrence_history = {}

# ---------------------------------------------------------------------------
# Sep 13 2026: SNIPER STOCKS filter candidates -- SHADOW MODE ONLY.
# Historical replay was checked and is genuinely impossible: this
# sandbox's network egress explicitly blocks every financial data host
# (confirmed via curl -- x-deny-reason: host_not_allowed on Yahoo
# Finance and NSE directly), so there is no way to reconstruct real
# historical OHLCV at past signal timestamps. This evaluates all six
# candidates against every REAL signal going forward, using data
# already computed this cycle -- none of it gates or alters the actual
# BUY/SELL/NEUTRAL decision. The comparison report below only produces
# a verdict once real accumulated evidence clears an explicit minimum
# bar; until then it reports exactly how much has been collected.

# {symbol: {'macd': float, 'date': 'YYYY-MM-DD'}} -- cross-CYCLE (not
# cross-day) comparison is enough for MACD slope: cycles run every
# ~90s, so two observations of the same symbol in one session already
# show real direction. Resets on restart, same accepted limitation as
# every other in-memory tracker in this file -- the first time a
# symbol is seen after a restart, candidate C reports
# UNKNOWN_INSUFFICIENT_HISTORY rather than guessing a slope from one
# reading.
_macd_cycle_tracker = {}


def _evaluate_shadow_candidates(sym, action, price, change_percent, macd, rsi, adx, vol, vol_avg, ema20, ema50, support=None, resistance=None, stock_t3=None, sector_change_pct=None, nifty_change_pct=None, oi_confirmation=None):
    """
    Returns a dict of nine {candidate: 'PASS'|'REJECT'|'UNKNOWN', candidate+'_reason': str}
    entries. Every value here is computed from data the live signal
    already has this cycle -- nothing new fetched, nothing guessed.
    Never called before the real action/score decision, and its output
    is never read by anything that gates a signal.

    Sep 13 2026 (revision): added candidates G/H. support/resistance are
    already computed every cycle (_compute_indicators' own return dict)
    but were never referenced anywhere in the actual entry/target logic
    before this -- confirmed by grep across the whole file finding zero
    other uses. stock_t3 is the STOCK-side (not option-premium) Target 3
    level already computed a few lines above where this is called.
    """
    out = {}

    # A. Today's own price-action direction.
    if action == "BUY":
        out["candidate_a"] = "PASS" if change_percent > 0 else "REJECT"
    else:
        out["candidate_a"] = "PASS" if change_percent < 0 else "REJECT"
    out["candidate_a_reason"] = f"change_percent={change_percent:+.2f}%"

    # B. EMA20/EMA50 trend structure -- both already computed, never
    # used for direction anywhere in the live scoring today.
    if ema20 is not None and ema50 is not None:
        if action == "BUY":
            out["candidate_b"] = "PASS" if (price > ema20 > ema50) else "REJECT"
        else:
            out["candidate_b"] = "PASS" if (price < ema20 < ema50) else "REJECT"
        out["candidate_b_reason"] = f"price={price:.2f}, ema20={ema20:.2f}, ema50={ema50:.2f}"
    else:
        out["candidate_b"] = "UNKNOWN"
        out["candidate_b_reason"] = "ema20/ema50 unavailable this cycle"

    # C. MACD slope -- needs a PRIOR cycle's reading for this exact
    # symbol; the very first time a symbol is seen in this session,
    # there is nothing to compare against, so this is UNKNOWN, not
    # guessed as PASS or REJECT.
    prev = _macd_cycle_tracker.get(sym)
    if prev is not None:
        macd_rising = macd > prev["macd"]
        if action == "BUY":
            out["candidate_c"] = "PASS" if macd_rising else "REJECT"
        else:
            out["candidate_c"] = "PASS" if not macd_rising else "REJECT"
        out["candidate_c_reason"] = f"macd={macd:.4f} vs previous_cycle_macd={prev['macd']:.4f}"
    else:
        out["candidate_c"] = "UNKNOWN"
        out["candidate_c_reason"] = "no prior cycle reading for this symbol yet this session"
    _macd_cycle_tracker[sym] = {"macd": macd, "date": datetime.now().strftime("%Y-%m-%d")}

    # D. Directional RSI -- 50 is RSI's own conventional midpoint
    # (bullish/bearish split), not an invented threshold.
    if action == "BUY":
        out["candidate_d"] = "PASS" if rsi > 50 else "REJECT"
    else:
        out["candidate_d"] = "PASS" if rsi < 50 else "REJECT"
    out["candidate_d_reason"] = f"rsi={rsi:.1f}"

    # E. Direction-aware volume -- high volume AND today's own move
    # agreeing with the claimed direction, not volume alone.
    high_vol = vol >= vol_avg * 1.5 if vol_avg else False
    directional_move = (change_percent > 0) if action == "BUY" else (change_percent < 0)
    out["candidate_e"] = "PASS" if (high_vol and directional_move) else "REJECT"
    out["candidate_e_reason"] = f"volume_ratio={(vol/vol_avg):.2f}x, change_percent={change_percent:+.2f}%" if vol_avg else "volume_avg unavailable"

    # F. ADX minimum trend-strength -- same 25 threshold already live
    # (as REQUIRE_ADX_TREND_STRENGTH, off by default) -- this records
    # what it WOULD have decided regardless of that flag's state, so
    # shadow evidence keeps accumulating even while the real flag is off.
    out["candidate_f"] = "PASS" if adx >= 25 else "REJECT"
    out["candidate_f_reason"] = f"adx={adx:.1f}"

    # G. Target Room -- is Target 3 realistic given the actual nearest
    # resistance (BUY) / support (SELL), or does it project straight
    # through a real structural level with no awareness it's there?
    if resistance is not None and support is not None and stock_t3 is not None:
        if action == "BUY":
            out["candidate_g"] = "PASS" if resistance > stock_t3 else "REJECT"
        else:
            out["candidate_g"] = "PASS" if support < stock_t3 else "REJECT"
        out["candidate_g_reason"] = f"stock_t3={stock_t3:.2f}, support={support:.2f}, resistance={resistance:.2f}"
    else:
        out["candidate_g"] = "UNKNOWN"
        out["candidate_g_reason"] = "support/resistance unavailable this cycle"

    # H. Entry Structure -- is entry genuinely closer to support than
    # resistance (BUY -- more room up than down to a floor), or closer
    # to resistance than support (SELL)?
    if resistance is not None and support is not None and resistance != support:
        dist_to_support = abs(price - support)
        dist_to_resistance = abs(resistance - price)
        if action == "BUY":
            out["candidate_h"] = "PASS" if dist_to_support < dist_to_resistance else "REJECT"
        else:
            out["candidate_h"] = "PASS" if dist_to_resistance < dist_to_support else "REJECT"
        out["candidate_h_reason"] = f"price={price:.2f}, support={support:.2f}, resistance={resistance:.2f}"
    else:
        out["candidate_h"] = "UNKNOWN"
        out["candidate_h_reason"] = "support/resistance unavailable or identical this cycle"

    # I. Market/Sector Alignment -- reuses quality_engine's own
    # evaluate_sector_alignment() rather than inventing new logic; that
    # function is already real, tested, and fed by data already
    # computed live every cycle (sector_change_map/nifty_change_pct) --
    # it was just never wired into the core V3 signal or this shadow
    # framework before now. ALIGNED -> PASS, CONFLICT -> REJECT;
    # NEUTRAL and INSUFFICIENT_DATA both map to UNKNOWN here (NEUTRAL
    # is a genuine real state, not a data gap, but it doesn't
    # constitute either confirmation or rejection).
    #
    # Sep 16 2026: REAL BUG FOUND live -- this was `import quality_engine
    # as qe` (absolute), which fails every single cycle with "No module
    # named 'quality_engine'" because it's not a top-level module, it's
    # a submodule of this same Django app package. Every other import
    # of this exact module elsewhere in this file (4 other call sites)
    # correctly uses the relative form -- matched here.
    from . import quality_engine as qe
    sector_result = qe.evaluate_sector_alignment(action, change_percent, sector_change_pct, nifty_change_pct)
    if sector_result["state"] == "ALIGNED":
        out["candidate_i"] = "PASS"
    elif sector_result["state"] == "CONFLICT":
        out["candidate_i"] = "REJECT"
    else:
        out["candidate_i"] = "UNKNOWN"
    out["candidate_i_reason"] = f"state={sector_result['state']}, is_leader={sector_result['is_leader']}, stock={change_percent}%, sector={sector_change_pct}%, nifty={nifty_change_pct}%"

    # J. Fresh OI Confirmation re-validation -- Sep 16 2026, added per
    # explicit request for real, evidence-based improvement ideas,
    # found during a full forensic pass of this repository.
    #
    # DIFFERENT PURPOSE from candidates A-I above: those all propose
    # NEW filters this project doesn't have yet. This one instead
    # RE-TESTS an EXISTING, ALREADY-LIVE scoring component -- the +20
    # OI CONFIRMED bonus in _build_all()'s own scoring block -- against
    # fresh, ongoing data, because the only evidence questioning it is
    # old: this project's own screener/check_oi_confirmation_score_bias.py
    # already found CONFIRMED's median base score equals NEUTRAL's
    # exactly, and NEUTRAL-labeled trades outperformed CONFIRMED
    # trades roughly 8x in real per-trade P&L -- but that finding has
    # an unknown date and unknown sample recency. Rather than touch
    # the live +20 bonus on stale evidence (exactly what this whole
    # project's own shadow-mode discipline exists to prevent), this
    # feeds the SAME real signal stream through the SAME
    # generate_shadow_comparison_report() evidence-bar machinery
    # already proven for candidates A-I, so a decision here will be
    # based on current data, not a historical snapshot of unknown age.
    #
    # PASS = this signal's OI was CONFIRMED (the live bonus fired).
    # REJECT = OI was NEUTRAL (no bonus). UNKNOWN = no live option
    # chain was available this cycle (NO_DATA) -- never guessed.
    if oi_confirmation == "CONFIRMED":
        out["candidate_j"] = "PASS"
    elif oi_confirmation == "NEUTRAL":
        out["candidate_j"] = "REJECT"
    else:
        out["candidate_j"] = "UNKNOWN"
    out["candidate_j_reason"] = f"oi_confirmation={oi_confirmation} (re-validating the existing live +20 score bonus against fresh data, not proposing a new filter)"

    return out


def _recurrence_status(prior_signal_count):
    """
    Sep 12 2026: NEW / RECURRING / HIGH_FREQUENCY_RECURRING bucketing.
    The 1-2 / 3+ thresholds are a round, conservative starting point,
    NOT statistically derived -- the forensic audit's real sample
    (n=8 first-occurrence, n=9 later) is nowhere near large enough to
    fit a real threshold from data. This exists so shadow logging can
    start accumulating evidence on where a real threshold should sit,
    not because 3 is a proven cutoff.
    """
    if not prior_signal_count:
        return "NEW"
    return "HIGH_FREQUENCY_RECURRING" if prior_signal_count >= 3 else "RECURRING"


def _build_shadow_assessment(recurrence_status):
    """
    Sep 12 2026: generic actual/shadow framework (spec section 9) --
    built for the recurrence rule specifically, since it's the only one
    with any real evidence behind it so far. The SAME {actual_decision,
    shadow_decision, shadow_block_reason} shape is meant to be reused
    for every future filter (market/sector/OI/structure/time/
    liquidity) once each has real data to evaluate against, not
    reinvented per filter.

    actual_decision is always 'PASS' -- nothing here blocks anything;
    RECURRENCE_PENALTY defaults False. shadow_decision reflects what
    WOULD happen if it were flipped on, purely for logging.
    """
    shadow_penalty = 0
    shadow_decision = "PASS"
    shadow_block_reason = None
    if recurrence_status in ("RECURRING", "HIGH_FREQUENCY_RECURRING") and SNIPER_V2_CONFIG["RECURRENCE_TRACKING"]:
        # Sep 12 2026: provisional penalty size, NOT statistically
        # derived -- flagged explicitly, same reasoning as
        # _recurrence_status()'s own threshold above. Exists to let
        # shadow logging start accumulating evidence on what size
        # would actually help.
        shadow_penalty = 20 if recurrence_status == "HIGH_FREQUENCY_RECURRING" else 10
        if SNIPER_V2_CONFIG["RECURRENCE_PENALTY"]:
            shadow_decision = "WOULD_BLOCK"
            shadow_block_reason = "RECURRENT_SYMBOL"
        else:
            shadow_decision = "PASS_SHADOW_FLAGGED"
    return {
        "actual_decision": "PASS",
        "shadow_decision": shadow_decision,
        "shadow_block_reason": shadow_block_reason,
        "shadow_recurrence_penalty": shadow_penalty,
    }


def _update_symbol_state_and_classify(sym, action, locked, entry, sl, target1, option_symbol):
    """
    Sep 12 2026 (revision 2): now delegates the actual classification to
    excel_logger.classify_signal_event(), which has the real persisted
    evidence (existing row state, cooldown timing, and real resolved-
    outcome history) needed to distinguish EXACT_DUPLICATE/
    SAME_SETUP_RETRIGGER/GENUINE_REENTRY from UNKNOWN -- this function's
    own in-memory view of a single cycle could never honestly determine
    those on its own (the explicit gap the previous revision flagged
    and left unresolved). Still owns the same-day signals_fired_today
    counter, since that's genuinely this file's own concern (a
    session-scoped observation), not persisted state.

    Returns (classification, day_state, hist):
      classification -- one of 'EXACT_DUPLICATE' / 'SAME_SETUP_RETRIGGER'
        / 'GENUINE_REENTRY' / 'NEW_SETUP' / 'UNKNOWN', or None when
        excel_logger reports 'ACTIVE' (the same signal is just
        continuing, not a new candidate event to classify at all).
    """
    today = datetime.now().strftime("%Y-%m-%d")
    now_iso = datetime.now().isoformat()

    if not SNIPER_V2_CONFIG["RECURRENCE_TRACKING"]:
        return None, None, None

    day_state = _symbol_daily_state.get(sym)
    if day_state is None or day_state.get('date') != today:
        day_state = {'date': today, 'signals_fired_today': 0, 'first_signal_time': now_iso, 'latest_signal_time': now_iso}
        _symbol_daily_state[sym] = day_state
    else:
        day_state['latest_signal_time'] = now_iso

    try:
        from . import excel_logger
        classification = excel_logger.classify_signal_event(sym, action, option_symbol)
    except Exception as e:
        print(f"[SNIPER V2] classify_signal_event failed for {sym}: {e}")
        classification = 'UNKNOWN'

    if classification == 'ACTIVE':
        return None, day_state, _symbol_recurrence_history.get(sym)

    day_state['signals_fired_today'] += 1

    # Session-only supplement -- still populated for the older
    # symbol_first_seen_this_session/symbol_prior_occurrences_this_session
    # fields read at the call site; excel_logger's classify_signal_event()
    # above is the authoritative classification source now, not this.
    hist = _symbol_recurrence_history.get(sym)
    if hist is None:
        hist = {'first_seen_date': today, 'last_seen_date': today, 'occurrences': []}
        _symbol_recurrence_history[sym] = hist
    hist['last_seen_date'] = today
    hist['occurrences'].append({'date': today, 'action': action, 'option_symbol': option_symbol})

    return classification, day_state, hist

_last_fetch = 0
CACHE_TTL = 60

# ============================================================
# STOCKS
# ============================================================
# FNO_STOCKS/SECTORS replaced this round -- previous list (201 symbols,
# built from a mix of a live-verified batch + general domain knowledge)
# checked programmatically against a real, authoritative F&O list the
# user provided directly (208 symbols, includes real F&O lot sizes and
# NEW-addition flags). Found 53 real symbols missing entirely (several
# of them recent F&O additions: BAJAJHLDNG, COCHINSHIP, FORCEMOT,
# GODFRYPHLP, GVT&D, HYUNDAI, MOTILALOFS, NAM-INDIA, PREMIERENE, RADICO,
# SWIGGY, VMM, WAAREEENER) and 46 symbols that were in the old list but
# NOT on this authoritative one (likely stale/no-longer-eligible, or
# scope mismatches from the earlier domain-knowledge-based additions).
# Replaced entirely with the user-provided 208, aligning to it as the
# source of truth rather than keeping a fuzzy union of both. One
# correction made to the source: it listed "LTM" for LTIMindtree, which
# does not match the real NSE ticker (LTIM, already well-established in
# this project) -- treated as a likely typo in the source and corrected
# rather than added as a second, wrong entry.
FNO_STOCKS = [
    "360ONE", "ABB", "ABCAPITAL", "ADANIENSOL", "ADANIENT", "ADANIGREEN",
    "ADANIPORTS", "ADANIPOWER", "ALKEM", "AMBER", "AMBUJACEM", "ANGELONE",
    "APLAPOLLO", "APOLLOHOSP", "ASHOKLEY", "ASIANPAINT", "ASTRAL", "AUBANK",
    "AUROPHARMA", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV", "BAJAJHLDNG",
    "BAJFINANCE", "BANDHANBNK", "BANKBARODA", "BANKINDIA", "BDL", "BEL",
    "BHARATFORG", "BHARTIARTL", "BHEL", "BIOCON", "BLUESTARCO", "BOSCHLTD",
    "BPCL", "BRITANNIA", "BSE", "CAMS", "CANBK", "CDSL", "CGPOWER",
    "CHOLAFIN", "CIPLA", "COALINDIA", "COCHINSHIP", "COFORGE", "COLPAL",
    "CONCOR", "CROMPTON", "CUMMINSIND", "DABUR", "DALBHARAT", "DELHIVERY",
    "DIVISLAB", "DIXON", "DLF", "DMART", "DRREDDY", "EICHERMOT", "ETERNAL",
    "FEDERALBNK", "FORCEMOT", "FORTIS", "GAIL", "GVT&D", "GLENMARK",
    "GMRAIRPORT", "GODFRYPHLP", "GODREJCP", "GODREJPROP", "GRASIM", "HAL",
    "HAVELLS", "HCLTECH", "HDFCAMC", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDPETRO", "HINDUNILVR", "HINDZINC", "HYUNDAI", "ICICIBANK",
    "ICICIGI", "ICICIPRULI", "IDEA", "IDFCFIRSTB", "IEX", "INDHOTEL",
    "INDIANB", "INDIGO", "INDUSINDBK", "INDUSTOWER", "INFY", "INOXWIND",
    "IOC", "IREDA", "IRFC", "ITC", "JINDALSTEL", "JIOFIN", "JSWENERGY",
    "JSWSTEEL", "JUBLFOOD", "KALYANKJIL", "KAYNES", "KEI", "KFINTECH",
    "KOTAKBANK", "KPITTECH", "LAURUSLABS", "LICHSGFIN", "LICI", "LODHA", "LT",
    "LTF", "LTIM", "LUPIN", "M&M", "MANAPPURAM", "MANKIND", "MARICO",
    "MARUTI", "MAXHEALTH", "MAZDOCK", "MCX", "MFSL", "MOTHERSON",
    "MOTILALOFS", "MPHASIS", "MUTHOOTFIN", "NAM-INDIA", "NATIONALUM",
    "NAUKRI", "NBCC", "NESTLEIND", "NHPC", "NMDC", "NTPC", "NYKAA",
    "OBEROIRLTY", "OFSS", "OIL", "ONGC", "PAGEIND", "PATANJALI", "PAYTM",
    "PERSISTENT", "PETRONET", "PFC", "PGEL", "PHOENIXLTD", "PIDILITIND",
    "PIIND", "PNB", "PNBHOUSING", "POLICYBZR", "POLYCAB", "POWERGRID",
    "POWERINDIA", "PREMIERENE", "PRESTIGE", "RADICO", "RBLBANK", "RECLTD",
    "RELIANCE", "RVNL", "SAIL", "SBICARD", "SBILIFE", "SBIN", "SHREECEM",
    "SHRIRAMFIN", "SIEMENS", "SOLARINDS", "SONACOMS", "SRF", "SUNPHARMA",
    "SUPREMEIND", "SUZLON", "SWIGGY", "TATACONSUM", "TATAELXSI", "TMPV",
    "TATAPOWER", "TATASTEEL", "TCS", "TECHM", "TIINDIA", "TITAN",
    "TORNTPHARM", "TRENT", "TVSMOTOR", "ULTRACEMCO", "UNIONBANK", "UNITDSPR",
    "UNOMINDA", "UPL", "VBL", "VEDL", "VMM", "VOLTAS", "WAAREEENER", "WIPRO",
    "YESBANK", "ZYDUSLIFE",
]

SECTORS = {
    "360ONE": "Finance", "ABB": "Capital Goods", "ABCAPITAL": "Finance",
    "ADANIENSOL": "Power", "ADANIENT": "Conglomerate", "ADANIGREEN": "Power",
    "ADANIPORTS": "Logistics", "ADANIPOWER": "Power", "ALKEM": "Pharma",
    "AMBER": "Consumer Durables", "AMBUJACEM": "Cement", "ANGELONE": "Finance",
    "APLAPOLLO": "Metals", "APOLLOHOSP": "Healthcare", "ASHOKLEY": "Auto",
    "ASIANPAINT": "Paints", "ASTRAL": "Plastics", "AUBANK": "Banking", "AUROPHARMA": "Pharma",
    "AXISBANK": "Banking", "BAJAJ-AUTO": "Auto", "BAJAJFINSV": "Finance",
    "BAJAJHLDNG": "Finance", "BAJFINANCE": "Finance", "BANDHANBNK": "Banking",
    "BANKBARODA": "Banking", "BANKINDIA": "Banking", "BDL": "Defence", "BEL": "Defence",
    "BHARATFORG": "Auto Anc", "BHARTIARTL": "Telecom", "BHEL": "Capital Goods",
    "BIOCON": "Pharma", "BLUESTARCO": "Consumer Durables", "BOSCHLTD": "Auto Anc",
    "BPCL": "Energy", "BRITANNIA": "FMCG", "BSE": "Finance", "CAMS": "Finance",
    "CANBK": "Banking", "CDSL": "Finance", "CGPOWER": "Capital Goods", "CHOLAFIN": "Finance",
    "CIPLA": "Pharma", "COALINDIA": "Mining", "COCHINSHIP": "Defence", "COFORGE": "IT",
    "COLPAL": "FMCG", "CONCOR": "Logistics", "CROMPTON": "Consumer Durables",
    "CUMMINSIND": "Capital Goods", "DABUR": "FMCG", "DALBHARAT": "Cement",
    "DELHIVERY": "Logistics", "DIVISLAB": "Pharma", "DIXON": "Consumer Durables",
    "DLF": "Realty", "DMART": "Retail", "DRREDDY": "Pharma", "EICHERMOT": "Auto",
    "ETERNAL": "New Age Tech", "FEDERALBNK": "Banking", "FORCEMOT": "Auto",
    "FORTIS": "Healthcare", "GAIL": "Energy", "GVT&D": "Capital Goods", "GLENMARK": "Pharma",
    "GMRAIRPORT": "Infra", "GODFRYPHLP": "FMCG", "GODREJCP": "FMCG", "GODREJPROP": "Realty",
    "GRASIM": "Cement", "HAL": "Defence", "HAVELLS": "Consumer Durables", "HCLTECH": "IT",
    "HDFCAMC": "Finance", "HDFCBANK": "Banking", "HDFCLIFE": "Insurance",
    "HEROMOTOCO": "Auto", "HINDALCO": "Metals", "HINDPETRO": "Energy", "HINDUNILVR": "FMCG",
    "HINDZINC": "Metals", "HYUNDAI": "Auto", "ICICIBANK": "Banking", "ICICIGI": "Insurance",
    "ICICIPRULI": "Insurance", "IDEA": "Telecom", "IDFCFIRSTB": "Banking", "IEX": "Power",
    "INDHOTEL": "Tourism", "INDIANB": "Banking", "INDIGO": "Aviation",
    "INDUSINDBK": "Banking", "INDUSTOWER": "Telecom", "INFY": "IT", "INOXWIND": "Power",
    "IOC": "Energy", "IREDA": "Finance", "IRFC": "Finance", "ITC": "FMCG",
    "JINDALSTEL": "Metals", "JIOFIN": "Finance", "JSWENERGY": "Power", "JSWSTEEL": "Metals",
    "JUBLFOOD": "Food", "KALYANKJIL": "Jewellery", "KAYNES": "Electronics",
    "KEI": "Capital Goods", "KFINTECH": "Finance", "KOTAKBANK": "Banking", "KPITTECH": "IT",
    "LAURUSLABS": "Pharma", "LICHSGFIN": "Finance", "LICI": "Insurance", "LODHA": "Realty",
    "LT": "Infra", "LTF": "Finance", "LTIM": "IT", "LUPIN": "Pharma", "M&M": "Auto",
    "MANAPPURAM": "Finance", "MANKIND": "Pharma", "MARICO": "FMCG", "MARUTI": "Auto",
    "MAXHEALTH": "Healthcare", "MAZDOCK": "Defence", "MCX": "Finance", "MFSL": "Insurance",
    "MOTHERSON": "Auto Anc", "MOTILALOFS": "Finance", "MPHASIS": "IT",
    "MUTHOOTFIN": "Finance", "NAM-INDIA": "Finance", "NATIONALUM": "Metals",
    "NAUKRI": "E-Commerce", "NBCC": "Infra", "NESTLEIND": "FMCG", "NHPC": "Power",
    "NMDC": "Mining", "NTPC": "Power", "NYKAA": "E-Commerce", "OBEROIRLTY": "Realty",
    "OFSS": "IT", "OIL": "Energy", "ONGC": "Energy", "PAGEIND": "Textile",
    "PATANJALI": "FMCG", "PAYTM": "Fintech", "PERSISTENT": "IT", "PETRONET": "Energy",
    "PFC": "Finance", "PGEL": "Electronics", "PHOENIXLTD": "Realty",
    "PIDILITIND": "Chemicals", "PIIND": "Agro", "PNB": "Banking", "PNBHOUSING": "Finance",
    "POLICYBZR": "Fintech", "POLYCAB": "Consumer Durables", "POWERGRID": "Power",
    "POWERINDIA": "Capital Goods", "PREMIERENE": "Power", "PRESTIGE": "Realty",
    "RADICO": "Alcohol", "RBLBANK": "Banking", "RECLTD": "Finance", "RELIANCE": "Energy",
    "RVNL": "Infra", "SAIL": "Metals", "SBICARD": "Finance", "SBILIFE": "Insurance",
    "SBIN": "Banking", "SHREECEM": "Cement", "SHRIRAMFIN": "Finance",
    "SIEMENS": "Capital Goods", "SOLARINDS": "Chemicals", "SONACOMS": "Auto Anc",
    "SRF": "Chemicals", "SUNPHARMA": "Pharma", "SUPREMEIND": "Plastics", "SUZLON": "Power",
    "SWIGGY": "New Age Tech", "TATACONSUM": "FMCG", "TATAELXSI": "IT", "TMPV": "Auto",
    "TATAPOWER": "Power", "TATASTEEL": "Metals", "TCS": "IT", "TECHM": "IT",
    "TIINDIA": "Auto Anc", "TITAN": "Consumer Durables", "TORNTPHARM": "Pharma",
    "TRENT": "Retail", "TVSMOTOR": "Auto", "ULTRACEMCO": "Cement", "UNIONBANK": "Banking",
    "UNITDSPR": "Beverages", "UNOMINDA": "Auto Anc", "UPL": "Agro", "VBL": "Beverages",
    "VEDL": "Metals", "VMM": "Retail", "VOLTAS": "Consumer Durables", "WAAREEENER": "Power",
    "WIPRO": "IT", "YESBANK": "Banking", "ZYDUSLIFE": "Pharma",
}


# ============================================================
# INDEX + STOCK DATA (Fyers ONLY -- no Yahoo/yfinance involved at all)
# ============================================================

FYERS_INDEX_SYMBOLS = {
    "NIFTY 50": "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "INDIA VIX": "NSE:INDIAVIX-INDEX",
    # Sep 11 2026: added for the Market Banner's new SENSEX card. Both
    # _fetch_index() and _fetch_indices_batched() below already loop
    # over this dict generically, so no changes needed to either --
    # only the two call sites that unpack specific keys by name
    # (_build_all(), _index_snapshot_worker()) need a matching update.
    "SENSEX": "BSE:SENSEX-INDEX",
}


def _fetch_index(name, fallbacks=None):
    """Index quote (NIFTY/BANKNIFTY/VIX) via Fyers only. No yfinance
    fallback -- if Fyers isn't authenticated or doesn't return this
    index, we return a zeroed placeholder instead of quietly pulling
    from Yahoo.

    Aug 20 2026: this used to fall through to the zeroed placeholder
    completely silently whenever Fyers responded but with resp['s'] !=
    'ok' (not an exception -- a real response Fyers just didn't mark as
    ok), or responded 'ok' with no usable item inside. That's a
    different, narrower failure than is_authenticated() itself being
    false (which already logs) -- confirmed live: indices sat at 0.00
    across multiple fresh-restart cycles with NEITHER the auth-gate log
    below NOR an exception ever printing, meaning execution was reaching
    here through one of these two silent paths. Now both log the actual
    Fyers response so the real reason is visible next time instead of
    just "it's zero, no idea why."
    """
    fyers_symbol = FYERS_INDEX_SYMBOLS.get(name)
    if fyers_symbol and is_authenticated():
        try:
            resp = get_quotes([fyers_symbol])
            if resp and resp.get('s') == 'ok':
                for item in resp.get('d', []):
                    if item.get('s') != 'ok':
                        continue
                    v = item.get('v', {}) or {}
                    price = v.get('lp')
                    if price and not (isinstance(price, float) and math.isnan(price)):
                        return {
                            'price': round(price, 2),
                            'change': round(v.get('ch', 0) or 0, 2),
                            'change_percent': round(v.get('chp', 0) or 0, 2),
                        }
                print(f"[Fyers] Index fetch {name}: response was 'ok' but no usable price in it -- {resp}")
            else:
                print(f"[Fyers] Index fetch {name}: response not ok -- {resp}")
        except Exception as e:
            print(f"[Fyers] Index fetch error {name}: {e}")
    else:
        print(f"[Fyers] Not authenticated -- skipping index {name} (no Yahoo fallback)")
    return {'price': 0, 'change': 0, 'change_percent': 0}


def _fetch_indices_batched():
    """
    Sep 3 2026: real bug -- NIFTY/BANKNIFTY/VIX used to be fetched via 3
    SEPARATE _fetch_index() calls below, each its own get_quotes()
    round-trip to Fyers, instead of 1 batched call for all 3 symbols
    together -- unlike fetch_broader_indices() above, which already
    batches its own (unrelated) set of index symbols correctly in one
    call. Confirmed live (screenshots, 09:15:43-09:20:19 Sep 3):
    continuous 429s on every quote call including these -- firing 3
    calls where 1 would do adds real, avoidable load onto an already-
    strained rate limit, every single cycle (60s in
    _index_snapshot_worker, up to 90s+ in _build_all).

    Same per-index parsing and zeroed-placeholder-with-logging fallback
    as _fetch_index() -- one index missing/unusable in the batch doesn't
    affect the others -- just done as one network round-trip for all 3
    instead of three.
    """
    zeroed = {'price': 0, 'change': 0, 'change_percent': 0}
    out = {name: dict(zeroed) for name in FYERS_INDEX_SYMBOLS}

    if not is_authenticated():
        print("[Fyers] Not authenticated -- skipping batched index fetch (no Yahoo fallback)")
        return out

    fyers_symbols = list(FYERS_INDEX_SYMBOLS.values())
    symbol_to_name = {v: k for k, v in FYERS_INDEX_SYMBOLS.items()}
    try:
        resp = get_quotes(fyers_symbols)
    except Exception as e:
        print(f"[Fyers] Batched index fetch error: {e}")
        return out

    if not resp or resp.get('s') != 'ok':
        print(f"[Fyers] Batched index fetch: response not ok -- {resp}")
        return out

    seen = set()
    for item in resp.get('d', []):
        if item.get('s') != 'ok':
            continue
        fyers_sym = item.get('n')
        name = symbol_to_name.get(fyers_sym)
        if not name:
            continue
        v = item.get('v', {}) or {}
        price = v.get('lp')
        if price and not (isinstance(price, float) and math.isnan(price)):
            out[name] = {
                'price': round(price, 2),
                'change': round(v.get('ch', 0) or 0, 2),
                'change_percent': round(v.get('chp', 0) or 0, 2),
            }
            seen.add(name)

    missing = set(FYERS_INDEX_SYMBOLS) - seen
    if missing:
        print(f"[Fyers] Batched index fetch: no usable price for {sorted(missing)} -- {resp}")

    return out


# Aug 28 2026: SEPARATE dict from FYERS_INDEX_SYMBOLS above -- these
# broader indices (Next 50, 100, Midcap 100, Smallcap 100) are NOT
# verified against a live Fyers connection the way NIFTY50/BANKNIFTY/
# VIX are (those are proven, deployed, working in this project for
# weeks). Evidence they exist under this exact "NSE:<NAME>-INDEX"
# convention comes from generic NSE index-symbol documentation
# (matching the same pattern already proven for NIFTY50/BANKNIFTY),
# NOT a confirmed Fyers-specific test. Kept in a fully separate dict
# and function from the core index fetch deliberately -- if any of
# these turn out wrong, that failure is fully isolated and can never
# affect the already-working NIFTY50/BANKNIFTY/VIX cards.
BROADER_INDEX_SYMBOLS = {
    "NIFTY Next 50": "NSE:NIFTYNXT50-INDEX",
    "NIFTY 100": "NSE:NIFTY100-INDEX",
    "NIFTY Midcap 100": "NSE:NIFTYMIDCAP100-INDEX",
    "NIFTY Smallcap 100": "NSE:NIFTYSMLCAP100-INDEX",
}


def fetch_broader_indices():
    """
    Real quotes for the broader NSE indices shown on Market View's
    Indices Performance table -- a fully separate fetch path from
    _fetch_index() above, batched in one call (same batch pattern as
    _fetch_all_quotes_fyers, field 'n' for the returned symbol).

    Each symbol here is genuinely UNVERIFIED against a live Fyers
    connection (see BROADER_INDEX_SYMBOLS' own comment) -- this
    degrades gracefully: whichever symbols come back with a real,
    usable price are returned; whichever don't are simply OMITTED
    from the result, never a zeroed placeholder standing in for real
    data. The frontend only ever renders what's actually here, so an
    unresolved symbol just means one fewer row, not a broken table.
    """
    if not is_authenticated():
        return {}
    symbols = list(BROADER_INDEX_SYMBOLS.values())
    symbol_to_name = {v: k for k, v in BROADER_INDEX_SYMBOLS.items()}
    try:
        resp = get_quotes(symbols)
    except Exception as e:
        print(f"[Fyers] Broader indices fetch error: {e}")
        return {}
    if not resp or resp.get('s') != 'ok':
        print(f"[Fyers] Broader indices fetch: response not ok -- {resp}")
        return {}

    results = {}
    for item in resp.get('d', []):
        if item.get('s') != 'ok':
            continue
        fyers_sym = item.get('n')
        name = symbol_to_name.get(fyers_sym)
        if not name:
            continue
        v = item.get('v', {}) or {}
        price = v.get('lp')
        if price is None or price <= 0 or (isinstance(price, float) and math.isnan(price)):
            continue
        results[name] = {
            'name': name,
            'price': round(price, 2),
            'change': round(v.get('ch', 0) or 0, 2),
            'change_percent': round(v.get('chp', 0) or 0, 2),
        }
    return results


def _fetch_all_quotes_fyers(symbols):
    """
    Batch-fetch current price/change/volume for every symbol via Fyers
    quotes (up to 50 symbols per call -- Fyers' documented batch limit),
    instead of one yfinance call per stock. This is the PRIMARY price
    source now. Returns {symbol: stock_dict} for whatever came back OK;
    silently drops anything that failed or came back with a NaN/zero
    price rather than raising.

    Aug 20 2026: the whole-batch "resp['s'] != 'ok'" case used to fall
    through with zero logging, same silent-failure shape as
    _fetch_index() above and confirmed live the same way -- the whole
    208-stock scan came back empty across multiple fresh-restart cycles
    with no exception and no batch-error print anywhere, while OTHER
    Fyers endpoints (option chains, Index Tracker's Market Depth calls)
    kept working at the same moment. This points at Fyers' plain
    /quotes endpoint specifically, not a broad auth/connectivity
    problem -- now logs the actual response so that's visible instead
    of assumed.
    """
    results = {}
    fyers_symbols = [f"NSE:{s}-EQ" for s in symbols]
    for i in range(0, len(fyers_symbols), 50):
        batch = fyers_symbols[i:i + 50]
        if i > 0:
            # Sep 3 2026: real bug -- these 5 batches (208 stocks / 50
            # per batch) used to fire back-to-back with zero delay,
            # unlike eod_scanner.py's already-paced version. Confirmed
            # live (09:15:43-09:20:19 Sep 3 screenshots) contributing to
            # continuous 429s. Skipped before the FIRST batch only --
            # no point delaying a fresh cycle's opening call.
            time.sleep(0.4)
        try:
            resp = get_quotes(batch)
        except Exception as e:
            print(f"[Fyers] Quotes batch error: {e}")
            continue
        if not resp or resp.get('s') != 'ok':
            print(f"[Fyers] Quotes batch {i}-{i + len(batch)}: response not ok -- {resp}")
            continue
        for item in resp.get('d', []):
            if item.get('s') != 'ok':
                continue
            v = item.get('v', {}) or {}
            sym = (item.get('n') or '').replace('NSE:', '').replace('-EQ', '')
            price = v.get('lp')
            if not sym or price is None or price <= 0 or (isinstance(price, float) and math.isnan(price)):
                continue
            results[sym] = {
                'symbol': sym, 'name': sym,
                'price': round(price, 2),
                'change': round(v.get('ch', 0) or 0, 2),
                'change_percent': round(v.get('chp', 0) or 0, 2),
                'open': v.get('open_price', price) or price,
                'high': v.get('high_price', price) or price,
                'low': v.get('low_price', price) or price,
                'close': round(price, 2),
                'volume': int(v.get('volume') or 0),
                'sector': SECTORS.get(sym, 'Unknown'),
            }
    return results


def _fetch_all_stocks(symbols):
    """
    Fyers ONLY -- batched quotes, up to 50 symbols per call. No Yahoo/
    yfinance fallback at all, per explicit request: if Fyers isn't
    authenticated, this cycle simply returns whatever it has (which may
    be nothing) rather than quietly pulling from Yahoo. This is also why
    "possibly delisted" errors are gone -- Fyers uses NSE's current live
    symbol list directly, so a correctly-named stock never hits that
    problem the way Yahoo's mirror did.
    """
    if not is_authenticated():
        print("[Scanner] Fyers not authenticated -- no data this cycle (no Yahoo fallback)")
        return {}
    return _fetch_all_quotes_fyers(symbols)


def _compute_indicators(close, high, low, volume):
    """
    Pure indicator math -- takes pandas Series (Close/High/Low/Volume),
    returns the same dict _calc_tech always has. Split out from the fetch
    logic so it's independently testable regardless of data source.
    """
    if len(close) < 20:
        return None

    # RSI (14)
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi = float(100 - (100 / (1 + rs.iloc[-1])))

    # VWAP
    typical = (high + low + close) / 3
    vwap = float((typical * volume).cumsum().iloc[-1] / volume.cumsum().iloc[-1])

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = float(ema12.iloc[-1] - ema26.iloc[-1])

    # ATR (14)
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = float(tr.rolling(window=14).mean().iloc[-1])

    # ADX (14) -- trend STRENGTH (not direction), via Wilder's smoothing
    period = 14
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    tr_smooth = tr.ewm(com=period - 1, adjust=False).mean().replace(0, np.nan)
    plus_di = 100 * (plus_dm.ewm(com=period - 1, adjust=False).mean() / tr_smooth)
    minus_di = 100 * (minus_dm.ewm(com=period - 1, adjust=False).mean() / tr_smooth)
    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    adx_val = dx.ewm(com=period - 1, adjust=False).mean().iloc[-1]
    adx = float(adx_val) if pd.notna(adx_val) else 0.0

    # Sep 8 2026: +DI/-DI were already computed above (needed for ADX
    # itself) but discarded before returning -- exposing them now for
    # the new quality engine's ADX+direction classifier (spec: "ADX
    # alone is not a bullish score, use ADX strength + DI+ > DI-").
    # Same NaN-safety pattern already applied to adx itself just above
    # (tr_smooth can be 0->NaN on a genuinely flat-range day) -- without
    # this, a flat day would raise where adx's own fallback already
    # protects it.
    plus_di_val = plus_di.iloc[-1]
    minus_di_val = minus_di.iloc[-1]
    plus_di_final = float(plus_di_val) if pd.notna(plus_di_val) else 0.0
    minus_di_final = float(minus_di_val) if pd.notna(minus_di_val) else 0.0

    # EMA20/EMA50 -- new, for the quality engine's price-structure/
    # extension checks. Same span-based EWM as MACD's ema12/ema26
    # above -- EWM doesn't produce leading NaNs the way a
    # rolling(window=X) average does, so this can't newly trigger the
    # NaN guard below for a stock that already had enough history for
    # RSI/MACD/ATR to compute cleanly.
    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])

    # Volume average (20)
    vol_avg = float(volume.rolling(window=20).mean().iloc[-1])

    # Support/Resistance (20-day)
    resistance = float(high.rolling(window=20).max().iloc[-1])
    support = float(low.rolling(window=20).min().iloc[-1])

    # Historical volatility (annualized)
    returns = close.pct_change().dropna()
    hist_vol = float(returns.std() * np.sqrt(252) * 100) if len(returns) else 20.0

    # EMA200 -- Sep 18 2026 addition, for the market-breadth dashboard's
    # "% of names above 200 EMA" tile. Same EWM as ema20/ema50 above,
    # just a longer span -- EWM's own reason for using it there
    # (no leading NaNs from a rolling window) applies identically here.
    ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1]) if len(close) >= 200 else None

    # MACD signal line + histogram -- Sep 18 2026 addition. `macd`
    # above is only the MACD LINE (ema12-ema26); the breadth
    # dashboard's "names sitting on their MACD signal line" tile needs
    # the standard 9-period EMA of that line (the signal line itself),
    # not the line alone -- these are two different, real numbers,
    # and conflating them would misreport this specific metric.
    macd_line_series = ema12 - ema26
    macd_signal = float(macd_line_series.ewm(span=9, adjust=False).mean().iloc[-1])
    macd_histogram = float(macd - macd_signal)

    # Bollinger Band width (20, 2 std) as % of price -- Sep 18 2026
    # addition, for the "ranges are widening" volatility breadth tile.
    # Standard definition: (upper - lower) / middle * 100, where
    # middle is the 20-day SMA and upper/lower are +/-2 standard
    # deviations from it.
    bb_sma20 = close.rolling(window=20).mean()
    bb_std20 = close.rolling(window=20).std()
    bb_width_series = (4 * bb_std20 / bb_sma20) * 100
    bb_width_pct = float(bb_width_series.iloc[-1])

    out = {
        'rsi': rsi, 'vwap': vwap, 'macd': macd, 'atr': atr, 'adx': adx,
        'plus_di': plus_di_final, 'minus_di': minus_di_final,
        'ema20': ema20, 'ema50': ema50, 'ema200': ema200,
        'macd_signal': macd_signal, 'macd_histogram': macd_histogram,
        'bb_width_pct': bb_width_pct,
        'volume_avg': vol_avg, 'resistance': resistance, 'support': support,
        'hist_vol': hist_vol,
    }
    # ema200 is legitimately None for a stock with under 200 days of
    # history (a recent listing) -- that's real missing data, not a
    # computation error, so it's excluded from the NaN-guard below
    # (which exists to catch genuine calculation failures) and left as
    # None for the caller to handle explicitly rather than fabricate.
    if any(isinstance(v, float) and math.isnan(v) for k, v in out.items() if k != 'ema200'):
        return None
    return {k: (round(v, 2) if isinstance(v, (int, float)) else v) for k, v in out.items()}


def _compute_participation_quality(high, low, close, volume, vol_avg):
    """
    Sep 2 2026: Doc 2 Section 8, "upgrade volume into participation
    quality" -- distinguishes genuine buying/selling pressure from
    volume that shows up but gets absorbed with no real follow-
    through. The review doc's own stated examples: "High RVOL + wide
    bullish candle + close near high -> strong participation" and
    "High RVOL + tiny net candle -> possible absorption/indecision."

    Uses CLV (close location value) -- ((close-low)-(high-close))/
    (high-low), ranges -1 (closed at the low) to +1 (closed at the
    high) -- a standard, self-sufficient technical measure. HONEST
    NOTE: the doc's "tiny net candle" language is really about
    close-vs-OPEN (small real body), which _compute_indicators()
    doesn't currently receive (adding it would mean touching that
    function's signature and every call site for a purely
    informational field). CLV -- close landing near the MIDDLE of the
    day's H-L range -- is used here as a reasonable proxy for the same
    underlying idea (an indecisive day that didn't resolve toward
    either extreme), not an identical measure. Tested directly against
    both of the review document's own stated example cases.

    Deliberately fully separate from _compute_indicators() -- that
    function's own NaN-guard drops the WHOLE stock from scoring if any
    of ITS fields come back NaN; a hiccup in this new, purely-
    informational field must never risk that. Never touches live
    signal qualification -- this is exposed as an extra informational
    field only, same boundary as target1_beyond_resistance,
    relative-strength, etc. added earlier today.
    """
    try:
        latest_high = float(high.iloc[-1])
        latest_low = float(low.iloc[-1])
        latest_close = float(close.iloc[-1])
        latest_volume = float(volume.iloc[-1])
    except (IndexError, ValueError, TypeError):
        return None

    if vol_avg is None or vol_avg <= 0:
        return None
    rvol = round(latest_volume / vol_avg, 2)

    day_range = latest_high - latest_low
    if day_range <= 0:
        # Halted, illiquid, or a genuinely flat day -- CLV is
        # undefined, not zero. RVOL is still real and reportable.
        return {"rvol": rvol, "clv": None, "participation_quality": None}

    clv = round(((latest_close - latest_low) - (latest_high - latest_close)) / day_range, 2)

    if rvol >= 1.5 and clv >= 0.5:
        quality = "Strong Participation (Bullish)"
    elif rvol >= 1.5 and clv <= -0.5:
        quality = "Strong Participation (Bearish)"
    elif rvol >= 1.5 and -0.3 < clv < 0.3:
        quality = "Absorption / Indecision"
    elif rvol < 1.2:
        quality = "Normal"
    else:
        quality = "Developing"

    return {"rvol": rvol, "clv": clv, "participation_quality": quality}


def _fyers_history_df(symbol, days=100):
    """~`days` calendar days of daily candles from Fyers, shaped into a
    DataFrame with the same column names yfinance used, so
    _compute_indicators doesn't care which source it came from."""
    range_to = datetime.now().date()
    range_from = range_to - timedelta(days=days)
    try:
        resp = get_history(f"NSE:{symbol}-EQ", resolution="D",
                            range_from=str(range_from), range_to=str(range_to))
    except Exception as e:
        print(f"[Fyers] History error {symbol}: {e}")
        return None
    if not resp or resp.get('s') != 'ok' or not resp.get('candles'):
        return None
    df = pd.DataFrame(resp['candles'], columns=['ts', 'Open', 'High', 'Low', 'Close', 'Volume'])
    return df


# Day-scoped cache: {symbol: {'date': 'YYYY-MM-DD', 'df': historical_df}}.
# Aug 14 2026 addition -- _calc_tech() used to re-fetch 100 days of daily
# candles from Fyers for every one of the day's ~30 top movers, EVERY
# cycle, even though 99 of those 100 days are identical to two minutes
# ago -- only today's candle moves. This caches everything except the
# most recent (today's) row once per symbol per day; _calc_tech appends
# a fresh "today" row built from the quote data _fetch_all_stocks()
# already pulled this cycle, so most cycles now cost ZERO extra Fyers
# calls here, not 30.
#
# Aug 27 2026: also now shared by _cached_index_history_df() below for
# NIFTY/BANKNIFTY's own ATR (index option calls, see index_signal.py) --
# keyed by "NIFTY"/"BANKNIFTY", which never collides with a real F&O
# stock ticker, so one cache dict serves both without any change here.
_history_cache = {}

# Aug 28 2026: SEPARATE from _history_cache above -- that one's cache
# check only looks at symbol+date, not the `days` window requested, so
# reusing it with a different days value here would silently return
# the wrong (100-day, not 365-day) window for a symbol already cached
# by _calc_tech's RSI/ADX/ATR calls. This gets its own dict and its
# own key so a 52-week lookup and a 100-day indicator lookup for the
# same symbol never collide or shadow each other.
_year_history_cache = {}  # {symbol: {'date': 'YYYY-MM-DD', 'high_52w': float, 'low_52w': float}}


def get_52_week_high_low(symbol):
    """
    Real 52-week high/low, computed from ~365 days of Fyers' History
    API daily candles -- confirmed (Aug 28 2026, via Fyers' own
    community forum and the full quotes-response field schema) that
    the Quotes API does NOT provide this directly: high_price/
    low_price there are TODAY's intraday high/low only, not a 52-week
    window. Reuses _fyers_history_df() unchanged, just with a longer
    days window -- no new Fyers call pattern introduced, same fetch
    mechanism already proven all session for RSI/ADX/ATR history.

    Cached once per symbol per day (own dict, see _year_history_cache)
    -- a fresh History API call per symbol on every request would be
    both slow and wasteful; this only re-fetches once per symbol per
    trading day.

    Returns (None, None) if history can't be fetched -- never guesses
    a 52-week range from partial or missing data.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    cached = _year_history_cache.get(symbol)
    if cached and cached.get('date') == today_str:
        return cached['high_52w'], cached['low_52w']

    df = _fyers_history_df(symbol, days=365)
    if df is None or df.empty:
        return None, None

    high_52w = round(float(df['High'].max()), 2)
    low_52w = round(float(df['Low'].min()), 2)
    _year_history_cache[symbol] = {'date': today_str, 'high_52w': high_52w, 'low_52w': low_52w}
    return high_52w, low_52w


def _cached_history_df(symbol, days=100):
    """
    Returns cached daily-candle history for `symbol`, EXCLUDING the most
    recent row -- _calc_tech always replaces that row with a fresh one
    built from this cycle's already-fetched live quote instead. Only
    hits Fyers once per symbol per day; every other call this trading
    day is a pure in-memory lookup.

    Drops the fetched response's LAST row unconditionally, rather than
    trying to identify "today" by comparing dates -- Fyers' candle
    timestamps are raw epoch seconds, and doing that comparison
    correctly needs careful timezone handling (this function runs in the
    machine's local time; naive epoch-to-date conversion defaults to
    UTC) that's easy to get subtly wrong, especially near midnight IST.
    Dropping the last row and replacing it with a definitely-current
    live quote sidesteps that entirely -- and it's consistent with how
    the rest of this file already works: every indicator in
    _compute_indicators reads .iloc[-1] as "today", so the code already
    assumes ascending chronological order with the most recent day last.
    This isn't a new assumption, just acting on the one already baked in.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    cached = _history_cache.get(symbol)
    if cached and cached.get('date') == today_str:
        return cached['df']

    df = _fyers_history_df(symbol, days=days)
    if df is None or df.empty or len(df) < 2:
        return None

    historical = df.iloc[:-1].reset_index(drop=True)
    _history_cache[symbol] = {'date': today_str, 'df': historical}
    return historical


def _cached_index_history_df(name, fyers_symbol, days=100):
    """
    Aug 27 2026: same caching pattern as _cached_history_df() above, but
    for an INDEX's own daily candles -- can't reuse that function
    directly since it hardcodes 'NSE:{symbol}-EQ', which is the wrong
    format for an index (NSE:NIFTY50-INDEX, not NSE:NIFTY50-EQ). Written
    as a separate function rather than modifying the working stock
    version, same "don't risk an already-working caller" principle used
    elsewhere in this project (e.g. index_tracker.py's two separate
    bullion-symbol resolvers).

    Shares the SAME _history_cache dict though, keyed by `name`
    ("NIFTY"/"BANKNIFTY" -- matching index_tracker.py's own naming, not
    FYERS_INDEX_SYMBOLS' "NIFTY 50" key, to keep this module's index
    calls consistent with the Bias/oi data they're paired with). Never
    collides with a real F&O stock ticker.

    Unlike _cached_history_df(), does NOT drop the last row / append a
    live-quote replacement -- this only feeds ATR (index_signal.py's
    SL/Target sizing), which doesn't need to be augmented with today's
    still-forming candle the way _calc_tech's fuller indicator set does.
    One day less current than the stock engine's version; simpler, and
    avoids sourcing a same-cycle live index quote into this function
    just for a marginal ATR freshness gain.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    cached = _history_cache.get(name)
    if cached and cached.get('date') == today_str:
        return cached['df']

    range_to = datetime.now().date()
    range_from = range_to - timedelta(days=days)
    try:
        resp = get_history(fyers_symbol, resolution="D",
                            range_from=str(range_from), range_to=str(range_to))
    except Exception as e:
        print(f"[IndexSignal] {name} history error: {e}")
        return None
    if not resp or resp.get('s') != 'ok' or not resp.get('candles'):
        return None
    df = pd.DataFrame(resp['candles'], columns=['ts', 'Open', 'High', 'Low', 'Close', 'Volume'])
    if df.empty or len(df) < 2:
        return None

    _history_cache[name] = {'date': today_str, 'df': df}
    return df


def _calc_index_atr(name, fyers_symbol):
    """
    Aug 27 2026: ATR for an index (NIFTY/BANKNIFTY), reusing the exact
    same _compute_indicators() math the stock engine already uses for
    every F&O stock -- so index option calls (index_signal.py) size
    SL/Target off the same kind of volatility measure stock calls do,
    not a different concept invented from scratch. Returns None (not a
    guessed number) if there isn't enough history or Fyers has nothing
    right now -- caller (index_signal.generate_index_call) already
    treats a None ATR as "can't generate a call yet."
    """
    try:
        if not is_authenticated():
            return None
        df = _cached_index_history_df(name, fyers_symbol, days=100)
        if df is None or len(df) < 20:
            return None
        indicators = _compute_indicators(df['Close'], df['High'], df['Low'], df['Volume'])
        return indicators['atr'] if indicators else None
    except Exception as e:
        print(f"[IndexSignal] {name} ATR calc error: {e}")
        return None


def _calc_index_indicators(name, fyers_symbol):
    """
    Sep 8 2026: full indicator set for an index (NIFTY/BANKNIFTY),
    reusing the exact same _cached_index_history_df() + _compute_
    indicators() pipeline _calc_index_atr() above already uses --
    just exposing the FULL dict (RSI/VWAP/MACD/ATR/ADX/+DI/-DI/EMA20/
    EMA50/etc.) instead of only 'atr'. Written as a SEPARATE function
    rather than changing _calc_index_atr()'s return shape, same "don't
    risk an already-working caller" principle this file already uses
    elsewhere (see _cached_index_history_df()'s own docstring). Zero
    new Fyers calls beyond what _calc_index_atr() already costs this
    cycle -- same cached history, same cache key.

    For the new Index Quality Engine's Price Structure component
    (shadow mode only -- see quality_engine.py). This directly
    contradicts my own earlier Phase 0 audit, which marked index-level
    ADX/DI/EMA20/EMA50 as "NOT AVAILABLE" -- that was wrong; the
    computation was already happening for ATR, just not exposed. Worth
    recording plainly rather than quietly fixing without a note.
    """
    try:
        if not is_authenticated():
            return None
        df = _cached_index_history_df(name, fyers_symbol, days=100)
        if df is None or len(df) < 20:
            return None
        return _compute_indicators(df['Close'], df['High'], df['Low'], df['Volume'])
    except Exception as e:
        print(f"[IndexQuality] {name} indicator calc error: {e}")
        return None


def _calc_tech(symbol, live_quote=None):
    """
    Technical indicators for a stock, sourced from Fyers only. No Yahoo/
    yfinance fallback -- if Fyers isn't authenticated or has no usable
    history for this symbol, returns None (caller skips the stock for
    this cycle) rather than pulling from Yahoo.

    `live_quote` (optional): this cycle's already-fetched quote dict for
    this symbol (from _fetch_all_stocks -- has open/high/low/price/
    volume). When given, today's candle is built from THIS instead of a
    second Fyers history call that would otherwise also include today --
    the quotes call already happened this cycle regardless, so reusing
    it here is genuinely free. Falls back to the original, slower path
    (a full history fetch that includes today, no caching) when not
    given, so any other caller keeps working exactly as before.
    """
    try:
        if not is_authenticated():
            return None

        if live_quote is not None:
            historical = _cached_history_df(symbol, days=100)
            if historical is None:
                return None
            today_row = pd.DataFrame([{
                'ts': int(datetime.now().timestamp()),
                'Open': live_quote.get('open') or live_quote.get('price'),
                'High': live_quote.get('high') or live_quote.get('price'),
                'Low': live_quote.get('low') or live_quote.get('price'),
                'Close': live_quote.get('price'),
                'Volume': live_quote.get('volume', 0),
            }])
            df = pd.concat([historical, today_row], ignore_index=True)
        else:
            df = _fyers_history_df(symbol, days=100)

        if df is None or len(df) < 20:
            return None
        indicators = _compute_indicators(df['Close'], df['High'], df['Low'], df['Volume'])
        if indicators is None:
            return None
        # Sep 2 2026: fully separate from _compute_indicators() on
        # purpose -- see _compute_participation_quality()'s own
        # docstring. A hiccup here (e.g. a halted stock, zero-range
        # day) returns None for just this one field, never drops the
        # stock from the rest of its already-computed indicators.
        pq = _compute_participation_quality(df['High'], df['Low'], df['Close'], df['Volume'], indicators.get('volume_avg'))
        if pq:
            indicators.update(pq)
        return indicators
    except Exception as e:
        print(f"Tech calc error {symbol}: {e}")
        return None


# ============================================================
# BACKGROUND WORKER
# ============================================================

# Sep 8 2026: NIFTY's own multi-factor market regime, computed ONCE
# per _build_all() cycle (see _update_market_regime_cache() below),
# not re-derived per stock -- _evaluate_and_log_shadow() below reads
# this cache for the market_regime component of the shadow quality
# score instead of the hardcoded None it used before this. Module-
# level, same simple-dict-cache pattern _index_cache already uses.
_current_market_regime = {"state": None}


def _update_market_regime_cache():
    """
    Sep 8 2026: SHADOW MODE ONLY -- computes NIFTY's regime via
    quality_engine.classify_market_regime(), reusing
    _calc_index_indicators() (same cached pipeline _calc_index_atr()
    already uses for the LIVE index-call engine, zero new Fyers calls
    beyond what that already costs) plus the already-cached
    _index_cache/_stock_cache. Called once at the top of _build_all(),
    never inside the per-stock loop. Own try/except -- a regime-calc
    failure degrades to "unavailable" (None), never raises into the
    live scan loop that calls this.
    """
    try:
        from . import quality_engine as qe
        indicators = _calc_index_indicators("NIFTY", "NSE:NIFTY50-INDEX")
        if not indicators:
            _current_market_regime["state"] = None
            return

        adx_dir = qe.classify_adx_direction(indicators.get('adx'), indicators.get('plus_di'), indicators.get('minus_di'))

        with _cache_lock:
            nifty_price = (_index_cache.get("nifty50") or {}).get("price")
            vix_change_pct = (_index_cache.get("india_vix") or {}).get("change_percent")
            stocks_snapshot = list(_stock_cache.values())

        price_structure = {"state": "INSUFFICIENT_DATA"}
        price_above_vwap = None
        price_above_ema20 = None
        if nifty_price is not None:
            hist_df = _cached_index_history_df("NIFTY", "NSE:NIFTY50-INDEX", days=100)
            if hist_df is not None and len(hist_df) >= 21:
                price_structure = qe.detect_price_structure(
                    list(hist_df['Close']) + [nifty_price],
                    list(hist_df['High']) + [nifty_price],
                    list(hist_df['Low']) + [nifty_price],
                )
            if indicators.get('vwap') is not None:
                price_above_vwap = nifty_price > indicators['vwap']
            if indicators.get('ema20') is not None:
                price_above_ema20 = nifty_price > indicators['ema20']

        breadth_data = _compute_breadth(stocks_snapshot)
        regime = qe.classify_market_regime(
            adx_dir['state'], price_structure['state'], price_above_vwap, price_above_ema20,
            breadth_data.get('advances_pct'), breadth_data.get('declines_pct'), vix_change_pct,
        )
        _current_market_regime["state"] = regime['state']
    except Exception as e:
        print(f"[MarketRegime] update failed (shadow mode unaffected): {e}")
        _current_market_regime["state"] = None


# Sep 8 2026: SHADOW MODE ONLY -- {sector_name: {symbol: {'state',
# 'rank', 'total_in_sector', 'percentile'}}}, computed ONCE per cycle
# by _update_sector_rankings_cache() below, read per-stock in
# _evaluate_and_log_shadow(). Same module-level-cache pattern as
# _current_market_regime above -- grouping and ranking all 208 stocks
# by sector once per cycle is real work; redoing it per-stock inside
# the main loop would be 208x more of the same computation for
# nothing new.
_sector_rankings_cache = {}

# Sep 8 2026: SHADOW MODE ONLY -- {sector_name: {'state', 'rank',
# 'total_sectors', 'percentile'}}, the SECTOR-vs-SECTOR ranking
# (distinct from _sector_rankings_cache above, which ranks stocks
# WITHIN one sector) -- computed alongside it in the same
# _update_sector_rankings_cache() call, since it reuses the same
# by_sector grouping.
_sector_strength_cache = {}


def _update_sector_rankings_cache():
    """
    Sep 8 2026: SHADOW MODE ONLY -- groups this cycle's _stock_cache by
    sector and calls quality_engine.rank_sector_peers() once per
    sector (spec section 12: "rank stocks within strong sectors...
    SECTOR LEADERS / NEUTRAL / LAGGARDS"). Zero new Fyers calls --
    change_percent is already sitting in _stock_cache from this same
    cycle's own quote fetch. Called once per _build_all() cycle,
    alongside _update_market_regime_cache(), never inside the per-
    stock loop. Own try/except -- a ranking failure degrades to an
    empty cache (every stock's lookup below then correctly reads as
    unavailable), never raises into the live scan loop.
    """
    global _sector_rankings_cache
    try:
        from . import quality_engine as qe
        with _cache_lock:
            stocks_snapshot = dict(_stock_cache)

        by_sector = {}
        for sym, s in stocks_snapshot.items():
            sector = s.get("sector")
            chg = s.get("change_percent")
            if sector and chg is not None:
                by_sector.setdefault(sector, {})[sym] = chg

        new_cache = {}
        for sector, changes in by_sector.items():
            new_cache[sector] = qe.rank_sector_peers(changes)
        _sector_rankings_cache = new_cache

        # Sep 8 2026: SHADOW MODE ONLY -- the missing middle layer of
        # the spec's "Index -> Sector -> Stock Cascade" (its own worked
        # example: "NIFTY BULLISH -> Sector ranking -> BANKING ->
        # STRONG"). Reuses the SAME by_sector grouping just built above
        # -- one real aggregate change_percent per sector (equal-weight
        # average of that sector's own stocks this cycle, same
        # methodology _compute_sector_performance() already uses and
        # already discloses as not market-cap-weighted), ranked against
        # every OTHER sector via quality_engine.rank_sectors().
        sector_avg_changes = {
            sector: sum(changes.values()) / len(changes)
            for sector, changes in by_sector.items() if changes
        }
        global _sector_strength_cache
        _sector_strength_cache = qe.rank_sectors(sector_avg_changes)
    except Exception as e:
        print(f"[SectorRanking] update failed (shadow mode unaffected): {e}")
        _sector_rankings_cache = {}
        _sector_strength_cache = {}


def _evaluate_and_log_shadow(sym, action, price, tech, stock, sector_change_map, nifty_change_pct,
                              v3_decision, v3_score, v3_grade, v3_reason, oi=None, signal_extra=None, option_leg=None,
                              mtf_data=None, futures_oi_data=None, skip_logging=False):
    """
    Sep 8 2026: SHADOW MODE glue -- converts this cycle's already-
    computed tech/oi/stock data into quality_engine's function
    signatures, computes an independent quality assessment, and logs
    it via shadow_logger alongside v3.0's REAL decision for the SAME
    candidate. This function NEVER influences v3.0's decision -- it's
    always called AFTER that decision is already final (a no_trade_log
    entry was already appended, or a signal was already appended to
    signals[]), purely as an observer.

    Zero new Fyers calls: price structure reuses _cached_history_df's
    same-day in-memory cache (already populated by _calc_tech() for
    this exact symbol, this exact cycle -- calling it again here is a
    pure dict lookup); everything else is data _build_all() already
    fetched this cycle for its own use.

    option_leg: Sep 8 2026 addition -- optional dict with 'oi',
    'volume', 'bid', 'ask', 'ltp' for the SPECIFIC strike/side v3.0
    resolved this cycle (options_analytics.py's own leg dict shape,
    confirmed real fields). Only passed at the call sites where that
    resolution has actually happened (spread-too-wide onward) -- the
    earlier rejection points (hysteresis-fail, OI-conflict, no-
    option-chain) genuinely don't have a resolved leg yet, so this
    stays None there and the option-liquidity portion of the gate
    below is correctly marked unavailable, not guessed.

    mtf_data/futures_oi_data: Sep 9 2026 addition -- optional dicts
    from the SAME candidate-based enrichment call in _build_all()
    (mtf_trend.get_mtf_trend() / futures_oi.get_stock_futures_oi()),
    gated at the exact same "candidate already cleared the technical
    filter" boundary the OI fetch above it already uses -- not a
    second shortlist decision. Only passed at call sites AFTER that
    enrichment point (everything except hysteresis-fail, which is
    textually earlier in _build_all() and genuinely has neither this
    nor OI data yet). market_regime is populated from
    _current_market_regime, computed once per cycle elsewhere.

    Wrapped in try/except by BOTH call sites in _build_all() as well as
    internally here -- shadow mode must never be able to break the live
    scan loop, belt-and-braces on purpose.

    skip_logging: Sep 12 2026 addition -- when True, computes and
    returns (quality_result, reasons) WITHOUT calling shadow_logger.
    Existing call sites are entirely unaffected (they don't pass this,
    so it defaults to False and behaves exactly as before). Lets the
    live SIGNAL path get quality_result BEFORE signals.append() (to
    gate on it) without computing it twice or double-logging to
    shadow_logger -- the caller logs separately, once, with these same
    values, after append.

    Returns (quality_result, reasons) on success, (None, []) if
    anything in here raised -- the caller must treat None as "don't
    know," never as a guessed confirmation.
    """
    try:
        from . import quality_engine as qe

        # Sep 8 2026: HARD GATE, evaluated BEFORE scoring -- spec
        # section 3/4, stated as plainly as anything in the whole
        # document: "A high score must NOT compensate for a critical
        # failure." Now checks BOTH stock-side (always available) AND
        # option-side liquidity (only when option_leg is provided --
        # see the parameter docstring above for exactly which call
        # sites that is). Previously option-side was never checked at
        # all here; this was the second of the two genuine liquidity
        # gaps disclosed at the end of last session.
        leg_oi = option_leg.get('oi') if option_leg else None
        leg_volume = option_leg.get('volume') if option_leg else None
        leg_bid = option_leg.get('bid') if option_leg else None
        leg_ask = option_leg.get('ask') if option_leg else None
        leg_ltp = option_leg.get('ltp') if option_leg else None
        liquidity_result = qe.evaluate_liquidity_gate(
            avg_volume=tech.get('volume_avg'), current_volume=stock.get('volume'),
            option_oi=leg_oi, option_volume=leg_volume, bid=leg_bid, ask=leg_ask, ltp=leg_ltp,
        )
        hard_gate_failures = liquidity_result['reasons']

        adx_dir = qe.classify_adx_direction(tech.get('adx'), tech.get('plus_di'), tech.get('minus_di'))
        price_above_vwap = (price > tech['vwap']) if tech.get('vwap') is not None else None
        rvol_result = qe.classify_rvol(stock.get('volume'), tech.get('volume_avg'))
        volume_confirmed = rvol_result['state'] in ('CONFIRMATION', 'STRONG', 'EXCEPTIONAL')
        rsi_regime = qe.classify_rsi_regime(tech.get('rsi'), adx_dir['state'], price_above_vwap, volume_confirmed)
        extension = qe.classify_extension(price, tech.get('ema20'), tech.get('atr'))

        hist_df = _cached_history_df(sym)
        if hist_df is not None and len(hist_df) >= 21:
            today_high = stock.get('high') or price
            today_low = stock.get('low') or price
            price_structure = qe.detect_price_structure(
                list(hist_df['Close']) + [price],
                list(hist_df['High']) + [today_high],
                list(hist_df['Low']) + [today_low],
            )
        else:
            price_structure = {"state": "INSUFFICIENT_DATA"}

        sector_change_pct = sector_change_map.get(stock.get("sector"))
        sector_result = qe.evaluate_sector_alignment(action, stock.get('change_percent'), sector_change_pct, nifty_change_pct)

        # Sep 8 2026: spec section 12's actual ranking requirement --
        # "for bullish trades prefer leaders, for bearish trades
        # prefer laggards" -- reads this stock's REAL rank against
        # every other stock in its own sector this cycle (computed
        # once for the whole sector by _update_sector_rankings_cache(),
        # not re-derived here).
        sector_rank_info = (_sector_rankings_cache.get(stock.get("sector")) or {}).get(sym)
        leadership_result = qe.evaluate_sector_leadership(action, sector_rank_info['state'] if sector_rank_info else None)

        # Sep 8 2026: SHADOW MODE ONLY -- "Index -> Sector -> Stock
        # Cascade," the missing middle layer. This answers a genuinely
        # DIFFERENT question from sector_result/leadership_result above
        # ("does direction agree" / "is this stock a leader WITHIN its
        # sector") -- is the sector ITSELF genuinely strong relative to
        # every OTHER sector today (spec's exact example: "BANKING ->
        # STRONG"). Kept as explainable context rather than folded into
        # the already-small 5-point sector_alignment score -- per the
        # spec's own "do not turn the scanner into an indicator
        # monster" principle, a stock's own direction/leadership
        # already captures most of what matters numerically; sector
        # strength earns its place as a real, computed fact to SHOW,
        # not a third layer competing for the same 5 points.
        sector_strength_info = _sector_strength_cache.get(stock.get("sector"))

        def _combined_sector_score(base_state, leadership_state):
            """Leadership REFINES a real alignment read, never rescues
            a genuine CONFLICT (market+sector both disagree) -- and
            when base alignment itself is unavailable but leadership
            IS real, scores off leadership alone rather than
            discarding a real signal just because a different one was
            missing."""
            if base_state == "CONFLICT":
                return 0.0
            if base_state == "INSUFFICIENT_DATA":
                if leadership_state == "INSUFFICIENT_DATA":
                    return None
                return {"PREFERRED": 5 * 0.7, "ACCEPTABLE": 5 * 0.4, "AVOID": 5 * 0.1}.get(leadership_state)
            base = 5.0 if base_state == "ALIGNED" else 5 * 0.3  # NEUTRAL
            if leadership_state == "PREFERRED":
                return min(5.0, base + 5 * 0.4)
            if leadership_state == "AVOID":
                return max(0.0, base - 5 * 0.4)
            return base

        sector_score = _combined_sector_score(sector_result['state'], leadership_result['state'])

        options_result = {"state": "INSUFFICIENT_DATA"}
        if oi and signal_extra:
            options_result = qe.evaluate_options_structure(
                action, stock.get('change_percent'),
                signal_extra.get('ce_oi_chg'), signal_extra.get('pe_oi_chg'), signal_extra.get('pcr'),
            )

        # Maps each classifier's real state into a 0..max-weight sub-
        # score for the aggregator: full weight for a genuinely good
        # state, partial (30%) for NEUTRAL (real but non-committal
        # evidence, not silence), zero for a real-but-unfavorable read,
        # and None (never a guessed number) when the classifier itself
        # reported INSUFFICIENT_DATA.
        def _sub_score(state, max_pts, good_states):
            if state == "INSUFFICIENT_DATA":
                return None
            if state in good_states:
                return max_pts
            if state == "NEUTRAL":
                return max_pts * 0.3
            return 0.0

        # Sep 8 2026: real market_regime scoring -- reads the SAME
        # regime _update_market_regime_cache() already computed once
        # this cycle (see call site in _build_all() below), scored
        # against THIS stock's own action. Full credit when the
        # regime genuinely agrees with the direction (BUY+TREND_UP or
        # SELL+TREND_DOWN); zero when it's fighting the market; a
        # smaller partial credit for RANGE/MIXED (no real edge either
        # way) than the standard NEUTRAL 30%, and smaller still for
        # HIGH_VOLATILITY -- spec: "reduce confidence/quality and
        # apply stricter confirmation" is explicitly MORE cautious
        # than an ordinary range-bound read, not the same as one.
        regime_state = _current_market_regime.get("state")
        if regime_state is None or regime_state == "INSUFFICIENT_DATA":
            market_regime_score = None
        elif (action == "BUY" and regime_state == "TREND_UP") or (action == "SELL" and regime_state == "TREND_DOWN"):
            market_regime_score = 15.0
        elif (action == "BUY" and regime_state == "TREND_DOWN") or (action == "SELL" and regime_state == "TREND_UP"):
            market_regime_score = 0.0
        elif regime_state == "HIGH_VOLATILITY":
            market_regime_score = 15 * 0.15
        else:  # RANGE or MIXED
            market_regime_score = 15 * 0.3

        # Sep 9 2026: real MTF alignment -- classify_mtf_alignment()
        # was already built earlier this session but had nothing real
        # to combine; mtf_data now comes from the candidate-based
        # enrichment call in _build_all() (see that call site's own
        # comment for why it's gated the same way OI already is).
        # UNAVAILABLE when mtf_data itself is None (enrichment wasn't
        # authenticated/ran this cycle) -- never guessed.
        mtf_result = qe.classify_mtf_alignment(
            mtf_data.get('mtf_1h') if mtf_data else None,
            mtf_data.get('mtf_15m') if mtf_data else None,
            mtf_data.get('mtf_5m') if mtf_data else None,
        )
        mtf_favorable = "ALIGNED_BULLISH" if action == "BUY" else "ALIGNED_BEARISH"
        mtf_unfavorable = "ALIGNED_BEARISH" if action == "BUY" else "ALIGNED_BULLISH"
        if mtf_result['state'] == "UNAVAILABLE":
            mtf_score = None
        elif mtf_result['state'] == mtf_favorable:
            mtf_score = 20.0
        elif mtf_result['state'] == mtf_unfavorable:
            mtf_score = 0.0
        else:  # MIXED or NEUTRAL -- real cross-timeframe data, just not a clean alignment either way
            mtf_score = 20 * 0.3

        # Sep 9 2026: real stock Futures OI -- reuses
        # evaluate_futures_oi_structure() built earlier for the index
        # engine verbatim (it only needs price_change_pct + a signed
        # OI-change value, which works identically for a stock's own
        # futures contract). futures_oi_data comes from the same
        # candidate-based enrichment call. AVAILABLE-but-still-
        # INSUFFICIENT_DATA (status fetched ok but a field was
        # missing) is handled the same honest way futures_oi.py
        # itself already treats it -- never substituted with 0.
        futures_oi_result = {"state": "INSUFFICIENT_DATA"}
        if futures_oi_data and futures_oi_data.get("status") == "AVAILABLE":
            futures_oi_result = qe.evaluate_futures_oi_structure(
                action, stock.get('change_percent'), futures_oi_data.get('oi_chg_pct'),
            )

        evidence = {
            "market_regime": market_regime_score,
            "multi_tf_trend": mtf_score,
            "price_structure": _sub_score(price_structure['state'], 15, ("BULLISH_STRUCTURE", "BEARISH_STRUCTURE")),
            "volume_rvol": _sub_score(rvol_result['state'], 15, ("STRONG", "EXCEPTIONAL")),
            "momentum": _sub_score(rsi_regime['state'], 10, ("BULLISH_CONTINUATION", "BEARISH_CONTINUATION")),
            "futures_oi": _sub_score(futures_oi_result['state'], 10, ("CONFIRMED",)),
            "options_confirmation": _sub_score(options_result['state'], 10, ("CONFIRMED",)),
            "sector_alignment": sector_score,
        }
        quality_result = qe.compute_stock_quality_score(evidence, hard_gate_failures=hard_gate_failures)

        # Extension filter (spec section 16) -- a SEPARATE modifier, not
        # one of the 8 weighted components above. Spec: highly extended
        # -> no new entry (capped at WATCH here, never a fresh TRADE
        # verdict); moderately extended -> a real point penalty, not a
        # hard block ("the purpose is to avoid late entries, not to
        # prevent momentum trades").
        if extension['state'] == "HIGHLY_EXTENDED" and quality_result['verdict'] == "TRADE":
            quality_result['verdict'] = "WATCH"
            quality_result['grade'] = "B"
        elif extension['state'] == "MODERATELY_EXTENDED" and quality_result['score'] is not None:
            quality_result['score'] = round(max(0.0, quality_result['score'] - 5), 1)
        quality_result['extension'] = extension['state']
        quality_result['sector_strength'] = sector_strength_info['state'] if sector_strength_info else None

        # Sep 8 2026: Hard Gate D (spec section 3) -- "Strong conflict
        # with market regime -> NO TRADE or WATCH." market_regime_score
        # was already 0.0 above when this stock's action genuinely
        # fights a REAL, confirmed TREND_UP/TREND_DOWN regime (not
        # merely RANGE/MIXED/unavailable, which score partial credit,
        # not zero) -- this caps an otherwise-TRADE verdict at WATCH
        # rather than just letting the score absorb it quietly. Same
        # "cap at WATCH, keep the score visible" severity as the
        # extension filter above, per spec's own "NO TRADE or WATCH"
        # phrasing (not mandating outright IGNORE).
        #
        # HONEST FINDING, tested directly against compute_stock_quality_
        # score() with every OTHER available component maxed: the best
        # achievable score with market_regime=0 is 78.6/100 -- just
        # under the 80-point TRADE threshold. Since multi_tf_trend (20
        # pts) and futures_oi (10 pts) are permanently unavailable for
        # stocks right now, this gate's own precondition (verdict
        # already TRADE despite market_regime=0) is very hard to reach
        # in practice today -- the normal weighted-redistribution math
        # already does this gate's job on its own for stocks. The logic
        # here is still correct (confirmed: it downgrades correctly
        # when the precondition IS met, and leaves the score visible)
        # -- it's a real safeguard, just a currently-dormant one for
        # stocks, that will start engaging on its own once more
        # components (e.g. multi-timeframe trend) become available,
        # with no code change needed here.
        regime_conflict = market_regime_score == 0.0 and regime_state not in (None, "INSUFFICIENT_DATA")
        if regime_conflict and quality_result['verdict'] == "TRADE":
            quality_result['verdict'] = "WATCH"
            quality_result['grade'] = "B"

        # Sep 8 2026: Hard Gate F (spec section 3) -- "Strong technical
        # bullish setup but strong contradictory option structure ->
        # WATCH / NO TRADE." options_result['state'] == 'CONFLICT' is
        # already a REAL, confirmed contradiction (see
        # evaluate_options_structure()'s own direct-OI-direction
        # logic, not a magnitude-comparison guess) -- same WATCH cap,
        # same reasoning as Gate D just above.
        option_conflict = options_result['state'] == "CONFLICT"
        if option_conflict and quality_result['verdict'] == "TRADE":
            quality_result['verdict'] = "WATCH"
            quality_result['grade'] = "B"

        # Sep 12 2026: explicit field for the new live gating function
        # below (_is_quality_confirmed_with_hysteresis) to check, rather
        # than string-matching the human-readable reason text built just
        # below this -- a real, confirmed contradiction (either of the
        # two conflict caps just applied), not a mere score dip. Both
        # gates were already computed above; this just names the OR of
        # the two explicitly instead of leaving it implicit in verdict.
        quality_result['conflict_gate_triggered'] = bool(regime_conflict or option_conflict)

        # Sep 8 2026: spec section 18, "Explainable Signals" -- "The
        # user must be able to understand the signal without opening
        # the source code." Every value used here was already computed
        # above for scoring; this only compiles it into plain English,
        # no new evidence gathered. Hard gate failures lead (they're
        # why nothing else here matters), then real ✓/✗ reads, then ⚠
        # warnings -- never a line for a component that's genuinely
        # INSUFFICIENT_DATA (silence there is more honest than a
        # fabricated-sounding "neutral" line).
        reasons = []
        for r in liquidity_result['reasons']:
            reasons.append(f"HARD GATE: {r}")
        if _current_market_regime.get("state"):
            rs = _current_market_regime["state"]
            if (action == "BUY" and rs == "TREND_UP") or (action == "SELL" and rs == "TREND_DOWN"):
                reasons.append(f"Market regime aligned ({rs})")
            elif (action == "BUY" and rs == "TREND_DOWN") or (action == "SELL" and rs == "TREND_UP"):
                reasons.append(f"GATE: Market regime conflict ({rs}) -- capped at WATCH" if regime_conflict else f"Market regime against this direction ({rs})")
            elif rs == "HIGH_VOLATILITY":
                reasons.append("Market in HIGH_VOLATILITY -- stricter confirmation applied")
        if adx_dir['state'] in ("BULLISH_TREND", "BEARISH_TREND"):
            reasons.append(f"ADX confirms {adx_dir['state'].replace('_', ' ').lower()} (ADX {adx_dir['adx']:.0f})")
        elif adx_dir['state'] == "RANGE":
            reasons.append("Weak trend strength (RANGE) -- avoid momentum chase")
        if rsi_regime['state'] in ("BULLISH_CONTINUATION", "BEARISH_CONTINUATION"):
            reasons.append(f"RSI {rsi_regime['state'].replace('_', ' ').lower()} (RSI {rsi_regime['rsi']:.0f})")
        elif rsi_regime['state'] == "EXTENDED":
            reasons.append(f"RSI extended (RSI {rsi_regime['rsi']:.0f}) -- late entry risk")
        if rvol_result['state'] in ("STRONG", "EXCEPTIONAL"):
            reasons.append(f"RVOL {rvol_result['rvol']:.1f}x -- strong volume confirmation")
        elif rvol_result['state'] == "WEAK":
            reasons.append(f"RVOL {rvol_result['rvol']:.1f}x -- weak volume, move not confirmed")
        if price_structure['state'] in ("BULLISH_STRUCTURE", "BEARISH_STRUCTURE"):
            tag = "Bullish" if price_structure['state'] == "BULLISH_STRUCTURE" else "Bearish"
            brk = f", {price_structure['breakout']} breakout" if price_structure.get('breakout') else ""
            reasons.append(f"{tag} price structure{brk}")
        if options_result['state'] == "CONFIRMED":
            reasons.append(f"Options structure confirms (CE {options_result['ce_quadrant']}, PE {options_result['pe_quadrant']})")
        elif options_result['state'] == "CONFLICT":
            reasons.append(f"GATE: Critical option conflict (CE {options_result['ce_quadrant']}, PE {options_result['pe_quadrant']}) -- capped at WATCH")
        if sector_rank_info and sector_rank_info['state'] in ("LEADER", "LAGGARD"):
            if leadership_result['state'] == "PREFERRED":
                reasons.append(f"Sector {sector_rank_info['state'].lower()} (rank {sector_rank_info['rank']} of {sector_rank_info['total_in_sector']}, {sector_rank_info['percentile']:.0f}th percentile)")
            elif leadership_result['state'] == "AVOID":
                reasons.append(f"Sector {sector_rank_info['state'].lower()} but wrong side for a {action}")
        if sector_strength_info and sector_strength_info['state'] in ("STRONG", "WEAK"):
            sec_name = stock.get("sector")
            reasons.append(f"Sector {sec_name} is {sector_strength_info['state']} (rank {sector_strength_info['rank']} of {sector_strength_info['total_sectors']} sectors)")
        if extension['state'] == "HIGHLY_EXTENDED":
            reasons.append(f"Highly extended ({extension['distance_atr']:.1f} ATR from EMA20) -- no new entry")
        elif extension['state'] == "MODERATELY_EXTENDED":
            reasons.append(f"Moderately extended ({extension['distance_atr']:.1f} ATR from EMA20)")
        if mtf_result['state'] == mtf_favorable:
            reasons.append(f"MTF aligned ({', '.join(mtf_result['aligned_timeframes'])} all {('bullish' if action == 'BUY' else 'bearish')})")
        elif mtf_result['state'] == mtf_unfavorable:
            reasons.append("MTF aligned AGAINST this direction")
        elif mtf_result['state'] == "MIXED":
            reasons.append("MTF mixed -- timeframes disagree")
        if futures_oi_result['state'] == "CONFIRMED":
            reasons.append(f"Futures OI confirms ({futures_oi_result.get('quadrant')})")
        elif futures_oi_result['state'] == "CONFLICT":
            reasons.append(f"Futures OI conflicts ({futures_oi_result.get('quadrant')})")
        elif futures_oi_data and futures_oi_data.get("status") == "UNAVAILABLE":
            reasons.append(f"Futures OI unavailable ({futures_oi_data.get('reason', 'unknown')})")

        from . import shadow_logger
        if not skip_logging:
            shadow_logger.log_shadow_candidate(sym, action, price, v3_decision, v3_score, v3_grade, v3_reason, quality_result, reasons=reasons)
        return quality_result, reasons
    except Exception as e:
        print(f"[ShadowMode] {sym} evaluation failed (v3.0 unaffected): {e}")
        return None, []


def _build_all():
    """Fetch everything: indices, stocks, signals. Cache all."""
    global _stock_cache, _index_cache, _index_cache_updated_at, _signal_cache, _tech_cache, _last_fetch, _no_trade_cache

    # 1. Indices -- Aug 20 2026: reuse _index_snapshot_worker's fetch if
    # it's recent (that loop runs every 60s specifically for this, and
    # independently re-fetching the identical 3 symbols here was
    # confirmed to meaningfully add to real Fyers /quotes rate-limiting,
    # not just a "lightweight" duplicate as originally assumed). Falls
    # back to fetching directly if the shared cache is empty or older
    # than 90s (covers cold start, before the snapshot worker's first
    # cycle completes, and the case where that worker's thread has died).
    with _cache_lock:
        cache_age = time.time() - _index_cache_updated_at
        cached_indices = dict(_index_cache) if _index_cache else None

    if cached_indices and cache_age < 90:
        nifty = cached_indices.get("nifty50", {'price': 0, 'change': 0, 'change_percent': 0})
        bank = cached_indices.get("banknifty", {'price': 0, 'change': 0, 'change_percent': 0})
        vix = cached_indices.get("india_vix", {'price': 0, 'change': 0, 'change_percent': 0})
        sensex = cached_indices.get("sensex", {'price': 0, 'change': 0, 'change_percent': 0})
    else:
        # Sep 3 2026: was 3 separate _fetch_index() calls -- see
        # _fetch_indices_batched()'s docstring for why that's a real,
        # confirmed problem, not just a style nitpick.
        _batched_idx = _fetch_indices_batched()
        nifty = _batched_idx["NIFTY 50"]
        bank = _batched_idx["BANKNIFTY"]
        vix = _batched_idx["INDIA VIX"]
        sensex = _batched_idx["SENSEX"]
        with _cache_lock:
            _index_cache = {"nifty50": nifty, "banknifty": bank, "india_vix": vix, "sensex": sensex}
            _index_cache_updated_at = time.time()
    
    # 2. Fetch all stock prices -- Fyers only, no Yahoo involved at all.
    results = _fetch_all_stocks(FNO_STOCKS)

    # Sep 2 2026: same real bug class as the PCR fix above, just much
    # bigger blast radius -- this used to unconditionally overwrite
    # _stock_cache with `results` every cycle, INCLUDING when
    # _fetch_all_stocks() returns {} (is_authenticated() cached a
    # transient False -- one momentary /profile hiccup, not
    # necessarily an actually-invalid token -- see is_authenticated()'s
    # own docstring in fyers_client.py). One bad cycle used to blank
    # the ENTIRE 208-stock cache -- every price, every signal, breadth,
    # sectors, movers, all derived from this -- not just one field.
    # Now only overwrites on a real, non-empty fetch; a failed cycle
    # leaves the last known good data in place. _last_fetch
    # correspondingly now means "last SUCCESSFUL fetch", which is also
    # the more correct, more honest input for DataHealthView's own
    # staleness_seconds reading elsewhere in this file.
    if results:
        with _cache_lock:
            _stock_cache = results
            _last_fetch = time.time()
    # else: this cycle got nothing -- _stock_cache deliberately left
    # untouched, same principle as the PCR fix above.

    # Sep 8 2026: SHADOW MODE ONLY -- once per cycle (not per stock),
    # now that both _index_cache and _stock_cache are populated for
    # this cycle. See _update_market_regime_cache()'s own docstring.
    _update_market_regime_cache()
    _update_sector_rankings_cache()

    # 3. PCR -- this used to be declines/advances among the scanned stock
    # universe (an advance-decline ratio, a completely different market
    # breadth statistic) mislabeled as "PCR". That's why it never matched
    # the real options Put-Call Ratio shown elsewhere (e.g. NIFTY's real
    # PCR sitting around 0.99-1.01 while this said 2.27-3.08) -- it was
    # never actually PCR. Now pulls NIFTY's real PCR from its live option
    # chain, which is what "market PCR" conventionally means.
    #
    # Sep 2 2026: real bug, confirmed live -- this used to unconditionally
    # overwrite _index_cache["pcr"] every single cycle, including on a
    # FAILED fetch (pcr_proxy/pcr_sentiment reset to None/"N/A" at the top
    # of every cycle, then written regardless of whether the fetch below
    # actually succeeded). One transient hiccup in this one Fyers call --
    # out of hundreds of cycles a day -- wiped out a perfectly good
    # previous value instead of just keeping it, same resilience nifty/
    # bank/vix already had above (cache_age < 90) that PCR never got. Now
    # only overwrites the cache on an actual successful fetch; a failed
    # cycle leaves the last known good value in place rather than
    # blanking it.
    pcr_proxy, pcr_sentiment = None, "N/A"
    if is_authenticated():
        try:
            nifty_oi = get_option_analytics("NSE:NIFTY50-INDEX", strikecount=10)
            if nifty_oi and nifty_oi.get('pcr') is not None:
                pcr_proxy = nifty_oi['pcr']
                pcr_sentiment = "Bearish" if pcr_proxy < 0.95 else "Bullish" if pcr_proxy > 1.05 else "Neutral"
        except Exception as e:
            print(f"[PCR] NIFTY option chain fetch failed: {e}")

    if pcr_proxy is not None:
        with _cache_lock:
            _index_cache["pcr"] = {"value": pcr_proxy, "sentiment": pcr_sentiment}
            _index_cache["pcr_updated_at"] = time.time()
    # else: this cycle's fetch failed -- _index_cache["pcr"] deliberately
    # left untouched, holding whatever the last successful cycle wrote.
    
    # 4. Build signals -- Sep 17 2026 (Zero-Signal Forensic Audit,
    # continued): this used to be `sorted(...)[:30]` -- only the day's
    # 30 biggest movers BY ALREADY-REALIZED |%change| ever reached
    # _calc_tech/scoring/OI at all. Real snapshot data (a 208-stock
    # F&O watchlist from a broad-based session) showed the top-30
    # cutoff's effective boundary was 2.31% that day -- 84 stocks
    # still moving >=1% and 10 stocks moving >=2% never got evaluated,
    # purely because ~30 OTHER stocks happened to be moving even more
    # that same cycle. That's the literal opposite of early detection:
    # a stock had to already be one of the day's biggest movers before
    # this pipeline would even look at its RSI/MACD/ADX/VWAP.
    #
    # Real cost check before removing this, not a guess: _fetch_all_
    # stocks(FNO_STOCKS) two lines above ALREADY fetches quotes for
    # the full 208-stock universe every cycle, truncation or not -- no
    # new quote traffic either way. _calc_tech's own history fetch
    # (_cached_history_df) is cached once per symbol per DAY (Aug 14
    # fix, see its own docstring) -- so scanning all 208 instead of 30
    # costs ZERO extra Fyers calls after the first cycle of the day;
    # only that first cycle pays a real, one-time cost of ~178 more
    # History-API calls to warm the cache for the newly-included
    # symbols. The expensive calls (option chain, futures OI) are
    # UNCHANGED -- still only fetched for symbols that already cleared
    # the technical+directional gates further down, exactly as before;
    # this change only widens who gets a chance to reach that point.
    #
    # SIGNAL_CANDIDATE_POOL_SIZE (0 = full universe, the new default)
    # exists as a safety valve given this project's real, repeated
    # Fyers 429 history (Aug 20/Sep 3/Sep 4 incidents) -- if the first-
    # cycle history-warming burst causes trouble, set it back to a
    # number (e.g. 50) with no code change rather than reverting this
    # entirely.
    #
    # Sep 18 2026 (Zero-Signal Forensic Audit, continued): that burst
    # happened -- seen live in this morning's console at market open.
    # The "costs zero extra Fyers calls after the first cycle" claim
    # from yesterday was right about the STEADY STATE, but wrong about
    # the TRANSITION: with the top-30 cap gone, the first cycle of the
    # day now wants a fresh _cached_history_df() fetch for all ~207
    # symbols AT ONCE (none cached yet), not 30 -- that simultaneous
    # burst is what tripped Fyers' own per-minute limit and opened the
    # circuit breaker, which then also blocked quotes/option-chain/
    # index calls for the whole cycle, not just the history warm-up.
    # Real, not guessed: this morning's own log line sequence --
    # Rejected: ... 'no_tech_data': 131 / 130 / 125 / 115 -- across
    # consecutive cycles shows it self-healing (fewer symbols cold each
    # time), but slowly, and re-tripping repeatedly along the way.
    #
    # Fix: cap how many NEWLY-cold symbols get warmed in any one cycle
    # (HISTORY_WARMUP_BATCH_SIZE, default 40) instead of capping the
    # candidate pool itself. Already-warm symbols (cached today) are
    # NEVER limited -- every symbol that already has today's history
    # gets evaluated every cycle, same as before this fix. Only the
    # still-cold remainder is throttled, so the full 208-stock universe
    # goal from yesterday is unchanged; it now arrives over several
    # cycles at market open instead of in one Fyers-limit-tripping
    # burst.
    _candidate_pool_size = int(os.environ.get("SIGNAL_CANDIDATE_POOL_SIZE", "0"))
    _history_warmup_batch_size = int(os.environ.get("HISTORY_WARMUP_BATCH_SIZE", "10"))
    movers = sorted(results.values(), key=lambda x: abs(x.get('change_percent', 0)), reverse=True)
    if _candidate_pool_size > 0:
        movers = movers[:_candidate_pool_size]
    _today_str = datetime.now().strftime("%Y-%m-%d")
    _warm_symbols = {sym for sym, _c in _history_cache.items() if _c.get('date') == _today_str}
    _warm = [s for s in movers if s.get('symbol') in _warm_symbols]
    _cold = [s for s in movers if s.get('symbol') not in _warm_symbols]
    # Sep 18 2026, same day, second pass -- live evidence (this
    # morning's own console) showed 40 was STILL enough to retrip the
    # breaker: it opens after just 2 consecutive 429s, and the shared
    # 0.32s inter-call governor (fyers_client.py) apparently isn't
    # enough headroom for the History endpoint specifically once other
    # traffic (quotes/option-chain/index/MCX calls) shares the same
    # window. Two changes, not one, since size alone didn't hold:
    # default batch cut 40->10, AND skip ALL new cold symbols this
    # cycle if the breaker is already open when this runs, so a fresh
    # batch never fires right as a previous trip is still cooling down
    # (before, cold symbols were attempted regardless of breaker state).
    from .fyers_client import _rate_limited_now
    _cold_batch = [] if _rate_limited_now() else _cold[:_history_warmup_batch_size]
    movers = _warm + _cold_batch
    signals = []
    techs = {}
    # Aug 31 2026: P0-7 -- one VIX read for the whole cycle, reused by
    # every signal's audit_snapshot below rather than re-reading
    # _index_cache per stock. Same source line 1404 already uses
    # elsewhere in this file (_index_cache.get("india_vix")).
    # Sep 1 2026: P1 from the FO-Radar/Sniper V2 logic review --
    # relative strength (stock vs sector vs index). Both computed ONCE
    # for the whole cycle here, not per-signal -- _compute_sector_performance
    # already exists (used by the Heatmap) and is real: a genuine
    # average of this cycle's own scanned stocks, not a fabricated
    # cap-weighted index (see its own docstring). nifty_change_pct
    # reuses the same _index_cache read pattern as cycle_vix above.
    sector_change_map = {s["sector"]: s["change_percent"] for s in _compute_sector_performance(list(results.values()))}
    with _cache_lock:
        nifty_snapshot = _index_cache.get("nifty50")
    nifty_change_pct = (nifty_snapshot or {}).get("change_percent")

    with _cache_lock:
        cycle_vix = _index_cache.get("india_vix")
    # Aug 31 2026: P0-6 from the UI Corrections checklist -- these
    # rejection points already existed (every `continue` below), they
    # just discarded the candidate silently. This makes each one an
    # explicit, explainable NO TRADE entry instead of a stock that
    # just vanishes with no record of why. Real reasons only -- no
    # liquidity/spread, IV-vs-expected-move, or expiry-proximity
    # checks added here, since this codebase doesn't compute those
    # yet and fabricating them would violate its own no-fake-data rule.
    no_trade_log = []
    
    for stock in movers:
        sym = stock['symbol']
        tech = _calc_tech(sym, live_quote=stock)
        if not tech:
            no_trade_log.append({"symbol": sym, "reason": "No technical data available"})
            continue
        techs[sym] = tech
        
        price = stock['price']
        # This was 'if price <= 0: continue' -- looks like it catches bad
        # data, but NaN fails EVERY comparison in Python (nan <= 0 is
        # False, not True), so a NaN price slipped straight through this
        # guard and crashed later at qty = int(50000 / price) with
        # "cannot convert float NaN to integer". math.isnan() is required
        # here specifically because <= can't catch it.
        if price <= 0 or math.isnan(price):
            no_trade_log.append({"symbol": sym, "reason": "Invalid or missing price data"})
            continue
        
        rsi = tech['rsi']
        macd = tech['macd']
        vwap = tech['vwap']
        adx = tech.get('adx', 0)
        vol = stock.get('volume', 0)
        vol_avg = tech.get('volume_avg', 1)

        # Same NaN issue can show up in any of the indicators (e.g. a
        # recently-listed stock with under 14 days of history won't have
        # a real ATR/ADX yet). Treat that stock as unscoreable for this
        # cycle instead of letting NaN quietly poison the score/quantity
        # math further down.
        if any(isinstance(v, float) and math.isnan(v) for v in (rsi, macd, vwap, adx, tech.get('atr', 0))):
            no_trade_log.append({"symbol": sym, "reason": "Insufficient history for indicators (NaN)"})
            continue
        
        # Rebalanced to make room for ADX -- a stock can look great on
        # RSI/volume/VWAP/MACD and still be going nowhere (ADX < 20 = no
        # real trend, just noise). This was advertised in the frontend
        # banner ("ADX >= 25") for a long time without ever being checked.
        score = 0
        if 40 <= rsi <= 65: score += 15
        if vol >= vol_avg * 1.5: score += 15
        if adx >= 25: score += 20  # genuine trend strength, not chop

        # Sep 13 2026: SNIPER_V2_CONFIG["REQUIRE_ADX_TREND_STRENGTH"] --
        # see its own comment there for why this exists. Defaults False,
        # so this is a no-op today -- current production behavior is
        # byte-for-byte unchanged unless explicitly enabled.
        if SNIPER_V2_CONFIG["REQUIRE_ADX_TREND_STRENGTH"] and adx < 25:
            no_trade_log.append({"symbol": sym, "reason": f"ADX {adx:.1f} below 25 -- no real trend strength (REQUIRE_ADX_TREND_STRENGTH enabled)"})
            continue

        # Directional confirmation -- this used to be two separate checks
        # ('price > vwap': +15, 'macd > 0': +15) that only ever rewarded
        # the BULLISH combination. A genuinely clean bearish setup
        # (price < vwap AND macd < 0) scored zero here no matter how
        # strong it was, so SELL/PE setups needed a near-perfect RSI +
        # Volume + ADX just to scrape past the gate -- which is why
        # almost everything that qualified was a BUY/CE signal. Both
        # directions now score the same for genuine internal agreement.
        bullish_aligned = price > vwap and macd > 0
        bearish_aligned = price < vwap and macd < 0
        if bullish_aligned or bearish_aligned:
            score += 30

        # Sep 13 2026: REAL BUG FOUND -- the previous line here was
        # `action = "BUY" if bullish_aligned else "SELL"`. That's an
        # implicit two-branch fallback: whenever NEITHER bullish_aligned
        # NOR bearish_aligned was true (price/VWAP and MACD disagree --
        # a genuinely ambiguous/no-trend reading), the `else` silently
        # forced "SELL" anyway, with zero bearish evidence behind it.
        # Since the +30 alignment bonus wasn't earned in that case, this
        # was reachable: RSI-in-range + high volume + ADX>=25 alone
        # (15+15+20=50) exactly clears ENTRY_SCORE_THRESHOLD, meaning a
        # stock with no real directional read could still qualify and
        # get labeled SELL purely by fallthrough, not genuine bearish
        # alignment.
        #
        # Fixed with an explicit three-state classification. NEUTRAL is
        # rejected here, before `action` is assigned or used by anything
        # downstream (hysteresis keying, OI-direction check, SNIPER V2
        # classification, shadow logging, the final signal dict) --
        # every one of those still only ever sees a real "BUY" or "SELL",
        # exactly as before, for the two genuine cases. Nothing about
        # scoring, duplicate protection, recurrence, signal_id, or
        # logging changes -- this only prevents a candidate with no
        # real directional evidence from reaching any of that in the
        # first place.
        directional_bias = "BULLISH" if bullish_aligned else "BEARISH" if bearish_aligned else "NEUTRAL"
        if directional_bias == "NEUTRAL":
            no_trade_log.append({"symbol": sym, "reason": "No clear directional bias -- price-vs-VWAP and MACD sign disagree; rejecting rather than defaulting to SELL"})
            continue

        # Sep 3 2026: action needs to exist BEFORE the gate now -- the
        # hysteresis check below is keyed per (symbol, action), and
        # both bullish_aligned/bearish_aligned are already known at
        # this point, so this is just a reorder, not new logic.
        action = "BUY" if directional_bias == "BULLISH" else "SELL"

        if not _is_qualified_with_hysteresis(sym, action, score):
            no_trade_log.append({"symbol": sym, "reason": f"Technical score {score} below qualification threshold (hysteresis: needs {ENTRY_SCORE_THRESHOLD} to enter, {EXIT_SCORE_THRESHOLD} to exit)"})
            # Sep 8 2026: SHADOW MODE ONLY (see quality_engine.py/
            # shadow_logger.py) -- logs an independent quality
            # assessment for this same rejected candidate using
            # whatever's already available at this point (tech +
            # sector; OI isn't fetched here since this stock never
            # passed the gate v3.0 requires before spending an OI call
            # on it -- no new Fyers traffic added). Purely an observer;
            # the continue below (v3.0's real decision) already happened.
            _evaluate_and_log_shadow(
                sym, action, price, tech, stock, sector_change_map, nifty_change_pct,
                v3_decision="NO_TRADE", v3_score=score, v3_grade=None,
                v3_reason="Technical score below hysteresis threshold",
            )
            continue
        
        atr = tech['atr']
        # These used to be atr*2/3/4 for targets and atr*1.5 for SL -- that's
        # sized for a multi-day swing, not an intraday option trade. One ATR
        # is a realistic estimate of a single session's full range, so
        # targets here are fractions of ONE session's move, not multiples of
        # it. (These are the STOCK-side move sizes; converted to actual
        # option-premium entry/SL/target further down via the contract's
        # own delta -- see below.)
        if action == "BUY":
            stock_sl = round(price - atr * 0.4, 2)
            stock_t1 = round(price + atr * 0.5, 2)
            stock_t2 = round(price + atr * 0.8, 2)
            stock_t3 = round(price + atr * 1.2, 2)
        else:
            stock_sl = round(price + atr * 0.4, 2)
            stock_t1 = round(price - atr * 0.5, 2)
            stock_t2 = round(price - atr * 0.8, 2)
            stock_t3 = round(price - atr * 1.2, 2)
        
        strike = round(price / (100 if price >= 10000 else 50 if price >= 2000 else 20 if price >= 500 else 10)) * (100 if price >= 10000 else 50 if price >= 2000 else 20 if price >= 500 else 10)
        opt_side = 'CE' if action == 'BUY' else 'PE'

        # --- REAL Fyers option-chain data (only for symbols that already
        # cleared the technical filter, to keep API call volume sane) ---
        # This used to be hardcoded/random. If Fyers isn't authenticated or
        # the call fails for any reason, we fall back to price-based
        # technical levels and mark live_oi False -- we never substitute a
        # fake OI/PCR/max-pain number again.
        oi = None
        if is_authenticated():
            try:
                oi = get_option_analytics(f"NSE:{sym}-EQ", strikecount=10)
            except Exception as e:
                print(f"[OI] {sym} fetch failed: {e}")
                oi = None

        # Sep 9 2026: SHADOW MODE ONLY -- MTF trend + stock Futures OI
        # enrichment, at the EXACT SAME "candidate shortlist" boundary
        # the OI fetch right above already establishes (this comment
        # block's own words: "only for symbols that already cleared
        # the technical filter, to keep API call volume sane"). Not a
        # second, separate shortlist decision -- reuses this one.
        #
        # Market-hours safety: this code lives entirely inside
        # _build_all(), which _background_worker() only ever calls
        # from inside `if is_market_hours():` -- confirmed directly at
        # that call site. No separate is_market_hours() check needed
        # here; it's structurally impossible for this to fire outside
        # NSE 09:00-15:40, inheriting the exact same freeze-at-close
        # behavior every other part of this function already has.
        # Strictly feeds evidence for _evaluate_and_log_shadow() below;
        # never read by score/oi_confirmation/pattern or anything that
        # reaches signals.append() or no_trade_log -- v3.0's own
        # selection is completely untouched by these two calls. Own
        # try/except each, same belt-and-braces convention as
        # everything else shadow-mode in this file.
        mtf_data = None
        futures_oi_data = None
        if is_authenticated():
            try:
                from .mtf_trend import get_mtf_trend
                mtf_data = get_mtf_trend(f"NSE:{sym}-EQ")
            except Exception as e:
                print(f"[ShadowMode] {sym} MTF enrichment failed: {e}")
            try:
                from .futures_oi import get_stock_futures_oi
                futures_oi_data = get_stock_futures_oi(sym)
            except Exception as e:
                print(f"[ShadowMode] {sym} futures OI enrichment failed: {e}")

        # --- OI-based quality scoring ---
        # This used to not exist: 'grade' came only from the 4 price/volume
        # checks above (max 70 points), so grades A (>=90) and B (>=80)
        # were mathematically unreachable no matter what. Real quality --
        # does the options market actually agree with this price setup --
        # now supplies the missing points, so a stock only reaches A/B when
        # live OI genuinely confirms the direction, not just on chart
        # pattern alone.
        oi_confirmation = "NO_DATA"
        oi_adjustment = 0
        pattern = None
        # Aug 31 2026: P0-2 from the UI Corrections checklist -- "OI
        # CONFIRMED" implies proof, but check_oi_confirmation_score_bias.py
        # already found CONFIRMED's median base score equals NEUTRAL's
        # exactly (65.0 = 65.0), and NEUTRAL trades outperformed
        # CONFIRMED ~8x in per-trade P&L on real logged data -- CONFIRMED
        # was never actually shown to add predictive value here. oi_reason
        # is ADDITIVE, not a replacement for oi_confirmation (unknown
        # what frontend logic currently keys on that exact string), and
        # uses evidence-language ("aligns with") instead of certainty-
        # language ("confirms").
        oi_reason = None

        if oi:
            buildup = oi.get('oi_buildup') or ''
            bullish_oi = 'PE writing dominant' in buildup
            bearish_oi = 'CE writing dominant' in buildup

            if action == 'BUY' and bullish_oi:
                oi_confirmation, oi_adjustment = "CONFIRMED", 20
                oi_reason = "OI aligns with BUY (PE writing dominant) — not shown to add predictive edge on its own"
            elif action == 'SELL' and bearish_oi:
                oi_confirmation, oi_adjustment = "CONFIRMED", 20
                oi_reason = "OI aligns with SELL (CE writing dominant) — not shown to add predictive edge on its own"
            elif (action == 'BUY' and bearish_oi) or (action == 'SELL' and bullish_oi):
                # CONFLICT used to just be a -15 penalty, which some
                # technically-strong setups could still survive (3 showed
                # up in one day's real log despite the penalty). Checked
                # against actual logged outcomes: the one CONFLICT signal
                # that had resolved by review time hit SL, not target --
                # small sample, but directionally consistent with the
                # obvious reasoning: if the real options market is
                # actively positioned AGAINST your technical direction,
                # that's a materially weaker bet regardless of how good
                # the chart looks. Excluded entirely now, same principle
                # as the confirmed-live-chain requirement -- not just
                # scored down, not shown as a trade recommendation at all.
                #
                # Sep 17 2026 (Zero-Signal Forensic Audit, continued):
                # "bearish_oi"/"bullish_oi" above are a SINGLE narrow
                # measure (chain-wide CE/PE OI-change ratio, no price
                # reference, no futures OI). Before treating that alone
                # as grounds to exclude entirely, check whether futures
                # OI -- already fetched above, already has a real 4-
                # quadrant classifier in quality_engine.py -- agrees.
                # See OI_CONFLICT_REQUIRES_FUTURES_CORROBORATION's own
                # comment (SNIPER_V2_CONFIG above) for the full
                # reasoning and how to revert this with no code change.
                futures_structure_state = None
                if SNIPER_V2_CONFIG["OI_CONFLICT_REQUIRES_FUTURES_CORROBORATION"] and futures_oi_data and futures_oi_data.get("status") == "AVAILABLE":
                    from .quality_engine import evaluate_futures_oi_structure
                    futures_structure_state = evaluate_futures_oi_structure(
                        action, stock.get('change_percent'), futures_oi_data.get('oi_chg_pct')
                    )['state']
                    corroborated = futures_structure_state == 'CONFLICT'
                else:
                    # Flag off, or futures OI unavailable this cycle --
                    # can't corroborate either way, so fall back to the
                    # original behavior: the options-chain reading alone
                    # decides.
                    corroborated = True

                if corroborated:
                    no_trade_log.append({"symbol": sym, "reason": f"OI conflicts with {action} direction ({buildup or 'no clear buildup'})" + (f" -- futures OI agrees ({futures_structure_state})" if futures_structure_state else "")})
                    # Sep 12 2026: a real, confirmed contradiction -- drop
                    # any persisted oi_confirmation state for this (symbol,
                    # action) rather than leaving a stale CONFIRMED sitting
                    # there. This candidate is dropped before signals.append()
                    # this cycle regardless, but the NEXT time it reads
                    # CONFIRMED again, it should have to re-earn entry, not
                    # silently resume as if the conflict never happened.
                    _oi_confirmation_state.pop((sym, action), None)
                    # Sep 8 2026: SHADOW MODE ONLY -- oi is available here
                    # (unlike the hysteresis-fail hook above), so the richer
                    # options_confirmation evidence is too. signal_extra
                    # itself isn't built yet at this exact point in the v3.0
                    # flow, so ce_oi_chg/pe_oi_chg/pcr are read directly off
                    # oi (options_analytics.analyze_option_chain()'s own
                    # confirmed return keys) instead.
                    _evaluate_and_log_shadow(
                        sym, action, price, tech, stock, sector_change_map, nifty_change_pct,
                        v3_decision="NO_TRADE", v3_score=score, v3_grade=None,
                        v3_reason=f"OI conflicts with {action} direction",
                        oi=oi, signal_extra={"ce_oi_chg": oi.get("ce_oi_chg"), "pe_oi_chg": oi.get("pe_oi_chg"), "pcr": oi.get("pcr")},
                        mtf_data=mtf_data, futures_oi_data=futures_oi_data,
                    )
                    continue
                else:
                    # Options chain alone leans against this direction,
                    # but futures OI does NOT corroborate (it read the
                    # opposite quadrant, or NEUTRAL/INSUFFICIENT_DATA) --
                    # score it down instead of killing it outright. Falls
                    # through to the PCR/max-pain logic below exactly
                    # like a genuine NEUTRAL reading would; -10 is a
                    # heuristic penalty, not statistically derived.
                    oi_confirmation, oi_adjustment = "NEUTRAL", -10
                    oi_reason = f"Options chain leans against {action} ({buildup or 'unclear'}), but futures OI does not corroborate ({futures_structure_state or 'unavailable'}) -- scored down, not excluded"
            else:
                oi_confirmation, oi_adjustment = "NEUTRAL", 0
                oi_reason = "OI shows no clear directional lean"

            # PCR as a secondary, smaller confirmation -- classic reading is
            # PCR > 1 = more puts written = bullish support building, and
            # PCR < 0.7 = more calls written = bearish resistance building.
            pcr_val = oi.get('pcr')
            if pcr_val is not None:
                if action == 'BUY' and pcr_val > 1.0:
                    oi_adjustment += 5
                elif action == 'SELL' and pcr_val < 0.7:
                    oi_adjustment += 5

            # Max-pain pinning: with days_to_expiry small and spot already
            # within ~1.5% of max pain, price tends to gravitate there
            # instead of trending -- worth flagging even though it doesn't
            # change the score.
            mp_dist = oi.get('max_pain_dist_pct')
            if mp_dist is not None and abs(mp_dist) < 1.5:
                pattern = 'Range-Pinned'
            elif oi_confirmation == 'CONFIRMED':
                pattern = 'OI-Confirmed Momentum'

        total_score = max(0, min(100, score + oi_adjustment))
        grade = 'A+' if total_score >= 95 else 'A' if total_score >= 85 else 'B' if total_score >= 75 else 'C' if total_score >= 60 else 'D'

        # Sep 12 2026: the actual root-cause fix -- see
        # _is_oi_confirmed_with_hysteresis()'s own docstring above.
        # oi_confirmation itself, not just quality_confirmed, needed
        # this.
        oi_confirmed_persisted = _is_oi_confirmed_with_hysteresis(sym, action, oi_confirmation)

        # Aug 31 2026: P0-4 from the UI Corrections checklist -- "no
        # hidden formulas, every score has a documented factor
        # breakdown." This is NOT a new scoring system, just the exact
        # same 5 components that already made up score/oi_adjustment
        # above, exposed as structured data instead of one opaque
        # percentage. Deliberately does NOT add factors that don't
        # exist yet in this codebase (Breadth, FII/FPI, DII, News/
        # event risk) -- inventing numbers for those would violate
        # this project's own no-fabrication rule.
        score_breakdown = {
            "rsi_favorable": 15 if (40 <= rsi <= 65) else 0,
            "volume_surge": 15 if (vol >= vol_avg * 1.5) else 0,
            "trend_strength_adx": 20 if (adx >= 25) else 0,
            "directional_alignment": 30 if (bullish_aligned or bearish_aligned) else 0,
            "oi_confirmation": oi_adjustment,
        }
        # Sep 1 2026: FO-Radar/Sniper V2 logic review asks "does a large
        # OI bonus let a technically weak setup outrank a stronger
        # one?" -- checked before adding anything: `score` here IS
        # already the pre-OI base score, and it's already exposed below
        # as "technical_score". No new field needed -- score_breakdown
        # (added earlier this session) plus technical_score already
        # answer this exact question.

        if oi:
            strike = oi.get('atm_strike') or strike
            greeks = (oi.get('greeks') or {}).get(opt_side, {})
            signal_extra = {
                "ce_oi": oi.get('ce_oi'), "pe_oi": oi.get('pe_oi'),
                "ce_oi_chg": oi.get('ce_oi_chg'), "pe_oi_chg": oi.get('pe_oi_chg'),
                # Aug 31 2026: Section 11 from the UI Corrections checklist
                # -- "define exactly whether PCR is total OI PCR, volume
                # PCR, or another measure." pcr_volume was ALREADY computed
                # by options_analytics.py's analyze_option_chain() (its own
                # compute_pcr_volume()) but never surfaced here -- this
                # codebase already had the second measure, it just wasn't
                # exposed. pcr_definition makes explicit which one "pcr"
                # itself is, since the two can (and do) disagree.
                "pcr": oi.get('pcr'), "pcr_volume": oi.get('pcr_volume'),
                "pcr_definition": "OI-based (total Put OI / total Call OI across the chain)",
                "days_to_expiry": oi.get('days_to_expiry'), "expiry_date": oi.get('expiry_date'),
                "max_pain": oi.get('max_pain'),
                "iv": oi.get('iv') if oi.get('iv') is not None else tech.get('hist_vol', 20),
                "resistance": oi.get('resistance') or tech.get('resistance', round(price * 1.05, 2)),
                "support": oi.get('support') or tech.get('support', round(price * 0.95, 2)),
                "oi_buildup": oi.get('oi_buildup'),
                "max_pain_dist_pct": oi.get('max_pain_dist_pct'),
                "delta": greeks.get('delta'), "theta": greeks.get('theta'),
                "vega": greeks.get('vega'), "gamma": greeks.get('gamma'),
                "live_oi": True,
            }
        else:
            # Honest fallback: price-action support/resistance and
            # historical volatility instead of options data. None (not 0,
            # not 1.0) for anything we genuinely cannot know without a
            # live option chain, so the frontend can show "--" instead of
            # a confident-looking fake number.
            signal_extra = {
                "ce_oi": None, "pe_oi": None, "ce_oi_chg": None, "pe_oi_chg": None,
                "pcr": None, "pcr_volume": None, "pcr_definition": None,
                "days_to_expiry": None, "expiry_date": None,
                "max_pain": None,
                "iv": tech.get('hist_vol', 20),
                "resistance": tech.get('resistance', round(price * 1.05, 2)),
                "support": tech.get('support', round(price * 0.95, 2)),
                "oi_buildup": None,
                "max_pain_dist_pct": None,
                "delta": None, "theta": None, "vega": None, "gamma": None,
                "live_oi": False,
            }

        # Aug 31 2026: Section 3 from the UI Corrections checklist --
        # "Support/Resistance: add source and distance from current
        # price." Computed once here (after both branches above
        # converge) rather than duplicated inside each -- support/
        # resistance themselves were already being set (from real OI
        # walls when live_oi is True, from price-action fallback
        # otherwise); this just adds how far away they actually are.
        # None if either input is missing, never a fabricated distance.
        supp, res = signal_extra.get("support"), signal_extra.get("resistance")
        signal_extra["support_distance_pct"] = round((price - supp) / price * 100, 2) if supp else None
        signal_extra["resistance_distance_pct"] = round((res - price) / price * 100, 2) if res else None

        # --- Reuse an already-locked trade plan if one exists ---
        # Aug 31 2026: P0-7 (Audit Snapshot) from the UI Corrections
        # checklist -- "persist every input used for the decision...
        # historical signal can be reconstructed exactly." Built from
        # values already computed above by this point -- nothing
        # re-fetched, nothing invented. Deliberately does NOT include
        # FII/DII (no real data source exists yet in this codebase --
        # same blocker Dashboard.jsx already flags) or market-wide
        # breadth (would mean recomputing _compute_breadth() per
        # signal, real added cost for a value that's about the whole
        # market, not this specific decision -- worth doing properly
        # later, not rushed in here). score_version lets a later
        # scoring-rule change be told apart from an old signal's math
        # without needing to diff the code by date.
        audit_snapshot = {
            "score_version": "2026-08-31-a",
            "price": price, "rsi": round(rsi, 2), "macd": round(macd, 4),
            "vwap": round(vwap, 2), "adx": round(adx, 1), "atr": round(atr, 2),
            "volume": vol, "volume_avg": vol_avg,
            "pcr": signal_extra.get("pcr"), "pcr_volume": signal_extra.get("pcr_volume"),
            "pcr_definition": signal_extra.get("pcr_definition"),
            "max_pain": signal_extra.get("max_pain"),
            "iv": signal_extra.get("iv"), "support": signal_extra.get("support"),
            "resistance": signal_extra.get("resistance"),
            "support_distance_pct": signal_extra.get("support_distance_pct"),
            "resistance_distance_pct": signal_extra.get("resistance_distance_pct"),
            "oi_buildup": signal_extra.get("oi_buildup"), "live_oi": signal_extra.get("live_oi"),
            "sector": stock["sector"],
            "india_vix": (cycle_vix or {}).get("price"),
            "captured_at": datetime.now().isoformat(),
        }

        # --- Reuse an already-locked trade plan if one exists ---
        # This used to recompute entry/SL/target1-3 from scratch every
        # single cycle for a stock that was ALREADY an active signal --
        # since price/ATR/premium all drift throughout the day, the same
        # stock could show SL=10 one cycle and SL=5 the next, which is
        # useless to actually trade off of. A trade plan has to hold
        # still once it's shown to you. If this (symbol, action) is
        # already being tracked today (still active, or within the
        # cooldown/reactivation window), reuse its exact frozen numbers
        # instead of deriving new ones. Only a genuinely new signal (or
        # one whose earlier plan already resolved via SL/Target 3) gets
        # fresh numbers computed below.
        from .excel_logger import get_locked_plan
        locked = get_locked_plan(sym, action)
        # Aug 27 2026: deferred import matching this file's existing
        # convention (get_locked_plan right above is imported the same
        # way) -- used by both branches below.
        from .lot_size_resolver import get_lot_size

        # Sep 8 2026: SHADOW MODE ONLY -- safe default BEFORE the
        # locked/fresh branch below, same defensive pattern this file's
        # own risk_amount/price_basis fix already uses a few lines down
        # ("that one only exists inside the fresh-computation branch,
        # not the locked-plan-reuse branch, so referencing it here
        # would crash"). A REUSED locked plan doesn't re-fetch a fresh
        # option-chain leg at all (that's the whole point of reusing
        # frozen numbers), so it genuinely has no fresh leg liquidity
        # data -- None here is honest, not a bug. Only the fresh-
        # computation branch below overwrites this with a real dict.
        shadow_option_leg = None

        if locked:
            entry, strike = locked['entry'], locked['strike'] or strike
            sl = locked['sl']
            t1, t2, t3 = locked['target1'], locked['target2'], locked['target3']
            # Sep 12 2026: was `locked['quantity'] or get_lot_size(sym) or 1`
            # -- that final `or 1` is the exact same class of bug
            # index_signal.py's own Sep 10 fix already root-caused and
            # removed for index calls (an arbitrary quantity standing in
            # for the real exchange lot size, silently wrong regardless
            # of which number it happened to be). Genuinely rare -- an
            # already-locked plan whose stored quantity is somehow empty
            # AND a fresh lot-size lookup also fails -- but "rare" isn't
            # "safe to guess a real position size for." Skip instead,
            # same as every other missing-data path in this function.
            qty = locked['quantity'] or get_lot_size(sym)
            if qty is None:
                no_trade_log.append({"symbol": sym, "reason": f"Locked plan for {sym} {action} has no stored quantity and lot size is unresolvable -- not guessing a position size"})
                continue
            rr = locked['risk_reward'] or 1.5
            option_symbol = locked['option_symbol']
            # Already-tracked outcome status for this locked plan -- see
            # get_locked_plan()'s Aug 20 update. A genuinely fresh signal
            # (the else branch below) hasn't had a chance to hit anything
            # yet, so it starts at sl_hit=False / furthest_target_hit=0.
            sl_hit = locked.get('sl_hit', False)
            furthest_target_hit = locked.get('furthest_target_hit', 0)
        else:
            sl_hit = False
            furthest_target_hit = 0
            # --- Convert the stock-side move into REAL option-premium terms ---
            # This used to just reuse the STOCK price as entry/SL/target (e.g.
            # "Entry ₹1,141.20" for what's supposed to be an options trade) --
            # a stock moving ₹15 does not mean the option premium also moves
            # ₹15. Translate the stock-side move into a premium move using the
            # contract's own delta.
            #
            # IMPORTANT CHANGE: this used to fall back to a Black-Scholes
            # ESTIMATE (using historical volatility as a stand-in for IV)
            # whenever Fyers didn't return a live option chain, and presented
            # that estimate exactly the same way as a real quote -- "SELL PE
            # — ₹400 STRIKE, Entry ₹3.90" with no way to tell it wasn't a
            # real, tradeable price. That's what produced confident-looking
            # recommendations on stocks where no live chain could be
            # confirmed. A trade recommendation now REQUIRES a real, live
            # Fyers option chain for this exact strike -- no chain, no
            # signal, full stop. (estimate_option_premium() is still in
            # options_analytics.py and still used elsewhere -- e.g. the OI
            # Analytics tab's fallback display -- just not for something that
            # tells you to place a trade.)
            premium_entry = None
            delta_for_premium = None
            option_symbol = None

            if oi:
                row = next((r for r in oi.get('rows', []) if r['strike'] == strike), None)
                leg = (row or {}).get(opt_side.lower()) if row else None
                if leg and leg.get('ltp'):
                    premium_entry = leg['ltp']
                    delta_for_premium = leg.get('delta', signal_extra.get('delta'))
                    option_symbol = leg.get('symbol') or None

            if premium_entry is None or delta_for_premium is None:
                # No confirmed live option chain for this exact strike --
                # skip. Don't invent a premium, and don't recommend a trade
                # we can't confirm is actually tradeable.
                no_trade_log.append({"symbol": sym, "reason": f"No confirmed live option chain for {strike} strike"})
                _evaluate_and_log_shadow(
                    sym, action, price, tech, stock, sector_change_map, nifty_change_pct,
                    v3_decision="NO_TRADE", v3_score=score, v3_grade=None,
                    v3_reason="No confirmed live option chain for this strike",
                    oi=oi, signal_extra=signal_extra,
                    mtf_data=mtf_data, futures_oi_data=futures_oi_data,
                )
                continue

            # Aug 31 2026: Section 9 (Risk Engine) from the UI Corrections
            # checklist -- "liquidity filter: reject signals with poor
            # volume/OI or excessive bid-ask spread." bid/ask were already
            # being fetched on this exact leg (options_analytics.py's
            # parse_option_chain()) but never checked -- entry was trusted
            # off ltp alone regardless of how wide the real tradeable
            # spread was. 15% of ltp is a reasonable starting cutoff, not
            # a historically validated one -- flagged as such, easy to
            # tighten/loosen once you've watched how often it actually
            # fires against real contracts.
            bid, ask = leg.get('bid'), leg.get('ask')

            # Sep 8 2026: SHADOW MODE ONLY -- real option-leg liquidity
            # data for the hard gate, built once here and reused at
            # every downstream _evaluate_and_log_shadow() call site
            # below (this is the FIRST point in v3.0's own flow where
            # leg/bid/ask are resolved -- see that function's own
            # option_leg parameter docstring for why the earlier
            # rejection points don't have this).
            shadow_option_leg = {'oi': leg.get('oi'), 'volume': leg.get('volume'), 'bid': bid, 'ask': ask, 'ltp': premium_entry}

            if bid is not None and ask is not None and ask > 0:
                spread_pct = round((ask - bid) / premium_entry * 100, 1)
                if spread_pct > 15:
                    no_trade_log.append({"symbol": sym, "reason": f"Spread too wide on {strike} {opt_side}: {spread_pct}% of premium (bid {bid}, ask {ask})"})
                    _evaluate_and_log_shadow(
                        sym, action, price, tech, stock, sector_change_map, nifty_change_pct,
                        v3_decision="NO_TRADE", v3_score=score, v3_grade=None,
                        v3_reason=f"Option spread too wide ({spread_pct}% of premium)",
                        oi=oi, signal_extra=signal_extra, option_leg=shadow_option_leg,
                        mtf_data=mtf_data, futures_oi_data=futures_oi_data,
                    )
                    continue

            d = max(abs(delta_for_premium), 0.05)  # floor so deep OTM deltas don't zero out the math
            # SL loses MORE than delta alone implies -- theta/gamma work
            # against you on an adverse move too, so weight it up rather than
            # a straight delta-only translation, which would understate real
            # option risk.
            entry = round(premium_entry, 2)
            # Sep 6 2026: real bug, traced from a concrete pattern in the
            # actual backtest data -- 10 trades on 2026-08-25 alone, all
            # entering at genuinely cheap premiums (Rs 0.60-2.85), all
            # showing an exit of exactly Rs 0.05 with outcome "SL Hit".
            # Root cause: this formula's raw SL distance easily exceeds a
            # cheap premium itself, going negative -- and `max(0.05, ...)`
            # was silently forcing that through as if Rs 0.05 were a real,
            # meaningful stop level, rather than recognizing that no sane
            # SL exists for this premium at this delta. A near-zero SL is
            # nearly guaranteed to be hit by ordinary theta decay alone,
            # regardless of whether the underlying thesis was even right --
            # not a real bounded-risk setup, just a broken calculation
            # forced through. Same "skip rather than fabricate" rule the
            # spread check right above this already follows -- this is the
            # option-premium equivalent, just never applied here before.
            raw_sl = premium_entry - d * abs(price - stock_sl) * 1.4
            if raw_sl <= 0.05:
                no_trade_log.append({"symbol": sym, "reason": f"No sane SL for {strike} {opt_side}: premium Rs {premium_entry} too cheap for this delta/distance to translate into a real stop level"})
                _evaluate_and_log_shadow(
                    sym, action, price, tech, stock, sector_change_map, nifty_change_pct,
                    v3_decision="NO_TRADE", v3_score=score, v3_grade=None,
                    v3_reason="Premium too cheap for a sane SL at this delta/distance",
                    oi=oi, signal_extra=signal_extra, option_leg=shadow_option_leg,
                    mtf_data=mtf_data, futures_oi_data=futures_oi_data,
                )
                continue
            sl = round(raw_sl, 2)
            t1 = round(premium_entry + d * abs(stock_t1 - price), 2)
            t2 = round(premium_entry + d * abs(stock_t2 - price), 2)
            t3 = round(premium_entry + d * abs(stock_t3 - price), 2)

            # Aug 27 2026: real, live-resolved NSE lot size -- REPLACES
            # int(50000/entry) entirely. That old math gave a cheap-
            # premium stock a wildly oversized position purely because
            # it was cheap, nothing to do with signal quality (real
            # example: a Rs 4.03 premium got ~12,400 units vs a
            # Rs 11.60 premium's ~4,300, same Rs 50k budget). One real
            # lot is what a trader actually holds. No confirmed live
            # lot size for this symbol -> skip the signal entirely,
            # same "no confirmed data, no signal" rule already applied
            # a few lines up for a missing option chain -- never
            # fabricate a quantity.
            lot_size = get_lot_size(sym)
            if lot_size is None:
                no_trade_log.append({"symbol": sym, "reason": "No confirmed live lot size"})
                _evaluate_and_log_shadow(
                    sym, action, price, tech, stock, sector_change_map, nifty_change_pct,
                    v3_decision="NO_TRADE", v3_score=score, v3_grade=None,
                    v3_reason="No confirmed live lot size",
                    oi=oi, signal_extra=signal_extra, option_leg=shadow_option_leg,
                    mtf_data=mtf_data, futures_oi_data=futures_oi_data,
                )
                continue
            qty, budget_skip_reason = compute_qty_with_risk_budget(lot_size, entry, sl, get_risk_budget_rupees())
            if qty is None:
                no_trade_log.append({"symbol": sym, "reason": budget_skip_reason})
                _evaluate_and_log_shadow(
                    sym, action, price, tech, stock, sector_change_map, nifty_change_pct,
                    v3_decision="NO_TRADE", v3_score=score, v3_grade=None,
                    v3_reason=budget_skip_reason,
                    oi=oi, signal_extra=signal_extra, option_leg=shadow_option_leg,
                    mtf_data=mtf_data, futures_oi_data=futures_oi_data,
                )
                continue
            risk = abs(entry - sl)
            rr = round(abs(t1 - entry) / risk, 2) if risk else 1.5

        # Aug 31 2026: Section 9 (Risk Engine) from the UI Corrections
        # checklist. Computed here (after locked/fresh converge) using
        # entry/sl/qty directly, NOT the `risk` variable above -- that
        # one only exists inside the fresh-computation branch, not the
        # locked-plan-reuse branch, so referencing it here would crash
        # on any already-tracked signal.
        # risk_amount: "risk per trade, calculated from entry to SL" --
        # real rupees, not just the per-unit premium difference.
        # price_basis: "explicitly identify which price entry/SL/target
        # refers to" -- confirmed via the P0-1 R:R check earlier this
        # session that these are ALWAYS option-premium levels, never
        # underlying, for every signal this engine produces. A fixed
        # label, not computed per-signal, because it's a property of
        # this system's design (always buys premium), not something
        # that varies signal to signal.
        risk_amount = round(abs(entry - sl) * qty, 2)
        reward_amount = round(abs(t1 - entry) * qty, 2)
        price_basis = "option_premium"
        # Aug 31 2026: Section 3 -- "add signal age." A genuinely fresh
        # signal (locked is None) is 0 minutes old by definition, no
        # lookup needed. A reused/locked plan's real creation time now
        # comes back from get_locked_plan() (see excel_logger.py) --
        # None only if that timestamp genuinely couldn't be recovered
        # (e.g. a pre-existing row from before this field existed).
        if locked and locked.get('created_at'):
            signal_created_at = locked['created_at']
            signal_age_minutes = round((datetime.now() - signal_created_at).total_seconds() / 60, 1)
        elif locked:
            signal_created_at = None
            signal_age_minutes = None
        else:
            signal_created_at = datetime.now()
            signal_age_minutes = 0.0

        # Sep 1 2026: Section 16 from the V2 logic review, "create
        # Signal IDs and Setup IDs" -- a stable identifier for THIS
        # specific signal occurrence, so a recurring setup can be
        # tracked as one thing across its lifetime instead of just
        # symbol+action. Derived purely from data already available
        # (symbol, action, signal_created_at) -- no new Excel column,
        # no schema-change risk. entry_time_bucket reuses the EXACT
        # same 6 windows backtest_signal_pnl.py's own
        # compute_time_of_day_breakdown() already uses, so live
        # signals and historical backtest buckets stay directly
        # comparable rather than drifting apart. Both None only when
        # signal_created_at itself couldn't be recovered (same rare
        # case signal_age_minutes already handles above).
        if signal_created_at:
            setup_id = f"{sym}_{action}_{signal_created_at.strftime('%Y%m%d_%H%M%S')}"
            entry_clock_time = signal_created_at.time()
            entry_time_bucket = None
            for label, b_start, b_end in [
                ("09:15-10:00", dt_time(9, 15), dt_time(10, 0)),
                ("10:00-11:00", dt_time(10, 0), dt_time(11, 0)),
                ("11:00-12:00", dt_time(11, 0), dt_time(12, 0)),
                ("12:00-13:00", dt_time(12, 0), dt_time(13, 0)),
                ("13:00-14:00", dt_time(13, 0), dt_time(14, 0)),
                ("14:00-15:30", dt_time(14, 0), dt_time(15, 30)),
            ]:
                if b_start <= entry_clock_time < b_end:
                    entry_time_bucket = label
                    break
        else:
            setup_id = None
            entry_time_bucket = None

        # Sep 1 2026: FO-Radar/Sniper V2 logic review, "R:R and
        # structural feasibility" -- a target can be mathematically
        # attractive but require price to clear a real support/
        # resistance wall first. Factual, not a threshold I'm
        # inventing: either stock_target1 sits past the nearest wall
        # or it doesn't. None when support/resistance itself isn't
        # available (honest, not a guess). Purely informational --
        # doesn't reject or downgrade anything, same reasoning as
        # everywhere else today: a real behavior change here needs a
        # decision on what to DO with a flagged signal, not a guess.
        resistance_val = signal_extra.get("resistance")
        support_val = signal_extra.get("support")
        if action == "BUY" and resistance_val:
            target1_beyond_resistance = stock_t1 >= resistance_val
        elif action == "SELL" and support_val:
            target1_beyond_resistance = stock_t1 <= support_val
        else:
            target1_beyond_resistance = None

        # Sep 1 2026: relative strength -- how much this stock's own
        # move differs from its sector's average and from NIFTY's,
        # this cycle. Positive stock_vs_sector_pct means it's
        # outperforming its own sector peers, not just moving with
        # them. None when the sector average or NIFTY's change wasn't
        # available this cycle -- never a guessed baseline.
        sector_change_pct = sector_change_map.get(stock["sector"])
        stock_vs_sector_pct = round(stock['change_percent'] - sector_change_pct, 2) if sector_change_pct is not None else None
        stock_vs_index_pct = round(stock['change_percent'] - nifty_change_pct, 2) if nifty_change_pct is not None else None

        # Sep 13 2026: SNIPER STOCKS filter candidates, shadow-only --
        # see _evaluate_shadow_candidates()'s own module-level comment
        # for why historical replay was ruled out and shadow mode was
        # built instead. Computed here, purely observational -- nothing
        # below this line reads shadow_candidates to decide anything.
        shadow_candidates = _evaluate_shadow_candidates(
            sym, action, price, stock['change_percent'], macd, rsi, adx, vol, vol_avg,
            tech.get('ema20'), tech.get('ema50'),
            support=tech.get('support'), resistance=tech.get('resistance'), stock_t3=stock_t3,
            sector_change_pct=sector_change_pct, nifty_change_pct=nifty_change_pct,
            oi_confirmation=oi_confirmation,
        )

        # Sep 12 2026: SNIPER V2 observability -- see the module-level
        # note above _symbol_daily_state for exactly what this can and
        # cannot honestly claim. Purely additive fields, never gates
        # this signal -- ENABLE_SAME_DAY_SYMBOL_LOCK and
        # ENABLE_RECURRENCE_PENALTY both default False and neither is
        # read anywhere in this function yet; they exist as switches
        # for a FUTURE change once real evidence supports flipping them,
        # not wired to anything that blocks a signal today.
        setup_classification, symbol_day_state, symbol_recurrence = _update_symbol_state_and_classify(
            sym, action, locked, entry, sl, t1, option_symbol,
        )
        # Sep 12 2026: real cross-date history from excel_logger.py's
        # actual persisted logs -- unlike symbol_recurrence above (this
        # SESSION's own memory only, wiped on restart), this survives a
        # restart and knows real prior outcomes, not just "have I seen
        # this symbol since the process started." Cached once per day
        # inside excel_logger.py, not re-scanned per symbol per cycle.
        try:
            from . import excel_logger
            symbol_real_history = excel_logger.get_symbol_recurrence_info(sym)
            # Sep 12 2026: signal_id, threaded onto the live signal dict
            # itself (previously only returned from get_locked_plan(),
            # never actually attached to what _build_all() emits). For
            # a continuing signal, use the real one excel_logger already
            # assigned when the row was written. For a genuinely fresh
            # signal, pre-compute the SAME deterministic value here --
            # excel_logger will independently compute the identical
            # string when sync_active_signals() actually writes the row
            # later this cycle, since the formula depends only on data
            # already resolved at this point (today, sym, action,
            # option_symbol) -- never two different ids for one signal.
            today_str = datetime.now().strftime("%Y-%m-%d")
            signal_id = locked.get("signal_id") if locked else excel_logger.compute_signal_id(today_str, sym, action, option_symbol)
        except Exception as e:
            print(f"[SNIPER V2] Recurrence lookup failed for {sym}: {e}")
            symbol_real_history = None

        # Sep 12 2026: setup_id architecture -- explicitly UNAVAILABLE,
        # not guessed. Real structure/BOS classification (breakout,
        # pullback, reversal, range, etc.) doesn't exist anywhere in
        # this codebase's live data yet; inventing a value from
        # insufficient data is exactly what was explicitly ruled out.
        #
        # IMPORTANT NAMING NOTE: this is deliberately called
        # structure_setup_id, NOT setup_id -- there's already a
        # PRE-EXISTING "setup_id" in this file (Sep 1 2026, "create
        # Signal IDs and Setup IDs", a few hundred lines above --
        # symbol_action_timestamp, identifying THIS signal occurrence).
        # That's a genuinely different concept (signal-instance
        # identity) from what's being built here (which STRUCTURAL
        # SETUP TYPE this represents, once real structure data exists)
        # -- reusing the same name would have silently collided with
        # and been overwritten by the existing dict key. Left completely
        # untouched; this is an ADDITIONAL, separate field.
        structure_setup_id, structure_setup_id_status = None, "UNAVAILABLE_NO_STRUCTURE_DATA"

        # Sep 12 2026: real prior_signal_count (excel_logger's actual
        # persisted history) drives the NEW/RECURRING/HIGH_FREQUENCY_
        # RECURRING bucket -- more authoritative than session-only
        # symbol_recurrence above, which can't see anything before a
        # restart.
        recurrence_status = _recurrence_status((symbol_real_history or {}).get("prior_signal_count", 0))
        shadow_assessment = _build_shadow_assessment(recurrence_status)

        # Sep 12 2026: computed HERE, before append, so it can gate this
        # signal -- previously this same computation only ran AFTER
        # append, purely as a shadow-mode observer. skip_logging=True
        # means shadow_logger isn't called yet; the logging call below
        # (after append) reuses these same values instead of recomputing
        # them, so nothing here doubles up the work or the log.
        quality_result, quality_reasons = _evaluate_and_log_shadow(
            sym, action, price, tech, stock, sector_change_map, nifty_change_pct,
            v3_decision="SIGNAL", v3_score=score, v3_grade=grade, v3_reason=None,
            oi=oi, signal_extra=signal_extra, option_leg=shadow_option_leg,
            mtf_data=mtf_data, futures_oi_data=futures_oi_data, skip_logging=True,
        )
        quality_confirmed = _is_quality_confirmed_with_hysteresis(sym, action, quality_result)

        signals.append({
            "symbol": sym, "name": sym, "price": price,
            "change": stock['change'], "change_percent": stock['change_percent'],
            "grade": grade, "confidence": f"{total_score}%",
            "technical_score": score, "oi_adjustment": oi_adjustment, "score_breakdown": score_breakdown,
            "rsi": rsi, "adx": round(adx, 1),
            "oi_confirmation": oi_confirmation, "oi_reason": oi_reason, "pattern": pattern,
            # Sep 13 2026: raw values for the not-yet-tested SNIPER
            # STOCKS filter candidates -- see excel_logger.py's own
            # COLUMNS comment for why these specific forms (ratio/%
            # rather than raw VWAP/volume). All five already computed
            # this cycle (tech dict, vol/vol_avg, price/vwap) -- purely
            # additive logging, not read by any scoring/qualification
            # code above this point.
            "macd": round(macd, 4),
            "vwap_distance_pct": round((price - vwap) / vwap * 100, 3) if vwap else None,
            "volume_ratio": round(vol / vol_avg, 3) if vol_avg else None,
            "ema20": tech.get("ema20"),
            "ema50": tech.get("ema50"),
            # Sep 13 2026: six shadow candidate PASS/REJECT/UNKNOWN
            # verdicts + their exact reasons -- see
            # _evaluate_shadow_candidates()'s own docstring. Purely
            # observational; none of these were read by anything above
            # this line that decided the real signal.
            **shadow_candidates,
            # Sep 12 2026: the actual root-cause fix, alongside the
            # quality-gate persistence added earlier today -- see
            # _is_oi_confirmed_with_hysteresis()'s docstring above.
            "oi_confirmed_persisted": oi_confirmed_persisted,
            # Sep 12 2026: SNIPER V2 observability fields -- see
            # _update_symbol_state_and_classify()'s own docstring for
            # exactly what these can/cannot claim. None of these gate
            # this signal; ENABLE_SAME_DAY_SYMBOL_LOCK/
            # ENABLE_RECURRENCE_PENALTY are both off and unused so far.
            "setup_classification": setup_classification,
            "symbol_signals_fired_today": (symbol_day_state or {}).get("signals_fired_today"),
            "symbol_first_seen_this_session": (symbol_recurrence or {}).get("first_seen_date"),
            "symbol_prior_occurrences_this_session": len((symbol_recurrence or {}).get("occurrences", [])) - 1 if symbol_recurrence else 0,
            # Sep 12 2026: real persisted history (excel_logger.py) --
            # see symbol_real_history's own comment above for why this
            # is more authoritative than the session-only fields just
            # above it. None (not 0) when this symbol has no real prior
            # occurrence in the cached lookback window.
            "symbol_real_prior_signal_count": (symbol_real_history or {}).get("prior_signal_count"),
            "symbol_real_prior_win_rate": (symbol_real_history or {}).get("prior_win_rate"),
            "symbol_real_last_seen_date": (symbol_real_history or {}).get("last_seen_date"),
            # Sep 12 2026: structure_setup_id -- explicitly unavailable,
            # see structure_setup_id_status computation above for why
            # this isn't guessed from insufficient data. NOT the same
            # key as the pre-existing "setup_id" set later in this same
            # dict (Sep 1 2026 feature, signal-instance identity) --
            # deliberately different name, see that computation's own
            # comment for why reusing "setup_id" here would have
            # silently collided.
            "structure_setup_id": structure_setup_id,
            "structure_setup_id_status": structure_setup_id_status,
            "signal_id": signal_id,
            # Sep 12 2026: config/version metadata -- lets a later
            # review reconstruct which SNIPER V2 config was active when
            # this specific signal was decided, without cross-referencing
            # a separate deploy log.
            "sniper_v2_config_snapshot": {k: v for k, v in SNIPER_V2_CONFIG.items()},
            # Sep 12 2026: previous-signal fields, sourced from
            # excel_logger's real persisted history -- None when there
            # is no real prior occurrence, never a guessed value.
            "previous_signal_id": (symbol_real_history or {}).get("previous_signal_id"),
            "previous_signal_status": (symbol_real_history or {}).get("previous_result"),
            "previous_signal_direction": (symbol_real_history or {}).get("previous_direction"),
            "days_since_last_signal": (symbol_real_history or {}).get("days_since_last_signal"),
            # Sep 12 2026: NEW/RECURRING/HIGH_FREQUENCY_RECURRING bucket
            # and the generic actual/shadow assessment -- see
            # _recurrence_status()/_build_shadow_assessment()'s own
            # docstrings for the "not yet statistically derived"
            # caveat on the specific thresholds/penalty sizes.
            "recurrence_status": recurrence_status,
            "actual_decision": shadow_assessment["actual_decision"],
            "shadow_decision": shadow_assessment["shadow_decision"],
            "shadow_block_reason": shadow_assessment["shadow_block_reason"],
            "shadow_recurrence_penalty": shadow_assessment["shadow_recurrence_penalty"],
            # Sep 12 2026: the new quality-engine confirmation layer --
            # quality_confirmed is what quality_signals below actually
            # gates on (when the feature flag is on); score/verdict/
            # reasons are exposed unconditionally, same "explainable
            # signals" principle as audit_snapshot below, and stay
            # visible even if the gate itself is toggled off, so its
            # would-be effect on the list can be watched before trusting it.
            "quality_confirmed": quality_confirmed,
            "quality_score": (quality_result or {}).get("score"),
            "quality_verdict": (quality_result or {}).get("verdict"),
            "quality_reasons": quality_reasons,
            "audit_snapshot": audit_snapshot,
            "sector": stock["sector"], "signal_type": "SNIPER",
            "action": action, "entry": entry, "quantity": qty,
            "sl": sl, "target1": t1, "target2": t2, "target3": t3,
            "risk_reward": rr, "risk_amount": risk_amount, "reward_amount": reward_amount,
            "price_basis": price_basis, "signal_age_minutes": signal_age_minutes,
            "pcr_chg": None, "option_symbol": option_symbol, "expiry_date": signal_extra.get("expiry_date"),
            # Sep 2 2026: Section 9, "change risk rules close to expiry."
            # 2 days is a near-universal risk marker for options
            # specifically (theta decay and pin risk both spike hard
            # in the final 1-2 sessions, regardless of which strategy
            # is being traded) -- different in kind from thresholds
            # like the spread filter or a score floor, which genuinely
            # are strategy-specific and were deliberately left for
            # validated data rather than guessed. None when
            # days_to_expiry itself isn't available -- never a
            # guessed warning state.
            "near_expiry_warning": (signal_extra.get("days_to_expiry") <= 2) if signal_extra.get("days_to_expiry") is not None else None,
            "stock_sl": stock_sl, "stock_target1": stock_t1,
            "stock_target2": stock_t2, "stock_target3": stock_t3,
            "target1_beyond_resistance": target1_beyond_resistance,
            "setup_id": setup_id, "entry_time_bucket": entry_time_bucket,
            "signal_logic_version": SIGNAL_LOGIC_VERSION,
            "india_vix_at_signal": (cycle_vix or {}).get("price"),
            "participation_quality": tech.get("participation_quality"),
            "rvol": tech.get("rvol"),
            "sector_change_pct": sector_change_pct, "stock_vs_sector_pct": stock_vs_sector_pct,
            "stock_vs_index_pct": stock_vs_index_pct,
            "strike": strike,
            "recommendation": f"{action} {opt_side} — ₹{strike} STRIKE",
            "timestamp": datetime.now().isoformat(),
            "sl_hit": sl_hit,
            "furthest_target_hit": furthest_target_hit,
            "outcome_status": (
                "SL Hit" if sl_hit
                else (f"Target {furthest_target_hit} Hit" if furthest_target_hit else "Open")
            ),
            **signal_extra,
        })

        # Sep 12 2026: quality_result was already computed above (before
        # append, to gate this signal) -- this just logs it, rather than
        # recomputing the whole evaluation a second time the way this
        # call site used to. Same shadow_logger call, same arguments,
        # same log content as before this change. Guarded the same way
        # _evaluate_and_log_shadow's own docstring requires (shadow
        # logging must never be able to break the live scan loop) --
        # that protection used to come from this call living INSIDE that
        # function's own try/except; now that it's out here at the call
        # site instead, it needs its own. Skips entirely when
        # quality_result is None, matching the OLD behavior exactly: a
        # failed computation never produced a shadow log entry before
        # either (the log call sat after the point an exception would
        # have already jumped past it).
        if quality_result is not None:
            try:
                from . import shadow_logger
                shadow_logger.log_shadow_candidate(
                    sym, action, price, "SIGNAL", score, grade, None, quality_result, reasons=quality_reasons,
                    setup_classification=setup_classification,
                    symbol_signals_fired_today=(symbol_day_state or {}).get("signals_fired_today"),
                    symbol_prior_occurrences=(len(symbol_recurrence.get("occurrences", [])) - 1) if symbol_recurrence else 0,
                )
            except Exception as e:
                print(f"[ShadowMode] {sym} shadow log write failed (v3.0 unaffected): {e}")
    
    signals.sort(key=lambda x: int(x['confidence'].replace('%', '')), reverse=True)

    # This used to be a hard signals[:6] regardless of how many stocks
    # actually cleared the bar. It's now everything that clears 65
    # (raised from 60 per feedback that the list was too noisy), capped
    # at 15 (was 20). Combined with the option-chain-confirmation gate
    # above (a signal can no longer exist at all without a real, live
    # Fyers option chain backing it), this cuts noise from both ends:
    # weaker technical setups are excluded, AND setups that technically
    # qualify but have no confirmed tradeable option are gone entirely.
    #
    # Sep 17 2026: per the Zero-Signal Forensic Audit and explicit,
    # scoped approval -- two conditions removed from this specific
    # filter, nothing upstream touched:
    #   - confidence>=85 removed: confidence IS total_score (see
    #     signals.append() above, "confidence": f"{total_score}%"),
    #     so this was the same technical-score gate checked a second
    #     time under a different name. The real technical floor,
    #     ENTRY_SCORE_THRESHOLD=50, already gated everything in
    #     `signals` before this line ever runs -- removing this does
    #     not lower that floor, it removes a duplicate of it.
    #   - oi_confirmed_persisted removed: this required OI to be
    #     specifically CONFIRMED. OI CONFLICT was never gated by this
    #     variable -- it's an outright `continue` far upstream (see
    #     the OI-buildup block above), so NEUTRAL and CONFIRMED both
    #     already reached this point on equal footing; only the
    #     requirement that it be CONFIRMED specifically is removed.
    # quality_confirmed's own bar was separately changed inside
    # _is_quality_confirmed_with_hysteresis() itself (score>=70,
    # TRADE or WATCH) -- not touched again here.
    quality_signals = [
        s for s in signals
        if (not _QUALITY_GATE_ENABLED or s.get('quality_confirmed'))
    ][:15]

    with _cache_lock:
        _signal_cache = quality_signals
        _tech_cache = techs
        _no_trade_cache = no_trade_log

    # Log every newly-appeared signal to today's Excel file, and mark
    # anything that dropped out of the list since last cycle as exited --
    # gives you a running record of the whole day's signals (entry time,
    # entry/SL/targets, how long each stayed active) instead of only ever
    # seeing the current snapshot.
    try:
        from .excel_logger import sync_active_signals, check_outcomes
        newly_logged = sync_active_signals(quality_signals)
        if newly_logged:
            try:
                from trading.telegram_bot import TelegramBot
                bot = TelegramBot()
                for s in newly_logged:
                    bot.send_signal_alert(
                        symbol=s.get("symbol"),
                        signal_type=s.get("action"),
                        entry=s.get("entry"),
                        sl=s.get("sl"),
                        target=s.get("target1"),
                        grade=s.get("grade", "A"),
                    )
            except Exception as e:
                print(f"[Telegram] Failed to send new-signal alert: {e}")
            # Aug 30 2026: the SAME genuinely-new signals, ALSO logged
            # to the positional tracker with wider multi-day SL/Target
            # -- see positional_logger.py's own docstring for exactly
            # how those levels get computed (same delta-based premium
            # translation the intraday engine above already uses, just
            # fed wider stock-side ATR multipliers). Own try/except so
            # a positional-logging problem can never block the
            # already-working intraday logging/Telegram alert above it.
            try:
                from .positional_logger import log_new_positional_signals
                log_new_positional_signals(newly_logged)
            except Exception as e:
                print(f"[PositionalLog] Failed to log new positional signals: {e}")
        if is_authenticated():
            check_outcomes(get_quotes)
            try:
                from .positional_logger import check_positional_outcomes
                check_positional_outcomes(get_quotes)
            except Exception as e:
                print(f"[PositionalLog] Failed to check positional outcomes: {e}")
            try:
                from .shadow_logger import check_shadow_outcomes
                check_shadow_outcomes(get_quotes)
            except Exception as e:
                print(f"[ShadowMode] Failed to check shadow outcomes: {e}")
    except Exception as e:
        print(f"[ExcelLog] sync failed: {e}")

    # NIFTY/BANKNIFTY index snapshotting used to happen right here, but
    # that tied it to this function's own ~2.5-3min real cycle time (the
    # 90s sleep below plus however long the 200-stock scan above it
    # actually takes). Moved to its own faster, independent worker below
    # -- see _index_snapshot_worker -- so index snapshots can run on a
    # ~60s cadence without needing the whole stock scan to also speed up.


def _background_worker():
    from .market_hours import is_market_hours
    last_closed_log = 0
    while True:
        try:
            if is_market_hours():
                _build_all()
                # Sep 17 2026 (Zero-Signal Forensic Audit, continued):
                # pure observability -- no gate, threshold, or behavior
                # touched here. _no_trade_cache already holds every
                # rejection this cycle with a real reason string (every
                # one of these no_trade_log.append() call sites already
                # existed before today); this just buckets them by
                # which gate produced them so "which gate is rejecting
                # everyone" is visible right in this same console line,
                # every cycle, without a separate API call.
                _reason_buckets = [
                    ("neutral_bias", "No clear directional bias"),
                    ("score_below_50", "below qualification threshold"),
                    ("oi_conflict", "OI conflicts with"),
                    ("no_option_chain", "No confirmed live option chain"),
                    ("spread_too_wide", "Spread too wide"),
                    ("no_sane_sl", "No sane SL"),
                    ("no_lot_size", "No confirmed live lot size"),
                    ("no_quantity", "no stored quantity"),
                    ("no_tech_data", "No technical data available"),
                    ("invalid_price", "Invalid or missing price"),
                    ("insufficient_history", "Insufficient history"),
                    ("adx_below_25", "below 25"),
                ]
                _tally = {}
                for _entry in _no_trade_cache:
                    _reason = _entry.get("reason", "")
                    _key = next((k for k, needle in _reason_buckets if needle in _reason), "other")
                    _tally[_key] = _tally.get(_key, 0) + 1
                print(f"[{datetime.now()}] Background refresh complete. Stocks: {len(_stock_cache)}, Signals: {len(_signal_cache)}, Rejected: {len(_no_trade_cache)} -- {_tally}")
                time.sleep(90)
            else:
                # Checking is_market_hours() itself costs nothing -- it's
                # a local time comparison, not a Fyers API call. So check
                # often (every 20s) for near-instant market-open detection
                # instead of the previous flat 300s sleep, which could
                # leave "market just opened" undetected for up to 5
                # minutes worst case (confirmed live: banner still
                # showing zeros 2+ min after open). Only the LOG LINE is
                # throttled to roughly every 5 min -- that was the actual
                # point of the old 300s interval (not spamming identical
                # lines all night), and this keeps that without also
                # slowing down detection.
                now = time.time()
                if now - last_closed_log >= 300:
                    print(f"[{datetime.now()}] Market closed -- waiting.")
                    last_closed_log = now
                time.sleep(20)
        except Exception as e:
            print(f"[{datetime.now()}] Background error: {e}")
            time.sleep(90)

_worker_thread = threading.Thread(target=_background_worker, daemon=True)
if not _IS_RELOADER_WATCHER_PROCESS:
    _worker_thread.start()


# Sep 18 2026: new cache + worker for the market-breadth dashboard.
# _calc_tech() (RSI/MACD/EMA/Bollinger/etc.) has only ever run for
# _build_all()'s top ~30 movers each cycle -- genuine breadth stats
# ("52% of names above 200 EMA", "average RSI sits at 50") need every
# one of the 208 F&O stocks, not a ~30-stock subset, or the dashboard
# would be reporting a number and quietly meaning something narrower
# than what it says.
#
# Real cost, stated plainly rather than assumed away: the FIRST pass
# each day costs roughly 178 additional Fyers history calls (208 minus
# the ~30 _build_all() already covers) -- at the existing ~3 req/s
# governor in fyers_client.py, that's under a minute, once. Every pass
# after that is cheap: _cached_history_df() already caches each
# symbol's history for the rest of the trading day, and this worker
# reuses _stock_cache's own already-fetched live quotes as _calc_tech's
# live_quote (the same free-reuse pattern _build_all() itself already
# uses) -- so no new Fyers calls at all on repeat passes, just pandas
# math over already-cached data.
_breadth_tech_cache = {}
_breadth_cache_lock = threading.Lock()


def _breadth_indicators_worker():
    from .market_hours import is_market_hours
    last_closed_log = 0
    while True:
        try:
            if is_market_hours():
                with _cache_lock:
                    symbols_and_quotes = list(_stock_cache.items())
                computed = {}
                for sym, quote in symbols_and_quotes:
                    tech = _calc_tech(sym, live_quote=quote)
                    if tech:
                        computed[sym] = tech
                    # A symbol that fails this pass (thin history, a
                    # transient Fyers hiccup) simply isn't updated this
                    # cycle -- its previous entry, if any, is left in
                    # place rather than being deleted, same "hold
                    # through a data gap, don't punish a symbol for a
                    # cycle's own failure" principle used everywhere
                    # else in this file for a transient miss.
                with _breadth_cache_lock:
                    _breadth_tech_cache.update(computed)
                print(f"[{datetime.now()}] Breadth indicators refreshed: {len(computed)}/{len(symbols_and_quotes)} stocks.")
                time.sleep(180)
            else:
                now = time.time()
                if now - last_closed_log >= 300:
                    print(f"[{datetime.now()}] Breadth worker: market closed -- waiting.")
                    last_closed_log = now
                time.sleep(20)
        except Exception as e:
            print(f"[{datetime.now()}] Breadth worker error: {e}")
            time.sleep(90)


_breadth_worker_thread = threading.Thread(target=_breadth_indicators_worker, daemon=True)
if not _IS_RELOADER_WATCHER_PROCESS:
    _breadth_worker_thread.start()


def _evaluate_and_log_index_shadow(name, fyers_symbol, bias, spot, atr, oi, call, price_change_pct=None, fut_oi_chg_pct=None, atm_strike=None):
    """
    Sep 8 2026: SHADOW MODE ONLY -- index counterpart to
    _evaluate_and_log_shadow() above. Same non-negotiable: this NEVER
    influences index_signal.generate_index_call()'s own real decision,
    always called AFTER that decision is already final, purely an
    observer, own try/except so a shadow-evaluation problem can never
    affect the real index call loop.

    Sep 8 2026, UPDATED: futures_oi and options_structure were
    honestly None all session, blocked on index_tracker.py's exact
    field names. Now confirmed directly from that file's real source:
    row["Fut OI Chg %"] (a signed %, Fyers' own oipercent, already on
    the same row dict the caller already has) and row["Change %"] for
    price_change_pct. options_structure needed NOTHING new -- oi here
    comes from the identical get_option_analytics() call stocks use
    (index_tracker.py's snapshot_index(): oi = get_option_analytics(
    fyers_symbol, strikecount=10)), so it already carries the same
    ce_oi_chg/pe_oi_chg/pcr fields evaluate_options_structure() above
    was built for -- reused verbatim, not reimplemented.

    atm_strike: Sep 8 2026 addition -- row["ATM Strike"], a confirmed
    real field from index_tracker.py's own COLUMNS list. Used for a
    genuine option-liquidity hard gate below. Deliberately does NOT
    try to replicate generate_index_call()'s own exact strike
    selection (support-vs-resistance wall logic) -- that source wasn't
    available to confirm this session, and guessing which strike it
    picked risks silently reading the WRONG leg's liquidity. Instead
    uses the ATM strike with the same BUY->CE / SELL->PE convention
    already used consistently everywhere else in this codebase (not a
    guess specific to this function) -- a defensible, real liquidity
    read near the money, not a replica of v3.0's internal choice.
    """
    try:
        from . import quality_engine as qe

        action = "BUY" if (bias or "").startswith("Bullish") else ("SELL" if (bias or "").startswith("Bearish") else None)
        if action is None or spot is None:
            return  # Neutral/unknown bias -- nothing directional to compare yet, same as generate_index_call()'s own gate

        # Sep 8 2026: HARD GATE (spec section 3C, option liquidity) --
        # same evaluate_liquidity_gate() already used for stocks, reused
        # verbatim, not reimplemented. option_oi/volume/bid/ask/ltp come
        # from the ATM strike's CE or PE leg in oi['rows'] (same row
        # shape stocks use, per this function's own earlier-confirmed
        # reuse of get_option_analytics()). Stock-side volume concepts
        # don't apply to an index the same way, so avg_volume/
        # current_volume are left None here -- correctly marked
        # unavailable rather than a stock-shaped number forced onto an
        # index.
        atm_leg = None
        if oi and atm_strike is not None:
            atm_row = next((r for r in oi.get('rows', []) if r.get('strike') == atm_strike), None)
            side_key = 'ce' if action == 'BUY' else 'pe'
            atm_leg = (atm_row or {}).get(side_key)
        liquidity_result = qe.evaluate_liquidity_gate(
            avg_volume=None, current_volume=None,
            option_oi=(atm_leg or {}).get('oi'), option_volume=(atm_leg or {}).get('volume'),
            bid=(atm_leg or {}).get('bid'), ask=(atm_leg or {}).get('ask'), ltp=(atm_leg or {}).get('ltp'),
        )
        hard_gate_failures = liquidity_result['reasons']

        index_indicators = _calc_index_indicators(name, fyers_symbol)
        price_structure = {"state": "INSUFFICIENT_DATA"}
        if index_indicators:
            hist_df = _cached_index_history_df(name, fyers_symbol, days=100)
            if hist_df is not None and len(hist_df) >= 21:
                price_structure = qe.detect_price_structure(
                    list(hist_df['Close']) + [spot],
                    list(hist_df['High']) + [spot],
                    list(hist_df['Low']) + [spot],
                )

        with _cache_lock:
            index_direction = "UP" if (_index_cache.get("nifty50" if name == "NIFTY" else "banknifty") or {}).get("change_percent", 0) >= 0 else "DOWN"
            stocks_snapshot = list(_stock_cache.values())
            vix_snapshot = _index_cache.get("india_vix") or {}
        breadth_data = _compute_breadth(stocks_snapshot)
        breadth_result = qe.evaluate_index_breadth(
            index_direction, breadth_data.get("advances_pct"), breadth_data.get("declines_pct"),
        )
        vix_result = qe.evaluate_index_vix(index_direction, vix_snapshot.get("change_percent"))

        futures_oi_result = qe.evaluate_futures_oi_structure(action, price_change_pct, fut_oi_chg_pct)

        options_structure_result = {"state": "INSUFFICIENT_DATA"}
        if oi:
            options_structure_result = qe.evaluate_options_structure(
                action, price_change_pct, oi.get("ce_oi_chg"), oi.get("pe_oi_chg"), oi.get("pcr"),
            )

        def _sub_score(state, max_pts, good_states):
            if state == "INSUFFICIENT_DATA":
                return None
            if state in good_states:
                return max_pts
            if state == "NEUTRAL":
                return max_pts * 0.3
            return 0.0

        evidence = {
            "price_structure": _sub_score(price_structure['state'], 25, ("BULLISH_STRUCTURE", "BEARISH_STRUCTURE")),
            "futures_oi": _sub_score(futures_oi_result['state'], 20, ("CONFIRMED",)),
            "options_structure": _sub_score(options_structure_result['state'], 25, ("CONFIRMED",)),
            "breadth": _sub_score(breadth_result['state'], 15, ("CONFIRMED",)),
            "vix": _sub_score(vix_result['state'], 15, ("SUPPORTIVE",)),
        }
        quality_result = qe.compute_index_quality_score(evidence, hard_gate_failures=hard_gate_failures)
        quality_result['futures_oi_quadrant'] = futures_oi_result.get('quadrant')
        quality_result['options_ce_quadrant'] = options_structure_result.get('ce_quadrant')
        quality_result['options_pe_quadrant'] = options_structure_result.get('pe_quadrant')

        # Sep 8 2026: same explainable-signals treatment as the stock
        # glue function -- compiled from state already computed above,
        # nothing new fetched.
        reasons = []
        for r in liquidity_result['reasons']:
            reasons.append(f"HARD GATE: {r}")
        if price_structure['state'] in ("BULLISH_STRUCTURE", "BEARISH_STRUCTURE"):
            tag = "Bullish" if price_structure['state'] == "BULLISH_STRUCTURE" else "Bearish"
            brk = f", {price_structure['breakout']} breakout" if price_structure.get('breakout') else ""
            reasons.append(f"{tag} price structure{brk}")
        if breadth_result['state'] == "CONFIRMED":
            reasons.append(f"Breadth confirms ({index_direction} move with strong participation)")
        elif breadth_result['state'] == "WEAK":
            reasons.append(f"Weak breadth -- {index_direction} move not broadly participated")
        if vix_result['state'] == "SUPPORTIVE":
            reasons.append("VIX environment supportive")
        elif vix_result['state'] == "CAUTION":
            reasons.append("VIX expanding sharply -- caution warranted")
        if futures_oi_result['state'] == "CONFIRMED":
            reasons.append(f"Futures OI confirms ({futures_oi_result['quadrant']})")
        elif futures_oi_result['state'] == "CONFLICT":
            reasons.append(f"Futures OI conflicts ({futures_oi_result['quadrant']})")
        if options_structure_result['state'] == "CONFIRMED":
            reasons.append(f"Options structure confirms (CE {options_structure_result['ce_quadrant']}, PE {options_structure_result['pe_quadrant']})")
        elif options_structure_result['state'] == "CONFLICT":
            reasons.append(f"Options structure conflicts (CE {options_structure_result['ce_quadrant']}, PE {options_structure_result['pe_quadrant']})")
        if quality_result['confirmations_count'] < 4:
            reasons.append(f"Only {quality_result['confirmations_count']} of 5 evidence groups confirm -- spec prefers >=4")

        v3_decision = "SIGNAL" if call else "NO_TRADE"
        v3_reason = None if call else "Bias neutral or no live premium/delta at the target wall strike"

        from . import shadow_logger
        shadow_logger.log_shadow_candidate(name, action, spot, v3_decision, None, None, v3_reason, quality_result, reasons=reasons)
    except Exception as e:
        print(f"[ShadowMode] {name} index evaluation failed (v3.0 unaffected): {e}")


def _index_snapshot_worker():
    """
    Separate, faster loop just for NIFTY/BANKNIFTY snapshots -- was
    previously done inside _build_all() above, which tied index
    snapshots to that function's real cycle time (its own 90s sleep
    plus however long the 200-stock scan actually takes on top of
    that -- around 2.5-3 min in practice, not 90s). A 2-index quote
    fetch is cheap enough to run on its own much faster ~60s cadence
    without meaningfully adding to Fyers API load the way re-running
    the whole stock scan that often would. Calls _fetch_index directly
    each cycle for genuinely fresh data, not a stale cached value, and
    now also WRITES that fetch into the shared _index_cache (see
    _build_all() above) so that function reuses it instead of
    independently re-fetching the same 3 symbols. That duplication used
    to be accepted as "lightweight enough not to matter" -- confirmed
    Aug 20 2026 that it was a real, meaningful contributor to hitting an
    actual Fyers 429 rate limit on /quotes, not just a lightweight
    quote-call tradeoff, so it's eliminated now rather than accepted.

    Also snapshots commodities (crude oil) every cycle now --
    snapshot_all_commodities() gates itself internally via
    index_tracker.is_mcx_hours(), completely independent of the NSE-only
    is_market_hours() check below, since MCX runs a longer session.
    That's why this call sits outside the `if is_market_hours()` branch:
    it needs to keep running (and simply no-op once genuinely outside
    MCX hours too) even after NSE closes for the day. The sleep interval
    reflects that too -- stays on the fast 60s cadence as long as EITHER
    market is open, only drops to the slow 300s check once both are shut.

    Aug 27 2026: also turns a confirmed NIFTY/BANKNIFTY Bias into an
    actual tradeable options call -- see index_signal.py's module
    docstring for the full reasoning (strike-at-the-OI-wall, same SL/
    Target math as the stock engine). Uses THIS cycle's own snapshot_
    all() result (index_tracker.get_last_oi_snapshot() -- same oi dict
    already fetched, no second option-chain call) plus the index's own
    ATR (fetched/cached separately, ~once/day via _calc_index_atr()).
    Runs only when NSE is open -- an index options call doesn't apply
    outside NSE F&O hours the way commodity snapshotting does.
    """
    from .market_hours import is_market_hours
    from .index_tracker import snapshot_all, snapshot_all_commodities, is_mcx_hours, get_last_oi_snapshot
    from . import index_signal
    from .oi_live_dashboard import write_live_dashboard, get_dashboard_path
    from .excel_logger import _FileLock
    last_closed_log = 0
    while True:
        try:
            nse_open = is_market_hours()
            if nse_open:
                # Sep 3 2026: was 3 separate _fetch_index() calls -- see
                # _fetch_indices_batched()'s docstring.
                _batched_idx = _fetch_indices_batched()
                nifty = _batched_idx["NIFTY 50"]
                bank = _batched_idx["BANKNIFTY"]
                vix = _batched_idx["INDIA VIX"]
                sensex = _batched_idx["SENSEX"]
                global _index_cache, _index_cache_updated_at
                with _cache_lock:
                    _index_cache = {"nifty50": nifty, "banknifty": bank, "india_vix": vix, "sensex": sensex}
                    _index_cache_updated_at = time.time()
                index_rows = snapshot_all(
                    change_percents={
                        "NIFTY": nifty.get("change_percent"),
                        "BANKNIFTY": bank.get("change_percent"),
                        "SENSEX": sensex.get("change_percent"),
                    },
                    vix=vix.get("price"),
                )

                # Sep 16 2026: live Excel mirror of the same option-chain
                # snapshot just produced above -- no second OI calculation,
                # no extra Fyers request, index_rows IS the same dict
                # write_live_dashboard() expects (confirmed: snapshot_index()'s
                # own row already has every key _build_values() reads --
                # Time/Spot/PCR/Bias/Total Call OI/Total Put OI/Highest
                # Call OI Strike+Value/Highest Put OI Strike+Value).
                # oi_live_dashboard.py already had every piece of this
                # (xlwings visible-Excel control, reconnect-on-close,
                # boundary panels, colour coding) -- it was simply never
                # called anywhere in this file until now.
                #
                # Locked the same way shadow_logger.py/excel_logger.py's
                # writes were locked earlier this session: xlwings drives a
                # live Excel COM instance, and if this scan cycle is ever
                # running in two processes at once (the same Django
                # autoreloader risk already flagged), each process's own
                # _next_row counter has no way to know about the other's --
                # they could both decide "row 5 is next" and overwrite each
                # other. try/except here is separate from (and outside) the
                # lock so a genuine Excel-side failure -- the file open in
                # another program, xlwings not installed, Excel crashed --
                # can never take down the scan cycle itself; every
                # individual write inside write_live_dashboard() already has
                # its own try/except too, this is a second layer, not the
                # only one.
                global _dashboard_consecutive_failures, _dashboard_disabled_this_session
                if not _dashboard_disabled_this_session:
                    try:
                        with _FileLock(get_dashboard_path(), timeout=15):
                            write_live_dashboard(index_rows)
                        _dashboard_consecutive_failures = 0
                    except Exception as e:
                        _dashboard_consecutive_failures += 1
                        if _dashboard_consecutive_failures >= _DASHBOARD_MAX_CONSECUTIVE_FAILURES:
                            _dashboard_disabled_this_session = True
                            print(f"[OILiveDashboard] Failed {_dashboard_consecutive_failures} cycles in a row "
                                  f"({e}) -- disabling for the rest of this session rather than repeating this "
                                  f"every cycle. Everything else continues normally; restart the server to retry.")
                        else:
                            print(f"[OILiveDashboard] Skipped this cycle ({_dashboard_consecutive_failures}/"
                                  f"{_DASHBOARD_MAX_CONSECUTIVE_FAILURES}): {e}")

                # Sep 11 2026: SENSEX snapshots into Index Tracker/the
                # Market Banner above (snapshot_all() already looped it
                # in via INDEX_SYMBOLS), but deliberately does NOT run
                # through the loop below -- that generates live
                # tradeable option calls, Shadow Mode entries, and
                # Bias-vs-OI-Signal agreement logging, none of which
                # were asked for here and each of which is its own real
                # scope (SENSEX's ATR/strike-selection math hasn't been
                # built or tested). NIFTY/BANKNIFTY only, same as before.
                for name, fyers_symbol in (("NIFTY", "NSE:NIFTY50-INDEX"), ("BANKNIFTY", "NSE:NIFTYBANK-INDEX")):
                    row = (index_rows or {}).get(name)
                    oi = get_last_oi_snapshot(name)
                    if not row or not oi:
                        continue
                    try:
                        atr = _calc_index_atr(name, fyers_symbol)
                        call = index_signal.generate_index_call(name, row.get("Bias"), oi, row.get("Spot"), atr)

                        # Sep 8 2026: SHADOW MODE ONLY -- purely an
                        # observer, called AFTER the real call above is
                        # already decided; see
                        # _evaluate_and_log_index_shadow()'s own
                        # docstring for what's confirmed-available vs
                        # honestly disclosed as unavailable this pass.
                        _evaluate_and_log_index_shadow(
                            name, fyers_symbol, row.get("Bias"), row.get("Spot"), atr, oi, call,
                            price_change_pct=row.get("Change %"), fut_oi_chg_pct=row.get("Fut OI Chg %"),
                            atm_strike=row.get("ATM Strike"),
                        )

                        # Sep 9 2026: real Bias-vs-OI-Signal agreement
                        # tracking -- built directly from a real
                        # disagreement found live in the running app
                        # (Bias Bullish while OI Signal read Short
                        # Buildup across many consecutive snapshots).
                        # Own separate log from shadow mode above --
                        # this compares two already-computed INDEX
                        # reads against each other, not v3.0 vs the
                        # Quality Engine. Purely observational, same
                        # as shadow mode: nothing here feeds back into
                        # row/call/Bias itself.
                        try:
                            from .index_agreement_logger import log_agreement_state
                            log_agreement_state(name, row.get("Bias"), row.get("Change %"), row.get("Fut OI Chg %"), row.get("Spot"))
                        except Exception as e:
                            print(f"[IndexAgreementLog] {name} logging failed: {e}")

                        # Outcome check only when a call is actually locked
                        # and we have its exact option_symbol -- one small
                        # extra quote call per active index call, not per
                        # cycle regardless (matches the "only fetch what's
                        # actually needed" principle already used
                        # throughout this project).
                        if call and call.get("option_symbol") and is_authenticated():
                            resp = get_quotes([call["option_symbol"]])
                            if resp and resp.get("s") == "ok":
                                for item in resp.get("d", []):
                                    if item.get("s") == "ok":
                                        ltp = (item.get("v") or {}).get("lp")
                                        if ltp:
                                            index_signal.check_call_outcome(name, ltp)
                    except Exception as e:
                        print(f"[IndexSignal] {name} call generation failed: {e}")

                # Sep 9 2026: once per cycle, not once per index -- same
                # cadence pattern shadow_logger.check_shadow_outcomes()
                # already uses. Silently no-ops if nothing's open to
                # check (no episode logged yet, or everything already
                # resolved to EOD).
                try:
                    from .index_agreement_logger import check_agreement_outcomes
                    check_agreement_outcomes(get_quotes)
                except Exception as e:
                    print(f"[IndexAgreementLog] Failed to check outcomes: {e}")
            # Sep 18 2026: commented out, not deleted -- per explicit
            # request to remove the Commodities tab entirely while
            # keeping the banner's three cards. This call was the
            # actual source of the large majority of MCX Depth/Option
            # chain calls confirmed in this project's own logs (all 6
            # commodity bases -- CRUDEOIL, CRUDEOILM, GOLD, GOLDM,
            # SILVER, SILVERM -- each getting a full get_option_
            # analytics() + get_market_depth() pair every cycle). The
            # banner now reads CommodityQuoteView instead (a single,
            # much lighter get_quotes() call, only for the 3 bases it
            # actually displays), so this heavier pipeline is no longer
            # needed by anything. Re-enable if the Commodities tab (or
            # anything else needing full commodity OI/option data)
            # comes back.
            # snapshot_all_commodities()
            mcx_open = is_mcx_hours()
            if nse_open or mcx_open:
                time.sleep(60)
            else:
                # Same fast-check/slow-log split as _background_worker()
                # above -- checking costs nothing, only the log line needs
                # throttling. In practice MCX opens at 9 AM, before NSE's
                # 9:15, so this loop is normally already on the fast 60s
                # cadence well before NSE opens -- this only matters for
                # the narrower case of a restart happening before EITHER
                # market has opened yet (e.g. very early morning).
                now = time.time()
                if now - last_closed_log >= 300:
                    print(f"[{datetime.now()}] NSE and MCX both closed -- waiting.")
                    last_closed_log = now
                time.sleep(20)
        except Exception as e:
            print(f"[{datetime.now()}] Index snapshot worker error: {e}")
            time.sleep(60)

_index_snapshot_thread = threading.Thread(target=_index_snapshot_worker, daemon=True)
if not _IS_RELOADER_WATCHER_PROCESS:
    _index_snapshot_thread.start()


def _news_alert_worker():
    """
    Separate loop checking for new F&O news and sending any to Telegram
    via news.send_new_news_alerts(). Deliberately NOT gated by NSE or
    MCX market hours -- news itself (and the real-world events it
    reports on) isn't restricted to trading hours the way live quotes
    are, so this keeps checking around the clock. Runs on a 5-min
    cadence, matching news.py's own RSS cache TTL -- checking more
    often than that wouldn't find anything newer anyway.
    """
    from .news import send_new_news_alerts
    while True:
        try:
            sent = send_new_news_alerts(FNO_STOCKS)
            if sent:
                print(f"[{datetime.now()}] Sent {sent} new news alert(s) to Telegram.")
        except Exception as e:
            print(f"[{datetime.now()}] News alert worker error: {e}")
        time.sleep(300)

_news_alert_thread = threading.Thread(target=_news_alert_worker, daemon=True)
# Sep 4 2026: NOT started, per direct request -- removing the News
# tab from the frontend didn't stop these, since this thread never
# checked any UI state to begin with; it just runs on its own clock
# regardless. Commenting out the one line that starts it (rather than
# deleting the function) keeps this a one-line toggle if news alerts
# are ever wanted back, instead of lost work.
# _news_alert_thread.start()


def _daily_backtest_worker():
    """
    Aug 27 2026: runs the full backtest checklist (backfill -> stock
    P&L backtest -> NIFTY positional -> BANKNIFTY positional)
    automatically, TWICE a day -- once shortly after market close
    (catches the day's just-finished signals) and once again early the
    next morning (catches anything that only fully resolved overnight,
    and re-confirms nothing was missed before the new trading day
    starts). Same daemon-thread pattern as the 3 workers above -- no
    Celery/Redis needed here either. See daily_backtest.py for the
    actual checklist logic.

    Uses a per-slot 'last run date' check so each of the two daily
    windows only fires once, even though this loop checks the clock
    frequently -- checking is free; the actual cycle is not (real
    Fyers history calls per unresolved row, real PDF generation).
    Mon-Fri only, matching market_hours.py's own weekend assumption.
    """
    CLOSE_RUN_HOUR, CLOSE_RUN_MINUTE = 16, 0     # ~20min after CAS/derivatives close (3:40 PM)
    MORNING_RUN_HOUR, MORNING_RUN_MINUTE = 8, 0  # well before 9:00 AM pre-open

    last_close_run_date = None
    last_morning_run_date = None

    while True:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            is_weekday = now.weekday() < 5

            if is_weekday and now.hour == CLOSE_RUN_HOUR and now.minute >= CLOSE_RUN_MINUTE and last_close_run_date != today_str:
                last_close_run_date = today_str
                print(f"[{now}] Daily backtest: running scheduled close-time cycle.")
                from .daily_backtest import run_daily_backtest_cycle
                run_daily_backtest_cycle(trigger="scheduled-close", backfill_days=7)

            if is_weekday and now.hour == MORNING_RUN_HOUR and now.minute >= MORNING_RUN_MINUTE and last_morning_run_date != today_str:
                last_morning_run_date = today_str
                print(f"[{now}] Daily backtest: running scheduled morning cycle.")
                from .daily_backtest import run_daily_backtest_cycle
                run_daily_backtest_cycle(trigger="scheduled-morning", backfill_days=7)

            time.sleep(60)
        except Exception as e:
            print(f"[{datetime.now()}] Daily backtest worker error: {e}")
            time.sleep(60)

_daily_backtest_thread = threading.Thread(target=_daily_backtest_worker, daemon=True)
if not _IS_RELOADER_WATCHER_PROCESS:
    _daily_backtest_thread.start()


_eod_scan_lock = threading.Lock()
_eod_scan_in_progress = False
_eod_scan_last_result = None  # {"universe": int, "with_data": int, "watchlist_len": int, "stopped_early": bool, "finished_at": iso string} -- last completed run, either trigger source


def _run_eod_scan_now(trigger_label):
    """
    Sep 2 2026: the actual scan-and-rank work, extracted so BOTH the
    scheduled worker below AND the manual trigger endpoint call the
    EXACT same code path -- one real implementation, not two that
    could drift apart. Lock-protected so a manual click can never
    overlap a scheduled run (or another manual click) -- concurrent
    scans would race on the same output files and double up real
    Fyers load for no reason. Returns True if it actually ran, False
    if a scan was already in progress and this call was skipped.
    """
    global _eod_scan_in_progress, _eod_scan_last_result
    with _eod_scan_lock:
        if _eod_scan_in_progress:
            return False
        _eod_scan_in_progress = True

    try:
        print(f"[{datetime.now()}] EOD scan ({trigger_label}): starting.")
        from .fyers_client import get_quotes, get_history
        from .eod_scanner import run as run_eod_scan
        from .next_day_ranking import build_watchlist

        raw_data, stopped_early = run_eod_scan(get_quotes, get_history)
        if stopped_early:
            print(f"[{datetime.now()}] EOD scan ({trigger_label}): stopped early on a real rate-limit hit -- "
                  f"whatever was scanned is saved; ranking runs on that partial set, not blocked.")

        watchlist, universe, with_data = build_watchlist(sectors_map=SECTORS, raw_data=raw_data)
        print(f"[{datetime.now()}] EOD scan ({trigger_label}): done. Universe {universe}, "
              f"{with_data} with enough data, {len(watchlist)} ranked.")
        _eod_scan_last_result = {
            "universe": universe, "with_data": with_data, "watchlist_len": len(watchlist),
            "stopped_early": stopped_early, "trigger": trigger_label,
            "finished_at": datetime.now().isoformat(),
        }
        return True
    finally:
        with _eod_scan_lock:
            _eod_scan_in_progress = False


# Sep 2 2026: automatic scheduled scanning removed per direct request
# -- manual trigger only now, via EODScanTriggerView's POST endpoint.
# _run_eod_scan_now() (the actual scan-and-rank logic, and its
# overlap-prevention lock) is untouched and still does all the real
# work -- this only removes the background clock that used to call it
# on its own. Nothing else about the scan changed.

# ============================================================
# VIEWS — READ FROM CACHE ONLY, NO BLOCKING
# ============================================================

class MarketSummaryOldView(APIView):
    def get(self, request):
        with _cache_lock:
            nifty = _index_cache.get("nifty50")
            bank = _index_cache.get("banknifty")
            vix = _index_cache.get("india_vix")
            sensex = _index_cache.get("sensex")
            pcr = _index_cache.get("pcr", {"value": None, "sentiment": "N/A"})
            warming = len(_stock_cache) == 0
            breadth = _compute_breadth(list(_stock_cache.values()))
            sectors = _compute_sector_performance(list(_stock_cache.values()))
            sentiment = _compute_market_sentiment(list(_stock_cache.values()))
            movers = _compute_market_movers(list(_stock_cache.values()))

        # MarketBanner (this endpoint) is the one thing mounted on every
        # tab, polling every 30s regardless of which tab is active --
        # unlike the sniper-only endpoint, which only checks outcomes
        # while specifically on the Live Signals tab. Piggybacking the
        # same check here means SL/Target hits get caught as long as the
        # app is open at all, not just while that one tab is in view.
        # check_outcomes() is safe to call repeatedly (see excel_logger.py
        # module docstring) so there's no conflict with the existing call.
        try:
            if is_authenticated():
                from .excel_logger import check_outcomes
                check_outcomes(get_quotes)
        except Exception as e:
            print(f"[ExcelLog] outcome check (market-summary) failed: {e}")

        return Response({
            "nifty50": nifty or {"price": 0, "change": 0, "change_percent": 0},
            "banknifty": bank or {"price": 0, "change": 0, "change_percent": 0},
            "india_vix": vix or {"value": 0, "change": 0, "change_percent": 0},
            "sensex": sensex or {"price": 0, "change": 0, "change_percent": 0},
            "pcr": pcr,
            "breadth": breadth,
            "sectors": sectors,
            "sentiment": sentiment,
            "movers": movers,
            "warming_up": warming,
            "timestamp": datetime.now().isoformat()
        })


class FoStockListOldView(APIView):
    def get(self, request):
        with _cache_lock:
            stocks = list(_stock_cache.values())
        
        # Fix: Replace NaN/Inf with None so JSON works
        for stock in stocks:
            for key, value in stock.items():
                if isinstance(value, float):
                    if math.isnan(value) or math.isinf(value):
                        stock[key] = None
        
        return Response({"stocks": stocks, "count": len(stocks)})


class MarketDataView(APIView):
    def get(self, request):
        with _cache_lock:
            stocks = list(_stock_cache.values())
        sorted_stocks = sorted(stocks, key=lambda x: x.get('change_percent', 0), reverse=True)
        
        with _cache_lock:
            nifty = _index_cache.get("nifty50")
            bank = _index_cache.get("banknifty")
        
        return Response({
            "indices": [
                nifty or {"name": "NIFTY 50", "price": 0, "change": 0, "change_percent": 0},
                bank or {"name": "BANKNIFTY", "price": 0, "change": 0, "change_percent": 0},
                {"name": "FINNIFTY", "price": 0, "change": 0, "change_percent": 0},
            ],
            "top_gainers": sorted_stocks[:5],
            "top_losers": sorted_stocks[-5:][::-1],
        })


class SignalsView(APIView):
    def get(self, request):
        with _cache_lock:
            signals = list(_signal_cache)
        return Response({"signals": signals, "count": len(signals)})


class SniperOnlyView(APIView):
    def get(self, request):
        with _cache_lock:
            signals = list(_signal_cache)
        return Response({"signals": signals, "count": len(signals)})


class SectorStocksView(APIView):
    """
    Aug 30 2026: powers the Market Heatmap's sector click-through.
    Price/change comes straight from _stock_cache (already fetched
    every scan cycle, free). OI buildup is DELIBERATELY a fresh live
    fetch per stock at request time, not reused from _signal_cache/
    techs -- those only cover the ~15-30 stocks that already clear
    today's technical filter each cycle (kept small on purpose, to
    bound Fyers call volume), and most of a given sector's stocks
    won't be in that set on a given day. Reusing it would show '--'
    for most stocks in most sectors, which defeats the point of a
    per-sector breakdown. Chosen directly over the faster option: a
    few seconds' wait and up to one option-chain call per stock in
    the clicked sector (sectors here run roughly 1-20 stocks), only
    on click, not added to the main scan cycle's budget.
    Never fabricates: not authenticated, or an individual fetch
    fails, that stock's oi_buildup/pcr come back None -- frontend
    shows '--', same rule as everywhere else in this codebase.
    """
    def get(self, request, sector):
        with _cache_lock:
            stock_list = [s for s in _stock_cache.values() if s.get('sector') == sector]

        authed = is_authenticated()
        results = []
        for s in stock_list:
            sym = s.get('symbol')
            oi_buildup, pcr = None, None
            if authed:
                try:
                    oi = get_option_analytics(f"NSE:{sym}-EQ", strikecount=10)
                    if oi:
                        oi_buildup = oi.get('oi_buildup')
                        pcr = oi.get('pcr')
                except Exception as e:
                    print(f"[SectorStocks] {sym} OI fetch failed: {e}")
            results.append({
                "symbol": sym,
                "price": s.get('price'),
                "change_percent": s.get('change_percent'),
                "oi_buildup": oi_buildup,
                "pcr": pcr,
            })

        results.sort(key=lambda r: r.get('change_percent') or 0, reverse=True)
        return Response({"sector": sector, "stocks": results, "authenticated": authed})


class NoTradeLogView(APIView):
    """
    Aug 31 2026: P0-6 from the UI Corrections checklist -- exposes
    THIS cycle's rejected candidates with real reasons (see the
    no_trade_log entries added throughout the signal-building loop).
    Not a history -- like _signal_cache, this is overwritten fresh
    every scan cycle, so it reflects "why did X get rejected just
    now", not a persisted log across the day.
    """
    def get(self, request):
        with _cache_lock:
            rejected = list(_no_trade_cache)
        return Response({"rejected": rejected, "count": len(rejected)})


class ShadowSignalsView(APIView):
    """
    Sep 8 2026: read-only view onto shadow_logger.py's SHADOW MODE log
    -- v3.0's real decision vs quality_engine's independent assessment,
    side by side, for every candidate _build_all() evaluated today
    (see the _evaluate_and_log_shadow() call sites throughout the
    signal-building loop). UNLIKE NoTradeLogView above, this genuinely
    IS a persisted history across the whole day, not just this cycle --
    reads straight from today's real xlsx (shadow_logger's own source
    of truth), so it stays correct across a server restart too.

    Purely observational: nothing this view exposes ever fed back into
    v3.0's own signal selection, and calling this endpoint has no side
    effects on the live scan.
    """
    def get(self, request):
        from .shadow_logger import get_today_shadow_signals
        rows = get_today_shadow_signals()
        agree = sum(1 for r in rows if r.get("Agreement") == "AGREE")
        v3_only = sum(1 for r in rows if r.get("Agreement") == "V3_ONLY")
        quality_only = sum(1 for r in rows if r.get("Agreement") == "QUALITY_ONLY")
        return Response({
            "candidates": rows, "count": len(rows),
            "agreement_summary": {"AGREE": agree, "V3_ONLY": v3_only, "QUALITY_ONLY": quality_only},
        })


class ShadowPerformanceView(APIView):
    """
    Sep 8 2026: spec sections 20/21, "Real Outcome Learning" / "Future
    Performance Analysis" -- THE actual question shadow mode exists to
    answer: does Agreement (AGREE/V3_ONLY/QUALITY_ONLY) correlate with
    better REAL outcomes? Reads across EVERY day's accumulated shadow
    log (get_all_shadow_signals(), not just today), and runs
    compute_shadow_performance() -- sample-size-gated (min 20 EOD-
    resolved candidates per bucket, matching this project's own
    established backtest-floor discipline), never a hit-rate/return
    percentage shown below that floor.

    On a fresh install with little/no accumulated history, every
    bucket will honestly read "Insufficient data (N=X)" -- that's
    correct, not a bug; the whole design intent of shadow mode is that
    this view becomes meaningful only once real data has accumulated.
    """
    def get(self, request):
        from .shadow_logger import get_all_shadow_signals, compute_shadow_performance
        rows = get_all_shadow_signals()
        performance = compute_shadow_performance(rows)
        return Response(performance)


class IndexAgreementLogView(APIView):
    """
    Sep 9 2026: read-only view onto index_agreement_logger.py's real
    Bias-vs-OI-Signal episode log for NIFTY/BANKNIFTY -- built directly
    from a real disagreement found live in the running app (Bias
    Bullish while OI Signal read Short Buildup across many consecutive
    snapshots, 09 Sep 2026). Purely observational, same as shadow mode:
    nothing this view exposes ever fed back into Bias/OI Signal/the
    index call itself.
    """
    def get(self, request):
        from .index_agreement_logger import get_today_agreement_log
        rows = get_today_agreement_log()
        agree = sum(1 for r in rows if r.get("Agreement") == "AGREE")
        disagree = sum(1 for r in rows if r.get("Agreement") == "DISAGREE")
        neutral = sum(1 for r in rows if r.get("Agreement") == "NEUTRAL_BIAS")
        return Response({
            "episodes": rows, "count": len(rows),
            "agreement_summary": {"AGREE": agree, "DISAGREE": disagree, "NEUTRAL_BIAS": neutral},
        })


class NextTradingSessionView(APIView):
    """
    Sep 12 2026: holiday-aware "when does trading next resume", for the
    header's Market Status display -- see get_next_trading_session()'s
    own docstring in market_hours.py for the real 2026 holiday
    calendars this is built on and their sourcing/limitations.

    Deliberately does NOT touch is_market_hours() or anything the live
    scanner's own on/off gate depends on -- this is purely informational,
    same principle as every other read-only status endpoint in this file.

    GET /api/next-trading-session/<NSE|BSE|MCX>/"""
    def get(self, request, market):
        from .market_hours import get_next_trading_session
        session = get_next_trading_session(market)
        return Response({"market": market.upper(), "next_session": session})


class DataHealthView(APIView):
    """
    Aug 31 2026: Section 18 from the UI Corrections checklist -- Data
    Health Center. Aggregates state that already existed scattered
    across this file (is_authenticated(), _last_fetch, is_market_hours(),
    FNO_STOCKS vs _stock_cache) into one honest status object. Adds no
    new tracking -- e.g. no real per-feed latency measurement exists
    in this codebase, so that field is left out rather than faked.
    missing_symbols is a genuine list (which of the real 208 F&O
    universe aren't in the current cache right now), not an estimate.
    market_session is deliberately OPEN/CLOSED only (2 states) -- this
    codebase doesn't have a confirmed PRE-OPEN/POST-CLOSE distinction
    available, so the 4-state version the checklist describes isn't
    built here rather than guessed at.
    The LIVE/DEGRADED/DOWN staleness cutoff (400s) is a reasonable
    heuristic (~2x this project's own documented ~2.5-3min real scan
    cycle), not a "historically validated" threshold -- flagged as
    such, easy to adjust if it proves too tight or too loose in
    practice.
    """
    def get(self, request):
        from .market_hours import is_market_hours

        with _cache_lock:
            cached_symbols = set(_stock_cache.keys())
            stock_count = len(_stock_cache)
            signal_count = len(_signal_cache)
            last_fetch = _last_fetch

        authed = is_authenticated()
        staleness_seconds = round(time.time() - last_fetch, 1) if last_fetch else None
        market_open = is_market_hours()
        missing_symbols = [s for s in FNO_STOCKS if s not in cached_symbols]

        if not authed:
            status = "DOWN"
        elif staleness_seconds is not None and staleness_seconds > 400:
            status = "DEGRADED"
        else:
            status = "LIVE"

        return Response({
            "fyers_status": status,
            "authenticated": authed,
            "source": "Fyers",
            "market_session": "OPEN" if market_open else "CLOSED",
            "last_update": datetime.fromtimestamp(last_fetch).isoformat() if last_fetch else None,
            "staleness_seconds": staleness_seconds,
            "stock_universe_total": len(FNO_STOCKS),
            "stock_cache_count": stock_count,
            "missing_symbols": missing_symbols,
            "missing_symbols_count": len(missing_symbols),
            "live_signal_count": signal_count,
        })


class TickerDataView(APIView):
    def get(self, request):
        with _cache_lock:
            stocks = list(_stock_cache.values())
        return Response({"ticker": stocks})


def get_technical_signal(symbol):
    """
    Aug 28 2026: real Bullish/Neutral/Bearish technical read for the
    upcoming Watchlist redesign, based on RSI. Deliberately reuses
    StockDetailView's exact existing pattern (check _stock_cache first
    -- free if this symbol happens to already be cached; fall back to
    _fetch_all_stocks([sym]) for a single fresh quote; then
    _calc_tech(sym, live_quote=q) for the full indicator set including
    TODAY's candle) rather than the _build_all()-populated _tech_cache
    global, which ONLY covers the day's top 30 movers by |change%| --
    a watchlist can contain any of the 208 F&O stocks, most of which
    won't be in that moving top-30 subset on a given day.

    RSI thresholds (>=60 Bullish, <=40 Bearish, else Neutral) sit
    around the same 40-65 "favorable" band this codebase's own signal-
    quality criteria already uses elsewhere (previously shown in the
    UI as "RSI 40-65 | ADX >=25 | Vol >=1.5x") -- not a new, unrelated
    scale invented just for this.

    Returns None if a fresh quote or enough history isn't available --
    never guesses a direction.
    """
    sym = symbol.upper().replace(".NS", "")
    with _cache_lock:
        q = _stock_cache.get(sym)
    if not q:
        fetched = _fetch_all_stocks([sym])
        q = fetched.get(sym)
        if not q:
            return None

    tech = _calc_tech(sym, live_quote=q)
    if not tech or tech.get('rsi') is None:
        return None

    rsi = tech['rsi']
    if rsi >= 60:
        label = 'Bullish'
    elif rsi <= 40:
        label = 'Bearish'
    else:
        label = 'Neutral'
    return {'label': label, 'rsi': rsi, 'adx': tech.get('adx')}


class StockDetailView(APIView):
    def get(self, request, symbol):
        sym = symbol.upper().replace(".NS", "")
        with _cache_lock:
            q = _stock_cache.get(sym)
        if not q:
            fetched = _fetch_all_stocks([sym])
            q = fetched.get(sym)
            if not q:
                return Response({"error": "Symbol not found"}, status=404)
        
        tech = _calc_tech(sym, live_quote=q)
        return Response({
            **q,
            "ohlc": {"open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"]},
            "technicals": tech or {},
            "fundamentals": {}
        })


class NewsView(APIView):
    """
    Real F&O-relevant news, pulled from ET's public RSS feeds (Markets,
    Stocks, Company) and filtered to headlines mentioning an F&O ticker
    directly. Previously returned 5 hardcoded headlines that never
    changed regardless of actual market conditions -- same pattern as
    the old fake PCR. Known limitation: only catches headlines that
    mention the bare ticker, not full company names -- see news.py.

    Aug 28 2026: added "broad_news" -- the F&O-ticker filter above
    means genuinely relevant macro/global news (bond yields, Fed
    decisions, global market moves) was being silently dropped
    whenever it didn't happen to name a specific stock, confirmed live
    ("not getting any news related to global tension, only F&O
    stocks"). get_broad_market_news() is the SAME feeds, unfiltered --
    see its own docstring for why it's a separate function rather than
    a change to get_fno_news() itself.
    """
    def get(self, request):
        from .news import get_fno_news, get_broad_market_news
        news = get_fno_news(FNO_STOCKS, limit=20)
        broad_news = get_broad_market_news(limit=15)
        return Response({"news": news, "broad_news": broad_news})


class FundamentalsWatchlistView(APIView):
    """
    Long-term value watchlist: NSE stocks meaningfully below their
    52-week high, ranked by combined fundamentals (P/E, ROE, Debt/
    Equity, Sales growth) via percentile ranking across whatever's been
    collected so far -- see fundamentals/ranking.py for the full method
    and reasoning (including why negative P/E is excluded from ranking
    rather than treated as "cheapest," caught from a real bad result).

    Reads from fundamentals_data.json, built by a SEPARATE background
    process (fundamentals/runner.py) -- not live-fetched here, since a
    full pass across the whole NSE list takes hours and fundamentals
    don't change that often anyway. This view is just reading whatever
    that process has saved so far, which may be a partial, still-
    growing list while the full run is in progress.

    GET /api/fundamentals-watchlist/
    Optional query params: ?min_discount=-10&limit=50
    """
    def get(self, request):
        from fundamentals.ranking import build_watchlist
        try:
            min_discount = float(request.GET.get("min_discount", -10))
        except (TypeError, ValueError):
            min_discount = -10
        try:
            limit = int(request.GET.get("limit", 50))
        except (TypeError, ValueError):
            limit = 50

        results = build_watchlist(min_discount_pct=min_discount, top_n=limit)
        return Response({"watchlist": results, "count": len(results)})


class FyersStatusView(APIView):
    def get(self, request):
        auth = is_authenticated()
        return Response({
            "authenticated": auth,
            "client_id": CLIENT_ID if auth else None,
            "status": "Connected" if auth else "Disconnected",
            "message": "Fyers API v3 active" if auth else "Please authenticate via /api/fyers/login/"
        })


class FyersDisconnectView(APIView):
    """
    Sep 8 2026: real disconnect -- deletes the saved Fyers token files
    (fyers_access_token.txt, fyers_auth.json) and resets the in-memory
    auth cache immediately, rather than waiting out its own TTL. This
    can't call a real Fyers-side disconnect (fyers-apiv3 exposes no
    such endpoint) -- it disconnects THIS app's saved credentials
    instead, which has the same practical effect: every live call
    fails honestly (is_authenticated() -> False) until re-authenticated.

    No matching "connect" button exists anywhere in this app to pair
    with this -- see FyersStatusView above and _FyersCompat.get_auth_url()
    in fyers_client.py: login has only ever been the manual
    get_fyers_token.py script. Reconnecting after this still means
    running that script again, same as today.
    POST /api/fyers-disconnect/
    """
    def post(self, request):
        from . import fyers_client
        removed = []
        for path in (fyers_client.TOKEN_PATH, fyers_client.TOKEN_JSON_PATH):
            try:
                if os.path.exists(path):
                    os.remove(path)
                    removed.append(os.path.basename(path))
            except OSError as e:
                return Response({"error": f"Could not remove {os.path.basename(path)}: {e}"}, status=500)
        fyers_client._auth_cache["value"] = False
        fyers_client._auth_cache["checked_at"] = 0.0
        return Response({"disconnected": True, "removed_files": removed})


class SignalExcelExportView(APIView):
    """Download today's auto-logged signal Excel file (entry time, entry/
    SL/targets, exit time for each signal that's dropped out of the
    active list). One file per trading day."""
    def get(self, request):
        from django.http import FileResponse, JsonResponse
        from .excel_logger import get_today_log_path
        path = get_today_log_path()
        if not path:
            return JsonResponse({"error": "No signals logged yet today."}, status=404)
        filename = os.path.basename(path)
        return FileResponse(open(path, 'rb'), as_attachment=True, filename=filename)


class SignalWatchlistCsvView(APIView):
    """Today's active qualifying signals as a Fyers-Watchlist-importable
    CSV. There is no Fyers API endpoint to push directly into a Watchlist
    (checked Aug 20 2026 -- watchlist write access isn't part of
    fyers-apiv3's exposed surface, only manual add/CSV-import via Fyers
    Web/App). Fyers Web DOES support Watchlist -> Import from a CSV with
    a single 'Symbol' column, so this is the closest real automation:
    generate the file in that exact importable shape, using the real
    Fyers option_symbol string already attached to each signal (the same
    one Fyers' own option-chain response returned -- not reconstructed),
    so the daily manual step becomes 'download, then Import in Fyers
    Web' instead of typing each strike by hand.
    GET /api/signals/watchlist-csv/"""
    def get(self, request):
        from django.http import HttpResponse, JsonResponse
        import csv
        import io

        with _cache_lock:
            signals = list(_signal_cache)

        seen = set()
        rows = []
        for s in signals:
            sym = s.get("option_symbol")
            if sym and sym not in seen:
                rows.append(sym)
                seen.add(sym)

        if not rows:
            return JsonResponse({"error": "No active signals with a confirmed option symbol right now."}, status=404)

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Symbol"])
        for sym in rows:
            writer.writerow([sym])

        response = HttpResponse(buffer.getvalue(), content_type="text/csv")
        filename = f"sniper_watchlist_{datetime.now().strftime('%Y-%m-%d_%H%M')}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class SignalExportDatesView(APIView):
    """Every date that has a signal log available, newest first --
    powers the date picker next to the download button so past days
    are reachable, not just today. GET /api/signals/export/dates/"""
    def get(self, request):
        from .excel_logger import list_available_dates
        return Response({"dates": list_available_dates()})


class SignalExcelExportByDateView(APIView):
    """Same file the regular export gives you for today, but for any
    past date that has one. GET /api/signals/export/<YYYY-MM-DD>/"""
    def get(self, request, date_str):
        from django.http import FileResponse, JsonResponse
        from .excel_logger import get_log_path_for_date
        path = get_log_path_for_date(date_str)
        if not path:
            return JsonResponse({"error": f"No signals logged for {date_str}."}, status=404)
        filename = os.path.basename(path)
        return FileResponse(open(path, 'rb'), as_attachment=True, filename=filename)


def _instrument_expiry_info(name):
    """
    Sep 12 2026: real, per-instrument nearest-expiry date and whether
    that's TODAY -- for a banner's "EXPIRY TODAY" line. Reads
    get_last_oi_snapshot(name), the same already-populated, in-memory
    cache oi_live_dashboard.py already reads from -- get_option_
    analytics()'s own already-computed expiry_date (real expiryData
    from Fyers' option chain response), added when that chain was
    fetched this cycle. Nothing new fetched here.

    Deliberately does NOT touch index_tracker.py's Excel-facing
    Snapshots row/COLUMNS -- this is an additional field on the API
    response only, so the Excel workbook's own layout is unaffected.

    Each instrument's own real fetched expiry, never one hardcoded
    weekday for everything -- NIFTY/BANKNIFTY/SENSEX each get whatever
    Fyers' own expiryData reports for THAT chain (confirmed different:
    SENSEX's own weekly cycle isn't NIFTY/BANKNIFTY's), and CRUDEOIL/
    GOLD/SILVER each get their own MCX contract's real expiry.

    Returns {"expiry_date": iso_date_str_or_None, "is_expiry_today": bool}.
    is_expiry_today is only True when a REAL expiry_date was found AND
    it matches today's real date -- a missing snapshot or missing
    expiry_date both read as False, same "unknown is never fabricated
    into a positive" rule as everywhere else in this project.
    """
    from .index_tracker import get_last_oi_snapshot
    snap = get_last_oi_snapshot(name)
    expiry_date = (snap or {}).get("expiry_date")
    is_today = bool(expiry_date and expiry_date == datetime.now().date().isoformat())
    return {"expiry_date": expiry_date, "is_expiry_today": is_today}


class MarketBreadthView(APIView):
    """
    Sep 18 2026: real market-breadth aggregation for the Dashboard
    rebuild, over _breadth_tech_cache (all 208 F&O stocks, populated by
    _breadth_indicators_worker -- see that worker's own comment for why
    this had to be a new, separate, full-universe cache rather than
    reusing _build_all()'s top-~30-movers-only _tech_cache computation).

    Every count below states the denominator it was computed over
    (count_with_data) rather than assuming full 208-stock coverage --
    a stock missing from this tile's math (thin history, a transient
    Fyers miss this cycle) is excluded from both numerator and
    denominator, never silently treated as a zero or an average. Same
    "an input that did not load stays absent, not a fabricated
    neutral" principle the reference dashboard itself states in its
    own disclaimer line.

    Definitions used, stated plainly since none of these are the only
    possible choice:
    - advancing/declining/flat: change_percent > 0 / < 0 / == 0.
    - trend_participation: price > ema200, ONLY over stocks with a
      real ema200 (>=200 days of history) -- genuinely a partial
      universe, reported as such via count_with_data.
    - market_momentum: mean RSI(14) across stocks with valid RSI;
      classified oversold <40, mid-range 40-60, overbought >60 --
      standard RSI convention, not this project's invention.
    - volume_activity: elevated = volume >= 2x the 20-day average
      volume (matches "2X VOL" in the reference literally); up/down
      split is which of those elevated-volume stocks are also up vs
      down today.
    - ema50_breadth / vwap_breadth: price > ema50 / price > vwap.
    - sector_breadth: per SECTORS mapping (already existed, used
      elsewhere in this file), count of advancing vs declining names.

    Deliberately NOT included: 52-week high/low breadth. That needs
    roughly a year of daily history per symbol; _calc_tech's own history
    fetch is 100 days today. Rather than fake this tile from data that
    doesn't exist, it's left out of this response entirely -- flagged
    here, not silently omitted, in has_52w_data: false so the frontend
    can show its own honest "not yet available" state instead of a
    default emerging as a fake number.
    GET /api/market-breadth/
    """
    def get(self, request):
        with _cache_lock:
            quotes = dict(_stock_cache)
        with _breadth_cache_lock:
            techs = dict(_breadth_tech_cache)

        advancing = declining = flat = 0
        bucket_edges = [-5, -2, 0, 2, 5]
        bucket_labels = ["<=-5%", "(-5,-2]", "(-2,0)", "[0,2)", "[2,5)", ">=5%"]
        buckets = {label: 0 for label in bucket_labels}

        def bucket_for(pct):
            if pct <= bucket_edges[0]: return bucket_labels[0]
            if pct <= bucket_edges[1]: return bucket_labels[1]
            if pct < bucket_edges[2]: return bucket_labels[2]
            if pct < bucket_edges[3]: return bucket_labels[3]
            if pct < bucket_edges[4]: return bucket_labels[4]
            return bucket_labels[5]

        ema200_above = ema200_total = 0
        rsi_values = []
        elevated_up = elevated_down = elevated_total = 0
        ema50_above = ema50_total = 0
        vwap_above = vwap_total = 0
        sector_breadth = {}

        for sym, q in quotes.items():
            pct = q.get('change_percent')
            price = q.get('price')
            if pct is not None:
                if pct > 0: advancing += 1
                elif pct < 0: declining += 1
                else: flat += 1
                buckets[bucket_for(pct)] += 1

                sector = q.get('sector', 'Unknown')
                sb = sector_breadth.setdefault(sector, {'up': 0, 'down': 0, 'total': 0})
                sb['total'] += 1
                if pct > 0: sb['up'] += 1
                elif pct < 0: sb['down'] += 1

            tech = techs.get(sym)
            if not tech or price is None:
                continue

            if tech.get('ema200') is not None:
                ema200_total += 1
                if price > tech['ema200']: ema200_above += 1

            if tech.get('rsi') is not None:
                rsi_values.append(tech['rsi'])

            vol_avg = tech.get('volume_avg')
            volume = q.get('volume')
            if vol_avg and volume is not None:
                elevated_total += 1
                if volume >= 2 * vol_avg:
                    if pct is not None and pct > 0: elevated_up += 1
                    elif pct is not None and pct < 0: elevated_down += 1

            if tech.get('ema50') is not None:
                ema50_total += 1
                if price > tech['ema50']: ema50_above += 1

            if tech.get('vwap') is not None:
                vwap_total += 1
                if price > tech['vwap']: vwap_above += 1

        total_directional = advancing + declining
        ratio = round(advancing / declining, 2) if declining else None
        mean_rsi = round(sum(rsi_values) / len(rsi_values), 1) if rsi_values else None
        momentum_class = (
            None if mean_rsi is None else
            'oversold' if mean_rsi < 40 else
            'overbought' if mean_rsi > 60 else
            'mid-range'
        )

        elevated_count = 0
        for sym, q in quotes.items():
            tech = techs.get(sym)
            if not tech: continue
            vol_avg = tech.get('volume_avg')
            volume = q.get('volume')
            if vol_avg and volume is not None and volume >= 2 * vol_avg:
                elevated_count += 1

        return Response({
            "universe_size": len(quotes),
            "advance_decline": {
                "advancing": advancing, "declining": declining, "flat": flat,
                "ratio": ratio, "net": advancing - declining,
                "buckets": [{"label": l, "count": buckets[l]} for l in bucket_labels],
                "count_with_data": total_directional + flat,
            },
            "trend_participation": {
                "pct_above_ema200": round(100 * ema200_above / ema200_total, 1) if ema200_total else None,
                "above_count": ema200_above, "count_with_data": ema200_total,
                "partial_universe": ema200_total < len(quotes),
            },
            "market_momentum": {
                "mean_rsi": mean_rsi, "classification": momentum_class,
                "count_with_data": len(rsi_values),
            },
            "volume_activity": {
                "pct_elevated": round(100 * elevated_count / elevated_total, 1) if elevated_total else None,
                "elevated_up": elevated_up, "elevated_down": elevated_down,
                "elevated_count": elevated_count, "count_with_data": elevated_total,
            },
            "ema50_breadth": {
                "pct_above": round(100 * ema50_above / ema50_total, 1) if ema50_total else None,
                "above_count": ema50_above, "below_count": ema50_total - ema50_above,
                "count_with_data": ema50_total,
            },
            "vwap_breadth": {
                "pct_above": round(100 * vwap_above / vwap_total, 1) if vwap_total else None,
                "above_count": vwap_above, "below_count": vwap_total - vwap_above,
                "count_with_data": vwap_total,
            },
            "sector_breadth": sector_breadth,
            "has_52w_data": False,
        })


class IndexTrackerView(APIView):
    """Intraday OI snapshot history for one index/commodity, most recent
    first -- today's by default, or a specific past date via ?date=.
    GET /api/index-tracker/<NIFTY|BANKNIFTY|CRUDEOIL|CRUDEOILM>/?date=2026-08-12"""
    def get(self, request, index_name):
        from .index_tracker import get_today_snapshots, get_snapshots_for_date, TRACKABLE_NAMES
        name = index_name.upper()
        if name not in TRACKABLE_NAMES:
            return Response({"error": f"index_name must be one of {TRACKABLE_NAMES}"}, status=400)
        date_str = request.GET.get("date")
        rows = get_snapshots_for_date(name, date_str) if date_str else get_today_snapshots(name)
        # Sep 12 2026: real per-instrument expiry, for the banner's
        # PRICE/INDICATIVE PRICE + EXPIRY TODAY line -- see
        # _instrument_expiry_info()'s own docstring above.
        expiry_info = _instrument_expiry_info(name)
        return Response(clean_json({"index": name, "date": date_str, "snapshots": rows, **expiry_info}))


class TrendMomentumView(APIView):
    """
    Sep 2 2026: pure price-action "Trend & Momentum" card (RSI/SMA/ATR/
    pivot S-R/volatility/Technical Bias) -- genuine second opinion
    alongside the options-derived Bias IndexTrackerView above already
    serves, not a replacement. See get_trend_momentum_card()'s own
    docstring in index_tracker.py for the full reasoning.
    GET /api/trend-momentum/<NIFTY|BANKNIFTY>/"""
    def get(self, request, index_name):
        from .index_tracker import get_trend_momentum_card, INDEX_SYMBOLS
        name = index_name.upper()
        if name not in INDEX_SYMBOLS:
            return Response({"error": f"index_name must be one of {list(INDEX_SYMBOLS)}"}, status=400)
        # Sep 11 2026: was a binary ternary ("nifty50" if NIFTY else
        # "banknifty") that silently mapped anything else -- SENSEX
        # included, once it joined INDEX_SYMBOLS -- to BANKNIFTY's
        # cached price. get_trend_momentum_card() itself is already
        # name-generic (goes through _fetch_daily_history() -> Fyers
        # history API, nothing NSE/BSE-specific), so this endpoint now
        # works correctly for SENSEX too if something calls it -- this
        # fix is only about not mislabeling the live spot, not a claim
        # that SENSEX is wired into the Dashboard's Trend & Momentum
        # UI (it isn't, wasn't asked for, and Dashboard.jsx wasn't
        # part of this change).
        _CACHE_KEY = {"NIFTY": "nifty50", "BANKNIFTY": "banknifty", "SENSEX": "sensex"}
        with _cache_lock:
            live_snapshot = _index_cache.get(_CACHE_KEY.get(name))
        current_spot = (live_snapshot or {}).get("price")
        card = get_trend_momentum_card(name, current_spot=current_spot)
        if card is None:
            return Response({"error": "Not enough real daily history yet to compute this -- try again shortly."}, status=503)
        return Response(clean_json(card))


class NextDayWatchlistView(APIView):
    """
    Sep 2 2026: the full-NSE-universe Next Day Watchlist -- Trend
    Status/Volume Status/Sector Strength/Score, ranked, built by the
    automatic post-close scan (_eod_scan_worker above). Purely reads
    next_day_ranking.py's already-written output file; this view does
    NOT trigger a scan itself, same "serve what's there, don't fetch
    live on request" principle as every other read-only reporting
    view in this file.
    GET /api/next-day-watchlist/"""
    def get(self, request):
        import json
        from .next_day_ranking import RANKED_OUTPUT_FILE
        if not os.path.exists(RANKED_OUTPUT_FILE):
            return Response({
                "error": "No scan has completed yet. The automatic scan runs on weekdays shortly after market close.",
                "universe_scanned": 0, "stocks_with_enough_data": 0, "watchlist": [],
            }, status=200)
        with open(RANKED_OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Response(clean_json(data))


class RiskBudgetSettingsView(APIView):
    """
    Sep 2 2026: read/write the persisted risk-budget-per-trade setting
    -- see compute_qty_with_risk_budget()'s own docstring near the top
    of this file for the full reasoning (a lot-count multiplier on the
    real exchange lot size, never a rupee-derived quantity on its own).
    GET returns the current value (null if never set -- the honest
    default/unchanged-behavior state). POST {"risk_budget_rupees": N}
    sets it; POST {"risk_budget_rupees": null} clears it back to
    unset/default 1-lot behavior.
    """
    def get(self, request):
        return Response({"risk_budget_rupees": get_risk_budget_rupees()})

    def post(self, request):
        import json
        value = request.data.get("risk_budget_rupees")
        if value is not None:
            try:
                value = float(value)
                if value <= 0:
                    return Response({"error": "risk_budget_rupees must be a positive number, or null to clear it"}, status=400)
            except (TypeError, ValueError):
                return Response({"error": "risk_budget_rupees must be a number or null"}, status=400)
        with open(USER_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({"risk_budget_rupees": value}, f)
        return Response({"risk_budget_rupees": value})


class EODScanTriggerView(APIView):
    """
    Sep 2 2026: manual "run it now" for the Next Day Watchlist scan --
    the automatic post-close trigger (_eod_scan_worker) only fires
    once a day and depends on the server actually being up when the
    window arrives; this lets a scan happen on demand instead, any
    time. Runs in a background thread -- a real full-universe scan
    takes many minutes (paced deliberately, see eod_scanner.py), so
    this returns immediately rather than holding the HTTP connection
    open that whole time. Shares _run_eod_scan_now()'s lock with the
    scheduled worker -- calling this while a scan (scheduled or
    manual) is already running is a no-op, not a second overlapping
    scan.
    GET checks status/last result. POST starts a scan if one isn't
    already running.
    """
    def get(self, request):
        from .eod_scanner import get_scan_progress
        return Response({
            "scan_in_progress": _eod_scan_in_progress,
            "last_result": _eod_scan_last_result,
            # Sep 3 2026: real live progress -- was only ever visible in
            # the terminal's own print() lines before. Zeros/None when
            # nothing has run yet this process, which the frontend
            # already treats the same as "no progress to show".
            "progress": get_scan_progress(),
        })

    def post(self, request):
        if _eod_scan_in_progress:
            return Response({"started": False, "reason": "A scan is already in progress."}, status=200)
        thread = threading.Thread(target=_run_eod_scan_now, args=("manual",), daemon=True)
        thread.start()
        return Response({"started": True, "reason": "Scan started -- this typically takes several minutes for the full NSE universe. Check back via GET, or just reopen the Next Day tab shortly."})


class IndexTrackerAvailableDatesView(APIView):
    """Which dates actually have logged snapshot data for one index --
    lets the frontend offer a real, populated date picker rather than
    letting someone guess at a date that has nothing behind it.
    GET /api/index-tracker/<NIFTY|BANKNIFTY|CRUDEOIL|CRUDEOILM>/dates/"""
    def get(self, request, index_name):
        from .index_tracker import list_available_dates, TRACKABLE_NAMES
        name = index_name.upper()
        if name not in TRACKABLE_NAMES:
            return Response({"error": f"index_name must be one of {TRACKABLE_NAMES}"}, status=400)
        return Response({"index": name, "dates": list_available_dates(name)})


class IndexBacktestView(APIView):
    """Day-wise Bias-accuracy backtest for one index or commodity, across
    15/30/60 minute look-ahead horizons -- does the Bias reading actually
    predict where price goes next, broken out per day rather than one
    aggregate number. GET /api/backtest/<NIFTY|BANKNIFTY|CRUDEOIL|CRUDEOILM>/"""
    def get(self, request, index_name):
        from .backtest_index_bias import backtest_by_day
        from .index_tracker import TRACKABLE_NAMES
        name = index_name.upper()
        if name not in TRACKABLE_NAMES:
            return Response({"error": f"index_name must be one of {TRACKABLE_NAMES}"}, status=400)
        horizons = (15, 30, 60)
        by_horizon = {h: backtest_by_day(name, h) for h in horizons}
        return Response(clean_json({"index": name, "horizons": by_horizon}))


class CASAuctionMovesView(APIView):
    """
    Day-by-day price move specifically attributable to the CAS
    auction window (3:15-3:35 PM): last reading before it starts vs
    first reading after it resolves, isolating the auction's real
    effect from ordinary intraday movement. NIFTY/BANKNIFTY only --
    CAS is an NSE cash-market mechanism, doesn't apply to commodities.
    Days before the market_hours.py fix (Aug 13, 2026) won't have a
    valid post-auction reading and are correctly excluded rather than
    guessed at -- real data only accumulates from today forward.
    GET /api/cas-auction-moves/<NIFTY|BANKNIFTY>/
    """
    def get(self, request, index_name):
        from .index_tracker import compute_cas_auction_moves
        name = index_name.upper()
        if name not in ("NIFTY", "BANKNIFTY"):
            return Response({"error": "index_name must be NIFTY or BANKNIFTY -- CAS doesn't apply to commodities"}, status=400)
        moves = compute_cas_auction_moves(name)
        return Response(clean_json({"index": name, "moves": moves}))


class IndexSignalView(APIView):
    """
    Aug 27 2026: current locked index option call(s) for NIFTY/
    BANKNIFTY, if Index Tracker's Bias has confirmed strongly enough to
    generate one -- see index_signal.py for the full strike-selection
    and SL/Target methodology (strike at the OI wall the Bias just
    confirmed, same ATR+delta math the stock Live Signals already use).
    Empty list (not an error) when Bias is currently Neutral for both,
    or nothing's fired yet this session.
    GET /api/index-signals/
    """
    def get(self, request):
        from . import index_signal
        calls = [c for c in (index_signal.get_locked_call("NIFTY"), index_signal.get_locked_call("BANKNIFTY")) if c]
        return Response(clean_json({"calls": calls, "count": len(calls)}))


class CommodityQuoteView(APIView):
    """
    Sep 18 2026: lightweight replacement for MarketBanner.jsx's three
    commodity cards (Crude/Gold/Silver), per explicit request to keep
    the banner while removing the Commodities tab's actual API cost.

    Deliberately does NOT reuse snapshot_commodity() or the Index
    Tracker Excel pipeline that powered the banner before -- that
    pipeline's own real cost is get_option_analytics() + get_market_
    depth() per symbol, every scan cycle, for all 6 commodity bases,
    which is what generated the large majority of MCX Depth/Option
    chain calls confirmed in this project's own logs. This view does
    exactly one get_quotes() call per request, no option chain, no
    market depth, no Excel write -- confirmed via the same fyers_
    client.py pattern the main 208-stock universe already uses to read
    change% (v.get('chp', ...)), so nothing new is being invented here.

    Also deliberately uses the PLAIN front-month resolvers
    (_front_month_commodity_symbol, _front_month_bullion_symbol), not
    the options-aware variants CommodityCurrentSymbolView above uses --
    those call get_option_analytics() internally specifically to
    validate a real options chain exists, which is real cost this view
    exists to avoid. A quote doesn't need that validation.

    Honest trade-off, not silently dropped: is_expiry_today (shown as
    a badge on the old banner cards) relied on get_last_oi_snapshot(),
    which only gets populated by the option-chain call this view
    deliberately skips -- so it is NOT included here. Returns is_
    expiry_today: False always, rather than faking a real-looking
    value from data this view never fetches.

    Same response shape the banner already expects (snapshots: [...],
    is_expiry_today), so the frontend's rendering logic needed no
    changes -- only the fetch target did.
    GET /api/commodity-quote/<CRUDEOIL|GOLD|SILVER>/
    """
    def get(self, request, name):
        from .index_tracker import (
            COMMODITY_BASES, _NEAR_MONTHLY_BASES,
            _front_month_commodity_symbol, _front_month_bullion_symbol,
        )
        from .fyers_client import get_quotes
        base_name = name.upper()
        if base_name not in COMMODITY_BASES:
            return Response({"error": f"name must be one of {list(COMMODITY_BASES)}"}, status=400)
        base = COMMODITY_BASES[base_name]
        try:
            symbol = (
                _front_month_commodity_symbol(base) if base in _NEAR_MONTHLY_BASES
                else _front_month_bullion_symbol(base)
            )
        except Exception as e:
            print(f"[CommodityQuoteView] {base_name} symbol resolve failed: {e}")
            symbol = None
        if not symbol:
            return Response({"snapshots": [], "is_expiry_today": False})
        try:
            resp = get_quotes([symbol])
            if not resp or resp.get("s") != "ok" or not resp.get("d"):
                return Response({"snapshots": [], "is_expiry_today": False})
            v = (resp["d"][0] or {}).get("v") or {}
            price = v.get("lp")
            if price is None:
                return Response({"snapshots": [], "is_expiry_today": False})
            row = {"Fut": price, "Change %": round(v.get("chp", 0) or 0, 2)}
            return Response({"snapshots": [row], "is_expiry_today": False})
        except Exception as e:
            print(f"[CommodityQuoteView] {base_name} quote fetch failed: {e}")
            return Response({"snapshots": [], "is_expiry_today": False})


class CommodityCurrentSymbolView(APIView):
    """
    Aug 27 2026: the live-resolved Fyers front-month symbol for a
    commodity (e.g. MCX:CRUDEOIL26AUGFUT) -- lets the frontend build a
    real Fyers chart link for Crude/Gold/Silver, the same way NIFTY/
    BANKNIFTY/VIX already can via their fixed INDEX symbols
    (MarketBanner.jsx couldn't do this before: the contract rolls
    monthly, and nothing exposed the CURRENT resolved string to it --
    hardcoding today's would go quietly stale next month).

    Deliberately reuses index_tracker.py's existing resolvers rather
    than re-deriving the rollover rule in JS, which would silently
    drift out of sync the next time either rule changes on the backend
    (exactly the kind of duplication this project has avoided
    elsewhere -- e.g. the two separate bullion-symbol resolvers already
    kept intentionally separate rather than one guessing at the
    other's job). CRUDEOIL/CRUDEOILM resolution is pure date math, no
    Fyers call; GOLD/GOLDM/SILVER/SILVERM's resolver does call Fyers
    but is already cached per-day (index_tracker._bullion_options_
    symbol_cache), so this is cheap on every call after the first each
    day. Returns {"symbol": None} rather than an error if nothing's
    resolvable right now (e.g. bullion with no live contract found in
    the probe window) -- same "don't guess" contract as the resolvers
    themselves already follow.
    GET /api/commodity-symbol/<CRUDEOIL|CRUDEOILM|GOLD|GOLDM|SILVER|SILVERM>/
    """
    def get(self, request, base_name):
        from .index_tracker import (
            COMMODITY_BASES, _NEAR_MONTHLY_BASES,
            _front_month_commodity_symbol, _front_month_bullion_symbol_with_options,
        )
        name = base_name.upper()
        if name not in COMMODITY_BASES:
            return Response({"error": f"base_name must be one of {list(COMMODITY_BASES)}"}, status=400)
        base = COMMODITY_BASES[name]
        try:
            symbol = (
                _front_month_commodity_symbol(base) if base in _NEAR_MONTHLY_BASES
                else _front_month_bullion_symbol_with_options(base)
            )
        except Exception as e:
            print(f"[CommodityCurrentSymbolView] {name} resolve failed: {e}")
            symbol = None
        return Response({"symbol": symbol})


class DailyBacktestStatusView(APIView):
    """
    Aug 27 2026: latest daily-backtest cycle's results -- backfill
    range, stock/NIFTY/BANKNIFTY summaries, PDF availability, any
    errors. Powers a dedicated frontend tab. All fields are None/empty
    until the first cycle has run at least once (either the scheduled
    close/morning run, or a manual trigger via DailyBacktestRunView).
    GET /api/daily-backtest/status/
    """
    def get(self, request):
        from .daily_backtest import get_last_run
        return Response(clean_json(get_last_run()))


class DailyBacktestRunView(APIView):
    """
    Aug 27 2026: manual 'Run Now' trigger for the same daily-backtest
    cycle the background worker runs automatically twice a day (the
    single-click option, alongside the automatic one). Fires the real
    checklist in a background thread and returns immediately -- the
    full cycle can take a while (real Fyers history calls per
    unresolved row, real PDF generation), so this doesn't hold the
    HTTP request open for it. Poll DailyBacktestStatusView (compare
    'started_at' against the time this was called) to see when it's
    finished.
    GET /api/daily-backtest/run/
    """
    def get(self, request):
        from .daily_backtest import run_daily_backtest_cycle_async
        run_daily_backtest_cycle_async(trigger="manual")
        return Response({"started": True, "message": "Daily backtest cycle started in the background -- poll /api/daily-backtest/status/ for results."})


class DailyBacktestReportDownloadView(APIView):
    """Download one of the latest daily-backtest cycle's PDFs.
    GET /api/daily-backtest/download/<stock|nifty|banknifty>/"""
    def get(self, request, report_type):
        from django.http import FileResponse, JsonResponse
        from .daily_backtest import get_last_run
        run = get_last_run()
        key_map = {"stock": "stock_pdf", "nifty": "nifty_pdf", "banknifty": "banknifty_pdf"}
        key = key_map.get(report_type.lower())
        if not key:
            return JsonResponse({"error": "report_type must be one of stock, nifty, banknifty"}, status=400)
        path = run.get(key)
        if not path or not os.path.exists(path):
            return JsonResponse({"error": f"No {report_type} report available yet -- run the daily backtest first."}, status=404)
        filename = os.path.basename(path)
        return FileResponse(open(path, 'rb'), as_attachment=True, filename=filename)


class DailyBacktestRangeView(APIView):
    """
    Aug 27 2026: on-demand backtest for a specific date range -- powers
    the date-range picker in the Daily Backtest tab. Pure preview
    computation: no PDF written, no Telegram send, doesn't touch the
    scheduled cycle's cached last-run status. Safe to call as often as
    someone drags the date picker.
    GET /api/daily-backtest/range/?start=YYYY-MM-DD&end=YYYY-MM-DD
    """
    def get(self, request):
        from .daily_backtest import run_range_backtest
        start = request.GET.get("start")
        end = request.GET.get("end")
        if not start or not end:
            return Response({"error": "start and end query params (YYYY-MM-DD) are required"}, status=400)
        try:
            result = run_range_backtest(start, end)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        return Response(clean_json(result))


class DailyBacktestRangeReportView(APIView):
    """
    Aug 29 2026: the actual downloadable PDF for a specific date range
    -- DailyBacktestRangeView above only ever returns a JSON preview,
    by design. This is the real counterpart: reuses the exact same
    compute_metrics()/write_pdf_report() pipeline (Strategy Scorecard,
    R-Multiple, Long vs Short, every section) the full daily-cycle PDF
    already uses, scoped to just the requested window.

    Sep 8 2026: extended with an optional ?index=NIFTY|BANKNIFTY param,
    routing to the new run_range_index_report() for those two. Default
    behavior (no index param) is UNCHANGED -- still the stock-signals
    range PDF via run_range_report() -- so the existing Stock Signals
    download link in DailyBacktestTab.jsx keeps working exactly as
    before with zero changes needed on its end.
    GET /api/daily-backtest/range/report/?start=YYYY-MM-DD&end=YYYY-MM-DD[&index=NIFTY|BANKNIFTY]
    """
    def get(self, request):
        from django.http import FileResponse, JsonResponse
        from .daily_backtest import run_range_report, run_range_index_report
        start = request.GET.get("start")
        end = request.GET.get("end")
        index_name = request.GET.get("index", "").upper()
        if not start or not end:
            return Response({"error": "start and end query params (YYYY-MM-DD) are required"}, status=400)
        if index_name and index_name not in ("NIFTY", "BANKNIFTY"):
            return Response({"error": "index must be NIFTY or BANKNIFTY"}, status=400)
        try:
            path = run_range_index_report(index_name, start, end) if index_name else run_range_report(start, end)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        if not path or not os.path.exists(path):
            label = f"{index_name} positional" if index_name else "stock"
            return JsonResponse({"error": f"No resolved {label} trades between {start} and {end}."}, status=404)
        filename = os.path.basename(path)
        return FileResponse(open(path, 'rb'), as_attachment=True, filename=filename)


class IndexBacktestExportView(APIView):
    """Download the day-wise backtest as an Excel file, one row per
    date+bias with a Hit% and sample count column per horizon.
    GET /api/backtest/<NIFTY|BANKNIFTY|CRUDEOIL|CRUDEOILM>/export/"""
    def get(self, request, index_name):
        from django.http import FileResponse, JsonResponse
        from .backtest_index_bias import write_backtest_report
        from .index_tracker import TRACKABLE_NAMES
        name = index_name.upper()
        if name not in TRACKABLE_NAMES:
            return JsonResponse({"error": f"index_name must be one of {TRACKABLE_NAMES}"}, status=400)
        try:
            path = write_backtest_report(name)
        except Exception as e:
            return JsonResponse({"error": f"Couldn't generate backtest report: {e}"}, status=500)
        filename = os.path.basename(path)
        return FileResponse(open(path, 'rb'), as_attachment=True, filename=filename)


class IndexTrackerExportView(APIView):
    """Download today's NIFTY/BANKNIFTY/crude-oil tracker Excel file."""
    def get(self, request, index_name):
        from django.http import FileResponse, JsonResponse
        from .index_tracker import get_today_log_path, TRACKABLE_NAMES
        name = index_name.upper()
        if name not in TRACKABLE_NAMES:
            return JsonResponse({"error": f"index_name must be one of {TRACKABLE_NAMES}"}, status=400)
        path = get_today_log_path(name)
        if not path:
            return JsonResponse({"error": f"No {name} snapshots logged yet today."}, status=404)
        filename = os.path.basename(path)
        return FileResponse(open(path, 'rb'), as_attachment=True, filename=filename)


class FyersBrowserTokenView(APIView):
    """
    Hands the frontend the app_id + access_token so services/fyersSocket.js
    can open its own authenticated WebSocket straight to Fyers
    (wss://socket.fyers.in/v3) for live tick updates.

    Previously nothing in this project ever wrote a token into
    localStorage, which is where fyersSocket.js looks -- so that socket
    could open a connection but never actually authenticate, and silently
    received no ticks. This is a stopgap for a single-user local dashboard;
    if you ever deploy this somewhere multi-user, don't expose a real
    trading token to the browser like this -- proxy ticks through the
    Channels consumers that already exist in options/consumers.py instead.
    """
    def get(self, request):
        if not is_authenticated():
            return Response({"authenticated": False, "access_token": None, "app_id": None})
        from .fyers_client import get_access_token
        try:
            token = get_access_token()
        except Exception:
            return Response({"authenticated": False, "access_token": None, "app_id": None})
        return Response({"authenticated": True, "access_token": token, "app_id": CLIENT_ID})


class OptionAnalyticsView(APIView):
    """
    Real option-chain analytics for one symbol: PCR, Max Pain, OI buildup,
    support/resistance, IV, and per-strike Greeks. Backs the 'OI Analytics'
    tab (individual stocks) AND the Crude Oil tab's options section --
    same underlying analytics either way, just resolved to a different
    Fyers symbol depending on what's asked for. Previously hardcoded every
    symbol to NSE:{sym}-EQ, which is wrong for commodities -- their option
    chain's underlying is the rolling front-month FUTURES contract, not an
    NSE equity symbol (confirmed via check_crude_oil_options.py).

    Sep 12 2026: expiry selection now actually wired through -- see the
    `expiry` query param below. Previously selectedExpiry existed only in
    the frontend's own React state and was never sent to this view at
    all, so clicking any of the three expiry buttons re-fetched the exact
    same default (nearest) expiry every time. Fyers' own option-chain
    API's `timestamp` parameter is (per Fyers' community support posts)
    actually "which expiry to fetch", not a point-in-time snapshot -- it
    expects the real `expiry` value from that same chain's own
    expiryData list, not an arbitrary date string, so a genuine expiry
    switch needs a real value from Fyers first, never a guessed one.
    """
    def get(self, request, symbol):
        sym = symbol.upper().replace(".NS", "")
        if not is_authenticated():
            return Response({
                "symbol": sym, "live": False,
                "error": "Fyers not authenticated. Run get_fyers_token.py to log in, then retry.",
            })

        # Aug 24 2026: switched to the options-aware resolver -- the
        # plain _front_month_bullion_symbol() validates only a futures
        # LTP, which a real live test showed can return a stale price
        # for an ALREADY-EXPIRED contract (MCX:GOLD26AUGFUT specifically
        # -- confirmed via the real Fyers symbol master that only Oct/
        # Dec are actually current). This variant additionally confirms
        # a real options chain exists for the candidate before using it.
        #
        # Aug 28 2026: added INDEX_SYMBOLS (NIFTY/BANKNIFTY) -- this view
        # never actually handled indices before. Every symbol NOT in
        # COMMODITY_BASES silently fell through to f"NSE:{sym}-EQ",
        # which is the WRONG Fyers symbol for an index (NSE:NIFTY50-
        # INDEX, not NSE:NIFTY-EQ) -- calling this with "NIFTY" would
        # have failed to resolve anything, not just returned imprecise
        # data. Reuses index_tracker.INDEX_SYMBOLS directly rather than
        # hardcoding the mapping a second time here.
        from .index_tracker import COMMODITY_BASES, _front_month_commodity_symbol, _front_month_bullion_symbol_with_options, _NEAR_MONTHLY_BASES, INDEX_SYMBOLS
        if sym in COMMODITY_BASES:
            base = COMMODITY_BASES[sym]
            fyers_symbol = _front_month_commodity_symbol(base) if base in _NEAR_MONTHLY_BASES else _front_month_bullion_symbol_with_options(base)
        elif sym in INDEX_SYMBOLS:
            fyers_symbol = INDEX_SYMBOLS[sym]
        else:
            fyers_symbol = f"NSE:{sym}-EQ"

        # Sep 12 2026: 'current' (the UI's default, always-existing
        # behavior) needs no extra call -- timestamp="" is already
        # Fyers' own "nearest expiry" default, exactly what this view
        # always did before this fix. 'next'/'monthly' need one
        # lightweight probe first (strikecount=1 -- only expiryData is
        # needed here, not real strike rows) to discover the REAL
        # expiries Fyers is currently listing for this symbol, since
        # there's no way to know a valid one without asking directly.
        expiry_choice = (request.GET.get("expiry") or "current").lower()
        if expiry_choice not in ("current", "next", "monthly"):
            return Response({"symbol": sym, "live": False, "error": f"Unknown expiry choice '{expiry_choice}'."})

        timestamp = ""
        if expiry_choice != "current":
            from .fyers_client import get_option_chain
            try:
                probe = get_option_chain(fyers_symbol, strikecount=1)
            except Exception as e:
                return Response({"symbol": sym, "live": False, "error": f"Could not resolve available expiries: {e}"})
            expiry_list = ((probe or {}).get("data", {}) or {}).get("expiryData", []) if probe else []
            if not expiry_list:
                return Response({"symbol": sym, "live": False, "error": "No expiry data available for this symbol right now."})
            # 'next' = the second listed expiry if one exists, else
            # falls back to the nearest (same as 'current') rather than
            # erroring on a symbol that only has one expiry listed.
            # 'monthly' = the FURTHEST expiry Fyers is currently
            # listing -- a positional best-effort reading of Fyers' own
            # real, live list (this symbol may not have a distinct
            # monthly contract separate from its weeklies), not a
            # verified "this IS the monthly contract" guarantee.
            # resolvedExpiryDate in the response below always reflects
            # whichever real expiry actually got used, so this is
            # verifiable against the live account either way.
            target = expiry_list[1] if expiry_choice == "next" and len(expiry_list) > 1 else (
                expiry_list[-1] if expiry_choice == "monthly" else expiry_list[0]
            )
            timestamp = target.get("expiry") or ""
            if not timestamp:
                return Response({"symbol": sym, "live": False, "error": "Could not resolve a real expiry identifier for this choice."})

        try:
            oi = get_option_analytics(fyers_symbol, strikecount=10, timestamp=timestamp)
        except Exception as e:
            return Response({"symbol": sym, "live": False, "error": str(e)})
        if not oi:
            return Response({
                "symbol": sym, "live": False,
                "error": "No option chain returned — symbol may have no listed F&O options, or market is closed.",
            })

        ce_data = [{"strike": r["strike"], **r["ce"]} for r in oi["rows"] if r["ce"]]
        pe_data = [{"strike": r["strike"], **r["pe"]} for r in oi["rows"] if r["pe"]]

        return Response(clean_json({
            "symbol": sym, "live": True, "spot": oi["spot"], "pcr": oi["pcr"],
            "pcrVolume": oi.get("pcr_volume"),
            "maxPain": oi["max_pain"], "atmIv": oi["iv"], "atmStrike": oi["atm_strike"],
            "atmStraddlePrice": oi.get("atm_straddle_price"),
            "maxPainDistPct": oi.get("max_pain_dist_pct"),
            "support": oi["support"], "resistance": oi["resistance"],
            "oiBuildup": oi["oi_buildup"], "greeks": oi["greeks"],
            "totalCeOi": oi["ce_oi"], "totalPeOi": oi["pe_oi"],
            "ceOiChg": oi["ce_oi_chg"], "peOiChg": oi["pe_oi_chg"],
            "ceData": ce_data, "peData": pe_data,
            "expiryChoice": expiry_choice,
            "resolvedExpiryDate": oi.get("expiry_date"),
        }))


class FiftyTwoWeekRangeView(APIView):
    """
    Aug 28 2026: real 52-week high/low PLUS a Bullish/Neutral/Bearish
    technical read, for a single F&O stock symbol -- built for the
    Watchlist redesign. Combined into one endpoint (not two) because a
    Watchlist row wants both together; no reason to make the frontend
    fire two separate requests per row for data that's always shown
    side by side.

    GET /api/52-week-range/<symbol>/ ->
      {"symbol", "high52w", "low52w", "technical": {"label","rsi","adx"} | null}

    Every field is null if it can't be resolved right now -- never a
    guessed range or a fabricated direction.
    """
    def get(self, request, symbol):
        sym = symbol.upper().replace(".NS", "")
        high52w, low52w = get_52_week_high_low(sym)
        technical = get_technical_signal(sym)
        return Response(clean_json({
            "symbol": sym, "high52w": high52w, "low52w": low52w,
            "technical": technical,
        }))


class OptionHistoryView(APIView):
    """
    Sep 3 2026: real historical candles for ONE SPECIFIC option
    contract, fetched live from Fyers' history() endpoint -- built
    after two failed attempts to send the user to an EXTERNAL site's
    chart for the exact contract (trade.fyers.in has no per-symbol URL
    at all, confirmed multiple times; a TradingView chart-URL attempt
    also failed real testing on an actual signal). This sidesteps that
    whole class of problem by rendering the contract's own chart INSIDE
    this app, using data this project already has real access to.

    Feasibility confirmed via Fyers' own community forum + their own
    notice-board outage notice: historical data is available for
    ACTIVE (not-yet-expired) option contracts specifically -- expired-
    contract history is NOT available (a real, separate Fyers
    limitation, unrelated to this project's code). Every live signal
    here is always for a currently-active contract, so that gap doesn't
    apply to this use case.

    GET /api/option-history/?symbol=NSE:SUZLON26SEP46PE&resolution=5
    resolution: Fyers' own resolution strings -- "5"/"15"/"30"/"60" for
    minute candles, "D" for daily. Defaults to "5" (5-minute candles),
    matching what a just-fired intraday signal actually needs to show.
    Fixed 5-calendar-day lookback -- deliberately NOT the same 1D/5D/1M/
    3M range picker IndexPriceChart.jsx offers; a monthly option
    contract has only ever existed for at most a few weeks, so multi-
    month ranges don't apply the way they do for NIFTY/BANKNIFTY.
    """
    def get(self, request):
        symbol = request.GET.get("symbol")
        if not symbol:
            return Response({"error": "symbol query param is required"}, status=400)
        resolution = request.GET.get("resolution", "5")

        if not is_authenticated():
            return Response({"error": "Not authenticated with Fyers -- no data available"}, status=503)

        # Sep 4 2026: real confusion, confirmed live -- a brand-new
        # signal (KEI, "just now") showed "No real historical data
        # available for this contract right now", which reads like the
        # CONTRACT has no data. The far more likely real cause, given
        # this account has been intermittently rate-limited most of
        # today: the shared circuit breaker (fyers_client.py) was open
        # at that moment, so get_history() below would've returned None
        # without even attempting a real call -- nothing to do with
        # this specific contract at all. Checking that directly here so
        # the message can honestly say which of the two real situations
        # this actually is, instead of one message covering both.
        from .fyers_client import _rate_limited_now
        if _rate_limited_now():
            return Response({
                "error": "Fyers is currently rate-limited (same account-wide block affecting the rest of the app right now) -- this recovers on its own, try again shortly.",
                "symbol": symbol,
            }, status=503)

        range_to = datetime.now().date()
        range_from = range_to - timedelta(days=5)
        try:
            resp = get_history(symbol, resolution=resolution,
                                range_from=str(range_from), range_to=str(range_to))
        except Exception as e:
            print(f"[OptionHistory] {symbol} fetch failed: {e}")
            return Response({"error": f"History fetch failed: {e}"}, status=502)

        if not resp or resp.get("s") != "ok" or not resp.get("candles"):
            return Response({
                "error": "No real historical data available for this contract right now.",
                "symbol": symbol,
            }, status=503)

        candles = resp.get("candles", [])
        points = [
            {"time": c[0], "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]}
            for c in candles if len(c) >= 6
        ]
        # Sep 4 2026: real bug, confirmed live -- the chart's own time
        # labels showed a later time on the left and an earlier time on
        # the right (11:35 before 11:00), meaning Fyers' raw candle
        # order isn't guaranteed to be chronological here, same lesson
        # eod_scanner.py's fetch_daily_history_paced() already learned
        # and handles with its own explicit sort -- this view just never
        # had the equivalent. Sorting by the real timestamp fixes both
        # the mislabeled axis AND the line's actual left-to-right shape,
        # since both were reading the same wrongly-ordered data.
        points.sort(key=lambda p: p["time"])
        return Response(clean_json({"symbol": symbol, "resolution": resolution, "candles": points}))


class CandleChartView(APIView):
    """
    Sep 7 2026: real OHLC candles + EMA(10/20/50/200) + RSI(14) for the
    chart-popup feature (stock/index click -> candlestick modal),
    reusing the SAME get_history() gateway backtest_signal_pnl.py /
    backtest_index_positional.py already depend on -- no second Fyers
    history path introduced.

    GET /api/candles/<symbol>/?interval=D|W&range=3M|6M|12M

    interval: "D" (default) = daily bars. "W" = calendar-week bars,
    built by RESAMPLING the same daily fetch rather than trusting an
    unverified Fyers weekly resolution code -- "D" is the one
    resolution this project has already confirmed works everywhere
    else (OptionHistoryView, the backtest scripts), so betting
    correctness on a second, untested code for weekly wasn't worth it.

    range: the VISIBLE window. The real fetch always pulls MORE than
    this (a buffer before the visible start) so EMA200 isn't sitting
    at null right at the left edge of the chart -- buffer size is a
    reasoned guess (400 calendar days for daily, ~4 years for weekly,
    since a 200-bar weekly warmup needs ~4 years of calendar time),
    not something backtested to an exact minimum. A stock with less
    real history than the buffer just gets whatever real history
    exists -- confirmed via a synthetic 60-day-old-listing test that
    this degrades to partial/null EMA200 and null RSI rather than
    crashing or fabricating values.

    Same symbol resolution as OptionAnalyticsView (commodity front-
    month / index / plain equity) -- reused, not reimplemented, so a
    symbol resolves identically here as it does in the option-chain
    view.

    Every EMA/RSI value that can't be computed yet (insufficient
    warmup history) is null, never a fabricated number -- same
    honesty rule as every other indicator in this project.
    """

    def get(self, request, symbol):
        sym = symbol.upper().replace(".NS", "")
        interval = request.GET.get("interval", "D").upper()
        range_param = request.GET.get("range", "6M").upper()

        if not is_authenticated():
            return Response({"error": "Not authenticated with Fyers -- no data available"}, status=503)

        from .fyers_client import _rate_limited_now
        if _rate_limited_now():
            return Response({
                "error": "Fyers is currently rate-limited (same account-wide block affecting the rest of the app right now) -- this recovers on its own, try again shortly.",
                "symbol": sym,
            }, status=503)

        from .index_tracker import (
            COMMODITY_BASES, _front_month_commodity_symbol,
            _front_month_bullion_symbol_with_options, _NEAR_MONTHLY_BASES, INDEX_SYMBOLS,
        )
        if sym in COMMODITY_BASES:
            base = COMMODITY_BASES[sym]
            fyers_symbol = (
                _front_month_commodity_symbol(base)
                if base in _NEAR_MONTHLY_BASES
                else _front_month_bullion_symbol_with_options(base)
            )
        elif sym in INDEX_SYMBOLS:
            fyers_symbol = INDEX_SYMBOLS[sym]
        else:
            fyers_symbol = f"NSE:{sym}-EQ"

        if not fyers_symbol:
            return Response({"error": f"Could not resolve a Fyers symbol for {sym} right now."}, status=503)

        RANGE_DAYS = {"3M": 90, "6M": 182, "12M": 365}
        visible_days = RANGE_DAYS.get(range_param, 182)

        # Sep 8 2026: real bug, confirmed live against Fyers -- a single
        # history request spanning more than 366 days for D/W/M
        # resolutions is REJECTED outright ("code": -50, "Date range
        # cannot exceed 366 days..."). The old single-call lookback
        # (visible_days + up to 4 years of buffer) blew past that on
        # every range, which is why every symbol/interval/range
        # combination was 503ing, not just one. Fixed by splitting into
        # TWO independent calls, each safely under 366 days on its own:
        # the visible window itself (<=365 days by construction), plus
        # one additional buffer call ending the day before it starts,
        # for EMA200 warmup. The buffer call is best-effort -- if IT
        # fails, the chart still renders off the visible-range call
        # alone (less/no EMA200 warmup at the left edge), it doesn't
        # fail the whole request over a nice-to-have.
        visible_end_date = datetime.now().date()
        visible_start_date = visible_end_date - timedelta(days=visible_days)
        BUFFER_DAYS = 350  # comfortably under 366 on its own, for either D or W
        buffer_end_date = visible_start_date - timedelta(days=1)
        buffer_start_date = buffer_end_date - timedelta(days=BUFFER_DAYS)

        try:
            resp = get_history(fyers_symbol, resolution="D",
                                range_from=str(visible_start_date), range_to=str(visible_end_date))
        except Exception as e:
            print(f"[CandleChart] {fyers_symbol} fetch failed: {e}")
            return Response({"error": f"History fetch failed: {e}"}, status=502)

        if not resp or resp.get("s") != "ok" or not resp.get("candles"):
            print(f"[CandleChart] {fyers_symbol} history not ok, raw Fyers response: {resp}")
            return Response({
                "error": "No real historical data available for this symbol right now.",
                "symbol": sym,
            }, status=503)

        all_candles = list(resp.get("candles", []))

        try:
            buffer_resp = get_history(fyers_symbol, resolution="D",
                                       range_from=str(buffer_start_date), range_to=str(buffer_end_date))
            if buffer_resp and buffer_resp.get("s") == "ok" and buffer_resp.get("candles"):
                all_candles.extend(buffer_resp["candles"])
            else:
                print(f"[CandleChart] {fyers_symbol} buffer history not ok (chart still renders, just less EMA200 warmup): {buffer_resp}")
        except Exception as e:
            print(f"[CandleChart] {fyers_symbol} buffer fetch failed (chart still renders): {e}")

        raw = sorted(all_candles, key=lambda c: c[0])
        df = pd.DataFrame(
            [c[:6] for c in raw if len(c) >= 6],
            columns=["time", "open", "high", "low", "close", "volume"],
        )
        if df.empty:
            return Response({"error": "No usable candles returned.", "symbol": sym}, status=503)

        df["time"] = pd.to_datetime(df["time"], unit="s")

        if interval == "W":
            df = (
                df.set_index("time")
                .resample("W")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
                .dropna(subset=["open"])
                .reset_index()
            )

        for period in (10, 20, 50, 200):
            df[f"ema{period}"] = df["close"].ewm(span=period, adjust=False).mean()

        delta = df["close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        # Textbook RSI edge cases: a pure-uptrend stretch (avg_loss==0)
        # is 100, not inf/nan; a completely flat stretch (both zero) is
        # neutral 50 -- both confirmed against synthetic data rather
        # than assumed.
        rsi = rsi.where(avg_loss != 0, 100.0)
        rsi = rsi.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)
        df["rsi14"] = rsi
        # First 14 bars: ewm still emits a number (it doesn't wait for
        # a full window), but that number isn't a real 14-period
        # average yet -- blanked out rather than shown as if it were.
        df.loc[df.index[:14], "rsi14"] = np.nan

        visible_start = df["time"].max() - pd.Timedelta(days=visible_days)
        visible = df[df["time"] >= visible_start]

        candles = [
            {
                "time": int(row.time.timestamp()),
                "open": float(row.open), "high": float(row.high),
                "low": float(row.low), "close": float(row.close),
                "volume": int(row.volume),
                "ema10": float(row.ema10), "ema20": float(row.ema20),
                "ema50": float(row.ema50), "ema200": float(row.ema200),
                "rsi14": float(row.rsi14),
            }
            for row in visible.itertuples()
        ]

        return Response(clean_json({
            "symbol": sym, "fyers_symbol": fyers_symbol,
            "interval": interval, "range": range_param,
            "candles": candles,
        }))


class BroaderIndicesView(APIView):
    """
    Aug 28 2026: real quotes for the broader NSE indices (Next 50, 100,
    Midcap 100, Smallcap 100) shown on Market View's Indices
    Performance table -- built for the Module 4 redesign.

    Deliberately its OWN endpoint, not folded into /api/market-summary/
    -- that endpoint is polled every 30s by several components
    (MarketBanner, MarketBreadth, SectorPerformance, the Sentiment
    gauge), all reading from the already-cached _stock_cache with zero
    added Fyers cost. fetch_broader_indices() makes a genuinely NEW
    live Fyers call every time it's invoked -- bolting that onto the
    already-heavily-polled endpoint would add a recurring live API
    call to every one of those unrelated components' polls too.

    GET /api/broader-indices/ -> {"indices": {name: {price, change,
    change_percent}, ...}} -- only includes indices that actually
    resolved; see fetch_broader_indices() for why some entries may be
    silently absent (unverified Fyers symbols, degrades gracefully).
    """
    def get(self, request):
        return Response(clean_json({"indices": fetch_broader_indices()}))


class StrategyBacktestRunView(APIView):
    """
    Aug 28 2026: triggers a background price-action strategy backtest
    across the F&O universe -- see strategy_backtest.py for the full
    engine and why OI-confirmation can't be included (only price-
    action conditions: rsi_min, rsi_max, adx_min).

    POST /api/strategy-backtest/run/
    Body: {"strategy": {"rsi_min": 40, "rsi_max": 65, "adx_min": 25},
           "days": 180}  -- days optional, defaults to 180
    Symbols default to the full FNO_STOCKS universe -- ~208 sequential
    Fyers History calls, runs as a background thread (see
    strategy_backtest.py's own module docstring), NOT synchronously --
    this endpoint returns immediately with the current run state; poll
    StrategyBacktestStatusView for progress and results.

    A trigger while a run is already in progress is a no-op (returns
    the ALREADY-RUNNING job's state, doesn't start a competing run --
    verified in strategy_backtest.py's own test suite).
    """
    def post(self, request):
        from .strategy_backtest import start_multi_symbol_backtest
        strategy = request.data.get("strategy") or {}
        days = int(request.data.get("days", 180))
        symbols = request.data.get("symbols") or FNO_STOCKS
        state = start_multi_symbol_backtest(symbols, strategy, days=days)
        return Response(clean_json({
            "running": state["running"],
            "started_at": state["started_at"],
            "symbols_total": state["symbols_total"],
        }))


class StrategyBacktestStatusView(APIView):
    """
    Aug 28 2026: poll the current/last price-action strategy backtest
    run. While running, returns progress only (no trades yet). Once
    complete, computes real metrics via backtest_signal_pnl.py's
    already-proven compute_metrics()/compute_capital_base()/
    compute_equity_curve() -- reusing that pipeline rather than a
    second, parallel aggregation implementation. Trades are scaled to
    a real rupee P&L first (scale_trades_to_lots()) -- the raw
    engine output is a per-SHARE price difference, not yet a real
    position-sized rupee figure.

    Aug 29 2026: scale_trades_to_lots() replaced the old fixed-capital
    version -- per explicit request, sizing now uses each symbol's
    real F&O lot size instead of a capital-derived share count. It
    also now returns an excluded count (trades dropped because their
    symbol had no resolvable live lot size) -- surfaced honestly below
    as excluded_trades, rather than silently vanishing from the trade
    count with no explanation.

    GET /api/strategy-backtest/status/
    """
    def get(self, request):
        from .strategy_backtest import get_strategy_backtest_status, scale_trades_to_lots, serialize_datetimes
        from .backtest_signal_pnl import compute_metrics, compute_capital_base, compute_equity_curve

        state = get_strategy_backtest_status()
        response = {
            "running": state["running"], "started_at": state["started_at"],
            "finished_at": state["finished_at"], "symbols_total": state["symbols_total"],
            "symbols_done": state["symbols_done"], "error": state["error"],
        }

        if state["trades"] is not None:
            scaled, excluded_trades = scale_trades_to_lots(state["trades"])
            capital_base = compute_capital_base(scaled)
            metrics = compute_metrics(scaled, capital_base)
            equity_curve = compute_equity_curve(scaled, capital_base)
            response["trade_count"] = len(scaled)
            response["excluded_trades"] = excluded_trades
            response["metrics"] = serialize_datetimes(metrics)
            response["capital_base"] = capital_base
            response["equity_curve"] = serialize_datetimes(equity_curve)
            response["trades"] = serialize_datetimes(scaled)
        return Response(clean_json(response))


# ============================================================
# TELEGRAM ALERTS
# ============================================================

TELEGRAM_BOT_TOKEN = 'YOUR_BOT_TOKEN_HERE'  # <-- replace
TELEGRAM_CHAT_ID = 'YOUR_CHAT_ID_HERE'       # <-- replace

def send_telegram_alert(signal):
    """Call this when a new SNIPER signal is generated"""
    msg = f"""🎯 *SNIPER SIGNAL*

*{signal['symbol']}* | Grade {signal['grade']}

{'🟢' if signal['action'] == 'BUY' else '🔴'} *{signal['action']} {signal['action'] == 'BUY' and 'CE' or 'PE'}*
Strike: ₹{signal.get('strike', 0)}
Entry: ₹{signal.get('entry', signal.get('price', 0))}
SL: ₹{signal.get('sl', 0)}
Target: ₹{signal.get('target1', 0)}
Qty: {signal.get('quantity', 1)}

Confidence: {signal.get('confidence', 'N/A')}
R:R {signal.get('risk_reward', 2)}

⏰ Generated at {pd.Timestamp.now().strftime('%H:%M IST')}

#SNIPER #{signal['symbol']}
"""
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': msg,
        'parse_mode': 'Markdown',
    }
    
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram send failed: {e}")


# ============================================================
# JSON CLEANER
# ============================================================

class WeeklyReportView(APIView):
    """
    Download the weekly signals + index report on demand. Same content
    the Friday-scheduled command generates. GET /api/weekly-report/
    Add ?telegram=1 to also send it to Telegram right away, same as
    the scheduled command does automatically.
    """
    def get(self, request):
        from django.http import FileResponse, JsonResponse
        from .weekly_report import generate_weekly_report
        path = generate_weekly_report()
        if not path:
            return JsonResponse({"error": "Report generation failed."}, status=500)

        if request.GET.get('telegram'):
            try:
                from trading.telegram_bot import TelegramBot
                bot = TelegramBot()
                bot.send_document(path, caption=f"📊 <b>F&O Radar — Weekly Report</b>\n{os.path.basename(path)}")
            except Exception as e:
                print(f"[Telegram] Failed to send weekly report: {e}")

        filename = os.path.basename(path)
        return FileResponse(open(path, 'rb'), as_attachment=True, filename=filename)


def _compute_breadth(stocks):
    """
    Aug 28 2026: real market breadth computed from the F&O universe this
    project already scans every cycle (_stock_cache, FNO_STOCKS -- 208
    symbols) -- NOT full-NSE breadth. A full-market breadth reading
    (thousands of stocks) would need an entirely new, much larger
    batch-quote flow this project has never had; scoped and labeled
    honestly to the real ~208-stock F&O universe already being tracked
    here, rather than presenting a smaller sample as if it were the
    whole market.

    "Unchanged" is a real, exact 0.0% change_percent reading from
    Fyers, not a rounding artifact -- a stock that genuinely hasn't
    traded yet today (or traded at exactly yesterday's close) reads
    this way; not fabricated or estimated.
    """
    if not stocks:
        return {
            "advances": 0, "declines": 0, "unchanged": 0, "total": 0,
            "advances_pct": 0, "declines_pct": 0, "unchanged_pct": 0,
            "total_volume": 0,
        }
    advances = sum(1 for s in stocks if (s.get("change_percent") or 0) > 0)
    declines = sum(1 for s in stocks if (s.get("change_percent") or 0) < 0)
    unchanged = sum(1 for s in stocks if (s.get("change_percent") or 0) == 0)
    total = len(stocks)
    total_volume = sum(s.get("volume") or 0 for s in stocks)
    return {
        "advances": advances, "declines": declines, "unchanged": unchanged,
        "total": total,
        "advances_pct": round(advances / total * 100, 1) if total else 0,
        "declines_pct": round(declines / total * 100, 1) if total else 0,
        "unchanged_pct": round(unchanged / total * 100, 1) if total else 0,
        "total_volume": total_volume,
    }


def _compute_sector_performance(stocks):
    """
    Aug 28 2026: real sector-level aggregation from the F&O universe
    this project already scans -- each stock's own `sector` field
    (already set from the SECTORS mapping in _fetch_all_quotes_fyers)
    grouped and averaged. This is a SIMPLE AVERAGE of each sector's
    stocks' change_percent, NOT a market-cap-weighted index reading --
    this project has no market-cap data wired into the live scan to
    weight by, so a cap-weighted figure would just be invented. Stated
    plainly as a simple average, not presented as a precise sector
    index the way NIFTY IT/NIFTY AUTO etc. are on NSE's own site.

    Sorted by real performance (best first) -- matches how this is
    actually used (scanning for which sectors are leading today), not
    alphabetical order.
    """
    from collections import defaultdict
    by_sector = defaultdict(list)
    for s in stocks:
        sector = s.get("sector") or "Unknown"
        by_sector[sector].append(s)

    results = []
    for sector, group in by_sector.items():
        changes = [s.get("change_percent") or 0 for s in group]
        avg_chg = round(sum(changes) / len(changes), 2) if changes else 0
        advances = sum(1 for c in changes if c > 0)
        declines = sum(1 for c in changes if c < 0)
        results.append({
            "sector": sector,
            "change_percent": avg_chg,
            "advances": advances,
            "declines": declines,
            "stock_count": len(group),
        })
    results.sort(key=lambda r: r["change_percent"], reverse=True)
    return results


def _compute_market_movers(stocks, limit=10):
    """
    Aug 28 2026: real top gainers/losers from the F&O universe's
    current change_percent -- same 208-stock scan every other
    Dashboard-tier panel uses. No fabricated per-mover timestamp (the
    mockup's own Market Movers panel showed a time per row, but this
    project doesn't track "when a stock became a top mover" as its
    own event -- only the current live change% snapshot, which is
    what's returned here).
    """
    sorted_stocks = sorted(stocks, key=lambda s: s.get('change_percent') or 0, reverse=True)
    gainers = [s for s in sorted_stocks if (s.get('change_percent') or 0) > 0][:limit]
    losers = sorted(
        [s for s in sorted_stocks if (s.get('change_percent') or 0) < 0],
        key=lambda s: s.get('change_percent') or 0,
    )[:limit]
    return {
        "gainers": [{"symbol": s["symbol"], "price": s["price"], "change_percent": s["change_percent"]} for s in gainers],
        "losers": [{"symbol": s["symbol"], "price": s["price"], "change_percent": s["change_percent"]} for s in losers],
    }


def _classify_sentiment_band(chg):
    """Assigns one of 5 sentiment bands to a single stock's change% --
    thresholds are a reasonable first cut, not empirically tuned, same
    "watch and retune" status as every other threshold in this project
    (PCR bands, Bias vote margins, price-confirmation thresholds)."""
    if chg >= 2.0:
        return "Very Bullish"
    if chg >= 0.5:
        return "Bullish"
    if chg > -0.5:
        return "Neutral"
    if chg > -2.0:
        return "Bearish"
    return "Very Bearish"


_SENTIMENT_BAND_VALUE = {"Very Bullish": 100, "Bullish": 75, "Neutral": 50, "Bearish": 25, "Very Bearish": 0}
_SENTIMENT_BAND_ORDER = ["Very Bullish", "Bullish", "Neutral", "Bearish", "Very Bearish"]


def _compute_market_sentiment(stocks):
    """
    Aug 28 2026: real market sentiment gauge computed ENTIRELY from the
    F&O universe's own change_percent distribution -- the same
    208-stock data breadth/sector performance already use. Deliberately
    NOT a hand-mixed formula blending PCR/VIX/Bias with invented
    weights -- the overall 0-100 score is the mathematically CONSISTENT
    weighted average of the same 5-band breakdown returned alongside
    it (each band's fixed sentiment value x its real percentage of
    stocks), so the gauge number and the legend can never quietly
    drift apart into two independently-guessed figures. Verified by
    this module's own test suite: score == weighted_avg(bands), always.
    """
    if not stocks:
        return {"score": 50, "label": "Neutral", "bands": []}

    counts = {name: 0 for name in _SENTIMENT_BAND_ORDER}
    for s in stocks:
        chg = s.get("change_percent") or 0
        band = _classify_sentiment_band(chg)
        counts[band] += 1

    total = len(stocks)
    bands = []
    weighted_sum = 0
    for name in _SENTIMENT_BAND_ORDER:
        count = counts[name]
        pct = round(count / total * 100, 1) if total else 0
        bands.append({"label": name, "count": count, "pct": pct})
        weighted_sum += _SENTIMENT_BAND_VALUE[name] * count

    score = round(weighted_sum / total, 1) if total else 50

    if score >= 80:
        label = "Very Bullish"
    elif score >= 60:
        label = "Bullish"
    elif score >= 40:
        label = "Neutral"
    elif score >= 20:
        label = "Bearish"
    else:
        label = "Very Bearish"

    return {"score": score, "label": label, "bands": bands}


def clean_json(data):
    """Replace NaN, Inf, -Inf with None so JSON serializes properly"""
    if isinstance(data, dict):
        return {k: clean_json(v) for k, v in data.items()}
    if isinstance(data, list):
        return [clean_json(item) for item in data]
    if isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            return None
    return data
