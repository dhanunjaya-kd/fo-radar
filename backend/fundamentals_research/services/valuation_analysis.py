"""
backend/fundamentals_research/services/valuation_analysis.py

Combines BharatStock's directly-supplied valuation fields with the
internally-calculated ones this project prefers (spec Section 12:
"prefer internally calculated metrics where raw data is reliable").
Where both exist for the same metric, BOTH are kept (not one silently
overwriting the other) -- the report builder decides how to present
a disagreement; this module's job is only to compute and tag, not to
pick a winner.
"""
from typing import Dict, Any

from .source_registry import SourcedValue, Source
from . import financial_analysis as fa


def build_valuation_snapshot(bharatstock_valuation: Dict[str, Any], bharatstock_market: Dict[str, Any]) -> Dict[str, SourcedValue]:
    """
    bharatstock_valuation: bharatstock_client.get_ratios()'s output.
    bharatstock_market: the 'market' section of normalize_stock_response()'s
    output (price, 52w range, DMAs) -- kept separate from valuation
    since they come from different logical sections of the same
    get_stock() response, per your own reported category breakdown.
    """
    def _v(key):
        return SourcedValue(value=bharatstock_valuation.get(key), source=Source.BHARATSTOCK)

    def _m(key):
        return SourcedValue(value=bharatstock_market.get(key), source=Source.BHARATSTOCK)

    price = _m('price') or _m('latest_price')
    week_52_high = _m('week_52_high') or _m('52w_high')
    pe = _v('pe')

    result = {
        'price': price,
        'market_cap': _v('market_cap') or _m('market_cap'),
        'pe': pe,
        'pb': _v('pb'),
        'peg': _v('peg'),
        'ev_ebitda': _v('ev_ebitda'),
        'price_to_sales': _v('price_to_sales'),
        'dividend_yield_pct': _v('dividend_yield'),
        'week_52_high': week_52_high,
        'week_52_low': _m('week_52_low') or _m('52w_low'),
        'dma_50': _m('dma_50') or _m('50dma'),
        'dma_200': _m('dma_200') or _m('200dma'),
        # BharatStock-supplied earnings yield if present, kept
        # separate from the internally-calculated version below --
        # never silently merged into one field (Section 7's explicit rule).
        'earnings_yield_pct_reported': _v('earnings_yield'),
    }
    result['earnings_yield_pct_calculated'] = fa.calculate_earnings_yield_pct(pe)
    result['distance_from_52w_high_pct'] = fa.calculate_distance_from_52w_high_pct(price, week_52_high)
    return result
