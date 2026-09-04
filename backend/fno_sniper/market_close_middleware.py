"""Freeze live-market API responses after the 3:40 PM NSE close.

During the session, selected live endpoints are allowed to execute normally
and their last successful 200 response is kept in process memory. After the
NSE derivatives close, those endpoints are short-circuited before the view
runs and the last successful response is replayed. This keeps the UI stable
instead of turning good closing values into zeros/N/A while also preventing
browser polling from causing fresh Fyers calls after close.

The snapshot remains available through the overnight closed period and is
replaced automatically by the first successful live response of the next
session. It is deliberately not dated: a closing snapshot is the correct
"last traded/last known" state before the next market opens. The background
scanner has its own market-hours gate; this middleware is the HTTP-side
safety net for browser polling.
"""

import threading
from datetime import datetime

from django.http import HttpResponse, JsonResponse

from screener.market_hours import is_market_hours


# Only endpoints that represent live/current market state are frozen.
# Historical exports, backtests, settings, and authentication endpoints
# must remain normal after close.
LIVE_API_PREFIXES = (
    "/api/market-summary/",
    "/api/commodity-symbol/",
    "/api/index-tracker/",
    "/api/signals/",
    "/api/sniper-only/",
    "/api/option-analytics/",
    "/api/trend-momentum/",
    "/api/data-health/",
    "/api/market-data/",
    "/api/sector-stocks/",
)

_snapshot_lock = threading.Lock()
_snapshots = {}  # {path+query: {content, content_type, status, captured_at}}


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

            # No closing snapshot exists in this process. Do not call the
            # view because that could pull fresh Fyers data after close.
            # Return an explicit unavailable response instead of fabricating
            # zeros or stale values from an unrelated session.
            response = JsonResponse(
                {
                    "error": "market_closed_no_snapshot",
                    "message": "Market is closed and no live snapshot is available in this process.",
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
                content_type = response.get("Content-Type", "application/json")
                with _snapshot_lock:
                    _snapshots[key] = {
                        "content": content,
                        "content_type": content_type,
                        "status": response.status_code,
                        "captured_at": now.isoformat(timespec="seconds"),
                    }
                response["X-Market-Data-Frozen"] = "0"
            except Exception:
                # Snapshotting is a safety layer; never break a healthy live
                # response merely because the local snapshot write failed.
                pass

        return response
