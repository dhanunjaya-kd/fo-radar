"""CAS dataset readiness diagnostics.

This endpoint reports whether the existing Index Tracker has enough actual
3:16-3:18 observations and forward rows for research. It never fabricates
missing data and never produces a trading signal.
"""
from datetime import datetime, time

from rest_framework.response import Response
from rest_framework.views import APIView

from .index_tracker import get_snapshots_for_date, list_available_dates

START = time(15, 16)
END = time(15, 18, 59)


def _rows(index_name, date_str):
    try:
        return get_snapshots_for_date(index_name, date_str, limit=None) or []
    except TypeError:
        return get_snapshots_for_date(index_name, date_str) or []


def _time(value):
    if isinstance(value, datetime):
        return value.time()
    text = str(value or "").strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            pass
    return None


def get_readiness(index_name):
    name = index_name.upper()
    if name not in ("NIFTY", "BANKNIFTY"):
        raise ValueError("index_name must be NIFTY or BANKNIFTY")

    dates = list_available_dates(name)
    day_reports = []
    event_count = 0
    forward_ready = 0
    for raw_date in dates:
        date_str = raw_date.strftime("%Y-%m-%d") if hasattr(raw_date, "strftime") else str(raw_date)
        rows = sorted((_row for _row in _rows(name, date_str)), key=lambda r: str(r.get("Time", "")))
        times = [_time(r.get("Time")) for r in rows]
        early = [t for t in times if t and START <= t <= END]
        if not early:
            continue
        event_count += len(early)
        last_time = max(t for t in times if t)
        has_forward = last_time >= time(15, 20)
        if has_forward:
            forward_ready += 1
        day_reports.append({
            "date": date_str,
            "early_warning_rows": len(early),
            "first_early_warning": min(early).strftime("%H:%M:%S"),
            "last_early_warning": max(early).strftime("%H:%M:%S"),
            "has_5m_forward_coverage": has_forward,
            "total_rows": len(rows),
        })

    return {
        "index": name,
        "research_only": True,
        "logged_dates": len(dates),
        "days_with_early_warning_data": len(day_reports),
        "days_with_5m_forward_coverage": forward_ready,
        "early_warning_rows": event_count,
        "minimum_target_days": 30,
        "ready_for_model_fitting": len(day_reports) >= 30 and forward_ready >= 30,
        "status": "ready_for_research_validation" if len(day_reports) >= 30 and forward_ready >= 30 else "collect_more_data",
        "days": day_reports[:60],
    }


class CASDataReadinessView(APIView):
    def get(self, request, index_name):
        try:
            return Response(get_readiness(index_name))
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            print(f"[CASReadiness] request failed: {exc}")
            return Response({"error": "CAS readiness data unavailable"}, status=503)
