from django.contrib import admin
from django.urls import path, include
from screener.views import (
    MarketDataView, SignalsView, TickerDataView,
    SniperOnlyView, StockDetailView, NewsView,
    MarketSummaryOldView, FoStockListOldView,
    FyersStatusView, OptionAnalyticsView, FyersBrowserTokenView,
    SignalExcelExportView, IndexTrackerView, IndexTrackerExportView
)

urlpatterns = [
    path('admin/', admin.site.urls),

    # OLD endpoints — frontend inka ivi call chestundi
    path('api/market-summary/', MarketSummaryOldView.as_view(), name='market_summary'),
    path('api/stocks/fo-list/', FoStockListOldView.as_view(), name='fo_stock_list'),
    path('api/market-data/', MarketDataView.as_view(), name='market_data'),
    path('api/signals/', SignalsView.as_view(), name='signals'),
    path('api/sniper-only/', SniperOnlyView.as_view(), name='sniper_only'),
    path('api/ticker/', TickerDataView.as_view(), name='ticker'),
    path('api/stock-detail/<str:symbol>/', StockDetailView.as_view(), name='stock_detail'),
    path('api/news/', NewsView.as_view(), name='news'),
    path('api/fyers-status/', FyersStatusView.as_view(), name='fyers_status'),
    path('api/fyers-browser-token/', FyersBrowserTokenView.as_view(), name='fyers_browser_token'),
    path('api/option-analytics/<str:symbol>/', OptionAnalyticsView.as_view(), name='option_analytics'),
    path('api/signals/export/', SignalExcelExportView.as_view(), name='signals_export'),
    path('api/index-tracker/<str:index_name>/', IndexTrackerView.as_view(), name='index_tracker'),
    path('api/index-tracker/<str:index_name>/export/', IndexTrackerExportView.as_view(), name='index_tracker_export'),

    # App-based endpoints (new structure)
    path('api/screener/', include('screener.urls')),
    path('api/options/', include('options.urls')),
    path('api/news/', include('news.urls')),
    path('api/trading/', include('trading.urls')),
    path('api/backtest/', include('backtest.urls')),
    path('api/fyers/', include('fyers_api.urls')),
]