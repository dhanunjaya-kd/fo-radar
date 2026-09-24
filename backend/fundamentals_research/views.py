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
from .services import research_engine, report_builder

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
        return Response(ResearchSnapshotDetailSerializer(snapshot).data)


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

        return Response({
            'symbol': symbol, 'primary_source': primary_source,
            'snapshot': ResearchSnapshotDetailSerializer(snapshot).data,
        }, status=status.HTTP_201_CREATED)
