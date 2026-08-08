from django.urls import path
from .views import (
    MarketDataView, SignalsView, TickerDataView,
    SniperOnlyView, StockDetailView, NewsView,
    MarketSummaryOldView, FoStockListOldView,
    FyersStatusView
)

urlpatterns = [
    path('signals/', SignalsView.as_view(), name='signals'),
    path('market/', MarketDataView.as_view(), name='market_data'),
    path('ticker/', TickerDataView.as_view(), name='ticker_data'),
    path('news/', NewsView.as_view(), name='news'),
    path('status/', SniperOnlyView.as_view(), name='sniper_only'),
    path('market-summary/', MarketSummaryOldView.as_view(), name='market_summary_old'),
    path('fo-list/', FoStockListOldView.as_view(), name='fo_list_old'),
    path('stock/<str:symbol>/', StockDetailView.as_view(), name='stock_detail'),
    path('fyers-status/', FyersStatusView.as_view(), name='fyers_status'),
]