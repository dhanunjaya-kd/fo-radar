"""Integration with existing Sniper V8.1 backtest Excel."""
import pandas as pd
from django.conf import settings
from datetime import datetime

class BacktestIntegration:
    def __init__(self):
        self.master_path = settings.BACKTEST_MASTER_PATH

    def read_master_file(self):
        """Read SNIPER_TOP5_BACKTEST_MASTER.xlsx."""
        if not self.master_path:
            return None
        try:
            df = pd.read_excel(self.master_path)
            return df
        except Exception as e:
            print(f"Backtest read error: {e}")
            return None

    def sync_to_db(self):
        """Sync Excel backtest data to database."""
        df = self.read_master_file()
        if df is None:
            return False

        from .models import BacktestResult
        # Process and save backtest metrics
        total_signals = len(df)
        executed = df[df['STATUS'].notna()].shape[0] if 'STATUS' in df.columns else 0

        BacktestResult.objects.create(
            strategy_name="Sniper V8.1",
            start_date=datetime.now(),
            end_date=datetime.now(),
            total_signals=total_signals,
            executed_signals=executed,
        )
        return True

    def get_performance_metrics(self):
        """Calculate performance from backtest data."""
        df = self.read_master_file()
        if df is None:
            return {}

        metrics = {
            "total_signals": len(df),
            "columns": list(df.columns),
            "sample": df.head(3).to_dict('records') if not df.empty else [],
        }
        return metrics
