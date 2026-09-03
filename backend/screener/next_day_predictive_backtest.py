"""
backend/screener/next_day_predictive_backtest.py

Real, evidence-first check of whether the Next Day Watchlist's current
scoring (RSI extreme, distance from 20-day SMA, volume ratio) actually
predicts NEXT-DAY price continuation -- i.e. whether a high score
today genuinely means a better bet for TOMORROW, or just means "today
was a volatile day for this stock" (which is what it currently
measures, and those are two different things).

Sep 3 2026: built after direct feedback -- the current watchlist
answers "what was notable about this stock TODAY", not "will it go
UP TOMORROW". Nothing in the current scoring distinguishes a stock
about to keep running from one about to see profit-booking after an
already-extreme move. This is the real check for that, using data
this project already has: every EOD scan already fetches ~40 real
trading days of daily candles per stock into next_day_watchlist_raw.json
(eod_scanner.py's own output) -- this was just never analyzed for its
own predictive power before.

METHOD: walk-forward, no look-ahead. For each stock, for each day i in
its real candle history (except the very last day, which has no known
"next day" outcome yet), computes the REAL, ACTUAL compute_score() /
classify_trend_status() / classify_volume_status() from
next_day_ranking.py -- imported directly, not re-derived -- using
ONLY price/volume data available up to and including day i. Then
looks up what ACTUALLY happened the next real trading day in the same
candle data. Aggregates across every stock and every day into score
buckets, so you can see directly whether a higher score actually
correlates with a better next-day return, a worse one, or no real
relationship at all.

HONEST LIMITATION: sector_relative_pct (25 of the real scoring
formula's 100 points) needs same-day peer data across the WHOLE
scanned universe for every single historical day to compute "vs
sector average that day" -- reconstructing that fully is real
additional work beyond this first pass, so it's left out here
(passed as None). This backtest scores on rsi + distance_from_sma +
volume_ratio only (max 75 of 100), not the full formula -- still
directly tests 3 of the 4 real factors, the ones doing most of the
work, just not sector strength.

USAGE -- run this against the REAL next_day_watchlist_raw.json this
project's own eod_scanner.py already builds, not synthetic data:

    cd backend
    python manage.py shell -c "from screener.next_day_predictive_backtest import run; run()"

Needs at least a few real days of scan history accumulated to say
anything meaningful -- a single day's scan alone won't have enough
"next day" outcomes yet to draw a real conclusion from.
"""
import json
import os

from .next_day_ranking import compute_score
from .index_tracker import compute_rsi, compute_sma

RAW_DATA_FILE = os.path.join(os.path.dirname(__file__), "next_day_watchlist_raw.json")
MIN_CANDLES_REQUIRED = 21  # 20 for SMA + 1 more for a volume-average baseline, same bar next_day_ranking.py itself uses


def _walk_forward_for_symbol(candles):
    """
    candles: list of {'date','open','high','low','close','volume'},
    oldest-first (same shape eod_scanner.py already produces). Yields
    (score, next_day_return_pct, breakdown) per valid day -- a day
    counts only if there's enough REAL history before it (>=21
    candles) AND a real next day after it to check the actual outcome
    against. Never fabricates a missing day's data.
    """
    closes = [c["close"] for c in candles]
    volumes = [c.get("volume") for c in candles]

    for i in range(MIN_CANDLES_REQUIRED, len(candles) - 1):
        closes_so_far = closes[:i + 1]  # only data up to and including day i -- no look-ahead, ever
        volumes_so_far = volumes[:i + 1]

        rsi = compute_rsi(closes_so_far, period=14)
        sma = compute_sma(closes_so_far, period=20)
        current_price = closes_so_far[-1]
        distance_from_sma_pct = round((current_price - sma) / sma * 100, 2) if sma else None

        today_volume = volumes_so_far[-1]
        vols_for_avg = [v for v in volumes_so_far[-21:-1] if v]
        avg_volume = round(sum(vols_for_avg) / len(vols_for_avg), 0) if len(vols_for_avg) >= 20 else None
        volume_ratio = round(today_volume / avg_volume, 2) if (today_volume and avg_volume) else None

        # sector_relative_pct intentionally None -- see module docstring's HONEST LIMITATION
        score, breakdown = compute_score(rsi, distance_from_sma_pct, volume_ratio, None)

        if current_price is None or current_price == 0:
            continue
        next_close = closes[i + 1]
        next_day_return_pct = round((next_close - current_price) / current_price * 100, 3)

        yield score, next_day_return_pct, breakdown


def run(raw_data=None, verbose=True):
    """
    raw_data: pass in directly for testing; defaults to reading the
    real file this project's own eod_scanner.py produces. Returns a
    results dict; also prints a real, readable summary if verbose.
    """
    if raw_data is None:
        if not os.path.exists(RAW_DATA_FILE):
            print(f"[Backtest] No raw data file found at {RAW_DATA_FILE} -- run a real EOD scan first (Run Scan Now on the Next Day tab), then come back to this.")
            return None
        with open(RAW_DATA_FILE, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

    all_points = []  # (score, next_day_return_pct)
    symbols_used = 0
    for symbol, entry in raw_data.items():
        candles = entry.get("daily_candles") or []
        if len(candles) < MIN_CANDLES_REQUIRED + 1:
            continue
        symbols_used += 1
        for score, ret, breakdown in _walk_forward_for_symbol(candles):
            all_points.append((score, ret))

    if not all_points:
        print("[Backtest] No valid (score, next-day-return) pairs yet -- not enough real history accumulated. Run a few more scans on different days and try again.")
        return None

    buckets = {"0-24": [], "25-49": [], "50-74": [], "75-100": []}
    for score, ret in all_points:
        if score < 25: buckets["0-24"].append(ret)
        elif score < 50: buckets["25-49"].append(ret)
        elif score < 75: buckets["50-74"].append(ret)
        else: buckets["75-100"].append(ret)

    summary = {}
    for label, rets in buckets.items():
        if not rets:
            summary[label] = None
            continue
        avg_ret = sum(rets) / len(rets)
        pct_positive = sum(1 for r in rets if r > 0) / len(rets) * 100
        summary[label] = {"n": len(rets), "avg_next_day_return_pct": round(avg_ret, 3), "pct_days_positive": round(pct_positive, 1)}

    if verbose:
        print(f"\n{'=' * 68}")
        print(f"NEXT-DAY PREDICTIVE BACKTEST -- {symbols_used} symbols, {len(all_points)} real (score, next-day-outcome) observations")
        print(f"{'=' * 68}")
        for label in ["0-24", "25-49", "50-74", "75-100"]:
            s = summary[label]
            if s is None:
                print(f"  Score {label:8s}: no observations")
            else:
                print(f"  Score {label:8s}: n={s['n']:6d}  avg next-day return={s['avg_next_day_return_pct']:+.3f}%   {s['pct_days_positive']:.1f}% of days closed higher")
        print(f"{'=' * 68}")
        print("If avg return / % positive climbs cleanly from '0-24' up to '75-100',")
        print("the current score genuinely predicts next-day continuation -- keep it,")
        print("maybe lean into it harder. If it's flat or inverted, a high score is NOT")
        print("a better bet for tomorrow specifically -- it may just mean today was")
        print("volatile, which is a real, different, useful thing to know before")
        print("trusting this list to pick tomorrow's trades.\n")

    return summary


if __name__ == "__main__":
    print("Run this via Django shell, not directly -- it needs the app package")
    print("context for its imports. From the backend/ folder:")
    print('  python manage.py shell -c "from screener.next_day_predictive_backtest import run; run()"')
