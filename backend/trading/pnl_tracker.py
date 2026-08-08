"""PnL Tracker for paper trading and live trades."""
import json
from datetime import datetime


class PnLTracker:
    """Simple PnL tracker for trades."""

    def __init__(self, trades_file="trades.json"):
        self.trades_file = trades_file
        self.trades = []

    def add_trade(self, symbol, entry_price, qty, trade_type="BUY", 
                  exit_price=None, sl=None, target=None):
        """Add a new trade."""
        trade = {
            "id": len(self.trades) + 1,
            "symbol": symbol,
            "entry_price": entry_price,
            "qty": qty,
            "trade_type": trade_type,
            "exit_price": exit_price,
            "sl": sl,
            "target": target,
            "entry_time": datetime.now().isoformat(),
            "exit_time": None,
            "pnl": None,
            "status": "OPEN"
        }
        self.trades.append(trade)
        return trade

    def close_trade(self, trade_id, exit_price):
        """Close a trade and calculate PnL."""
        for trade in self.trades:
            if trade["id"] == trade_id and trade["status"] == "OPEN":
                trade["exit_price"] = exit_price
                trade["exit_time"] = datetime.now().isoformat()
                trade["status"] = "CLOSED"

                if trade["trade_type"] == "BUY":
                    trade["pnl"] = (exit_price - trade["entry_price"]) * trade["qty"]
                else:
                    trade["pnl"] = (trade["entry_price"] - exit_price) * trade["qty"]

                return trade
        return None

    def get_open_trades(self):
        """Get all open trades."""
        return [t for t in self.trades if t["status"] == "OPEN"]

    def get_closed_trades(self):
        """Get all closed trades."""
        return [t for t in self.trades if t["status"] == "CLOSED"]

    def get_total_pnl(self):
        """Get total realized PnL."""
        closed = self.get_closed_trades()
        return sum(t["pnl"] for t in closed if t["pnl"] is not None)

    def get_summary(self):
        """Get PnL summary."""
        closed = self.get_closed_trades()
        total_pnl = self.get_total_pnl()
        winning_trades = [t for t in closed if t["pnl"] and t["pnl"] > 0]
        losing_trades = [t for t in closed if t["pnl"] and t["pnl"] <= 0]

        return {
            "total_trades": len(self.trades),
            "open_trades": len(self.get_open_trades()),
            "closed_trades": len(closed),
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(len(winning_trades) / len(closed) * 100, 2) if closed else 0
        }
