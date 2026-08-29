"""
screener/strategy_backtest.py

Aug 28 2026: core simulation engine for a price-action-only strategy
backtest -- the foundational piece of Module 10's "rule builder"
concept from the 12-screen redesign reference.

WHY PRICE-ACTION ONLY, NOT THE FULL RULE BUILDER THE MOCKUP IMPLIES:
OI-confirmation (a core part of every live SNIPER signal) depends on a
LIVE option-chain fetch at signal-evaluation time -- that data was
never archived for the broader F&O universe (only NIFTY/BANKNIFTY get
historical option-chain snapshots, via Index Tracker, and only from
whenever that snapshotting started). There is no historical record of
"what did WIPRO's option chain look like on a past date" to test an
OI-based rule against. A strategy defined here can only ever use
conditions derivable from ordinary OHLCV history (RSI, ADX, ATR-based
sizing) -- OI-confirmation can be used live (as it already is) but
never backtested.

Strategy dict format: any of {rsi_min, rsi_max, adx_min} -- a key
that's absent means "no constraint on this condition." Extensible to
more price-action conditions later without changing this shape.

MULTI-SYMBOL PERFORMANCE: looping the full ~208-stock F&O universe
means ~208 sequential Fyers History API calls -- run via a background
daemon thread (run_multi_symbol_backtest_worker below), same pattern
as daily_backtest.py's own worker, not a synchronous request that
would time out.
"""
import threading
from datetime import datetime

import pandas as pd
import numpy as np


def compute_indicator_series(close, high, low, volume):
    """
    Same math as views.py's _compute_indicators(), but returns the
    FULL per-day series instead of truncating to .iloc[-1] -- a
    backtest needs to know what RSI/ADX/ATR WAS on every historical
    day, not just the most recent one. The underlying pandas rolling/
    ewm calls already compute a value for every row internally; this
    just keeps all of them instead of discarding all but the last.

    Verified (test_indicator_series.py) to produce an IDENTICAL final
    value to the already-proven, already-live _compute_indicators() --
    same math, just not truncated early.
    """
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=14).mean()

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
    adx = dx.ewm(com=period - 1, adjust=False).mean()

    return pd.DataFrame({'rsi': rsi, 'adx': adx, 'atr': atr})


def simulate_price_action_strategy(indicator_df, price_df, strategy,
                                    max_holding_days=10, atr_multiplier_sl=1.5,
                                    atr_multiplier_target=3.0):
    """
    Walks indicator_df/price_df day by day (must be aligned, same
    index -- indicator_df from compute_indicator_series(), price_df
    with Close/High/Low columns). On each day NOT already inside an
    open trade, if every condition actually present in `strategy` is
    satisfied, opens a trade at that day's close. SL/Target computed
    from that day's real ATR (same ATR-based convention this project
    already uses for live signal sizing). Exits at whichever comes
    first: SL hit (Low <= SL), Target hit (High >= Target), or
    max_holding_days elapsed (Timeout, exits at that day's close).

    No overlapping trades -- can't re-enter until strictly after the
    current trade has exited (verified in test_trade_simulation.py).
    A trade whose entry would leave zero real days to exit into is
    discarded, never given a fabricated outcome.

    Returns a list of trade dicts: {entry_idx, exit_idx, entry_price,
    exit_price, sl, target, pnl, pnl_pct, exit_reason}. entry_idx/
    exit_idx are positions into price_df/indicator_df -- see
    attach_real_dates() below to convert these into real calendar
    dates.
    """
    trades = []
    n = len(price_df)
    i = 0
    while i < n:
        row = indicator_df.iloc[i]
        if pd.isna(row['rsi']) or pd.isna(row['adx']) or pd.isna(row['atr']):
            i += 1
            continue

        if 'rsi_min' in strategy and row['rsi'] < strategy['rsi_min']:
            i += 1
            continue
        if 'rsi_max' in strategy and row['rsi'] > strategy['rsi_max']:
            i += 1
            continue
        if 'adx_min' in strategy and row['adx'] < strategy['adx_min']:
            i += 1
            continue

        entry_price = price_df['Close'].iloc[i]
        atr = row['atr']
        sl = entry_price - atr * atr_multiplier_sl
        target = entry_price + atr * atr_multiplier_target
        entry_idx = i

        exit_idx = None
        exit_price = None
        exit_reason = None
        for j in range(i + 1, min(i + 1 + max_holding_days, n)):
            day_low = price_df['Low'].iloc[j]
            day_high = price_df['High'].iloc[j]
            if day_low <= sl:
                exit_idx, exit_price, exit_reason = j, sl, 'SL Hit'
                break
            if day_high >= target:
                exit_idx, exit_price, exit_reason = j, target, 'Target Hit'
                break

        if exit_idx is None:
            last_j = min(i + max_holding_days, n - 1)
            if last_j <= i:
                break  # zero real days remaining to exit into -- discard, never fabricate an outcome
            exit_idx = last_j
            exit_price = price_df['Close'].iloc[last_j]
            exit_reason = 'Timeout'

        pnl = exit_price - entry_price
        pnl_pct = (pnl / entry_price) * 100
        trades.append({
            'entry_idx': int(entry_idx), 'exit_idx': int(exit_idx),
            'entry_price': round(float(entry_price), 2), 'exit_price': round(float(exit_price), 2),
            'sl': round(float(sl), 2), 'target': round(float(target), 2),
            'pnl': round(float(pnl), 2), 'pnl_pct': round(float(pnl_pct), 2),
            'exit_reason': exit_reason,
        })
        i = exit_idx + 1  # no overlapping trades -- next scan starts strictly after this one closed

    return trades


def attach_real_dates(trades, price_df):
    """
    Aug 28 2026: maps each trade's positional entry_idx/exit_idx back
    to real calendar dates using price_df's 'ts' column (epoch
    seconds, Fyers' candle format) -- converts the trade dict into the
    exact shape backtest_signal_pnl.py's compute_metrics()/
    compute_equity_curve() expect (entry_dt, exit_dt as real
    datetimes, alongside the existing pnl field), so this engine's
    output can plug directly into that already-proven aggregation
    pipeline rather than needing a second, parallel implementation.

    Naive datetimes (datetime.utcfromtimestamp(), not timezone-aware)
    deliberately -- matches this project's existing convention
    throughout backtest_signal_pnl.py/news.py; switching to
    timezone-aware here specifically would risk a type-mismatch
    TypeError the moment these trades are compared against other
    naive datetimes in that existing pipeline.

    Verified in test_date_mapping.py: correct date resolution,
    exit_dt always after entry_dt, all original fields preserved,
    correct behavior when merging trades from different symbols.
    """
    result = []
    for t in trades:
        entry_ts = price_df['ts'].iloc[t['entry_idx']]
        exit_ts = price_df['ts'].iloc[t['exit_idx']]
        new_trade = dict(t)
        new_trade['entry_dt'] = datetime.utcfromtimestamp(entry_ts)
        new_trade['exit_dt'] = datetime.utcfromtimestamp(exit_ts)
        result.append(new_trade)
    return result


def backtest_symbol(symbol, strategy, days=180, **kwargs):
    """
    Fetches real history for `symbol` via the existing, already-proven
    _fyers_history_df() (views.py) and runs simulate_price_action_
    strategy() against it, then attaches real dates so the output is
    directly compatible with backtest_signal_pnl.py's aggregation
    functions. Deferred import to avoid a circular dependency
    (views.py imports THIS module).

    Returns [] (never raises to the caller) if history can't be
    fetched -- same "no real data, no results" rule every other
    function in this project follows.
    """
    from .views import _fyers_history_df
    df = _fyers_history_df(symbol, days=days)
    if df is None or df.empty or len(df) < 20:
        return []
    indicator_df = compute_indicator_series(df['Close'], df['High'], df['Low'], df['Volume'])
    trades = simulate_price_action_strategy(indicator_df, df, strategy, **kwargs)
    for t in trades:
        t['symbol'] = symbol
    return attach_real_dates(trades, df)


# ============================================================
# MULTI-SYMBOL BACKGROUND WORKER
# ============================================================
# Aug 28 2026: same "trigger + poll" pattern as daily_backtest.py's
# own worker -- a run across the full F&O universe means ~208
# sequential Fyers History calls, genuinely too slow for a
# synchronous request/response cycle. One background thread at a
# time; a second trigger while one is already running is a no-op
# (returns the current status instead of starting a competing run).

_strategy_backtest_state = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "strategy": None,
    "symbols_total": 0,
    "symbols_done": 0,
    "trades": None,   # list of trade dicts once complete
    "error": None,
}
_strategy_backtest_lock = threading.Lock()


def _run_multi_symbol_backtest(symbols, strategy, days=180, **kwargs):
    """The actual worker body -- runs in a background thread, updates
    _strategy_backtest_state as it goes so a status endpoint can show
    live progress rather than a silent black box."""
    global _strategy_backtest_state
    all_trades = []
    try:
        for i, symbol in enumerate(symbols):
            try:
                trades = backtest_symbol(symbol, strategy, days=days, **kwargs)
                all_trades.extend(trades)
            except Exception as e:
                print(f"[StrategyBacktest] {symbol} failed, skipping: {e}")
            with _strategy_backtest_lock:
                _strategy_backtest_state["symbols_done"] = i + 1
        all_trades.sort(key=lambda t: t["exit_dt"])
        with _strategy_backtest_lock:
            _strategy_backtest_state["trades"] = all_trades
            _strategy_backtest_state["error"] = None
    except Exception as e:
        with _strategy_backtest_lock:
            _strategy_backtest_state["error"] = str(e)
    finally:
        with _strategy_backtest_lock:
            _strategy_backtest_state["running"] = False
            _strategy_backtest_state["finished_at"] = datetime.utcnow().isoformat()


def start_multi_symbol_backtest(symbols, strategy, days=180, **kwargs):
    """
    Triggers a background run across `symbols` if one isn't already in
    progress. Returns the CURRENT state immediately (doesn't block) --
    the caller polls get_strategy_backtest_status() for progress and
    the final trade list.
    """
    with _strategy_backtest_lock:
        if _strategy_backtest_state["running"]:
            return dict(_strategy_backtest_state)
        _strategy_backtest_state.update({
            "running": True, "started_at": datetime.utcnow().isoformat(),
            "finished_at": None, "strategy": strategy,
            "symbols_total": len(symbols), "symbols_done": 0,
            "trades": None, "error": None,
        })
        state_copy = dict(_strategy_backtest_state)

    thread = threading.Thread(target=_run_multi_symbol_backtest, args=(symbols, strategy, days), kwargs=kwargs, daemon=True)
    thread.start()
    return state_copy


def get_strategy_backtest_status():
    """Read-only snapshot of the current/last run's state -- safe to
    call from a polling endpoint at any time, running or not."""
    with _strategy_backtest_lock:
        return dict(_strategy_backtest_state)


def scale_trades_to_lots(trades):
    """
    Aug 29 2026: REPLACED scale_trades_to_capital() (fixed-capital
    sizing, qty = capital_per_trade / entry_price) with real, per-
    symbol lot-size sizing -- per explicit request. Matches this
    project's existing backtest_signal_pnl.py convention exactly: same
    get_lot_size() resolver, same skip-on-unresolvable behavior (never
    defaults to a guessed quantity).

    HONEST LIMITATION, carried over unchanged from before: this engine
    simulates the UNDERLYING STOCK's price movement (RSI/ADX/ATR), not
    actual option premium movement -- there's no historical option-
    chain archive for the broader F&O universe, so OI-confirmation
    can't be backtested here (see simulate_price_action_strategy()'s
    own docstring). Sizing by the real lot size makes the POSITION
    SIZE realistic and F&O-native -- what you'd actually trade in --
    but the P&L still reflects the underlying's price change per lot,
    not a real option premium's own movement, which would differ due
    to delta, theta, and IV. This is a more realistic quantity
    convention, not a true options-premium P&L simulation.

    Trades whose symbol has no resolvable live lot size are EXCLUDED
    entirely, never defaulted to a guessed quantity -- same rule
    backtest_signal_pnl.py already follows for exactly this situation.

    pnl_pct is left completely untouched -- it's a pure percentage
    return, independent of position size. Only the absolute pnl field
    is scaled.

    Returns (list of NEW trade dicts, excluded_count) -- never mutates
    the input. Tested in test_lot_size_scaling.py (5 cases) against an
    injected mock lookup; re-verified here against the real resolver.
    """
    from .lot_size_resolver import get_lot_size
    result = []
    excluded = 0
    for t in trades:
        qty = get_lot_size(t['symbol'])
        if qty is None:
            excluded += 1
            continue
        new_trade = dict(t)
        new_trade['qty'] = qty
        new_trade['pnl'] = round(t['pnl'] * qty, 2)
        result.append(new_trade)
    return result, excluded


def serialize_datetimes(obj):
    """
    Aug 28 2026: caught live by this module's own response-shaping
    test (test_status_response.py) -- backtest_signal_pnl.py's
    compute_metrics() returns raw datetime objects NESTED throughout
    its output (max_drawdown.peak_dt/trough_dt/recovered_dt,
    drawdown_periods[].*, equity_curve[].dt), not just at the top
    level. A plain json.dumps() on that raises TypeError immediately.
    Django REST Framework's Response() MIGHT handle this automatically
    via its own JSON encoder, but that's project-configuration-
    dependent and unverified here -- rather than rely on unconfirmed
    framework behavior for something that would be a hard 500 error if
    wrong, this recursively walks any nested dict/list structure and
    converts every datetime found to an ISO string explicitly.
    """
    if isinstance(obj, dict):
        return {k: serialize_datetimes(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [serialize_datetimes(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj




