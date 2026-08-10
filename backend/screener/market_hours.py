"""
Is NSE actually open right now? Nothing in this project's scanning
pipeline checked this before -- _background_worker (the thread that
drives the whole live pipeline: stock scanning, signal Excel logging,
Telegram alerts, and Index Tracker snapshots) ran unconditionally
every 90 seconds regardless of the clock, from the moment the Django
server started. Any time it's been running outside actual trading
hours -- before 9:15, after close, weekends -- it fetched whatever
Fyers returned (almost always stale/previous-close data with nothing
distinguishing it from a genuine live reading) and logged it into the
same Excel files and Telegram alerts as real intraday signals.

9:15 AM open is unambiguous and unaffected by anything recent.

3:30 PM close is used as a deliberately conservative cutoff. SEBI's
Closing Auction Session (effective Aug 3, 2026) extends the actual
settlement process for individual F&O stocks to roughly 3:30-3:35 PM,
but exactly how that affects the *computed index value* during that
auction window isn't something confirmed here -- so this stays at the
traditional close rather than guessing at auction-era index behavior.
Worth revisiting if data right at the close ever looks off in a way
that traces back to this boundary.
"""
from datetime import datetime


def is_market_hours(now=None):
    """True only Mon-Fri, 9:15 AM - 3:30 PM. Doesn't account for NSE
    holidays -- those still need to be manually avoided (or the app
    just left off) same as always; this only handles the daily/
    weekend boundary, which was the actual gap."""
    now = now or datetime.now()
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close
