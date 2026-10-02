"""
Oct 2 2026: the AI Decision Summary failed outright on "HTTP 503: This model is currently experiencing
high demand. Spikes in demand are usually temporary." These tests pin down the fix: transient provider
errors are retried (and only those), fallbacks are used only when configured, identical inputs reuse
a cached answer, and an outage falls back to the last good summary instead of nothing.
"""
import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fundamentals_research.services import llm_narrative as ln


def http(status, body='{"error":{"code":503,"message":"This model is currently experiencing high demand.","status":"UNAVAILABLE"}}'):
    r = MagicMock()
    r.status_code = status
    r.text = body
    return r


def gemini_ok(text='hello'):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {'candidates': [{'content': {'parts': [{'text': text}]}}]}
    return r


def claude_ok(text='from claude'):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {'content': [{'type': 'text', 'text': text}]}
    return r


ENV = {'GEMINI_API_KEY': 'k', 'AI_PROVIDER': 'gemini'}
MSG = [{'role': 'user', 'content': 'hi'}]


class Base(unittest.TestCase):
    def setUp(self):
        self.sleeps = []
        p = patch.object(ln, '_sleep', lambda s: self.sleeps.append(s))
        p.start()
        self.addCleanup(p.stop)
        ln._FRESH.clear()
        ln._LAST_GOOD.clear()


class Retries(Base):
    def test_503_twice_then_success(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(ln.requests, 'post', side_effect=[http(503), http(503), gemini_ok('finally')]) as post:
            text, reason, detail = ln._call_llm('sys', MSG)
        self.assertEqual((text, reason), ('finally', 'ok'))
        self.assertEqual(post.call_count, 3)
        self.assertEqual(len(self.sleeps), 2)

    def test_persistent_503_reports_how_many_attempts(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(ln.requests, 'post', return_value=http(503)) as post:
            text, reason, detail = ln._call_llm('sys', MSG)
        self.assertEqual(reason, 'http_error')
        self.assertIsNone(text)
        self.assertIn('[tried 3x]', detail)
        self.assertEqual(post.call_count, 3)

    def test_permanent_errors_are_not_retried(self):
        for status in (400, 401, 403, 404):
            with patch.dict(os.environ, ENV, clear=True), patch.object(ln.requests, 'post', return_value=http(status, '{"error":"bad"}')) as post:
                _, reason, detail = ln._call_llm('sys', MSG)
            self.assertEqual(post.call_count, 1, status)
            self.assertNotIn('tried', detail)

    def test_network_error_is_retried(self):
        with patch.dict(os.environ, ENV, clear=True), \
             patch.object(ln.requests, 'post', side_effect=[ln.requests.exceptions.ConnectionError('boom'), gemini_ok('back')]) as post:
            text, reason, _ = ln._call_llm('sys', MSG)
        self.assertEqual((text, reason, post.call_count), ('back', 'ok', 2))

    def test_retry_budget_caps_total_waiting(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(ln.requests, 'post', return_value=http(503)) as post, \
             patch.object(ln, '_RETRY_BUDGET_SECONDS', 1.0):
            ln._call_llm('sys', MSG)
        self.assertEqual(post.call_count, 1)            # first wait (2s+) already exceeds the 1s budget


class Fallbacks(Base):
    def test_fallback_model_used_only_when_configured(self):
        urls = []

        def fake_post(url, **kw):
            urls.append(url)
            return gemini_ok('from fallback') if 'fallback-model' in url else http(503)
        with patch.dict(os.environ, {**ENV, 'GEMINI_MODEL': 'primary-model', 'GEMINI_FALLBACK_MODEL': 'fallback-model'}, clear=True), \
             patch.object(ln.requests, 'post', side_effect=fake_post):
            text, reason, _ = ln._call_llm('sys', MSG)
        self.assertEqual((text, reason), ('from fallback', 'ok'))
        self.assertTrue(any('primary-model' in u for u in urls) and any('fallback-model' in u for u in urls))

    def test_no_fallback_model_configured_means_no_guessing(self):
        urls = []

        def fake_post(url, **kw):
            urls.append(url)
            return http(503)
        with patch.dict(os.environ, {**ENV, 'GEMINI_MODEL': 'primary-model'}, clear=True), patch.object(ln.requests, 'post', side_effect=fake_post):
            _, reason, _ = ln._call_llm('sys', MSG)
        self.assertEqual(reason, 'http_error')
        self.assertTrue(all('primary-model' in u for u in urls))

    def test_other_provider_used_when_its_key_exists(self):
        def fake_post(url, **kw):
            return claude_ok('rescued') if 'anthropic' in url else http(503)
        with patch.dict(os.environ, {**ENV, 'ANTHROPIC_API_KEY': 'ak'}, clear=True), patch.object(ln.requests, 'post', side_effect=fake_post):
            text, reason, _ = ln._call_llm('sys', MSG)
        self.assertEqual((text, reason), ('rescued', 'ok'))

    def test_no_other_key_no_other_provider(self):
        urls = []

        def fake_post(url, **kw):
            urls.append(url)
            return http(503)
        with patch.dict(os.environ, ENV, clear=True), patch.object(ln.requests, 'post', side_effect=fake_post):
            ln._call_llm('sys', MSG)
        self.assertFalse(any('anthropic' in u for u in urls))


FACT = {'company': {'name': 'ACME', 'symbol': 'ACME'}}
GOOD = {'status': 'Insufficient data', 'supporting_evidence': ['a'], 'opposing_evidence': ['b'], 'conditions_to_monitor': ['c'], 'invalidation_conditions': ['d']}


class DecisionCaching(Base):
    def run_summary(self, conf=None, language='english'):
        return ln.generate_decision_summary(FACT, conf or {'x': 1}, {'e': 1}, {'t': 1}, language=language)

    def test_identical_inputs_reuse_the_answer(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(ln.requests, 'post', return_value=gemini_ok(json.dumps(GOOD))) as post:
            s1, r1, _ = self.run_summary()
            s2, r2, _ = self.run_summary()
        self.assertEqual((r1, r2), ('ok', 'ok'))
        self.assertEqual(post.call_count, 1)
        self.assertEqual(s1['supporting_evidence'], s2['supporting_evidence'])
        self.assertIn('generated_at', s1)

    def test_changed_inputs_or_language_call_again(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(ln.requests, 'post', return_value=gemini_ok(json.dumps(GOOD))) as post:
            self.run_summary({'x': 1})
            self.run_summary({'x': 2})
            self.run_summary({'x': 1}, language='roman_telugu')
        self.assertEqual(post.call_count, 3)

    def test_failures_are_not_cached(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(ln.requests, 'post', side_effect=[http(503)] * 3 + [gemini_ok(json.dumps(GOOD))]) as post:
            s1, r1, _ = self.run_summary()
            s2, r2, _ = self.run_summary()
        self.assertEqual((s1, r1), (None, 'http_error'))
        self.assertEqual(r2, 'ok')

    def test_last_good_survives_a_later_outage(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(ln.requests, 'post', return_value=gemini_ok(json.dumps(GOOD))):
            self.run_summary({'x': 1})
        self.assertEqual(ln.get_last_good_summary('acme', 'english')['supporting_evidence'], ['a'])
        with patch.dict(os.environ, ENV, clear=True), patch.object(ln.requests, 'post', return_value=http(503)):
            s, r, _ = self.run_summary({'x': 2})                  # numbers moved -> cache miss -> outage
        self.assertIsNone(s)
        self.assertIsNotNone(ln.get_last_good_summary('ACME', 'english'))
        self.assertIsNone(ln.get_last_good_summary('OTHER', 'english'))


if __name__ == '__main__':
    unittest.main()
