"""
Tests for services/bharatstock_client.py -- ALL mocked at the
requests.get() level, per spec Section 29: "Do NOT consume BharatStock
API quota during normal test execution." Zero real network calls here.
"""
import os
import unittest
from unittest.mock import patch, MagicMock
import requests

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from fundamentals_research.services import bharatstock_client as bc


def _mock_response(status_code, json_data=None, text_data=""):
    resp = MagicMock()
    resp.status_code = status_code
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("no JSON")
    resp.text = text_data
    return resp


class TestApiKeyHandling(unittest.TestCase):
    def test_missing_key_raises_authentication_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(bc.AuthenticationError):
                bc._get_api_key()

    def test_present_key_returned(self):
        with patch.dict(os.environ, {'BHARATSTOCK_API_KEY': 'bsk_live_test123'}):
            self.assertEqual(bc._get_api_key(), 'bsk_live_test123')


class TestRequestStatusHandling(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict(os.environ, {'BHARATSTOCK_API_KEY': 'bsk_live_test123'})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()

    @patch('fundamentals_research.services.bharatstock_client.requests.get')
    def test_200_returns_parsed_json(self, mock_get):
        mock_get.return_value = _mock_response(200, {'symbol': 'RELIANCE', 'company_name': 'Reliance Industries'})
        result = bc._request('/v1/stocks/RELIANCE')
        self.assertEqual(result['symbol'], 'RELIANCE')
        # confirm the key was sent as a header, not a query param (never logged/exposed)
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs['headers']['X-API-Key'], 'bsk_live_test123')

    @patch('fundamentals_research.services.bharatstock_client.requests.get')
    def test_401_raises_authentication_error(self, mock_get):
        mock_get.return_value = _mock_response(401, text_data="Unauthorized")
        with self.assertRaises(bc.AuthenticationError):
            bc._request('/v1/stocks/RELIANCE')

    @patch('fundamentals_research.services.bharatstock_client.requests.get')
    def test_403_raises_authentication_error(self, mock_get):
        mock_get.return_value = _mock_response(403, text_data="Forbidden")
        with self.assertRaises(bc.AuthenticationError):
            bc._request('/v1/stocks/RELIANCE')

    @patch('fundamentals_research.services.bharatstock_client.requests.get')
    def test_404_raises_not_found_error(self, mock_get):
        mock_get.return_value = _mock_response(404, text_data="Not found")
        with self.assertRaises(bc.NotFoundError):
            bc._request('/v1/stocks/NOTAREALSTOCK')

    @patch('fundamentals_research.services.bharatstock_client.requests.get')
    def test_429_raises_rate_limit_error_with_detail(self, mock_get):
        mock_get.return_value = _mock_response(429, {'limit': 50, 'reset_at': '2026-09-25T00:00:00Z'})
        with self.assertRaises(bc.RateLimitError) as ctx:
            bc._request('/v1/stocks/RELIANCE')
        self.assertEqual(ctx.exception.detail['limit'], 50)

    @patch('fundamentals_research.services.bharatstock_client.requests.get')
    def test_429_does_not_retry(self, mock_get):
        """Retrying an identical request against a 429 gains nothing and burns quota -- confirm it's not retried."""
        mock_get.return_value = _mock_response(429, {'limit': 50})
        with self.assertRaises(bc.RateLimitError):
            bc._request('/v1/stocks/RELIANCE')
        self.assertEqual(mock_get.call_count, 1)

    @patch('fundamentals_research.services.bharatstock_client.requests.get')
    def test_500_retries_then_raises_server_error(self, mock_get):
        mock_get.return_value = _mock_response(500, text_data="Internal Server Error")
        with patch('fundamentals_research.services.bharatstock_client.time.sleep'):
            with self.assertRaises(bc.ServerError):
                bc._request('/v1/stocks/RELIANCE')
        # MAX_RETRIES=2 -> 3 total attempts
        self.assertEqual(mock_get.call_count, 3)

    @patch('fundamentals_research.services.bharatstock_client.requests.get')
    def test_timeout_retries_then_raises(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout()
        with patch('fundamentals_research.services.bharatstock_client.time.sleep'):
            with self.assertRaises(bc.BharatStockError):
                bc._request('/v1/stocks/RELIANCE')
        self.assertEqual(mock_get.call_count, 3)

    @patch('fundamentals_research.services.bharatstock_client.requests.get')
    def test_malformed_json_raises(self, mock_get):
        mock_get.return_value = _mock_response(200, json_data=None)  # triggers ValueError in .json()
        with self.assertRaises(bc.BharatStockError):
            bc._request('/v1/stocks/RELIANCE')

    @patch('fundamentals_research.services.bharatstock_client.requests.get')
    def test_missing_fields_in_200_response_dont_crash(self, mock_get):
        """A field genuinely absent from the response must not raise -- it
        should just be absent from the returned dict, for the normalizer
        to handle as None/unavailable."""
        mock_get.return_value = _mock_response(200, {'symbol': 'RELIANCE'})  # no other fields at all
        result = bc._request('/v1/stocks/RELIANCE')
        self.assertNotIn('company_name', result)  # genuinely absent, not crashed


class TestNormalizeStockResponse(unittest.TestCase):
    """Sep 24 2026: rewritten against a REAL response (your live
    WIPRO call), not a guessed shape -- the previous version of these
    tests was internally consistent but tested the wrong structure,
    which is exactly why it didn't catch the real bug."""

    def _real_wipro_sample(self):
        return {
            'symbol': 'WIPRO', 'company_name': 'Wipro Limited', 'sector': 'Information Technology',
            'market_cap': 1620608740000.0,
            'latest_price': {'close': 163.64},
            'metrics': {
                'price': 164.9, 'high_52w': 272.67, 'low_52w': 164.55,
                'pe_ratio': 13.07, 'pb_ratio': 1.8501, 'peg_ratio': 36.3662,
                'promoter_holding': 72.59, 'fii_holding': 11.14, 'dii_holding': 5.22,
                'public_holding': 27.29, 'mutual_funds_holding': 1.83, 'computed_at': '2026-09-23',
            },
            'mf_holdings_summary': {'total_schemes': 178},
        }

    def test_real_response_extracts_valuation_from_metrics(self):
        norm = bc.normalize_stock_response(self._real_wipro_sample())
        self.assertEqual(norm['valuation']['pe'], 13.07)
        self.assertEqual(norm['valuation']['pb'], 1.8501)

    def test_real_response_extracts_ownership_from_metrics(self):
        norm = bc.normalize_stock_response(self._real_wipro_sample())
        self.assertEqual(norm['ownership']['promoter_pct'], 72.59)
        self.assertEqual(norm['ownership']['fii_pct'], 11.14)
        self.assertIsNone(norm['ownership']['promoter_pledge_pct'])  # confirmed absent from the real API -- must stay None, never guessed

    def test_market_cap_uses_rupee_figure_not_crore_figure(self):
        """The real bug this rewrite fixes: metrics['market_cap'] is in
        CRORES (163308.71), raw['market_cap'] is in RUPEES
        (1620608740000.0) -- using the wrong one silently corrupts
        every market-cap-derived ratio by 10,000,000x."""
        norm = bc.normalize_stock_response(self._real_wipro_sample())
        self.assertEqual(norm['valuation']['market_cap'], 1620608740000.0)
        self.assertNotEqual(norm['valuation']['market_cap'], 163308.71)

    def test_mf_holdings_from_real_key(self):
        norm = bc.normalize_stock_response(self._real_wipro_sample())
        self.assertEqual(norm['ownership']['mutual_fund_scheme_count'], 178)

    def test_dma_derived_correctly_from_pct(self):
        """dma50 = price / (1 + price_vs_50dma_pct/100) -- real formula,
        checked against a hand-computed value, not just 'runs without
        crashing'."""
        raw = dict(self._real_wipro_sample())
        raw['metrics'] = dict(raw['metrics'], price_vs_50dma_pct=-7.1455, price_vs_200dma_pct=-19.0893)
        norm = bc.normalize_stock_response(raw)
        self.assertAlmostEqual(norm['market']['dma_50'], 177.59, places=1)
        self.assertAlmostEqual(norm['market']['dma_200'], 203.8, places=1)

    def test_missing_sections_return_empty_dict_not_none(self):
        norm = bc.normalize_stock_response({'symbol': 'RELIANCE'})
        self.assertTrue(all(v is None for v in norm['valuation'].values()))
        self.assertTrue(all(v is None for v in norm['ownership'].values()))
        self.assertEqual(norm['segments'], [])


class TestMfHoldingsFallback(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict(os.environ, {'BHARATSTOCK_API_KEY': 'bsk_live_test123'})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()

    @patch('fundamentals_research.services.bharatstock_client.requests.get')
    def test_falls_back_to_stock_response_when_dedicated_endpoint_404s(self, mock_get):
        def side_effect(url, headers=None, params=None, timeout=None):
            if 'mf-holdings' in url:
                return _mock_response(404, text_data="not found")
            # real key confirmed live: 'mf_holdings_summary' with 'total_schemes', not 'mutual_funds'/'scheme_count'
            return _mock_response(200, {'symbol': 'RELIANCE', 'mf_holdings_summary': {'total_schemes': 302}})
        mock_get.side_effect = side_effect
        result = bc.get_mf_holdings('RELIANCE')
        self.assertEqual(result['total_schemes'], 302)


if __name__ == '__main__':
    unittest.main(verbosity=2)
