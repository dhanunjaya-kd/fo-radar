"""
Sep 21 2026: standalone Telegram diagnostic -- run this directly,
anytime, not dependent on market hours or a live signal firing:

    python test_telegram_alert.py

This exists because the REAL app's own alert path (views.py's
_build_all(), around the sync_active_signals()/TelegramBot() call)
wraps the whole send in a broad try/except that only prints a generic
one-line failure to the server console -- easy to miss, and it only
fires on a genuinely NEW signal, so testing it means waiting for one
to appear live. This script isolates JUST the Telegram send, calls
Telegram's API directly, and prints its EXACT response -- so the
cause (missing config vs. a wrong token vs. a wrong chat ID vs.
something else entirely) is visible on the first run, not inferred
from a quiet log line days later.

Same .env-reading pattern as get_fyers_token.py (same folder) --
reads backend/.env directly via environ, doesn't need the full Django
app running.
"""
import os
import sys

from environ import Env
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env = Env()
env.read_env(os.path.join(BASE_DIR, ".env"))

BOT_TOKEN = env.str("TELEGRAM_BOT_TOKEN", default="")
CHAT_ID = env.str("TELEGRAM_CHAT_ID", default="")

print("=" * 70)
print("TELEGRAM ALERT DIAGNOSTIC")
print("=" * 70)

# Step 1: are the two required values even present in .env at all?
# Checked and reported separately, not combined into one message --
# "both missing" and "one missing" point at different fixes.
missing = []
if not BOT_TOKEN:
    missing.append("TELEGRAM_BOT_TOKEN")
if not CHAT_ID:
    missing.append("TELEGRAM_CHAT_ID")

if missing:
    print(f"\nMISSING FROM backend/.env: {', '.join(missing)}")
    print("\nThis is very likely the entire cause of zero alerts -- the real")
    print("app's own TelegramBot silently no-ops (one console line, no crash,")
    print("no exception) whenever either of these is blank, which is exactly")
    print("why signals keep generating correctly while nothing ever arrives.")
    print("\nFix: open backend/.env and add the missing line(s):")
    if "TELEGRAM_BOT_TOKEN" in missing:
        print("  TELEGRAM_BOT_TOKEN=<your bot token from @BotFather>")
    if "TELEGRAM_CHAT_ID" in missing:
        print("  TELEGRAM_CHAT_ID=<your chat id>")
    print("\nIf you don't have these yet:")
    print("  1. Message @BotFather on Telegram, /newbot, follow its prompts")
    print("     -> gives you TELEGRAM_BOT_TOKEN")
    print("  2. Message your new bot anything (e.g. 'hi'), then visit:")
    print("     https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates")
    print("     -> look for \"chat\":{\"id\": <a number>} in the response")
    print("     -> that number is TELEGRAM_CHAT_ID")
    print("\nRe-run this script after adding them.")
    sys.exit(1)

print(f"\nTELEGRAM_BOT_TOKEN: found ({len(BOT_TOKEN)} chars)")
print(f"TELEGRAM_CHAT_ID: {CHAT_ID}")
print("\nBoth present -- attempting a real test send now...")

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
payload = {
    "chat_id": CHAT_ID,
    "text": "F&O Radar -- Telegram diagnostic test message. If you see this, alerts are working correctly.",
    "parse_mode": "HTML",
}

try:
    resp = requests.post(url, json=payload, timeout=10)
    data = resp.json()
except Exception as e:
    print(f"\nNETWORK/REQUEST FAILURE (not a Telegram API response at all): {e}")
    print("This is a connectivity issue, not a config issue -- check your")
    print("internet connection or whether api.telegram.org is reachable")
    print("from this machine.")
    sys.exit(1)

print(f"\nHTTP status: {resp.status_code}")
print(f"Telegram API response: {data}")

if data.get("ok"):
    print("\nSUCCESS -- check your Telegram chat now, the test message should")
    print("be there. If it is, the alert mechanism itself is fully working;")
    print("any past missing alerts were the .env-was-blank case, now fixed.")
else:
    # Sep 21 2026: Telegram's own error_code/description are printed
    # verbatim, not paraphrased -- these are the two most common real
    # causes, named directly rather than left for the person to
    # decode from a raw API error on their own.
    err_code = data.get("error_code")
    err_desc = data.get("description", "")
    print(f"\nFAILED -- Telegram rejected this request. code={err_code}, description={err_desc!r}")
    if err_code == 401:
        print("\ncode 401 = Unauthorized -- TELEGRAM_BOT_TOKEN is wrong or revoked.")
        print("Get a fresh token from @BotFather (/mybots -> your bot -> API Token)")
        print("and update backend/.env, then re-run this script.")
    elif err_code == 400 and "chat not found" in err_desc.lower():
        print("\n'chat not found' = TELEGRAM_CHAT_ID is wrong, OR you've never")
        print("messaged this bot before (a bot can't message you first -- you")
        print("have to message it at least once). Message your bot anything,")
        print("then re-check the chat id via:")
        print(f"  https://api.telegram.org/bot{BOT_TOKEN}/getUpdates")
    else:
        print("\nUnrecognized error -- paste this exact output back and it can")
        print("be diagnosed from the real code/description above.")
    sys.exit(1)
