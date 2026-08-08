from django.contrib import admin
from .models import Stock, StockSnapshot, Signal, MarketOverview

@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'name', 'sector', 'is_fno', 'lot_size']
    search_fields = ['symbol', 'name']
    list_filter = ['sector', 'is_fno']

@admin.register(StockSnapshot)
class StockSnapshotAdmin(admin.ModelAdmin):
    list_display = ['stock', 'ltp', 'change_pct', 'rsi', 'adx', 'timestamp']
    list_filter = ['timestamp']

@admin.register(Signal)
class SignalAdmin(admin.ModelAdmin):
    list_display = ['stock', 'score', 'grade', 'signal_type', 'option_type', 'confidence', 'is_active', 'created_at']
    list_filter = ['signal_type', 'grade', 'is_active', 'created_at']
    search_fields = ['stock__symbol']

@admin.register(MarketOverview)
class MarketOverviewAdmin(admin.ModelAdmin):
    list_display = ['nifty_spot', 'nifty_change', 'total_signals', 'timestamp']
