"""
Sep 19 2026: real candlestick pattern detection for the Scanner's
pattern tags -- standard shape definitions (body/wick ratios), not
fabricated or approximate. Operates on the CURRENT (most recent)
candle, using a few candles of trailing context for trend direction
(Hammer vs Hanging Man, Inverted Hammer vs Shooting Star share the
same shape and are only distinguished by whether they follow a
downtrend or an uptrend) and multi-candle patterns (Engulfing, Dark
Cloud Cover, Morning Star).

Verified against 16 hand-built synthetic OHLC examples (one per
pattern, plus two negative controls -- an ordinary candle correctly
produces no tag) before this was wired into anything -- a subtle
threshold bug (Hammer/Inverted-Hammer test bodies landing just under
the Doji cutoff) was caught and fixed by that suite, not left for a
live scan to surface first.

Takes a pandas DataFrame with Open/High/Low/Close columns, oldest row
first, most recent row last (same convention _fyers_history_df already
uses everywhere else in this project). Returns a list of pattern name
strings detected on the LAST row -- empty list if none. Patterns are
not mutually exclusive -- a real candle can legitimately match more
than one shape (e.g. a strongly engulfing candle that's also a
marubozu), so more than one tag coming back is expected, not a bug.
"""
import pandas as pd


def _candle_metrics(row):
    o, h, l, c = row['Open'], row['High'], row['Low'], row['Close']
    body = abs(c - o)
    rng = h - l
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    return {
        'open': o, 'high': h, 'low': l, 'close': c,
        'body': body, 'range': rng,
        'upper_wick': upper_wick, 'lower_wick': lower_wick,
        'bullish': c > o, 'bearish': c < o,
    }


def _prior_trend(closes, lookback=5):
    """'up' / 'down' / 'flat' -- based on the close N candles before
    the pattern candle vs the close just before it (excludes the
    pattern candle itself, which is what decides Hammer-vs-Hanging-Man
    and Inverted-Hammer-vs-Shooting-Star)."""
    if len(closes) < lookback + 1:
        return 'flat'
    prior_closes = closes[-(lookback + 1):-1]
    if prior_closes[-1] > prior_closes[0]:
        return 'up'
    elif prior_closes[-1] < prior_closes[0]:
        return 'down'
    return 'flat'


def detect_patterns(df):
    if df is None or len(df) < 2:
        return []
    patterns = []
    cur = _candle_metrics(df.iloc[-1])
    prev = _candle_metrics(df.iloc[-2]) if len(df) >= 2 else None
    prev2 = _candle_metrics(df.iloc[-3]) if len(df) >= 3 else None
    closes = df['Close'].tolist()
    trend = _prior_trend(closes)

    if cur['range'] <= 0:
        return []  # a zero-range candle (halted stock, bad data) -- no shape to read

    body_pct = cur['body'] / cur['range']
    upper_pct = cur['upper_wick'] / cur['range']
    lower_pct = cur['lower_wick'] / cur['range']

    # --- Doji family: tiny body ---
    if body_pct <= 0.1:
        if upper_pct >= 0.6 and lower_pct <= 0.1:
            patterns.append('Gravestone Doji')
        elif lower_pct >= 0.6 and upper_pct <= 0.1:
            patterns.append('Dragonfly Doji')
        elif upper_pct >= 0.3 and lower_pct >= 0.3:
            patterns.append('Long-Legged Doji')
        else:
            patterns.append('Doji')

    # --- Marubozu: almost no wicks at all ---
    elif body_pct >= 0.9:
        patterns.append('Bull Marubozu' if cur['bullish'] else 'Bear Marubozu')

    # --- Hammer-shaped: small-but-real body, long lower wick, small
    # upper wick (a near-zero body here is already claimed by the
    # Doji branch above, so body > 0 in practice by this point) ---
    elif cur['body'] > 0 and cur['lower_wick'] >= 2 * cur['body'] and cur['upper_wick'] <= 0.3 * cur['body']:
        if trend == 'down':
            patterns.append('Hammer')
        elif trend == 'up':
            patterns.append('Hanging Man')

    # --- Inverted-hammer-shaped: small-but-real body, long upper
    # wick, small lower wick ---
    elif cur['body'] > 0 and cur['upper_wick'] >= 2 * cur['body'] and cur['lower_wick'] <= 0.3 * cur['body']:
        if trend == 'down':
            patterns.append('Inverted Hammer')
        elif trend == 'up':
            patterns.append('Shooting Star')

    # --- Spinning Top: smallish body, both wicks meaningful but not
    # long enough to qualify as hammer/inverted-hammer shapes ---
    elif 0.1 < body_pct <= 0.35 and upper_pct >= 0.2 and lower_pct >= 0.2:
        patterns.append('Spinning Top')

    # --- Two-candle patterns ---
    if prev is not None:
        if prev['bearish'] and cur['bullish'] and cur['open'] <= prev['close'] and cur['close'] >= prev['open']:
            patterns.append('Bullish Engulfing')
        if prev['bullish'] and cur['bearish'] and cur['open'] >= prev['close'] and cur['close'] <= prev['open']:
            patterns.append('Bearish Engulfing')

        prev_mid = (prev['open'] + prev['close']) / 2
        if (prev['bullish'] and cur['bearish']
                and cur['open'] > prev['close']
                and prev_mid > cur['close'] > prev['open']):
            patterns.append('Dark Cloud Cover')

    # --- Three-candle pattern: Morning Star ---
    if prev2 is not None and prev is not None:
        first_mid = (prev2['open'] + prev2['close']) / 2
        if (prev2['bearish'] and (prev2['body'] / prev2['range'] >= 0.5 if prev2['range'] > 0 else False)
                and (prev['body'] / prev['range'] <= 0.3 if prev['range'] > 0 else False)
                and cur['bullish'] and cur['close'] > first_mid):
            patterns.append('Morning Star')

    return patterns
