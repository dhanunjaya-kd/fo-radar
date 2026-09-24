"""
backend/fundamentals_research/services/source_registry.py

Every metric that flows through this app is wrapped in a SourcedValue
before it's stored -- this is the concrete mechanism behind the spec's
Section 20 requirement ("every important number must have source,
period, retrieved_at") and Section 7's rule ("never silently mix
values from different sources"). A raw float never travels through
this codebase unaccompanied by where it came from.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

IST = timezone.utc  # stored as UTC in the DB (Django convention); rendered in IST at the API/frontend layer


class Source:
    """Plain string constants, not an enum -- these values must exactly
    match models.SourceChoices' values, checked by
    test_source_registry.py's own consistency test rather than trusted
    to stay in sync by hand."""
    BHARATSTOCK = 'bharatstock'
    SCREENER = 'screener'
    FYERS = 'fyers'
    COMPANY_IR = 'company_ir'
    NEWS = 'news'
    CALCULATED = 'calculated'


@dataclass
class SourcedValue:
    """A value that knows where it came from. `value=None` is a real,
    valid state (genuinely unavailable) -- callers must check for it
    explicitly rather than let a None silently propagate as if it were
    zero or "unknown but probably fine"."""
    value: Any
    source: str
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(IST))
    period: Optional[str] = None  # e.g. "FY2025-26", "Q1 FY2026-27", or None for a point-in-time value

    @property
    def is_available(self) -> bool:
        return self.value is not None

    def as_dict(self) -> dict:
        return {
            'value': self.value,
            'source': self.source,
            'retrieved_at': self.retrieved_at.isoformat() if self.retrieved_at else None,
            'period': self.period,
        }


def unavailable(source: str, period: Optional[str] = None) -> SourcedValue:
    """Explicit constructor for 'we checked, this source genuinely
    doesn't have it' -- reads clearly at every call site, versus a
    bare SourcedValue(None, source) that looks like it might be an
    oversight."""
    return SourcedValue(value=None, source=source, period=period)
