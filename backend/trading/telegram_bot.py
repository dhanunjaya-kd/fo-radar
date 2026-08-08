"""Telegram Bot integration for F&O Sniper alerts."""
import os
import requests
from django.conf import settings


class TelegramBot:
    """Simple Telegram bot for sending trade alerts."""

    def __init__(self, bot_token=None, chat_id=None):
        self.bot_token = bot_token or os.environ.get('TELEGRAM_BOT_TOKEN', '')
        self.chat_id = chat_id or os.environ.get('TELEGRAM_CHAT_ID', '')
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"

    def send_message(self, message, parse_mode='HTML'):
        """Send a text message to Telegram."""
        if not self.bot_token or not self.chat_id:
            print("[TelegramBot] Token or Chat ID not configured. Skipping send.")
            return None

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            return response.json()
        except Exception as e:
            print(f"[TelegramBot] Error sending message: {e}")
            return None

    def send_signal_alert(self, symbol, signal_type, entry, sl, target, grade="A"):
        """Send a formatted signal alert."""
        emoji = "🟢" if signal_type in ["BUY", "BUY NOW"] else "🔴"
        message = f"""
{emoji} <b>F&O SNIPER SIGNAL</b> {emoji}

<b>Symbol:</b> {symbol}
<b>Signal:</b> {signal_type}
<b>Grade:</b> {grade}
<b>Entry:</b> ₹{entry}
<b>SL:</b> ₹{sl}
<b>Target:</b> ₹{target}

⏱ Auto-refresh: 5s
        """.strip()

        return self.send_message(message)

    def send_pnl_alert(self, symbol, pnl, trade_type="BUY"):
        """Send PnL update for closed trade."""
        emoji = "✅" if pnl > 0 else "❌"
        message = f"""
{emoji} <b>Trade Closed - {symbol}</b>

<b>Type:</b> {trade_type}
<b>P&L:</b> ₹{round(pnl, 2)}

{'🎯 Profit booked!' if pnl > 0 else '⚠️ SL hit'}
        """.strip()

        return self.send_message(message)

    def test_connection(self):
        """Test if bot is working."""
        return self.send_message("🤖 <b>F&O Sniper Bot</b> is online and ready!")

    
    # Alias for compatibility with views.py
TelegramAlertBot = TelegramBot
