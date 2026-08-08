"""
Historically broken, now patched: FyersAuth used to only hold the access
token in memory on whichever instance ran generate_access_token(), so every
other FyersClient() (here, and in data_fetcher.py) built a fresh FyersAuth()
with access_token=None and every request failed. auth.py now persists the
token to fyers_auth.json and loads it back on init, so this class works
again -- but screener/fyers_client.py (the official fyers_apiv3 SDK wrapper)
is still the primary, better-tested client used by the live scanner
pipeline; prefer that for anything new.
"""
import requests
from django.conf import settings
from .auth import FyersAuth

class FyersClient:
    def __init__(self):
        self.auth = FyersAuth()
        self.base_url = "https://api.fyers.in/api/v3"

    def get_profile(self):
        url = f"{self.base_url}/profile"
        return requests.get(url, headers=self.auth.get_headers()).json()

    def get_quotes(self, symbols):
        """symbols: list like ["NSE:RELIANCE-EQ", "NSE:TCS-EQ"]"""
        url = f"{self.base_url}/quotes"
        return requests.get(url, headers=self.auth.get_headers(), params={"symbols": ",".join(symbols)}).json()

    def get_depth(self, symbol):
        url = f"{self.base_url}/depth"
        return requests.get(url, headers=self.auth.get_headers(), params={"symbol": symbol}).json()

    def get_option_chain(self, symbol, strikecount=10):
        """Fetch option chain for a symbol.
        NOTE: this used to send params={"symbol": symbol, "date": expiry_date}
        -- "date" is not a Fyers option-chain param at all (the real ones are
        "symbol", "strikecount", "timestamp"), so every call 400'd even once
        auth was fixed. Corrected below to match the documented endpoint."""
        url = f"{self.base_url}/options-chain-v3"
        params = {"symbol": symbol, "strikecount": strikecount, "timestamp": ""}
        return requests.get(url, headers=self.auth.get_headers(), params=params).json()

    def place_order(self, symbol, qty, side, type_, product="INTRADAY", limit_price=0):
        """Place order via Fyers API."""
        url = f"{self.base_url}/orders"
        payload = {
            "symbol": symbol,
            "qty": qty,
            "type": type_,  # 1=Limit, 2=Market
            "side": side,   # 1=Buy, -1=Sell
            "productType": product,
            "limitPrice": limit_price,
            "stopPrice": 0,
            "disclosedQty": 0,
            "validity": "DAY",
            "offlineOrder": False,
            "stopLoss": 0,
            "takeProfit": 0
        }
        return requests.post(url, headers=self.auth.get_headers(), json=payload).json()

    def get_positions(self):
        url = f"{self.base_url}/positions"
        return requests.get(url, headers=self.auth.get_headers()).json()

    def get_holdings(self):
        url = f"{self.base_url}/holdings"
        return requests.get(url, headers=self.auth.get_headers()).json()
