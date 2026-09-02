"""
backend/eod_scanner.py

Full-NSE-universe End-of-Day scan, feeding the Next Day Watchlist --
100% Fyers-sourced (symbol universe via nse_universe.py, price/volume/
history via fyers_client.py), NOT Screener.in, matching this project's
foundational Fyers-only rule.

RATE LIMIT SAFETY -- the single most important thing about this file,
given this project's own real, documented Aug 20 2026 incident (a
FULL-DAY account lockout after tripping Fyers' per-minute limit just 3
times). Real, current Fyers V3 limits, confirmed via Fyers' own
community docs, not guessed: ~10 requests/second, ~200/minute,
~100,000/day. History API calls count toward these same limits, one
request per symbol -- no batch-history capability exists (confirmed by
a Fyers team reply, not assumed). Deliberately paced at roughly HALF
the documented per-minute ceiling, and hard-stops immediately -- not
just logs and continues -- on any real rate-limit response, saving
whatever progress exists rather than continuing to hammer a service
that has already said stop.

Quotes (today's price/volume/change%) DO batch -- up to 50 symbols/
call, same limit excel_logger.py's get_quotes() already uses -- used
here for that portion, cutting ~2000 individual calls to ~40.

History (daily candles, needed for RSI/SMA/volume-average) does NOT
batch -- the real bottleneck, paced conservatively below.

RESUMABLE, same pattern as runner.py: saves progress incrementally,
skips symbols already freshly scanned today on a re-run rather than
re-fetching everything from zero.
"""
import json
import os
import time
from datetime import datetime, timedelta

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "next_day_watchlist_raw.json")

# Roughly HALF Fyers' documented ~200/min ceiling -- a deliberate
# safety margin, not the theoretical max. Adjust down further, never
# up, if a real run shows any sign of trouble.
HISTORY_CALLS_PER_MINUTE = 90
PAUSE_BETWEEN_HISTORY_CALLS = 60.0 / HISTORY_CALLS_PER_MINUTE
QUOTE_BATCH_SIZE = 50
SAVE_PROGRESS_EVERY = 50


class RateLimitStop(Exception):
    """Raised the moment Fyers signals a real rate-limit hit. Caught
    once, at the top of run() -- stop immediately, save progress,
    never retry-and-hope within the same run."""
    pass


def _is_rate_limit_response(resp):
    """Matches BOTH documented Fyers 429 error shapes -- 'quota_exceeded'
    (daily) and 'throttled' (per-second/minute) -- checked directly
    against Fyers' own documented error_key values, not guessed at."""
    if not resp:
        return False
    code = resp.get("code")
    error_key = str(resp.get("error_key", "")).lower()
    message = str(resp.get("message", "")).lower()
    return code == 429 or "throttled" in error_key or "quota_exceeded" in error_key or "limit" in message


def load_existing():
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(data):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def is_stale(entry, max_age_hours=20):
    """Same is_stale() concept runner.py already uses, just a much
    shorter window -- this is a DAILY EOD scan, not a weekly
    fundamentals refresh, so "already done today" is the bar, not
    "done within the last 7 days"."""
    fetched_at = entry.get("fetched_at")
    if not fetched_at:
        return True
    try:
        fetched_dt = datetime.fromisoformat(fetched_at)
    except (ValueError, TypeError):
        return True
    return (datetime.now() - fetched_dt) > timedelta(hours=max_age_hours)


def fetch_quotes_batched(symbols, get_quotes_fn):
    """Today's price/change%/volume for every symbol, batched 50-at-a-
    time. Returns {symbol: {'price','change_percent','volume'}} --
    entries missing from the response are simply absent, never
    guessed at. Raises RateLimitStop immediately if Fyers signals a
    real limit hit on any batch."""
    result = {}
    for i in range(0, len(symbols), QUOTE_BATCH_SIZE):
        batch = symbols[i:i + QUOTE_BATCH_SIZE]
        resp = get_quotes_fn(batch)
        if _is_rate_limit_response(resp):
            raise RateLimitStop(f"Rate limit hit on quotes batch starting at index {i}: {resp}")
        if not resp or resp.get("s") != "ok":
            continue  # this batch failed for a non-rate-limit reason -- skip it, don't guess its contents
        for item in resp.get("d", []):
            if item.get("s") != "ok":
                continue
            v = item.get("v", {}) or {}
            result[item.get("n")] = {
                "price": v.get("lp"),
                "change_percent": v.get("chp"),
                "volume": v.get("volume"),
            }
    return result


def fetch_daily_history_paced(symbols, get_history_fn, days_back=30):
    """The real bottleneck -- one History API call per symbol, no
    batching exists. Paced at PAUSE_BETWEEN_HISTORY_CALLS between every
    single call, evenly spread rather than bursty-then-idle. Raises
    RateLimitStop immediately on the first real rate-limit response --
    does not try to push through a few more before giving up."""
    result = {}
    range_to = datetime.now().strftime("%Y-%m-%d")
    range_from = (datetime.now() - timedelta(days=days_back * 2)).strftime("%Y-%m-%d")

    for symbol in symbols:
        try:
            resp = get_history_fn(symbol, resolution="1D", range_from=range_from, range_to=range_to)
        except Exception as e:
            print(f"[EODScanner] {symbol}: history fetch raised {e}")
            time.sleep(PAUSE_BETWEEN_HISTORY_CALLS)
            continue

        if _is_rate_limit_response(resp):
            raise RateLimitStop(f"Rate limit hit fetching history for {symbol}: {resp}")

        if resp and resp.get("s") == "ok":
            candles = []
            for c in resp.get("candles", []):
                if len(c) < 6:
                    continue
                candles.append({
                    "date": datetime.fromtimestamp(c[0]).strftime("%Y-%m-%d"),
                    "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5],
                })
            candles.sort(key=lambda x: x["date"])
            result[symbol] = candles

        time.sleep(PAUSE_BETWEEN_HISTORY_CALLS)

    return result


def run(get_quotes_fn, get_history_fn, symbols=None, limit=None):
    """
    Main entry point. get_quotes_fn/get_history_fn: injected, same
    reasoning as runner.py/check_outcomes() elsewhere in this project
    -- keeps this testable with fakes, no import-time Fyers dependency.

    symbols: pass in explicitly to test with a small list; defaults to
    the real full NSE universe via nse_universe.get_all_nse_equity_symbols().
    limit: same "test small first" pattern as runner.py's own CLI arg.

    Returns (raw_data, stopped_early). stopped_early=True means a real
    rate limit was hit -- whatever's in raw_data is genuine progress,
    already saved, safe to resume from later, not a failure to discard.
    """
    if symbols is None:
        from .nse_universe import get_all_nse_equity_symbols
        symbols = get_all_nse_equity_symbols()
        if not symbols:
            print("[EODScanner] Could not fetch the NSE symbol universe -- aborting.")
            return {}, False

    if limit:
        symbols = symbols[:limit]
        print(f"[EODScanner] TEST RUN -- limited to {limit} symbols.")

    existing = load_existing()
    to_scan = [s for s in symbols if s not in existing or is_stale(existing[s])]
    print(f"[EODScanner] {len(symbols)} total symbols, {len(to_scan)} need scanning "
          f"({len(symbols) - len(to_scan)} already fresh from earlier today).")

    if not to_scan:
        return existing, False

    stopped_early = False
    try:
        print(f"[EODScanner] Fetching quotes for {len(to_scan)} symbols (batched, {QUOTE_BATCH_SIZE}/call)...")
        quotes = fetch_quotes_batched(to_scan, get_quotes_fn)
        print(f"[EODScanner] Got quotes for {len(quotes)}/{len(to_scan)}. Fetching daily history "
              f"(paced, ~{HISTORY_CALLS_PER_MINUTE}/min, ~{len(to_scan) / HISTORY_CALLS_PER_MINUTE:.0f} min estimated)...")

        # History is the slow part -- save progress incrementally as it
        # goes, not just once at the very end, matching runner.py's own
        # resumability pattern.
        history_by_symbol = {}
        range_to = datetime.now().strftime("%Y-%m-%d")
        for idx, symbol in enumerate(to_scan):
            batch_result = fetch_daily_history_paced([symbol], get_history_fn)
            if symbol in batch_result:
                history_by_symbol[symbol] = batch_result[symbol]
                existing[symbol] = {
                    "quote": quotes.get(symbol),
                    "daily_candles": batch_result[symbol],
                    "fetched_at": datetime.now().isoformat(),
                }
            if (idx + 1) % SAVE_PROGRESS_EVERY == 0:
                save_progress(existing)
                print(f"[EODScanner]   -- progress saved ({idx + 1}/{len(to_scan)})")

    except RateLimitStop as e:
        print(f"\n{'=' * 70}\n[EODScanner] STOPPING -- real rate limit hit: {e}\n{'=' * 70}")
        stopped_early = True

    save_progress(existing)
    print(f"[EODScanner] Done this pass. {len(existing)} total symbols now in {OUTPUT_FILE}.")
    return existing, stopped_early


if __name__ == "__main__":
    import sys
    from .fyers_client import get_quotes, get_history
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(get_quotes, get_history, limit=limit)
