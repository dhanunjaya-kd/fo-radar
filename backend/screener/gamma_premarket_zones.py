"""
screener/gamma_premarket_zones.py

Gamma Blast Strategy -- per-symbol S&R directory builder.

Ported from the purchased package's core/daily_premarket_runner.py
(compute_daily_sr_all_stocks' per-symbol body) -- NOT just
gamma_zone_engine.py's raw compute_zones() output. Two real pieces of
logic live here that a naive "just take zones[0]" port would miss
entirely (caught by actually reading this file, not assumed):

1. CONSOLIDATION CEILING/FLOOR ("Dual S&R"): the max high / min low of
   the last 10 bars is added as an EXTRA candidate zone when it isn't
   already within 0.4*ATR50 of a real pivot-based zone on that side.
   Catches tight-range consolidations (the original's own example:
   "INDIGO 5000") that the pivot detector alone can miss because
   nothing ever pivoted cleanly there.
2. "NEAREST" IS GEOMETRIC, NOT RECENCY: nearest_resistance is NOT
   whichever zone the pivot detector found most recently -- it's
   whichever live zone (pivot-based OR consolidation) has its bottom
   edge closest to price, filtered to zones whose top is actually >=
   last_close (i.e. genuinely overhead). Nearest_support mirrors this
   below price. A zone engine's own zones list is FIFO by creation
   order, which is a completely different ordering.
"""
import numpy as np
import pandas as pd
from typing import Dict, Any

from .gamma_zone_engine import VolatilitySupplyDemandEngine


def compute_symbol_sr_directory(
    df: pd.DataFrame,
    lot_size: int = 1,
    pivot_len: int = 10,
    zone_depth: float = 2.5,
    guard_mult: float = 2.0,
) -> Dict[str, Any]:
    """
    df must have columns open/high/low/close/date (or timestamp), same
    shape gamma_zone_engine.compute_zones() takes. Returns a dict with
    the same two directory-entry shapes the original's resistance_
    directory[sym] / support_directory[sym] have.
    """
    engine = VolatilitySupplyDemandEngine(pivot_len=pivot_len, zone_depth=zone_depth, guard_mult=guard_mult, zone_memory=20, use_wick=False)
    sell_zones, buy_zones = engine.compute_zones(df)

    last_close = float(df['close'].iloc[-1])
    last_date = str(df['date'].iloc[-1]) if 'date' in df.columns else str(df['timestamp'].iloc[-1])

    highs = df['high'].to_numpy(dtype=float)
    lows = df['low'].to_numpy(dtype=float)
    closes = df['close'].to_numpy(dtype=float)
    atr_arr = engine.calculate_atr_wilder(highs, lows, closes, 50)
    curr_atr = float(atr_arr[-1]) if not np.isnan(atr_arr[-1]) else float(np.median(highs[-10:] - lows[-10:]))
    zone_buffer = curr_atr * zone_depth / 10.0

    lookback_bars = min(len(highs), 10)
    cons_high = float(np.max(highs[-lookback_bars:]))
    cons_low = float(np.min(lows[-lookback_bars:]))

    all_res_candidates = list(sell_zones)
    if cons_high >= last_close:
        if not any(abs(z['top'] - cons_high) <= (0.4 * curr_atr) for z in sell_zones):
            all_res_candidates.append({
                'side': 'SELL', 'top': round(cons_high, 2), 'bottom': round(cons_high - zone_buffer, 2),
                'mid': round(cons_high - zone_buffer / 2.0, 2), 'buffer': round(zone_buffer, 2),
                'anchor_bar': len(highs) - 1, 'confirm_bar': len(highs) - 1, 'date': last_date,
                'is_live': True, 'type': 'CONSOLIDATION_CEILING',
            })

    all_sup_candidates = list(buy_zones)
    if cons_low <= last_close:
        if not any(abs(z['bottom'] - cons_low) <= (0.4 * curr_atr) for z in buy_zones):
            all_sup_candidates.append({
                'side': 'BUY', 'top': round(cons_low + zone_buffer, 2), 'bottom': round(cons_low, 2),
                'mid': round(cons_low + zone_buffer / 2.0, 2), 'buffer': round(zone_buffer, 2),
                'anchor_bar': len(lows) - 1, 'confirm_bar': len(lows) - 1, 'date': last_date,
                'is_live': True, 'type': 'CONSOLIDATION_FLOOR',
            })

    overhead_resistance = [z for z in all_res_candidates if z['top'] >= last_close]
    overhead_resistance.sort(key=lambda z: z['bottom'])
    underlying_support = [z for z in all_sup_candidates if z['bottom'] <= last_close]
    underlying_support.sort(key=lambda z: z['top'], reverse=True)

    return {
        "resistance": {
            "symbol": None, "lot_size": lot_size, "reference_close": last_close, "reference_date": last_date,
            "atr50": curr_atr,
            "nearest_resistance": overhead_resistance[0] if overhead_resistance else (all_res_candidates[0] if all_res_candidates else None),
            "all_resistance_zones": all_res_candidates,
        },
        "support": {
            "symbol": None, "lot_size": lot_size, "reference_close": last_close, "reference_date": last_date,
            "atr50": curr_atr,
            "nearest_support": underlying_support[0] if underlying_support else (all_sup_candidates[0] if all_sup_candidates else None),
            "all_support_zones": all_sup_candidates,
        },
    }
