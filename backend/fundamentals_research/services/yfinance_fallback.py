"""
backend/fundamentals_research/services/yfinance_fallback.py

Third fallback tier: BharatStock -> Screener -> yfinance -> N/A.
Every field name and scale below is taken from a REAL, live yfinance
1.7.0 call against RELIANCE.NS (you ran this, not me -- I have no
network path to Yahoo either) -- not from yfinance's docs or my own
training data, both of which I confirmed were stale for this package
before writing this file.

SCALE WARNING, confirmed from the real output -- Yahoo mixes two
different scales in the SAME .info dict, not one consistent
convention:
    - debtToEquity (36.653) and dividendYield (0.48) are ALREADY
      percentages -- use as-is, don't multiply by 100.
    - profitMargins, operatingMargins, ebitdaMargins, revenueGrowth,
      earningsGrowth, payoutRatio, heldPercentInsiders,
      heldPercentInstitutions are FRACTIONS (0.066 = 6.6%) -- these
      DO need multiplying by 100 to match this app's convention
      (every other source in this codebase stores margins/growth/
      ownership as already-scaled percentages, e.g. BharatStock's
      promoter_holding: 72.59 means 72.59%, not 0.7259).
    Verified against real numbers, not assumed: heldPercentInsiders
    0.51798 -> 51.8%, matching RELIANCE's real-world promoter-range
    holding; debtToEquity 36.653 taken as-is (not x100, which would
    be an absurd 3665%).

OWNERSHIP CAVEAT, real and permanent, not a bug to fix: Yahoo has no
promoter/FII/DII/public split -- only insiders vs institutions
(a US-shaped model). heldPercentInsiders is used below as a labeled
PROXY for promoter holding, not presented as the same real figure
BharatStock/Screener report. No pledge data exists here at all.
"""
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger('fundamentals_research.yfinance_fallback')

# Real row labels confirmed from your live .financials/.balance_sheet/.cashflow output.
_INCOME_ROWS = {
    'revenue': 'Total Revenue', 'ebitda': 'EBITDA', 'ebit': 'EBIT',
    'net_profit': 'Net Income', 'eps': 'Diluted EPS', 'pretax_income': 'Pretax Income',
    'interest_expense': 'Interest Expense',
}
_BALANCE_ROWS = {
    'total_debt': 'Total Debt', 'net_debt': 'Net Debt', 'total_assets': 'Total Assets',
    'current_assets': 'Current Assets', 'current_liabilities': 'Current Liabilities',
    'cash': 'Cash And Cash Equivalents', 'total_equity': 'Stockholders Equity',
    'accounts_payable': 'Accounts Payable', 'accounts_receivable': 'Accounts Receivable',
    'inventory': 'Inventory',
}
_CASHFLOW_ROWS = {
    'operating_cash_flow': 'Operating Cash Flow', 'capex': 'Capital Expenditure',
    'free_cash_flow': 'Free Cash Flow', 'investing_cash_flow': 'Investing Cash Flow',
    'financing_cash_flow': 'Financing Cash Flow',
}


def _df_value(df, row_label: str, col):
    """Safe DataFrame lookup -- returns None (never NaN, never a
    crash) for a missing row or a real NaN cell, both confirmed
    present in your real output (see the 2022-03-31 column, almost
    entirely NaN for RELIANCE)."""
    if df is None or df.empty or row_label not in df.index:
        return None
    try:
        val = df.loc[row_label, col]
    except KeyError:
        return None
    if val is None:
        return None
    try:
        import math
        if isinstance(val, float) and math.isnan(val):
            return None
    except TypeError:
        pass
    return float(val)


def get_yfinance_fundamentals(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Returns None if yfinance itself is unavailable or returns nothing
    real for this symbol (never fabricates a partial result to look
    successful). On success, returns a dict shaped for
    research_engine.py's own persistence functions:
        'company': {...}, 'market': {...}, 'valuation': {...}, 'ownership': {...},
        'annual': [ {period, revenue, ebitda, ... } , ... ]  -- newest-first, matches
                   every other per-period list in this app
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed -- run: pip install yfinance")
        return None

    yf_symbol = f"{symbol.upper()}.NS"
    try:
        ticker = yf.Ticker(yf_symbol)
        info = ticker.info
    except Exception as e:
        logger.warning(f"yfinance get info failed for {yf_symbol}: {e}")
        return None

    if not info or not info.get('symbol'):
        logger.info(f"yfinance returned no real data for {yf_symbol} -- treating as unavailable, not fabricating.")
        return None

    try:
        financials = ticker.financials
        balance_sheet = ticker.balance_sheet
        cashflow = ticker.cashflow
    except Exception as e:
        logger.warning(f"yfinance financials fetch failed for {yf_symbol}: {e}")
        financials = balance_sheet = cashflow = None

    result = {
        'company': {
            'company_name': info.get('longName') or info.get('shortName'),
            'sector': info.get('sector'), 'industry': info.get('industry'),
            'exchange': 'NSE',  # info['exchange'] is really 'NSI' (Yahoo's internal code) -- normalized to the label this app uses everywhere else
        },
        'market': {
            'price': info.get('currentPrice') or info.get('regularMarketPrice'),
            'market_cap': info.get('marketCap'),  # confirmed rupees, consistent with financials -- same scale check already done for BharatStock applies here too, and this one checks out
            'week_52_high': info.get('fiftyTwoWeekHigh'), 'week_52_low': info.get('fiftyTwoWeekLow'),
            'dma_50': info.get('fiftyDayAverage'), 'dma_200': info.get('twoHundredDayAverage'),
        },
        'valuation': {
            'pe': info.get('trailingPE'), 'pb': info.get('priceToBook'), 'peg': info.get('pegRatio'),
            'ev_ebitda': info.get('enterpriseToEbitda'), 'price_to_sales': info.get('priceToSalesTrailing12Months'),
            'dividend_yield': info.get('dividendYield'),  # already a percentage, confirmed -- do not multiply
            'market_cap': info.get('marketCap'),
        },
        'ownership': {
            # PROXY, not the real Indian ownership split -- see module docstring.
            'promoter_pct_proxy': (info.get('heldPercentInsiders') * 100) if info.get('heldPercentInsiders') is not None else None,
            'institutions_pct_proxy': (info.get('heldPercentInstitutions') * 100) if info.get('heldPercentInstitutions') is not None else None,
        },
        'debt_equity_reported': info.get('debtToEquity'),  # already a percentage (36.653 = 0.3665 ratio) -- research_engine.py divides by 100 when using this
        'annual': [],
    }

    if financials is not None and not financials.empty:
        columns = list(financials.columns)  # confirmed newest-first from your real output (2026-03-31 first)
        for col in columns:
            year_label = col.strftime('%Y-%m-%d') if hasattr(col, 'strftime') else str(col)
            row = {'period': year_label}
            for key, label in _INCOME_ROWS.items():
                row[key] = _df_value(financials, label, col)
            for key, label in _BALANCE_ROWS.items():
                row[key] = _df_value(balance_sheet, label, col)
            for key, label in _CASHFLOW_ROWS.items():
                row[key] = _df_value(cashflow, label, col)
            # skip a column that's entirely empty (confirmed real -- your
            # 2022-03-31 column for RELIANCE was almost all NaN) rather
            # than persist a fiscal year with nothing real in it
            if any(v is not None for k, v in row.items() if k != 'period'):
                result['annual'].append(row)

    return result
