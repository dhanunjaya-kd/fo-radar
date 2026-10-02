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
        ln._cooldown_until.clear()


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


QUOTA = '{"error":{"code":429,"message":"You exceeded your current quota, please check your plan and billing details.","status":"RESOURCE_EXHAUSTED"}}'


def openai_ok(text='from groq'):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {'choices': [{'message': {'content': text}}]}
    return r


class QuotaExhausted(Base):
    """Oct 2 2026: Gemini free tier ran out ("HTTP 429: You exceeded your current quota"). Retrying a spent
    quota only burns more of it; the right move is to go to a backup provider straight away."""

    def test_quota_error_is_not_retried(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(ln.requests, 'post', return_value=http(429, QUOTA)) as post:
            text, reason, detail = ln._call_llm('sys', MSG)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(reason, 'http_error')
        self.assertIn('no backup provider configured', detail)      # tells the user how to fix it

    def test_plain_rate_limit_429_is_still_retried(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(ln.requests, 'post', side_effect=[http(429, '{"error":"too many requests"}'), gemini_ok('ok now')]) as post:
            text, reason, _ = ln._call_llm('sys', MSG)
        self.assertEqual((text, post.call_count), ('ok now', 2))

    def test_falls_back_to_groq_when_quota_is_spent(self):
        env = dict(ENV, GROQ_API_KEY='g')
        def fake(url, **kw):
            return http(429, QUOTA) if 'googleapis' in url else openai_ok('groq answered')
        with patch.dict(os.environ, env, clear=True), patch.object(ln.requests, 'post', side_effect=fake) as post:
            text, reason, _ = ln._call_llm('sys', MSG)
        self.assertEqual((text, reason), ('groq answered', 'ok'))
        self.assertEqual(post.call_count, 2)
        url = post.call_args.args[0]
        self.assertIn('api.groq.com', url)
        self.assertEqual(post.call_args.kwargs['json']['messages'][0], {'role': 'system', 'content': 'sys'})
        self.assertEqual(post.call_args.kwargs['headers']['authorization'], 'Bearer g')

    def test_exhausted_provider_is_skipped_on_the_next_request(self):
        env = dict(ENV, GROQ_API_KEY='g')
        urls = []
        def fake(url, **kw):
            urls.append(url)
            return http(429, QUOTA) if 'googleapis' in url else openai_ok()
        with patch.dict(os.environ, env, clear=True), patch.object(ln.requests, 'post', side_effect=fake):
            ln._call_llm('sys', MSG)
            ln._call_llm('sys', MSG)
        self.assertEqual(sum('googleapis' in u for u in urls), 1)   # second request went straight to groq
        self.assertEqual(sum('groq' in u for u in urls), 2)

    def test_gemini_fallback_model_is_tried_on_quota_error(self):
        env = dict(ENV, GEMINI_FALLBACK_MODEL='other-model')
        seen = []
        def fake(url, **kw):
            seen.append(url)
            return http(429, QUOTA) if 'other-model' not in url else gemini_ok('second model')
        with patch.dict(os.environ, env, clear=True), patch.object(ln.requests, 'post', side_effect=fake):
            text, reason, _ = ln._call_llm('sys', MSG)
        self.assertEqual(text, 'second model')

    def test_only_configured_providers_are_fallbacks(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'k', 'OPENROUTER_API_KEY': 'o'}, clear=True):
            self.assertEqual(ln._fallback_order('gemini'), ['openrouter'])
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'k', 'GROQ_API_KEY': 'g', 'ANTHROPIC_API_KEY': 'a', 'AI_FALLBACKS': 'groq'}, clear=True):
            self.assertEqual(ln._fallback_order('gemini'), ['groq'])

    def test_primary_without_key_still_works_through_a_fallback(self):
        with patch.dict(os.environ, {'AI_PROVIDER': 'gemini', 'GROQ_API_KEY': 'g'}, clear=True), patch.object(ln.requests, 'post', return_value=openai_ok('only groq')):
            text, reason, _ = ln._call_llm('sys', MSG)
        self.assertEqual((text, reason), ('only groq', 'ok'))


class OpenAICompatible(Base):
    def test_custom_endpoint_for_a_local_model(self):
        env = {'AI_PROVIDER': 'custom', 'LLM_BASE_URL': 'http://localhost:11434/v1', 'LLM_MODEL': 'llama3.1'}
        with patch.dict(os.environ, env, clear=True), patch.object(ln.requests, 'post', return_value=openai_ok('local')) as post:
            text, reason, _ = ln._call_llm('sys', MSG)
        self.assertEqual((text, reason), ('local', 'ok'))
        self.assertEqual(post.call_args.args[0], 'http://localhost:11434/v1/chat/completions')
        self.assertEqual(post.call_args.kwargs['json']['model'], 'llama3.1')
        self.assertNotIn('authorization', post.call_args.kwargs['headers'])    # no key needed locally

    def test_json_mode_retried_without_response_format_if_rejected(self):
        env = {'AI_PROVIDER': 'groq', 'GROQ_API_KEY': 'g'}
        with patch.dict(os.environ, env, clear=True), patch.object(ln.requests, 'post', side_effect=[http(400, 'bad response_format'), openai_ok('{"a":1}')]) as post:
            text, reason, _ = ln._call_llm('sys', MSG, response_schema={'type': 'object'})
        self.assertEqual((text, reason), ('{"a":1}', 'ok'))
        self.assertIn('response_format', post.call_args_list[0].kwargs['json'])
        self.assertNotIn('response_format', post.call_args_list[1].kwargs['json'])


class GroqDefaults(Base):
    def test_default_groq_model_is_a_current_one_and_reasoning_is_kept_low(self):
        with patch.dict(os.environ, {'AI_PROVIDER': 'groq', 'GROQ_API_KEY': 'g'}, clear=True), patch.object(ln.requests, 'post', return_value=openai_ok('x')) as post:
            ln._call_llm('sys', MSG)
        sent = post.call_args.kwargs['json']
        self.assertEqual(sent['model'], 'openai/gpt-oss-120b')
        self.assertEqual(sent['reasoning_effort'], 'low')

    def test_model_override_from_env_and_no_reasoning_param_for_other_models(self):
        with patch.dict(os.environ, {'AI_PROVIDER': 'groq', 'GROQ_API_KEY': 'g', 'GROQ_MODEL': 'some/other-model'}, clear=True), patch.object(ln.requests, 'post', return_value=openai_ok('x')) as post:
            ln._call_llm('sys', MSG)
        sent = post.call_args.kwargs['json']
        self.assertEqual(sent['model'], 'some/other-model')
        self.assertNotIn('reasoning_effort', sent)
