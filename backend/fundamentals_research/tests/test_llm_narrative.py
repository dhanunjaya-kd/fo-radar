import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fundamentals_research.services import llm_narrative as ln


def _mock_claude_response(text):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {'content': [{'type': 'text', 'text': text}]}
    return resp


class TestApiKeyHandling(unittest.TestCase):
    def test_no_key_returns_none_not_crash(self):
        with patch.dict(os.environ, {}, clear=True):
            result, reason = ln._call_claude('system', [{'role': 'user', 'content': 'hi'}])
        self.assertIsNone(result)
        self.assertEqual(reason, 'no_api_key')


class TestGenerateNarrativeSections(unittest.TestCase):
    def setUp(self):
        self.fact_sheet = {
            'company': {'name': 'Test Corp', 'symbol': 'TEST', 'sector': 'IT', 'industry': 'Software'},
            'financials_by_year': [{'year': '2025-26', 'revenue': 1000.0, 'revenue_growth_yoy_pct': 12.0}],
            'balance_sheet': {'debt_equity': 0.3}, 'cash_flow': {'cfo_to_pat': 1.0},
            'valuation': {'pe': 25.0}, 'ownership': {'promoter_pct': 60.0},
        }

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test'})
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

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test'})
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

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test'})
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

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_malformed_json_returns_none_not_crash(self, mock_post):
        mock_post.return_value = _mock_claude_response("not valid json at all {{{")
        result = ln.generate_narrative_sections(self.fact_sheet)
        self.assertIsNone(result)

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test'})
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

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_http_error_returns_none_not_crash(self, mock_post):
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "Internal Server Error"
        mock_post.return_value = resp
        result = ln.generate_narrative_sections(self.fact_sheet)
        self.assertIsNone(result)

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_network_exception_returns_none_not_crash(self, mock_post):
        import requests
        mock_post.side_effect = requests.exceptions.ConnectionError("network down")
        result = ln.generate_narrative_sections(self.fact_sheet)
        self.assertIsNone(result)


class TestAnswerQuestion(unittest.TestCase):
    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test'})
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

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test'})
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

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_valid_response_parsed_correctly(self, mock_post):
        valid = json.dumps({
            'status': 'Fundamentals relatively stable, technical trend weak',
            'supporting_evidence': ['Revenue grew 10%'], 'opposing_evidence': ['RSI weakening'],
            'conditions_to_monitor': ['Watch EMA50'], 'invalidation_conditions': ['Close below support'],
        })
        mock_post.return_value = _mock_claude_response(valid)
        result, reason = ln.generate_decision_summary(self.fact_sheet, self.confluence, self.entry_setup, self.trend)
        self.assertIsNotNone(result)
        self.assertEqual(reason, 'ok')
        self.assertEqual(result['status'], 'Fundamentals relatively stable, technical trend weak')

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_nonstandard_status_discarded(self, mock_post):
        """The model must use EXACTLY one of the spec's own status
        strings -- an invented one must be discarded, not passed through."""
        bad = json.dumps({
            'status': 'Looks bullish honestly', 'supporting_evidence': [], 'opposing_evidence': [],
            'conditions_to_monitor': [], 'invalidation_conditions': [],
        })
        mock_post.return_value = _mock_claude_response(bad)
        result, reason = ln.generate_decision_summary(self.fact_sheet, self.confluence, self.entry_setup, self.trend)
        self.assertIsNone(result)
        self.assertEqual(reason, 'invalid_status')

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_banned_buy_sell_language_discarded(self, mock_post):
        bad = json.dumps({
            'status': 'Insufficient data', 'supporting_evidence': ['You should buy this now'],
            'opposing_evidence': [], 'conditions_to_monitor': [], 'invalidation_conditions': [],
        })
        mock_post.return_value = _mock_claude_response(bad)
        result, reason = ln.generate_decision_summary(self.fact_sheet, self.confluence, self.entry_setup, self.trend)
        self.assertIsNone(result)
        self.assertEqual(reason, 'banned_term')

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test'})
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

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test'})
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
        result, reason = ln.generate_decision_summary(self.fact_sheet, self.confluence, self.entry_setup, self.trend)
        self.assertIsNone(result)
        self.assertEqual(reason, 'no_api_key')

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test'})
    @patch('fundamentals_research.services.llm_narrative.requests.post')
    def test_missing_required_key_discarded(self, mock_post):
        incomplete = json.dumps({'status': 'Insufficient data'})
        mock_post.return_value = _mock_claude_response(incomplete)
        result, reason = ln.generate_decision_summary(self.fact_sheet, self.confluence, self.entry_setup, self.trend)
        self.assertIsNone(result)
        self.assertEqual(reason, 'missing_keys')
