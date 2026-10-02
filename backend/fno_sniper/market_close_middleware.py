"""Freeze NSE live-market API responses after the 3:40 PM NSE close.

MCX commodities are deliberately exempt: their live session continues until
11:30 PM, so Crude Oil, Gold and Silver endpoints must keep polling during the
MCX session even after NSE has closed.
"""

import base64
import json
import os
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from django.http import HttpResponse, JsonResponse

from screener.market_hours import is_market_hours
from screener.index_tracker import is_mcx_hours


# Only endpoints that represent live/current market state are frozen.
# Historical exports, backtests, settings, news, and authentication-token
# endpoints remain normal after close.
LIVE_API_PREFIXES = (
    "/api/market-summary/",
    "/api/market-data/",
    "/api/stocks/fo-list/",
    "/api/ticker/",
    "/api/stock-detail/",
    "/api/fyers-status/",
    "/api/commodity-symbol/",
    "/api/index-tracker/",
    "/api/index-signals/",
    "/api/trend-momentum/",
    "/api/option-analytics/",
    "/api/signals/",
    "/api/sniper-only/",
    "/api/data-health/",
    "/api/broader-indices/",
    "/api/sector-stocks/",
    "/api/no-trade-log/",
)

# MCX contracts are allowed to remain live after the NSE 3:40 PM close.
# Keep the names aligned with index_tracker.COMMODITY_BASES so the exemption
# covers both standard and mini Crude/Gold/Silver modules.
MCX_COMMODITY_NAMES = (
    "CRUDEOIL",
    "CRUDEOILM",
    "GOLD",
    "GOLDM",
    "SILVER",
    "SILVERM",
)

_snapshot_lock = threading.Lock()
_snapshots = {}  # {path+query: {content, content_type, status, captured_at}}

# Keep this outside source control. It is only a last-known-market-state cache.
_SNAPSHOT_FILE = Path(__file__).resolve().parent.parent / "runtime" / "market_close_snapshots.json"


def _load_persisted_snapshots():
    """Load the last successful market responses after a process restart."""
    try:
        if not _SNAPSHOT_FILE.exists():
            return {}
        with _SNAPSHOT_FILE.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            return {}

        loaded = {}
        for key, snapshot in raw.items():
            if not isinstance(snapshot, dict):
                continue
            encoded = snapshot.get("content_b64")
            if not encoded:
                continue
            try:
                content = base64.b64decode(encoded.encode("ascii"), validate=True)
            except Exception:
                continue
            loaded[key] = {
                "content": content,
                "content_type": snapshot.get("content_type", "application/json"),
                "status": int(snapshot.get("status", 200)),
                "captured_at": snapshot.get("captured_at", "unknown"),
            }
        return loaded
    except Exception as exc:
        print(f"[MarketCloseFreeze] Could not load persisted snapshots: {exc}")
        return {}


def _persist_snapshots(snapshots):
    """Atomically persist all last-good responses so restart cannot erase them."""
    try:
        _SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {}
        for key, snapshot in snapshots.items():
            payload[key] = {
                "content_b64": base64.b64encode(snapshot["content"]).decode("ascii"),
                "content_type": snapshot["content_type"],
                "status": snapshot["status"],
                "captured_at": snapshot["captured_at"],
            }

        fd, tmp_name = tempfile.mkstemp(
            prefix="market_close_snapshots_",
            suffix=".tmp",
            dir=str(_SNAPSHOT_FILE.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, separators=(",", ":"))
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, _SNAPSHOT_FILE)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
    except Exception as exc:
        print(f"[MarketCloseFreeze] Could not persist snapshot: {exc}")


_snapshots = _load_persisted_snapshots()


def _is_freezable_live_endpoint(path):
    return any(path.startswith(prefix) for prefix in LIVE_API_PREFIXES)


def _is_mcx_endpoint(path):
    """Return True only for routes carrying an MCX commodity instrument."""
    if not (
        path.startswith("/api/index-tracker/")
        or path.startswith("/api/trend-momentum/")
        or path.startswith("/api/commodity-symbol/")
        or path.startswith("/api/option-analytics/")
    ):
        return False

    normalized = path.upper()
    return any(name in normalized for name in MCX_COMMODITY_NAMES)


def _snapshot_key(request):
    return request.get_full_path()


class MarketCloseFreezeMiddleware:
    """Freeze NSE live APIs after 3:40 PM, but never freeze MCX modules during MCX hours."""

    def __init__(self, get_response):
        self.get_response = get_response
        start_option_snapshot_worker(self)

    def __call__(self, request):
        path = request.path
        if request.method != "GET" or not _is_freezable_live_endpoint(path):
            return self.get_response(request)

        # MCX has its own 09:00-23:30 session. It must bypass the NSE close
        # freezer completely while MCX is open. Outside MCX hours the normal
        # response path is allowed; no NSE snapshot is substituted for MCX.
        if _is_mcx_endpoint(path):
            return self.get_response(request)

        now = datetime.now()
        live = is_market_hours(now)
        key = _snapshot_key(request)

        if not live:
            with _snapshot_lock:
                snapshot = _snapshots.get(key)
                if snapshot:
                    response = HttpResponse(
                        snapshot["content"],
                        status=snapshot["status"],
                        content_type=snapshot["content_type"],
                    )
                    response["X-Market-Data-Frozen"] = "1"
                    response["X-Market-Data-Snapshot"] = snapshot["captured_at"]
                    return response

            response = JsonResponse(
                {
                    "error": "market_closed_no_snapshot",
                    "message": "Market is closed and no live snapshot is available.",
                },
                status=503,
            )
            response["X-Market-Data-Frozen"] = "1"
            return response

        response = self.get_response(request)

        if response.status_code == 200 and not getattr(response, "streaming", False):
            try:
                content = bytes(response.content)
                if not content:
                    return response
                content_type = response.get("Content-Type", "application/json")
                # A 200 whose body says {"live": false, "error": ...} is a failed fetch (Fyers logged out,
                # no chain yet), not market state: never let it replace a good last-session snapshot.
                if path.startswith("/api/option-analytics/") and (b'"live":false' in content or b'"live": false' in content):
                    return response
                snapshot = {
                    "content": content,
                    "content_type": content_type,
                    "status": response.status_code,
                    "captured_at": now.isoformat(timespec="seconds"),
                }
                with _snapshot_lock:
                    _snapshots[key] = snapshot
                    _persist_snapshots(_snapshots)
                response["X-Market-Data-Frozen"] = "0"
            except Exception:
                pass

        return response


# ---------------------------------------------------------------------------
# Option-chain snapshot keeper
# ---------------------------------------------------------------------------
# After the close, /api/option-analytics/* is replayed from the last snapshot captured while the market
# was live -- but a snapshot is only captured when somebody OPENS that view live. Open OI Distribution on
# Tuesday, skip it on Wednesday/Thursday, and on Friday evening it replays Tuesday's chain (already
# expired, a different spot from the closing figures on the dashboard cards). This worker requests the
# index chains itself while the market is open so the replayed snapshot is always the last session's.
_OPTION_INDICES = ("NIFTY", "BANKNIFTY", "SENSEX")
_OPTION_NEAREST_EVERY_S = 300        # nearest expiry: every 5 minutes
_OPTION_OTHER_EVERY_S = 1800         # next / monthly expiry: every 30 minutes (each needs an extra probe call)
_worker_started = False


def _snapshot_option_chains(middleware, include_other, now=None):
    from django.test import RequestFactory
    factory = RequestFactory()
    paths = [f"/api/option-analytics/{name}/" for name in _OPTION_INDICES]
    if include_other:
        paths += [f"/api/option-analytics/{name}/?expiry={e}" for name in _OPTION_INDICES for e in ("next", "monthly")]
    for path in paths:
        try:
            request = factory.get(path)
            request.session = {}      # SessionMiddleware sits upstream of us and is skipped here; anonymous is fine
            middleware(request)
        except Exception as exc:
            print(f"[MarketCloseFreeze] option snapshot {path} failed: {exc}")
        time.sleep(1.5)   # stay well inside Fyers' rate limits


def _option_snapshot_loop(middleware):
    last_nearest = last_other = 0.0
    while True:
        try:
            if is_market_hours(datetime.now()):
                t = time.time()
                if t - last_nearest >= _OPTION_NEAREST_EVERY_S:
                    other = t - last_other >= _OPTION_OTHER_EVERY_S
                    _snapshot_option_chains(middleware, other)
                    last_nearest = time.time()
                    if other:
                        last_other = last_nearest
        except Exception as exc:
            print(f"[MarketCloseFreeze] option snapshot loop error: {exc}")
        time.sleep(30)


def start_option_snapshot_worker(middleware):
    """One daemon thread per process; off under tests or with OPTION_SNAPSHOT_WORKER=0."""
    global _worker_started
    if _worker_started or os.environ.get("OPTION_SNAPSHOT_WORKER", "1") == "0" or "test" in sys.argv:
        return
    _worker_started = True
    threading.Thread(target=_option_snapshot_loop, args=(middleware,), daemon=True, name="option-snapshot-keeper").start()
