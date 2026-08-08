from django.db import models
from screener.models import Stock

class NewsItem(models.Model):
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='news', null=True, blank=True)
    headline = models.TextField()
    source = models.CharField(max_length=100)
    url = models.URLField(blank=True)
    sentiment_score = models.DecimalField(max_digits=4, decimal_places=3, default=0)
    sentiment_label = models.CharField(max_length=20, default='Neutral')
    published_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-published_at']
