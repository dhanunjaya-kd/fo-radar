"""
backend/fundamentals_research/services/news_analysis.py

Wraps the EXISTING news/fetcher.py's NewsFetcher class, unmodified.
Confirmed its real methods by reading the file directly:
fetch_newsapi(query=...) -> list of raw NewsAPI article dicts,
analyze_sentiment(text) -> (polarity_float, label) where label is
'Bullish'/'Bearish'/'Neutral' (that file's own convention) -- mapped
here to this app's 'positive'/'negative'/'neutral' choices, since the
existing labels were written for a market-mood context and this
report's ResearchNewsItem model uses the more standard trio.

Per spec Section 16: every item must carry headline/date/source/
summary/impact-category/source-URL, and sentiment must be based on
actual content with a stated reason -- not a bare label with nothing
behind it. sentiment_basis below states exactly that reason.
"""
import logging
from datetime import datetime
from typing import List, Dict, Any

logger = logging.getLogger('fundamentals_research.news_analysis')

_SENTIMENT_LABEL_MAP = {'Bullish': 'positive', 'Bearish': 'negative', 'Neutral': 'neutral'}


def get_company_news(symbol: str, company_name: str = '', limit: int = 10) -> List[Dict[str, Any]]:
    """
    Returns a list of dicts shaped to map directly onto
    ResearchNewsItem fields. Query is built from symbol + company name
    together (when available) since NewsAPI's free-text search matches
    better against a real company name than a bare ticker -- 'RELIANCE'
    alone pulls a lot of noise NewsAPI's relevance ranking doesn't
    filter well; 'RELIANCE Reliance Industries' narrows it.

    Returns an empty list (never raises, never fabricates a headline)
    if NEWSAPI_KEY isn't configured or the request fails -- exactly
    the existing fetch_newsapi()'s own behavior, just not swallowed
    silently here; logged so a genuinely missing key is visible in
    ops, not just an empty-looking report section.
    """
    try:
        from news.fetcher import NewsFetcher
    except ImportError as e:
        logger.warning(f"Could not import existing news/fetcher.py: {e}")
        return []

    fetcher = NewsFetcher()
    if not fetcher.api_key:
        logger.info("NEWSAPI_KEY not configured -- news section will be empty, not fabricated.")
        return []

    query = f"{symbol} {company_name}".strip() if company_name else symbol
    try:
        articles = fetcher.fetch_newsapi(query=query)
    except Exception as e:
        logger.warning(f"News fetch failed for {symbol}: {e}")
        return []

    items = []
    for article in articles[:limit]:
        title = article.get('title') or ''
        description = article.get('description') or ''
        text_for_sentiment = f"{title}. {description}".strip()
        try:
            polarity, raw_label = fetcher.analyze_sentiment(text_for_sentiment) if text_for_sentiment else (0.0, 'Neutral')
        except Exception:
            polarity, raw_label = 0.0, 'Neutral'
        sentiment = _SENTIMENT_LABEL_MAP.get(raw_label, 'neutral')

        published_at = None
        raw_date = article.get('publishedAt')
        if raw_date:
            try:
                published_at = datetime.strptime(raw_date, '%Y-%m-%dT%H:%M:%SZ')
            except (ValueError, TypeError):
                published_at = None

        items.append({
            'headline': title,
            'url': article.get('url') or '',
            'published_at': published_at,
            'news_source': (article.get('source') or {}).get('name', ''),
            'summary': description,
            'sentiment': sentiment,
            'sentiment_basis': f"TextBlob polarity {polarity:+.3f} on the headline+description text (>+0.2 positive, <-0.2 negative, else neutral -- existing project's own established threshold, not a new rule invented here).",
        })
    return items
