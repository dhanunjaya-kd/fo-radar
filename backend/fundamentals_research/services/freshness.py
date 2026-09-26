"""
backend/fundamentals_research/services/freshness.py

Sep 26 2026. Every stored metric already carries its own retrieved_at
timestamp (built into every model from the start via SourcedValue) --
this module turns that into an honest freshness STATUS, with
different rules per category, per spec: "Do not treat historical
quarterly financial statements as stale merely because they are not
updated daily." A financial statement and a live price have
completely different natural refresh cadences; using one threshold
for both would either falsely flag quarterly financials as stale
constantly, or falsely call a day-old price fresh.

Sep 26 2026 correctness fix, found by this file's own tests: this
project's settings.py sets TIME_ZONE = 'Asia/Kolkata', which makes
plain datetime.now() (no args) return IST wall-clock time in this
process, not UTC -- confirmed directly (a ~5.5 hour gap between
datetime.now() and datetime.now(timezone.utc) in the same process).
A naive retrieved_at value therefore must NOT be assumed to be UTC
(this file originally did exactly that, and its own test caught the
resulting ~3.5-hour "future timestamp" misfire). Uses Django's own
django.utils.timezone utilities below instead of raw datetime/UTC
assumptions -- they already know and correctly respect this project's
real TIME_ZONE and USE_TZ settings, which a hand-rolled UTC assumption
cannot.
"""
from typing import Optional
from enum import Enum

from django.utils import timezone as dj_timezone


class Freshness(str, Enum):
    FRESH = 'fresh'
    STALE = 'stale'
    UNAVAILABLE = 'unavailable'
    PERIOD_NOT_VERIFIED = 'reporting_period_not_verified'


# Sep 26 2026: thresholds per category, each with a stated reason --
# not arbitrary numbers. Financial statements (annual/quarterly) don't
# change intra-quarter, so a multi-day window is honest, not lax.
# Prices/technicals move every trading session, so same-session is the
# only honest "fresh." Ownership (promoter/FII/DII) is a quarterly
# regulatory filing in India, so a ~100-day window matches its own
# real-world update cadence, not this app's preference.
_FRESHNESS_WINDOWS_HOURS = {
    'financial_statement': 24 * 14,   # 14 days -- a fetch is "fresh" for two weeks; the underlying period itself doesn't change that often either way
    'market_price': 24,               # 1 day -- prices are effectively stale by the next session
    'technical_indicator': 24,        # 1 day -- same reasoning as price; both come from the same daily-candle fetch
    'ownership': 24 * 100,            # ~100 days -- matches India's quarterly shareholding-pattern filing cadence
    'news': 24 * 7,                   # 7 days -- news relevance genuinely fades, but a week-old item is still "recent" not stale
    'valuation': 24,                  # 1 day -- price-driven ratios (P/E, P/B) move with the price
}


def assess_freshness(retrieved_at, category: str) -> dict:
    """
    Returns {'status': Freshness, 'age_hours': float|None, 'label': str}.

    A None retrieved_at is UNAVAILABLE, never silently treated as
    fresh or stale -- there's genuinely nothing to assess.
    An unrecognized category is PERIOD_NOT_VERIFIED rather than
    guessing a window for it, since guessing a threshold for an
    uncategorized metric would itself be a kind of fabrication.
    """
    if retrieved_at is None:
        return {'status': Freshness.UNAVAILABLE, 'age_hours': None, 'label': 'Unavailable'}

    window_hours = _FRESHNESS_WINDOWS_HOURS.get(category)
    if window_hours is None:
        return {'status': Freshness.PERIOD_NOT_VERIFIED, 'age_hours': None, 'label': 'Reporting period not verified'}

    # dj_timezone.make_aware() correctly applies THIS PROJECT's real
    # configured TIME_ZONE to a naive value, and dj_timezone.now()
    # returns an aware "now" consistent with that same setting --
    # both correct by construction, unlike a hardcoded UTC assumption.
    if dj_timezone.is_naive(retrieved_at):
        retrieved_at = dj_timezone.make_aware(retrieved_at)
    now = dj_timezone.now()
    age_hours = (now - retrieved_at).total_seconds() / 3600.0

    if age_hours < 0:
        # A timestamp from the future is a real data problem, not
        # something to silently clamp to "fresh" -- surfaced honestly.
        return {'status': Freshness.PERIOD_NOT_VERIFIED, 'age_hours': age_hours, 'label': 'Reporting period not verified'}

    status = Freshness.FRESH if age_hours <= window_hours else Freshness.STALE
    label = _humanize_age(age_hours) if status == Freshness.STALE else 'Fresh'
    return {'status': status, 'age_hours': round(age_hours, 1), 'label': label}


def _humanize_age(age_hours: float) -> str:
    if age_hours < 48:
        return f"Stale ({round(age_hours)}h old)"
    days = round(age_hours / 24)
    return f"Stale ({days}d old)"


def assess_snapshot_freshness(snapshot) -> dict:
    """
    Convenience wrapper: assesses every major section of one
    ResearchSnapshot at once, using each section's own retrieved_at
    and the category rules above. Returns a dict keyed by section
    name -- built for the API/serializer layer to attach directly to
    a response, not for display formatting (that's the frontend's job).
    """
    latest_financial = snapshot.financials.order_by('-fiscal_year').first()
    bs = snapshot.balance_sheets.order_by('-fiscal_year').first()
    cf = snapshot.cash_flows.order_by('-fiscal_year').first()
    val = getattr(snapshot, 'valuation', None)
    own = getattr(snapshot, 'ownership', None)

    return {
        'financials': assess_freshness(getattr(latest_financial, 'retrieved_at', None), 'financial_statement'),
        'balance_sheet': assess_freshness(getattr(bs, 'retrieved_at', None), 'financial_statement'),
        'cash_flow': assess_freshness(getattr(cf, 'retrieved_at', None), 'financial_statement'),
        'valuation': assess_freshness(getattr(val, 'retrieved_at', None), 'valuation'),
        'ownership': assess_freshness(getattr(own, 'retrieved_at', None), 'ownership'),
    }
