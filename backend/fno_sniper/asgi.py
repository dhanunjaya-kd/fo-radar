"""
ASGI config for fno_sniper project.
Uses Channels for WebSocket support.
"""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fno_sniper.settings')

# django.setup() (triggered by get_asgi_application()) must run BEFORE any
# app code that touches models/settings is imported -- that's why the
# channels/routing imports are below this line, not at the top of the file.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

# This used to be `from . import consumers` -- fno_sniper/consumers.py has
# never existed in this project (the real consumer classes live in
# screener/consumers.py, options/consumers.py, trading/consumers.py), so
# every import of this module raised ImportError and the whole ASGI app
# failed to boot. `uvicorn fno_sniper.asgi:application` could not run.
import screener.routing
import options.routing
import trading.routing

# screener/routing.py and trading/routing.py BOTH register 'ws/alerts/' for
# two different consumer classes (screener.AlertConsumer vs
# trading.AlertsConsumer). Channels' URLRouter matches the first pattern in
# the list, so simply concatenating both apps' patterns would silently
# shadow one of them. Keep screener's (it's the one screener/views.py's
# signal pipeline actually sends alerts through) and drop trading's
# duplicate 'ws/alerts/' entry to avoid a silent collision.
_trading_patterns = [
    p for p in trading.routing.websocket_urlpatterns
    if p.pattern.regex.pattern != r'ws/alerts/$'
]

websocket_urlpatterns = (
    screener.routing.websocket_urlpatterns
    + options.routing.websocket_urlpatterns
    + _trading_patterns
)

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(websocket_urlpatterns)
    ),
})