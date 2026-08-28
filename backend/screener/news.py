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

Also sends new headlines to Telegram via send_new_news_alerts() below,
reusing the existing TelegramBot.send_message() (trading/telegram_bot.py)
-- same bot that already sends signal/trade/weekly-report alerts, no new
integration built. First call after a restart SEEDS the already-known
headlines without alerting on them, rather than dumping the whole
current list to Telegram as if it all just happened -- same class of
restart-burst bug already caught once in excel_logger.py.
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
        minutes = int(delta.total_seconds() // 60)
        if minutes < 1:
            item["time"] = "just now"
        elif minutes < 60:
            item["time"] = f"{minutes}m ago"
        else:
            hours = int(delta.total_seconds() // 3600)
            if hours < 24:
                item["time"] = f"{hours}h ago"
            else:
                item["time"] = f"{hours // 24}d ago"

    _cache["data"] = items
    _cache["fetched_at"] = now
    return items[:limit]


# Aug 28 2026: separate cache from get_fno_news()'s _cache above --
# genuinely independent data (unfiltered vs ticker-filtered), so a
# shared cache would return the wrong content for whichever function
# asked second.
_broad_cache = {"data": None, "fetched_at": 0}


# Aug 28 2026: HONEST STATUS -- whether ET's specific RSS feeds
# actually include image data is UNCONFIRMED. A direct fetch of the
# raw feed was blocked (site access restriction hit while checking),
# and general research on RSS/media conventions doesn't confirm
# anything ET-specific. This function is written DEFENSIVELY: it reads
# the two standard places feedparser normalizes image data into if a
# feed provides it (media:thumbnail -> entry.media_thumbnail,
# <enclosure> -> entry.enclosures) and returns None if neither is
# present -- so if the feeds DO carry images, they show up; if they
# don't, nothing breaks and every "image" field is just null. Confirm
# by checking the real deployed output once this is live, not by
# trusting this comment.
def _extract_image_url(entry):
    thumbnails = getattr(entry, "media_thumbnail", None)
    if thumbnails and isinstance(thumbnails, list) and thumbnails[0].get("url"):
        return thumbnails[0]["url"]
    enclosures = getattr(entry, "enclosures", None)
    if enclosures and isinstance(enclosures, list):
        for enc in enclosures:
            enc_type = (enc.get("type") or "").lower()
            enc_url = enc.get("href") or enc.get("url")
            if enc_url and (not enc_type or enc_type.startswith("image/")):
                return enc_url
    return None


def get_broad_market_news(limit=10):
    """
    Broader macro/global market news -- bond yields, Fed decisions,
    global market moves, etc -- that get_fno_news() above deliberately
    EXCLUDES by design (it only keeps headlines mentioning a specific
    F&O ticker by name). Real gap reported live: "not getting any news
    related to global tension/global positive, only F&O stocks" --
    confirmed by reading get_fno_news()'s own filter, which drops
    anything without a direct ticker match, including exactly this
    kind of broader coverage ET Markets genuinely publishes.

    Deliberately a FULLY SEPARATE function from get_fno_news(), not a
    shared-helper refactor of it -- that function is already live and
    feeding send_new_news_alerts()'s Telegram integration; duplicating
    ~20 lines of fetch/format logic here is a small, worthwhile cost
    for zero risk of changing its behavior. Do not merge these into one
    shared implementation without re-testing send_new_news_alerts()'s
    seeding behavior end to end.

    Returns [] if feedparser isn't installed or every feed fails, same
    as get_fno_news() -- never substitutes fake headlines.
    """
    if not FEEDPARSER_AVAILABLE:
        return []

    now = time.time()
    if _broad_cache["data"] is not None and (now - _broad_cache["fetched_at"]) < CACHE_TTL:
        return _broad_cache["data"][:limit]

    seen_links = set()
    items = []

    for source_name, url in RSS_FEEDS:
        try:
            parsed = feedparser.parse(url)
            for entry in parsed.entries:
                title = getattr(entry, "title", "") or ""
                link = getattr(entry, "link", "") or ""
                if not title or not link or link in seen_links:
                    continue
                seen_links.add(link)

                published_struct = getattr(entry, "published_parsed", None)
                published_dt = datetime(*published_struct[:6]) if published_struct else datetime.utcnow()

                items.append({
                    "title": title,
                    "source": source_name,
                    "link": link,
                    "_published": published_dt,
                    "sentiment": "Neutral",
                    "image": _extract_image_url(entry),
                })
        except Exception as e:
            print(f"[News] Failed to fetch {source_name}: {e}")
            continue

    items.sort(key=lambda x: x["_published"], reverse=True)

    now_utc = datetime.utcnow()
    for item in items:
        delta = now_utc - item.pop("_published")
        minutes = int(delta.total_seconds() // 60)
        if minutes < 1:
            item["time"] = "just now"
        elif minutes < 60:
            item["time"] = f"{minutes}m ago"
        else:
            hours = int(delta.total_seconds() // 3600)
            if hours < 24:
                item["time"] = f"{hours}h ago"
            else:
                item["time"] = f"{hours // 24}d ago"

    _broad_cache["data"] = items
    _broad_cache["fetched_at"] = now
    return items[:limit]


_sent_links = set()
_seeded = False


def send_new_news_alerts(fno_tickers):
    """
    Check for F&O news items not yet sent to Telegram, send each as a
    message via the existing bot, and remember them so they don't get
    resent next cycle.

    The FIRST call after a server restart is a SEED, not an alert batch
    -- every headline present at that point gets recorded as already-
    seen without sending anything. Otherwise every restart would dump
    the entire current news list to Telegram as if it all just
    happened, the same class of restart-burst bug excel_logger.py's
    _ensure_fresh() already had to fix once for signal logging. Only
    genuinely new headlines from the second call onward trigger a
    message.

    Returns how many were newly sent (always 0 on the seeding call).
    """
    global _seeded
    from trading.telegram_bot import TelegramBot

    items = get_fno_news(fno_tickers, limit=20)

    if not _seeded:
        _sent_links.update(item["link"] for item in items)
        _seeded = True
        return 0

    new_items = [i for i in items if i["link"] not in _sent_links]
    if not new_items:
        return 0

    bot = TelegramBot()
    sent_count = 0
    for item in reversed(new_items):  # oldest-first -- alerts arrive in the order things actually happened
        message = (
            f"\U0001F4F0 <b>F&O News</b>\n\n"
            f"{item['title']}\n\n"
            f"<i>{item['source']} \u00b7 {item['time']}</i>\n"
            f"{item['link']}"
        )
        result = bot.send_message(message)
        _sent_links.add(item["link"])
        if result:
            sent_count += 1
    return sent_count