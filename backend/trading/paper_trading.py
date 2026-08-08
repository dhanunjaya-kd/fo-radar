"""Paper trading engine."""
from django.utils import timezone
from .models import PaperTrade
from screener.models import Stock

class PaperTradingEngine:
    def __init__(self):
        pass

    def execute_trade(self, symbol, option_type, strike, entry_price, qty, stop_loss, target_1, target_2=None, target_3=None):
        """Execute a paper trade."""
        stock = Stock.objects.get(symbol=symbol)
        trade = PaperTrade.objects.create(
            stock=stock, option_type=option_type, strike=strike,
            entry_price=entry_price, qty=qty,
            stop_loss=stop_loss, target_1=target_1,
            target_2=target_2, target_3=target_3,
            status='OPEN'
        )
        return trade

    def update_trade(self, trade_id, current_price):
        """Update trade status based on current price."""
        try:
            trade = PaperTrade.objects.get(id=trade_id, status='OPEN')

            # Check SL
            if trade.option_type == 'CE':
                if current_price <= trade.stop_loss:
                    trade.exit_price = current_price
                    trade.pnl = (current_price - trade.entry_price) * trade.qty
                    trade.pnl_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100
                    trade.status = 'SL_HIT'
                    trade.exit_reason = 'Stop Loss'
                elif current_price >= trade.target_1:
                    trade.exit_price = current_price
                    trade.pnl = (current_price - trade.entry_price) * trade.qty
                    trade.pnl_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100
                    trade.status = 'TARGET_HIT'
                    trade.exit_reason = 'Target 1'
            else:  # PE
                if current_price >= trade.stop_loss:
                    trade.exit_price = current_price
                    trade.pnl = (trade.entry_price - current_price) * trade.qty
                    trade.pnl_pct = ((trade.entry_price - current_price) / trade.entry_price) * 100
                    trade.status = 'SL_HIT'
                    trade.exit_reason = 'Stop Loss'
                elif current_price <= trade.target_1:
                    trade.exit_price = current_price
                    trade.pnl = (trade.entry_price - current_price) * trade.qty
                    trade.pnl_pct = ((trade.entry_price - current_price) / trade.entry_price) * 100
                    trade.status = 'TARGET_HIT'
                    trade.exit_reason = 'Target 1'

            if trade.status != 'OPEN':
                trade.closed_at = timezone.now()
            trade.save()
            return trade
        except PaperTrade.DoesNotExist:
            return None

    def get_open_trades(self):
        return PaperTrade.objects.filter(status='OPEN')

    def get_today_pnl(self):
        from django.utils import timezone
        today = timezone.now().date()
        trades = PaperTrade.objects.filter(created_at__date=today)
        return sum(t.pnl for t in trades)
