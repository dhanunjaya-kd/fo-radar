from django.apps import AppConfig


class ScreenerConfig(AppConfig):
    """Application-level wiring for the live market session boundary."""

    name = "screener"

    def ready(self):
        # The index worker intentionally has a separate MCX-hours helper,
        # because it historically allowed crude/gold/silver to continue
        # after NSE closed. The scanner UI, however, is a single market
        # snapshot: after the requested 3:40 PM NSE derivatives close we
        # must freeze ALL displayed market data and stop live pulls.
        #
        # Patch the helper at application startup rather than duplicating
        # the same close-time rule inside the worker. The worker imports
        # is_mcx_hours lazily when its loop starts, so it receives this
        # wrapped version. Idempotent because Django can call ready() more
        # than once in unusual test setups.
        try:
            from . import index_tracker
            from .market_hours import is_market_hours

            if getattr(index_tracker, "_fo_radar_global_close_gate", False):
                return

            original = index_tracker.is_mcx_hours

            def _global_close_gated_mcx_hours(now=None):
                if not is_market_hours(now):
                    return False
                return original(now)

            index_tracker.is_mcx_hours = _global_close_gated_mcx_hours
            index_tracker._fo_radar_global_close_gate = True
        except Exception as exc:
            # Startup must remain loud in logs but should not make Django
            # unusable merely because this optional compatibility wrapper
            # could not be installed.
            print(f"[MarketSession] Global close gate setup failed: {exc}")
