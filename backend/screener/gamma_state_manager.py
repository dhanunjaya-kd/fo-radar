"""
screener/gamma_state_manager.py

Gamma Blast Strategy -- Persistent State & Lifecycle Manager.

Direct, unmodified port of the purchased package's
core/persistent_state_manager.py. Pure JSON-file state management --
no broker calls anywhere in this file in the original either, so
nothing needed adapting; only the storage path changed to fit this
project's existing signal_logs/ directory instead of a new data/ one.

Carries a qualified stock/option across scan cycles (and across a
restart, since it round-trips through disk) until one of:
  1. Target achieved (handled by gamma_microstructure.py's own
     lifecycle tracking on options; this file itself just tracks
     ACTIVE_TRACKING vs INVALIDATED/EXPIRED for stocks/options)
  2. Invalidation: price breaches 1.5x ATR(50) beyond the OPPOSITE
     side of its S&R zone (a resistance stock invalidates if price
     falls below zone_bottom - 1.5*ATR; a support stock invalidates
     if price rallies above zone_top + 1.5*ATR)
  3. Option's expiry date has passed
"""
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))


class GammaStateManager:
    def __init__(self, state_file: Path, lot_size_map: Optional[Dict[str, int]] = None):
        self.state_file = state_file
        self.lot_size_map = lot_size_map or {}
        self.state: Dict[str, Any] = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return self._normalize_state(json.load(f))
            except Exception:
                pass
        return {
            "strategy": "Gamma_Blast_Options_strategy",
            "version": "1.4.0",
            "last_updated": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
            "active_stocks": {}, "active_options": {},
            "completed_trades": [], "invalidated_items": [],
        }

    def _normalize_state(self, data: Dict[str, Any]) -> Dict[str, Any]:
        lots = self.lot_size_map
        for sym, s in data.get("active_stocks", {}).items():
            cmp_val = float(s.get("cmp", s.get("last_cmp", 0.0)))
            s["cmp"], s["last_cmp"] = cmp_val, cmp_val
            vol_val = int(s.get("volume", s.get("last_volume", 0)))
            s["volume"], s["last_volume"] = vol_val, vol_val
            s["lot_size"] = int(s.get("lot_size") if s.get("lot_size", 1) > 1 else lots.get(sym, s.get("lot_size", 1)))
            if "distance_pct" not in s or s["distance_pct"] is None:
                if s.get("type") == "RESISTANCE":
                    z_bot = float(s.get("zone_bottom", cmp_val))
                    s["distance_pct"] = round(((z_bot - cmp_val) / (cmp_val or 1.0)) * 100.0, 2)
                else:
                    z_top = float(s.get("zone_top", cmp_val))
                    s["distance_pct"] = round(((cmp_val - z_top) / (cmp_val or 1.0)) * 100.0, 2)

        for key, o in data.get("active_options", {}).items():
            sym = o.get("symbol", "")
            ltp_val = float(o.get("ltp", o.get("last_ltp", 0.0)))
            o["ltp"], o["last_ltp"] = ltp_val, ltp_val
            oi_val = int(o.get("oi", o.get("last_oi", 0)))
            o["oi"], o["last_oi"] = oi_val, oi_val
            vol_val = int(o.get("volume", o.get("last_volume", 0)))
            o["volume"], o["last_volume"] = vol_val, vol_val
            o["lot_size"] = int(o.get("lot_size") if o.get("lot_size", 1) > 1 else lots.get(sym, o.get("lot_size", 1)))
            gamma_v, delta_v = float(o.get("gamma", 0.0)), float(o.get("delta", 0.0))
            bid_v, ask_v = float(o.get("bid", 0.0)), float(o.get("ask", 0.0))
            conv_val = o.get("convexity", o.get("gamma_convexity"))
            if conv_val is None:
                conv_val = round((gamma_v / (ltp_val if ltp_val > 0 else 1.0)) * 100.0, 4)
            o["convexity"], o["gamma_convexity"] = conv_val, conv_val
            sprd_val = o.get("spread_pct", o.get("bid_ask_spread_pct"))
            if sprd_val is None:
                sprd_val = round(((ask_v - bid_v) / (ltp_val if ltp_val > 0 else 1.0)) * 100.0, 2) if (ask_v > 0 and bid_v > 0) else 0.0
            o["spread_pct"], o["bid_ask_spread_pct"] = sprd_val, sprd_val
            if "delta_sweet_spot" not in o:
                o["delta_sweet_spot"] = bool(0.15 <= abs(delta_v) <= 0.45)
        return data

    def save_state(self):
        self.state["last_updated"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        tmp = self.state_file.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
            tmp.replace(self.state_file)  # atomic on both Windows and POSIX
        except Exception as e:
            print(f"[GammaState] save failed: {e}")

    def sync_scanned_stocks(self, resistance_watchlist: List[Dict], support_watchlist: List[Dict], prune_unlisted: bool = False):
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        now_ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        def _sync_side(watchlist, side_type, default_category):
            for stock in watchlist:
                sym = stock["symbol"]
                cmp_val = float(stock.get("cmp", stock.get("last_cmp", 0.0)))
                vol_val = int(stock.get("volume", stock.get("last_volume", 0)))
                dist_val = float(stock.get("distance_pct", 0.0))
                lot_val = int(stock.get("lot_size", 1))
                if sym not in self.state["active_stocks"]:
                    self.state["active_stocks"][sym] = {
                        "symbol": sym, "type": side_type,
                        "category": stock.get("category", default_category),
                        "added_date": today_str, "first_seen_ist": now_ts,
                        "scrip_id": stock.get("scrip_id"),
                        "zone_bottom": stock.get("zone_bottom"), "zone_top": stock.get("zone_top"),
                        "atr50": stock.get("atr50"), "ema50": stock.get("ema50"),
                        "trend_aligned": stock.get("trend_aligned", True),
                        "target_options": stock.get("target_options", []),
                        "cmp": cmp_val, "last_cmp": cmp_val, "volume": vol_val, "last_volume": vol_val,
                        "lot_size": lot_val, "distance_pct": dist_val,
                        "open": stock.get("open", cmp_val), "day_high": stock.get("day_high", cmp_val),
                        "day_low": stock.get("day_low", cmp_val),
                        "status": "ACTIVE_TRACKING", "carryover": False,
                    }
                else:
                    entry = self.state["active_stocks"][sym]
                    entry["cmp"], entry["last_cmp"] = cmp_val, cmp_val
                    entry["volume"], entry["last_volume"] = vol_val, vol_val
                    entry["lot_size"] = lot_val if lot_val > 1 else entry.get("lot_size", lot_val)
                    entry["distance_pct"] = dist_val
                    entry["zone_bottom"] = stock.get("zone_bottom", entry.get("zone_bottom"))
                    entry["zone_top"] = stock.get("zone_top", entry.get("zone_top"))
                    entry["atr50"] = stock.get("atr50", entry.get("atr50"))
                    entry["ema50"] = stock.get("ema50", entry.get("ema50"))
                    entry["trend_aligned"] = stock.get("trend_aligned", entry.get("trend_aligned", True))
                    entry["target_options"] = stock.get("target_options", entry.get("target_options", []))

        _sync_side(resistance_watchlist, "RESISTANCE", "RESISTANCE_WATCHLIST")
        _sync_side(support_watchlist, "SUPPORT", "SUPPORT_WATCHLIST")

        if prune_unlisted:
            active_symbols = {s["symbol"] for s in (resistance_watchlist + support_watchlist) if s.get("symbol")}
            for sym in list(self.state["active_stocks"].keys()):
                if sym not in active_symbols:
                    del self.state["active_stocks"][sym]
        self.save_state()

    def sync_scanned_options(self, options_list: List[Dict[str, Any]], prune_unlisted: bool = False):
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        now_ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        for opt in options_list:
            sec_id = opt.get("security_id")
            if not sec_id:
                continue
            key = str(sec_id)
            ltp_val = float(opt.get("ltp", opt.get("last_ltp", 0.0)))
            oi_val = int(opt.get("oi", opt.get("last_oi", 0)))
            vol_val = int(opt.get("volume", opt.get("last_volume", 0)))

            if key not in self.state["active_options"]:
                conv = float(opt.get("convexity") or opt.get("gamma_convexity") or round((float(opt.get("gamma", 0.0)) / (ltp_val or 1.0)) * 100.0, 4))
                bid_o, ask_o = float(opt.get("bid", 0.0)), float(opt.get("ask", 0.0))
                sprd = float(opt.get("spread_pct") or opt.get("bid_ask_spread_pct") or (round(((ask_o - bid_o) / (ltp_val or 1.0)) * 100.0, 2) if (ask_o > 0 and bid_o > 0) else 0.0))
                self.state["active_options"][key] = {
                    "security_id": sec_id, "symbol": opt.get("symbol"), "option_type": opt.get("option_type"),
                    "strike": opt.get("strike"), "expiry": opt.get("expiry"), "rank": opt.get("rank"),
                    "tier": opt.get("tier", "GOLD" if opt.get("rank") == 1 else "SILVER"),
                    "category": opt.get("category"), "lot_size": opt.get("lot_size", 1),
                    "added_date": today_str, "first_seen_ist": now_ts,
                    "initial_oi": oi_val, "oi": oi_val, "last_oi": oi_val,
                    "delta_oi": opt.get("delta_oi", 0), "delta_oi_pct": opt.get("delta_oi_pct", 0.0),
                    "ltp": ltp_val, "last_ltp": ltp_val, "volume": vol_val, "last_volume": vol_val,
                    "bid": bid_o, "ask": ask_o,
                    "delta": float(opt.get("delta", 0.0)), "gamma": float(opt.get("gamma", 0.0)),
                    "theta": float(opt.get("theta", 0.0)), "vega": float(opt.get("vega", 0.0)),
                    "iv": float(opt.get("iv", 0.0)), "convexity": conv, "gamma_convexity": conv,
                    "spread_pct": sprd, "bid_ask_spread_pct": sprd,
                    "delta_sweet_spot": opt.get("delta_sweet_spot", bool(0.15 <= abs(float(opt.get("delta", 0.0))) <= 0.45)),
                    "spot_cmp": opt.get("spot_cmp", 0.0), "distance_to_strike_pct": opt.get("distance_to_strike_pct", 0.0),
                    "status": "ACTIVE_TRACKING", "carryover": False,
                }
            else:
                entry = self.state["active_options"][key]
                entry["oi"], entry["last_oi"] = oi_val, oi_val
                entry["ltp"], entry["last_ltp"] = ltp_val, ltp_val
                entry["volume"], entry["last_volume"] = vol_val, vol_val
                entry["bid"] = float(opt.get("bid", entry.get("bid", 0.0)))
                entry["ask"] = float(opt.get("ask", entry.get("ask", 0.0)))
                entry["lot_size"] = int(opt.get("lot_size") if opt.get("lot_size", 1) > 1 else entry.get("lot_size", 1))
                entry["rank"] = opt.get("rank", entry.get("rank"))
                entry["tier"] = opt.get("tier", entry.get("tier", "GOLD" if entry.get("rank") == 1 else "SILVER"))
                entry["category"] = opt.get("category", entry.get("category"))
                entry["delta_oi"] = opt.get("delta_oi", entry.get("delta_oi", 0))
                entry["delta_oi_pct"] = opt.get("delta_oi_pct", entry.get("delta_oi_pct", 0.0))
                entry["delta"] = float(opt.get("delta", entry.get("delta", 0.0)))
                entry["gamma"] = float(opt.get("gamma", entry.get("gamma", 0.0)))
                entry["theta"] = float(opt.get("theta", entry.get("theta", 0.0)))
                entry["vega"] = float(opt.get("vega", entry.get("vega", 0.0)))
                entry["iv"] = float(opt.get("iv", entry.get("iv", 0.0)))
                conv = float(opt.get("convexity") or opt.get("gamma_convexity") or entry.get("convexity", 0.0))
                entry["convexity"], entry["gamma_convexity"] = conv, conv
                sprd = float(opt.get("spread_pct") or opt.get("bid_ask_spread_pct") or entry.get("spread_pct", 0.0))
                entry["spread_pct"], entry["bid_ask_spread_pct"] = sprd, sprd
                entry["delta_sweet_spot"] = opt.get("delta_sweet_spot", entry.get("delta_sweet_spot", False))

        if prune_unlisted and options_list:
            active_keys = {str(opt.get("security_id")) for opt in options_list if opt.get("security_id")}
            for k in list(self.state["active_options"].keys()):
                if k not in active_keys:
                    del self.state["active_options"][k]
        self.save_state()

    def evaluate_invalidation(self, live_quotes_by_symbol: Dict[str, Dict[str, Any]]):
        """live_quotes_by_symbol keyed by SYMBOL (not scrip_id -- this project has no
        Dhan scrip-id concept, so invalidation is matched by symbol directly)."""
        today_str = datetime.now(IST).strftime("%Y-%m-%d")

        for sym, stock in list(self.state["active_stocks"].items()):
            quote = live_quotes_by_symbol.get(sym)
            if quote:
                cmp = float(quote.get("cmp", stock.get("cmp", stock.get("last_cmp", 0.0))))
                stock["cmp"], stock["last_cmp"] = cmp, cmp
                stock["volume"] = int(quote.get("volume", stock.get("volume", 0)))
                stock["last_volume"] = stock["volume"]
                atr = float(stock.get("atr50", cmp * 0.02))

                if stock["type"] == "RESISTANCE":
                    z_bot = float(stock.get("zone_bottom", cmp))
                    stock["distance_pct"] = round(((z_bot - cmp) / cmp) * 100.0, 2)
                    if cmp < z_bot - (1.5 * atr):
                        stock["status"] = "INVALIDATED"
                        stock["invalidation_reason"] = f"Price retreated below Resistance - 1.5 ATR (CMP: {cmp} < {round(z_bot - 1.5*atr, 2)})"
                        self.state["invalidated_items"].append(stock)
                        del self.state["active_stocks"][sym]
                        continue
                elif stock["type"] == "SUPPORT":
                    z_top = float(stock.get("zone_top", cmp))
                    stock["distance_pct"] = round(((cmp - z_top) / cmp) * 100.0, 2)
                    if cmp > z_top + (1.5 * atr):
                        stock["status"] = "INVALIDATED"
                        stock["invalidation_reason"] = f"Price rallied above Support + 1.5 ATR (CMP: {cmp} > {round(z_top + 1.5*atr, 2)})"
                        self.state["invalidated_items"].append(stock)
                        del self.state["active_stocks"][sym]
                        continue

            if stock.get("added_date") != today_str:
                stock["carryover"] = True

        for sec_id, opt in list(self.state["active_options"].items()):
            exp = opt.get("expiry", "")
            if exp and exp < today_str:
                opt["status"] = "EXPIRED"
                opt["invalidation_reason"] = f"Contract expired on {exp}"
                self.state["invalidated_items"].append(opt)
                del self.state["active_options"][sec_id]
                continue
            if opt.get("added_date") != today_str:
                opt["carryover"] = True

        self.save_state()

    def get_combined_stocks_watchlist(self) -> Dict[str, List[Dict[str, Any]]]:
        resistance_list, support_list = [], []
        for stock in self.state["active_stocks"].values():
            if stock.get("status") == "ACTIVE_TRACKING":
                (resistance_list if stock.get("type") == "RESISTANCE" else support_list).append(stock)
        return {"resistance_watchlist": resistance_list, "support_watchlist": support_list}

    def get_combined_options_watchlist(self) -> List[Dict[str, Any]]:
        opts = [o for o in self.state["active_options"].values() if o.get("status") == "ACTIVE_TRACKING"]
        opts.sort(key=lambda x: (x.get("option_type", "CE") != "CE", x.get("symbol", ""), x.get("rank", 99)))
        return opts
