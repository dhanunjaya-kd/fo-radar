"""
screener/futures_oi.py

Sep 9 2026: stock-level Futures OI confirmation. Reuses two pieces of
EXISTING, already-working infrastructure verbatim rather than building
anything parallel:

1. lot_size_resolver.get_futures_symbol() -- the real, live, near-
   month Fyers futures ticker for an underlying, from the same daily-
   cached symbol-master table get_lot_size() already maintains. Not a
   second contract resolver.

2. The EXACT depth-response parsing already proven in
   index_tracker.py's snapshot_index() for NIFTY/BANKNIFTY futures:
   get_market_depth(fut_symbol) -> depth_resp["d"][fut_symbol] ->
   .get("ltp")/.get("oi")/.get("oipercent"). Copied verbatim (same
   field names, same nesting, same s=="ok" check) rather than
   reimplemented, so any future depth-response quirk fixed in one
   place doesn't silently stay broken in the other.

Short in-memory cache (default 3 minutes) during active market hours
-- OI genuinely moves through the day, unlike lot size, so a once-
daily cache would go stale; but re-fetching on every single candidate
evaluation within the same ~90s scan cycle would multiply real Fyers
calls for no new information. Per spec's own explicit warning: "Do
not repeatedly request identical data during the same scan."

futures_oi_status is always explicitly 'AVAILABLE' or 'UNAVAILABLE' --
never silently substitutes 0 for a real OI value that couldn't be
fetched (0 and 'no data' mean very different things for OI structure
classification; conflating them would be exactly the kind of missing-
data-becomes-a-number bug this whole project has been careful to avoid
everywhere else).
"""
import time
import threading

CACHE_TTL_SECONDS = 180  # 3 minutes -- short enough to stay fresh intraday, long enough to survive several scan cycles without a duplicate call

_cache_lock = threading.Lock()
_futures_oi_cache = {}  # {underlying: {'data': {...}, 'fetched_at': monotonic_time}}


def get_stock_futures_oi(underlying_symbol, force_refresh=False):
    """
    Real futures price + OI + OI-change-% for `underlying_symbol`
    (e.g. "WIPRO"), via the SAME get_market_depth() gateway and field
    parsing index_tracker.py already uses for index futures. Cached
    up to CACHE_TTL_SECONDS -- a second call for the same underlying
    within that window returns the cached result with zero new Fyers
    traffic.

    Returns {'status': 'AVAILABLE', 'symbol', 'price', 'oi',
    'oi_chg_pct'} on success, or {'status': 'UNAVAILABLE', 'reason'}
    on any failure (unresolvable futures symbol, depth call failure,
    missing fields) -- callers must treat UNAVAILABLE as genuinely
    unknown, never substitute 0 for oi/oi_chg_pct.
    """
    key = underlying_symbol.strip().upper()
    now = time.monotonic()

    with _cache_lock:
        cached = _futures_oi_cache.get(key)
        if not force_refresh and cached and (now - cached["fetched_at"]) < CACHE_TTL_SECONDS:
            return cached["data"]

    from .lot_size_resolver import get_futures_symbol
    from .fyers_client import get_market_depth

    fut_symbol = get_futures_symbol(key)
    if not fut_symbol:
        result = {"status": "UNAVAILABLE", "reason": f"No resolvable futures contract for {key}"}
        with _cache_lock:
            _futures_oi_cache[key] = {"data": result, "fetched_at": now}
        return result

    try:
        depth_resp = get_market_depth(fut_symbol)
    except Exception as e:
        result = {"status": "UNAVAILABLE", "reason": f"Depth fetch error: {e}"}
        with _cache_lock:
            _futures_oi_cache[key] = {"data": result, "fetched_at": now}
        return result

    if not depth_resp or depth_resp.get("s") != "ok":
        result = {"status": "UNAVAILABLE", "reason": "Depth response not ok"}
        with _cache_lock:
            _futures_oi_cache[key] = {"data": result, "fetched_at": now}
        return result

    # Verbatim field extraction from index_tracker.py's snapshot_index()
    # -- same nesting (depth_resp["d"][fut_symbol]), same three field
    # names (ltp/oi/oipercent), same "None if missing" behavior.
    fut_data = (depth_resp.get("d", {}) or {}).get(fut_symbol, {})
    price = fut_data.get("ltp")
    oi = fut_data.get("oi")
    oi_chg_pct = fut_data.get("oipercent")

    if price is None or oi is None or oi_chg_pct is None:
        result = {"status": "UNAVAILABLE", "reason": "Depth response missing ltp/oi/oipercent"}
    else:
        result = {"status": "AVAILABLE", "symbol": fut_symbol, "price": price, "oi": oi, "oi_chg_pct": oi_chg_pct}

    with _cache_lock:
        _futures_oi_cache[key] = {"data": result, "fetched_at": now}
    return result
