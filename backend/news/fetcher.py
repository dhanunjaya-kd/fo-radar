"""News fetcher with sentiment analysis."""
import requests
import feedparser
from textblob import TextBlob
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from .models import NewsItem
from screener.models import Stock

class NewsFetcher:
    def __init__(self):
        self.api_key = settings.NEWSAPI_KEY

    def fetch_newsapi(self, query="NSE India stock market"):
        """Fetch from NewsAPI."""
        if not self.api_key:
            return []
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 20,
            "apiKey": self.api_key,
        }
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("articles", [])
        return []

    def fetch_rss(self, url="https://www.moneycontrol.com/rss/business.xml"):
        """Fetch from RSS feed."""
        feed = feedparser.parse(url)
        return [{"title": e.title, "link": e.link, "published": e.published} for e in feed.entries[:20]]

    def analyze_sentiment(self, text):
        """Analyze sentiment using TextBlob."""
        blob = TextBlob(text)
        polarity = blob.sentiment.polarity
        if polarity > 0.2:
            label = "Bullish"
        elif polarity < -0.2:
            label = "Bearish"
        else:
            label = "Neutral"
        return round(polarity, 3), label

    def save_news(self, articles):
        """Save articles to DB with sentiment."""
        saved = 0
        for article in articles:
            headline = article.get("title", "")
            if NewsItem.objects.filter(headline=headline).exists():
                continue

            score, label = self.analyze_sentiment(headline)

            # Try to link to a stock
            stock = None
            for s in Stock.objects.filter(is_fno=True):
                if s.symbol.lower() in headline.lower():
                    stock = s
                    break

            NewsItem.objects.create(
                stock=stock,
                headline=headline,
                source=article.get("source", {}).get("name", "NewsAPI"),
                url=article.get("url", ""),
                sentiment_score=score,
                sentiment_label=label,
                published_at=timezone.now(),
            )
            saved += 1
        return saved
