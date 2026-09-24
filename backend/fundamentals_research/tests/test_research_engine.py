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
    return {
        'symbol': 'RELIANCE', 'company_name': 'Reliance Industries Limited', 'isin': 'INE002A01018',
        'sector': 'Energy', 'industry': 'Refineries', 'exchange': 'NSE', 'listing_date': '1977-11-29',
        'market': {'price': 1370.5, 'market_cap': 18543210000000, 'week_52_high': 1608.8, 'week_52_low': 1201.4, 'dma_50': 1350.0, 'dma_200': 1400.0},
        'valuation': {'pe': 24.1, 'pb': 2.3, 'peg': 1.8, 'ev_ebitda': 12.5, 'price_to_sales': 2.1, 'dividend_yield': 0.4},
        'ownership': {'as_of_quarter': 'Q1 FY2026-27', 'promoter_pct': 50.3, 'promoter_pledge_pct': 0.0, 'fii_pct': 22.1, 'dii_pct': 15.6, 'public_pct': 12.0, 'mutual_fund_pct': 8.2, 'mutual_fund_scheme_count': 302},
        'segments': [
            {'name': 'Oil to Chemicals', 'period': 'FY2025-26', 'revenue': 500000, 'result': 45000, 'revenue_contribution_pct': 55.5},
            {'name': 'Retail', 'period': 'FY2025-26', 'revenue': 300000, 'result': 22000, 'revenue_contribution_pct': 33.3},
        ],
        'mutual_funds': {'scheme_count': 302},
    }


def _fake_financials_annual(revenue=900000, pat=74000):
    return {'periods': [
        {'fiscal_year': 'FY2025-26', 'revenue': revenue, 'ebitda': 150000, 'pat': pat, 'eps': 54.7, 'total_equity': 800000},
        {'fiscal_year': 'FY2024-25', 'revenue': 850000, 'ebitda': 140000, 'pat': 68000, 'eps': 50.3, 'total_equity': 750000},
    ], 'balance_sheet': {'fiscal_year': 'FY2025-26', 'total_debt': 300000, 'cash': 50000, 'total_equity': 800000, 'current_assets': 400000, 'current_liabilities': 200000}, 'cash_flow': {'fiscal_year': 'FY2025-26', 'operating_cash_flow': 120000, 'capex': 60000, 'pat': pat, 'revenue': revenue}}


def _fake_financials_quarterly():
    return {'periods': [
        {'fiscal_quarter': 'Q1 FY2026-27', 'revenue': 230000, 'pat': 19000, 'eps': 14.1},
        {'fiscal_quarter': 'Q4 FY2025-26', 'revenue': 225000, 'pat': 18500, 'eps': 13.7},
    ]}


class TestRunResearchBharatStockPath(TestCase):
    @patch('fundamentals_research.services.research_engine.na.get_company_news', return_value=[])
    @patch('fundamentals_research.services.research_engine.bsc.get_stock', return_value=_fake_bharatstock_stock_response())
    def test_creates_company_and_full_snapshot(self, mock_stock, mock_news):
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

        bs = BalanceSheetSnapshot.objects.get(snapshot=snapshot)
        self.assertAlmostEqual(float(bs.debt_equity), 0.375, places=2)  # 300000/800000
        self.assertAlmostEqual(float(bs.net_debt), 250000.0)  # 300000-50000

        cf = CashFlowSnapshot.objects.get(snapshot=snapshot)
        self.assertAlmostEqual(float(cf.free_cash_flow), 60000.0)  # 120000-60000

        val = ValuationSnapshot.objects.get(snapshot=snapshot)
        self.assertEqual(float(val.pe), 24.1)
        # earnings yield calculated = 100/pe = 100/24.1
        self.assertAlmostEqual(float(val.earnings_yield_pct), 4.15, places=1)

        own = OwnershipSnapshot.objects.get(snapshot=snapshot)
        self.assertEqual(float(own.promoter_pct), 50.3)
        self.assertIsNone(own.promoter_change_pct)  # no previous snapshot to compare against yet

    @patch('fundamentals_research.services.research_engine.na.get_company_news', return_value=[])
    def test_second_snapshot_computes_what_changed(self, mock_news):
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
    def test_falls_back_to_screener_when_bharatstock_fully_down(self, mock_screener, mock_stock, mock_news):
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
    def test_raises_when_both_sources_fail(self, mock_screener, mock_stock):
        with self.assertRaises(re.ResearchUnavailableError):
            re.run_research('NOTAREALSTOCK')
        # confirm nothing was persisted for a symbol that never had real data
        self.assertEqual(ResearchCompany.objects.filter(symbol='NOTAREALSTOCK').count(), 0)
