from django.urls import path
from . import views

urlpatterns = [
    path('results/', views.backtest_results, name='backtest-results'),
    path('sync/', views.sync_backtest, name='sync-backtest'),
    path('metrics/', views.backtest_metrics, name='backtest-metrics'),
]
