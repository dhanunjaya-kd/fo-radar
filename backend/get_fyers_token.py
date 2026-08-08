from fyers_apiv3 import fyersModel
import webbrowser
import json
from urllib.parse import urlparse, parse_qs

# ─── YOUR CREDENTIALS ───
CLIENT_ID    = "LYNP1Z6GGG-100"
SECRET_KEY   = "ZJGKUS4OBB"
REDIRECT_URI = "https://trade.fyers.in/api-login/redirect-uri/index.html"

# ─── STEP 1: Open browser for login ───
session = fyersModel.SessionModel(
    client_id=CLIENT_ID,
    secret_key=SECRET_KEY,
    redirect_uri=REDIRECT_URI,
    response_type="code",
    grant_type="authorization_code",
    state="sample_state"
)

auth_url = session.generate_authcode()
print("=" * 60)
print("OPENING FYERS LOGIN...")
print("=" * 60)
print(f"\nIf browser doesn't open, use this URL:\n{auth_url}\n")

webbrowser.open(auth_url)

# ─── STEP 2: Paste the FULL redirected URL ───
print("\nAfter login, paste the FULL URL from your browser below:")
print("(Right-click address bar → Copy → Paste here)")
redirect_url = input("\nPaste URL: ").strip()

# ─── Auto-extract auth code ───
parsed = urlparse(redirect_url)
auth_code = parse_qs(parsed.query).get('auth_code', [None])[0]

if not auth_code:
    print("\n❌ Could not find auth_code in URL!")
    exit(1)

print(f"\n✅ Auth code extracted ({len(auth_code)} chars)")

# ─── STEP 3: Exchange for access token ───
session.set_token(auth_code)
response = session.generate_token()

print("\n" + "=" * 60)
print("FYERS RESPONSE:")
print("=" * 60)
print(json.dumps(response, indent=2))

if "access_token" in response:
    token_data = {
        "app_id": CLIENT_ID,
        "access_token": response["access_token"],
        "refresh_token": response.get("refresh_token", ""),
    }
    with open("fyers_auth.json", "w") as f:
        json.dump(token_data, f, indent=2)
    print("\n🎉 SUCCESS! Token saved to fyers_auth.json")
    print(f"Token: {response['access_token'][:50]}...")
else:
    print("\n❌ FAILED:", response.get("message", "Unknown error"))