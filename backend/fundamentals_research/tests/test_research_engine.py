"""
backend/fundamentals_research/tests/test_research_engine.py

Real Django TestCase -- uses an actual (test) database, actual ORM
writes, actual migrations. Only the external calls (BharatStock,
Screener, News) are mocked, per spec Section 29: never consume real
API quota in tests. This is the most important test file in this app
-- it's the only one that proves the full pipeline (fetch -> fallback
-> calculate -> persist -> diff) actually works together, not just
that each piece works alone.
"""
from unittest.mock import patch, MagicMock
from django.test import TestCase

from fundamentals_research.models import (
    ResearchCompany, ResearchSnapshot, FinancialSnapshot, BalanceSheetSnapshot,
    CashFlowSnapshot, ValuationSnapshot, OwnershipSnapshot,
)
from fundamentals_research.services import research_engine as re
from fundamentals_research.services.source_registry import SourcedValue, Source


def _fake_bharatstock_stock_response():
    """Sep 24 2026: rewritten to the REAL raw shape (confirmed live,
    your WIPRO call) -- this is what get_stock() actually returns,
    BEFORE normalize_stock_response() processes it. The mock below
    patches get_stock() only, so normalize_stock_response() still runs
    for real inside the test -- this is what makes these tests catch a
    real mapping bug instead of just testing themselves."""
    return {
        'symbol': 'RELIANCE', 'company_name': 'Reliance Industries Limited', 'isin': 'INE002A01018',
        'sector': 'Energy', 'industry': 'Refineries', 'exchange': 'NSE', 'listing_date': '1977-11-29',
        'market_cap': 18543210000000.0,  # rupees -- top-level, real unit confirmed live
        'latest_price': {'close': 1370.5},
        'metrics': {
            'price': 1370.5, 'high_52w': 1608.8, 'low_52w': 1201.4,
            'pe_ratio': 24.1, 'pb_ratio': 2.3, 'peg_ratio': 1.8, 'ev_to_ebitda': 12.5,
            'price_to_sales': 2.1, 'dividend_yield': 0.4,
            'promoter_holding': 50.3, 'fii_holding': 22.1, 'dii_holding': 15.6,
            'public_holding': 12.0, 'mutual_funds_holding': 8.2, 'computed_at': '2026-09-24',
        },
        'mf_holdings_summary': {'total_schemes': 302},
    }


def _fake_financials_annual(revenue=900000, pat=74000):
    """Real shape confirmed live: {"data": [...], "pagination": {...}},
    newest-first, every field flat on each row -- P&L, balance sheet,
    and cash flow all together, not in separate sub-objects."""
    return {'data': [
        {
            'fiscal_year': 'FY2025-26', 'quarter': None, 'revenue': revenue, 'ebitda': 150000,
            'net_profit': pat, 'eps': 54.7, 'total_equity': 800000,
            'total_assets': 1200000, 'current_assets': 400000, 'current_liabilities': 200000,
            'cash_and_cash_equivalents': 50000, 'borrowings_current': 100000, 'borrowings_non_current': 200000,
            'cash_flow_operating': 120000, 'cash_flow_investing': -40000, 'cash_flow_financing': -30000, 'capex': 60000,
            'segment_revenue': [{'segment': 'Oil to Chemicals', 'value': 500000}, {'segment': 'Retail', 'value': 300000}],
            'segment_results': [{'segment': 'Oil to Chemicals', 'value': 45000}, {'segment': 'Retail', 'value': 22000}],
        },
        {
            'fiscal_year': 'FY2024-25', 'quarter': None, 'revenue': 850000, 'ebitda': 140000,
            'net_profit': 68000, 'eps': 50.3, 'total_equity': 750000,
            'total_assets': 1100000, 'current_assets': 380000, 'current_liabilities': 190000,
            'cash_and_cash_equivalents': 45000, 'borrowings_current': 95000, 'borrowings_non_current': 190000,
            'cash_flow_operating': 110000, 'cash_flow_investing': -35000, 'cash_flow_financing': -28000, 'capex': 55000,
            'segment_revenue': [], 'segment_results': [],
        },
    ], 'pagination': {'page': 1, 'page_size': 20, 'total_items': 2, 'total_pages': 1}}


def _fake_financials_quarterly():
    return {'data': [
        {'fiscal_year': '2026-27', 'quarter': 'Q1', 'revenue': 230000, 'net_profit': 19000, 'eps': 14.1},
        {'fiscal_year': '2025-26', 'quarter': 'Q4', 'revenue': 225000, 'net_profit': 18500, 'eps': 13.7},
    ], 'pagination': {'page': 1, 'page_size': 20, 'total_items': 2, 'total_pages': 1}}


class TestRunResearchBharatStockPath(TestCase):
    @patch('fundamentals_research.services.research_engine.na.get_company_news', return_value=[])
    @patch('fundamentals_research.services.research_engine.bsc.get_stock', return_value=_fake_bharatstock_stock_response())
    @patch('fundamentals_research.services.research_engine.yff.get_yfinance_fundamentals', return_value=None)
    def test_creates_company_and_full_snapshot(self, mock_yfinance, mock_stock, mock_news):
        with patch('fundamentals_research.services.research_engine.bsc.get_financials') as mock_fin, \
             patch('fundamentals_research.services.research_engine.bsc.get_insider_trades', return_value={'trades': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_bulk_deals', return_value={'deals': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_block_deals', return_value={'deals': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_corporate_actions', return_value={'actions': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_mf_holdings', return_value={}):
            mock_fin.side_effect = lambda symbol, period_type: _fake_financials_annual() if period_type == 'annual' else _fake_financials_quarterly()

            snapshot, what_changed, primary_source = re.run_research('RELIANCE')

        self.assertEqual(primary_source, Source.BHARATSTOCK)
        self.assertIsNone(what_changed)  # first-ever snapshot -- no previous to diff against

        company = ResearchCompany.objects.get(symbol='RELIANCE')
        self.assertEqual(company.company_name, 'Reliance Industries Limited')
        self.assertEqual(company.sector, 'Energy')

        financials = FinancialSnapshot.objects.filter(snapshot=snapshot).order_by('-fiscal_year')
        self.assertEqual(financials.count(), 2)
        latest = financials.first()
        self.assertEqual(latest.fiscal_year, 'FY2025-26')
        self.assertEqual(float(latest.revenue), 900000.0)
        # verify a REAL calculation happened, not just a copy: EBITDA margin = 150000/900000*100
        self.assertAlmostEqual(float(latest.ebitda_margin_pct), 16.67, places=1)
        # revenue growth YoY = (900000-850000)/850000*100
        self.assertAlmostEqual(float(latest.revenue_growth_yoy_pct), 5.88, places=1)

        # Sep 24 2026: now correctly one row per fiscal year (matches
        # real multi-year data confirmed live) -- fetch the latest,
        # not .get() which now correctly errors on >1 row.
        bs = BalanceSheetSnapshot.objects.filter(snapshot=snapshot).order_by('-fiscal_year').first()
        self.assertAlmostEqual(float(bs.debt_equity), 0.375, places=2)  # 300000/800000
        self.assertAlmostEqual(float(bs.net_debt), 250000.0)  # 300000-50000

        cf = CashFlowSnapshot.objects.filter(snapshot=snapshot).order_by('-fiscal_year').first()
        self.assertAlmostEqual(float(cf.free_cash_flow), 60000.0)  # 120000-60000

        val = ValuationSnapshot.objects.get(snapshot=snapshot)
        self.assertEqual(float(val.pe), 24.1)
        # earnings yield calculated = 100/pe = 100/24.1
        self.assertAlmostEqual(float(val.earnings_yield_pct), 4.15, places=1)

        own = OwnershipSnapshot.objects.get(snapshot=snapshot)
        self.assertEqual(float(own.promoter_pct), 50.3)
        self.assertIsNone(own.promoter_change_pct)  # no previous snapshot to compare against yet

    @patch('fundamentals_research.services.research_engine.na.get_company_news', return_value=[])
    @patch('fundamentals_research.services.research_engine.yff.get_yfinance_fundamentals', return_value=None)
    def test_second_snapshot_computes_what_changed(self, mock_yfinance, mock_news):
        with patch('fundamentals_research.services.research_engine.bsc.get_stock', return_value=_fake_bharatstock_stock_response()), \
             patch('fundamentals_research.services.research_engine.bsc.get_financials') as mock_fin, \
             patch('fundamentals_research.services.research_engine.bsc.get_insider_trades', return_value={'trades': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_bulk_deals', return_value={'deals': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_block_deals', return_value={'deals': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_corporate_actions', return_value={'actions': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_mf_holdings', return_value={}):
            mock_fin.side_effect = lambda symbol, period_type: _fake_financials_annual(revenue=900000, pat=74000) if period_type == 'annual' else _fake_financials_quarterly()
            re.run_research('RELIANCE')  # first snapshot

            # Second call: revenue genuinely changed (simulating a real refresh later)
            mock_fin.side_effect = lambda symbol, period_type: _fake_financials_annual(revenue=950000, pat=80000) if period_type == 'annual' else _fake_financials_quarterly()
            snapshot2, what_changed, _ = re.run_research('RELIANCE', triggered_by='refresh')

        self.assertIsNotNone(what_changed)
        self.assertIn('revenue', what_changed)
        self.assertEqual(what_changed['revenue']['previous'], 900000.0)
        self.assertEqual(what_changed['revenue']['current'], 950000.0)
        self.assertAlmostEqual(what_changed['revenue']['change_pct'], 5.56, places=1)
        # confirm this really is a SECOND, separate snapshot, not an overwrite of the first
        self.assertEqual(ResearchSnapshot.objects.filter(company__symbol='RELIANCE').count(), 2)


class TestRunResearchScreenerFallback(TestCase):
    @patch('fundamentals_research.services.research_engine.na.get_company_news', return_value=[])
    @patch('fundamentals_research.services.research_engine.bsc.get_stock', side_effect=re.bsc.BharatStockError("simulated outage"))
    @patch('fundamentals_research.services.research_engine.sf.get_screener_fundamentals')
    @patch('fundamentals_research.services.research_engine.yff.get_yfinance_fundamentals', return_value=None)
    def test_falls_back_to_screener_when_bharatstock_fully_down(self, mock_yfinance, mock_screener, mock_stock, mock_news):
        mock_screener.return_value = {
            'company_name': SourcedValue('Reliance Industries', Source.SCREENER, period='Mar-25'),
            'current_price': SourcedValue(1370.5, Source.SCREENER, period='Mar-25'),
            'market_cap_cr': SourcedValue(1854321.0, Source.SCREENER, period='Mar-25'),
            'sales_cr': SourcedValue(900000.0, Source.SCREENER, period='Mar-25'),
            'net_profit_cr': SourcedValue(74000.0, Source.SCREENER, period='Mar-25'),
            'eps': SourcedValue(54.7, Source.SCREENER, period='Mar-25'),
            'pe_ratio': SourcedValue(21.97, Source.SCREENER, period='Mar-25'),
            'roe_pct': SourcedValue(8.93, Source.SCREENER, period='Mar-25'),
            'debt_to_equity': SourcedValue(0.446, Source.SCREENER, period='Mar-25'),
            'opm_pct': SourcedValue(17.2, Source.SCREENER, period='Mar-25'),
            'sales_cagr_pct': SourcedValue(14.84, Source.SCREENER, period='Mar-25'),
        }
        snapshot, what_changed, primary_source = re.run_research('RELIANCE')
        self.assertEqual(primary_source, Source.SCREENER)

        fin = FinancialSnapshot.objects.get(snapshot=snapshot)
        self.assertEqual(fin.source, Source.SCREENER)
        self.assertEqual(float(fin.eps), 54.7)

        val = ValuationSnapshot.objects.get(snapshot=snapshot)
        self.assertEqual(float(val.pe), 21.97)
        self.assertEqual(val.source, Source.SCREENER)

    @patch('fundamentals_research.services.research_engine.bsc.get_stock', side_effect=re.bsc.BharatStockError("simulated outage"))
    @patch('fundamentals_research.services.research_engine.sf.get_screener_fundamentals', return_value=None)
    @patch('fundamentals_research.services.research_engine.yff.get_yfinance_fundamentals', return_value=None)
    def test_raises_when_both_sources_fail(self, mock_yfinance, mock_screener, mock_stock):
        with self.assertRaises(re.ResearchUnavailableError):
            re.run_research('NOTAREALSTOCK')
        # confirm nothing was persisted for a symbol that never had real data
        self.assertEqual(ResearchCompany.objects.filter(symbol='NOTAREALSTOCK').count(), 0)


class TestRunResearchYfinancePrimary(TestCase):
    """Renamed from TestRunResearchYfinanceThirdTier -- yfinance is the
    primary source now, not the third tier, per the Sep 26 2026 reorder."""
    """Sep 26 2026: renamed/reframed -- yfinance is now tried FIRST
    (reordered per explicit request), so this is no longer a 3-tier
    fallback test, it's the primary-path-succeeds test. The old
    BharatStock/Screener-fail mocks are removed since neither is even
    invoked anymore when yfinance succeeds on the first attempt -- an
    unused mock claiming "BharatStock failed" when it was never called
    at all would be actively misleading here, not just unnecessary."""

    @patch('fundamentals_research.services.research_engine.na.get_company_news', return_value=[])
    def test_yfinance_as_primary_source_succeeds_on_first_attempt(self, mock_news):
        yfinance_bundle = {
            'company': {'company_name': 'Reliance Industries Limited', 'sector': 'Energy', 'industry': 'Refining', 'exchange': 'NSE'},
            'market': {'price': 1220.5, 'market_cap': 16516382720000, 'week_52_high': 1611.8, 'week_52_low': 1210.5, 'dma_50': 1292.4, 'dma_200': 1364.0},
            'valuation': {'pe': 22.65, 'pb': 1.83, 'peg': 0.82, 'ev_ebitda': 10.92, 'price_to_sales': 1.46, 'dividend_yield': 0.48, 'market_cap': 16516382720000},
            'ownership': {'promoter_pct_proxy': 51.8, 'institutions_pct_proxy': 28.07},
            'debt_equity_reported': 36.653,
            'annual': [
                {'period': '2026-03-31', 'revenue': 1.057219e13, 'ebitda': 2.049060e12, 'net_profit': 8.077500e11, 'eps': 59.69,
                 'total_equity': 9.040300e12, 'total_debt': 3.980000e12, 'cash': 1.373270e12,
                 'current_assets': 5.942490e12, 'current_liabilities': 5.412540e12,
                 'operating_cash_flow': 1.921130e12, 'capex': -1.229160e12,
                 'investing_cash_flow': -1.010890e12, 'financing_cash_flow': -5.154900e11},
                {'period': '2025-03-31', 'revenue': 9.646930e12, 'ebitda': 1.812740e12, 'net_profit': 6.964800e11, 'eps': 51.47,
                 'total_equity': 8.432000e12, 'total_debt': 3.695750e12, 'cash': 1.006450e12,
                 'current_assets': 4.992700e12, 'current_liabilities': 4.537370e12,
                 'operating_cash_flow': 1.787030e12, 'capex': -1.399670e12,
                 'investing_cash_flow': -1.375350e12, 'financing_cash_flow': -3.189100e11},
            ],
        }
        with patch('fundamentals_research.services.research_engine.yff.get_yfinance_fundamentals', return_value=yfinance_bundle) as mock_yfinance, \
             patch('fundamentals_research.services.research_engine.bsc.get_stock') as mock_bharatstock, \
             patch('fundamentals_research.services.research_engine.sf.get_screener_fundamentals') as mock_screener:
            snapshot, what_changed, primary_source = re.run_research('RELIANCE')

        self.assertEqual(primary_source, Source.YFINANCE)
        # confirm this is really the PRIMARY path now, not a fallback --
        # BharatStock and Screener must never even be called when
        # yfinance succeeds on the first attempt.
        mock_bharatstock.assert_not_called()
        mock_screener.assert_not_called()

        company = ResearchCompany.objects.get(symbol='RELIANCE')
        self.assertEqual(company.company_name, 'Reliance Industries Limited')

        fin = FinancialSnapshot.objects.filter(snapshot=snapshot).order_by('-fiscal_year').first()
        self.assertEqual(fin.source, Source.YFINANCE)
        self.assertEqual(float(fin.revenue), 1.057219e13)
        # confirm growth was actually calculated across the 2 real years, not left blank
        self.assertAlmostEqual(float(fin.revenue_growth_yoy_pct), 9.60, places=1)

        bs = BalanceSheetSnapshot.objects.filter(snapshot=snapshot).order_by('-fiscal_year').first()
        self.assertAlmostEqual(float(bs.debt_equity), 0.4403, places=3)  # 3.98e12 / 9.0403e12

        cf = CashFlowSnapshot.objects.filter(snapshot=snapshot).order_by('-fiscal_year').first()
        self.assertAlmostEqual(float(cf.free_cash_flow), 6.9197e11, delta=1e8)  # capex sign handled correctly (real negative-capex convention)

        val = ValuationSnapshot.objects.get(snapshot=snapshot)
        self.assertEqual(val.source, Source.YFINANCE)
        self.assertEqual(float(val.pe), 22.65)

    @patch('fundamentals_research.services.research_engine.na.get_company_news', return_value=[])
    @patch('fundamentals_research.services.research_engine.bsc.get_stock', return_value=_fake_bharatstock_stock_response())
    def test_falls_through_to_bharatstock_when_yfinance_fails(self, mock_stock, mock_news):
        """The genuinely new scenario this reorder introduces: yfinance
        (now primary) fails, falls through to BharatStock (now
        secondary) -- confirms the fallback direction actually
        reversed, not just that the primary-succeeds path works."""
        with patch('fundamentals_research.services.research_engine.yff.get_yfinance_fundamentals', return_value=None), \
             patch('fundamentals_research.services.research_engine.bsc.get_financials') as mock_fin, \
             patch('fundamentals_research.services.research_engine.bsc.get_insider_trades', return_value={'trades': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_bulk_deals', return_value={'deals': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_block_deals', return_value={'deals': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_corporate_actions', return_value={'actions': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_mf_holdings', return_value={}):
            mock_fin.side_effect = lambda symbol, period_type: _fake_financials_annual() if period_type == 'annual' else _fake_financials_quarterly()
            snapshot, what_changed, primary_source = re.run_research('RELIANCE')

        self.assertEqual(primary_source, Source.BHARATSTOCK)
        fin = FinancialSnapshot.objects.filter(snapshot=snapshot).order_by('-fiscal_year').first()
        self.assertEqual(fin.source, Source.BHARATSTOCK)
        # ownership IS populated here (BharatStock has it, yfinance doesn't) --
        # confirms the real, documented tradeoff of yfinance-as-primary in practice
        own = OwnershipSnapshot.objects.get(snapshot=snapshot)
        self.assertEqual(float(own.promoter_pct), 50.3)


class TestResearchDoesNotHoldDbLockDuringNetwork(TestCase):
    """Oct 2 2026: "database is locked" -- the news/financial HTTP calls used to run inside the write
    transaction, so concurrent requests timed out waiting for the single SQLite writer."""

    def test_network_calls_happen_before_the_write_lock_is_taken(self):
        held_during_fetch = []

        def spy_news(symbol, name):
            held_during_fetch.append(re._PERSIST_LOCK.locked())
            return []

        def spy_yf(symbol):
            held_during_fetch.append(re._PERSIST_LOCK.locked())
            return None

        with patch('fundamentals_research.services.research_engine.na.get_company_news', side_effect=spy_news), \
             patch('fundamentals_research.services.research_engine.yff.get_yfinance_fundamentals', side_effect=spy_yf), \
             patch('fundamentals_research.services.research_engine.bsc.get_stock', return_value=_fake_bharatstock_stock_response()), \
             patch('fundamentals_research.services.research_engine.bsc.get_financials') as mock_fin, \
             patch('fundamentals_research.services.research_engine.bsc.get_insider_trades', return_value={'trades': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_bulk_deals', return_value={'deals': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_block_deals', return_value={'deals': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_corporate_actions', return_value={'actions': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_mf_holdings', return_value={}):
            mock_fin.side_effect = lambda symbol, period_type: _fake_financials_annual() if period_type == 'annual' else _fake_financials_quarterly()
            re.run_research('RELIANCE')

        self.assertEqual(held_during_fetch, [False, False])
        self.assertFalse(re._PERSIST_LOCK.locked())

    def test_locked_database_is_retried_then_succeeds(self):
        from django.db import OperationalError
        calls = {'n': 0}
        real = re._persist_research

        def flaky(*a, **k):
            calls['n'] += 1
            if calls['n'] < 3:
                raise OperationalError('database is locked')
            return real(*a, **k)

        with patch('fundamentals_research.services.research_engine.time.sleep'), \
             patch('fundamentals_research.services.research_engine._persist_research', side_effect=flaky), \
             patch('fundamentals_research.services.research_engine.na.get_company_news', return_value=[]), \
             patch('fundamentals_research.services.research_engine.yff.get_yfinance_fundamentals', return_value=None), \
             patch('fundamentals_research.services.research_engine.bsc.get_stock', return_value=_fake_bharatstock_stock_response()), \
             patch('fundamentals_research.services.research_engine.bsc.get_financials') as mock_fin, \
             patch('fundamentals_research.services.research_engine.bsc.get_insider_trades', return_value={'trades': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_bulk_deals', return_value={'deals': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_block_deals', return_value={'deals': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_corporate_actions', return_value={'actions': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_mf_holdings', return_value={}):
            mock_fin.side_effect = lambda symbol, period_type: _fake_financials_annual() if period_type == 'annual' else _fake_financials_quarterly()
            snapshot, _, _ = re.run_research('RELIANCE')

        self.assertEqual(calls['n'], 3)
        self.assertIsNotNone(snapshot.pk)
