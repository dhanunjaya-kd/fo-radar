"""
Sep 24 2026: rewritten for the same reason as test_news_analysis.py --
module-level sys.modules stubbing (even with a tearDownModule cleanup)
still pollutes sys.modules during Django's test-discovery phase, before
any teardown runs. screener_fallback.py's own `from fundamentals import
screener_client, parser` is a deferred, in-function import specifically
so the stub only needs to exist for the duration of one test method,
via patch.dict as a context manager -- never at file-import time.

'fundamentals' is an especially important one to get right here: it's
a REAL package other code in this app imports directly (views.py's
ResearchSearchView uses fundamentals.symbol_master) -- a leaked stub
here doesn't just look like an unrelated missing-module error
elsewhere, it silently breaks a totally different feature's real
import.
"""
import os
import sys
import types
import unittest
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fundamentals_research.services import screener_fallback as sf
from fundamentals_research.services.source_registry import Source


class _FakeSessionExpiredError(Exception):
    pass


def _fake_fundamentals_modules(get_session=None, fetch_export_bytes=None, parse_fundamentals=None,
                                get_session_side_effect=None, fetch_side_effect=None, parse_side_effect=None):
    fundamentals_pkg = types.ModuleType('fundamentals')
    screener_client_mod = types.ModuleType('fundamentals.screener_client')
    parser_mod = types.ModuleType('fundamentals.parser')

    screener_client_mod.SessionExpiredError = _FakeSessionExpiredError
    screener_client_mod.get_session = MagicMock(return_value=get_session, side_effect=get_session_side_effect)
    screener_client_mod.fetch_export_bytes = MagicMock(return_value=fetch_export_bytes, side_effect=fetch_side_effect)
    parser_mod.parse_fundamentals = MagicMock(return_value=parse_fundamentals, side_effect=parse_side_effect)

    return {'fundamentals': fundamentals_pkg, 'fundamentals.screener_client': screener_client_mod, 'fundamentals.parser': parser_mod}


class TestScreenerFallback(unittest.TestCase):
    def test_success_case_maps_all_fields_with_source_tagged(self):
        parsed = {
            'company_name': 'Reliance Industries', 'current_price': 1370.5, 'market_cap_cr': 1854321.0,
            'latest_year': 'Mar-25', 'sales_cr': 900000.0, 'net_profit_cr': 74000.0,
            'eps': 54.7, 'pe_ratio': 21.97, 'roe_pct': 8.93, 'debt_to_equity': 0.446,
            'opm_pct': 17.2, 'sales_cagr_pct': 14.84,
        }
        modules = _fake_fundamentals_modules(get_session=MagicMock(), fetch_export_bytes=b'fake xlsx bytes', parse_fundamentals=parsed)
        with patch.dict(sys.modules, modules):
            result = sf.get_screener_fundamentals('RELIANCE')

        self.assertIsNotNone(result)
        self.assertEqual(result['pe_ratio'].value, 21.97)
        self.assertEqual(result['pe_ratio'].source, Source.SCREENER)
        self.assertEqual(result['pe_ratio'].period, 'Mar-25')
        self.assertEqual(result['roe_pct'].value, 8.93)

    def test_session_expired_returns_none_not_crash(self):
        modules = _fake_fundamentals_modules(get_session_side_effect=_FakeSessionExpiredError())
        with patch.dict(sys.modules, modules):
            result = sf.get_screener_fundamentals('RELIANCE')
        self.assertIsNone(result)

    def test_fetch_returns_none_propagates_as_none(self):
        modules = _fake_fundamentals_modules(get_session=MagicMock(), fetch_export_bytes=None)
        with patch.dict(sys.modules, modules):
            result = sf.get_screener_fundamentals('BADSYMBOL')
        self.assertIsNone(result)

    def test_parse_returns_none_propagates_as_none(self):
        modules = _fake_fundamentals_modules(get_session=MagicMock(), fetch_export_bytes=b'corrupt', parse_fundamentals=None)
        with patch.dict(sys.modules, modules):
            result = sf.get_screener_fundamentals('RELIANCE')
        self.assertIsNone(result)

    def test_unexpected_exception_during_fetch_does_not_propagate(self):
        modules = _fake_fundamentals_modules(get_session=MagicMock(), fetch_side_effect=RuntimeError("network blew up"))
        with patch.dict(sys.modules, modules):
            result = sf.get_screener_fundamentals('RELIANCE')
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main(verbosity=2)
