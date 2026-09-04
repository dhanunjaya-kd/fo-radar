"""
Fyers API v3 Client Wrapper.

This module is the single gateway used by the live scanner for Fyers calls.
It deliberately contains transport/reliability controls only; it must not
change Sniper scoring or signal-selection logic.
"""
import os
import time
import threading
from datetime import datetime

from fyers_apiv3 import fyersModel

try:
    from django.conf import settings as _django_settings
    CLIENT_ID = _django_settings.FYERS_APP_ID
except Exception:
    CLIENT_ID = os.environ.get("FYERS_APP_ID", "")

BACKEND_DIR = os.path.dirname(os.path.dirname(__file__))
TOKEN_PATH = os.path.join(BACKEND_DIR, "fyers_access_token.txt")
TOKEN_JSON_PATH = os.path.join(BACKEND_DIR, "fyers_auth.json")


def get_access_token():
    """Read the newest saved Fyers token from either supported token file."""
    import json as _json

    candidates = []
    if os.path.exists(TOKEN_PATH):
        candidates.append((os.path.getmtime(TOKEN_PATH), TOKEN_PATH, "txt"))
    if os.path.exists(TOKEN_JSON_PATH):
        candidates.append((os.path.getmtime(TOKEN_JSON_PATH), TOKEN_JSON_PATH, "json"))

    if not candidates:
        raise FileNotFoundError(
            f"No saved Fyers token found. Looked for:\n  {TOKEN_PATH}\n  {TOKEN_JSON_PATH}\n"
            "Run get_fyers_token.py to log in and save one."
        )

    _, path, fmt = max(candidates)
    if fmt == "txt":
        with open(path, "r") as f:
            return f.read().strip()
    with open(path, "r") as f:
        return _json.load(f)["access_token"].strip()


def get_fyers_client():
    """Return the authenticated Fyers v3 SDK client."""
    return fyersModel.FyersModel(
        client_id=CLIENT_ID,
        token=get_access_token(),
        is_async=False,
    )


# ---------------------------------------------------------------------------
# Authentication cache
# ---------------------------------------------------------------------------
# Do not repeatedly hit /profile from every scanner component. Successful
# authentication is cached for 30s. A failed check is cached only briefly so
# a transient failure cannot suppress the whole scanner for 30 seconds.
_auth_cache = {"value": None, "checked_at": 0.0}
_AUTH_SUCCESS_TTL = 30.0
_AUTH_FAILURE_TTL = 5.0


# ---------------------------------------------------------------------------
# Shared Fyers request governor + rate-limit circuit breaker
# ---------------------------------------------------------------------------
# Fyers Standard permits 10 requests/sec and 200 requests/min. The minute
# limit is the tighter constraint for a scanner making many calls, so the
# gateway deliberately spaces real requests by at least 0.32s. That caps a
# single process at ~187 requests/min even if several scanner threads call the
# SDK concurrently. The lock is held while sleeping AND while the SDK call is
# running, so concurrent threads cannot burst around the limiter.
_REQUEST_MIN_INTERVAL = 0.32
_request_lock = threading.Lock()
_last_request_at = 0.0

_rate_limit_state = {
    "consecutive_429s": 0,
    "blocked_until": 0.0,
    "cooldown_seconds": 60.0,
}
_RATE_LIMIT_TRIP_THRESHOLD = 2
_RATE_LIMIT_MAX_COOLDOWN = 300.0


def _rate_limited_now():
    return time.monotonic() < _rate_limit_state["blocked_until"]


def _is_429(resp):
    try:
        return int(resp.get("code")) == 429
    except (AttributeError, TypeError, ValueError):
        return False


def _note_429():
    _rate_limit_state["consecutive_429s"] += 1
    if _rate_limit_state["consecutive_429s"] >= _RATE_LIMIT_TRIP_THRESHOLD:
        cooldown = min(
            _rate_limit_state["cooldown_seconds"],
            _RATE_LIMIT_MAX_COOLDOWN,
        )
        _rate_limit_state["blocked_until"] = time.monotonic() + cooldown
        print(
            "[Fyers] Rate-limit circuit breaker TRIPPED -- "
            f"backing off {int(cooldown)}s "
            f"(consecutive 429s: {_rate_limit_state['consecutive_429s']})"
        )
        _rate_limit_state["cooldown_seconds"] = min(
            cooldown * 2, _RATE_LIMIT_MAX_COOLDOWN
        )


def _note_success():
    if _rate_limit_state["consecutive_429s"] or _rate_limit_state["blocked_until"]:
        print("[Fyers] Rate-limit circuit breaker reset -- real response received.")
    _rate_limit_state["consecutive_429s"] = 0
    _rate_limit_state["blocked_until"] = 0.0
    _rate_limit_state["cooldown_seconds"] = 60.0


def _call(method, label, *args, **kwargs):
    """Execute one Fyers SDK request through the shared transport governor.

    Returns None when the breaker is open or the SDK raises. No retry is done
    here: retries would multiply traffic and make a rate-limit incident worse.
    """
    global _last_request_at

    if _rate_limited_now():
        print(f"[Fyers] {label}: circuit breaker open -- skipping real call.")
        return None

    with _request_lock:
        # Re-check after waiting for another thread; another request may have
        # tripped the breaker while this thread was queued.
        if _rate_limited_now():
            print(f"[Fyers] {label}: circuit breaker open -- skipping real call.")
            return None

        now = time.monotonic()
        wait = _REQUEST_MIN_INTERVAL - (now - _last_request_at)
        if wait > 0:
            time.sleep(wait)

        if _rate_limited_now():
            print(f"[Fyers] {label}: circuit breaker open -- skipping real call.")
            return None

        try:
            _last_request_at = time.monotonic()
            resp = method(*args, **kwargs)
        except Exception as exc:
            print(f"[Fyers] {label} error: {exc}")
            return None

        if _is_429(resp):
            _note_429()
        else:
            _note_success()
        return resp


def is_authenticated():
    """Check the current token, with a short-lived result cache."""
    now = time.monotonic()
    cached = _auth_cache["value"]
    age = now - _auth_cache["checked_at"]
    ttl = _AUTH_SUCCESS_TTL if cached is True else _AUTH_FAILURE_TTL
    if cached is not None and age < ttl:
        return cached

    try:
        fyers = get_fyers_client()
        resp = _call(fyers.get_profile, "Profile")
        if resp is None:
            result = False
        else:
            result = resp.get("s") == "ok"
            if not result:
                print(f"[Fyers] is_authenticated(): profile check returned not-ok: {resp}")
    except Exception as exc:
        print(f"[Fyers] is_authenticated(): profile setup failed: {exc}")
        result = False

    _auth_cache["value"] = result
    _auth_cache["checked_at"] = now
    return result


def get_quotes(symbols):
    """Fetch quotes. Returns None when Fyers is unavailable."""
    try:
        fyers = get_fyers_client()
        return _call(fyers.quotes, "Quotes", {"symbols": ",".join(symbols)})
    except Exception as exc:
        print(f"[Fyers] Quote setup error: {exc}")
        return None


def get_history(symbol, resolution="1D", range_from=None, range_to=None):
    """Fetch historical candles. Returns None when unavailable."""
    try:
        fyers = get_fyers_client()
        data = {
            "symbol": symbol,
            "resolution": resolution,
            "date_format": "1",
            "range_from": range_from,
            "range_to": range_to,
            "cont_flag": "1",
        }
        return _call(fyers.history, f"History({symbol})", data)
    except Exception as exc:
        print(f"[Fyers] History setup error for {symbol}: {exc}")
        return None


def get_market_depth(symbol):
    """Fetch market depth. Returns None when unavailable."""
    try:
        fyers = get_fyers_client()
        return _call(
            fyers.depth,
            f"Depth({symbol})",
            {"symbol": symbol, "ohlcv_flag": "1"},
        )
    except Exception as exc:
        print(f"[Fyers] Depth setup error for {symbol}: {exc}")
        return None


def get_option_chain(symbol, strikecount=10, timestamp=""):
    """Fetch a raw option chain through the official SDK."""
    try:
        fyers = get_fyers_client()
        data = {"symbol": symbol, "strikecount": strikecount, "timestamp": timestamp}
        return _call(fyers.optionchain, f"Option chain({symbol})", data=data)
    except Exception as exc:
        print(f"[Fyers] Option chain setup error for {symbol}: {exc}")
        return None


def get_nearest_expiry_days(raw_option_chain_response):
    """Return real days-to-expiry from Fyers expiryData.

    Missing/invalid expiry is returned as None. Never invent a 3-day expiry:
    fabricated expiry makes IV look real when the source data is unavailable.
    """
    try:
        expiry_list = (raw_option_chain_response or {}).get("data", {}).get("expiryData", [])
        if not expiry_list:
            return None
        first = expiry_list[0].get("date")
        if not first:
            return None
        expiry_date = datetime.strptime(first, "%d-%m-%Y").date()
        return max((expiry_date - datetime.now().date()).days, 1)
    except (TypeError, ValueError, AttributeError):
        return None


def get_option_analytics(symbol, strikecount=10):
    """Fetch and analyse a real option chain; return None if unusable."""
    from .options_analytics import analyze_option_chain

    raw = get_option_chain(symbol, strikecount=strikecount)
    if not raw or raw.get("s") != "ok":
        return None

    days = get_nearest_expiry_days(raw)
    if days is None:
        print(f"[Fyers] Option analytics: expiry unavailable for {symbol}; returning None.")
        return None

    result = analyze_option_chain(raw, days_to_expiry=days)
    if result is not None:
        result["days_to_expiry"] = days
        try:
            expiry_list = raw.get("data", {}).get("expiryData", [])
            result["expiry_date"] = (
                datetime.strptime(expiry_list[0].get("date"), "%d-%m-%Y").date().isoformat()
                if expiry_list and expiry_list[0].get("date")
                else None
            )
        except (TypeError, ValueError, AttributeError, IndexError):
            result["expiry_date"] = None
    return result


# Backward compatibility for views.py
class _FyersCompat:
    @staticmethod
    def is_authenticated():
        return is_authenticated()

    @staticmethod
    def get_quotes(symbols):
        return get_quotes(symbols)

    @staticmethod
    def get_auth_url():
        return ("Run fyers_auth_sdk_v4.py", "manual")

    @staticmethod
    def exchange_code(code):
        return (False, "Use fyers_auth_sdk_v4.py")

    @staticmethod
    def get_profile():
        try:
            return get_fyers_client().get_profile()
        except Exception as exc:
            print(f"[Fyers] Profile error: {exc}")
            return None

    @property
    def access_token(self):
        try:
            return get_access_token()
        except Exception:
            return None


fyers_client = _FyersCompat()


if __name__ == "__main__":
    print("Fyers Client Test")
    print(f"Token path: {TOKEN_PATH}")
    print(f"Token exists: {os.path.exists(TOKEN_PATH)}")
    print(f"Authenticated: {is_authenticated()}")
    if is_authenticated():
        print(get_quotes(["NSE:NIFTY50-INDEX"]))
