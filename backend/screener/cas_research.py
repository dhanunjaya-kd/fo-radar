"""CAS early-warning research dataset.

Builds an auditable event table from the project's existing Index Tracker
snapshots. It deliberately does not use future information as a feature:
features are taken from the snapshot at the event timestamp, while outcome
columns describe what happened afterwards.

This is a research/backtest layer only. It does not generate trading signals.
"""
from datetime import date, datetime, time, timedelta

from rest_framework.response import Response
from rest_framework.views import APIView

from .index_tracker import get_snapshots_for_date, list_available_dates

CAS_START = time(15, 15)
CAS_END = time(15, 35)
EARLY_WARNING_START = time(15, 16)
EARLY_WARNING_END = time(15, 18, 59)
OUTCOME_HORIZONS_MIN = (1, 2, 3, 5)


def _to_dt(date_value, time_value):
    """Normalize tracker date/time values without assuming string-only input."""
    if isinstance(time_value, datetime):
        return time_value
    if not time_value:
        return None
    if isinstance(date_value, date):
        date_obj = date_value
    else:
        try:
            date_obj = datetime.strptime(str(date_value), "%Y-%m-%d").date()
        except ValueError:
            return None
    text = str(time_value).strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.combine(date_obj, datetime.strptime(text, fmt).time())
        except ValueError:
            pass
    return None


def _date_str(value):
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _num(row, key):
    value = row.get(key)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _pct_move(start, end):
    if start in (None, 0) or end is None:
        return None
    return (end - start) / start * 100.0


def _max_abs_move_pct(base, future_rows):
    values = [_pct_move(base, _num(row, "Spot")) for row in future_rows]
    values = [value for value in values if value is not None]
    return max(values, key=abs) if values else None


def _direction(move_pct):
    if move_pct is None:
        return None
    return "up" if move_pct > 0 else "down" if move_pct < 0 else "flat"


def _expiry_candidate(index_name, date_obj):
    """Weekday candidate only; holidays are not guessed as expiries."""
    if index_name == "NIFTY":
        return date_obj.weekday() == 3
    if index_name == "BANKNIFTY":
        return date_obj.weekday() == 2
    return False


def _rows_for_day(index_name, date_value):
    date_str = _date_str(date_value)
    try:
        rows = get_snapshots_for_date(index_name, date_str, limit=None)
    except TypeError:
        # Compatibility with implementations whose helper only accepts
        # positional/default arguments. Never let the research layer invent data.
        rows = get_snapshots_for_date(index_name, date_str)
    dated = []
    for row in rows or []:
        dt = _to_dt(date_str, row.get("Time"))
        if dt is not None:
            dated.append((dt, row))
    return sorted(dated, key=lambda x: x[0])


def build_cas_event_dataset(index_name, start_time=EARLY_WARNING_START, end_time=EARLY_WARNING_END):
    """Return early-warning observations and forward outcomes for all logged days."""
    name = index_name.upper()
    if name not in ("NIFTY", "BANKNIFTY"):
        raise ValueError("index_name must be NIFTY or BANKNIFTY")

    events = []
    for raw_date in list_available_dates(name):
        date_str = _date_str(raw_date)
        day_rows = _rows_for_day(name, date_str)
        if not day_rows:
            continue
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()

        for event_dt, row in day_rows:
            if not (start_time <= event_dt.time() <= end_time):
                continue
            spot = _num(row, "Spot")
            if spot is None:
                continue

            future = [(dt, r) for dt, r in day_rows if event_dt < dt and dt.time() <= CAS_END]
            outcomes = {}
            for horizon in OUTCOME_HORIZONS_MIN:
                cutoff = event_dt + timedelta(minutes=horizon)
                window = [r for dt, r in future if dt <= cutoff]
                move = _max_abs_move_pct(spot, window)
                outcomes[f"max_abs_move_{horizon}m_pct"] = round(move, 5) if move is not None else None
                outcomes[f"max_abs_move_{horizon}m_direction"] = _direction(move)

            first_after = next((r for dt, r in future if dt <= event_dt + timedelta(minutes=5)), None)
            first_move = _pct_move(spot, _num(first_after, "Spot")) if first_after else None

            events.append({
                "index": name,
                "date": date_str,
                "event_time": event_dt.strftime("%H:%M:%S"),
                "minutes_from_cas_start": round((event_dt - datetime.combine(date_obj, CAS_START)).total_seconds() / 60, 3),
                "expiry_weekday_candidate": _expiry_candidate(name, date_obj),
                "spot": spot,
                "fut": _num(row, "Fut"),
                "change_pct": _num(row, "Change %"),
                "pcr": _num(row, "PCR"),
                "iv_pct": _num(row, "IV %"),
                "fut_oi_chg_pct": _num(row, "Fut OI Chg %"),
                "momentum_pct": _num(row, "Momentum %"),
                "bias": row.get("Bias"),
                "bias_v2": row.get("Bias V2"),
                "first_forward_move_5m_pct": round(first_move, 5) if first_move is not None else None,
                **outcomes,
            })

    return sorted(events, key=lambda r: (r["date"], r["event_time"]), reverse=True)


def _classification_metrics(
    events,
    feature_key,
    threshold,
    direction="absolute",
    outcome_key="max_abs_move_5m_pct",
    outcome_threshold=0.25,
):
    """Evaluate a simple, auditable threshold rule; no model fitting."""
    rows = [e for e in events if e.get(feature_key) is not None and e.get(outcome_key) is not None]
    if direction == "absolute":
        predicted = [abs(float(e[feature_key])) >= threshold for e in rows]
    elif direction == "positive":
        predicted = [float(e[feature_key]) >= threshold for e in rows]
    else:
        predicted = [float(e[feature_key]) <= -threshold for e in rows]
    actual = [abs(float(e[outcome_key])) >= outcome_threshold for e in rows]
    tp = sum(p and a for p, a in zip(predicted, actual))
    fp = sum(p and not a for p, a in zip(predicted, actual))
    fn = sum((not p) and a for p, a in zip(predicted, actual))
    tn = sum((not p) and (not a) for p, a in zip(predicted, actual))
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    accuracy = (tp + tn) / len(rows) if rows else None
    return {
        "feature": feature_key,
        "threshold": threshold,
        "outcome_threshold_pct": outcome_threshold,
        "direction": direction,
        "sample_size": len(rows),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision_pct": round(100 * precision, 1) if precision is not None else None,
        "recall_pct": round(100 * recall, 1) if recall is not None else None,
        "accuracy_pct": round(100 * accuracy, 1) if accuracy is not None else None,
        "status": "research_sample" if len(rows) >= 30 else "insufficient_sample",
    }


def summarize_cas_events(events, large_move_threshold_pct=0.25):
    """Summarize sample size and large-move hit rates without fitting a model."""
    valid = [e for e in events if e.get("max_abs_move_5m_pct") is not None]
    expiry = [e for e in valid if e.get("expiry_weekday_candidate")]
    non_expiry = [e for e in valid if not e.get("expiry_weekday_candidate")]

    def rate(rows):
        return round(100 * sum(abs(r["max_abs_move_5m_pct"]) >= large_move_threshold_pct for r in rows) / len(rows), 1) if rows else None

    # One observation per minute is useful for a first diagnostic, but
    # the full event table remains available for lead-time analysis.
    minute_groups = {}
    for event in valid:
        minute_groups.setdefault((event["date"], event["event_time"][:5]), event)
    minute_events = list(minute_groups.values())

    metrics = []
    for feature, threshold in (("momentum_pct", 0.05), ("change_pct", 0.25)):
        metrics.append(_classification_metrics(
            minute_events,
            feature,
            threshold,
            outcome_threshold=large_move_threshold_pct,
        ))

    return {
        "sample_size": len(valid),
        "minute_level_sample_size": len(minute_events),
        "large_move_threshold_pct": large_move_threshold_pct,
        "large_move_count": sum(abs(e["max_abs_move_5m_pct"]) >= large_move_threshold_pct for e in valid),
        "large_move_rate_pct": rate(valid),
        "expiry_candidate_sample": len(expiry),
        "expiry_candidate_large_move_rate_pct": rate(expiry),
        "non_expiry_sample": len(non_expiry),
        "non_expiry_large_move_rate_pct": rate(non_expiry),
        "simple_threshold_metrics": metrics,
        "status": "insufficient_sample" if len(valid) < 30 else "research_sample",
        "warning": "Expiry classification is weekday-based and must be checked against the official holiday-adjusted expiry calendar before model fitting.",
        "warning_2": "Events from the same day are correlated; minute-level metrics are diagnostic only and are not a substitute for an out-of-sample time-series test.",
    }


class CASResearchDatasetView(APIView):
    """Research endpoint; intentionally returns no trade recommendation."""
    def get(self, request, index_name):
        try:
            events = build_cas_event_dataset(index_name)
            threshold = float(request.query_params.get("threshold", 0.25))
            return Response({
                "index": index_name.upper(),
                "research_only": True,
                "summary": summarize_cas_events(events, threshold),
                "events": events[:500],
            })
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            print(f"[CASResearch] request failed: {exc}")
            return Response({"error": "CAS research data unavailable"}, status=503)
