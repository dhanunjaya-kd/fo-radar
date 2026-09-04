"""
Fyers API v3 Client Wrapper.

This module is the single gateway used by the live scanner for Fyers calls.
It deliberately contains transport/reliability controls only; it must not
change Sniper scoring or signal-selection logic.
"""
import json
import os
import time
import threading
from datetime import datetime

from fyers_apiv3 import fyersModel

try:
    from django.conf import settings as _django_settings
    CLIENT_ID = _django_settings.FYERS_APP_ID
    CLIENT_SECRET = getattr(_django_settings, "FYERS_APP_SECRET", "")
    REDIRECT_URI = getattr(_django_settings, "FYERS_REDIRECT_URI", "")
except Exception:
    CLIENT_ID = os.environ.get("FYERS_APP_ID", "")
    CLIENT_SECRET = os.environ.get("FYERS_APP_SECRET", os.environ.get("FYERS_SECRET_KEY", ""))
    REDIRECT_URI = os.environ.get("FYERS_REDIRECT_URI", "")

BACKEND_DIR = os.path.dirname(os.path.dirname(__file__))
TOKEN_PATH = os.path.join(BACKEND_DIR, "fyers_access_token.txt")
TOKEN_JSON_PATH = os.path.join(BACKEND_DIR, "fyers_auth.json")


def _load_auth_file():
    if not os.path.exists(TOKEN_JSON_PATH):
        return {}
    try:
        with open(TOKEN_JSON_PATH, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def get_access_token():
    """Read the newest saved Fyers access token from either supported file."""
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
        return json.load(f)["access_token"].strip()


def get_fyers_client():
    """Return the authenticated Fyers v3 SDK client."""
    return fyersModel.FyersModel(
        client_id=CLIENT_ID,
        token=get_access_token(),
        is_async=False,
    )


# ---------------------------------------------------------------------------
# Automatic access-token refresh
# ---------------------------------------------------------------------------
# Fyers access tokens expire. The auth exchange stores a refresh token in
# fyers_auth.json; when the API explicitly reports an expired access token,
# refresh it once and persist the replacement before retrying the profile
# check. If the refresh token itself has expired/revoked, we fail loudly and
# leave the scanner in honest "unavailable" state rather than inventing data.
_auth_refresh_lock = threading.Lock()
_refresh_failure_until = 0.0
_REFRESH_FAILURE_COOLDOWN = 60.0


def _save_refreshed_tokens(response):
    access_token = (response or {}).get("access_token", "").strip()
    if not access_token:
        return False

    current = _load_auth_file()
    data = {
        "app_id": CLIENT_ID,
        "access_token": access_token,
        "refresh_token": (response.get("refresh_token") or current.get("refresh_token") or "").strip(),
    }
    temp_path = TOKEN_JSON_PATH + ".tmp"
    try:
        with open(temp_path, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, TOKEN_JSON_PATH)
        # Keep the legacy text token file in sync when it already exists.
        if os.path.exists(TOKEN_PATH):
            temp_txt = TOKEN_PATH + ".tmp"
            with open(temp_txt, "w") as f:
                f.write(access_token)
            os.replace(temp_txt, TOKEN_PATH)
        return True
    except OSError as exc:
        print(f"[Fyers] Token refresh succeeded but token persistence failed: {exc}")
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        return False


def _refresh_access_token():
    """Refresh the saved access token using the saved Fyers refresh token."""
    global _refresh_failure_until

    now = time.monotonic()
    if now < _refresh_failure_until:
        return False

    with _auth_refresh_lock:
        now = time.monotonic()
        if now < _refresh_failure_until:
            return False

        auth = _load_auth_file()
        refresh_token = str(auth.get("refresh_token") or "").strip()
        if not refresh_token:
            print("[Fyers] Access token expired but no refresh token is saved.")
            _refresh_failure_until = now + _REFRESH_FAILURE_COOLDOWN
            return False
        if not CLIENT_ID or not CLIENT_SECRET:
            print("[Fyers] Access token expired but FYERS app credentials are not configured for refresh.")
            _refresh_failure_until = now + _REFRESH_FAILURE_COOLDOWN
            return False

        try:
            session = fyersModel.SessionModel(
                client_id=CLIENT_ID,
                secret_key=CLIENT_SECRET,
                redirect_uri=REDIRECT_URI,
                response_type="code",
                grant_type="refresh_token",
                state="fno_sniper_refresh",
            )
            session.set_token(refresh_token)
            response = session.generate_token()
        except Exception as exc:
            print(f"[Fyers] Automatic token refresh failed: {exc}")
            _refresh_failure_until = now + _REFRESH_FAILURE_COOLDOWN
            return False

        if not _save_refreshed_tokens(response):
            _refresh_failure_until = now + _REFRESH_FAILURE_COOLDOWN
            return False

        print("[Fyers] Access token refreshed and persisted successfully.")
        _refresh_failure_until = 0.0
        return True


# ---------------------------------------------------------------------------
# Authentication cache
# ---------------------------------------------------------------------------
_auth_cache = {"value": None, "checked_at": 0.0}
_AUTH_SUCCESS_TTL = 30.0
_AUTH_FAILURE_TTL = 5.0


# ---------------------------------------------------------------------------
# Shared Fyers request governor + rate-limit circuit breaker
# ---------------------------------------------------------------------------
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
        cooldown = min(_rate_limit_state["cooldown_seconds"], _RATE_LIMIT_MAX_COOLDOWN)
        _rate_limit_state["blocked_until"] = time.monotonic() + cooldown
        print(
            "[Fyers] Rate-limit circuit breaker TRIPPED -- "
            f"backing off {int(cooldown)}s "
            f"(consecutive 429s: {_rate_limit_state['consecutive_429s']})"
        )
        _rate_limit_state["cooldown_seconds"] = min(cooldown * 2, _RATE_LIMIT_MAX_COOLDOWN)


def _note_success():
    if _rate_limit_state["consecutive_429s"] or _rate_limit_state["blocked_until"]:
        print("[Fyers] Rate-limit circuit breaker reset -- real response received.")
    _rate_limit_state["consecutive_429s"] = 0
    _rate_limit_state["blocked_until"] = 0.0
    _rate_limit_state["cooldown_seconds"] = 60.0


def _call(method, label, *args, **kwargs):
    """Execute one Fyers SDK request through the shared transport governor."""
    global _last_request_at

    if _rate_limited_now():
        print(f"[Fyers] {label}: circuit breaker open -- skipping real call.")
        return None

    with _request_lock:
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
    """Check the current token; automatically refresh once on explicit expiry."""
    now = time.monotonic()
    cached = _auth_cache["value"]
    age = now - _auth_cache["checked_at"]
    ttl = _AUTH_SUCCESS_TTL if cached is True else _AUTH_FAILURE_TTL
    if cached is not None and age < ttl:
        return cached

    try:
        fyers = get_fyers_client()
        resp = _call(fyers.get_profile, "Profile")
        if resp is not None and resp.get("s") == "ok":
            result = True
        elif resp is not None and str(resp.get("code")) == "-8":
            print("[Fyers] Access token expired -- attempting automatic refresh.")
            if _refresh_access_token():
                fyers = get_fyers_client()
                resp = _call(fyers.get_profile, "Profile(after refresh)")
                result = bool(resp and resp.get("s") == "ok")
            else:
                result = False
            if not result and resp:
                print(f"[Fyers] Profile after refresh returned not-ok: {resp}")
        else:
            result = False
            if resp is not None:
                print(f"[Fyers] is_authenticated(): profile check returned not-ok: {resp}")
    except Exception as exc:
        print(f"[Fyers] is_authenticated(): profile setup failed: {exc}")
        result = False

    _auth_cache["value"] = result
    _auth_cache["checked_at"] = time.monotonic()
    return result


def get_quotes(symbols):
    try:
        fyers = get_fyers_client()
        return _call(fyers.quotes, "Quotes", {"symbols": ",".join(symbols)})
    except Exception as exc:
        print(f"[Fyers] Quote setup error: {exc}")
        return None


def get_history(symbol, resolution="1D", range_from=None, range_to=None):
    try:
        fyers = get_fyers_client()
        data = {"symbol": symbol, "resolution": resolution, "date_format": "1", "range_from": range_from, "range_to": range_to, "cont_flag": "1"}
        return _call(fyers.history, f"History({symbol})", data)
    except Exception as exc:
        print(f"[Fyers] History setup error for {symbol}: {exc}")
        return None


def get_market_depth(symbol):
    try:
        fyers = get_fyers_client()
        return _call(fyers.depth, f"Depth({symbol})", {"symbol": symbol, "ohlcv_flag": "1"})
    except Exception as exc:
        print(f"[Fyers] Depth setup error for {symbol}: {exc}")
        return None


def get_option_chain(symbol, strikecount=10, timestamp=""):
    try:
        fyers = get_fyers_client()
        data = {"symbol": symbol, "strikecount": strikecount, "timestamp": timestamp}
        return _call(fyers.optionchain, f"Option chain({symbol})", data=data)
    except Exception as exc:
        print(f"[Fyers] Option chain setup error for {symbol}: {exc}")
        return None


def get_nearest_expiry_days(raw_option_chain_response):
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
            return _call(get_fyers_client().get_profile, "Profile")
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
