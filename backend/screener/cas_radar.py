"""CAS Radar research layer.

This module deliberately builds on the project's existing Fyers-backed
Index Tracker snapshots. It does NOT invent IEP/imbalance fields and does
not turn the existing Bias/OI values into a trading recommendation.

The first version is intentionally narrow: expose the latest observable
snapshot, the existing complete CAS pre/post history, and a machine-readable
capability flag for auction microstructure fields. This gives the frontend a
real CAS tab without creating a second market-data pipeline.
"""
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# These are the names used by NSE's CAS session. Keep the window definition
# here local and explicit; the existing market-hours helper is still the
# source of truth for whether the scanner should be fetching data.
CAS_START = dt_time(15, 15)
CAS_END = dt_time(15, 35)


def _cas_window_now():
    now = datetime.now(IST).time()
    return CAS_START <= now < CAS_END


def _microstructure_capabilities(rows):
    """Detect auction fields only when they genuinely exist in stored data.

    Existing rows use the Index Tracker schema. We deliberately do not
    derive an IEP or imbalance proxy and label it as IEP/imbalance.
    """
    keys = set()
    for row in rows or []:
        keys.update(row.keys())

    aliases = {
        "iep": ("IEP", "Indicative Equilibrium Price", "iep", "indicative_equilibrium_price"),
        "indicative_quantity": ("Indicative Quantity", "indicative_quantity", "IEP Quantity"),
        "imbalance": ("Imbalance", "imbalance", "Indicative Imbalance"),
        "buy_quantity": ("Buy Quantity", "buy_quantity", "Indicative Buy Quantity"),
        "sell_quantity": ("Sell Quantity", "sell_quantity", "Indicative Sell Quantity"),
    }
    found = {name: any(alias in keys for alias in candidates) for name, candidates in aliases.items()}
    return {
        **found,
        "available": any(found.values()),
        "source": "Fyers project feed",
    }


def get_cas_radar(index_name):
    """Return a compact, real-data CAS research payload for one index."""
    from .index_tracker import get_today_snapshots, compute_cas_auction_moves

    name = index_name.upper()
    if name not in ("NIFTY", "BANKNIFTY"):
        raise ValueError("index_name must be NIFTY or BANKNIFTY")

    today_rows = get_today_snapshots(name, limit=120)
    history = compute_cas_auction_moves(name)
    latest = today_rows[0] if today_rows else None
    capabilities = _microstructure_capabilities(today_rows)

    # Keep the API explicit about the absence of auction fields. A future
    # provider can populate these without changing the frontend contract.
    return {
        "index": name,
        "timestamp": datetime.now(IST).isoformat(),
        "cas_window": _cas_window_now(),
        "cas_session": {"start": "15:15", "end": "15:35", "timezone": "Asia/Kolkata"},
        "latest": latest,
        "today_snapshots": today_rows[:20],
        "history": history,
        "microstructure": capabilities,
        "prediction": {
            "status": "research_only",
            "direction": None,
            "large_move_probability": None,
            "reason": "No validated CAS predictor is fitted; historical timestamps are retained for lead-time research.",
        },
    }
