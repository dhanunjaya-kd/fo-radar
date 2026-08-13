"""
backend/fundamentals/screener_client.py

Authenticates to Screener.in using your own logged-in session cookie
and fetches a company's real financial-data export (.xlsx), reusing
the exact mechanism confirmed working live in check_screener_fundamentals.py:
search -> company page (which sets a fresh Django CSRF cookie) ->
authenticated POST to the export endpoint. Session/CSRF handling is
fully automatic via requests.Session() -- callers just need a valid
sessionid sitting in screener_session.txt.

Screener has no public API (confirmed via their own docs -- "we don't
provide APIs on Screener"); this automates their own "Export to Excel"
feature instead, which is a real, sanctioned first-party mechanism,
not scraping raw HTML.
"""
import re
import requests

SESSION_FILE = "screener_session.txt"  # same file/folder convention as the rest of this project (e.g. fyers_auth.json)


def _load_session_id(path=SESSION_FILE):
    """Reads and sanitizes the session value -- takes only the first
    whitespace-separated field (discards any extra pasted columns
    entirely rather than mashing them together) then strips anything
    that isn't a plausible cookie character. This exact defensive
    cleanup was needed live: a raw copy-paste from DevTools initially
    grabbed extra table content that broke outgoing HTTP headers."""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    first_line = raw.splitlines()[0] if raw.splitlines() else ""
    first_field = re.split(r'[\s\t]+', first_line.strip())[0] if first_line.strip() else ""
    return re.sub(r'[^A-Za-z0-9_\-\.]', '', first_field)


def get_session(path=SESSION_FILE):
    """One authenticated requests.Session(), meant to be reused across
    many company lookups -- the CSRF token gets captured automatically
    on the first company-page fetch and persists for subsequent POSTs,
    so callers should create ONE session and pass it to every
    fetch_export_bytes() call in a batch, not a fresh one per stock."""
    session_id = _load_session_id(path)
    if not session_id:
        raise RuntimeError(f"{path} is empty or unreadable -- re-copy your sessionid cookie value into it.")
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    session.cookies.set("sessionid", session_id, domain="www.screener.in")
    return session


def find_company_path(session, symbol):
    """Search Screener for a ticker, return its company page path (e.g.
    '/company/RELIANCE/consolidated/') or None if not found. Screener's
    search can return multiple partial-name matches (e.g. searching
    RELIANCE also returns Reliance Power, Reliance Infra, etc.) --
    takes the first result, which is Screener's own best match."""
    try:
        resp = session.get(f"https://www.screener.in/api/company/search/?q={symbol}", timeout=15)
        if resp.status_code != 200:
            return None
        results = resp.json()
        return results[0].get("url") if results else None
    except Exception:
        return None


def fetch_export_bytes(session, symbol):
    """
    Full pipeline for one symbol: search -> company page (also picks up
    the CSRF token Django sets) -> authenticated POST to the export
    endpoint. Returns the raw .xlsx bytes, or None if any step fails
    (bad symbol, no listed export, request rejected, etc.) -- callers
    must treat None as "no data for this symbol," never substitute a
    guess in its place.
    """
    company_path = find_company_path(session, symbol)
    if not company_path:
        return None

    page_url = f"https://www.screener.in{company_path}"
    try:
        resp = session.get(page_url, timeout=15)
        if resp.status_code != 200:
            return None

        match = re.search(r'formaction=./user/company/export/(\d+)/.', resp.text)
        if not match:
            return None
        warehouse_id = match.group(1)

        csrf_token = session.cookies.get("csrftoken")
        export_url = f"https://www.screener.in/user/company/export/{warehouse_id}/"
        post_data = {"csrfmiddlewaretoken": csrf_token} if csrf_token else {}
        resp = session.post(export_url, data=post_data, headers={"Referer": page_url}, timeout=15)

        content_type = resp.headers.get("Content-Type", "")
        if "spreadsheet" not in content_type and "excel" not in content_type:
            return None
        return resp.content
    except Exception:
        return None
