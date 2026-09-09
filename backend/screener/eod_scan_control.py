from rest_framework.response import Response
from rest_framework.views import APIView


class EODScanCancelView(APIView):
    """Request the active Next Day EOD scan to stop at its next safe checkpoint."""

    def post(self, request):
        from . import views
        from .eod_scanner import request_scan_cancel

        if not views._eod_scan_in_progress:
            return Response({"cancelled": False, "reason": "No scan is currently running."})

        request_scan_cancel()
        return Response({
            "cancelled": True,
            "reason": "End Scan requested. The active scan will stop at the next safe checkpoint and keep the genuine results collected so far.",
        })
