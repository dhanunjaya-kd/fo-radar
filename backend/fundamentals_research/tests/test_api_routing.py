from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse

from fundamentals_research.models import ResearchCompany, ResearchSnapshot
from fundamentals_research.services import research_engine as re
from fundamentals_research.tests.test_research_engine import (
    _fake_bharatstock_stock_response, _fake_financials_annual, _fake_financials_quarterly,
)


class TestApiRouting(TestCase):
    """Real HTTP requests through Django's test client, through the
    ACTUAL urls.py -> views.py wiring -- not calling view functions
    directly. This is what proves /api/research/... is really reachable,
    not just that the Python underneath it works in isolation."""

    def test_company_report_404s_cleanly_when_no_research_exists_yet(self):
        response = self.client.get('/api/research/company/NOTRESEARCHEDYET/report/')
        self.assertEqual(response.status_code, 404)
        self.assertIn('No research on file', response.json()['detail'])

    @patch('fundamentals_research.services.research_engine.na.get_company_news', return_value=[])
    @patch('fundamentals_research.services.research_engine.bsc.get_stock', return_value=_fake_bharatstock_stock_response())
    def test_refresh_then_report_round_trip_through_real_urls(self, mock_stock, mock_news):
        with patch('fundamentals_research.services.research_engine.bsc.get_financials') as mock_fin, \
             patch('fundamentals_research.services.research_engine.bsc.get_insider_trades', return_value={'trades': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_bulk_deals', return_value={'deals': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_block_deals', return_value={'deals': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_corporate_actions', return_value={'actions': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_mf_holdings', return_value={}):
            mock_fin.side_effect = lambda symbol, period_type: _fake_financials_annual() if period_type == 'annual' else _fake_financials_quarterly()

            refresh_response = self.client.post('/api/research/company/RELIANCE/refresh/')

        self.assertEqual(refresh_response.status_code, 201)
        self.assertEqual(refresh_response.json()['primary_source'], 'bharatstock')

        # now the report should actually be retrievable through the real GET route
        report_response = self.client.get('/api/research/company/RELIANCE/report/')
        self.assertEqual(report_response.status_code, 200)
        data = report_response.json()
        self.assertEqual(data['company']['symbol'], 'RELIANCE')
        self.assertEqual(len(data['financials']), 2)
        self.assertIsNotNone(data['report'])  # the ResearchReport row was actually created and attached
        self.assertIn('RAW:', data['report']['financial_quality_notes'])

        # and the financials/valuation/ownership sub-endpoints work too
        fin_response = self.client.get('/api/research/company/RELIANCE/financials/')
        self.assertEqual(fin_response.status_code, 200)
        self.assertEqual(len(fin_response.json()['annual']), 2)

        val_response = self.client.get('/api/research/company/RELIANCE/valuation/')
        self.assertEqual(val_response.status_code, 200)
        self.assertEqual(val_response.json()['pe'], '24.10')

        history_response = self.client.get('/api/research/company/RELIANCE/history/')
        self.assertEqual(history_response.status_code, 200)
        self.assertEqual(len(history_response.json()), 1)

    @patch('fundamentals_research.services.research_engine.bsc.get_stock', side_effect=re.bsc.BharatStockError("outage"))
    @patch('fundamentals_research.services.research_engine.sf.get_screener_fundamentals', return_value=None)
    @patch('fundamentals_research.services.research_engine.yff.get_yfinance_fundamentals', return_value=None)
    def test_refresh_returns_503_when_no_source_available(self, mock_yfinance, mock_screener, mock_stock):
        response = self.client.post('/api/research/company/NOTAREALSTOCK/refresh/')
        self.assertEqual(response.status_code, 503)
        self.assertIn('detail', response.json())

    def test_search_endpoint_reachable(self):
        response = self.client.get('/api/research/search/?q=RELIANCE')
        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.json())
