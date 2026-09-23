"""
screener/gamma_zone_engine.py

Gamma Blast Strategy -- Volatility Supply & Demand Zone Engine.

Direct, unmodified port of the purchased package's
core/core_pinescript_engine.py (itself a claimed "line-by-line
mathematical translation" of pine/Volatility_Supply_and_Demand_Zones.pine,
verified against that .pine source directly here, not just trusted).
Zero broker dependency in this file -- pure OHLC-in, zones-out -- so
this ports with the logic completely unchanged; only the module
docstring/location changed to fit this project's flat screener/ layout.

Zone geometry (exactly as specified):
    buffer = ATR(50) * zone_depth / 10       (default zone_depth=2.5 -> 0.25*ATR)
    band   = ATR(50) * guard_mult            (default guard_mult=2.0)
    SELL (resistance) zone: top=pivot high, bottom=top-buffer
    BUY  (support)    zone: bottom=pivot low, top=bottom+buffer
A new zone is refused when its midpoint sits within `band` of a live
zone's midpoint on the same side (the "overlap guard"). A zone retires
the moment price CLOSES through it against its own direction (a sell
zone breaks on close > top, a buy zone on close < bottom) -- matches
the .pine's default brokenMode='Remove'/useWick=false exactly; this
port does not implement the .pine's optional "Freeze"/"Leave running"
modes or wick-based breaks since the source config never enables them.
"""
import numpy as np
import pandas as pd
from typing import List, Dict, Tuple
from dataclasses import dataclass, asdict


@dataclass
class Zone:
    side: str          # 'SELL' (Resistance) or 'BUY' (Support)
    top: float
    bottom: float
    mid: float
    buffer: float
    anchor_bar: int     # bar index the pivot actually formed on
    confirm_bar: int    # bar index the pivot was confirmed (anchor_bar + pivot_len)
    date: str
    is_live: bool = True


class VolatilitySupplyDemandEngine:
    """
    Pivot Length: 10, Zone Depth: 2.5 (tenths of ATR50), Guard Band: 2.0x ATR50
    -- exactly the purchased package's own stated defaults, unchanged.
    """
    def __init__(
        self,
        pivot_len: int = 10,
        zone_depth: float = 2.5,
        guard_mult: float = 2.0,
        zone_memory: int = 20,
        use_wick: bool = False
    ):
        self.pivot_len = pivot_len
        self.zone_depth = zone_depth
        self.guard_mult = guard_mult
        self.zone_memory = zone_memory
        self.use_wick = use_wick

    @staticmethod
    def calculate_atr_wilder(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int = 50) -> np.ndarray:
        """Wilder's RMA ATR(50), matching Pine's ta.atr(50) exactly."""
        n = len(close)
        atr = np.full(n, np.nan)
        if n < 2:
            return atr

        tr = np.zeros(n)
        tr[0] = high[0] - low[0]
        for i in range(1, n):
            hl = high[i] - low[i]
            hc = abs(high[i] - close[i - 1])
            lc = abs(low[i] - close[i - 1])
            tr[i] = max(hl, hc, lc)

        if n >= length:
            atr[length - 1] = np.mean(tr[:length])
            for i in range(length, n):
                atr[i] = (atr[i - 1] * (length - 1) + tr[i]) / length

        return atr

    def compute_zones(self, df: pd.DataFrame) -> Tuple[List[Dict], List[Dict]]:
        """
        Sequential bar-by-bar zone creation and retirement -- no look-ahead:
        each bar first retires any zone price has just closed through,
        THEN (only once pivot_len bars have passed since a candidate
        pivot bar) tests whether that bar was really a pivot and opens
        a zone for it. df must have columns: open/high/low/close, and
        optionally timestamp or date (falls back to a bare row index).

        Returns (live_resistance_zones, live_support_zones), newest first.
        """
        if len(df) < (self.pivot_len * 2 + 1):
            return [], []

        highs = df['high'].to_numpy(dtype=float)
        lows = df['low'].to_numpy(dtype=float)
        closes = df['close'].to_numpy(dtype=float)
        if 'timestamp' in df.columns:
            dates = df['timestamp'].to_numpy()
        elif 'date' in df.columns:
            dates = df['date'].to_numpy()
        else:
            dates = np.array([str(i) for i in range(len(df))])

        n = len(df)
        atr = self.calculate_atr_wilder(highs, lows, closes, length=50)

        tr = np.zeros(n)
        tr[0] = highs[0] - lows[0]
        for k in range(1, n):
            tr[k] = max(highs[k] - lows[k], abs(highs[k] - closes[k - 1]), abs(lows[k] - closes[k - 1]))

        sell_zones: List[Zone] = []
        buy_zones: List[Zone] = []

        for i in range(n):
            curr_close = closes[i]
            curr_atr = atr[i] if not np.isnan(atr[i]) else float(np.mean(tr[:i + 1]))
            buffer = curr_atr * self.zone_depth / 10.0
            band = curr_atr * self.guard_mult

            sell_probe = highs[i] if self.use_wick else curr_close
            buy_probe = lows[i] if self.use_wick else curr_close

            # Retire first -- a zone dying on this bar must not block the
            # zone that may replace it a few lines below.
            sell_zones = [z for z in sell_zones if sell_probe <= z.top]
            buy_zones = [z for z in buy_zones if buy_probe >= z.bottom]

            piv_idx = i - self.pivot_len
            if piv_idx >= self.pivot_len:
                target_h = highs[piv_idx]
                is_piv_high = True
                for k in range(piv_idx - self.pivot_len, piv_idx + self.pivot_len + 1):
                    if k != piv_idx and highs[k] >= target_h:
                        is_piv_high = False
                        break

                if is_piv_high:
                    top = target_h
                    bot = top - buffer
                    mid = (top + bot) / 2.0
                    is_clear = all(abs(mid - z.mid) > band for z in sell_zones)
                    if is_clear:
                        sell_zones.insert(0, Zone(
                            side='SELL', top=float(top), bottom=float(bot), mid=float(mid),
                            buffer=float(buffer), anchor_bar=piv_idx, confirm_bar=i,
                            date=str(dates[piv_idx]), is_live=True,
                        ))
                        if len(sell_zones) > self.zone_memory:
                            sell_zones.pop()

                target_l = lows[piv_idx]
                is_piv_low = True
                for k in range(piv_idx - self.pivot_len, piv_idx + self.pivot_len + 1):
                    if k != piv_idx and lows[k] <= target_l:
                        is_piv_low = False
                        break

                if is_piv_low:
                    bot = target_l
                    top = bot + buffer
                    mid = (top + bot) / 2.0
                    is_clear = all(abs(mid - z.mid) > band for z in buy_zones)
                    if is_clear:
                        buy_zones.insert(0, Zone(
                            side='BUY', top=float(top), bottom=float(bot), mid=float(mid),
                            buffer=float(buffer), anchor_bar=piv_idx, confirm_bar=i,
                            date=str(dates[piv_idx]), is_live=True,
                        ))
                        if len(buy_zones) > self.zone_memory:
                            buy_zones.pop()

        return [asdict(z) for z in sell_zones], [asdict(z) for z in buy_zones]
