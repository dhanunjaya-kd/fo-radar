"""
backend/fundamentals_research/services/bharatstock_client.py

Sep 24 2026. Honest note on verification status, since this matters
for how much to trust this file without a follow-up check:

CONFIRMED live, by you, directly against your own backend (not by me --
I have no network path to bharatstockapi.com from my own environment,
confirmed by a direct blocked test):
    GET /v1/stocks/{symbol}
    GET /v1/stocks/{symbol}/financials?period_type=annual
    GET /v1/stocks/{symbol}/financials?period_type=quarterly

CONFIRMED from BharatStock's own public documentation text (not live-
tested, but seen verbatim in their docs, not guessed):
    GET /v1/insider-trades
    GET /v1/deals/bulk
    GET /v1/deals/block

INFERRED -- REST-consistent guesses, not seen anywhere, not tested:
    GET /v1/stocks/{symbol}/corporate-actions
    GET /v1/stocks/{symbol}/mf-holdings

For ratios/shareholding/mutual-fund-summary specifically: your own
verified test showed the single GET /v1/stocks/{symbol} response
already contains Valuation, Ownership, Segments, and Mutual Funds
sections alongside Company/Market data -- so get_ratios()/
get_shareholding()/get_mf_summary() below read from THAT already-
confirmed response rather than guessing at separate endpoints for
data you already showed exists there. Their exact nested key names
(e.g. response['valuation']['pe'] vs response['ratios']['pe']) are my
best reasonable guess from the category names you reported, NOT from
a literal JSON sample -- normalize_stock_response()'s own docstring
flags this precisely. The first real call against real data will
either confirm this key shape or reveal the real one; this client's
parsing is centralized in ONE function specifically so that's a
small, contained fix if the shape differs, not a rewrite.
"""
import os
import time
import logging
from typing import Optional, Dict, Any, List

import requests

logger = logging.getLogger('fundamentals_research.bharatstock')

BASE_URL = 'https://bharatstockapi.com'
DEFAULT_TIMEOUT = 15
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 1.5


class BharatStockError(Exception):
    """Base class -- mirrors the shape of errors the official
    bharatstock Python SDK itself defines (NotFoundError,
    RateLimitError, both subclassing a common base), per their own
    PyPI docs. Reimplemented here rather than depending on the
    third-party package, to keep this project's own error-handling
    conventions (matching how fyers_client.py / gamma_options_resolver.py
    already handle their own broker's errors) rather than adding a new
    exception hierarchy style."""
    pass


class AuthenticationError(BharatStockError):
    """401/403 -- bad or missing key."""
    pass


class NotFoundError(BharatStockError):
    """404 -- symbol or resource genuinely doesn't exist."""
    pass


class RateLimitError(BharatStockError):
    """429 -- daily quota or rate limit hit. Carries whatever the
    response body said about the limit/reset, when present."""
    def __init__(self, message, detail=None):
        super().__init__(message)
        self.detail = detail


class ServerError(BharatStockError):
    """5xx -- BharatStock's own problem, not a request-shape problem."""
    pass


def _get_api_key() -> str:
    """Read-on-call, not read-at-import -- so a missing key fails at
    the moment of the actual API call with a clear message, rather
    than at Django startup with a less obvious stack trace, and so
    tests can monkeypatch the environment cleanly per-test."""
    key = os.environ.get('BHARATSTOCK_API_KEY')
    if not key:
        raise AuthenticationError(
            "BHARATSTOCK_API_KEY is not set in the environment. "
            "Add it to backend/.env -- never hardcode it here."
        )
    return key


def _request(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Centralizes ALL HTTP behavior -- retry, timeout, error
    translation -- so no other function in this file duplicates a
    requests.get() call. Retries only on timeout/connection errors and
    5xx (transient); never retries 401/403/404/429, since retrying an
    identical request against those gains nothing and just burns
    quota on a 429 specifically."""
    key = _get_api_key()
    url = f"{BASE_URL}{path}"
    headers = {'X-API-Key': key}

    last_exc = None
    for attempt in range(1, MAX_RETRIES + 2):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=DEFAULT_TIMEOUT)
        except requests.exceptions.Timeout:
            last_exc = BharatStockError(f"Timeout calling {path} (attempt {attempt})")
            if attempt <= MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise last_exc
        except requests.exceptions.RequestException as e:
            last_exc = BharatStockError(f"Connection error calling {path}: {e}")
            if attempt <= MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise last_exc

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                raise BharatStockError(f"Malformed (non-JSON) response from {path}")
        if resp.status_code in (401, 403):
            # Never log/echo the key itself -- only the fact that auth failed.
            raise AuthenticationError(f"BharatStock rejected the API key (HTTP {resp.status_code}) for {path}")
        if resp.status_code == 404:
            raise NotFoundError(f"Not found: {path}")
        if resp.status_code == 429:
            detail = None
            try:
                detail = resp.json()
            except ValueError:
                detail = resp.text[:200]
            raise RateLimitError(f"Rate limited calling {path}", detail=detail)
        if 500 <= resp.status_code < 600:
            last_exc = ServerError(f"BharatStock server error {resp.status_code} on {path}")
            if attempt <= MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise last_exc
        # Any other unexpected status -- don't guess, surface it plainly.
        raise BharatStockError(f"Unexpected HTTP {resp.status_code} from {path}: {resp.text[:200]}")

    raise last_exc or BharatStockError(f"Failed calling {path} after retries")


# ---------------------------------------------------------------------------
# CONFIRMED endpoints
# ---------------------------------------------------------------------------

def get_stock(symbol: str) -> Dict[str, Any]:
    """GET /v1/stocks/{symbol} -- CONFIRMED live by you. Returns the
    raw response as-is; normalize_stock_response() below is where the
    (currently inferred) nested-key assumptions live, kept separate so
    this function itself never needs to change if only the key shape
    turns out different."""
    return _request(f'/v1/stocks/{symbol.upper()}')


def get_financials(symbol: str, period_type: str = 'annual') -> Dict[str, Any]:
    """GET /v1/stocks/{symbol}/financials?period_type=annual|quarterly
    -- CONFIRMED live by you. period_type is passed straight through,
    not validated against a fixed list here, so a future BharatStock
    addition (e.g. 'ttm') works without a code change on this side."""
    return _request(f'/v1/stocks/{symbol.upper()}/financials', params={'period_type': period_type})


def get_insider_trades(symbol: Optional[str] = None) -> Dict[str, Any]:
    """GET /v1/insider-trades -- path confirmed from BharatStock's own
    docs text. Per-ticker filtering param name is NOT confirmed (their
    docs show both per-ticker and market-wide use for this endpoint
    but didn't show the exact query param) -- passed as `symbol` as
    the most likely REST convention; if BharatStock rejects/ignores
    this param, the endpoint still returns market-wide data rather
    than erroring, so this degrades safely rather than breaking."""
    params = {'symbol': symbol.upper()} if symbol else None
    return _request('/v1/insider-trades', params=params)


def get_bulk_deals(symbol: Optional[str] = None) -> Dict[str, Any]:
    """GET /v1/deals/bulk -- path confirmed from BharatStock's own docs text."""
    params = {'symbol': symbol.upper()} if symbol else None
    return _request('/v1/deals/bulk', params=params)


def get_block_deals(symbol: Optional[str] = None) -> Dict[str, Any]:
    """GET /v1/deals/block -- path confirmed from BharatStock's own docs text."""
    params = {'symbol': symbol.upper()} if symbol else None
    return _request('/v1/deals/block', params=params)


# ---------------------------------------------------------------------------
# Derived from the CONFIRMED get_stock() response (see module docstring --
# your own verified test showed these sections already come back on that
# one call; these are thin extractors, not separate HTTP requests)
# ---------------------------------------------------------------------------

def get_ratios(symbol: str) -> Dict[str, Any]:
    """Sep 24 2026 fix: was reading raw.get('valuation') directly --
    that key never existed. Now correctly goes through
    normalize_stock_response(), which extracts these from the real
    'metrics' dict."""
    return normalize_stock_response(get_stock(symbol)).get('valuation', {})


def get_shareholding(symbol: str) -> Dict[str, Any]:
    """Same fix as get_ratios() -- was reading a raw key that never existed."""
    return normalize_stock_response(get_stock(symbol)).get('ownership', {})


def get_mf_holdings(symbol: str) -> Dict[str, Any]:
    """INFERRED path as a fallback only -- tries the dedicated
    endpoint first, falls back to the confirmed-real 'mf_holdings_summary'
    section of get_stock() (via normalize_stock_response()) if that 404s."""
    try:
        return _request(f'/v1/stocks/{symbol.upper()}/mf-holdings')
    except NotFoundError:
        return normalize_stock_response(get_stock(symbol)).get('mutual_funds', {})


# ---------------------------------------------------------------------------
# INFERRED endpoint -- not seen in any documentation text fetched so far
# ---------------------------------------------------------------------------

def get_corporate_actions(symbol: str) -> Dict[str, Any]:
    """INFERRED path, not confirmed anywhere. If this 404s in practice,
    fallback_screener.py's corporate-action handling (Screener does
    show dividends/splits/bonus on its export) is the real fallback --
    see services/screener_fallback.py."""
    try:
        return _request(f'/v1/stocks/{symbol.upper()}/corporate-actions')
    except NotFoundError:
        return {}


def normalize_stock_response(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Single place where this client's assumptions about get_stock()'s
    NESTED key structure live. Built from the CATEGORY LIST your live
    test reported (company/market/valuation/financial quality/balance
    sheet/cash flow/ownership/segments/mutual funds), not from a
    literal JSON sample -- I do not have one. The keys guessed below
    Sep 24 2026 -- REWRITTEN against a real, verified response (WIPRO,
    fetched live through your own key -- see chat history for the full
    raw dump this was built from, not guessed a second time).

    Real shape, confirmed: BharatStock does NOT split valuation/
    ownership/balance-sheet into separate top-level objects the way
    the earlier guess assumed. Almost everything (P/E, ROE, D/E,
    ownership %, CFO/PAT, margins -- ~70 fields) lives flat inside one
    `metrics` dict. `latest_price` holds today's OHLC. `mf_holdings_
    summary` holds mutual fund data. There is no `segments` key at
    this endpoint at all -- segment revenue/results come back per-
    period inside get_financials() instead (see research_engine.py).

    Real bug caught and fixed here, not just a rename: `market_cap`
    appears in TWO places with TWO DIFFERENT UNITS -- the top-level
    `raw['market_cap']` is in raw rupees (matches revenue/ebitda/
    net_profit's own units everywhere else in this API), but
    `metrics['market_cap']` is in CRORES. Using the wrong one would
    have silently corrupted every market-cap-derived ratio by a
    factor of 10,000,000. The top-level (rupee) one is used below,
    for consistency with every other rupee-denominated figure in this
    codebase.

    No promoter-pledge field exists anywhere in this real response --
    left genuinely unavailable (None) below rather than assumed.
    """
    metrics = raw.get('metrics') or {}
    latest_price = raw.get('latest_price') or {}
    mf = raw.get('mf_holdings_summary') or {}
    price = metrics.get('price') or latest_price.get('close')

    def _dma_from_pct(pct):
        """price_vs_NNdma_pct = (price - dmaNN) / dmaNN * 100, so
        dmaNN = price / (1 + pct/100) -- a real derivation from two
        genuinely-reported fields, not a fabricated number, but
        flagged as CALCULATED (not BharatStock-reported) at the call
        site in research_engine.py for exactly that reason."""
        if price is None or pct is None:
            return None
        try:
            return round(price / (1 + pct / 100.0), 2)
        except ZeroDivisionError:
            return None

    return {
        'symbol': raw.get('symbol'),
        'company_name': raw.get('company_name'),
        'isin': raw.get('isin'),
        'sector': raw.get('sector'),
        'industry': raw.get('industry'),
        'exchange': raw.get('exchange'),
        'listing_date': raw.get('listing_date'),
        'market': {
            'price': price,
            'market_cap': raw.get('market_cap'),  # rupees -- NOT metrics['market_cap'], which is crores; see docstring
            'week_52_high': metrics.get('high_52w'),
            'week_52_low': metrics.get('low_52w'),
            'dma_50': _dma_from_pct(metrics.get('price_vs_50dma_pct')),
            'dma_200': _dma_from_pct(metrics.get('price_vs_200dma_pct')),
        },
        'valuation': {
            'pe': metrics.get('pe_ratio'), 'pb': metrics.get('pb_ratio'), 'peg': metrics.get('peg_ratio'),
            'ev_ebitda': metrics.get('ev_to_ebitda'), 'price_to_sales': metrics.get('price_to_sales'),
            'dividend_yield': metrics.get('dividend_yield'), 'earnings_yield': metrics.get('earnings_yield'),
            'market_cap': raw.get('market_cap'),
        },
        'ownership': {
            'as_of_quarter': metrics.get('computed_at'),  # a computation date, not a real fiscal-quarter label -- BharatStock doesn't return one here
            'promoter_pct': metrics.get('promoter_holding'),
            'promoter_change_pct': metrics.get('promoter_holding_change_qoq'),
            'promoter_pledge_pct': None,  # confirmed absent from this endpoint's real response -- not guessed as 0
            'fii_pct': metrics.get('fii_holding'), 'dii_pct': metrics.get('dii_holding'),
            'mutual_fund_pct': metrics.get('mutual_funds_holding'), 'public_pct': metrics.get('public_holding'),
            'mutual_fund_scheme_count': mf.get('total_schemes'),
        },
        'financial_summary': metrics,  # raw metrics kept accessible for anything not explicitly mapped above
        'segments': [],  # confirmed not present at this endpoint -- real segment data comes from get_financials(), handled separately
        'mutual_funds': mf,
    }
