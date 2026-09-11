"""Install the shared NSE Tuesday-expiry rule into legacy call sites.

index_tracker.py and positional_logger.py historically used a Thursday helper.
Keeping the patch in one tiny compatibility layer avoids touching their mature
snapshot/tracking logic while making every runtime caller use the same current
NSE rule.
"""
import threading

_install_lock = threading.Lock()
_installed = False


def install():
    global _installed
    with _install_lock:
        if _installed:
            return
        from . import index_tracker
        from .nse_expiry import last_nse_fno_expiry

        # Existing callers ask for _last_thursday(year, month). Keep that API
        # shape but route it to the authoritative Tuesday-expiry implementation.
        index_tracker._last_thursday = last_nse_fno_expiry
        _installed = True
