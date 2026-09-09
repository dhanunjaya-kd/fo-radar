"""
backend/screener/eod_scanner.py

Full-NSE-universe End-of-Day scan, feeding the Next Day Watchlist --
100% Fyers-sourced. Progress is saved incrementally and partial rankings
are published during the scan so the UI can show genuine scanned stocks
without waiting for the full universe to finish.
"""
import json
import os
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

CALL_TIMEOUT_SECONDS = 30
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "next_day_watchlist_raw.json")
_scan_progress = {"scanned": 0, "total": 0, "current_symbol": None}

def get_scan_progress():
    return dict(_scan_progress)

def _reset_scan_progress(total):
    _scan_progress["scanned"] = 0
    _scan_progress["total"] = total
    _scan_progress["current_symbol"] = None

def _advance_scan_progress(symbol):
    _scan_progress["scanned"] += 1
    _scan_progress["current_symbol"] = symbol

HISTORY_CALLS_PER_MINUTE = 90
PAUSE_BETWEEN_HISTORY_CALLS = 60.0 / HISTORY_CALLS_PER_MINUTE
QUOTE_BATCH_SIZE = 50
SAVE_PROGRESS_EVERY = 50

class CallTimedOut(Exception):
    pass

def _call_with_timeout(fn, *args, **kwargs):
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn, *args, **kwargs)
    try:
        result = future.result(timeout=CALL_TIMEOUT_SECONDS)
        executor.shutdown(wait=False)
        return result
    except FuturesTimeoutError:
        executor.shutdown(wait=False)
        raise CallTimedOut(f"{getattr(fn, '__name__', fn)} did not return within {CALL_TIMEOUT_SECONDS}s")

class RateLimitStop(Exception):
    pass

def _is_rate_limit_response(resp):
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
    fetched_at = entry.get("fetched_at")
    if not fetched_at:
        return True
    try:
        fetched_dt = datetime.fromisoformat(fetched_at)
    except (ValueError, TypeError):
        return True
    return (datetime.now() - fetched_dt) > timedelta(hours=max_age_hours)

def fetch_quotes_batched(symbols, get_quotes_fn):
    result = {}
    for i in range(0, len(symbols), QUOTE_BATCH_SIZE):
        batch = symbols[i:i + QUOTE_BATCH_SIZE]
        try:
            resp = _call_with_timeout(get_quotes_fn, batch)
        except CallTimedOut as e:
            print(f"[EODScanner] Quotes batch at index {i} timed out ({e}) -- skipped, continuing.")
            continue
        if _is_rate_limit_response(resp):
            raise RateLimitStop(f"Rate limit hit on quotes batch starting at index {i}: {resp}")
        if not resp or resp.get("s") != "ok":
            continue
        for item in resp.get("d", []):
            if item.get("s") != "ok":
                continue
            v = item.get("v", {}) or {}
            result[item.get("n")] = {"price": v.get("lp"), "change_percent": v.get("chp"), "volume": v.get("volume")}
        time.sleep(PAUSE_BETWEEN_HISTORY_CALLS)
    return result

def fetch_daily_history_paced(symbols, get_history_fn, days_back=30):
    result = {}
    range_to = datetime.now().strftime("%Y-%m-%d")
    range_from = (datetime.now() - timedelta(days=days_back * 2)).strftime("%Y-%m-%d")
    for symbol in symbols:
        try:
            resp = _call_with_timeout(get_history_fn, symbol, resolution="1D", range_from=range_from, range_to=range_to)
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
                candles.append({"date": datetime.fromtimestamp(c[0]).strftime("%Y-%m-%d"), "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]})
            candles.sort(key=lambda x: x["date"])
            result[symbol] = candles
        time.sleep(PAUSE_BETWEEN_HISTORY_CALLS)
    return result

def _publish_partial_ranking(raw_data):
    """Publish genuine partial results without writing the Excel ledger."""
    try:
        from .next_day_ranking import build_watchlist
        from .views import SECTORS
        ranked, universe, with_data = build_watchlist(sectors_map=SECTORS, raw_data=raw_data, persist_backtest=False)
        print(f"[EODScanner] Partial ranking published: {len(ranked)} picks from {universe} scanned / {with_data} eligible.")
    except Exception as e:
        print(f"[EODScanner] Partial ranking publish skipped: {e}")

def run(get_quotes_fn, get_history_fn, symbols=None, limit=None):
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
    print(f"[EODScanner] {len(symbols)} total symbols, {len(to_scan)} need scanning ({len(symbols) - len(to_scan)} already fresh from earlier today).")
    if not to_scan:
        return existing, False

    _reset_scan_progress(len(to_scan))
    stopped_early = False
    try:
        print(f"[EODScanner] Fetching quotes for {len(to_scan)} symbols (batched, {QUOTE_BATCH_SIZE}/call)...")
        quotes = fetch_quotes_batched(to_scan, get_quotes_fn)
        # Publish as soon as the fresh quote phase completes. Existing daily
        # candles are still genuine historical data, while price/volume/change
        # are already fresh for this scan. History refresh then progressively
        # replaces the old candles and republishes the ranking below.
        fresh_quote_count = 0
        for symbol, quote in quotes.items():
            if symbol in existing:
                existing[symbol]["quote"] = quote
                fresh_quote_count += 1
        if fresh_quote_count:
            save_progress(existing)
            _publish_partial_ranking(existing)
            print(f"[EODScanner] Initial live preview published using {fresh_quote_count} fresh quotes.")
        print(f"[EODScanner] Got quotes for {len(quotes)}/{len(to_scan)}. Fetching daily history (paced, ~{HISTORY_CALLS_PER_MINUTE}/min, ~{len(to_scan) / HISTORY_CALLS_PER_MINUTE:.0f} min estimated)...")

        for idx, symbol in enumerate(to_scan):
            batch_result = fetch_daily_history_paced([symbol], get_history_fn)
            if symbol in batch_result:
                existing[symbol] = {"quote": quotes.get(symbol), "daily_candles": batch_result[symbol], "fetched_at": datetime.now().isoformat()}
            _advance_scan_progress(symbol)
            if (idx + 1) % SAVE_PROGRESS_EVERY == 0:
                save_progress(existing)
                _publish_partial_ranking(existing)
                print(f"[EODScanner]   -- progress saved ({idx + 1}/{len(to_scan)})")
    except RateLimitStop as e:
        print(f"\n{'=' * 70}\n[EODScanner] STOPPING -- real rate limit hit: {e}\n{'=' * 70}")
        stopped_early = True

    save_progress(existing)
    _publish_partial_ranking(existing)
    print(f"[EODScanner] Done this pass. {len(existing)} total symbols now in {OUTPUT_FILE}.")
    return existing, stopped_early

if __name__ == "__main__":
    import sys
    from .fyers_client import get_quotes, get_history
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(get_quotes, get_history, limit=limit)
