"""Runtime resilience guard for the live scanner.

The main scanner already preserves _stock_cache when the Fyers quote fetch
returns no data. This guard closes the remaining gap: _build_all() could
still replace _signal_cache with [] after that failed fetch, making the live
UI falsely show Signals=0 for a transient outage.

We deliberately wrap the existing scanner instead of rewriting its scoring
logic. A cycle that did not advance _last_fetch is a failed quote-fetch cycle,
so its signal list is not allowed to erase the last successful signal list.
A successful cycle that genuinely produces zero qualifying signals is left
alone and correctly shows zero.
"""
import threading

_install_lock = threading.Lock()
_installed = False


def install():
    global _installed
    with _install_lock:
        if _installed:
            return

        from . import views
        original = views._build_all

        def guarded_build_all(*args, **kwargs):
            previous_signals = list(getattr(views, "_signal_cache", []) or [])
            previous_fetch = getattr(views, "_last_fetch", 0)
            original(*args, **kwargs)

            # If no successful stock quote fetch occurred during this cycle,
            # the scanner's own empty-result assignment must not erase good data.
            current_fetch = getattr(views, "_last_fetch", 0)
            if current_fetch == previous_fetch and previous_signals:
                with views._cache_lock:
                    views._signal_cache = previous_signals
                print("[ScannerGuard] Quote scan failed; preserved last-good signals")

        guarded_build_all.__name__ = original.__name__
        guarded_build_all.__doc__ = original.__doc__
        guarded_build_all._last_good_guard_installed = True
        views._build_all = guarded_build_all
        _installed = True
