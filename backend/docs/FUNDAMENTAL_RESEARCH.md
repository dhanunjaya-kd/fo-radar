# Fundamental Research Engine

Status: **backend complete and tested. Frontend not yet built.**

## What this is

An isolated Django app (`fundamentals_research`) that produces an on-demand,
single-company fundamentals research report — separate from the existing
`fundamentals/` app (which runs a slow, full-universe weekly screening batch
job with no database models). This module has real DB models, a REST API,
and returns a report for one company in seconds, not hours.

## Setup

Add to `backend/.env` (never commit this file — it's already gitignored):

```
BHARATSTOCK_API_KEY=bsk_live_...
```

Get a free key at https://bharatstockapi.com (50 requests/day, no card
required, every endpoint unlocked on the free tier).

Already added to `INSTALLED_APPS` in `fno_sniper/settings.py` and
`fno_sniper/urls.py` (`path('api/research/', include('fundamentals_research.urls'))`).

Run migrations once:
```
python manage.py migrate fundamentals_research
```

## API

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/research/search/?q=RELIANCE` | GET | Symbol lookup, via the existing `fundamentals/symbol_master.py` |
| `/api/research/company/{symbol}/refresh/` | POST | Fetch fresh data, persist a new snapshot, generate the report |
| `/api/research/company/{symbol}/report/` | GET | The latest full report |
| `/api/research/company/{symbol}/financials/` | GET | Annual + quarterly statements |
| `/api/research/company/{symbol}/valuation/` | GET | Valuation ratios |
| `/api/research/company/{symbol}/ownership/` | GET | Shareholding pattern |
| `/api/research/company/{symbol}/news/` | GET | Recent news for this company |
| `/api/research/company/{symbol}/history/` | GET | List of past snapshots for this company |

`refresh` is synchronous (matches this project's existing pattern of daemon
threads rather than a task queue — no Celery dependency added for this).

## Architecture

```
services/
  source_registry.py     -- SourcedValue: every number carries source + retrieved_at
  bharatstock_client.py  -- HTTP client, retry/error handling
  screener_fallback.py   -- wraps the EXISTING fundamentals/screener_client.py, unmodified
  financial_analysis.py  -- pure calculation functions (CAGR, margins, ratios) -- no network, no DB
  ownership_analysis.py  -- shareholding data + promoter-change calculation
  valuation_analysis.py  -- valuation data + earnings yield / 52w-distance calculation
  news_analysis.py       -- wraps the EXISTING news/fetcher.py with a company-scoped query
  research_engine.py     -- orchestrator: fetch -> fallback -> calculate -> persist -> diff
  report_builder.py      -- turns persisted data into the narrative report (FACT/CALCULATED/INTERPRETATION)
```

Fallback chain: BharatStock (primary) → existing Screener client (secondary) →
`ResearchUnavailableError` if both fail. Never fabricates a number.

## Known limitations — read before treating this as finished

1. **Some BharatStock endpoint paths are inferred, not confirmed.** `get_stock()` and both `get_financials()` calls (annual/quarterly) were verified live by the user directly. `get_insider_trades()`, `get_bulk_deals()`, `get_block_deals()` paths came from BharatStock's own documentation text. `get_corporate_actions()` and the dedicated `get_mf_holdings()` path are best-guess REST-conventional paths, not confirmed anywhere — see `bharatstock_client.py`'s own module docstring for the exact breakdown. If a guessed endpoint 404s in production, it degrades to an empty section (never a crash, never a fabricated section) — but it won't show real data until the real path is confirmed and, if different, corrected in that one file.

2. **The nested key structure of `get_stock()`'s response is inferred from category names, not a literal JSON sample.** `normalize_stock_response()` in `bharatstock_client.py` is the single place this assumption lives — if a real call shows different key names, that's the one function to fix.

3. **No frontend yet.** The API is fully functional and tested via Django's real test client (`tests/test_api_routing.py`), but there is no React component consuming it yet.

4. **No governance/red-flag feed.** Auditor qualifications and related-party-transaction flags aren't available from any source found during the audit — `report_builder.py`'s governance section says so explicitly rather than leaving a misleading blank.

5. **Annual reports / management commentary have no API.** By design, not a gap to fix — see the original audit document for why.

## Testing

```
python manage.py test fundamentals_research
```

64 tests as of this writing, all real (mocked external calls only — zero
BharatStock/Screener/NewsAPI quota consumed by the test suite), covering:
unit tests for the calculation engine and clients, and full Django
integration tests (real database, real migrations, real HTTP requests
through the actual URL routing) for the orchestrator and API layer.

Two real bugs were caught and fixed by this test suite during development,
not by inspection:
- A year-over-year growth calculation that had the comparison backwards for newest-first data (`research_engine.py`)
- A wrong function name (`get_all_symbols` guessed vs. the real `get_nse_equity_symbols`) in `views.py`, caught by `test_api_routing.py`'s real HTTP-level test
