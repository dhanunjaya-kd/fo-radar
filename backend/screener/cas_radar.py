"""CAS Radar research layer.

This module deliberately builds on the project's existing Fyers-backed
Index Tracker snapshots. It does NOT invent IEP/imbalance fields and does
not turn the existing Bias/OI values into a trading recommendation.
"""
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

from rest_framework.views import APIView
from rest_framework.response import Response

IST = ZoneInfo("Asia/Kolkata")
CAS_START = dt_time(15, 15)
CAS_END = dt_time(15, 35)


def _cas_window_now():
    now = datetime.now(IST).time()
    return CAS_START <= now < CAS_END


def _microstructure_capabilities(rows):
    """Detect auction fields only when they genuinely exist in stored data."""
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
    return {**found, "available": any(found.values()), "source": "Fyers project feed"}


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


class CASRadarView(APIView):
    """HTTP adapter for the dedicated CAS Radar research tab."""
    def get(self, request, index_name):
        try:
            return Response(get_cas_radar(index_name))
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        except Exception as e:
            print(f"[CASRadar] request failed: {e}")
            return Response({"error": "CAS Radar data unavailable"}, status=503)
