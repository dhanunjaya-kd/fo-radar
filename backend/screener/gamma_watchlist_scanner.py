"""
screener/gamma_watchlist_scanner.py

Gamma Blast Strategy -- Proximity Scanner + 50 EMA Macro Trend Gate.

Direct port of the purchased package's core/watchlist_scanner.py
evaluate_market_proximity()/scan_universe() logic -- every threshold,
buffer formula, and sort order below is copied unchanged from that
file. What's NOT ported unchanged is the data-fetching shell around
it: the original hits DhanHQ's REST API directly (fetch_live_quotes,
fetch_live_fno_quotes) and reads a Dhan-specific token-map JSON. This
project is Fyers-only everywhere else, so that HTTP layer is replaced
by plain function inputs here -- the CALLER (gamma_live_scanner.py)
is responsible for supplying quotes/zones/ema50 from this project's
own existing Fyers plumbing (_cached_history_df, get_quotes). Nothing
below this docstring changes behavior versus the original; only where
the input data comes from changes.
"""
from typing import Dict, List, Any, Optional


def evaluate_market_proximity(
    quotes: Dict[str, Dict[str, Any]],
    zones_by_symbol: Dict[str, Dict[str, Any]],
    ema50_by_symbol: Dict[str, float],
    proximity_pct: float = 0.75,
    approach_pct: float = 2.0,
) -> Dict[str, List[Dict]]:
    """
    quotes: {symbol: {"cmp", "open", "day_high", "day_low", "volume", "lot_size"}}
    zones_by_symbol: {symbol: {"nearest_resistance": {"top","bottom","date"} | None,
                                "nearest_support": {"top","bottom","date"} | None,
                                "atr50": float}}
    ema50_by_symbol: {symbol: float}

    Returns the same 4 step-buckets the original returns, unchanged
    field names and unchanged formulas throughout.
    """
    approaching_resistance: List[Dict] = []
    approaching_support: List[Dict] = []
    resistance_watchlist: List[Dict] = []
    support_watchlist: List[Dict] = []

    for sym, quote in quotes.items():
        cmp = float(quote.get("cmp", 0.0))
        if cmp <= 0:
            continue

        open_p = float(quote.get("open", cmp))
        day_high = float(quote.get("day_high", cmp))
        day_low = float(quote.get("day_low", cmp))
        day_vol = int(quote.get("volume", 0))
        lot_size = int(quote.get("lot_size", 1))

        zinfo = zones_by_symbol.get(sym, {})
        nearest_res = zinfo.get("nearest_resistance")
        nearest_sup = zinfo.get("nearest_support")
        atr = float(zinfo.get("atr50", cmp * 0.02))

        # Resistance / CE evaluation
        if nearest_res:
            res_top = float(nearest_res["top"])
            res_bot = float(nearest_res["bottom"])
            dist_res_pct = round(((res_bot - cmp) / cmp) * 100.0, 2)
            ema_val = ema50_by_symbol.get(sym, cmp)
            ce_trend_aligned = (cmp >= ema_val)

            breakout_buffer_res = max(0.5 * atr, cmp * 0.015)
            is_approaching_res = (cmp <= res_top + breakout_buffer_res) and (cmp >= res_bot - max(atr, cmp * (approach_pct / 100.0)))
            if is_approaching_res:
                status_res = "RESISTANCE_BREAKOUT_ACTIVE" if cmp > res_top else "APPROACHING_RESISTANCE"
                ce_momentum = bool((cmp >= open_p) or (day_high > day_low and cmp >= day_low + 0.50 * (day_high - day_low)))
                item_res = {
                    "symbol": sym, "cmp": cmp, "open": open_p, "day_high": day_high, "day_low": day_low,
                    "volume": day_vol, "lot_size": lot_size,
                    "zone_bottom": round(res_bot, 2), "zone_top": round(res_top, 2),
                    "distance_pct": dist_res_pct, "atr50": round(atr, 2), "ema50": ema_val,
                    "trend_aligned": ce_trend_aligned, "intraday_momentum": ce_momentum,
                    "zone_date": nearest_res.get("date", ""), "status": status_res,
                }
                approaching_resistance.append(item_res)

                is_in_res_wl = (
                    (dist_res_pct <= proximity_pct and cmp >= res_bot - 0.35 * atr) or
                    (res_bot <= cmp <= res_top + breakout_buffer_res)
                )
                if is_in_res_wl:
                    wl = dict(item_res)
                    wl["status"] = "RESISTANCE_BREAKOUT_ACTIVE" if cmp > res_top else "RESISTANCE_WATCHLIST_ACTIVE"
                    resistance_watchlist.append(wl)

        # Support / PE evaluation
        if nearest_sup:
            sup_top = float(nearest_sup["top"])
            sup_bot = float(nearest_sup["bottom"])
            dist_sup_pct = round(((cmp - sup_top) / cmp) * 100.0, 2)
            ema_val = ema50_by_symbol.get(sym, cmp)
            pe_trend_aligned = (cmp <= ema_val)

            breakdown_buffer_sup = max(0.5 * atr, cmp * 0.015)
            is_approaching_sup = (cmp >= sup_bot - breakdown_buffer_sup) and (cmp <= sup_top + max(atr, cmp * (approach_pct / 100.0)))
            if is_approaching_sup:
                status_sup = "SUPPORT_BREAKDOWN_ACTIVE" if cmp < sup_bot else "APPROACHING_SUPPORT"
                pe_momentum = bool((cmp <= open_p) or (day_high > day_low and cmp <= day_low + 0.50 * (day_high - day_low)))
                item_sup = {
                    "symbol": sym, "cmp": cmp, "open": open_p, "day_high": day_high, "day_low": day_low,
                    "volume": day_vol, "lot_size": lot_size,
                    "zone_bottom": round(sup_bot, 2), "zone_top": round(sup_top, 2),
                    "distance_pct": dist_sup_pct, "atr50": round(atr, 2), "ema50": ema_val,
                    "trend_aligned": pe_trend_aligned, "intraday_momentum": pe_momentum,
                    "zone_date": nearest_sup.get("date", ""), "status": status_sup,
                }
                approaching_support.append(item_sup)

                is_in_sup_wl = (
                    (dist_sup_pct <= proximity_pct and cmp <= sup_top + 0.35 * atr) or
                    (sup_bot - breakdown_buffer_sup <= cmp <= sup_top)
                )
                if is_in_sup_wl:
                    wl = dict(item_sup)
                    wl["status"] = "SUPPORT_BREAKDOWN_ACTIVE" if cmp < sup_bot else "SUPPORT_WATCHLIST_ACTIVE"
                    support_watchlist.append(wl)

    approaching_resistance.sort(key=lambda x: x["distance_pct"])
    approaching_support.sort(key=lambda x: x["distance_pct"])
    resistance_watchlist.sort(key=lambda x: (not x.get("trend_aligned", False), not x.get("intraday_momentum", False), x["distance_pct"]))
    support_watchlist.sort(key=lambda x: (not x.get("trend_aligned", False), not x.get("intraday_momentum", False), x["distance_pct"]))

    return {
        "step2_approaching_resistance": approaching_resistance,
        "step3_approaching_support": approaching_support,
        "step4_resistance_watchlist": resistance_watchlist,
        "step5_support_watchlist": support_watchlist,
    }


def scan_universe(
    quotes: Dict[str, Dict[str, Any]],
    zones_by_symbol: Dict[str, Dict[str, Any]],
    ema50_by_symbol: Dict[str, float],
    proximity_pct: float = 0.75,
    approach_pct: float = 2.0,
    min_underlying_volume: float = 500000,
    min_underlying_turnover_cr: float = 100.0,
) -> Dict[str, Any]:
    """
    Same liquidity gate + top-3-per-side selection as the original
    scan_universe(): underlying volume/turnover floor, then sorted by
    (trend_aligned first, then closest distance_pct), top 3 kept.
    """
    proximity_res = evaluate_market_proximity(quotes, zones_by_symbol, ema50_by_symbol, proximity_pct, approach_pct)
    res_pool = proximity_res.get("step4_resistance_watchlist") or proximity_res.get("step2_approaching_resistance", [])
    sup_pool = proximity_res.get("step5_support_watchlist") or proximity_res.get("step3_approaching_support", [])

    if min_underlying_volume > 0 or min_underlying_turnover_cr > 0:
        def _passes(x):
            vol_ok = min_underlying_volume == 0 or x.get("volume", 0) >= min_underlying_volume
            to_ok = min_underlying_turnover_cr == 0 or (x.get("volume", 0) * x.get("cmp", 0.0) / 1e7) >= min_underlying_turnover_cr
            return vol_ok and to_ok
        res_pool = [x for x in res_pool if _passes(x)]
        sup_pool = [x for x in sup_pool if _passes(x)]

    res_pool.sort(key=lambda x: (not x.get("trend_aligned", False), x.get("distance_pct", 99.0)))
    sup_pool.sort(key=lambda x: (not x.get("trend_aligned", False), x.get("distance_pct", 99.0)))

    return {
        "resistance_watchlist": res_pool[:3],
        "support_watchlist": sup_pool[:3],
        "raw_proximity": proximity_res,
    }
