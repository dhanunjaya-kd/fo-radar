from pathlib import Path
from screener.gamma_trade_tracker import GammaTradeTracker

def a():
 return {"alert_id":"A1","symbol":"JIOFIN","contract":"JIOFIN 2026-10-27 212 PE","security_id":"J1","option_type":"PE","strike":212,"expiry":"2026-10-27",
         "fyers_symbol":"NSE:JIOFIN26OCT212PE","entry_price":5.4,"stop_loss":4.05,"target_1":7.56,"target_2":9.18,
         "timestamp_ist":"2026-10-01 10:45:18 IST","trigger_candle":"5m_CONFIRMED"}

def test_exact_contract_once(tmp_path):
 t=GammaTradeTracker(Path(tmp_path)/"tracker.xlsx"); x=a()
 assert t.record_alert(x,x) is True
 assert t.record_alert(x,x) is False
 assert len(t.get_all_rows())==1

def test_lifecycle_update_in_place(tmp_path):
 t=GammaTradeTracker(Path(tmp_path)/"tracker.xlsx"); x=a(); t.record_alert(x,x)
 y=dict(x,status="TARGET_1_HIT",current_ltp=7.56,trailing_sl=5.4,mfe_pct=40.0,t1_hit_at_ist="2026-10-01 11:05:00 IST")
 t.sync_alerts([y]); row=t.get_all_rows()[0]
 assert row["status"]=="TARGET_1_HIT"
 assert row["t1_hit_at_ist"]=="2026-10-01 11:05:00 IST"
