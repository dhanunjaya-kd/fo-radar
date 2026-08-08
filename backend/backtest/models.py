from django.db import models

class BacktestResult(models.Model):
    strategy_name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()
    total_signals = models.IntegerField(default=0)
    executed_signals = models.IntegerField(default=0)
    winning_trades = models.IntegerField(default=0)
    losing_trades = models.IntegerField(default=0)
    total_pnl = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    max_drawdown = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    win_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    avg_rr = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
