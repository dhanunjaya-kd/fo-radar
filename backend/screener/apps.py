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

        # Keep live OI Excel refresh lightweight without changing OI math or
        # scanner/trading logic.
        try:
            from .oi_dashboard_runtime_guard import install
            install()
        except Exception as exc:
            print(f"[OILiveDashboard] Runtime guard unavailable: {exc}")

        # Match the live OI workbook to the compact desktop reference layout.
        # Presentation only: no market-data, OI, scanner, or signal logic is
        # changed by this guard.
        try:
            from .oi_dashboard_visual_guard import install
            install()
        except Exception as exc:
            print(f"[OILiveDashboard] Visual guard unavailable: {exc}")

        # Preserve the last good live signal list when a whole Fyers quote
        # cycle fails. A genuine successful scan that finds zero signals is
        # still allowed to publish zero.
        try:
            from .scanner_runtime_guard import install
            install()
        except Exception as exc:
            print(f"[ScannerGuard] unavailable: {exc}")

        # Centralize the current NSE F&O Tuesday-expiry rule for legacy
        # callers that still expose the old _last_thursday() helper name.
        try:
            from .expiry_runtime_guard import install
            install()
        except Exception as exc:
            print(f"[ExpiryGuard] unavailable: {exc}")

        # RSS/network reliability and Telegram retry behavior.
        try:
            from .news_runtime_guard import install
            install()
        except Exception as exc:
            print(f"[NewsGuard] unavailable: {exc}")
