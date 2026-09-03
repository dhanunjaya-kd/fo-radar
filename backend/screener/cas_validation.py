"""Non-overlapping CAS validation helpers.

Research only: these diagnostics are deliberately conservative. Minute
observations are useful for lead-time inspection, but independent validation
must not treat adjacent observations as independent bets.
"""
from datetime import datetime, timedelta


def _event_dt(event):
    try:
        return datetime.strptime(f"{event['date']} {event['event_time']}", "%Y-%m-%d %H:%M:%S")
    except (KeyError, TypeError, ValueError):
        return None


def select_non_overlapping_events(events, gap_minutes=5):
    """Keep observations at least ``gap_minutes`` apart per day."""
    valid = sorted((e for e in events if _event_dt(e) is not None), key=lambda e: (_event_dt(e), e.get("index", "")), reverse=True)
    selected = []
    last_by_day = {}
    gap = timedelta(minutes=gap_minutes)
    for event in valid:
        day = event["date"]
        dt = _event_dt(event)
        previous = last_by_day.get(day)
        if previous is not None and abs(previous - dt) < gap:
            continue
        selected.append(event)
        last_by_day[day] = dt
    return sorted(selected, key=lambda e: (_event_dt(e), e.get("index", "")), reverse=True)


def select_first_event_per_day(events):
    """Select the earliest valid event per day without using future data."""
    first = {}
    for event in events:
        dt = _event_dt(event)
        if dt is None:
            continue
        day = event.get("date")
        if day not in first or dt < _event_dt(first[day]):
            first[day] = event
    return sorted(first.values(), key=lambda e: (_event_dt(e), e.get("index", "")), reverse=True)


def aggregate_day_level(events, outcome_key="max_abs_move_5m_pct", threshold=0.25):
    """Use the earliest event per day and that event's own forward outcome."""
    rows = []
    for event in select_first_event_per_day(events):
        outcome = event.get(outcome_key)
        if outcome is None:
            continue
        value = float(outcome)
        rows.append({
            "index": event.get("index"),
            "date": event.get("date"),
            "event_time": event.get("event_time"),
            "expiry_weekday_candidate": bool(event.get("expiry_weekday_candidate")),
            "momentum_pct": event.get("momentum_pct"),
            "change_pct": event.get("change_pct"),
            outcome_key: value,
            "large_move": abs(value) >= threshold,
            "outcome_direction": "up" if value > 0 else "down" if value < 0 else "flat",
        })
    return rows


def lead_time_profile(events, threshold=0.25):
    """Report hit rates at 1/2/3/5m without claiming independence."""
    result = []
    for horizon in (1, 2, 3, 5):
        key = f"max_abs_move_{horizon}m_pct"
        valid = [e for e in events if e.get(key) is not None]
        hits = sum(abs(float(e[key])) >= threshold for e in valid)
        result.append({"horizon_minutes": horizon, "sample_size": len(valid), "large_move_count": hits, "large_move_rate_pct": round(100 * hits / len(valid), 1) if valid else None})
    return result


def validate_early_warning(events, feature_key="momentum_pct", threshold=0.05, outcome_threshold=0.25):
    """Compute conservative day-level classification metrics from one event/day."""
    days = aggregate_day_level(events, threshold=outcome_threshold)
    rows = [d for d in days if d.get(feature_key) is not None]
    predicted = [abs(float(d[feature_key])) >= threshold for d in rows]
    actual = [bool(d["large_move"]) for d in rows]
    tp = sum(p and a for p, a in zip(predicted, actual))
    fp = sum(p and not a for p, a in zip(predicted, actual))
    fn = sum((not p) and a for p, a in zip(predicted, actual))
    tn = sum((not p) and (not a) for p, a in zip(predicted, actual))
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    return {
        "sample_size_days": len(rows), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision_pct": round(100 * precision, 1) if precision is not None else None,
        "recall_pct": round(100 * recall, 1) if recall is not None else None,
        "outcome_threshold_pct": outcome_threshold,
        "selection_rule": "earliest_event_per_day",
        "status": "research_sample" if len(rows) >= 30 else "insufficient_sample",
    }
