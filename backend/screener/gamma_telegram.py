"""
screener/gamma_telegram.py

Gamma Blast Strategy -- Telegram alert formatting.

Exact port of the purchased package's core/telegram_dispatcher.py
format_telegram_alert() -- same HTML, same layout, same emoji, same
line order, character-for-character. What's NOT ported: that file's
OWN send functions (_dispatch_html_message/send_telegram_alert/
TelegramDispatcher class) -- those are a second, separate Telegram
HTTP client the original package rolls itself. This project already
has a working, tested one (trading/telegram_bot.py, TelegramBot.
send_message()) -- reusing that instead of adding a second Telegram
client is the adaptation here, same reasoning as swapping Dhan's
broker calls for Fyers' elsewhere in this module: don't duplicate
plumbing this project already has and already proved works.
"""
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

IST = timezone(timedelta(hours=5, minutes=30))


def format_gamma_alert(payload: Dict[str, Any], include_targets: bool = True) -> str:
    """payload matches gamma_microstructure.py's alert_payload shape,
    plus optionally spot_price/vah/val/avwap/expansion_score if the
    caller has them. Identical text to the original's
    format_telegram_alert()."""
    symbol = payload.get("symbol", "")
    option_type = payload.get("option_type", "")
    strike = payload.get("strike", 0.0)
    expiry = payload.get("expiry", "")
    entry_price = float(payload.get("entry_price", payload.get("ltp", 0.0)))
    stop_loss = float(payload.get("stop_loss", entry_price * 0.75))
    target_1 = float(payload.get("target_1", entry_price * 1.40))
    target_2 = float(payload.get("target_2", entry_price * 1.70))
    chase_ceiling = float(payload.get("chase_ceiling", entry_price * 1.07))
    lot_size = int(payload.get("lot_size", 1))
    delta = float(payload.get("delta", 0.35))
    gamma = float(payload.get("gamma", 0.0025))
    dte = int(payload.get("dte", 8))
    spot = float(payload.get("spot_price", payload.get("cmp", 0.0)))
    vah = float(payload.get("vah", 0.0))
    val = float(payload.get("val", 0.0))
    avwap = float(payload.get("avwap", 0.0))
    expansion_score = float(payload.get("expansion_score", 0.0))
    time_str = payload.get("timestamp_ist", datetime.now(IST).strftime("%Y-%m-%d %I:%M:%S %p IST"))

    action_emoji = "🟢" if option_type == "CE" else "🔴"
    direction_label = "BULLISH BREAKOUT (CALL)" if option_type == "CE" else "BEARISH BREAKDOWN (PUT)"

    lines = [
        "⚡ <b>[GAMMA_BLAST] TRADE SETUP ALERT</b> ⚡",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"<blockquote>🎯 <b><a href=\"https://t.me/share/url?url={symbol}\">{symbol}</a></b>   •   <b><u>{int(strike) if strike else ''} {option_type}</u></b>   •   <code>{expiry}</code>  {action_emoji}",
        f"🧭 <b>Direction :</b> <b>{direction_label}</b>",
        f"⏰ <b>Timestamp :</b> <b>{time_str}</b></blockquote>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "📊 <b>UNDERLYING PROFILE:</b>",
        f"• 🔹 <b>Symbol</b>          : <code>#{symbol}</code>",
    ]
    if spot > 0:
        lines.append(f"• 💵 <b>Spot CMP</b>        : <b>₹{spot:,.2f}</b>")
    if vah > 0 and val > 0:
        lines.append(f"• 🧱 <b>3-Day VAH / VAL</b>  : <b>₹{vah:,.2f}</b> / <b>₹{val:,.2f}</b>")
    if avwap > 0:
        lines.append(f"• 📈 <b>Monthly AVWAP</b>   : <b>₹{avwap:,.2f}</b>")
    if expansion_score != 0:
        lines.append(f"• 🚀 <b>Zone Proximity</b>  : <b>{expansion_score:+.2f}%</b> into Setup Pocket")

    lines.extend([
        "",
        "⚡ <b><u>OPTION EXECUTION BOUNDS (GAMMA IGNITION)</u></b> ⚡",
        f"<blockquote>🎯 <b>TARGET STRIKE :</b> <b><u>   [ {int(strike) if strike else ''} {option_type} ]   </u></b>  {action_emoji}",
        f"   ↳ <i>Greeks: Delta {delta:.2f} • Gamma {gamma:.5f} • DTE: {dte}</i>",
        "",
        f"🟢 <b>BUY ENTRY BAND   :</b> <b><u>₹{entry_price:.2f} – ₹{chase_ceiling:.2f}</u></b>",
        f"🛑 <b>Initial Stop Loss :</b> <b>₹{stop_loss:.2f} (-25.0% Structure SL • 1.0R Risk)</b>",
    ])
    if include_targets and target_1 > 0:
        lines.extend([
            f"🎯 <b>Target 1 (+40%)   :</b> <b>₹{target_1:.2f}</b> <i>(1:1.6R • Book 50% & Move SL to Breakeven)</i>",
            f"🏆 <b>Target 2 (+70%)   :</b> <b>₹{target_2:.2f}</b> <i>(1:2.8R • Runner Final Profit)</i>",
        ])
    lines.extend([
        f"⚠️ <i>Strict Rule: DO NOT CHASE above ₹{chase_ceiling:.2f} (+7% max slippage)</i>",
        f"📦 <b>Contract Lot Size :</b> <b>{lot_size:,} shares</b></blockquote>",
        "",
        "📋 <b>QUICK ONE-TAP ORDER COPY:</b>",
        f"<code>BUY {symbol} {int(strike) if strike else ''} {option_type} @ {entry_price:.2f} | SL: {stop_loss:.2f} | T1: {target_1:.2f} (1.6R) | T2: {target_2:.2f} (2.8R)</code>",
        "",
        "🛡️ <b>RISK GOVERNANCE:</b> Trade idea and entry parameters generated on volume-confirmed gamma ignition. Position sizing & capital allocation strictly per individual risk profile.",
    ])
    return "\n".join(lines)


def compute_lots(account_capital: float, risk_pct: float, entry_price: float, stop_loss_price: float, lot_size: int) -> int:
    """
    Exact formula from the README's Risk Management section:
    Lots = floor(Capital * Risk% / ((Entry - SL) * LotSize))
    Never risk more than risk_pct (default 0.75-1.0%) of account
    capital on a single trade. Returns 0 (not 1) if the risk-per-lot
    already exceeds the allowed risk budget, rather than forcing a
    trade through undersized.
    """
    risk_per_share = entry_price - stop_loss_price
    if risk_per_share <= 0 or lot_size <= 0:
        return 0
    risk_budget = account_capital * (risk_pct / 100.0)
    risk_per_lot = risk_per_share * lot_size
    if risk_per_lot <= 0:
        return 0
    import math
    return math.floor(risk_budget / risk_per_lot)
