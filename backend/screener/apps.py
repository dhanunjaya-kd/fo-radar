from django.apps import AppConfig


class ScreenerConfig(AppConfig):
    """Standard Django application configuration.

    NSE and MCX have different trading sessions. Market-close handling is
    scoped in the API middleware, so this app config must not globally patch
    the MCX clock with the NSE 3:40 PM close.
    """

    name = "screener"

    def ready(self):
        # Existing Excel workbooks can retain an old black header format even
        # when the stored labels are correct. Reapply only the header styling;
        # no market-data or OI calculation logic is changed.
        try:
            from .oi_dashboard_header_guard import install
            install()
        except Exception as exc:
            print(f"[OILiveDashboard] Header guard unavailable: {exc}")
