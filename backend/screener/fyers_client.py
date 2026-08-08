"""
Fyers API v3 Client Wrapper — Production Ready
Usage:
    from fyers_client import get_fyers_client
    fyers = get_fyers_client()
    data = fyers.quotes({"symbols": "NSE:RELIANCE-EQ"})
"""
import os
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


def is_authenticated():
    """Check if token exists and is valid by fetching profile."""
    try:
        fyers = get_fyers_client()
        resp = fyers.get_profile()
        return resp.get("s") == "ok"
    except Exception:
        return False


def get_quotes(symbols):
    """
    Fetch quotes for given symbols.
    symbols: list like ["NSE:RELIANCE-EQ", "NSE:NIFTY50-INDEX"]
    """
    try:
        fyers = get_fyers_client()
        return fyers.quotes({"symbols": ",".join(symbols)})
    except Exception as e:
        print(f"[Fyers] Quote error: {e}")
        return None


def get_history(symbol, resolution="1D", range_from=None, range_to=None):
    """Fetch historical data."""
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
        return fyers.history(data)
    except Exception as e:
        print(f"[Fyers] History error: {e}")
        return None


def get_market_depth(symbol):
    """Fetch market depth (order book)."""
    try:
        fyers = get_fyers_client()
        return fyers.depth({"symbol": symbol, "ohlcv_flag": "1"})
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
    try:
        fyers = get_fyers_client()
        data = {"symbol": symbol, "strikecount": strikecount, "timestamp": timestamp}
        return fyers.optionchain(data=data)
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
    return analyze_option_chain(raw, days_to_expiry=days)


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