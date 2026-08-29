from django.contrib import admin
from django.urls import path, include
from screener.views import (
    MarketDataView, SignalsView, TickerDataView,
    SniperOnlyView, StockDetailView, NewsView,
    MarketSummaryOldView, FoStockListOldView,
    FyersStatusView, OptionAnalyticsView, FyersBrowserTokenView,
    SignalExcelExportView, IndexTrackerView, IndexTrackerExportView,
    SignalExportDatesView, SignalExcelExportByDateView,
    IndexBacktestView, IndexBacktestExportView, WeeklyReportView,
    FundamentalsWatchlistView, CASAuctionMovesView, IndexTrackerAvailableDatesView,
    SignalWatchlistCsvView, IndexSignalView, CommodityCurrentSymbolView,
    DailyBacktestStatusView, DailyBacktestRunView, DailyBacktestReportDownloadView,
    DailyBacktestRangeView, FiftyTwoWeekRangeView, BroaderIndicesView,
    StrategyBacktestRunView, StrategyBacktestStatusView,
    DailyBacktestRangeReportView,
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
    path('api/signals/export/dates/', SignalExportDatesView.as_view(), name='signals_export_dates'),
    path('api/signals/export/<str:date_str>/', SignalExcelExportByDateView.as_view(), name='signals_export_by_date'),
    path('api/signals/watchlist-csv/', SignalWatchlistCsvView.as_view(), name='signals_watchlist_csv'),
    path('api/index-tracker/<str:index_name>/', IndexTrackerView.as_view(), name='index_tracker'),
    path('api/index-tracker/<str:index_name>/dates/', IndexTrackerAvailableDatesView.as_view(), name='index_tracker_dates'),
    path('api/index-tracker/<str:index_name>/export/', IndexTrackerExportView.as_view(), name='index_tracker_export'),
    path('api/index-backtest/<str:index_name>/', IndexBacktestView.as_view(), name='index_backtest'),
    path('api/index-backtest/<str:index_name>/export/', IndexBacktestExportView.as_view(), name='index_backtest_export'),
    path('api/weekly-report/', WeeklyReportView.as_view(), name='weekly_report'),
    path('api/fundamentals-watchlist/', FundamentalsWatchlistView.as_view(), name='fundamentals_watchlist'),
    path('api/cas-auction-moves/<str:index_name>/', CASAuctionMovesView.as_view(), name='cas_auction_moves'),
    # Aug 27 2026: index option calls (NIFTY/BANKNIFTY) -- see
    # index_signal.py for the strike/SL/Target methodology.
    path('api/index-signals/', IndexSignalView.as_view(), name='index_signals'),
    # Aug 27 2026: live-resolved Fyers front-month symbol for a
    # commodity (Crude/Gold/Silver) -- powers MarketBanner.jsx's
    # Crude Oil chart link.
    path('api/commodity-symbol/<str:base_name>/', CommodityCurrentSymbolView.as_view(), name='commodity_symbol'),
    # Aug 27 2026: combined daily backtest checklist (backfill + stock
    # P&L + NIFTY/BANKNIFTY positional) -- see daily_backtest.py.
    path('api/daily-backtest/status/', DailyBacktestStatusView.as_view(), name='daily_backtest_status'),
    path('api/daily-backtest/run/', DailyBacktestRunView.as_view(), name='daily_backtest_run'),
    path('api/daily-backtest/download/<str:report_type>/', DailyBacktestReportDownloadView.as_view(), name='daily_backtest_download'),
    path('api/daily-backtest/range/', DailyBacktestRangeView.as_view(), name='daily_backtest_range'),
    # Aug 29 2026: the actual downloadable PDF for a specific date
    # range -- the line above only ever returns a JSON preview, by
    # design (see DailyBacktestRangeView's own docstring). This is the
    # real counterpart, see DailyBacktestRangeReportView/
    # daily_backtest.run_range_report() for why it needed its own
    # endpoint rather than overloading the preview one.
    path('api/daily-backtest/range/report/', DailyBacktestRangeReportView.as_view(), name='daily_backtest_range_report'),
    # Aug 28 2026: real 52-week high/low for the upcoming Watchlist
    # redesign -- see views.py's get_52_week_high_low() for why this
    # needs its own Fyers History API call (the Quotes API confirmed
    # NOT to provide this field at all).
    path('api/52-week-range/<str:symbol>/', FiftyTwoWeekRangeView.as_view(), name='fifty_two_week_range'),
    # Aug 28 2026: broader NSE indices for Market View's Indices
    # Performance table -- own endpoint, own cadence, see
    # BroaderIndicesView's docstring for why this is separate from
    # market-summary.
    path('api/broader-indices/', BroaderIndicesView.as_view(), name='broader_indices'),
    # Aug 28 2026: price-action strategy backtest (Module 10) -- see
    # strategy_backtest.py for the full engine and why OI-confirmation
    # can't be part of any backtestable strategy.
    path('api/strategy-backtest/run/', StrategyBacktestRunView.as_view(), name='strategy_backtest_run'),
    path('api/strategy-backtest/status/', StrategyBacktestStatusView.as_view(), name='strategy_backtest_status'),

    # App-based endpoints (new structure)
    path('api/screener/', include('screener.urls')),
    path('api/options/', include('options.urls')),
    path('api/news/', include('news.urls')),
    path('api/trading/', include('trading.urls')),
    path('api/backtest/', include('backtest.urls')),
    path('api/fyers/', include('fyers_api.urls')),
]
