import json
from unittest.mock import patch, MagicMock
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


class TestAveragingEndpoint(TestCase):
    """Real HTTP requests through the actual averaging route."""

    def test_averaging_with_explicit_current_price(self):
        response = self.client.post(
            '/api/research/company/RELIANCE/averaging/',
            data={
                'existing_avg_price': 200, 'existing_qty': 100, 'current_price': 150,
                'scenarios': [{'label': 'Add 100 shares', 'additional_qty': 100}],
                'downside_price_levels': [140, 175],
            },
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['current_position']['unrealized_pnl'], -5000)
        self.assertEqual(len(data['scenarios']), 1)
        self.assertEqual(data['scenarios'][0]['new_weighted_avg_price'], 175)
        self.assertEqual(len(data['scenarios'][0]['downside_scenarios']), 2)

    def test_averaging_missing_required_fields_400s(self):
        response = self.client.post('/api/research/company/RELIANCE/averaging/', data={}, content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_averaging_without_current_price_and_no_research_400s(self):
        response = self.client.post(
            '/api/research/company/NOTRESEARCHED/averaging/',
            data={'existing_avg_price': 200, 'existing_qty': 100, 'scenarios': []},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_averaging_invalid_scenario_input_400s(self):
        response = self.client.post(
            '/api/research/company/RELIANCE/averaging/',
            data={
                'existing_avg_price': 200, 'existing_qty': 100, 'current_price': 150,
                'scenarios': [{'label': 'Bad', 'additional_qty': -50}],
            },
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)


class TestCandlesEndpoint(TestCase):
    """Real HTTP requests through the actual candles route. Does NOT
    require a prior research call -- confirmed by not calling
    self.client.post('.../refresh/') in any of these."""

    def test_invalid_timeframe_400s(self):
        with patch('screener.fyers_client.is_authenticated', return_value=True):
            response = self.client.get('/api/research/company/RELIANCE/candles/?timeframe=3m')
        self.assertEqual(response.status_code, 400)

    def test_not_authenticated_returns_503(self):
        with patch('screener.fyers_client.is_authenticated', return_value=False):
            response = self.client.get('/api/research/company/RELIANCE/candles/?timeframe=1d')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['reason'], 'not_authenticated')

    def test_successful_fetch_returns_real_shaped_candles(self):
        raw = {'s': 'ok', 'candles': [[1758000000, 100.0, 105.0, 99.0, 103.0, 50000]]}
        with patch('screener.fyers_client.is_authenticated', return_value=True), \
             patch('screener.fyers_client._rate_limited_now', return_value=False), \
             patch('screener.fyers_client.get_history', return_value=raw):
            response = self.client.get('/api/research/company/RELIANCE/candles/?timeframe=1d')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(len(data['candles']), 1)
        self.assertEqual(data['latest_price'], 103.0)

    def test_default_timeframe_is_daily_when_not_specified(self):
        with patch('screener.fyers_client.is_authenticated', return_value=True), \
             patch('screener.fyers_client._rate_limited_now', return_value=False), \
             patch('screener.fyers_client.get_history', return_value=None) as mock_hist:
            self.client.get('/api/research/company/RELIANCE/candles/')
        self.assertEqual(mock_hist.call_args.kwargs['resolution'], 'D')


class TestTechnicalEndpoint(TestCase):
    def test_technical_404s_when_snapshot_unavailable(self):
        with patch('fundamentals_research.services.technical_analysis.get_technical_snapshot', return_value=None):
            response = self.client.get('/api/research/company/RELIANCE/technical/')
        self.assertEqual(response.status_code, 404)

    def test_technical_returns_snapshot_and_classification(self):
        fake_technicals = {'current_price': 110, 'ema20': 105, 'ema50': 100, 'ema200': 95, 'rsi': 58, 'adx': 25, 'plus_di': 28, 'minus_di': 14}
        with patch('fundamentals_research.services.technical_analysis.get_technical_snapshot', return_value=fake_technicals):
            response = self.client.get('/api/research/company/RELIANCE/technical/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['trend']['classification'], 'Potential recovery setup')
        self.assertEqual(data['technicals']['rsi'], 58)


class TestDecisionSupportEndpoint(TestCase):
    """Real HTTP requests through the actual decision-support route,
    ties together technical_analysis + entry_setup + confluence + the
    AI decision summary's fallback path (mocked Claude only)."""

    def setUp(self):
        super().setUp()
        # the summary cache / last-good fallback are process-wide; a summary generated by another
        # test must not be served as a "stale" answer here
        from fundamentals_research.services import llm_narrative as ln
        ln._FRESH.clear()
        ln._LAST_GOOD.clear()
        ln._cooldown_until.clear()

    def _research_reliance(self):
        with patch('fundamentals_research.services.research_engine.na.get_company_news', return_value=[]), \
             patch('fundamentals_research.services.research_engine.bsc.get_stock', return_value=_fake_bharatstock_stock_response()), \
             patch('fundamentals_research.services.research_engine.bsc.get_financials') as mock_fin, \
             patch('fundamentals_research.services.research_engine.bsc.get_insider_trades', return_value={'trades': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_bulk_deals', return_value={'deals': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_block_deals', return_value={'deals': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_corporate_actions', return_value={'actions': []}), \
             patch('fundamentals_research.services.research_engine.bsc.get_mf_holdings', return_value={}), \
             patch('fundamentals_research.services.research_engine.yff.get_yfinance_fundamentals', return_value=None):
            mock_fin.side_effect = lambda symbol, period_type: _fake_financials_annual() if period_type == 'annual' else _fake_financials_quarterly()
            self.client.post('/api/research/company/RELIANCE/refresh/')

    def test_404_when_no_research_on_file(self):
        response = self.client.get('/api/research/company/NOTRESEARCHED/decision-support/')
        self.assertEqual(response.status_code, 404)

    def test_returns_all_sections_with_no_technicals_available(self):
        self._research_reliance()
        with patch('fundamentals_research.services.technical_analysis.get_technical_snapshot', return_value=None), \
             patch('fundamentals_research.services.llm_narrative.requests.post') as mock_claude:
            mock_claude.return_value = MagicMock(status_code=500)
            response = self.client.get('/api/research/company/RELIANCE/decision-support/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['trend']['classification'], 'Insufficient data')
        self.assertEqual(data['entry_setup']['status'], 'unavailable')
        # AI summary must gracefully fall back, never crash the whole endpoint
        self.assertEqual(data['ai_decision_summary']['status'], 'Insufficient data')
        self.assertIn('unavailable', data['ai_decision_summary']['note'])

    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'sk-ant-test', 'AI_PROVIDER': 'anthropic'})
    def test_full_pipeline_with_real_technicals_and_ai_summary(self):
        self._research_reliance()
        fake_technicals = {'current_price': 110, 'ema20': 105, 'ema50': 100, 'ema200': 95, 'rsi': 58, 'adx': 25, 'plus_di': 28, 'minus_di': 14, 'atr': 4, 'support': 98, 'volume_avg': 500000}
        ai_response = json.dumps({
            'status': 'Setup confirmed under defined conditions',
            'supporting_evidence': ['RSI 58 constructive'], 'opposing_evidence': [],
            'conditions_to_monitor': ['EMA50'], 'invalidation_conditions': ['Close below stop'],
        })
        with patch('fundamentals_research.services.technical_analysis.get_technical_snapshot', return_value=fake_technicals), \
             patch('fundamentals_research.services.llm_narrative.requests.post') as mock_claude:
            resp = MagicMock(status_code=200)
            resp.json.return_value = {'content': [{'type': 'text', 'text': ai_response}]}
            mock_claude.return_value = resp
            response = self.client.get('/api/research/company/RELIANCE/decision-support/')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['trend']['classification'], 'Potential recovery setup')
        self.assertEqual(data['ai_decision_summary']['status'], 'Setup confirmed under defined conditions')
        # confirm confluence never contains a forbidden combined score
        self.assertNotIn('score', data['confluence'])

    def test_invalid_language_param_falls_back_to_english(self):
        self._research_reliance()
        with patch('fundamentals_research.services.technical_analysis.get_technical_snapshot', return_value=None), \
             patch('fundamentals_research.services.llm_narrative.requests.post') as mock_claude:
            mock_claude.return_value = MagicMock(status_code=500)
            response = self.client.get('/api/research/company/RELIANCE/decision-support/?language=klingon')
        self.assertEqual(response.status_code, 200)  # doesn't 400/crash on a bad language value, just falls back


class TestChatEndpoint(TestCase):
    """Real HTTP requests through the actual chat route, mocked Claude
    API only -- proves the endpoint, snapshot lookup, and fact-sheet
    grounding work together, not just that llm_narrative.py works alone."""

    def test_chat_404s_with_no_research_on_file(self):
        response = self.client.post('/api/research/company/NOTRESEARCHED/chat/', data={'question': 'Why?'}, content_type='application/json')
        self.assertEqual(response.status_code, 404)

    def test_chat_400s_with_no_question(self):
        response = self.client.post('/api/research/company/RELIANCE/chat/', data={}, content_type='application/json')
        self.assertEqual(response.status_code, 400)

    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'sk-ant-test', 'AI_PROVIDER': 'anthropic'})
    @patch('fundamentals_research.services.research_engine.na.get_company_news', return_value=[])
    @patch('fundamentals_research.services.research_engine.bsc.get_stock', return_value=_fake_bharatstock_stock_response())
    def test_chat_answers_grounded_in_real_snapshot_after_research(self, mock_stock, mock_news):
        with patch('fundamentals_research.services.llm_narrative.requests.post') as mock_claude:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {'content': [{'type': 'text', 'text': 'Revenue was 900000 for FY2025-26, per the data provided.'}]}
            mock_claude.return_value = resp

            with patch('fundamentals_research.services.research_engine.bsc.get_financials') as mock_fin, \
                 patch('fundamentals_research.services.research_engine.bsc.get_insider_trades', return_value={'trades': []}), \
                 patch('fundamentals_research.services.research_engine.bsc.get_bulk_deals', return_value={'deals': []}), \
                 patch('fundamentals_research.services.research_engine.bsc.get_block_deals', return_value={'deals': []}), \
                 patch('fundamentals_research.services.research_engine.bsc.get_corporate_actions', return_value={'actions': []}), \
                 patch('fundamentals_research.services.research_engine.bsc.get_mf_holdings', return_value={}):
                mock_fin.side_effect = lambda symbol, period_type: _fake_financials_annual() if period_type == 'annual' else _fake_financials_quarterly()
                # Sep 25 2026: the refresh call ALSO triggers report_builder's
                # own LLM narrative attempt (build_report -> generate_narrative_
                # sections) -- previously unmocked here, so it made a REAL live
                # call to Anthropic with the fake test key and got a real 401
                # back (harmless, correctly fell back to templates, but still a
                # genuine live network call from a test, which this project's
                # tests never do anywhere else). Now inside the same mock
                # context as the chat call below, so nothing in this test ever
                # leaves the process.
                self.client.post('/api/research/company/RELIANCE/refresh/')

            chat_response = self.client.post(
                '/api/research/company/RELIANCE/chat/',
                data={'question': 'What was revenue?'}, content_type='application/json',
            )

        self.assertEqual(chat_response.status_code, 200)
        self.assertIn('900000', chat_response.json()['answer'])
        # confirm the real snapshot's real revenue (900000, from the fake bundle) was actually
        # sent as grounding context to Claude, not a hardcoded or stale value
        sent_context = mock_claude.call_args.kwargs['json']['messages'][0]['content']
        self.assertIn('900000', sent_context)
        self.assertIn('RELIANCE', sent_context)
