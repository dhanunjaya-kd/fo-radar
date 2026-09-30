"""Telegram Bot integration for F&O Radar alerts."""
import os
import time
import requests
from django.conf import settings


class TelegramBot:
    """Simple Telegram bot for sending trade alerts."""

    def __init__(self, bot_token=None, chat_id=None):
        self.bot_token = bot_token or os.environ.get('TELEGRAM_BOT_TOKEN', '')
        self.chat_id = chat_id or os.environ.get('TELEGRAM_CHAT_ID', '')
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"

    def send_document(self, file_path, caption=None):
        """
        Send a file as a Telegram document (multipart upload, different
        from send_message's plain JSON POST). Used for the weekly
        report -- the file itself, not just a text summary.
        """
        if not self.bot_token or not self.chat_id:
            print("[TelegramBot] Token or Chat ID not configured. Skipping send.")
            return None

        url = f"{self.base_url}/sendDocument"
        try:
            with open(file_path, 'rb') as f:
                files = {'document': (os.path.basename(file_path), f)}
                data = {'chat_id': self.chat_id}
                if caption:
                    data['caption'] = caption
                    data['parse_mode'] = 'HTML'
                response = requests.post(url, data=data, files=files, timeout=30)
                return response.json()
        except Exception as e:
            print(f"[TelegramBot] Failed to send document: {e}")
            return None

    def send_message(self, message, parse_mode='HTML'):
        """
        Send a text message to Telegram.

        Sep 22 2026: this is the module every real call site (views.py,
        tasks.py, generate_weekly_report.py) actually imports --
        `screener/telegram_bot.py` is a separate, unused duplicate that
        earlier retry/logging improvements were mistakenly written into
        instead of here. Ported those improvements into the real file
        this time:

        1. Missing config (blank token/chat id) -- retrying gains
           nothing, so this prints a hard-to-miss, multi-line warning
           ONCE instead of a single easy-to-scroll-past line, pointing
           at test_telegram_alert.py (backend/, run standalone anytime)
           for full diagnosis.
        2. An actual send that fails (network blip, timeout, a
           transient Telegram-side 5xx) -- THIS case retrying genuinely
           helps, so up to 2 retries with a short backoff (1s, then 2s)
           before giving up, each attempt's failure reason printed.
        """
        if not self.bot_token or not self.chat_id:
            print("=" * 60)
            print("[TelegramBot] NOT CONFIGURED -- alert not sent.")
            print("TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID missing from backend/.env")
            print("Run: python test_telegram_alert.py  (from backend/) to diagnose and fix.")
            print("=" * 60)
            return None

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode
        }

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                response = requests.post(url, json=payload, timeout=10)
                data = response.json()
                if data.get("ok"):
                    return data
                # A real Telegram-side rejection (bad token, bad chat
                # id, message too long, etc.) -- retrying with the
                # IDENTICAL payload would fail identically, so this
                # does NOT retry; it reports the real reason instead.
                print(f"[TelegramBot] Telegram rejected the message (attempt {attempt}/{max_attempts}): {data}")
                return data
            except Exception as e:
                print(f"[TelegramBot] Send attempt {attempt}/{max_attempts} failed: {e}")
                if attempt < max_attempts:
                    time.sleep(attempt)  # 1s before attempt 2, 2s before attempt 3
                else:
                    print("[TelegramBot] All retry attempts exhausted -- message NOT delivered.")
                    return None

    def send_signal_alert(self, signal):
        """
        Send a formatted signal alert.

        Sep 30 2026 rewrite: "Design 8" (Bloomberg-style market desk),
        per explicit request with a reference image. Formatting and
        layout ONLY -- every field below is read from the exact same
        signal dict keys the Sep 24 plain-text version used, no new
        fields invented, no value recalculated. html.escape() added on
        every dynamic string value (symbol, pattern, quality_verdict,
        etc.) since this version uses real HTML tags for the first time
        -- the previous plain-text version never needed it, but an
        unescaped '<' or '&' in a dynamic field could now break
        Telegram's HTML parsing or render wrong, so this closes that
        gap rather than carrying it forward unnoticed.
        """
        import html as _html

        symbol = signal.get("symbol", "")
        action = signal.get("action") or signal.get("signal_type", "")
        opt_side = "CE" if action == "BUY" else "PE"
        strike = signal.get("strike")
        strike_int = int(strike) if strike else None
        option_symbol = signal.get("option_symbol", "")
        expiry_date = signal.get("expiry_date") or ""
        entry = signal.get("entry")
        sl = signal.get("sl")
        target1 = signal.get("target1")
        target2 = signal.get("target2")
        target3 = signal.get("target3")
        grade = signal.get("grade", "A")
        confidence = signal.get("confidence", "")
        pattern = signal.get("pattern")
        oi_confirmation = signal.get("oi_confirmation")
        quality_verdict = signal.get("quality_verdict")
        quality_score = signal.get("quality_score")
        risk_reward = signal.get("risk_reward")
        generated_at = signal.get("generated_at")

        def esc(value):
            return _html.escape(str(value)) if value is not None else ""

        def price(value):
            # Sep 30 2026: formatting-only fallback for a missing price
            # value -- the Sep 24 version printed Python's literal
            # "None" string for any unset field (Stop Loss included),
            # which the reference design's own sample shows as "₹—"
            # instead. Never touches a REAL value; only changes how a
            # genuinely absent one is displayed.
            return f"₹{esc(value)}" if value not in (None, "") else "₹—"

        is_buy = action == "BUY"
        direction_emoji = "🟢" if is_buy else "🔴"
        divider = "\u2501" * 24

        instrument_bits = [b for b in [expiry_date, str(strike_int) if strike_int else None, opt_side] if b]

        lines = [
            f"{direction_emoji} <b>{esc(action)}</b> · <b>{esc(opt_side)}</b>     ⚡ <b>F&amp;O RADAR SIGNAL</b>",
            divider,
            f"<b>{esc(symbol)}</b>",
        ]
        if option_symbol:
            lines.append(f"<code>{esc(option_symbol)}</code>")
        if instrument_bits:
            lines.append(" · ".join(esc(b) for b in instrument_bits))
        lines.append(divider)

        if quality_verdict:
            score_bit = f" · {esc(quality_score)}" if quality_score is not None else ""
            lines.append(f"📊 Quality: <b>{esc(quality_verdict)}</b>{score_bit}")
        else:
            lines.append(f"📊 Grade: <b>{esc(grade)}</b>")
        if confidence:
            lines.append(f"🎯 Confidence: <b>{esc(confidence)}</b>")
        if risk_reward:
            lines.append(f"⚖️ Risk:Reward: <b>{esc(risk_reward)}</b>")
        lines.append(divider)

        lines.append(f"🔵 Entry (LIMIT): <b>{price(entry)}</b>")
        lines.append(f"🔴 Stop Loss: <b>{price(sl)}</b>")
        lines.append(f"🟢 Target 1: <b>{price(target1)}</b>")
        if target2 is not None:
            lines.append(f"🟢 Target 2: <b>{price(target2)}</b>")
        if target3 is not None:
            lines.append(f"🟢 Target 3: <b>{price(target3)}</b>")
        lines.append(divider)

        if pattern:
            lines.append(f"✨ Setup: {esc(pattern)}")
        if oi_confirmation:
            lines.append(f"🛡 OI Status: <b>{esc(oi_confirmation)}</b>")
        lines.append(f"🕐 Generated: {esc(generated_at or 'Just now')}")
        lines.append(divider)

        order_target = option_symbol or (f"{symbol} {strike_int} {opt_side}" if strike_int else f"{symbol} {opt_side}")
        lines.append("📋 <b>ORDER COPY</b>")
        lines.append(f"<code>{esc(action)} {esc(order_target)}\nLIMIT @ {esc(entry)}</code>")

        return self.send_message("\n".join(lines))

    def send_pnl_alert(self, trade_info):
        """
        Send a P&L update when a paper trade closes. trade_info is a
        dict with the real PaperTrade fields: symbol, option_type,
        strike, status ('TARGET_HIT'/'SL_HIT'/'CLOSED'), pnl, pnl_pct,
        entry_price, exit_price.
        """
        pnl = trade_info.get('pnl', 0) or 0
        emoji = "✅" if pnl > 0 else "❌"
        status_label = {
            'TARGET_HIT': '🎯 Target hit',
            'SL_HIT': '⚠️ SL hit',
        }.get(trade_info.get('status'), trade_info.get('status', ''))

        message = f"""
{emoji} <b>Trade Closed — {trade_info.get('symbol', '?')} {trade_info.get('option_type', '')} {trade_info.get('strike', '')}</b>

<b>Status:</b> {status_label}
<b>Entry:</b> ₹{trade_info.get('entry_price', '—')}
<b>Exit:</b> ₹{trade_info.get('exit_price', '—')}
<b>P&L:</b> ₹{round(float(pnl), 2)} ({float(trade_info.get('pnl_pct', 0) or 0):+.1f}%)
        """.strip()

        return self.send_message(message)

    def send_market_summary(self, summary):
        """
        Send an end-of-day market summary. summary is a dict matching
        the real MarketOverview model fields: nifty_spot, nifty_change,
        banknifty_spot, banknifty_change, total_pcr, total_signals,
        buy_signals, sell_signals.
        """
        message = f"""
📊 <b>Daily Market Summary</b>

<b>NIFTY:</b> {summary.get('nifty_spot', '—')} ({float(summary.get('nifty_change', 0) or 0):+.2f}%)
<b>BANKNIFTY:</b> {summary.get('banknifty_spot', '—')} ({float(summary.get('banknifty_change', 0) or 0):+.2f}%)

<b>Signals today:</b> {summary.get('total_signals', 0)} total ({summary.get('buy_signals', 0)} BUY / {summary.get('sell_signals', 0)} SELL)
<b>PCR:</b> {summary.get('total_pcr', '—')}
        """.strip()

        return self.send_message(message)

    def test_connection(self):
        """Test if bot is working."""
        return self.send_message("🤖 <b>F&O Radar Bot</b> is online and ready!")


# Alias for compatibility with views.py
TelegramAlertBot = TelegramBot
