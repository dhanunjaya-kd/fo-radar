from django.db import models

class Stock(models.Model):
    symbol = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200, blank=True)
    sector = models.CharField(max_length=100, blank=True)
    is_fno = models.BooleanField(default=True)
    lot_size = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.symbol

class StockSnapshot(models.Model):
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='snapshots')
    ltp = models.DecimalField(max_digits=12, decimal_places=2)
    change_pct = models.DecimalField(max_digits=6, decimal_places=2)
    volume = models.BigIntegerField(default=0)
    avg_volume = models.BigIntegerField(default=0)
    rsi = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    adx = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    macd = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    ema_20 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    ema_50 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    vwap = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['stock', '-timestamp']),
        ]

class Signal(models.Model):
    SIGNAL_CHOICES = [
        ('BUY_NOW', 'Buy Now'),
        ('BUY', 'Buy'),
        ('WATCHLIST', 'Watchlist'),
        ('SELL', 'Sell'),
        ('AVOID', 'Avoid'),
        ('NEUTRAL', 'Neutral'),
    ]
    GRADE_CHOICES = [
        ('A+', 'A+'), ('A', 'A'), ('B+', 'B+'), ('B', 'B'),
        ('C+', 'C+'), ('C', 'C'), ('D', 'D'),
    ]

    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='signals')
    score = models.IntegerField(default=0)
    grade = models.CharField(max_length=2, choices=GRADE_CHOICES, default='C')
    signal_type = models.CharField(max_length=20, choices=SIGNAL_CHOICES, default='NEUTRAL')
    option_type = models.CharField(max_length=2, choices=[('CE', 'CE'), ('PE', 'PE')], default='CE')
    strike = models.IntegerField(default=0)
    entry = models.DecimalField(max_digits=12, decimal_places=2)
    stop_loss = models.DecimalField(max_digits=12, decimal_places=2)
    target_1 = models.DecimalField(max_digits=12, decimal_places=2)
    target_2 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    target_3 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    risk_reward = models.CharField(max_length=20, blank=True)
    confidence = models.IntegerField(default=0)
    pcr = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    max_pain = models.IntegerField(null=True, blank=True)
    iv = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    oi_buildup = models.CharField(max_length=100, blank=True)
    trend = models.CharField(max_length=20, default='NEUTRAL')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    # Prediction fields
    prediction_1d = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text='Predicted move % next day')
    prediction_3d = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text='Predicted move % next 3 days')
    prediction_confidence = models.IntegerField(default=0, help_text='Prediction model confidence')

    class Meta:
        ordering = ['-score', '-created_at']
        indexes = [
            models.Index(fields=['-score', '-created_at']),
            models.Index(fields=['signal_type', '-created_at']),
        ]

    def __str__(self):
        return f"{self.stock.symbol} | {self.signal_type} | Score:{self.score}"

class MarketOverview(models.Model):
    nifty_spot = models.DecimalField(max_digits=10, decimal_places=2)
    nifty_change = models.DecimalField(max_digits=6, decimal_places=2)
    banknifty_spot = models.DecimalField(max_digits=10, decimal_places=2)
    banknifty_change = models.DecimalField(max_digits=6, decimal_places=2)
    total_pcr = models.DecimalField(max_digits=5, decimal_places=2)
    total_signals = models.IntegerField(default=0)
    buy_signals = models.IntegerField(default=0)
    sell_signals = models.IntegerField(default=0)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
