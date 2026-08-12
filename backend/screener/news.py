"""
screener/news.py

Real F&O-relevant market news, replacing what used to be 5 hardcoded
headlines in NewsView that never changed regardless of what was actually
happening in the market -- same "looks done but isn't" pattern as the
old Math.random() PCR problem from earlier rounds.

SOURCE: The Economic Times' public RSS feeds (Markets, Stocks, Company).
RSS is built for syndication -- unlike scraping a webpage, there's no
anti-bot/ToS concern here, and it's free. Deliberately NOT NSE's own
corporate announcements (the more authoritative source for a material
event like a leadership change) -- pulling those means scraping NSE's
site directly, the same anti-bot/legal-gray-area tradeoff already
declined once for Fut OI. This is the clean, free, live alternative.

KNOWN LIMITATION, stated plainly rather than hidden: matching a headline
to your F&O list only works via a DIRECT ticker mention in the text
(e.g. "TCS shares fall 2%" matches, since TCS is the literal ticker).
Multi-word company names (RELIANCE -> "Reliance Industries", TATASTEEL
-> "Tata Steel") are NOT matched -- that needs a real ticker-to-company-
name mapping that doesn't exist in this codebase yet. This will miss
real, relevant news that doesn't happen to use the bare ticker. Word-
boundary matching is used to avoid the worst substring false positives
(so "BEL" doesn't match inside "LABEL"), but short 2-3 letter tickers
(LT, PFC, IEX, BSE...) can still rarely collide with ordinary word usage
in a large enough headline corpus -- a real, not-fully-eliminated risk.
"""
import re
import time
from datetime import datetime

try:
    import feedparser
    FEEDPARSER_AVAILABLE = True
except ImportError:
    FEEDPARSER_AVAILABLE = False

RSS_FEEDS = [
    ("ET Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("ET Stocks", "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"),
    ("ET Company", "https://economictimes.indiatimes.com/news/company/rssfeeds/2143429.cms"),
]

_cache = {"data": None, "fetched_at": 0}
CACHE_TTL = 300  # 5 min -- RSS doesn't update fast enough to justify polling harder, and this avoids hammering ET's servers on every page load


def _ticker_pattern(tickers):
    """One compiled regex matching any ticker as a whole word (case-
    insensitive), not a bare substring."""
    escaped = [re.escape(t) for t in tickers]
    return re.compile(r'\b(' + '|'.join(escaped) + r')\b', re.IGNORECASE)


def get_fno_news(fno_tickers, limit=20):
    """
    Fetch, merge, and filter ET's RSS feeds down to headlines that
    mention an F&O ticker directly. Returns a list of
    {title, source, link, time, sentiment} dicts, newest first.
    'sentiment' is always 'Neutral' -- there's no real sentiment
    analysis here, deliberately not faked as Positive/Negative the way
    the old hardcoded version did.

    Returns [] if feedparser isn't installed or every feed fails --
    callers should treat that as "no real news available right now",
    not substitute anything fake in its place.
    """
    if not FEEDPARSER_AVAILABLE:
        return []

    now = time.time()
    if _cache["data"] is not None and (now - _cache["fetched_at"]) < CACHE_TTL:
        return _cache["data"][:limit]

    pattern = _ticker_pattern(fno_tickers)
    seen_links = set()
    items = []

    for source_name, url in RSS_FEEDS:
        try:
            parsed = feedparser.parse(url)
            for entry in parsed.entries:
                title = getattr(entry, "title", "") or ""
                summary = getattr(entry, "summary", "") or ""
                link = getattr(entry, "link", "") or ""
                if not title or not link or link in seen_links:
                    continue
                if not pattern.search(title) and not pattern.search(summary):
                    continue
                seen_links.add(link)

                # feedparser normalizes published_parsed to UTC -- keep
                # everything in UTC below (datetime.utcnow(), not
                # datetime.now()) so the "Xh ago" math doesn't drift by
                # whatever the server's local timezone offset is.
                published_struct = getattr(entry, "published_parsed", None)
                published_dt = datetime(*published_struct[:6]) if published_struct else datetime.utcnow()

                items.append({
                    "title": title,
                    "source": source_name,
                    "link": link,
                    "_published": published_dt,
                    "sentiment": "Neutral",
                })
        except Exception as e:
            print(f"[News] Failed to fetch {source_name}: {e}")
            continue  # one feed failing shouldn't take down the others

    items.sort(key=lambda x: x["_published"], reverse=True)

    now_utc = datetime.utcnow()
    for item in items:
        delta = now_utc - item.pop("_published")
        hours = int(delta.total_seconds() // 3600)
        if hours < 1:
            item["time"] = "just now"
        elif hours < 24:
            item["time"] = f"{hours}h ago"
        else:
            item["time"] = f"{hours // 24}d ago"

    _cache["data"] = items
    _cache["fetched_at"] = now
    return items[:limit]
