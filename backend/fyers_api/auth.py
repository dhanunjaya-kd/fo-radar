import hashlib
import json
import os
import requests
from django.conf import settings

# Same file screener/fyers_client.py's get_access_token() reads (it checks
# this path and fyers_access_token.txt, picking whichever is newer).
TOKEN_JSON_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fyers_auth.json")


class FyersAuth:
    def __init__(self):
        self.app_id = settings.FYERS_APP_ID
        self.secret = settings.FYERS_APP_SECRET
        self.redirect_uri = settings.FYERS_REDIRECT_URI
        self.access_token = self._load_persisted_token()

    @staticmethod
    def _load_persisted_token():
        """Read back whatever generate_access_token() last saved, so a
        fresh FyersAuth() (e.g. inside FyersClient.__init__) isn't always
        starting from None."""
        if not os.path.exists(TOKEN_JSON_PATH):
            return None
        try:
            with open(TOKEN_JSON_PATH, "r") as f:
                return json.load(f).get("access_token")
        except Exception:
            return None

    def generate_auth_url(self):
        return f"https://api.fyers.in/api/v3/generate-authcode?client_id={self.app_id}&redirect_uri={self.redirect_uri}&response_type=code&state=sample"

    def generate_access_token(self, auth_code):
        """Exchange auth code for access token using SHA256."""
        hash_input = f"{self.app_id}:{self.secret}"
        sha256_hash = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()

        url = "https://api.fyers.in/api/v3/validate-authcode"
        payload = {
            "grant_type": "authorization_code",
            "appIdHash": sha256_hash,
            "code": auth_code,
        }
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            data = response.json()
            self.access_token = data.get("access_token")
            if self.access_token:
                # THIS WAS THE BUG: the token used to live only in
                # self.access_token, which dies with this request -- the
                # next FyersClient() created a fresh FyersAuth() with
                # access_token=None. Persist it to the same file
                # get_fyers_token.py writes, so every client (this app's
                # AND screener/fyers_client.py) can find it.
                with open(TOKEN_JSON_PATH, "w") as f:
                    json.dump({
                        "app_id": self.app_id,
                        "access_token": self.access_token,
                        "refresh_token": data.get("refresh_token", ""),
                    }, f, indent=2)
            return self.access_token
        return None

    def get_headers(self):
        return {
            "Authorization": f"{self.app_id}:{self.access_token}",
            "Content-Type": "application/json"
        }
