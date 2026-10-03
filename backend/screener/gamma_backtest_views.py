"""
screener/gamma_backtest_views.py

Oct 3 2026: download endpoints for the Gamma Blast strategy's own backtest PDF (see backtest_gamma.py). Kept in
their own small module so the (very large) views.py does not have to change; wired up in fno_sniper/urls.py.
Same response conventions as the existing DailyBacktest* views next to which these routes sit.
"""
import math
import os

from rest_framework.response import Response
from rest_framework.views import APIView


def _json_safe(v):
    """NaN / +-inf are not valid JSON (DRF refuses them); the metrics can contain them on tiny samples. -> None."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    return v


class GammaBacktestRunView(APIView):
    """
    GET /api/daily-backtest/gamma/run/ -- build the Gamma report NOW and return it. Runs only the Gamma step (local xlsx
    files -> one PDF, a few seconds, no Fyers), so it works even if the full daily cycle is slow or failing. Always answers
    200 with a `message` saying what was found; `pdf_ready` says whether /gamma/download/ will now return a file.
    """

    def get(self, request):
        from .daily_backtest import run_gamma_now
        try:
            g = run_gamma_now()
        except Exception as e:  # never a bare 500 for the user -- say what broke
            return Response({"pdf_ready": False, "message": f"Gamma report failed: {e}", "summary": None, "equity_curve": None,
                             "recent_trades": None, "pdf_error": str(e)})
        return Response(_json_safe({
            "pdf_ready": bool(g.get("pdf") and os.path.exists(g["pdf"])), "message": g.get("message"),
            "summary": g.get("summary"), "equity_curve": g.get("equity_curve"), "recent_trades": g.get("recent_trades"),
            "pdf_error": g.get("pdf_error"),
        }))


class GammaBacktestDownloadView(APIView):
    """GET /api/daily-backtest/gamma/download/ -- the Gamma PDF from the latest daily-backtest cycle."""

    def get(self, request):
        from django.http import FileResponse, JsonResponse
        from .daily_backtest import get_last_run
        path = get_last_run().get("gamma_pdf")
        if not path or not os.path.exists(path):
            return JsonResponse(
                {"error": "No Gamma report available yet -- run the daily backtest first. It needs at least one FINISHED Gamma trade "
                          "(hit a target or the stop); trades still open are not counted."}, status=404)
        return FileResponse(open(path, "rb"), as_attachment=True, filename=os.path.basename(path))


class GammaBacktestRangeReportView(APIView):
    """GET /api/daily-backtest/gamma/range-report/?start=YYYY-MM-DD&end=YYYY-MM-DD -- Gamma PDF for one window (by exit date)."""

    def get(self, request):
        from django.http import FileResponse, JsonResponse
        from .backtest_gamma import run_gamma_range_report
        start, end = request.GET.get("start"), request.GET.get("end")
        if not start or not end:
            return Response({"error": "start and end query params (YYYY-MM-DD) are required"}, status=400)
        try:
            path = run_gamma_range_report(start, end)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        if not path or not os.path.exists(path):
            return JsonResponse({"error": f"No finished Gamma trades between {start} and {end}."}, status=404)
        return FileResponse(open(path, "rb"), as_attachment=True, filename=os.path.basename(path))
