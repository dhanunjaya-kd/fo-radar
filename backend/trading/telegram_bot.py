"""Telegram Bot integration for F&O Radar alerts."""
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
{emoji} <b>F&O RADAR SIGNAL</b> {emoji}

<b>Symbol:</b> {symbol}
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
