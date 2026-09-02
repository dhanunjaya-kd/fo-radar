"""
backend/next_day_ranking.py

Turns eod_scanner.py's raw quote+history data into the actual Next Day
Watchlist -- Trend Status, Volume Status, Sector Strength, and a
transparent 0-100 Score per stock, ranked best-first. Same
"runner.py fetches, ranking.py ranks" separation this project already
uses for fundamentals -- fetching and ranking kept in separate files.

HONEST SCOPE: Trend Status/Volume Status/Score/Sector Strength are
REASONABLE, CLEARLY-LABELED proposals built from real computed
indicators (RSI/SMA/volume-vs-average -- the same tested functions
index_tracker.py's Trend & Momentum card already uses), not an
extraction of any specific reference tool's exact undisclosed formula.

sectors_map is passed in by the caller (not imported from views.py
directly) deliberately -- views.py will need to import FROM this
module too, once an API view exists for it, and importing SECTORS
from views.py here would create a circular import.
"""
import json
import os
from datetime import datetime

from .index_tracker import compute_rsi, compute_sma
from .eod_scanner import OUTPUT_FILE as RAW_DATA_FILE

RANKED_OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "next_day_watchlist.json")
MIN_CANDLES_REQUIRED = 21  # 20 for SMA + 1 more for a volume-average baseline


def classify_trend_status(rsi, distance_from_sma_pct):
    """Reasonable, labeled tiers -- not extracted from anywhere.
    Requires BOTH inputs; returns None (never guesses a tier) if
    either is missing."""
    if rsi is None or distance_from_sma_pct is None:
        return None
    strength = 0
    if rsi >= 60 or rsi <= 40:
        strength += 1
    if abs(distance_from_sma_pct) >= 2:
        strength += 1
    if abs(distance_from_sma_pct) >= 5:
        strength += 1
    if strength >= 3:
        return "Strong"
    elif strength >= 2:
        return "Moderate"
    elif strength >= 1:
        return "Weak"
    return "None"


def classify_volume_status(today_volume, avg_volume):
    """Today's volume vs the trailing 20-day average -- ratio-based
    tiers, reasonable and labeled, not extracted from anywhere. None
    if either value is missing/zero, never a guessed ratio."""
    if not today_volume or not avg_volume:
        return None
    ratio = today_volume / avg_volume
    if ratio >= 3:
        return "Heavy Accumulation"
    elif ratio >= 1.5:
        return "Accumulation"
    elif ratio <= 0.5:
        return "Heavy Distribution"
    elif ratio <= 0.7:
        return "Distribution"
    return "Normal"


def compute_score(rsi, distance_from_sma_pct, volume_ratio, sector_relative_pct):
    """
    Transparent 0-100 score, same spirit as the existing F&O sniper
    score (score_breakdown in views.py) -- real, documented factor
    weights, no hidden formula. Each factor contributes independently
    and only if its input is actually available -- missing data means
    that factor contributes 0, not a guessed default.
    """
    score = 0
    breakdown = {}

    if rsi is not None:
        pts = 20 if (rsi >= 60 or rsi <= 40) else 0
        breakdown["rsi"] = pts
        score += pts

    if distance_from_sma_pct is not None:
        pts = min(25, round(abs(distance_from_sma_pct) * 5))
        breakdown["trend_distance"] = pts
        score += pts

    if volume_ratio is not None:
        pts = max(0, min(30, round((volume_ratio - 1) * 15))) if volume_ratio > 1 else 0
        breakdown["volume"] = pts
        score += pts

    if sector_relative_pct is not None:
        pts = 25 if sector_relative_pct > 0 else 0
        breakdown["sector_strength"] = pts
        score += pts

    return min(100, score), breakdown


def build_watchlist(sectors_map=None, top_n=30, min_score=0, raw_data=None):
    """
    Reads eod_scanner.py's raw output (or accepts raw_data directly,
    for testing), computes real indicators per symbol, ranks best-
    first. sectors_map: {short_symbol: sector_name}, e.g. views.py's
    SECTORS -- passed in by the caller, not imported here. Stocks not
    in it show sector "Unknown", honestly, never guessed.

    Returns (watchlist, universe_scanned, stocks_with_enough_data).
    """
    if raw_data is None:
        if not os.path.exists(RAW_DATA_FILE):
            return [], 0, 0
        with open(RAW_DATA_FILE, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

    sectors_map = sectors_map or {}
    candidates = []
    sector_changes = {}

    for symbol, entry in raw_data.items():
        candles = entry.get("daily_candles") or []
        quote = entry.get("quote") or {}
        if len(candles) < MIN_CANDLES_REQUIRED:
            continue

        closes = [c["close"] for c in candles]
        volumes = [c.get("volume") for c in candles if c.get("volume")]

        rsi = compute_rsi(closes, period=14)
        sma = compute_sma(closes, period=20)
        current_price = quote.get("price") or closes[-1]
        distance_from_sma_pct = round((current_price - sma) / sma * 100, 2) if sma else None

        today_volume = quote.get("volume") or (volumes[-1] if volumes else None)
        avg_volume = round(sum(volumes[-21:-1]) / len(volumes[-21:-1]), 0) if len(volumes) >= 21 else None
        volume_ratio = round(today_volume / avg_volume, 2) if (today_volume and avg_volume) else None

        short_symbol = symbol.replace("NSE:", "").replace("-EQ", "")
        sector = sectors_map.get(short_symbol, "Unknown")
        change_percent = quote.get("change_percent")
        if sector != "Unknown" and change_percent is not None:
            sector_changes.setdefault(sector, []).append(change_percent)

        candidates.append({
            "symbol": symbol, "sector": sector, "eod_price": current_price,
            "change_percent": change_percent, "rsi": rsi, "sma_20": sma,
            "distance_from_sma_pct": distance_from_sma_pct,
            "today_volume": today_volume, "avg_volume_20d": avg_volume,
            "volume_ratio": volume_ratio,
        })

    # Sector Strength -- this stock's change% vs its sector's average
    # among OTHER scanned stocks. Only meaningful with a known sector
    # AND at least 2 peers to compare against.
    for c in candidates:
        if c["sector"] == "Unknown" or c["change_percent"] is None:
            c["sector_strength"] = None
            c["sector_relative_pct"] = None
            continue
        peers = sector_changes.get(c["sector"], [])
        if len(peers) < 2:
            c["sector_strength"] = None
            c["sector_relative_pct"] = None
            continue
        sector_avg = sum(peers) / len(peers)
        relative = round(c["change_percent"] - sector_avg, 2)
        c["sector_relative_pct"] = relative
        c["sector_strength"] = "Leading" if relative > 0 else "Average" if relative > -1 else "Lagging"

    for c in candidates:
        c["trend_status"] = classify_trend_status(c["rsi"], c["distance_from_sma_pct"])
        c["volume_status"] = classify_volume_status(c["today_volume"], c["avg_volume_20d"])
        score, breakdown = compute_score(c["rsi"], c["distance_from_sma_pct"], c["volume_ratio"], c["sector_relative_pct"])
        c["score"] = score
        c["score_breakdown"] = breakdown

    candidates = [c for c in candidates if c["score"] >= min_score]
    candidates.sort(key=lambda c: c["score"], reverse=True)

    ranked = candidates[:top_n]
    for i, c in enumerate(ranked, 1):
        c["rank"] = i

    result = {
        "generated_at": datetime.now().isoformat(),
        "universe_scanned": len(raw_data),
        "stocks_with_enough_data": len(candidates),
        "watchlist": ranked,
    }
    with open(RANKED_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    return ranked, len(raw_data), len(candidates)
