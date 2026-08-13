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

UPDATED Aug 13, 2026: close moved from 3:30 PM to 3:40 PM. SEBI's
Closing Auction Session went live Aug 3, 2026 -- confirmed directly
against NSE's own CAS page and Fyers' own notice board (not a guess):
continuous cash-market trading for F&O-eligible stocks now stops at
3:15 PM, a 20-minute auction runs 3:15-3:35 PM to discover the
official close, and the EQUITY DERIVATIVES segment -- what this app
actually trades signals on -- now trades until 3:40 PM, ten minutes
later than before. The old 3:30 PM cutoff was quietly missing that
last real 10 minutes of legitimate derivatives trading every single
day since Aug 3rd.

Separately, during 3:15-3:35 PM specifically, the underlying cash
price for CAS stocks can appear to freeze (no continuous trades) then
jump all at once when the auction resolves -- a real, documented,
market-wide side effect of the new mechanism, not a data bug (multiple
market analysts and Fyers' own community have described this same
pattern since go-live). is_cas_auction_window() below flags this
window specifically, for anything computing Change % or "does price
confirm Bias" against spot price, so a jump caused by the auction
mechanism itself doesn't get read the same as a genuine intraday move.
"""
from datetime import datetime


def is_market_hours(now=None):
    """True only Mon-Fri, 9:15 AM - 3:40 PM (updated for CAS -- see
    module docstring). Doesn't account for NSE holidays -- those still
    need to be manually avoided (or the app just left off) same as
    always; this only handles the daily/weekend boundary and the
    post-CAS close time."""
    now = now or datetime.now()
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=40, second=0, microsecond=0)
    return market_open <= now <= market_close


def is_cas_auction_window(now=None):
    """True during the 3:15-3:35 PM Closing Auction Session window.
    Continuous cash-market trading is stopped for F&O stocks during
    this window -- the underlying spot/index price can appear frozen,
    then jump all at once when the auction resolves around 3:35 PM.
    The derivatives (options/futures) themselves keep trading normally
    through this window; it's specifically the underlying CASH price
    that behaves this way. Use this to flag/label a Change % or Bias-
    confirmation reading taken during this window, rather than treat
    an auction-driven jump the same as a normal intraday move."""
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    auction_start = now.replace(hour=15, minute=15, second=0, microsecond=0)
    auction_end = now.replace(hour=15, minute=35, second=0, microsecond=0)
    return auction_start <= now <= auction_end
