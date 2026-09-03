"""
Fyers API v3 Client Wrapper — Production Ready
Usage:
    from fyers_client import get_fyers_client
    fyers = get_fyers_client()
    data = fyers.quotes({"symbols": "NSE:RELIANCE-EQ"})
"""
import os
import time
from datetime import datetime
from fyers_apiv3 import fyersModel

try:
    # Read from Django settings so there is exactly ONE place (.env /
    # settings.py) that defines which Fyers app this project talks to.
    # Previously this was hardcoded here to a stale app id ("6OWXIMCOXF-100")
    # that did not match the app actually connected in the Fyers dashboard
    # (fyers_auth.json / the API dashboard both show "LYNP1Z6GGG-100"), so
    # every call made with this client was silently using the wrong
    # client_id even when the access token itself was valid.
    from django.conf import settings as _django_settings
    CLIENT_ID = _django_settings.FYERS_APP_ID
except Exception:
    # Fallback for standalone scripts run outside Django (e.g. `python
    # screener/fyers_client.py` directly) -- reads the same .env var name.
    CLIENT_ID = os.environ.get("FYERS_APP_ID", "")

# Token is written by whichever auth script was last run. This project has
# several (exchange_token.py, get_fyers_token.py, fyers_auth.py...) and they
# don't agree on where they save it:
#   - fyers_access_token.txt : plain text, just the token
#   - fyers_auth.json        : {"app_id", "access_token", "refresh_token"}
#     (this is what get_fyers_token.py writes -- the script whose
#     CLIENT_ID/SECRET_KEY match the currently-connected Fyers app)
# Rather than force a switch to one script today, read whichever is newer,
# checking the format so both keep working.
BACKEND_DIR = os.path.dirname(os.path.dirname(__file__))
TOKEN_PATH = os.path.join(BACKEND_DIR, "fyers_access_token.txt")
TOKEN_JSON_PATH = os.path.join(BACKEND_DIR, "fyers_auth.json")


def get_access_token():
    """Read the most recently saved token, whichever script wrote it."""
    import json as _json

    candidates = []
    if os.path.exists(TOKEN_PATH):
        candidates.append((os.path.getmtime(TOKEN_PATH), TOKEN_PATH, "txt"))
    if os.path.exists(TOKEN_JSON_PATH):
        candidates.append((os.path.getmtime(TOKEN_JSON_PATH), TOKEN_JSON_PATH, "json"))

    if not candidates:
        raise FileNotFoundError(
            f"No saved Fyers token found. Looked for:\n  {TOKEN_PATH}\n  {TOKEN_JSON_PATH}\n"
            f"Run get_fyers_token.py to log in and save one."
        )

    candidates.sort(reverse=True)  # newest first
    _, path, fmt = candidates[0]
    if fmt == "txt":
        with open(path, "r") as f:
            return f.read().strip()
    with open(path, "r") as f:
        return _json.load(f)["access_token"].strip()


def get_fyers_client():
    """Return authenticated Fyers v3 client."""
    token = get_access_token()
    return fyersModel.FyersModel(
        client_id=CLIENT_ID,
        token=token,
        is_async=False
    )


# Aug 20 2026: is_authenticated() used to hit Fyers' /profile endpoint --
# a real network round-trip -- EVERY single time it was called. views.py
# alone calls it up to ~35 times in one _build_all() scan cycle (3x for
# the indices, once for the stock-quotes gate, once for PCR, once per
# top mover inside _calc_tech() -- up to 30 more). Any ONE of those 35
# identical calls hitting a transient hiccup or a rate limit specific to
# /profile would silently zero out whatever it was gating, even while
# OTHER Fyers endpoints (quotes, option chains) kept working fine at the
# exact same moment -- confirmed as the real cause of a live incident
# where indices and the whole stock scan came back empty ("Stocks: 0,
# Signals: 0") while the Index Tracker and individual option-chain
# fetches, which don't gate on this check, stayed populated. Caching
# this for a short TTL cuts ~35 real network calls/cycle down to at
# most 1 -- short enough (30s) that re-authenticating mid-day (e.g.
# running get_fyers_token.py again) is picked up quickly, not stale for
# the rest of the day.
_auth_cache = {"value": None, "checked_at": 0.0}
_AUTH_CACHE_TTL = 30  # seconds


def is_authenticated():
    """Check if token exists and is valid by fetching profile. Cached
    for _AUTH_CACHE_TTL seconds -- see the comment above for why. Also
    now logs WHY on failure instead of silently swallowing it, so a
    future failure shows up in the terminal instead of just quietly
    returning nothing."""
    now = time.time()
    if _auth_cache["value"] is not None and (now - _auth_cache["checked_at"]) < _AUTH_CACHE_TTL:
        return _auth_cache["value"]

    result = False
    try:
        fyers = get_fyers_client()
        resp = fyers.get_profile()
        result = resp.get("s") == "ok"
        if not result:
            print(f"[Fyers] is_authenticated(): profile check returned not-ok: {resp}")
    except Exception as e:
        print(f"[Fyers] is_authenticated(): profile check failed: {e}")
        result = False

    _auth_cache["value"] = result
    _auth_cache["checked_at"] = now
    return result


# ============================================================
# RATE-LIMIT CIRCUIT BREAKER
# ============================================================
# Sep 3 2026: real bug, confirmed live -- screenshots showed 429
# ({'s': 'error', 'code': 429, 'message': 'Bad request'}) on every
# single quote/option-chain call, continuously, 09:15:43-09:20:19 with
# zero recovery in between. Root cause traced in views.py: _fetch_index()
# fired 3 separate single-symbol calls where 1 batched call would do
# (fixed there), but the bigger problem was here -- nothing in this
# module ever backed off on a 429. Every function below just logged the
# error and returned, then the exact same call volume repeated again
# next cycle (60-90s later), re-tripping the same limit every time with
# no chance for it to clear. eod_scanner.py already has a working
# circuit breaker for this exact scenario (see its own comments); the
# live-scanner/index-worker path never got one.
#
# This tracks CONSECUTIVE 429s across every Fyers call (all of them
# funnel through this one module), and once a real threshold is
# crossed, stops making actual network calls for a cooldown window --
# callers get None back immediately instead of adding another request
# to the pile. Escalates the cooldown on repeated trips (60s -> 120s ->
# 240s, capped at 300s) since a single flat cooldown clearly wasn't
# guaranteed to be enough on its own. Any real non-429 response (a
# genuine success OR a different kind of error) resets the counter and
# the escalation back to baseline -- this only reacts to confirmed,
# repeated rate-limit signals, never to an unrelated error.
#
# The {'s': 'error', 'code': 429} envelope is CONFIRMED live for quotes
# and option-chain (the two endpoints in the actual screenshots).
# get_history()/get_market_depth() are assumed to share the same SDK
# response envelope (every other endpoint in this file already checks
# resp.get('s') the same way) but that specific 429 shape hasn't been
# independently observed live on those two -- if it turns out different,
# the worst case is those two simply never trip or reset the breaker
# themselves, which is safe; they still RESPECT an active breaker
# tripped by quotes/option-chain either way.
_rate_limit_state = {"consecutive_429s": 0, "blocked_until": 0.0, "cooldown_seconds": 60}
_RATE_LIMIT_TRIP_THRESHOLD = 2  # back off once this many 429s land in a row
_RATE_LIMIT_MAX_COOLDOWN = 300


def _rate_limited_now():
    """True while a backoff window is active -- callers should skip the
    real network call entirely and return None rather than add to the
    pile."""
    return time.time() < _rate_limit_state["blocked_until"]


def _is_429(resp):
    return bool(resp) and resp.get("s") == "error" and resp.get("code") == 429


def _note_429():
    """Record a real 429. Below the trip threshold this just counts --
    one isolated 429 can be a harmless transient blip, not yet evidence
    of a real block."""
    _rate_limit_state["consecutive_429s"] += 1
    if _rate_limit_state["consecutive_429s"] >= _RATE_LIMIT_TRIP_THRESHOLD:
        cooldown = min(_rate_limit_state["cooldown_seconds"], _RATE_LIMIT_MAX_COOLDOWN)
        _rate_limit_state["blocked_until"] = time.time() + cooldown
        print(f"[Fyers] Rate-limit circuit breaker TRIPPED -- backing off {cooldown}s "
              f"(consecutive 429s: {_rate_limit_state['consecutive_429s']})")
        _rate_limit_state["cooldown_seconds"] = min(cooldown * 2, _RATE_LIMIT_MAX_COOLDOWN)


def _note_success():
    """Record a real non-429 response -- resets the consecutive count
    and the escalating cooldown back to baseline, since this is genuine
    evidence the limit has cleared."""
    if _rate_limit_state["consecutive_429s"] > 0:
        print("[Fyers] Rate-limit circuit breaker reset -- real response received.")
    _rate_limit_state["consecutive_429s"] = 0
    _rate_limit_state["cooldown_seconds"] = 60


def get_quotes(symbols):
    """
    Fetch quotes for given symbols.
    symbols: list like ["NSE:RELIANCE-EQ", "NSE:NIFTY50-INDEX"]

    Sep 3 2026: now respects the rate-limit circuit breaker above --
    returns None immediately without a real network call while a
    backoff window is active, and updates the breaker's state on every
    real response (429 or not). See the breaker's own comments for why.
    """
    if _rate_limited_now():
        print("[Fyers] Quotes: circuit breaker open -- skipping real call.")
        return None
    try:
        fyers = get_fyers_client()
        resp = fyers.quotes({"symbols": ",".join(symbols)})
        if _is_429(resp):
            _note_429()
        else:
            _note_success()
        return resp
    except Exception as e:
        print(f"[Fyers] Quote error: {e}")
        return None


def get_history(symbol, resolution="1D", range_from=None, range_to=None):
    """Fetch historical data. Sep 3 2026: respects the shared circuit
    breaker (see get_quotes above) -- skips the real call while a
    backoff window from quotes/option-chain is active."""
    if _rate_limited_now():
        print(f"[Fyers] History: circuit breaker open -- skipping real call for {symbol}.")
        return None
    try:
        fyers = get_fyers_client()
        data = {
            "symbol": symbol,
            "resolution": resolution,
            "date_format": "1",
            "range_from": range_from,
            "range_to": range_to,
            "cont_flag": "1"
        }
        resp = fyers.history(data)
        if _is_429(resp):
            _note_429()
        return resp
    except Exception as e:
        print(f"[Fyers] History error: {e}")
        return None


def get_market_depth(symbol):
    """Fetch market depth (order book). Sep 3 2026: respects the
    shared circuit breaker (see get_quotes above)."""
    if _rate_limited_now():
        print(f"[Fyers] Depth: circuit breaker open -- skipping real call for {symbol}.")
        return None
    try:
        fyers = get_fyers_client()
        resp = fyers.depth({"symbol": symbol, "ohlcv_flag": "1"})
        if _is_429(resp):
            _note_429()
        return resp
    except Exception as e:
        print(f"[Fyers] Depth error: {e}")
        return None


def get_option_chain(symbol, strikecount=10, timestamp=""):
    """
    Fetch the RAW option chain for a symbol via the official SDK method.

    IMPORTANT: this is `fyers.optionchain(data=...)`, NOT a hand-rolled
    `requests.get(".../options-chain-v3", params={"date": ...})` call --
    that other implementation (fyers_api/client.py + data_fetcher.py) hits
    the wrong param name ("date" instead of "timestamp") and was never
    actually exercised end-to-end.

    symbol: Fyers symbol, e.g. "NSE:RELIANCE-EQ" or "NSE:NIFTY50-INDEX"
    strikecount: number of strikes on each side of ATM to return
    Returns the raw dict response (or None on failure) -- pass it straight
    to screener.options_analytics.analyze_option_chain().
    """
    if _rate_limited_now():
        print(f"[Fyers] Option chain: circuit breaker open -- skipping real call for {symbol}.")
        return None
    try:
        fyers = get_fyers_client()
        data = {"symbol": symbol, "strikecount": strikecount, "timestamp": timestamp}
        resp = fyers.optionchain(data=data)
        if _is_429(resp):
            _note_429()
        else:
            _note_success()
        return resp
    except Exception as e:
        print(f"[Fyers] Option chain error for {symbol}: {e}")
        return None


def get_nearest_expiry_days(raw_option_chain_response):
    """Fyers returns expiryData as a list of {'date': 'DD-MM-YYYY', ...}
    sorted by nearest first. Convert the nearest one into days-to-expiry
    for the Black-Scholes IV solve. Falls back to 3 (a typical weekly
    expiry gap) if the field is missing so IV still computes instead of
    silently returning None."""
    try:
        expiry_list = (raw_option_chain_response or {}).get("data", {}).get("expiryData", [])
        if not expiry_list:
            return 3
        first = expiry_list[0].get("date")
        expiry_date = datetime.strptime(first, "%d-%m-%Y").date()
        days = (expiry_date - datetime.now().date()).days
        return max(days, 1)
    except Exception:
        return 3


def get_option_analytics(symbol, strikecount=10):
    """
    One call: fetch the real option chain for `symbol` and turn it into
    PCR / max pain / support / resistance / OI buildup / IV.
    Returns None if Fyers isn't authenticated, the symbol has no listed
    options, or the response is otherwise unusable -- callers MUST treat
    None as "no real data available" and say so rather than substituting
    a random number.
    """
    from .options_analytics import analyze_option_chain

    raw = get_option_chain(symbol, strikecount=strikecount)
    if not raw or raw.get("s") != "ok":
        return None
    days = get_nearest_expiry_days(raw)
    result = analyze_option_chain(raw, days_to_expiry=days)
    # Aug 31 2026: Section 9 (Risk Engine) from the UI Corrections
    # checklist -- "expiry awareness: show days/time to expiry." `days`
    # was already computed on the line above (fed INTO
    # analyze_option_chain as an input for its own IV math), it just
    # never made it back OUT in the result dict. Added here rather than
    # inside analyze_option_chain() itself, since that function's job is
    # turning a chain into analytics -- the expiry it was TOLD to use
    # isn't really one of its own outputs.
    if result is not None:
        result["days_to_expiry"] = days
        # Aug 31 2026: also expose the actual expiry DATE, not just a
        # day-count -- needed to build a correct TradingView option
        # symbol, which encodes the full YYMMDD expiry (TradingView's
        # own format, confirmed via real examples like
        # NIFTY250814C24700 -- year+month+DAY, not just year+month like
        # this project's own Fyers-format option_symbol uses). Re-
        # parsed directly from the same expiryData Fyers already
        # returned, not derived from `days` -- avoids drift if today's
        # date changes between when this was fetched and when it's used.
        try:
            expiry_list = (raw or {}).get("data", {}).get("expiryData", [])
            if expiry_list:
                expiry_date_obj = datetime.strptime(expiry_list[0].get("date"), "%d-%m-%Y").date()
                result["expiry_date"] = expiry_date_obj.isoformat()
            else:
                result["expiry_date"] = None
        except Exception:
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
        return get_fyers_client().get_profile()
    @property
    def access_token(self):
        try:
            return get_access_token()
        except:
            return None

fyers_client = _FyersCompat()


if __name__ == "__main__":
    print("Fyers Client Test")
    print(f"Token path: {TOKEN_PATH}")
    print(f"Token exists: {os.path.exists(TOKEN_PATH)}")
    print(f"Authenticated: {is_authenticated()}")
    if is_authenticated():
        print(get_quotes(["NSE:NIFTY50-INDEX"]))