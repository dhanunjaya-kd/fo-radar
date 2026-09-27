"""
backend/fundamentals_research/views.py

Endpoints exactly as listed in spec Section 22, adapted to this
project's existing convention (function-agnostic APIView classes,
matching screener/views.py's own style rather than introducing DRF
ViewSets this codebase doesn't otherwise use).
"""
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404

from .models import ResearchCompany, ResearchSnapshot, ResearchReport
from .serializers import ResearchSnapshotDetailSerializer, ResearchSnapshotListSerializer, ResearchCompanySerializer
from .services import research_engine, report_builder, llm_narrative

logger = logging.getLogger('fundamentals_research.views')


def _latest_snapshot_or_none(symbol):
    return (ResearchSnapshot.objects
            .filter(company__symbol=symbol.upper())
            .select_related('company')
            .order_by('-snapshot_date', '-created_at')
            .first())


class ResearchSearchView(APIView):
    """GET /api/research/search/?q=RELIANCE
    Resolves against the EXISTING symbol master (fundamentals/symbol_master.py)
    rather than a new symbol list -- per spec Section 25's own instruction
    to use existing infrastructure."""
    def get(self, request):
        query = (request.query_params.get('q') or '').strip().upper()
        if not query:
            return Response({'results': []})
        try:
            from fundamentals.symbol_master import get_nse_equity_symbols
            all_symbols = get_nse_equity_symbols()
            matches = [s for s in all_symbols if query in s.upper()][:20]
        except Exception as e:
            logger.warning(f"Symbol master lookup failed, falling back to exact-match only: {e}")
            matches = [query]
        return Response({'query': query, 'results': matches})


class CompanyView(APIView):
    """GET /api/research/company/{symbol}/ -- latest snapshot's headline data."""
    def get(self, request, symbol):
        snapshot = _latest_snapshot_or_none(symbol)
        if not snapshot:
            return Response({'detail': f'No research on file for {symbol.upper()} yet -- POST to /refresh/ to generate one.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(ResearchSnapshotDetailSerializer(snapshot).data)


class CompanyFinancialsView(APIView):
    """GET /api/research/company/{symbol}/financials/"""
    def get(self, request, symbol):
        snapshot = _latest_snapshot_or_none(symbol)
        if not snapshot:
            return Response({'detail': 'No research on file yet.'}, status=status.HTTP_404_NOT_FOUND)
        from .serializers import FinancialSnapshotSerializer, QuarterlyFinancialSnapshotSerializer
        return Response({
            'annual': FinancialSnapshotSerializer(snapshot.financials.all(), many=True).data,
            'quarterly': QuarterlyFinancialSnapshotSerializer(snapshot.quarterly_financials.all(), many=True).data,
        })


class CompanyValuationView(APIView):
    """GET /api/research/company/{symbol}/valuation/"""
    def get(self, request, symbol):
        snapshot = _latest_snapshot_or_none(symbol)
        if not snapshot or not hasattr(snapshot, 'valuation'):
            return Response({'detail': 'No valuation data on file yet.'}, status=status.HTTP_404_NOT_FOUND)
        from .serializers import ValuationSnapshotSerializer
        return Response(ValuationSnapshotSerializer(snapshot.valuation).data)


class CompanyOwnershipView(APIView):
    """GET /api/research/company/{symbol}/ownership/"""
    def get(self, request, symbol):
        snapshot = _latest_snapshot_or_none(symbol)
        if not snapshot or not hasattr(snapshot, 'ownership'):
            return Response({'detail': 'No ownership data on file yet.'}, status=status.HTTP_404_NOT_FOUND)
        from .serializers import OwnershipSnapshotSerializer
        return Response(OwnershipSnapshotSerializer(snapshot.ownership).data)


class CompanyNewsView(APIView):
    """GET /api/research/company/{symbol}/news/"""
    def get(self, request, symbol):
        snapshot = _latest_snapshot_or_none(symbol)
        if not snapshot:
            return Response({'detail': 'No research on file yet.'}, status=status.HTTP_404_NOT_FOUND)
        from .serializers import ResearchNewsItemSerializer
        return Response(ResearchNewsItemSerializer(snapshot.news_items.all(), many=True).data)


class CompanyReportView(APIView):
    """GET /api/research/company/{symbol}/report/ -- the full assembled report."""
    def get(self, request, symbol):
        snapshot = _latest_snapshot_or_none(symbol)
        if not snapshot:
            return Response({'detail': f'No research on file for {symbol.upper()} yet -- POST to /refresh/ to generate one.'}, status=status.HTTP_404_NOT_FOUND)
        from .services import freshness as fr
        data = ResearchSnapshotDetailSerializer(snapshot).data
        data['freshness'] = fr.assess_snapshot_freshness(snapshot)
        return Response(data)


class CompanyHistoryView(APIView):
    """GET /api/research/company/{symbol}/history/ -- list of past snapshots."""
    def get(self, request, symbol):
        snapshots = ResearchSnapshot.objects.filter(company__symbol=symbol.upper()).order_by('-snapshot_date')
        return Response(ResearchSnapshotListSerializer(snapshots, many=True).data)


class CompanyRefreshView(APIView):
    """
    POST /api/research/company/{symbol}/refresh/

    Synchronous, per spec Section 23's own explicit fallback rule
    ("if background jobs are not already available, implement a clean
    synchronous version first with sensible timeouts") -- this
    project's own established pattern (confirmed throughout this whole
    codebase) is daemon threads at import time, not a task queue, so a
    synchronous request/response here matches existing conventions
    rather than introducing Celery for the first time anywhere in this
    project.
    """
    def post(self, request, symbol):
        symbol = symbol.upper().strip()
        try:
            snapshot, what_changed, primary_source = research_engine.run_research(symbol, triggered_by='refresh')
        except research_engine.ResearchUnavailableError as e:
            return Response({'detail': str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as e:
            logger.error(f"Unexpected error researching {symbol}: {e}")
            return Response({'detail': f'Research failed unexpectedly: {e}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        report_data = report_builder.build_report(snapshot, what_changed)
        ResearchReport.objects.update_or_create(snapshot=snapshot, defaults=report_data)

        from .services import freshness as fr
        snapshot_data = ResearchSnapshotDetailSerializer(snapshot).data
        snapshot_data['freshness'] = fr.assess_snapshot_freshness(snapshot)

        return Response({
            'symbol': symbol, 'primary_source': primary_source,
            'snapshot': snapshot_data,
        }, status=status.HTTP_201_CREATED)


class CompanyChatView(APIView):
    """
    POST /api/research/company/{symbol}/chat/
    Body: {"question": "...", "history": [{"role": "user"|"assistant", "content": "..."}]}

    Stateless on the backend -- history is round-tripped from the
    frontend with each request (a standard, valid chat-UI pattern),
    no new model/migration needed for this first version. Grounded
    strictly in the latest stored snapshot's data via the same
    build_fact_sheet() the narrative generator uses -- a chat answer
    can never reference a number the narrative itself didn't also
    have access to.
    """
    def post(self, request, symbol):
        question = (request.data.get('question') or '').strip()
        if not question:
            return Response({'detail': 'question is required.'}, status=status.HTTP_400_BAD_REQUEST)

        history = request.data.get('history') or []
        if not isinstance(history, list):
            return Response({'detail': 'history must be a list of {role, content} objects.'}, status=status.HTTP_400_BAD_REQUEST)

        snapshot = _latest_snapshot_or_none(symbol)
        if not snapshot:
            return Response({'detail': f'No research on file for {symbol.upper()} yet -- research it first, then ask questions.'}, status=status.HTTP_404_NOT_FOUND)

        fact_sheet = llm_narrative.build_fact_sheet(snapshot)
        answer = llm_narrative.answer_question(fact_sheet, question, conversation_history=history)
        return Response({'answer': answer, 'symbol': symbol.upper()})


class CompanyTechnicalView(APIView):
    """GET /api/research/company/{symbol}/technical/ -- real indicators
    (reused from screener's own engine) + deterministic trend
    classification. No AI, no fabrication -- see technical_analysis.py."""
    def get(self, request, symbol):
        from .services import technical_analysis as ta
        snapshot = ta.get_technical_snapshot(symbol)
        if snapshot is None:
            return Response({'detail': f'No technical data available for {symbol.upper()} -- insufficient price history or data unavailable.'}, status=status.HTTP_404_NOT_FOUND)
        trend = ta.classify_trend(snapshot)
        return Response({'symbol': symbol.upper(), 'technicals': snapshot, 'trend': trend})


class CompanyDecisionSupportView(APIView):
    """
    GET /api/research/company/{symbol}/decision-support/?language=english|roman_telugu
    Ties together technical_analysis + entry_setup + confluence +
    (optionally) the AI decision summary -- everything deterministic
    computes regardless of AI availability; only the final
    ai_decision_summary field depends on the LLM and degrades to a
    plain, honest structure (built from the same deterministic data,
    no AI needed) if the LLM call fails or isn't configured.
    """
    def get(self, request, symbol):
        from .services import technical_analysis as ta, entry_setup as es, confluence as cf, llm_narrative as ln

        research_snapshot = _latest_snapshot_or_none(symbol)
        if not research_snapshot:
            return Response({'detail': f'No research on file for {symbol.upper()} yet -- research it first.'}, status=status.HTTP_404_NOT_FOUND)

        technicals = ta.get_technical_snapshot(symbol)
        trend = ta.classify_trend(technicals) if technicals else {'classification': 'Insufficient data', 'reason': 'No technical data available.'}
        entry = es.build_entry_setup(technicals) if technicals else {'status': 'unavailable', 'message': 'No technical data available.'}
        confluence_result = cf.build_confluence(research_snapshot, technicals, trend)

        language = request.query_params.get('language', 'english')
        if language not in ('english', 'roman_telugu'):
            language = 'english'

        fact_sheet = ln.build_fact_sheet(research_snapshot)
        ai_summary, ai_reason = ln.generate_decision_summary(fact_sheet, confluence_result, entry, trend, language=language)
        if ai_summary is None:
            # Sep 26 2026: was a single generic message regardless of
            # WHY -- couldn't tell "no key configured" from "call
            # failed" apart, which the spec this was built against
            # explicitly flagged as a problem to fix. ai_reason now
            # comes straight from generate_decision_summary()'s own
            # documented reason codes.
            REASON_MESSAGES = {
                'no_api_key': 'AI decision summary unavailable -- ANTHROPIC_API_KEY is not set in the backend .env file.',
                'network_error': 'AI decision summary unavailable -- could not reach the AI service (network error).',
                'http_error': 'AI decision summary unavailable -- the AI service returned an error.',
                'parse_error': 'AI decision summary unavailable -- the AI service response was malformed.',
                'json_parse_error': 'AI decision summary unavailable -- the AI response was not valid JSON.',
                'missing_keys': 'AI decision summary unavailable -- the AI response was missing required fields.',
                'invalid_status': 'AI decision summary unavailable -- the AI used a non-standard status value.',
                'banned_term': 'AI decision summary unavailable -- the AI response contained disallowed recommendation language.',
            }
            # Honest, deterministic fallback -- built from the SAME data
            # the AI would have used, not a generic placeholder. Never
            # silently claims AI-generated content when the call failed.
            ai_summary = {
                'status': 'Insufficient data',
                'supporting_evidence': [], 'opposing_evidence': [],
                'conditions_to_monitor': [], 'invalidation_conditions': [],
                'note': REASON_MESSAGES.get(ai_reason, 'AI decision summary unavailable.') + ' The technical/confluence/entry-setup data above is unaffected and still real.',
                'error_reason': ai_reason,
            }

        return Response({
            'symbol': symbol.upper(),
            'technicals': technicals,
            'trend': trend,
            'entry_setup': entry,
            'confluence': confluence_result,
            'ai_decision_summary': ai_summary,
        })


class CompanyAveragingView(APIView):
    """
    POST /api/research/company/{symbol}/averaging/
    Body: {
        "existing_avg_price": float, "existing_qty": float, "current_price": float (optional, defaults to latest valuation),
        "scenarios": [{"label": str, "additional_qty": float} OR {"label": str, "additional_investment": float}, ...],
        "downside_price_levels": [float, ...] (optional)
    }
    Stateless -- nothing persisted, per spec ("the user's holding
    details are theirs"). Pure math via averaging_calculator.py, no AI
    call at all in this endpoint.
    """
    def post(self, request, symbol):
        from .services import averaging_calculator as ac
        data = request.data
        try:
            existing_avg_price = float(data.get('existing_avg_price'))
            existing_qty = float(data.get('existing_qty'))
        except (TypeError, ValueError):
            return Response({'detail': 'existing_avg_price and existing_qty are required numeric fields.'}, status=status.HTTP_400_BAD_REQUEST)

        current_price = data.get('current_price')
        if current_price is not None:
            try:
                current_price = float(current_price)
            except (TypeError, ValueError):
                return Response({'detail': 'current_price must be numeric if provided.'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            snapshot = _latest_snapshot_or_none(symbol)
            val = getattr(snapshot, 'valuation', None) if snapshot else None
            if val is None or val.price is None:
                return Response({'detail': 'current_price not provided and no researched valuation on file for this symbol -- provide it explicitly.'}, status=status.HTTP_400_BAD_REQUEST)
            current_price = float(val.price)

        try:
            current_position = ac.calculate_current_position(existing_avg_price, existing_qty, current_price)
        except ac.AveragingInputError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        scenarios_out = []
        for s in (data.get('scenarios') or []):
            try:
                result = ac.calculate_averaging_scenario(
                    existing_avg_price=existing_avg_price, existing_qty=existing_qty, current_price=current_price,
                    additional_qty=s.get('additional_qty'), additional_investment=s.get('additional_investment'),
                    label=s.get('label', 'Scenario'),
                )
            except ac.AveragingInputError as e:
                return Response({'detail': f"Scenario '{s.get('label', '?')}': {e}"}, status=status.HTTP_400_BAD_REQUEST)
            scenario_dict = ac.scenario_to_dict(result)
            downside_levels = data.get('downside_price_levels') or []
            if downside_levels:
                scenario_dict['downside_scenarios'] = ac.calculate_downside_scenarios(
                    result.new_total_qty, result.new_total_invested, [float(p) for p in downside_levels],
                )
            scenarios_out.append(scenario_dict)

        return Response({
            'symbol': symbol.upper(), 'current_position': current_position, 'scenarios': scenarios_out,
        })
