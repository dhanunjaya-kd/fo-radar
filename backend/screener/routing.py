from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/screener/$', consumers.ScreenerConsumer.as_asgi()),
    re_path(r'ws/alerts/$', consumers.AlertConsumer.as_asgi()),
    re_path(r'ws/market-overview/$', consumers.MarketOverviewConsumer.as_asgi()),
]
