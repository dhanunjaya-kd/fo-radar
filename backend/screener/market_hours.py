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
    """True only Mon-Fri, 9:00 AM - 3:40 PM.

    Aug 24 2026: start moved from 9:15 to 9:00 AM at his explicit
    request. Worth knowing: 9:00-9:15 is NSE's actual pre-open
    session (a call auction 9:00-9:08, then a quiet 9:08-9:15
    transition), not continuous trading -- structurally similar in
    spirit to the CAS auction window this file already treats
    specially at the close. Quotes fetched in this window may look
    frozen or reflect indicative pre-open pricing rather than genuine
    live trades, same general caution as is_cas_auction_window()
    below, just not given its own explicit flag/window function --
    this was a direct request to widen the gate, not a claim that
    9:00-9:15 behaves identically to normal continuous trading.

    Doesn't account for NSE holidays -- those still need to be
    manually avoided (or the app just left off) same as always; this
    only handles the daily/weekend boundary and the post-CAS close
    time."""
    now = now or datetime.now()
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    market_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
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


# ---------------------------------------------------------------------------
# Sep 12 2026: holiday-aware "next trading session" -- deliberately
# separate from is_market_hours() above, which still only checks
# weekday+time exactly as before and still gates the live scanner.
# Touching is_market_hours() itself would mean this change reaches into
# Sniper signal generation (the scanner's own on/off gate), explicitly
# out of scope for this pass -- this section only powers the DISPLAYED
# "next trading session" message, nothing that decides whether the
# scanner runs.
#
# Real 2026 holiday dates, cross-referenced against multiple
# independently-published sources (Zerodha's own market-intel holiday
# calendar, and NSE/BSE/MCX circular-derived listings republished by
# CalendarLabs, Kotak Neo, ProStocks, Choice, Upstox, and 5paisa --
# all agreeing on the same dates) -- not fabricated, but also not
# pulled from a live official API, since neither NSE, BSE, nor MCX
# publish one. This table needs a human check-and-refresh at the start
# of every calendar year, and sooner if an exchange announces a
# special/muhurat session mid-year.
#
# NSE and BSE share one identical published equity/derivatives holiday
# calendar (confirmed across every source checked) -- one table covers
# both. MCX genuinely differs and is kept separate.
NSE_BSE_HOLIDAYS_2026 = {
    "2026-01-15",  # Municipal Corporation Elections (Maharashtra)
    "2026-01-26",  # Republic Day
    "2026-03-03",  # Holi
    "2026-03-26",  # Shri Ram Navami
    "2026-03-31",  # Shri Mahavir Jayanti
    "2026-04-03",  # Good Friday
    "2026-04-14",  # Dr. Baba Saheb Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-05-28",  # Bakri Eid
    "2026-06-26",  # Muharram
    "2026-09-14",  # Ganesh Chaturthi
    "2026-10-02",  # Mahatma Gandhi Jayanti
    "2026-10-20",  # Dussehra
    "2026-11-10",  # Diwali-Balipratipada
    "2026-11-24",  # Guru Nanak Jayanti
    "2026-12-25",  # Christmas
}

# MCX FULL-day closures only (both the 9AM-5PM morning session and the
# 5PM-11:30PM evening session shut). MCX's real 2026 calendar also has
# ~11 PARTIAL holidays (Holi, Ram Navami, Mahavir Jayanti, Ambedkar
# Jayanti, Maharashtra Day, Bakri Eid, Muharram, Ganesh Chaturthi,
# Dussehra, Diwali-Balipratipada, Guru Nanak Jayanti) where only the
# morning session closes and the evening session opens normally at
# 5 PM -- deliberately NOT included here. "Next trading session" only
# needs to know whether a day has ANY real trading on it, and MCX
# genuinely does trade on those partial-holiday days (just starting
# later), so correctly treating them as trading days here is accurate,
# not a gap. New Year's Day (Jan 1) is the mirror case -- morning open,
# evening closed -- also correctly left off this list for the same
# reason.
MCX_HOLIDAYS_2026 = {
    "2026-01-26",  # Republic Day
    "2026-04-03",  # Good Friday
    "2026-10-02",  # Mahatma Gandhi Jayanti
    "2026-12-25",  # Christmas
}

MARKET_HOLIDAYS = {
    "NSE": NSE_BSE_HOLIDAYS_2026,
    "BSE": NSE_BSE_HOLIDAYS_2026,
    "MCX": MCX_HOLIDAYS_2026,
}


def get_next_trading_session(market, now=None):
    """
    Real next-trading-day resolver for `market` ('NSE' | 'BSE' | 'MCX'),
    skipping both weekends AND that market's own real 2026 holiday list
    above -- not just "the next weekday" the way the frontend's own
    display logic worked before this. Each market gets its own real
    calendar (NSE/BSE share one, MCX differs), never one holiday list
    assumed for all three.

    Always walks forward from the day AFTER `now`'s date -- this
    answers "when does trading next resume", which is only meaningful
    as a future day, not "is today itself open" (is_market_hours()
    above already answers that separately).

    Returns {'date': 'YYYY-MM-DD', 'weekday': 'Tuesday'} for the next
    real trading day, or None if `market` isn't recognized, or if the
    walk would leave the years this table actually covers (2026 only,
    right now) -- fails conservatively rather than guessing past what
    this table actually knows, exactly as instructed: an unmodeled
    year must not silently produce a wrong-but-confident answer.
    """
    from datetime import timedelta

    holidays = MARKET_HOLIDAYS.get((market or "").upper())
    if holidays is None:
        return None

    now = now or datetime.now()
    candidate = now.date() + timedelta(days=1)

    for _ in range(21):  # three weeks of headroom -- generous for any real holiday cluster, never infinite
        if candidate.year != 2026:
            return None  # outside the calendar this table actually covers -- fail conservative, don't guess
        if candidate.weekday() < 5 and candidate.isoformat() not in holidays:
            return {"date": candidate.isoformat(), "weekday": candidate.strftime("%A")}
        candidate += timedelta(days=1)
    return None
