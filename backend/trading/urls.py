from django.urls import path
from . import views

urlpatterns = [
    path('paper-trade/', views.create_paper_trade, name='create-paper-trade'),
    path('paper-trades/', views.list_paper_trades, name='list-paper-trades'),
    path('pnl/summary/', views.pnl_summary, name='pnl-summary'),
    path('pnl/today/', views.today_pnl, name='today-pnl'),
    path('telegram/test/', views.test_telegram, name='test-telegram'),
]
