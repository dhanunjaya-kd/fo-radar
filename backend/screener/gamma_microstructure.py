"""
screener/gamma_microstructure.py

Gamma Blast Strategy -- 4-Phase Microstructure Trigger Engine.

Direct port of the purchased package's core/microstructure_daemon.py.
This is tick-driven, not history-driven -- it has zero broker
dependency (record_tick() just takes plain numbers), so it ports with
NO logic changes at all. The only thing that differs between here and
the live scanner is WHAT feeds it ticks (this project's Fyers option-
chain polling instead of Dhan's), which lives in the caller, not here.

4 phases, all must confirm together on the same tick for a trigger:
  1. OI DIP:    peak-to-trough OI drop over the lookback >= 0.80%
  2. INFLECTION: current OI > previous tick's OI AND > the trough
  3. VOLUME BUILD: this tick's volume increase >= 1.5x the mean recent
     increase, AND >= max(5*lot_size, 2000)
  4. PRICE LIFT: price has risen 2.0%-9.0% off its recent low, still
     rising tick-over-tick, with spread <= 3.0%
Cooldown (default 1800s = 30min) per contract between triggers.
"""
import numpy as np
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class OptionTick:
    timestamp: float
    time_str: str
    ltp: float
    oi: int
    volume: int
    bid: float
    ask: float


@dataclass
class Candle5M:
    bucket_key: str
    time_str: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    oi: int
    is_confirmed: bool = False


@dataclass
class OptionHistory:
    security_id: Any
    symbol: str
    option_type: str
    strike: float
    expiry: str
    lot_size: int
    ticks: List[OptionTick] = field(default_factory=list)
    candles_5m: List[Candle5M] = field(default_factory=list)
    current_forming_5m: Optional[Candle5M] = None
    last_5m_bucket: Optional[str] = None
    last_trigger_time: float = 0.0


class MicrostructureDaemon:
    """High-frequency tick-buffer state machine, one instance per live scanner process."""

    def __init__(self, buffer_len: int = 25, cooldown_sec: float = 1800.0, enforce_5m_boundary: bool = False):
        self.buffer_len = buffer_len
        self.cooldown_sec = cooldown_sec
        self.enforce_5m_boundary = enforce_5m_boundary
        self.history: Dict[Any, OptionHistory] = {}
        self.alerts_emitted: List[Dict[str, Any]] = []

    def register_contract(self, contract: Dict[str, Any]):
        sec_id = contract.get("security_id")
        if not sec_id or sec_id in self.history:
            return
        self.history[sec_id] = OptionHistory(
            security_id=sec_id,
            symbol=contract.get("symbol", ""),
            option_type=contract.get("option_type", ""),
            strike=float(contract.get("strike", 0.0)),
            expiry=contract.get("expiry", ""),
            lot_size=int(contract.get("lot_size", 1)),
        )

    def update_lifecycle_from_quote(self, sec_id: Any, ltp: float):
        """Update an existing alert lifecycle without evaluating a new trigger."""
        self._update_alert_lifecycles(sec_id, ltp)

    def record_tick(
        self, sec_id: Any, ltp: float, oi: int, volume: int,
        bid: float = 0.0, ask: float = 0.0, tick_time: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        if sec_id not in self.history:
            return None

        now = tick_time if tick_time is not None else datetime.now(IST).timestamp()
        now_dt = datetime.fromtimestamp(now, tz=IST)
        time_str = now_dt.strftime("%H:%M:%S")

        entry = self.history[sec_id]
        entry.ticks.append(OptionTick(timestamp=now, time_str=time_str, ltp=ltp, oi=oi, volume=volume, bid=bid, ask=ask))
        if len(entry.ticks) > self.buffer_len:
            entry.ticks.pop(0)

        bucket_min = (now_dt.minute // 5) * 5
        bucket_key = f"{now_dt.strftime('%Y-%m-%d %H')}:{bucket_min:02d}"
        candle_closed = False

        if entry.last_5m_bucket is not None and bucket_key != entry.last_5m_bucket:
            if entry.current_forming_5m is not None:
                entry.current_forming_5m.is_confirmed = True
                entry.candles_5m.append(entry.current_forming_5m)
                if len(entry.candles_5m) > self.buffer_len:
                    entry.candles_5m.pop(0)
                candle_closed = True
            entry.current_forming_5m = Candle5M(bucket_key=bucket_key, time_str=time_str, open=ltp, high=ltp, low=ltp, close=ltp, volume=volume, oi=oi)
            entry.last_5m_bucket = bucket_key
        elif entry.current_forming_5m is None:
            entry.current_forming_5m = Candle5M(bucket_key=bucket_key, time_str=time_str, open=ltp, high=ltp, low=ltp, close=ltp, volume=volume, oi=oi)
            entry.last_5m_bucket = bucket_key
        else:
            c = entry.current_forming_5m
            c.high = max(c.high, ltp)
            c.low = min(c.low, ltp)
            c.close = ltp
            c.volume = volume
            c.oi = oi

        self._update_alert_lifecycles(sec_id, ltp)
        return self._evaluate_microstructure_trigger(entry, candle_closed=candle_closed, now=now, now_dt=now_dt)

    def _evaluate_microstructure_trigger(self, entry: OptionHistory, candle_closed: bool = False,
                                          now: Optional[float] = None, now_dt=None) -> Optional[Dict[str, Any]]:
        ticks = entry.ticks
        if len(ticks) < 4:
            return None
        if now is None:
            now = datetime.now(IST).timestamp()
        if now_dt is None:
            now_dt = datetime.fromtimestamp(now, tz=IST)
        if self.enforce_5m_boundary and not candle_closed and (now_dt.minute % 5 != 0):
            return None
        if (now - entry.last_trigger_time) < self.cooldown_sec:
            return None

        ois = np.array([t.oi for t in ticks], dtype=float)
        ltps = np.array([t.ltp for t in ticks], dtype=float)
        vols = np.array([t.volume for t in ticks], dtype=float)
        curr_oi, curr_ltp, curr_vol = ois[-1], ltps[-1], vols[-1]
        if curr_ltp <= 0 or curr_oi <= 0:
            return None

        lookback = min(len(ticks) - 1, 8)
        prior_ois = ois[-lookback:-1]
        peak_oi = np.max(prior_ois)
        trough_oi = np.min(prior_ois)
        oi_drop_pct = ((peak_oi - trough_oi) / peak_oi) * 100.0 if peak_oi > 0 else 0.0
        has_oi_fall = bool(oi_drop_pct >= 0.80)

        has_oi_rise = bool((curr_oi > ois[-2]) and (curr_oi > trough_oi))

        vol_changes = np.diff(vols)
        vol_changes = np.maximum(vol_changes, 0)
        recent_vol = vol_changes[-1] if len(vol_changes) > 0 else curr_vol
        mean_vol = np.mean(vol_changes[:-1]) if len(vol_changes) > 1 else max(recent_vol, 1.0)
        min_candle_vol = max(5 * entry.lot_size, 2000)
        has_vol_build = bool((recent_vol >= 1.5 * mean_vol) and (recent_vol >= min_candle_vol))

        trough_ltp = np.min(ltps[-lookback:])
        price_gain_from_base = ((curr_ltp - trough_ltp) / trough_ltp) * 100.0 if trough_ltp > 0 else 0.0
        last_bid, last_ask = ticks[-1].bid, ticks[-1].ask
        spread_val = round(((last_ask - last_bid) / curr_ltp) * 100.0, 2) if (last_ask > 0 and last_bid > 0) else 0.0
        has_price_lift = bool((price_gain_from_base >= 2.0) and (price_gain_from_base <= 9.0) and (curr_ltp >= ltps[-2]) and (spread_val <= 3.0))

        if has_oi_fall and has_oi_rise and has_vol_build and has_price_lift:
            entry.last_trigger_time = now
            sl_price = round(max(0.05, curr_ltp * 0.75), 2)
            risk = max(0.10, curr_ltp - sl_price)
            t1_price = round(curr_ltp + (risk * 1.6), 2)
            t2_price = round(curr_ltp + (risk * 2.8), 2)
            is_5m_confirmed = candle_closed or (now_dt.minute % 5 == 0 and len(entry.candles_5m) > 0)
            candle_tag = "5m_CONFIRMED" if is_5m_confirmed else "INTRADAY_TICK"

            alert_payload = {
                "alert_id": f"ALT_{entry.security_id}_{int(now)}",
                "strategy": "Gamma_Blast_Options_strategy",
                "setup_type": "RESISTANCE_BREAKOUT_CE" if entry.option_type == "CE" else "SUPPORT_BREAKDOWN_PE",
                "horizon": "INTRADAY / SWING",
                "symbol": entry.symbol,
                "contract": f"{entry.symbol} {entry.expiry} {int(entry.strike)} {entry.option_type}",
                "security_id": entry.security_id, "option_type": entry.option_type,
                "strike": entry.strike, "expiry": entry.expiry, "lot_size": entry.lot_size,
                "entry_price": round(curr_ltp, 2), "stop_loss": sl_price, "trailing_sl": sl_price,
                "target_1": t1_price, "target_2": t2_price, "risk_reward": "1:1.6 to 1:2.8",
                "trigger_candle": candle_tag,
                "metrics": {
                    "oi_drop_prior_pct": round(oi_drop_pct, 2), "curr_oi": int(curr_oi),
                    "volume_expansion_ratio": round(recent_vol / max(mean_vol, 1.0), 2),
                    "price_lift_from_base_pct": round(price_gain_from_base, 2),
                },
                "status": "ACTIVE", "highest_ltp": round(curr_ltp, 2), "lowest_ltp": round(curr_ltp, 2),
                "mfe_pct": 0.0, "mae_pct": 0.0, "realized_r": 0.0,
                "exit_price": None, "exit_time_ist": None,
                "timestamp_ist": now_dt.strftime("%Y-%m-%d %H:%M:%S IST"),
            }
            self.alerts_emitted.append(alert_payload)
            return alert_payload
        return None

    def _update_alert_lifecycles(self, sec_id: Any, ltp: float):
        if ltp <= 0:
            return
        now_ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        for alert in self.alerts_emitted:
            if alert.get("security_id") != sec_id:
                continue
            alert["current_ltp"] = round(ltp, 2)
            if ltp > alert.get("highest_ltp", alert["entry_price"]):
                alert["highest_ltp"] = round(ltp, 2)
            if ltp < alert.get("lowest_ltp", alert["entry_price"]):
                alert["lowest_ltp"] = round(ltp, 2)
            entry_p, sl = alert["entry_price"], alert["stop_loss"]
            risk = max(0.05, entry_p - sl)
            if entry_p > 0:
                alert["mfe_pct"] = round(((alert["highest_ltp"] - entry_p) / entry_p) * 100.0, 2)
                alert["mae_pct"] = round(((alert["lowest_ltp"] - entry_p) / entry_p) * 100.0, 2)
            curr_status = alert.get("status", "ACTIVE")
            if curr_status in ("ACTIVE", "TRIGGERED_PRE_EXPLOSION"):
                if ltp >= alert["target_2"]:
                    alert.update(status="TARGET_2_HIT", exit_price=alert["target_2"], exit_time_ist=now_ts,
                                 t2_hit_at_ist=now_ts, realized_r=round((alert["target_2"] - entry_p) / risk, 2))
                elif ltp >= alert["target_1"]:
                    alert.update(status="TARGET_1_HIT", exit_price=alert["target_1"], exit_time_ist=now_ts,
                                 t1_hit_at_ist=now_ts, realized_r=round((alert["target_1"] - entry_p) / risk, 2), trailing_sl=entry_p)
                elif ltp <= alert["stop_loss"]:
                    alert.update(status="STOPPED_OUT", exit_price=alert["stop_loss"], exit_time_ist=now_ts,
                                 sl_hit_at_ist=now_ts, realized_r=round((alert["stop_loss"] - entry_p) / risk, 2))
            elif curr_status == "TARGET_1_HIT":
                if ltp >= alert["target_2"]:
                    r_t1 = (alert["target_1"] - entry_p) / risk
                    r_t2 = (alert["target_2"] - entry_p) / risk
                    alert.update(status="TARGET_2_HIT", exit_price=alert["target_2"], exit_time_ist=now_ts,
                                 t2_hit_at_ist=now_ts, realized_r=round(0.50 * r_t1 + 0.50 * r_t2, 2))
                elif ltp <= alert.get("trailing_sl", entry_p):
                    r_t1 = (alert["target_1"] - entry_p) / risk
                    r_be = (alert.get("trailing_sl", entry_p) - entry_p) / risk
                    alert.update(status="TARGET_1_HIT_TRAILED", exit_price=alert.get("trailing_sl", entry_p), exit_time_ist=now_ts,
                                 realized_r=round(0.50 * r_t1 + 0.50 * r_be, 2))

    def get_signal_journal(self) -> Dict[str, Any]:
        alerts = list(self.alerts_emitted)
        total = len(alerts)
        active = sum(1 for a in alerts if a.get("status") in ("ACTIVE", "TRIGGERED_PRE_EXPLOSION"))
        t1_hits = sum(1 for a in alerts if a.get("status") in ("TARGET_1_HIT", "TARGET_1_HIT_TRAILED"))
        t2_hits = sum(1 for a in alerts if a.get("status") == "TARGET_2_HIT")
        stopped = sum(1 for a in alerts if a.get("status") == "STOPPED_OUT")
        closed = t1_hits + t2_hits + stopped
        win_rate = round(((t1_hits + t2_hits) / closed) * 100.0, 1) if closed > 0 else 0.0
        net_r = round(sum(a.get("realized_r", 0.0) for a in alerts if a.get("status") not in ("ACTIVE", "TRIGGERED_PRE_EXPLOSION")), 2)
        gross_profit = sum(a.get("realized_r", 0.0) for a in alerts if a.get("realized_r", 0.0) > 0)
        gross_loss = abs(sum(a.get("realized_r", 0.0) for a in alerts if a.get("realized_r", 0.0) < 0))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (round(gross_profit, 2) if gross_profit > 0 else 0.0)
        return {
            "total_signals": total, "active_signals": active, "target_1_hits": t1_hits, "target_2_hits": t2_hits,
            "stopped_out": stopped, "closed_signals": closed, "win_rate_pct": win_rate,
            "net_r_multiple": net_r, "profit_factor": profit_factor, "signals": alerts,
        }
