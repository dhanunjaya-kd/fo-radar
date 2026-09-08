from django.apps import AppConfig


class ScreenerConfig(AppConfig):
    """Standard Django application configuration.

    NSE and MCX have different trading sessions. Market-close handling is
    scoped in the API middleware, so this app config must not globally patch
    the MCX clock with the NSE 3:40 PM close.
    """

    name = "screener"
