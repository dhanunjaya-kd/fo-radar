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
in a button's formaction attribute, and THAT ID is what the real
export endpoint needs. Tests all three steps for one sample stock
(RELIANCE) before this gets pointed at the full NSE list.

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
# Unicode character (a rupee symbol crashed the first run of this
# script with "ordinal not in range(256)") -- reconfigure stdout to
# UTF-8 and swap unprintable characters for a placeholder instead of
# crashing. This only affects what gets displayed, not what gets
# parsed from the actual response.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

with open("screener_session.txt", "r", encoding="utf-8") as f:
    raw = f.read()

# HTTP headers must be plain ASCII/latin-1 by spec -- the actual
# traceback showed the crash happening deep inside urllib3 while
# SENDING the cookie header, not in any print statement. That means
# screener_session.txt likely has more in it than just the bare
# session value (a common way this happens: DevTools truncates long
# text with a single "..." ellipsis CHARACTER, not three periods, if
# more than one table column gets selected/copied together). Clean
# defensively: take only the first line, strip anything that isn't a
# plausible cookie character, and say exactly what got removed so this
# isn't a silent guess either.
first_line = raw.splitlines()[0] if raw.splitlines() else ""
# Take the FIRST whitespace-separated field before cleaning -- if
# extra columns got pasted alongside the real value (tab-separated,
# straight from a DevTools table row), this discards them entirely
# instead of mashing separate columns into one garbled string.
first_field = re.split(r'[\s\t]+', first_line.strip())[0] if first_line.strip() else ""
SESSION_ID = re.sub(r'[^A-Za-z0-9_\-\.]', '', first_field)

if SESSION_ID != first_line.strip():
    print(f"NOTE: cleaned screener_session.txt down to just the first field: {SESSION_ID!r}")
    print(f"      (raw first line was {len(first_line.strip())} chars, cleaned to {len(SESSION_ID)} chars)")
    print("      If the result below still fails, re-copy ONLY the sessionid VALUE column into that file, nothing else.\n")

if not SESSION_ID:
    print("ERROR: screener_session.txt is empty after cleanup -- re-check its contents.")
    sys.exit(1)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
COOKIES = {"sessionid": SESSION_ID}

TEST_SYMBOL = "RELIANCE"

print("=" * 70)
print(f"STEP 1: Company search for '{TEST_SYMBOL}'")
print("=" * 70)
search_url = f"https://www.screener.in/api/company/search/?q={TEST_SYMBOL}"
company_path = None
try:
    resp = requests.get(search_url, headers=HEADERS, cookies=COOKIES, timeout=15)
    print(f"Status: {resp.status_code}")
    # Parse BEFORE printing raw text -- so a display-only crash can
    # never block the actual data extraction the way it did last time.
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
if company_path:
    page_url = f"https://www.screener.in{company_path}"
    try:
        resp = requests.get(page_url, headers=HEADERS, cookies=COOKIES, timeout=15)
        print(f"Status: {resp.status_code}, length: {len(resp.text)} chars")
        with open("screener_test_page.html", "w", encoding="utf-8") as f:
            f.write(resp.text)
        print("Saved full HTML to screener_test_page.html for review.")

        match = re.search(r'formaction=./user/company/export/(\d+)/.', resp.text)
        if match:
            warehouse_id = match.group(1)
            print(f">>> Found export/warehouse ID: {warehouse_id}")
        else:
            print(">>> Could not find an export ID in the page HTML -- the button may be gated behind a different flow now, or the page structure has changed since this pattern was last confirmed working.")

        if "Stock P/E" in resp.text or "ROE" in resp.text:
            print(">>> Ratio-like labels found directly in the page HTML (Stock P/E / ROE present) -- may be parseable straight from the page itself, without even needing the export step.")
    except Exception:
        print("ERROR -- full traceback below (this is the real diagnostic, not a guess):")
        traceback.print_exc(file=sys.stdout)
else:
    print("Skipped -- no company path found in step 1")

print("\n" + "=" * 70)
print("STEP 3: Export endpoint")
print("=" * 70)
if warehouse_id:
    export_url = f"https://www.screener.in/user/company/export/{warehouse_id}/"
    try:
        resp = requests.get(export_url, headers=HEADERS, cookies=COOKIES, timeout=15)
        print(f"Status: {resp.status_code}")
        print(f"Content-Type: {resp.headers.get('Content-Type')}")
        print(f"Content-Length: {len(resp.content)} bytes")
        content_type = resp.headers.get("Content-Type", "")
        if "spreadsheet" in content_type or "excel" in content_type:
            with open("screener_test_export.xlsx", "wb") as f:
                f.write(resp.content)
            print(">>> Real Excel file received -- saved as screener_test_export.xlsx. Open it and check which sheet/cells actually hold P/E, ROE, Debt/Equity, etc.")
        else:
            print("Not a spreadsheet content-type -- first 500 chars of response:")
            print(resp.text[:500])
    except Exception:
        print("ERROR -- full traceback below (this is the real diagnostic, not a guess):")
        traceback.print_exc(file=sys.stdout)
else:
    print("Skipped -- no export ID found in step 2")

print("\n" + "=" * 70)
print("DONE. Paste this full output back for review.")
print("=" * 70)