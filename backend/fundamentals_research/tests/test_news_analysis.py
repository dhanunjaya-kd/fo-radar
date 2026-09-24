"""
Sep 24 2026: rewritten after a real bug -- the original version stubbed
sys.modules['news']/['news.fetcher'] at MODULE IMPORT TIME (with a
tearDownModule() cleanup). That cleanup ran too late: Django's test
runner imports ALL test modules during discovery, then runs its own
`check` command (which imports the real urlconf, including the real
news.urls) BEFORE any test's tearDownModule gets a chance to fire. The
stub was already polluting sys.modules by the time check() ran.

Fixed properly here: news_analysis.py itself only imports news.fetcher
INSIDE get_company_news() (a deferred import, by design, specifically
for this reason) -- so the stub only needs to exist for the exact
duration of a test method's execution, via patch.dict as a context
manager. It's applied and removed within each test, never touching
sys.modules at import time or between tests.
"""
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fundamentals_research.services import news_analysis as na


def _fake_news_modules(fetcher_instance):
    """Builds the {module_name: module} dict for patch.dict(sys.modules, ...),
    scoped to exactly one test via a `with` block -- never left in
    place after the block exits, regardless of pass/fail/exception."""
    news_pkg = types.ModuleType('news')
    fetcher_mod = types.ModuleType('news.fetcher')
    fetcher_mod.NewsFetcher = MagicMock(return_value=fetcher_instance)
    return {'news': news_pkg, 'news.fetcher': fetcher_mod}


class TestNewsAnalysis(unittest.TestCase):
    def test_maps_articles_and_sentiment_correctly(self):
        fake_fetcher = MagicMock()
        fake_fetcher.api_key = 'fake-key'
        fake_fetcher.fetch_newsapi.return_value = [
            {'title': 'Reliance posts record profit', 'description': 'Strong quarter for RIL',
             'url': 'https://example.com/1', 'publishedAt': '2026-09-20T10:00:00Z',
             'source': {'name': 'Moneycontrol'}},
        ]
        fake_fetcher.analyze_sentiment.return_value = (0.45, 'Bullish')

        with patch.dict(sys.modules, _fake_news_modules(fake_fetcher)):
            result = na.get_company_news('RELIANCE', 'Reliance Industries')

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['sentiment'], 'positive')  # mapped from 'Bullish'
        self.assertIn('0.450', result[0]['sentiment_basis'])
        self.assertEqual(result[0]['news_source'], 'Moneycontrol')
        self.assertIsNotNone(result[0]['published_at'])

    def test_no_api_key_returns_empty_list_not_crash(self):
        fake_fetcher = MagicMock()
        fake_fetcher.api_key = None
        with patch.dict(sys.modules, _fake_news_modules(fake_fetcher)):
            result = na.get_company_news('RELIANCE')
        self.assertEqual(result, [])

    def test_fetch_exception_returns_empty_list_not_crash(self):
        fake_fetcher = MagicMock()
        fake_fetcher.api_key = 'fake-key'
        fake_fetcher.fetch_newsapi.side_effect = RuntimeError("network error")
        with patch.dict(sys.modules, _fake_news_modules(fake_fetcher)):
            result = na.get_company_news('RELIANCE')
        self.assertEqual(result, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
