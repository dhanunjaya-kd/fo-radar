import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock
import requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fundamentals_research.services import llm_narrative as ln


def _mock_claude_response(text):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {'content': [{'type': 'text', 'text': text}]}
    return resp


def _mock_gemini_response(text):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {'candidates': [{'content': {'parts': [{'text': text}]}, 'finishReason': 'STOP'}]}
    return resp


class TestApiKeyHandling(unittest.TestCase):
    def test_no_key_returns_none_not_crash(self):
        with patch.dict(os.environ, {}, clear=True):
            result, reason, detail = ln._call_llm('system', [{'role': 'user', 'content': 'hi'}])
        self.assertIsNone(result)
        self.assertEqual(reason, 'no_api_key')

    def test_default_provider_is_gemini(self):
        """Real, confirmed intent: default AI_PROVIDER is 'gemini'
        (matching this project's actual current setup -- Gemini
        credentials added, no Anthropic key), not 'anthropic'."""
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ln._get_provider(), 'gemini')

    def test_gemini_provider_looks_for_gemini_api_key_not_anthropic(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test-key'}, clear=True):
            result, reason, detail = ln._call_llm('system', [{'role': 'user', 'content': 'hi'}])
        # key IS present, so this should NOT be 'no_api_key' -- it'll
        # genuinely try a network call and fail (no mock here), proving
        # the key was found and used, not skipped
        self.assertNotEqual(reason, 'no_api_key')

    def test_trailing_whitespace_in_env_key_stripped_not_crashed(self):
        """Real bug found and fixed: a trailing newline/space in a
        copy-pasted .env value makes the HTTP header invalid, which
        raises plain ValueError (confirmed by direct reproduction) --
        not a requests.exceptions subclass. Without stripping AND the
        broadened except clause, this would crash unhandled instead of
        degrading gracefully."""
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test-key\n', 'AI_PROVIDER': 'gemini'}, clear=True), \
             patch('fundamentals_research.services.llm_narrative.requests.post') as mock_post:
            mock_post.return_value = _mock_gemini_response('ok')
            text, reason, detail = ln._call_llm('system', [{'role': 'user', 'content': 'hi'}])
        self.assertEqual(reason, 'ok')  # stripped correctly, no crash, real call succeeded
        sent_headers = mock_post.call_args.kwargs['headers']
        self.assertEqual(sent_headers['x-goog-api-key'], 'test-key')  # confirmed stripped, not left with the newline

    def test_malformed_header_value_degrades_gracefully_not_unhandled_crash(self):
        """Defense in depth: even if some OTHER unanticipated invalid
        character slips through, this must never raise an unhandled
        500 -- confirmed by directly reproducing the real ValueError
        requests raises for an invalid header value."""
        with patch.dict(os.environ, {'AI_PROVIDER': 'gemini'}, clear=True), \
             patch('fundamentals_research.services.llm_narrative.requests.post', side_effect=ValueError("Invalid header value")):
            with patch('fundamentals_research.services.llm_narrative._get_api_key', return_value='key-with-\x00-null'):
                text, reason, detail = ln._call_llm('system', [{'role': 'user', 'content': 'hi'}])
        self.assertIsNone(text)
        self.assertEqual(reason, 'network_error')  # graceful, not a crash

    def test_anthropic_provider_selected_explicitly_looks_for_anthropic_key(self):
        with patch.dict(os.environ, {'AI_PROVIDER': 'anthropic'}, clear=True):
            result, reason, detail = ln._call_llm('system', [{'role': 'user', 'content': 'hi'}])
        self.assertEqual(reason, 'no_api_key')  # ANTHROPIC_API_KEY genuinely absent here


class TestCallGemini(unittest.TestCase):
    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-gemini-key', 'AI_PROVIDER': 'gemini'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_successful_call_parses_response_correctly(self, mock_post):
        mock_post.return_value = _mock_gemini_response('Hello from Gemini')
        text, reason, detail = ln._call_llm('system prompt', [{'role': 'user', 'content': 'hi'}])
        self.assertEqual(reason, 'ok')
        self.assertEqual(text, 'Hello from Gemini')

    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-gemini-key', 'AI_PROVIDER': 'gemini'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_uses_correct_model_and_url(self, mock_post):
        mock_post.return_value = _mock_gemini_response('ok')
        ln._call_llm('system prompt', [{'role': 'user', 'content': 'hi'}])
        called_url = mock_post.call_args[0][0]
        self.assertIn('gemini-3-flash-preview', called_url)
        self.assertIn('generateContent', called_url)

    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-gemini-key', 'AI_PROVIDER': 'gemini'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_api_key_sent_as_header_not_url_param(self, mock_post):
        """Explicit security check: the key must go in a header
        (x-goog-api-key), never appended to the URL where it could leak
        into logs or browser history more easily."""
        mock_post.return_value = _mock_gemini_response('ok')
        ln._call_llm('system prompt', [{'role': 'user', 'content': 'hi'}])
        called_url = mock_post.call_args[0][0]
        called_headers = mock_post.call_args.kwargs['headers']
        self.assertNotIn('test-gemini-key', called_url)
        self.assertEqual(called_headers['x-goog-api-key'], 'test-gemini-key')

    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-gemini-key', 'AI_PROVIDER': 'gemini'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_message_roles_mapped_correctly_for_gemini(self, mock_post):
        """Gemini uses 'model' where Anthropic uses 'assistant' --
        confirms the mapping, not just that a request goes out."""
        mock_post.return_value = _mock_gemini_response('ok')
        messages = [{'role': 'user', 'content': 'Q1'}, {'role': 'assistant', 'content': 'A1'}, {'role': 'user', 'content': 'Q2'}]
        ln._call_llm('system prompt', messages)
        sent_contents = mock_post.call_args.kwargs['json']['contents']
        self.assertEqual(sent_contents[1]['role'], 'model')  # 'assistant' mapped to Gemini's 'model'
        self.assertEqual(sent_contents[0]['role'], 'user')

    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-gemini-key', 'AI_PROVIDER': 'gemini'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_system_prompt_sent_as_system_instruction_not_a_message(self, mock_post):
        mock_post.return_value = _mock_gemini_response('ok')
        ln._call_llm('MY SYSTEM PROMPT', [{'role': 'user', 'content': 'hi'}])
        sent_body = mock_post.call_args.kwargs['json']
        self.assertEqual(sent_body['systemInstruction']['parts'][0]['text'], 'MY SYSTEM PROMPT')
        # confirm it's NOT duplicated into the contents list
        for c in sent_body['contents']:
            for part in c['parts']:
                self.assertNotEqual(part['text'], 'MY SYSTEM PROMPT')

    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-gemini-key', 'AI_PROVIDER': 'gemini'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_http_error_returns_error_reason_not_crash(self, mock_post):
        resp = MagicMock()
        resp.status_code = 429
        resp.text = '{"error":{"code":429,"message":"Resource exhausted","status":"RESOURCE_EXHAUSTED"}}'
        mock_post.return_value = resp
        text, reason, detail = ln._call_llm('system', [{'role': 'user', 'content': 'hi'}])
        self.assertIsNone(text)
        self.assertEqual(reason, 'http_error')

    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-gemini-key', 'AI_PROVIDER': 'gemini'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_network_error_returns_network_error_reason(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError("down")
        text, reason, detail = ln._call_llm('system', [{'role': 'user', 'content': 'hi'}])
        self.assertIsNone(text)
        self.assertEqual(reason, 'network_error')

    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-gemini-key', 'AI_PROVIDER': 'gemini'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_empty_candidates_returns_parse_error_not_crash(self, mock_post):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {'candidates': []}
        mock_post.return_value = resp
        text, reason, detail = ln._call_llm('system', [{'role': 'user', 'content': 'hi'}])
        self.assertIsNone(text)
        self.assertEqual(reason, 'parse_error')

    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-gemini-key', 'AI_PROVIDER': 'gemini'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_malformed_response_shape_returns_parse_error_not_crash(self, mock_post):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {'candidates': [{'content': {}}]}  # missing 'parts' entirely
        mock_post.return_value = resp
        text, reason, detail = ln._call_llm('system', [{'role': 'user', 'content': 'hi'}])
        self.assertIsNone(text)
        self.assertEqual(reason, 'parse_error')

    @patch.dict(os.environ, {'GEMINI_MODEL': 'gemini-custom-override', 'GEMINI_API_KEY': 'test-gemini-key', 'AI_PROVIDER': 'gemini'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_gemini_model_overridable_via_env_var(self, mock_post):
        mock_post.return_value = _mock_gemini_response('ok')
        ln._call_llm('system', [{'role': 'user', 'content': 'hi'}])
        called_url = mock_post.call_args[0][0]
        self.assertIn('gemini-custom-override', called_url)

    def test_full_pipeline_generate_narrative_sections_works_with_gemini(self):
        """Confirms the REAL, end-to-end narrative generation function
        (not just the low-level call) works with Gemini -- same JSON
        parsing, same banned-term check, same everything downstream."""
        valid_json = json.dumps({
            'financial_quality_notes': 'Revenue grew.', 'balance_sheet_notes': 'x',
            'cash_flow_notes': 'x', 'ownership_notes': 'x', 'valuation_notes': 'x',
        })
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test-gemini-key', 'AI_PROVIDER': 'gemini'}), \
             patch('fundamentals_research.services.llm_narrative.requests.post') as mock_post:
            mock_post.return_value = _mock_gemini_response(valid_json)
            result = ln.generate_narrative_sections({'company': {'name': 'Test', 'symbol': 'TST'}})
        self.assertIsNotNone(result)
        self.assertIn('grew', result['financial_quality_notes'])


class TestGenerateNarrativeSections(unittest.TestCase):
    def setUp(self):
        self.fact_sheet = {
            'company': {'name': 'Test Corp', 'symbol': 'TEST', 'sector': 'IT', 'industry': 'Software'},
            'financials_by_year': [{'year': '2025-26', 'revenue': 1000.0, 'revenue_growth_yoy_pct': 12.0}],
            'balance_sheet': {'debt_equity': 0.3}, 'cash_flow': {'cfo_to_pat': 1.0},
            'valuation': {'pe': 25.0}, 'ownership': {'promoter_pct': 60.0},
        }

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test', 'AI_PROVIDER': 'anthropic'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_valid_json_response_parsed_correctly(self, mock_post):
        valid_json = json.dumps({
            'financial_quality_notes': 'Revenue grew 12% to 1000, a solid pace.',
            'balance_sheet_notes': 'Debt/Equity of 0.3 indicates moderate leverage.',
            'cash_flow_notes': 'CFO/PAT of 1.0 shows full cash conversion.',
            'ownership_notes': 'Promoter holding of 60% is stable.',
            'valuation_notes': 'P/E of 25 reflects current market pricing.',
        })
        mock_post.return_value = _mock_claude_response(valid_json)
        result = ln.generate_narrative_sections(self.fact_sheet)
        self.assertIsNotNone(result)
        self.assertIn('grew 12%', result['financial_quality_notes'])

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test', 'AI_PROVIDER': 'anthropic'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_response_wrapped_in_markdown_fence_still_parses(self, mock_post):
        """Models often wrap JSON in ```json fences despite instructions not to -- must handle this, not just the ideal case."""
        wrapped = "```json\n" + json.dumps({
            'financial_quality_notes': 'x', 'balance_sheet_notes': 'x', 'cash_flow_notes': 'x',
            'ownership_notes': 'x', 'valuation_notes': 'x',
        }) + "\n```"
        mock_post.return_value = _mock_claude_response(wrapped)
        result = ln.generate_narrative_sections(self.fact_sheet)
        self.assertIsNotNone(result)

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test', 'AI_PROVIDER': 'anthropic'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_banned_term_in_response_discards_entire_result(self, mock_post):
        """Same hard rule as report_builder.py's template output --
        applies to LLM output too, checked explicitly, not assumed
        the prompt alone is enough."""
        bad_json = json.dumps({
            'financial_quality_notes': 'This looks like a strong buy given the growth.',
            'balance_sheet_notes': 'x', 'cash_flow_notes': 'x', 'ownership_notes': 'x', 'valuation_notes': 'x',
        })
        mock_post.return_value = _mock_claude_response(bad_json)
        result = ln.generate_narrative_sections(self.fact_sheet)
        self.assertIsNone(result)  # discarded entirely, caller falls back to templates

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test', 'AI_PROVIDER': 'anthropic'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_malformed_json_returns_none_not_crash(self, mock_post):
        mock_post.return_value = _mock_claude_response("not valid json at all {{{")
        result = ln.generate_narrative_sections(self.fact_sheet)
        self.assertIsNone(result)

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test', 'AI_PROVIDER': 'anthropic'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_missing_required_key_returns_none(self, mock_post):
        incomplete = json.dumps({'financial_quality_notes': 'x'})  # missing 4 of 5 keys
        mock_post.return_value = _mock_claude_response(incomplete)
        result = ln.generate_narrative_sections(self.fact_sheet)
        self.assertIsNone(result)

    @patch.dict(os.environ, {}, clear=True)
    def test_no_api_key_returns_none(self):
        result = ln.generate_narrative_sections(self.fact_sheet)
        self.assertIsNone(result)

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test', 'AI_PROVIDER': 'anthropic'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_http_error_returns_none_not_crash(self, mock_post):
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "Internal Server Error"
        mock_post.return_value = resp
        result = ln.generate_narrative_sections(self.fact_sheet)
        self.assertIsNone(result)

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test', 'AI_PROVIDER': 'anthropic'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_network_exception_returns_none_not_crash(self, mock_post):
        import requests
        mock_post.side_effect = requests.exceptions.ConnectionError("network down")
        result = ln.generate_narrative_sections(self.fact_sheet)
        self.assertIsNone(result)


class TestAnswerQuestion(unittest.TestCase):
    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test', 'AI_PROVIDER': 'anthropic'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_answers_using_fact_sheet_context(self, mock_post):
        mock_post.return_value = _mock_claude_response("Revenue grew 12% to 1000, driven by strong demand per the data provided.")
        fact_sheet = {'company': {'name': 'Test Corp', 'symbol': 'TEST'}, 'financials_by_year': [{'year': '2025-26', 'revenue': 1000.0}]}
        answer = ln.answer_question(fact_sheet, "Why did revenue grow?")
        self.assertIn('12%', answer)
        # confirm the fact sheet was actually sent as context, not just the bare question
        sent_messages = mock_post.call_args.kwargs['json']['messages']
        self.assertTrue(any('Test Corp' in m['content'] for m in sent_messages))

    @patch.dict(os.environ, {}, clear=True)
    def test_no_key_returns_honest_error_string_not_none(self):
        """Unlike generate_narrative_sections, this is user-facing --
        must always return a real string the chat UI can display,
        never None."""
        fact_sheet = {'company': {'name': 'Test Corp', 'symbol': 'TEST'}}
        answer = ln.answer_question(fact_sheet, "Why?")
        self.assertIsInstance(answer, str)
        self.assertIn('unavailable', answer.lower())

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test', 'AI_PROVIDER': 'anthropic'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_conversation_history_included_in_request(self, mock_post):
        mock_post.return_value = _mock_claude_response("Follow-up answer.")
        fact_sheet = {'company': {'name': 'Test Corp', 'symbol': 'TEST'}}
        history = [{'role': 'user', 'content': 'First question'}, {'role': 'assistant', 'content': 'First answer'}]
        ln.answer_question(fact_sheet, "Second question", conversation_history=history)
        sent_messages = mock_post.call_args.kwargs['json']['messages']
        contents = [m['content'] for m in sent_messages]
        self.assertIn('First question', contents)
        self.assertIn('Second question', contents)


class TestBuildFactSheetNeverCrashes(unittest.TestCase):
    def test_none_related_objects_handled(self):
        """A snapshot with no valuation/ownership rows yet (a genuine,
        valid partial state) must produce None for those keys, not crash."""
        fake_snapshot = MagicMock()
        fake_snapshot.company.company_name = 'Test'
        fake_snapshot.company.symbol = 'TEST'
        fake_snapshot.company.sector = None
        fake_snapshot.company.industry = None
        fake_snapshot.financials.all.return_value = []
        fake_snapshot.balance_sheets.first.return_value = None
        fake_snapshot.cash_flows.first.return_value = None
        del fake_snapshot.valuation  # simulate no OneToOne row existing
        del fake_snapshot.ownership

        result = ln.build_fact_sheet(fake_snapshot)
        self.assertIsNone(result['balance_sheet'])
        self.assertIsNone(result['cash_flow'])
        self.assertIsNone(result['valuation'])
        self.assertIsNone(result['ownership'])
        self.assertEqual(result['financials_by_year'], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)


class TestGenerateDecisionSummary(unittest.TestCase):
    def setUp(self):
        self.fact_sheet = {'company': {'name': 'Test Corp', 'symbol': 'TEST'}}
        self.confluence = {'fundamental_quality': {'assessment': 'Strong'}}
        self.entry_setup = {'status': 'no_setup'}
        self.trend = {'classification': 'Weakening trend'}

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test', 'AI_PROVIDER': 'anthropic'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_valid_response_parsed_correctly(self, mock_post):
        valid = json.dumps({
            'status': 'Fundamentals relatively stable, technical trend weak',
            'supporting_evidence': ['Revenue grew 10%'], 'opposing_evidence': ['RSI weakening'],
            'conditions_to_monitor': ['Watch EMA50'], 'invalidation_conditions': ['Close below support'],
        })
        mock_post.return_value = _mock_claude_response(valid)
        result, reason, detail = ln.generate_decision_summary(self.fact_sheet, self.confluence, self.entry_setup, self.trend)
        self.assertIsNotNone(result)
        self.assertEqual(reason, 'ok')
        self.assertEqual(result['status'], 'Fundamentals relatively stable, technical trend weak')

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test', 'AI_PROVIDER': 'anthropic'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_nonstandard_status_discarded(self, mock_post):
        """The model must use EXACTLY one of the spec's own status
        strings -- an invented one must be discarded, not passed through."""
        bad = json.dumps({
            'status': 'Looks bullish honestly', 'supporting_evidence': [], 'opposing_evidence': [],
            'conditions_to_monitor': [], 'invalidation_conditions': [],
        })
        mock_post.return_value = _mock_claude_response(bad)
        result, reason, detail = ln.generate_decision_summary(self.fact_sheet, self.confluence, self.entry_setup, self.trend)
        self.assertIsNone(result)
        self.assertEqual(reason, 'invalid_status')

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test', 'AI_PROVIDER': 'anthropic'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_banned_buy_sell_language_discarded(self, mock_post):
        bad = json.dumps({
            'status': 'Insufficient data', 'supporting_evidence': ['You should buy this now'],
            'opposing_evidence': [], 'conditions_to_monitor': [], 'invalidation_conditions': [],
        })
        mock_post.return_value = _mock_claude_response(bad)
        result, reason, detail = ln.generate_decision_summary(self.fact_sheet, self.confluence, self.entry_setup, self.trend)
        self.assertIsNone(result)
        self.assertEqual(reason, 'banned_term')

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test', 'AI_PROVIDER': 'anthropic'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_roman_telugu_instruction_included_when_requested(self, mock_post):
        valid = json.dumps({
            'status': 'Insufficient data', 'supporting_evidence': [], 'opposing_evidence': [],
            'conditions_to_monitor': [], 'invalidation_conditions': [],
        })
        mock_post.return_value = _mock_claude_response(valid)
        ln.generate_decision_summary(self.fact_sheet, self.confluence, self.entry_setup, self.trend, language='roman_telugu')
        sent_prompt = mock_post.call_args.kwargs['json']['messages'][0]['content']
        self.assertIn('Roman Telugu', sent_prompt)
        self.assertIn('BUY, SELL, RSI, EMA, OI, SL, Target', sent_prompt)

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test', 'AI_PROVIDER': 'anthropic'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_english_default_does_not_include_telugu_instruction(self, mock_post):
        """Default language must stay English -- no silent behavior
        change for existing callers who don't pass language= at all."""
        valid = json.dumps({
            'status': 'Insufficient data', 'supporting_evidence': [], 'opposing_evidence': [],
            'conditions_to_monitor': [], 'invalidation_conditions': [],
        })
        mock_post.return_value = _mock_claude_response(valid)
        ln.generate_decision_summary(self.fact_sheet, self.confluence, self.entry_setup, self.trend)
        sent_prompt = mock_post.call_args.kwargs['json']['messages'][0]['content']
        self.assertNotIn('Roman Telugu', sent_prompt)

    @patch.dict(os.environ, {}, clear=True)
    def test_no_api_key_returns_none(self):
        """This is the exact real-world case behind 'AI decision summary
        unavailable (not configured or the call failed)' -- confirms the
        reason code is specifically 'no_api_key', distinguishable from
        every other failure mode now."""
        result, reason, detail = ln.generate_decision_summary(self.fact_sheet, self.confluence, self.entry_setup, self.trend)
        self.assertIsNone(result)
        self.assertEqual(reason, 'no_api_key')

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test', 'AI_PROVIDER': 'anthropic'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_missing_required_key_discarded(self, mock_post):
        incomplete = json.dumps({'status': 'Insufficient data'})
        mock_post.return_value = _mock_claude_response(incomplete)
        result, reason, detail = ln.generate_decision_summary(self.fact_sheet, self.confluence, self.entry_setup, self.trend)
        self.assertIsNone(result)
        self.assertEqual(reason, 'missing_keys')
