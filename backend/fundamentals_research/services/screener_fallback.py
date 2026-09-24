"""
backend/fundamentals_research/services/screener_fallback.py

Wraps the EXISTING fundamentals/screener_client.py and
fundamentals/parser.py -- neither file is modified, imported as-is.
Confirmed their exact signatures by reading the real files rather than
assuming: get_session(), fetch_export_bytes(session, symbol) ->
bytes|None, parse_fundamentals(xlsx_bytes) -> dict|None with keys
company_name/current_price/market_cap_cr/latest_year/sales_cr/
net_profit_cr/eps/pe_ratio/roe_pct/debt_to_equity/opm_pct/
sales_cagr_pct.

This module's only job: call those two functions, and map their
output into this app's SourcedValue shape so financial_analysis.py
and the report builder never need to know which underlying source a
value came from.
"""
import sys
import os
import logging
from typing import Optional, Dict

# fundamentals/ is a sibling app, not a package fundamentals_research
# depends on via pip -- imported directly, matching how other apps in
# this project already cross-import (e.g. screener/views.py importing
# from trading/telegram_bot.py).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from .source_registry import SourcedValue, Source

logger = logging.getLogger('fundamentals_research.screener_fallback')


def get_screener_fundamentals(symbol: str) -> Optional[Dict[str, SourcedValue]]:
    """
    Returns None if Screener genuinely has nothing for this symbol
    (session expired, symbol not found, export failed, or the export
    format wasn't recognized) -- every one of those is already
    distinguished inside the wrapped functions themselves; this
    function doesn't need to re-derive why, only that the end result
    is "no data," which the caller (research_engine.py) already knows
    to treat as "try the next source in the fallback chain."
    """
    try:
        from fundamentals import screener_client, parser
    except ImportError as e:
        logger.warning(f"Could not import existing fundamentals/ Screener modules: {e}")
        return None

    try:
        session = screener_client.get_session()
    except screener_client.SessionExpiredError:
        logger.warning("Screener session expired -- needs a manual cookie refresh, same as the existing weekly batch job requires.")
        return None
    except Exception as e:
        logger.warning(f"Could not load Screener session: {e}")
        return None

    try:
        xlsx_bytes = screener_client.fetch_export_bytes(session, symbol)
    except Exception as e:
        logger.warning(f"Screener export fetch failed for {symbol}: {e}")
        return None

    if xlsx_bytes is None:
        return None

    try:
        parsed = parser.parse_fundamentals(xlsx_bytes)
    except Exception as e:
        logger.warning(f"Screener export parse failed for {symbol}: {e}")
        return None

    if parsed is None:
        return None

    period = str(parsed.get('latest_year')) if parsed.get('latest_year') else None

    def _sv(key):
        return SourcedValue(value=parsed.get(key), source=Source.SCREENER, period=period)

    return {
        'company_name': _sv('company_name'),
        'current_price': _sv('current_price'),
        'market_cap_cr': _sv('market_cap_cr'),
        'sales_cr': _sv('sales_cr'),
        'net_profit_cr': _sv('net_profit_cr'),
        'eps': _sv('eps'),
        'pe_ratio': _sv('pe_ratio'),
        'roe_pct': _sv('roe_pct'),
        'debt_to_equity': _sv('debt_to_equity'),
        'opm_pct': _sv('opm_pct'),
        'sales_cagr_pct': _sv('sales_cagr_pct'),
    }
