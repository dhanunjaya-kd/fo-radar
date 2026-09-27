"""
backend/fundamentals_research/services/llm_narrative.py

The AI interpretation layer the original spec always planned for
(Section 10: "RAW DATA -> VALIDATION -> NORMALIZATION -> CALCULATIONS
-> AI INTERPRETATION" -- this file is that last step, deliberately
built last, after the deterministic pipeline was solid).

Hard rule, carried over from report_builder.py and enforced twice
here (in the prompt AND by reusing that file's own banned-term check
on the output): the model narrates and answers questions using ONLY
the numbers in build_fact_sheet()'s output. It never receives
instructions to look anything up, never sees anything beyond this
one snapshot's stored data, and is explicitly told to say "not
available in this report" rather than estimate a missing figure.

Uses plain requests (already a project dependency) against the
Messages API directly -- matches this codebase's own established
pattern (bharatstock_client.py does the same) rather than adding the
`anthropic` SDK as a new dependency for what's a small number of
straightforward calls.
"""
import os
import json
import logging
from typing import Optional, Dict, Any, List

import requests

logger = logging.getLogger('fundamentals_research.llm_narrative')

# --- Anthropic (Claude) provider ---
_ANTHROPIC_API_URL = 'https://api.anthropic.com/v1/messages'
_ANTHROPIC_API_VERSION = '2023-06-01'
# Sep 25 2026: Haiku 4.5, confirmed current via live docs search (not
# memory) -- fast and cheap, appropriate since this runs on every
# refresh. Configurable via env for anyone who wants richer prose from
# Sonnet 5 instead -- also confirmed current, no dated suffix (it's an
# alias). Neither string is guessed.
_ANTHROPIC_DEFAULT_MODEL = os.environ.get('ANTHROPIC_NARRATIVE_MODEL', 'claude-haiku-4-5-20251001')

# --- Gemini provider ---
_GEMINI_API_URL_TEMPLATE = 'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
# Sep 27 2026: confirmed directly against Google's own, 4-day-old
# developer guide (ai.google.dev/gemini-api/docs/gemini-3), not
# guessed and not taken from third-party summaries (several of which
# were confirmed stale during this same search -- e.g. gemini-2.0-flash
# and gemini-2.0-flash-lite were both shut down June 1 2026, per
# Firebase's own docs). The guide's exact words: "Gemini 3 Flash
# gemini-3-flash-preview has a free tier in the Gemini API." Overridable
# via GEMINI_MODEL so this doesn't need a code change if Google renames
# it again.
_GEMINI_DEFAULT_MODEL = 'gemini-3-flash-preview'

DEFAULT_TIMEOUT = 30

_SYSTEM_PROMPT = """You are a financial-data narrator for an Indian equity research tool. You will be given a JSON fact sheet of ALREADY-VERIFIED numbers for one company, pulled from structured financial data sources. Your job is to write clear, analytical prose describing what these numbers show.

STRICT RULES, no exceptions:
1. Use ONLY the numbers given in the fact sheet. Never estimate, infer, or state a figure not explicitly present.
2. If a section's data is missing or null, say so plainly ("not available in this report") -- never fill the gap with a plausible-sounding guess.
3. Never give investment advice or a recommendation. Never use the words: buy, sell, strong buy, strong sell, best stock, worst stock, recommend, target price.
4. Distinguish facts (numbers as given) from your own interpretation (what a trend might suggest) -- make that distinction visible in your writing, e.g. "Revenue grew 12%. This is a meaningfully faster pace than the prior year." not blended into one unattributed claim.
5. Stay factual and measured in tone -- no hype, no alarm, no superlatives not directly supported by the data.
6. Cite the specific number when you reference it, so a reader can verify it against the data above your text."""


def _get_provider() -> str:
    """
    Sep 27 2026. AI_PROVIDER env var, defaults to 'gemini' -- matching
    this project's ACTUAL current setup (Gemini credentials already
    added, no Anthropic key present) rather than defaulting to
    'anthropic' and leaving the AI summary broken out of the box.
    Fully overridable: setting AI_PROVIDER=anthropic (with
    ANTHROPIC_API_KEY present) switches back with no code change.
    """
    return os.environ.get('AI_PROVIDER', 'gemini').strip().lower()


def _get_api_key(provider: str) -> Optional[str]:
    # Sep 27 2026: .strip() added after finding a real, unhandled bug --
    # a trailing newline or space in a copy-pasted .env value (a
    # genuinely common gotcha, especially on Windows) makes the HTTP
    # header invalid, which raises a plain ValueError -- NOT a
    # requests.exceptions.RequestException -- so it would crash
    # unhandled rather than degrade gracefully to 'network_error'.
    # Confirmed by directly reproducing it before writing this fix.
    raw = os.environ.get('GEMINI_API_KEY') if provider == 'gemini' else os.environ.get('ANTHROPIC_API_KEY')
    return raw.strip() if raw else raw


def _call_llm(system: str, messages: List[Dict[str, str]], max_tokens: int = 1500) -> tuple:
    """
    Provider-agnostic entry point -- every caller in this file uses
    THIS, not a provider-specific function directly. Returns (text,
    reason), exact same contract regardless of which provider is
    active, so nothing downstream (JSON parsing, banned-term checks,
    status validation) needs to know or care which provider answered.

    reason values: 'ok', 'no_api_key', 'network_error', 'http_error',
    'parse_error'.
    """
    provider = _get_provider()
    api_key = _get_api_key(provider)
    if not api_key:
        key_name = 'GEMINI_API_KEY' if provider == 'gemini' else 'ANTHROPIC_API_KEY'
        logger.info(f"{key_name} not set (AI_PROVIDER={provider}) -- narrative generation skipped, template fallback will be used.")
        return None, 'no_api_key'

    if provider == 'gemini':
        return _call_gemini(system, messages, max_tokens, api_key)
    return _call_anthropic(system, messages, max_tokens, api_key)


def _call_anthropic(system: str, messages: List[Dict[str, str]], max_tokens: int, api_key: str) -> tuple:
    try:
        resp = requests.post(
            _ANTHROPIC_API_URL,
            headers={'x-api-key': api_key, 'anthropic-version': _ANTHROPIC_API_VERSION, 'content-type': 'application/json'},
            json={'model': _ANTHROPIC_DEFAULT_MODEL, 'max_tokens': max_tokens, 'system': system, 'messages': messages},
            timeout=DEFAULT_TIMEOUT,
        )
    except (requests.exceptions.RequestException, ValueError) as e:
        # ValueError included per a real, confirmed finding: a
        # malformed header value (e.g. from unstripped whitespace)
        # raises plain ValueError, not a RequestException subclass --
        # without this, that case would crash unhandled instead of
        # degrading gracefully.
        logger.warning(f"Claude API call failed (network): {e}")
        return None, 'network_error'

    if resp.status_code != 200:
        logger.warning(f"Claude API returned HTTP {resp.status_code}: {resp.text[:300]}")
        return None, 'http_error'

    try:
        data = resp.json()
        text_blocks = [b['text'] for b in data.get('content', []) if b.get('type') == 'text']
        text = ''.join(text_blocks) if text_blocks else None
        return (text, 'ok') if text is not None else (None, 'parse_error')
    except (ValueError, KeyError) as e:
        logger.warning(f"Claude API response malformed: {e}")
        return None, 'parse_error'


def _call_gemini(system: str, messages: List[Dict[str, str]], max_tokens: int, api_key: str) -> tuple:
    """
    Real Gemini REST call via generateContent -- an officially
    supported API method per Google's own docs (used here directly
    with `requests`, matching this project's established pattern of
    plain REST calls over adding a provider SDK as a new dependency).

    Gemini's message shape differs from Anthropic's and is mapped
    here: role 'assistant' -> 'model' (Gemini's own term), system
    prompt goes in a separate systemInstruction field rather than a
    top-level 'system' key.
    """
    model = (os.environ.get('GEMINI_MODEL') or _GEMINI_DEFAULT_MODEL).strip()
    url = _GEMINI_API_URL_TEMPLATE.format(model=model)

    gemini_contents = [
        {'role': 'model' if m['role'] == 'assistant' else 'user', 'parts': [{'text': m['content']}]}
        for m in messages
    ]

    try:
        resp = requests.post(
            url,
            headers={'x-goog-api-key': api_key, 'content-type': 'application/json'},
            json={
                'contents': gemini_contents,
                'systemInstruction': {'parts': [{'text': system}]},
                'generationConfig': {'maxOutputTokens': max_tokens},
            },
            timeout=DEFAULT_TIMEOUT,
        )
    except (requests.exceptions.RequestException, ValueError) as e:
        logger.warning(f"Gemini API call failed (network): {e}")
        return None, 'network_error'

    if resp.status_code != 200:
        # Sep 27 2026: never log the api_key itself -- confirmed this
        # response body doesn't echo it back (Gemini's own error shape,
        # like Anthropic's, only describes the error, e.g.
        # {"error":{"code":429,"message":"...","status":"RESOURCE_EXHAUSTED"}}),
        # same safety property already verified for the Anthropic path.
        logger.warning(f"Gemini API returned HTTP {resp.status_code}: {resp.text[:300]}")
        return None, 'http_error'

    try:
        data = resp.json()
        candidates = data.get('candidates') or []
        if not candidates:
            return None, 'parse_error'
        parts = candidates[0].get('content', {}).get('parts', [])
        text = ''.join(p.get('text', '') for p in parts) or None
        return (text, 'ok') if text is not None else (None, 'parse_error')
    except (ValueError, KeyError, IndexError, AttributeError) as e:
        logger.warning(f"Gemini API response malformed: {e}")
        return None, 'parse_error'



def build_fact_sheet(snapshot) -> Dict[str, Any]:
    """
    The single source of grounding for BOTH narrative generation and
    chat Q&A -- built once, used for both, so a chat answer can never
    reference a number the narrative didn't also have access to.
    Reads the exact same model fields report_builder.py's template
    functions already use.
    """
    company = snapshot.company
    financials = list(snapshot.financials.all())
    bs = snapshot.balance_sheets.first()
    cf = snapshot.cash_flows.first()
    val = getattr(snapshot, 'valuation', None)
    own = getattr(snapshot, 'ownership', None)

    return {
        'company': {'name': company.company_name, 'symbol': company.symbol, 'sector': company.sector, 'industry': company.industry},
        'financials_by_year': [
            {'year': f.fiscal_year, 'revenue': _n(f.revenue), 'revenue_growth_yoy_pct': _n(f.revenue_growth_yoy_pct),
             'ebitda': _n(f.ebitda), 'ebitda_margin_pct': _n(f.ebitda_margin_pct), 'pat': _n(f.pat),
             'pat_margin_pct': _n(f.pat_margin_pct), 'pat_growth_yoy_pct': _n(f.pat_growth_yoy_pct),
             'eps': _n(f.eps), 'roe_pct': _n(f.roe_pct), 'source': f.source}
            for f in financials
        ],
        'balance_sheet': None if bs is None else {
            'fiscal_year': bs.fiscal_year, 'total_debt': _n(bs.total_debt), 'cash': _n(bs.cash),
            'net_debt': _n(bs.net_debt), 'debt_equity': _n(bs.debt_equity), 'current_ratio': _n(bs.current_ratio),
            'source': bs.source,
        },
        'cash_flow': None if cf is None else {
            'fiscal_year': cf.fiscal_year, 'operating_cash_flow': _n(cf.operating_cash_flow),
            'free_cash_flow': _n(cf.free_cash_flow), 'cfo_to_pat': _n(cf.cfo_to_pat), 'source': cf.source,
        },
        'valuation': None if val is None else {
            'pe': _n(val.pe), 'pb': _n(val.pb), 'ev_ebitda': _n(val.ev_ebitda),
            'dividend_yield_pct': _n(val.dividend_yield_pct), 'week_52_high': _n(val.week_52_high),
            'week_52_low': _n(val.week_52_low), 'distance_from_52w_high_pct': _n(val.distance_from_52w_high_pct),
            'source': val.source,
        },
        'ownership': None if own is None else {
            'promoter_pct': _n(own.promoter_pct), 'promoter_change_pct': _n(own.promoter_change_pct),
            'promoter_pledge_pct': _n(own.promoter_pledge_pct), 'fii_pct': _n(own.fii_pct), 'dii_pct': _n(own.dii_pct),
            'public_pct': _n(own.public_pct), 'source': own.source,
        },
    }


def _n(decimal_value):
    """Decimal -> float or None, for clean JSON serialization -- never
    a Decimal object reaching json.dumps(), never a silent str-cast
    that would confuse the model about whether something is a number."""
    return None if decimal_value is None else float(decimal_value)


def generate_narrative_sections(fact_sheet: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """
    Returns a dict with the same keys report_builder.py's template
    functions produce (financial_quality_notes, balance_sheet_notes,
    cash_flow_notes, ownership_notes, valuation_notes), or None if the
    API call failed for any reason -- report_builder.py's own
    template versions are the fallback, not duplicated here.
    """
    prompt = f"""Fact sheet for {fact_sheet['company']['name']} ({fact_sheet['company']['symbol']}):

{json.dumps(fact_sheet, indent=2)}

Write five short sections analyzing this data. Return ONLY valid JSON, no other text, with exactly these keys:
{{
  "financial_quality_notes": "...",
  "balance_sheet_notes": "...",
  "cash_flow_notes": "...",
  "ownership_notes": "...",
  "valuation_notes": "..."
}}
Each value should be 2-4 sentences. If a section's underlying data is null in the fact sheet, that section's text must say the data isn't available -- do not skip the key or invent content for it."""

    raw, _reason = _call_llm(_SYSTEM_PROMPT, [{'role': 'user', 'content': prompt}], max_tokens=1200)
    if raw is None:
        return None

    try:
        cleaned = raw.strip()
        if cleaned.startswith('```'):
            cleaned = cleaned.split('```')[1]
            if cleaned.startswith('json'):
                cleaned = cleaned[4:]
        sections = json.loads(cleaned.strip())
    except (ValueError, IndexError) as e:
        logger.warning(f"Could not parse narrative JSON from Claude response: {e}")
        return None

    required_keys = {'financial_quality_notes', 'balance_sheet_notes', 'cash_flow_notes', 'ownership_notes', 'valuation_notes'}
    if not required_keys.issubset(sections.keys()):
        logger.warning(f"Narrative response missing expected keys: {required_keys - sections.keys()}")
        return None

    full_text = ' '.join(str(v) for v in sections.values()).lower()
    from .report_builder import _BANNED_TERMS
    for term in _BANNED_TERMS:
        if term in full_text:
            logger.warning(f"LLM narrative contained banned term '{term}' -- discarding, template fallback will be used instead.")
            return None

    return sections


def answer_question(fact_sheet: Dict[str, Any], question: str, conversation_history: Optional[List[Dict[str, str]]] = None) -> str:
    """
    conversation_history: prior turns as [{'role': 'user'|'assistant', 'content': ...}, ...]
    -- kept and sent by the FRONTEND (stateless on the backend, no new
    model added for this first version), matching a standard,
    perfectly valid chat-UI pattern that doesn't require persisting
    conversation state server-side.

    Always returns a string -- on any failure, returns a plain,
    honest error message rather than None, since this is a direct
    user-facing response, not a section with a template fallback to
    fall back to.
    """
    context_prompt = f"Fact sheet for {fact_sheet['company']['name']} ({fact_sheet['company']['symbol']}):\n\n{json.dumps(fact_sheet, indent=2)}"
    messages = [{'role': 'user', 'content': context_prompt}, {'role': 'assistant', 'content': "I have the fact sheet. Ask me anything about this company's numbers."}]
    messages.extend(conversation_history or [])
    messages.append({'role': 'user', 'content': question})

    system = _SYSTEM_PROMPT + "\n\nYou are now answering a direct follow-up question from the user about this company. If the answer isn't in the fact sheet, say so plainly -- do not guess."
    answer, _reason = _call_llm(system, messages, max_tokens=600)
    if answer is None:
        return "Sorry, I couldn't generate an answer right now -- the AI service is unavailable or not configured. The structured data above is still accurate and unaffected."
    return answer


_DECISION_STATUSES = [
    'Potential setup - confirmation pending', 'Setup confirmed under defined conditions',
    'Trend remains bearish', 'Fundamentals deteriorating',
    'Fundamentals relatively stable, technical trend weak', 'Risk elevated', 'Insufficient data',
]

_ROMAN_TELUGU_INSTRUCTION = (
    "Write your response in Roman Telugu (Telugu language, written in Latin/English script) "
    "as the default. Keep standard financial terms in English exactly as given, never translated "
    "or transliterated: BUY, SELL, RSI, EMA, OI, SL, Target, and similarly-standard terms."
)


def generate_decision_summary(
    fact_sheet: Dict[str, Any], confluence: Dict[str, Any], entry_setup: Dict[str, Any],
    trend_classification: Dict[str, str], language: str = 'english',
) -> tuple:
    """
    Sep 26 2026. Synthesizes the ALREADY-COMPUTED confluence.py,
    entry_setup.py, and technical_analysis.py outputs (passed in, not
    re-fetched) into the spec's exact required decision-summary shape.
    No new numbers are given to the model here beyond what these three
    already-deterministic modules produced -- this function's only job
    is turning structured data into the required narrative fields
    (supporting evidence / opposing evidence / conditions to monitor
    etc.), not generating new figures.

    language: 'english' (default, safe/explicit -- does not silently
    change behavior for existing callers) or 'roman_telugu' (per this
    feature's own spec -- opt-in via this parameter, not forced).

    Returns (summary_dict_or_None, reason). reason is always populated,
    even on success ('ok'), so the caller (ultimately the API response)
    can show WHY, not just THAT, e.g. "AI not configured" vs "AI call
    failed" -- previously indistinguishable, which the spec this was
    built against explicitly asked to fix.
    Possible reasons: 'ok', 'no_api_key', 'network_error', 'http_error',
    'parse_error' (the API call's own response wasn't valid), 'json_parse_error'
    (got text back but it wasn't valid JSON), 'missing_keys', 'invalid_status',
    'banned_term'.
    """
    combined_input = {
        'fact_sheet': fact_sheet, 'confluence': confluence,
        'entry_setup': entry_setup, 'trend_classification': trend_classification,
    }
    language_instruction = _ROMAN_TELUGU_INSTRUCTION if language == 'roman_telugu' else ""

    prompt = f"""Data for {fact_sheet['company']['name']} ({fact_sheet['company']['symbol']}):

{json.dumps(combined_input, indent=2)}

Write a decision summary. Return ONLY valid JSON, no other text, with exactly these keys:
{{
  "status": "...",
  "supporting_evidence": ["...", "..."],
  "opposing_evidence": ["...", "..."],
  "conditions_to_monitor": ["...", "..."],
  "invalidation_conditions": ["...", "..."]
}}

"status" MUST be exactly one of these strings (choose the single best match, do not invent a new one):
{json.dumps(_DECISION_STATUSES)}

Each evidence/condition list: 2-4 short items, each citing a specific number or classification from the data above. If the evidence is genuinely conflicting or data is missing, "status" must be "Insufficient data" or reflect the conflict honestly -- never force a confident status the data doesn't support.
{language_instruction}"""

    raw, call_reason = _call_llm(_SYSTEM_PROMPT, [{'role': 'user', 'content': prompt}], max_tokens=1000)
    if raw is None:
        return None, call_reason

    try:
        cleaned = raw.strip()
        if cleaned.startswith('```'):
            cleaned = cleaned.split('```')[1]
            if cleaned.startswith('json'):
                cleaned = cleaned[4:]
        summary = json.loads(cleaned.strip())
    except (ValueError, IndexError) as e:
        logger.warning(f"Could not parse decision summary JSON from Claude response: {e}")
        return None, 'json_parse_error'

    required_keys = {'status', 'supporting_evidence', 'opposing_evidence', 'conditions_to_monitor', 'invalidation_conditions'}
    if not required_keys.issubset(summary.keys()):
        logger.warning(f"Decision summary missing expected keys: {required_keys - summary.keys()}")
        return None, 'missing_keys'

    if summary['status'] not in _DECISION_STATUSES:
        logger.warning(f"Decision summary used a non-standard status '{summary['status']}' -- discarding.")
        return None, 'invalid_status'

    full_text = ' '.join(str(v) for v in summary.values() if isinstance(v, (str, list)) for v in ([v] if isinstance(v, str) else v)).lower()
    from .report_builder import _BANNED_TERMS
    for term in _BANNED_TERMS:
        if term in full_text:
            logger.warning(f"Decision summary contained banned term '{term}' -- discarding.")
            return None, 'banned_term'

    return summary, 'ok'
