"""CAS capture/readiness diagnostics.

This module does not call Fyers. It inspects the snapshots already written by
Index Tracker and reports whether the dataset is dense enough around the CAS
window for trustworthy research. It is intentionally conservative: missing
samples are reported, never interpolated or fabricated.
"""
from datetime import datetime, time

from .index_tracker import get_snapshots_for_date, list_available_dates

CAS_START = time(15, 15)
CAS_END = time(15, 35)
EARLY_START = time(15, 16)
EARLY_END = time(15, 18, 59)


def _dt(date_value, value):
    if not value:
        return None
    try:
        d = datetime.strptime(str(date_value), "%Y-%m-%d").date()
    except ValueError:
        return None
    text = str(value).strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.combine(d, datetime.strptime(text, fmt).time())
        except ValueError:
            pass
    return None


def _day_rows(index_name, date_value):
    date_str = str(date_value)
    try:
        rows = get_snapshots_for_date(index_name, date_str, limit=None)
    except TypeError:
        rows = get_snapshots_for_date(index_name, date_str)
    result = []
    for row in rows or []:
        stamp = _dt(date_str, row.get("Time"))
        if stamp:
            result.append((stamp, row))
    return sorted(result, key=lambda x: x[0])


def _coverage(stamps, start, end):
    window = [s for s in stamps if start <= s.time() <= end]
    if not window:
        return {"samples": 0, "first": None, "last": None, "span_seconds": 0}
    return {
        "samples": len(window),
        "first": window[0].strftime("%H:%M:%S"),
        "last": window[-1].strftime("%H:%M:%S"),
        "span_seconds": int((window[-1] - window[0]).total_seconds()),
    }


def build_cas_readiness(index_name):
    name = index_name.upper()
    if name not in ("NIFTY", "BANKNIFTY"):
        raise ValueError("index_name must be NIFTY or BANKNIFTY")

    days = []
    for raw_date in list_available_dates(name):
        date_str = str(raw_date)
        rows = _day_rows(name, date_str)
        if not rows:
            continue
        stamps = [stamp for stamp, _ in rows]
        cas = _coverage(stamps, CAS_START, CAS_END)
        early = _coverage(stamps, EARLY_START, EARLY_END)
        days.append({
            "date": date_str,
            "cas": cas,
            "early_warning": early,
            "early_warning_usable": early["samples"] >= 2,
        })

    usable = [d for d in days if d["early_warning_usable"]]
    total = len(days)
    usable_count = len(usable)
    return {
        "index": name,
        "status": "ready_for_research" if usable_count >= 30 else "collecting",
        "logged_days": total,
        "usable_early_warning_days": usable_count,
        "usable_day_rate_pct": round(100 * usable_count / total, 1) if total else None,
        "minimum_target_days": 30,
        "remaining_usable_days": max(0, 30 - usable_count),
        "definition": "At least two snapshots between 15:16:00 and 15:18:59 IST; no interpolation.",
        "days": days[:120],
    }
