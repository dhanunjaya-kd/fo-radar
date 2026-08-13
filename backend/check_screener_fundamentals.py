"""
check_screener_fundamentals.py

Purpose: Screener.in has no public API (confirmed via their own docs --
"we don't provide APIs on Screener"). This tests what's actually
reachable using your own logged-in session cookie, dumping the raw
response at each step so the real shape of the data drives what gets
built next -- not a guess.

Based on a working reference (a public notebook that automates
Screener's own "Export to Excel" button): the company search API gives
a page URL, that page's HTML contains an export/"warehouse" ID buried
in a button's formaction attribute, and the export itself is a POST
to that ID's URL, not a plain GET -- confirmed by an earlier run of
this script (auth now genuinely works, event-user="free" and a real
page came back, but a GET to the export URL just re-served the normal
page instead of a file).

Screener runs on Django (the csrftoken cookie sitting next to
sessionid is the tell), which requires a CSRF token submitted with
any POST. Rather than ask you to manually copy a SECOND cookie value
by hand (error-prone, as sessionid alone already proved), this uses a
real requests.Session() -- Step 2's request lets Django set/refresh
the csrftoken cookie automatically, the same way a real browser tab
would pick it up, and Step 3 reads it straight from the session and
submits it with the POST.

PRIVACY: reads your session value from screener_session.txt (a file
you create next to this script, containing just that one value) rather
than hardcoding it here -- same reason fyers_auth.json stays out of
git. Add screener_session.txt to .gitignore too.

Run from backend/ with venv active.
Paste the full printed output back for review -- and check the two
files it saves (screener_test_page.html, screener_test_export.xlsx if
step 3 succeeds) since those show the real structure this needs to
parse next.
"""
import re
import sys
import traceback
import requests

# Windows PowerShell's default console encoding can't display every
# Unicode character -- reconfigure stdout to UTF-8 and swap
# unprintable characters for a placeholder instead of crashing.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

with open("screener_session.txt", "r", encoding="utf-8") as f:
    raw = f.read()

# HTTP headers must be plain ASCII/latin-1 by spec -- an earlier run's
# traceback showed a crash happening deep inside urllib3 while SENDING
# the cookie header, which meant screener_session.txt had more in it
# than just the bare session value. Clean defensively: take only the
# first whitespace-separated field (discards extra pasted columns
# entirely rather than mashing them together), then strip anything
# that isn't a plausible cookie character.
first_line = raw.splitlines()[0] if raw.splitlines() else ""
first_field = re.split(r'[\s\t]+', first_line.strip())[0] if first_line.strip() else ""
SESSION_ID = re.sub(r'[^A-Za-z0-9_\-\.]', '', first_field)

if SESSION_ID != first_line.strip():
    print(f"NOTE: cleaned screener_session.txt down to just the first field: {SESSION_ID!r}")
    print(f"      (raw first line was {len(first_line.strip())} chars, cleaned to {len(SESSION_ID)} chars)")
    print("      If the result below still fails, re-copy ONLY the sessionid VALUE column into that file, nothing else.\n")

if not SESSION_ID:
    print("ERROR: screener_session.txt is empty after cleanup -- re-check its contents.")
    sys.exit(1)

# A real Session (not bare requests.get calls) so cookies -- including
# a fresh csrftoken Django sets on each response -- persist
# automatically across all three steps, the same way a real browser
# tab carries them. sessionid is the only thing seeded manually, since
# it's the one thing only your login can provide.
session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
session.cookies.set("sessionid", SESSION_ID, domain="www.screener.in")

TEST_SYMBOL = "RELIANCE"

print("=" * 70)
print(f"STEP 1: Company search for '{TEST_SYMBOL}'")
print("=" * 70)
search_url = f"https://www.screener.in/api/company/search/?q={TEST_SYMBOL}"
company_path = None
try:
    resp = session.get(search_url, timeout=15)
    print(f"Status: {resp.status_code}")
    results = resp.json() if resp.status_code == 200 else []
    if results:
        company_path = results[0].get("url")
        print(f">>> Found company path: {company_path}")
    else:
        print(">>> Search returned an empty result list")
    print("\nRaw response (first 1500 chars):")
    print(resp.text[:1500])
except Exception:
    print("ERROR -- full traceback below (this is the real diagnostic, not a guess):")
    traceback.print_exc(file=sys.stdout)

print("\n" + "=" * 70)
print("STEP 2: Company page HTML + export ID extraction")
print("=" * 70)
warehouse_id = None
page_url = None
csrf_token = None
if company_path:
    page_url = f"https://www.screener.in{company_path}"
    try:
        resp = session.get(page_url, timeout=15)
        print(f"Status: {resp.status_code}, length: {len(resp.text)} chars")
        with open("screener_test_page.html", "w", encoding="utf-8") as f:
            f.write(resp.text)
        print("Saved full HTML to screener_test_page.html for review.")

        match = re.search(r'formaction=./user/company/export/(\d+)/.', resp.text)
        if match:
            warehouse_id = match.group(1)
            print(f">>> Found export/warehouse ID: {warehouse_id}")
        else:
            print(">>> Could not find an export ID in the page HTML.")

        if "Stock P/E" in resp.text or "ROE" in resp.text:
            print(">>> Ratio-like labels found directly in the page HTML.")

        # THIS response is what actually sets/refreshes the csrftoken
        # cookie on the session (Django does this on GET requests to
        # pages containing a CSRF-protected form) -- grab it now.
        csrf_token = session.cookies.get("csrftoken")
        print(f">>> CSRF token picked up from session: {'found, ' + str(len(csrf_token)) + ' chars' if csrf_token else 'NOT FOUND'}")
    except Exception:
        print("ERROR -- full traceback below (this is the real diagnostic, not a guess):")
        traceback.print_exc(file=sys.stdout)
else:
    print("Skipped -- no company path found in step 1")

print("\n" + "=" * 70)
print("STEP 3: Export endpoint (POST with CSRF token -- matches how the button actually submits, not a plain GET)")
print("=" * 70)
if warehouse_id:
    export_url = f"https://www.screener.in/user/company/export/{warehouse_id}/"
    try:
        post_data = {"csrfmiddlewaretoken": csrf_token} if csrf_token else {}
        resp = session.post(export_url, data=post_data, headers={"Referer": page_url}, timeout=15)
        print(f"Status: {resp.status_code}")
        print(f"Content-Type: {resp.headers.get('Content-Type')}")
        print(f"Content-Length: {len(resp.content)} bytes")
        content_type = resp.headers.get("Content-Type", "")
        if "spreadsheet" in content_type or "excel" in content_type:
            with open("screener_test_export.xlsx", "wb") as f:
                f.write(resp.content)
            print(">>> Real Excel file received -- saved as screener_test_export.xlsx. Open it and check which sheet/cells actually hold P/E, ROE, Debt/Equity, etc.")
        else:
            print("Still not a spreadsheet content-type -- first 500 chars of response:")
            print(resp.text[:500])
    except Exception:
        print("ERROR -- full traceback below (this is the real diagnostic, not a guess):")
        traceback.print_exc(file=sys.stdout)
else:
    print("Skipped -- no export ID found in step 2")

print("\n" + "=" * 70)
print("DONE. Paste this full output back for review.")
print("=" * 70)