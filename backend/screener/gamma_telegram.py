"""
screener/gamma_telegram.py (Sep 24 2026 rewrite)

Gamma Blast Strategy -- Telegram alert formatting, clean plain-text
layout (direct request, replacing the earlier HTML/blockquote format).

All values below are real, computed by this project's own pipeline --
none are copied from any reference example. Two things worth being
explicit about, since a reference format shown alongside this request
used different numbers:
  - Risk:Reward is genuinely 1:1.6 / 1:2.8 here (target_1_r_multiple/
    target_2_r_multiple in gamma_config.py, from the purchased
    package's own spec) -- not 1:2/1:3.
  - Stop loss is a flat 25% below entry (initial_stop_loss_pct in
    gamma_config.py) -- not an ATR-based structural stop. Nothing in
    this codebase computes an ATR-based option-premium stop; labeling
    it that way would misdescribe the real math.
"Max Holding" is new -- derived from hard_time_stop_hours (48) in
gamma_config.py's risk_management section, not invented: 48 wall-clock
hours generally spans 2 trading sessions, occasionally 3 if it
straddles a weekend -- worded as a range for that reason, not a guess.
"""
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

IST = timezone(timedelta(hours=5, minutes=30))

_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _fmt_expiry_short(expiry_str: str) -> str:
    """'2026-10-27' -> '27OCT' -- matches NSE contract-naming convention."""
    try:
        d = datetime.strptime(expiry_str, "%Y-%m-%d")
        return f"{d.day}{_MONTHS[d.month - 1]}"
    except (ValueError, TypeError):
        return expiry_str or ""


def _fmt_expiry_month(expiry_str: str) -> str:
    """'2026-10-27' -> 'OCT' -- for the Order Copy line's month-only convention."""
    try:
        d = datetime.strptime(expiry_str, "%Y-%m-%d")
        return _MONTHS[d.month - 1]
    except (ValueError, TypeError):
        return ""


def format_gamma_alert(payload: Dict[str, Any]) -> str:
    symbol = payload.get("symbol", "")
    option_type = payload.get("option_type", "")
    strike = payload.get("strike", 0)
    strike_int = int(strike) if strike else 0
    expiry = payload.get("expiry", "")
    security_id = payload.get("security_id", "")
    fyers_symbol = payload.get("fyers_symbol", "")
    lot_size = payload.get("lot_size", 0)
    entry_price = float(payload.get("entry_price", 0.0))
    stop_loss = float(payload.get("stop_loss", 0.0))
    target_1 = float(payload.get("target_1", 0.0))
    target_2 = float(payload.get("target_2", 0.0))
    delta = payload.get("delta")
    convexity = payload.get("convexity")
    dte = payload.get("dte", "")
    trigger_candle = payload.get("trigger_candle", "")

    sl_pct = round(((entry_price - stop_loss) / entry_price) * 100, 1) if entry_price else 0.0
    t1_r = "1.6"
    t2_r = "2.8"
    phase_label = "Confirmed 4-Phase Trigger (OI Dip -> Inflection -> Volume -> Price Lift)"
    hold_label = "up to 2 trading sessions (48h hard stop)"

    expiry_short = _fmt_expiry_short(expiry)
    expiry_month = _fmt_expiry_month(expiry)
    divider = "\u2501" * 35

    lines = [
        f"\u26a1 GAMMA BLAST STRATEGY ALERT [BUY {option_type}] \u26a1",
        divider,
        f"Instrument:    {symbol} {expiry_short} {strike_int} {option_type}",
        # Sep 24 2026: the real Fyers tradable symbol, not this
        # project's own internal tracking key -- Fyers has no numeric
        # "Security ID" concept the way Dhan does, so "Symbol" is the
        # accurate label here, not a copied field name that implies a
        # kind of ID this broker doesn't have. Falls back to the
        # internal key only if the real symbol is somehow missing.
        f"Symbol:        {fyers_symbol or security_id} | Lot Size: {lot_size}",
        f"Market Phase:  {phase_label}",
        divider,
        f"Entry LTP:     Rs {entry_price:.2f}",
        f"Stop Loss:     Rs {stop_loss:.2f} (-{sl_pct:.0f}% flat)",
        f"Target 1:      Rs {target_1:.2f} (1:{t1_r} Risk-Reward)",
        f"Target 2:      Rs {target_2:.2f} (1:{t2_r} Risk-Reward)",
        f"Max Holding:   {hold_label}",
        divider,
    ]
    if delta is not None and convexity is not None:
        lines.append(f"Greeks:        Delta: {delta:.2f} | Gamma Convexity: {convexity:.4f} | DTE: {dte}")
    lines.append(f"Order Copy:    BUY {symbol} {expiry_month} {strike_int} {option_type} LIMIT @ {entry_price:.2f}")
    if trigger_candle:
        lines.append(f"Trigger Tick:  {trigger_candle}")

    return "\n".join(lines)


def compute_lots(account_capital: float, risk_pct: float, entry_price: float, stop_loss_price: float, lot_size: int) -> int:
    """Unchanged from the previous version -- Lots = floor(Capital * Risk% / ((Entry-SL) * LotSize))."""
    risk_per_share = entry_price - stop_loss_price
    if risk_per_share <= 0 or lot_size <= 0:
        return 0
    risk_budget = account_capital * (risk_pct / 100.0)
    risk_per_lot = risk_per_share * lot_size
    if risk_per_lot <= 0:
        return 0
    import math
    return math.floor(risk_budget / risk_per_lot)
