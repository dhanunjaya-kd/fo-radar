"""
screener/strategy_backtest.py

Aug 28 2026: core simulation engine for a price-action-only strategy
backtest -- the foundational piece of Module 10's "rule builder"
concept from the 12-screen redesign reference.

SCOPE, stated plainly: this is the CORE, single-stock simulation
engine, proven correct by its own test suite (test_indicator_series.py,
test_trade_simulation.py) -- NOT yet a complete feature. Still needed
before this is usable end-to-end:
  1. Wiring into a Django view + URL route
  2. Extension to loop across the full F&O universe (208 sequential
     Fyers History API calls is slow -- needs a background-worker
     pattern like daily_backtest.py, not a synchronous request)
  3. A frontend UI for defining strategy parameters and viewing results

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
"""
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
    exit_idx are positions into price_df/indicator_df -- the caller
    maps these back to real dates.
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


def backtest_symbol(symbol, strategy, days=180, **kwargs):
    """
    Fetches real history for `symbol` via the existing, already-proven
    _fyers_history_df() (views.py) and runs simulate_price_action_
    strategy() against it. Thin convenience wrapper -- deferred import
    to avoid a circular dependency (views.py will import THIS module).

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
    return trades
