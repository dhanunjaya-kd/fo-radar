"""Single source of truth for NSE F&O monthly expiry dates.

NSE moved NIFTY, BANKNIFTY and individual-security derivatives to Tuesday
expiry effective from August 2025. If the last Tuesday is an NSE F&O trading
holiday, expiry is the previous trading day.

The holiday table below covers the currently published 2026 F&O calendar.
For later years, the weekday rule remains correct but callers should refresh
the holiday source when NSE publishes the new annual calendar.
"""
from datetime import datetime, timedelta

# NSE F&O trading holidays published for calendar 2026 (FAOP71777).
# Dates are ISO strings so comparisons stay timezone/date-only and deterministic.
NSE_FO_HOLIDAYS_2026 = {
    "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31",
    "2026-04-03", "2026-04-14", "2026-05-01", "2026-05-28",
    "2026-06-26", "2026-09-14", "2026-10-02", "2026-10-20",
    "2026-11-10", "2026-11-24", "2026-12-25",
}


def is_nse_fno_trading_day(day):
    """Return True when *day* is a weekday and not a published NSE F&O holiday."""
    if day.weekday() >= 5:
        return False
    if day.year == 2026 and day.strftime("%Y-%m-%d") in NSE_FO_HOLIDAYS_2026:
        return False
    return True


def last_nse_fno_expiry(year, month):
    """Return the last NSE F&O expiry trading day for the given month.

    Current NSE rule: last Tuesday of the expiry period; if that Tuesday is
    a trading holiday, move backward to the previous trading day.
    """
    if month == 12:
        first_next = datetime(year + 1, 1, 1)
    else:
        first_next = datetime(year, month + 1, 1)

    day = first_next - timedelta(days=1)
    while day.weekday() != 1:  # Tuesday
        day -= timedelta(days=1)

    while not is_nse_fno_trading_day(day):
        day -= timedelta(days=1)
    return day
