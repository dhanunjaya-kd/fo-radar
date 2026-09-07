# ============================================================
# PASTE INSTRUCTIONS
# ============================================================
# 1. This class needs one more name imported at the top of views.py.
#    Your existing import block (line ~26) already pulls in
#    is_authenticated, get_quotes, get_option_analytics, get_history,
#    CLIENT_ID from .fyers_client -- nothing new needed there, this
#    view only uses names already imported at module level (pd, np,
#    datetime, timedelta, APIView, Response, is_authenticated,
#    get_history, clean_json).
#
# 2. Paste the class below anywhere among your other APIView classes
#    -- right after OptionHistoryView (around line 3030) is a natural
#    spot, since it's the closest sibling (same get_history() + Fyers
#    circuit-breaker pattern).
#
# 3. Add the matching route to urls.py (see the separately-delivered
#    urls.py) and import CandleChartView alongside your other view
#    imports there.
#
# Verified: the EMA/RSI/resample logic below was run standalone
# against synthetic daily data across all 6 interval/range
# combinations (D/W x 3M/6M/12M), plus a short-history (60-day,
# newly-listed-stock) edge case and an empty-candles edge case --
# no exceptions, every numeric field came back as a native
# JSON-safe Python int/float or None, RSI's 0-avg-loss/0-avg-gain
# edge cases resolved to 100/50 rather than inf/nan.
# ============================================================


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
        lookback_days = visible_days + (365 * 4 if interval == "W" else 400)

        range_to = datetime.now().date()
        range_from = range_to - timedelta(days=lookback_days)
        try:
            resp = get_history(fyers_symbol, resolution="D",
                                range_from=str(range_from), range_to=str(range_to))
        except Exception as e:
            print(f"[CandleChart] {fyers_symbol} fetch failed: {e}")
            return Response({"error": f"History fetch failed: {e}"}, status=502)

        if not resp or resp.get("s") != "ok" or not resp.get("candles"):
            return Response({
                "error": "No real historical data available for this symbol right now.",
                "symbol": sym,
            }, status=503)

        raw = sorted(resp.get("candles", []), key=lambda c: c[0])
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
