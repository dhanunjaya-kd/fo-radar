# Fundamental Research — Metric-to-Source Audit

Sep 26 2026. Every metric the Fundamental Research page displays, traced to its
actual source, raw field, unit, and fallback behavior. Built by reading the
actual code (`services/yfinance_fallback.py`, `services/bharatstock_client.py`,
`services/screener_fallback.py`, `services/research_engine.py`,
`services/financial_analysis.py`), not assumed.

**Source priority (confirmed in `research_engine.py`)**: yfinance → BharatStock → Screener.
The whole snapshot uses ONE primary source per research run — sources are never
silently mixed metric-by-metric within one snapshot's core financials.

## Company Overview

| Metric | Source | Raw field | Fallback |
|---|---|---|---|
| Company name | Primary source | yfinance: `info.longName`; BharatStock: `company_name`; Screener: `company_name` | Falls to next source |
| Sector / Industry | Primary source | yfinance: `info.sector`/`info.industry`; BharatStock: `sector`/`industry` | Screener doesn't provide this — stays from whichever prior source populated `ResearchCompany` |
| Exchange | Primary source | yfinance: hardcoded `'NSE'` (Yahoo's own `exchange` field is `'NSI'`, an internal code, normalized) | BharatStock: `exchange` field directly |

## Financial Snapshot (per fiscal year, `FinancialSnapshot` model)

| Metric | yfinance field | BharatStock field | Unit | Calculated? |
|---|---|---|---|---|
| Revenue | `.financials` row `Total Revenue` | `get_financials()` → `revenue` | Raw INR | No — reported |
| EBITDA | `.financials` row `EBITDA` | `revenue`-period `ebitda` | Raw INR | No — reported |
| PAT | `.financials` row `Net Income` | `net_profit` | Raw INR | No — reported |
| EPS | `.financials` row `Diluted EPS` | `eps` | Rupees/share | No — reported |
| Revenue growth YoY % | — | — | % | **Yes** — `financial_analysis.calculate_growth_pct()`, current vs. prior period |
| EBITDA margin % | — | — | % | **Yes** — EBITDA/Revenue × 100 |
| PAT margin % | — | — | % | **Yes** — PAT/Revenue × 100 |
| ROE % | — | — | % | **Yes** — PAT/Total Equity × 100 |

## Balance Sheet (`BalanceSheetSnapshot`)

| Metric | yfinance field | BharatStock field | Calculated? |
|---|---|---|---|
| Total Debt | `.balance_sheet` row `Total Debt` | period `borrowings_current` + `borrowings_non_current` (summed — no single field) | No |
| Cash | `.balance_sheet` row `Cash And Cash Equivalents` | `cash_and_cash_equivalents` | No |
| Total Equity | `.balance_sheet` row `Stockholders Equity` | `total_equity` | No |
| Net Debt | — | — | **Yes** — Total Debt − Cash |
| Debt/Equity | — | — | **Yes** — Total Debt / Total Equity |
| Current Ratio | — | — | **Yes** — Current Assets / Current Liabilities |

## Cash Flow (`CashFlowSnapshot`)

| Metric | yfinance field | BharatStock field | Sign convention |
|---|---|---|---|
| Operating CF | `.cashflow` row `Operating Cash Flow` | `cash_flow_operating` | Both positive-inflow |
| Capex | `.cashflow` row `Capital Expenditure` | `capex` | **yfinance: negative (outflow). BharatStock: positive.** `calculate_free_cash_flow()` takes `abs()` specifically to handle both. |
| Free Cash Flow | — | — | **Calculated** — Operating CF − \|Capex\| |
| CFO/PAT | — | — | **Calculated** — Operating CF / PAT |
| Capex Intensity % | — | — | **Calculated** — \|Capex\| / Revenue × 100 |

## Ownership (`OwnershipSnapshot`) — real, confirmed gap

| Metric | yfinance | BharatStock |
|---|---|---|
| Promoter % | **Not populated. yfinance has no promoter/FII/DII concept — only `heldPercentInsiders`, a different US-style category, deliberately never mapped here.** | `promoter_holding` |
| FII / DII % | Not available at all from yfinance | `fii_holding` / `dii_holding` |
| Promoter pledge % | Not available | Not available either — confirmed absent from BharatStock's real response too |

**Practical consequence of yfinance-primary**: ownership is unavailable on most research pulls now. It only appears when yfinance fails and this falls through to BharatStock. Verified with a dedicated test (`test_falls_through_to_bharatstock_when_yfinance_fails`).

## Valuation (`ValuationSnapshot`)

| Metric | yfinance field | BharatStock field | Label |
|---|---|---|---|
| P/E | `info.trailingPE` | `pe_ratio` | **Trailing**, not forward — yfinance's `forwardPE` is a separate, unused field |
| P/B | `info.priceToBook` | `pb_ratio` | — |
| 52W High/Low | `info.fiftyTwoWeekHigh/Low` | `metrics.high_52w`/`low_52w` | — |
| Dividend Yield | `info.dividendYield` (already a %, not a fraction — confirmed via real testing) | `dividend_yield` | — |

## Segments (`SegmentSnapshot`) — the GAIL finding

| Field | Source | Confirmed reconciliation behavior |
|---|---|---|
| `segment_revenue` | BharatStock only (yfinance has no segment data at all) | **Reported before inter-segment eliminations for at least GAIL** — confirmed via GAIL's own published Q1 FY27 results ("segment revenue... Rs 52,091 crore, while inter-segment adjustments resulted in consolidated revenue... of Rs 41,350 crore"). This app has no elimination figure to back this out, so it isn't estimated — the UI shows a reconciliation warning instead. |

## Technical Indicators (`technical_analysis.py`) — separate module, not part of the fundamental snapshot

| Metric | Source | Notes |
|---|---|---|
| RSI, MACD, ADX, EMA20/50/200, ATR, support/resistance | Reused directly from `screener/views.py`'s `_compute_indicators()` — the same engine Sniper Signals uses | Not reimplemented; fetched fresh per request via `screener/fyers_client.py get_history()` |
| Trend classification | `technical_analysis.classify_trend()` | Deterministic rule table, not an LLM call |

## AI-Generated Content (`llm_narrative.py`)

| Section | Grounding | Fallback |
|---|---|---|
| Financial/balance sheet/cash flow/ownership/valuation notes | `build_fact_sheet()` — only the numbers already in the DB, nothing fetched fresh for narration | Template-based (`report_builder.py`) if the LLM call fails, is malformed, or contains a banned term |
| Chat Q&A | Same fact sheet, plus conversation history round-tripped from the frontend | Returns an honest "AI service unavailable" string, never silent |

## Known limitations (real, not yet resolved)

- No metric anywhere is labeled by exact reporting period consistency check across sources (e.g., a BharatStock annual figure and a yfinance valuation figure from different days aren't cross-validated against each other for date coherence).
- Freshness tracking (`freshness.py`) assesses `retrieved_at` recency, not whether a *newer* fiscal period should exist by now — the spec's own instruction not to flag quarterly data as stale for not updating daily means this app doesn't attempt to guess a company's exact reporting calendar.
- Segment reconciliation is confirmed for GAIL specifically; not independently re-verified against every other company's own segment reporting convention.
