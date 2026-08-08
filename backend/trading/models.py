from django.db import models
from screener.models import Stock

class PaperTrade(models.Model):
    SIDE_CHOICES = [('BUY', 'Buy'), ('SELL', 'Sell')]
    TYPE_CHOICES = [('CE', 'CE'), ('PE', 'PE')]
    STATUS_CHOICES = [('OPEN', 'Open'), ('CLOSED', 'Closed'), ('SL_HIT', 'SL Hit'), ('TARGET_HIT', 'Target Hit')]

    stock = models.ForeignKey(Stock, on_delete=models.CASCADE)
    option_type = models.CharField(max_length=2, choices=TYPE_CHOICES)
    side = models.CharField(max_length=4, choices=SIDE_CHOICES, default='BUY')
    strike = models.IntegerField()
    entry_price = models.DecimalField(max_digits=10, decimal_places=2)
    qty = models.IntegerField(default=1)
    stop_loss = models.DecimalField(max_digits=10, decimal_places=2)
    target_1 = models.DecimalField(max_digits=10, decimal_places=2)
    target_2 = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    target_3 = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    exit_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    pnl = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pnl_pct = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN')
    exit_reason = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

class PnLSummary(models.Model):
    date = models.DateField(unique=True)
    total_trades = models.IntegerField(default=0)
    winning_trades = models.IntegerField(default=0)
    losing_trades = models.IntegerField(default=0)
    total_pnl = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    win_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    avg_profit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    avg_loss = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    max_drawdown = models.DecimalField(max_digits=10, decimal_places=2, default=0)
