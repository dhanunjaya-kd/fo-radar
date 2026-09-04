"""Freeze live-market API responses after the 3:40 PM NSE close.

During the session, selected live endpoints execute normally and their last
successful 200 response is kept both in memory and in a small local runtime
snapshot. After the NSE derivatives close, those endpoints are short-circuited
before the view runs and the last successful response is replayed.

The important part is that the closing snapshot survives a Django restart.
The previous implementation kept it only in process memory, so restarting the
server after the close caused every endpoint to return ``market_closed_no_snapshot``
even though the user had already collected valid closing values earlier that
day. That is exactly the failure mode this middleware is intended to prevent.

The snapshot is deliberately runtime state, not source-controlled trading
history. It is replaced by the first successful live response of the next
session. Browser polling after close therefore remains safe: it can replay the
last known values but cannot trigger fresh Fyers calls.
"""

import base64
import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from django.http import HttpResponse, JsonResponse

from screener.market_hours import is_market_hours


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
        # Snapshot persistence is a safety layer. Never break a healthy live
        # response merely because the local runtime file cannot be written.
        print(f"[MarketCloseFreeze] Could not persist snapshot: {exc}")


# Load once at process startup. A server restart after close can now replay the
# closing values captured by the previous process.
_snapshots = _load_persisted_snapshots()


def _is_freezable_live_endpoint(path):
    return any(path.startswith(prefix) for prefix in LIVE_API_PREFIXES)


def _snapshot_key(request):
    # Keep query parameters because some live endpoints use them to select
    # an instrument/variant. Never share one instrument's response with
    # another merely because both use the same endpoint prefix.
    return request.get_full_path()


class MarketCloseFreezeMiddleware:
    """Replay the last good live API response after the 3:40 PM close."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if request.method != "GET" or not _is_freezable_live_endpoint(path):
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

            # No closing snapshot exists anywhere this server can access. Do
            # not call the view because that could pull fresh Fyers data after
            # close. Return an explicit unavailable response instead of
            # fabricating zeros or stale values from an unrelated endpoint.
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

        # Only cache successful, non-streaming responses. A transient 500,
        # 503, or empty response must never replace a previously good
        # closing snapshot.
        if response.status_code == 200 and not getattr(response, "streaming", False):
            try:
                content = bytes(response.content)
                if not content:
                    return response
                content_type = response.get("Content-Type", "application/json")
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
                # Snapshotting is a safety layer; never break a healthy live
                # response merely because the local snapshot write failed.
                pass

        return response
