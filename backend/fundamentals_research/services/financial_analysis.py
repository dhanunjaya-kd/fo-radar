"""
backend/fundamentals_research/services/financial_analysis.py

Deterministic calculations only -- per spec Section 9 ("Do NOT let an
LLM invent financial analysis"). Every function here is pure: same
inputs always produce the same output, no network calls, no randomness.

Convention followed throughout: every function takes and returns
SourcedValue objects, not bare numbers. A None input propagates to a
None output automatically (never a crash, never a fabricated zero) --
this is what Section 27's "if one section fails, the report should
NOT crash" actually looks like at the function level, not just at the
top-level orchestrator.
"""
from typing import Optional
from decimal import Decimal, InvalidOperation

from .source_registry import SourcedValue, Source


def _to_decimal(value) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _calculated(value, period: Optional[str] = None) -> SourcedValue:
    return SourcedValue(value=value, source=Source.CALCULATED, period=period)


def calculate_growth_pct(current: SourcedValue, previous: SourcedValue, period: Optional[str] = None) -> SourcedValue:
    """Works for YoY or QoQ alike -- the caller decides what 'current'
    and 'previous' mean (consecutive years vs consecutive quarters);
    this function doesn't need to know which."""
    cur = _to_decimal(current.value if current else None)
    prev = _to_decimal(previous.value if previous else None)
    if cur is None or prev is None or prev == 0:
        return _calculated(None, period)
    return _calculated(round(float((cur - prev) / abs(prev) * 100), 2), period)


def calculate_cagr(start_value: SourcedValue, end_value: SourcedValue, years: float, period: Optional[str] = None) -> SourcedValue:
    """Revenue/PAT/EPS/FCF CAGR per spec Section 9. Returns None
    (never a fabricated number) for a negative start value, a zero
    start value, or fewer than 1 full year -- a CAGR is mathematically
    undefined or meaningless in those cases, not just 'hard to
    compute'."""
    start = _to_decimal(start_value.value if start_value else None)
    end = _to_decimal(end_value.value if end_value else None)
    if start is None or end is None or start <= 0 or years is None or years < 1:
        return _calculated(None, period)
    try:
        cagr = (float(end) / float(start)) ** (1.0 / years) - 1.0
    except (ZeroDivisionError, ValueError):
        return _calculated(None, period)
    return _calculated(round(cagr * 100, 2), period)


def calculate_margin_pct(numerator: SourcedValue, denominator: SourcedValue, period: Optional[str] = None) -> SourcedValue:
    """EBITDA margin, PAT margin, FCF margin -- all the same shape:
    numerator / revenue * 100."""
    num = _to_decimal(numerator.value if numerator else None)
    den = _to_decimal(denominator.value if denominator else None)
    if num is None or den is None or den == 0:
        return _calculated(None, period)
    return _calculated(round(float(num / den * 100), 2), period)


def calculate_roe_pct(pat: SourcedValue, equity: SourcedValue, period: Optional[str] = None) -> SourcedValue:
    p = _to_decimal(pat.value if pat else None)
    e = _to_decimal(equity.value if equity else None)
    if p is None or e is None or e <= 0:
        return _calculated(None, period)
    return _calculated(round(float(p / e * 100), 2), period)


def calculate_roce_pct(ebit: SourcedValue, capital_employed: SourcedValue, period: Optional[str] = None) -> SourcedValue:
    """Capital Employed = Total Assets - Current Liabilities (standard
    definition) -- the caller is responsible for supplying that
    figure already computed; this function just does the division, to
    keep it testable independent of how capital_employed was derived."""
    eb = _to_decimal(ebit.value if ebit else None)
    ce = _to_decimal(capital_employed.value if capital_employed else None)
    if eb is None or ce is None or ce <= 0:
        return _calculated(None, period)
    return _calculated(round(float(eb / ce * 100), 2), period)


def calculate_debt_equity(total_debt: SourcedValue, equity: SourcedValue, period: Optional[str] = None) -> SourcedValue:
    d = _to_decimal(total_debt.value if total_debt else None)
    e = _to_decimal(equity.value if equity else None)
    if d is None or e is None or e <= 0:
        return _calculated(None, period)
    return _calculated(round(float(d / e), 3), period)


def calculate_net_debt(total_debt: SourcedValue, cash: SourcedValue, period: Optional[str] = None) -> SourcedValue:
    d = _to_decimal(total_debt.value if total_debt else None)
    c = _to_decimal(cash.value if cash else None)
    if d is None or c is None:
        return _calculated(None, period)
    return _calculated(round(float(d - c), 2), period)


def calculate_interest_coverage(ebit: SourcedValue, interest_expense: SourcedValue, period: Optional[str] = None) -> SourcedValue:
    eb = _to_decimal(ebit.value if ebit else None)
    ie = _to_decimal(interest_expense.value if interest_expense else None)
    if eb is None or ie is None or ie == 0:
        return _calculated(None, period)
    return _calculated(round(float(eb / ie), 2), period)


def calculate_current_ratio(current_assets: SourcedValue, current_liabilities: SourcedValue, period: Optional[str] = None) -> SourcedValue:
    ca = _to_decimal(current_assets.value if current_assets else None)
    cl = _to_decimal(current_liabilities.value if current_liabilities else None)
    if ca is None or cl is None or cl == 0:
        return _calculated(None, period)
    return _calculated(round(float(ca / cl), 3), period)


def calculate_working_capital(current_assets: SourcedValue, current_liabilities: SourcedValue, period: Optional[str] = None) -> SourcedValue:
    ca = _to_decimal(current_assets.value if current_assets else None)
    cl = _to_decimal(current_liabilities.value if current_liabilities else None)
    if ca is None or cl is None:
        return _calculated(None, period)
    return _calculated(round(float(ca - cl), 2), period)


def calculate_free_cash_flow(cfo: SourcedValue, capex: SourcedValue, period: Optional[str] = None) -> SourcedValue:
    """Capex is expected as a positive number (spend), subtracted from
    CFO -- caller's responsibility to normalize sign; documented here
    since a sign-flip bug here would silently corrupt every FCF-derived
    metric downstream (FCF margin, FCF yield, FCF CAGR)."""
    c = _to_decimal(cfo.value if cfo else None)
    x = _to_decimal(capex.value if capex else None)
    if c is None or x is None:
        return _calculated(None, period)
    return _calculated(round(float(c - abs(x)), 2), period)


def calculate_cfo_to_pat(cfo: SourcedValue, pat: SourcedValue, period: Optional[str] = None) -> SourcedValue:
    """Cash-flow quality check per spec Section 12's exact example
    ('Operating cash flow was lower than reported net profit') --
    a ratio well below 1.0 is the factual signal that flags that
    sentence, computed here rather than hardcoded as a rule."""
    c = _to_decimal(cfo.value if cfo else None)
    p = _to_decimal(pat.value if pat else None)
    if c is None or p is None or p == 0:
        return _calculated(None, period)
    return _calculated(round(float(c / p), 3), period)


def calculate_capex_intensity_pct(capex: SourcedValue, revenue: SourcedValue, period: Optional[str] = None) -> SourcedValue:
    x = _to_decimal(capex.value if capex else None)
    r = _to_decimal(revenue.value if revenue else None)
    if x is None or r is None or r == 0:
        return _calculated(None, period)
    return _calculated(round(float(abs(x) / r * 100), 2), period)


def calculate_distance_from_52w_high_pct(price: SourcedValue, week_52_high: SourcedValue, period: Optional[str] = None) -> SourcedValue:
    p = _to_decimal(price.value if price else None)
    h = _to_decimal(week_52_high.value if week_52_high else None)
    if p is None or h is None or h == 0:
        return _calculated(None, period)
    return _calculated(round(float((p - h) / h * 100), 2), period)


def calculate_fcf_yield_pct(fcf: SourcedValue, market_cap: SourcedValue, period: Optional[str] = None) -> SourcedValue:
    f = _to_decimal(fcf.value if fcf else None)
    m = _to_decimal(market_cap.value if market_cap else None)
    if f is None or m is None or m == 0:
        return _calculated(None, period)
    return _calculated(round(float(f / m * 100), 2), period)


def calculate_earnings_yield_pct(pe: SourcedValue, period: Optional[str] = None) -> SourcedValue:
    """Earnings yield is just the inverse of P/E -- kept as its own
    named function (rather than inlined at every call site) since the
    spec lists it as a distinct metric (Section 6/14) and a reader of
    the report shouldn't have to know that fact to trust the number."""
    pe_val = _to_decimal(pe.value if pe else None)
    if pe_val is None or pe_val == 0:
        return _calculated(None, period)
    return _calculated(round(float(100 / pe_val), 2), period)
