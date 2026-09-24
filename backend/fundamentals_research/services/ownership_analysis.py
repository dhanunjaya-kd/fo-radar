"""
backend/fundamentals_research/services/ownership_analysis.py

Thin by design -- BharatStock's get_shareholding() (via the confirmed
get_stock() response's ownership section) already returns these
fields directly; this module's job is just to wrap each one in a
SourcedValue and compute the one derived figure (promoter change)
that needs two periods to exist, not to re-derive anything BharatStock
already computed itself. Per spec Section 13: "Do not infer intent" --
this file reports numbers, never a narrative about WHY a promoter
holding changed.
"""
from typing import Dict, Any, Optional

from .source_registry import SourcedValue, Source
from . import financial_analysis as fa


def build_ownership_snapshot(bharatstock_ownership: Dict[str, Any], previous_promoter_pct: Optional[float] = None) -> Dict[str, SourcedValue]:
    """
    bharatstock_ownership: the dict returned by
    bharatstock_client.get_shareholding() -- field names are the same
    INFERRED-key caveat as normalize_stock_response() (see that
    function's docstring); this function reads via .get() defensively
    for exactly that reason.
    previous_promoter_pct: the prior snapshot's promoter_pct, if one
    exists, purely so promoter_change_pct can be computed here rather
    than pushed onto the caller.
    """
    period = bharatstock_ownership.get('as_of_quarter')

    def _sv(key):
        return SourcedValue(value=bharatstock_ownership.get(key), source=Source.BHARATSTOCK, period=period)

    promoter_pct = _sv('promoter_pct')
    promoter_change = fa._calculated(None, period)
    if promoter_pct.is_available and previous_promoter_pct is not None:
        promoter_change = fa.calculate_growth_pct(
            promoter_pct,
            SourcedValue(value=previous_promoter_pct, source=Source.BHARATSTOCK, period=None),
            period=period,
        )
        # promoter_change is expressed as an absolute percentage-point
        # move (e.g. 50.3% -> 51.1% = +0.8pp), NOT a relative growth
        # rate -- overwritten below rather than reusing
        # calculate_growth_pct's relative-% output, which would be
        # misleading for a holding percentage.
        if promoter_pct.value is not None and previous_promoter_pct is not None:
            promoter_change = SourcedValue(
                value=round(promoter_pct.value - previous_promoter_pct, 2),
                source=Source.CALCULATED, period=period,
            )

    return {
        'as_of_quarter': period,
        'promoter_pct': promoter_pct,
        'promoter_change_pct': promoter_change,
        'promoter_pledge_pct': _sv('promoter_pledge_pct'),
        'fii_pct': _sv('fii_pct'),
        'dii_pct': _sv('dii_pct'),
        'mutual_fund_pct': _sv('mutual_fund_pct'),
        'mutual_fund_scheme_count': _sv('mutual_fund_scheme_count'),
        'public_pct': _sv('public_pct'),
    }
