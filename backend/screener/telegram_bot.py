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

        Sep 21 2026: real, confirmed incident -- signals were logging
        correctly (proven from the actual Excel log) but zero
        Telegram alerts arrived, with only a quiet one-line console
        print as the trace. Two changes here, addressing the two real
        failure modes separately rather than one blanket fix:

        1. Missing config (blank token/chat id) -- retrying gains
           nothing (the same blank value fails the same way every
           time), so this now prints a hard-to-miss, multi-line
           warning ONCE instead of a single easy-to-scroll-past line,
           pointing directly at test_telegram_alert.py (backend/,
           same folder, run standalone anytime -- not market-hours-
           or live-signal-dependent) for full diagnosis rather than
           repeating that script's own detailed guidance here.
        2. An actual send that fails (network blip, timeout, a
           transient Telegram-side 5xx) -- THIS case retrying
           genuinely helps, so up to 2 retries with a short backoff
           (1s, then 2s) before giving up, each attempt's failure
           reason printed so a persistent failure is still fully
           diagnosable, not just eaten silently after 3 tries.
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

    def send_signal_alert(self, symbol, signal_type, entry, sl, target, grade="A", strike=None):
        """Send a formatted signal alert."""
        emoji = "🟢" if signal_type in ["BUY", "BUY NOW"] else "🔴"
        # Sep 19 2026: Strike added, right after Symbol -- direct
        # request. The signal dict has carried this ("strike": strike)
        # since before this alert existed (views.py's own
        # "recommendation" field already spells out f"{action}
        # {opt_side} — ₹{strike} STRIKE" using the same value) -- this
        # was already computed and available, just never passed
        # through to this specific message. Optional (defaults to
        # None) so nothing breaks if this is ever called without a
        # strike on hand; the line is only shown when there's a real
        # value, never a fabricated placeholder.
        strike_line = f"\n<b>Strike:</b> ₹{strike}" if strike is not None else ""
        message = f"""
{emoji} <b>F&O RADAR SIGNAL</b> {emoji}

<b>Symbol:</b> {symbol}{strike_line}
<b>Signal:</b> {signal_type}
<b>Grade:</b> {grade}
<b>Entry:</b> ₹{entry}
<b>SL:</b> ₹{sl}
<b>Target:</b> ₹{target}

⏱ Auto-refresh: 5s
        """.strip()

        return self.send_message(message)

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
