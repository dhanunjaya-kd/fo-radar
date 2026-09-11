"""Paper trading engine."""
from django.utils import timezone
from .models import PaperTrade
from screener.models import Stock


class PaperTradingEngine:
    def __init__(self):
        pass

    def execute_trade(self, symbol, option_type, strike, entry_price, qty, stop_loss, target_1, target_2=None, target_3=None):
        """Create a validated paper trade.

        Paper trading must reject malformed levels rather than creating a trade
        that can later divide by zero or resolve in the wrong direction.
        """
        if not symbol:
            raise ValueError("Symbol is required")
        option_type = str(option_type or '').upper()
        if option_type not in ('CE', 'PE'):
            raise ValueError("option_type must be CE or PE")

        try:
            strike = float(strike)
            entry_price = float(entry_price)
            qty = int(qty)
            stop_loss = float(stop_loss)
            target_1 = float(target_1)
            target_2 = float(target_2) if target_2 is not None else None
            target_3 = float(target_3) if target_3 is not None else None
        except (TypeError, ValueError):
            raise ValueError("Strike, prices and quantity must be numeric")

        if strike <= 0 or entry_price <= 0 or qty <= 0:
            raise ValueError("Strike, entry price and quantity must be positive")
        if stop_loss <= 0 or target_1 <= 0:
            raise ValueError("Stop loss and target 1 must be positive")

        if option_type == 'CE':
            valid_levels = stop_loss < entry_price < target_1
            if target_2 is not None and target_2 <= target_1:
                raise ValueError("For CE, target 2 must be above target 1")
            if target_3 is not None and (target_2 is None or target_3 <= target_2):
                raise ValueError("For CE, target 3 must be above target 2")
        else:
            valid_levels = stop_loss > entry_price > target_1
            if target_2 is not None and target_2 >= target_1:
                raise ValueError("For PE, target 2 must be below target 1")
            if target_3 is not None and (target_2 is None or target_3 >= target_2):
                raise ValueError("For PE, target 3 must be below target 2")

        if not valid_levels:
            raise ValueError("Stop loss / target 1 levels are inconsistent with the option direction")

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
        """Update trade status based on current premium."""
        try:
            current_price = float(current_price)
        except (TypeError, ValueError):
            return None
        if current_price <= 0:
            return None

        try:
            trade = PaperTrade.objects.get(id=trade_id, status='OPEN')
            if trade.entry_price is None or trade.entry_price <= 0 or not trade.qty or trade.qty <= 0:
                return None

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
        today = timezone.now().date()
        trades = PaperTrade.objects.filter(created_at__date=today)
        return sum((t.pnl or 0) for t in trades)
