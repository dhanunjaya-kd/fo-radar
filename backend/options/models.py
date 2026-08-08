from django.db import models
from screener.models import Stock

class OptionChain(models.Model):
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='option_chain')
    expiry = models.DateField()
    strike = models.IntegerField()
    ce_ltp = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    ce_oi = models.BigIntegerField(default=0)
    ce_oi_chg = models.BigIntegerField(default=0)
    ce_iv = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    pe_ltp = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    pe_oi = models.BigIntegerField(default=0)
    pe_oi_chg = models.BigIntegerField(default=0)
    pe_iv = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    pcr = models.DecimalField(max_digits=5, decimal_places=2, default=1.0)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [models.Index(fields=['stock', 'expiry', '-timestamp'])]
