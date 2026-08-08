"""
Celery tasks for trading operations
"""
from celery import shared_task
from django.utils import timezone
from django.db.models import Q
from .models import PaperTrade
from .paper_trading import PaperTradingEngine
from .pnl_tracker import PnLTracker
from .telegram_bot import TelegramBot
from screener.models import StockSnapshot
import logging

logger = logging.getLogger(__name__)

@shared_task
def update_paper_trades():
    """Update all open paper trades with current prices"""
    open_trades = PaperTrade.objects.filter(status='OPEN')

    for trade in open_trades:
        # Get latest snapshot
        snapshot = StockSnapshot.objects.filter(stock=trade.stock).first()
        if not snapshot:
            continue

        # For options, we'd need option LTP - using stock LTP as proxy for demo
        current_price = snapshot.ltp

        updated = PaperTradingEngine.update_trade_status(trade, current_price)

        if updated.status != 'OPEN':
            # Send Telegram alert
            bot = TelegramBot()
            bot.send_pnl_alert({
                'symbol': trade.stock.symbol,
                'option_type': trade.option_type,
                'strike': trade.strike,
                'status': updated.status,
                'pnl': updated.pnl,
                'pnl_pct': updated.pnl_pct,
                'entry_price': trade.entry_price,
                'exit_price': updated.exit_price,
            })

    return f"Updated {open_trades.count()} trades"

@shared_task
def calculate_daily_pnl():
    """Calculate daily PnL summary at market close"""
    today = timezone.now().date()
    summary = PnLTracker.calculate_daily_summary(today)

    if summary:
        logger.info(f"Daily PnL calculated: {summary.net_pnl}")

    return summary.net_pnl if summary else 0

@shared_task
def send_daily_summary():
    """Send daily market summary via Telegram"""
    from screener.models import MarketOverview

    today = timezone.now().date()
    try:
        overview = MarketOverview.objects.filter(date=today).latest('timestamp')
        bot = TelegramBot()
        bot.send_market_summary({
            'nifty_spot': overview.nifty_spot,
            'nifty_change': overview.nifty_change,
            'banknifty_spot': overview.banknifty_spot,
            'banknifty_change': overview.banknifty_change,
            'total_signals': overview.total_signals,
            'buy_signals': overview.buy_signals,
            'sell_signals': overview.sell_signals,
            'avg_score': overview.avg_score,
            'avg_confidence': overview.avg_confidence,
            'pcr_nifty': overview.pcr_nifty,
            'pcr_banknifty': overview.pcr_banknifty,
        })
    except Exception as e:
        logger.error(f"Daily summary error: {e}")

    return "Daily summary sent"
