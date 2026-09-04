import json
import os
import webbrowser
from urllib.parse import urlparse, parse_qs

from environ import Env
from fyers_apiv3 import fyersModel

# Credentials are loaded from backend/.env; never commit client secrets.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env = Env()
env.read_env(os.path.join(BASE_DIR, ".env"))
CLIENT_ID = env.str("FYERS_APP_ID")
SECRET_KEY = env.str("FYERS_APP_SECRET", default=env.str("FYERS_SECRET_KEY", default=""))
REDIRECT_URI = env.str("FYERS_REDIRECT_URI", default="https://trade.fyers.in/api-login/redirect-uri/index.html")

if not SECRET_KEY:
    raise RuntimeError("FYERS_APP_SECRET/FYERS_SECRET_KEY is missing from backend/.env")

# STEP 1: Open browser for login
session = fyersModel.SessionModel(
    client_id=CLIENT_ID,
    secret_key=SECRET_KEY,
    redirect_uri=REDIRECT_URI,
    response_type="code",
    grant_type="authorization_code",
    state="sample_state",
)

auth_url = session.generate_authcode()
print("=" * 60)
print("OPENING FYERS LOGIN...")
print("=" * 60)
print(f"\nIf browser doesn't open, use this URL:\n{auth_url}\n")
webbrowser.open(auth_url)

# STEP 2: Paste the FULL redirected URL
print("\nAfter login, paste the FULL URL from your browser below:")
print("(Right-click address bar -> Copy -> Paste here)")
redirect_url = input("\nPaste URL: ").strip()

parsed = urlparse(redirect_url)
auth_code = parse_qs(parsed.query).get("auth_code", [None])[0]

if not auth_code:
    print("\nCould not find auth_code in URL!")
    raise SystemExit(1)

print(f"\nAuth code extracted ({len(auth_code)} chars)")

# STEP 3: Exchange auth code for access + refresh tokens
session.set_token(auth_code)
response = session.generate_token()

print("\n" + "=" * 60)
print("FYERS RESPONSE:")
print("=" * 60)
print(json.dumps({k: ("<redacted>" if "token" in k.lower() else v) for k, v in response.items()}, indent=2))

if "access_token" in response:
    token_data = {
        "app_id": CLIENT_ID,
        "access_token": response["access_token"],
        "refresh_token": response.get("refresh_token", ""),
    }
    token_path = os.path.join(BASE_DIR, "fyers_auth.json")
    with open(token_path, "w") as f:
        json.dump(token_data, f, indent=2)
    print(f"\nSUCCESS! Token pair saved to {token_path}")
    print("The live scanner can now automatically refresh an expired access token while the refresh token remains valid.")
else:
    print("\nFAILED:", response.get("message", "Unknown error"))
