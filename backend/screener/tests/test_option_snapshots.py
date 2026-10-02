"""After-close option-chain snapshots: never replace a good one with a failed fetch, and keep them fresh."""
from unittest.mock import patch, MagicMock
from django.http import JsonResponse
from django.test import SimpleTestCase, RequestFactory

from fno_sniper import market_close_middleware as mw


class OptionSnapshotTests(SimpleTestCase):
    def setUp(self):
        self._saved = dict(mw._snapshots)
        mw._snapshots.clear()
        self._persist = patch.object(mw, '_persist_snapshots')
        self._persist.start()

    def tearDown(self):
        self._persist.stop()
        mw._snapshots.clear()
        mw._snapshots.update(self._saved)

    def _run(self, body):
        m = mw.MarketCloseFreezeMiddleware(lambda req: JsonResponse(body))
        with patch.object(mw, 'is_market_hours', return_value=True):
            return m(RequestFactory().get('/api/option-analytics/NIFTY/'))

    def test_good_chain_is_captured(self):
        self._run({'live': True, 'spot': 23000})
        self.assertIn('/api/option-analytics/NIFTY/', mw._snapshots)

    def test_failed_fetch_never_replaces_a_good_snapshot(self):
        self._run({'live': True, 'spot': 23000})
        good = mw._snapshots['/api/option-analytics/NIFTY/']['content']
        self._run({'live': False, 'error': 'Fyers not authenticated.'})
        self.assertEqual(mw._snapshots['/api/option-analytics/NIFTY/']['content'], good)

    def test_keeper_requests_every_index_and_expiry(self):
        seen = []
        def fake(req):
            seen.append(req.get_full_path())
            return JsonResponse({})
        with patch.object(mw.time, 'sleep'):
            mw._snapshot_option_chains(fake, include_other=True)
        self.assertEqual(len(seen), 9)
        self.assertIn('/api/option-analytics/SENSEX/', seen)
        self.assertIn('/api/option-analytics/BANKNIFTY/?expiry=monthly', seen)

    def test_keeper_survives_a_failing_request(self):
        calls = []
        def boom(req):
            calls.append(1); raise RuntimeError('x')
        with patch.object(mw.time, 'sleep'):
            mw._snapshot_option_chains(boom, include_other=False)
        self.assertEqual(len(calls), 3)

    def test_keeper_goes_through_the_real_view_without_a_session(self):
        # the real handler chain, called the way the keeper calls it (no SessionMiddleware upstream)
        from django.core.handlers.base import BaseHandler
        handler = BaseHandler(); handler.load_middleware()
        m = mw.MarketCloseFreezeMiddleware(handler._get_response)
        with patch.object(mw.time, 'sleep'), patch.object(mw, 'is_market_hours', return_value=True):
            mw._snapshot_option_chains(m, include_other=False)   # must not raise / log AttributeError
