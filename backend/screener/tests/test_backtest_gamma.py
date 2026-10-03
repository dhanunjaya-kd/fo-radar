"""
Oct 3 2026: tests for backtest_gamma.py -- the Gamma Blast strategy's own backtest report.
python -m unittest screener.tests.test_backtest_gamma

The end-to-end tests build their log files with the app's OWN gamma_excel_logger / GammaTradeTracker, so a change to
either file format that would break this report fails here instead of silently producing an empty PDF.
"""
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

from screener import backtest_gamma as bg
from screener import gamma_excel_logger as gel
from screener import gamma_trade_tracker as gtt


def row(**over):
    """A finished, well-formed tracker-style row (entry 20, SL 15 -> 1R = 5; T1 28, T2 34)."""
    base = {
        "alert_id": "A1", "contract": "RELIANCE 2026-10-27 1300 CE", "symbol": "RELIANCE", "option_type": "CE",
        "strike": 1300, "expiry": "2026-10-27", "dte": 5, "entry": 20.0, "sl": 15.0, "t1": 28.0, "t2": 34.0,
        "lot_size": 250, "status": "STOPPED_OUT", "realized_r": -1.0, "exit_price": None,
        "entered": "2026-09-24 10:00:00 IST", "closed": "2026-09-24 10:30:00 IST", "trigger_candle": "5m_CONFIRMED",
        "trailing_sl": None, "oi_drop": 1.2, "vol_exp": 2.1, "price_lift": 3.0,
        "t1_hit": None, "t2_hit": None, "sl_hit": "2026-09-24 10:30:00 IST", "carry": False,
    }
    base.update(over)
    return base


def load(rows, lots=None):
    with mock.patch("screener.lot_size_resolver.get_lot_size", side_effect=lambda s: (lots or {}).get(s)):
        return bg.load_gamma_trades(rows=rows)


class RowsToTrades(unittest.TestCase):
    def test_all_four_finish_types_match_the_live_engines_realized_r(self):
        rows = [
            row(alert_id="a", contract="C a", status="STOPPED_OUT", realized_r=-1.0),
            row(alert_id="b", contract="C b", status="TARGET_2_HIT", realized_r=2.8),
            row(alert_id="c", contract="C c", status="TARGET_2_HIT", realized_r=2.2, t1_hit="2026-09-24 10:10:00 IST"),
            row(alert_id="d", contract="C d", status="TARGET_1_HIT_TRAILED", realized_r=0.8, t1_hit="2026-09-24 10:10:00 IST"),
        ]
        trades, excluded, info = load(rows)
        self.assertEqual((len(trades), excluded, info["still_open"]), (4, 0, 0))
        pnl = {t["contract"]: t["pnl"] for t in trades}
        # lot 250, risk 5: R x 5 x 250
        self.assertEqual(pnl, {"C a": -1250.0, "C b": 3500.0, "C c": 2750.0, "C d": 1000.0})
        self.assertEqual({t["contract"]: t["exit_reason"] for t in trades},
                         {"C a": "SL Hit", "C b": "Target 2 Hit", "C c": "Target 2 Hit", "C d": "Target 1 Hit"})

    def test_blended_exit_price_is_not_rounded(self):
        # entry 2.5 / SL 1.88 (risk 0.62) / +0.8R -> exit 2.996; rounding to 2 dp would add ~Rs 22 to a 5500 lot
        t, _, _ = load([row(entry=2.5, sl=1.88, t1=3.49, t2=4.24, lot_size=5500, status="TARGET_1_HIT_TRAILED", realized_r=0.8)])
        self.assertAlmostEqual(t[0]["pnl"], 5500 * 0.8 * 0.62, places=2)
        self.assertAlmostEqual(t[0]["exit_price"], 2.996, places=6)

    def test_calls_are_BUY_and_puts_are_SELL(self):
        t, _, _ = load([row(alert_id="1", contract="X 1", option_type="CE"), row(alert_id="2", contract="X 2", option_type="PE")])
        self.assertEqual(sorted(x["action"] for x in t), ["BUY", "SELL"])

    def test_open_trades_are_never_counted(self):
        rows = [row(alert_id="1", contract="X 1", status="ACTIVE", realized_r=0.0),
                row(alert_id="2", contract="X 2", status="TARGET_1_HIT", realized_r=1.6)]   # first leg booked, second still running
        trades, excluded, info = load(rows)
        self.assertEqual((len(trades), excluded, info["still_open"]), (0, 2, 2))

    def test_overnight_flag_comes_from_the_dates_not_the_trackers_carry_column(self):
        t, _, _ = load([row(closed="2026-09-25 11:00:00 IST", carry=False)])
        self.assertTrue(t[0]["carried_overnight"])
        t, _, _ = load([row()])
        self.assertFalse(t[0]["carried_overnight"])


class WhatIsNeverGuessed(unittest.TestCase):
    def test_missing_lot_size_excludes_the_trade(self):
        trades, excluded, info = load([row(lot_size=None)], lots={})
        self.assertEqual((len(trades), info["excluded_other"]), (0, {"no_lot_size": 1}))

    def test_lot_size_from_the_resolver_when_the_log_has_none(self):
        trades, _, _ = load([row(lot_size=None)], lots={"RELIANCE": 250})
        self.assertEqual(trades[0]["qty"], 250)

    def test_a_logged_lot_of_one_is_the_restart_placeholder_not_a_real_lot(self):
        trades, _, _ = load([row(lot_size=1)], lots={"RELIANCE": 250})
        self.assertEqual(trades[0]["qty"], 250)

    def test_r_is_recomputed_only_where_unambiguous(self):
        rows = [
            row(alert_id="1", contract="C 1", status="STOPPED_OUT", realized_r=0.0),                                   # -> -1R
            row(alert_id="2", contract="C 2", status="TARGET_1_HIT_TRAILED", realized_r=None, trailing_sl=20.0),       # -> 0.8R
            row(alert_id="3", contract="C 3", status="TARGET_2_HIT", realized_r=None, t1_hit="2026-09-24 10:10:00 IST"),  # -> 2.2R
            row(alert_id="4", contract="C 4", status="TARGET_2_HIT", realized_r=None, t1_hit=None),                    # T1 first or straight through? unknown
        ]
        trades, _, info = load(rows)
        self.assertEqual(sorted(round(t["r_multiple"], 2) for t in trades), [-1.0, 0.8, 2.2])
        self.assertEqual(info["excluded_other"], {"r_unrecoverable": 1})
        self.assertEqual(info["r_recomputed"], 3)

    def test_bad_rows_are_excluded_and_counted_by_reason(self):
        rows = [
            row(alert_id="1", contract="C 1", closed="2026-09-24 09:00:00 IST", sl_hit=None),   # exit before entry
            row(alert_id="2", contract="C 2", sl=25.0),                                          # SL above entry
            row(alert_id="3", contract="C 3", option_type="XX"),
            row(alert_id="4", contract="C 4", entered=None),
            row(alert_id="5", contract="C 5", closed=None, sl_hit=None),                         # no exit time anywhere
        ]
        trades, _, info = load(rows)
        self.assertEqual(len(trades), 0)
        self.assertEqual(info["excluded_other"], {"exit_before_entry": 1, "bad_levels": 1, "bad_option_type": 1, "no_entry_time": 1, "no_exit_time": 1})

    def test_exit_time_falls_back_to_the_hit_time(self):
        t, _, _ = load([row(closed=None, sl_hit="2026-09-24 10:45:00 IST")])
        self.assertEqual(t[0]["exit_dt"], datetime(2026, 9, 24, 10, 45))


class Diagnosis(unittest.TestCase):
    """The card / terminal must say WHY there is no PDF, in plain words, from what was actually found."""

    def test_unknown_status_is_surfaced_not_treated_as_open(self):
        trades, _, info = load([row(alert_id="1", contract="C 1", status="TARGET_3_HIT", realized_r=3.5)])
        self.assertEqual((len(trades), info["still_open"], info["excluded_other"]), (0, 0, {"unknown_status": 1}))
        self.assertIn("TARGET_3_HIT 1", bg.explain(info))
        self.assertIn("status is not one this report knows", bg.explain(info))

    def test_status_counts_cover_every_logged_row(self):
        rows = [row(alert_id=str(i), contract=f"C {i}", status=st, realized_r=0.0) for i, st in enumerate(["ACTIVE", "ACTIVE", "TARGET_1_HIT"])]
        _, _, info = load(rows)
        self.assertEqual(info["status_counts"], {"ACTIVE": 2, "TARGET_1_HIT": 1})
        msg = bg.explain(info)
        self.assertIn("3 Gamma triggers logged, none finished yet", msg)
        self.assertIn("ACTIVE 2, TARGET_1_HIT 1", msg)

    def test_expired_contract_is_priced_from_the_last_seen_premium(self):
        trades, _, info = load([row(status="EXPIRED", realized_r=None, current_ltp=10.0, closed="2026-10-27 15:30:00 IST", sl_hit=None)])
        self.assertEqual(len(trades), 1)
        self.assertAlmostEqual(trades[0]["r_multiple"], (10.0 - 20.0) / 5.0, places=6)      # -2R: it fell through the stop unseen
        self.assertEqual(trades[0]["exit_reason"], "Closed (expired)")

    def test_expired_with_no_price_anywhere_is_left_out(self):
        _, _, info = load([row(status="EXPIRED", realized_r=None, current_ltp=None, closed="2026-10-27 15:30:00 IST", sl_hit=None)])
        self.assertEqual(info["excluded_other"], {"r_unrecoverable": 1})

    def test_explain_when_nothing_was_found(self):
        info = {"logged_contracts": 0, "resolved_trades": 0, "still_open": 0, "excluded_other": {}, "status_counts": {},
                "sources": {"log_dir": "/x/signal_logs", "tracker_found": False, "daily_files": 0}}
        msg = bg.explain(info)
        self.assertIn("No Gamma log files found", msg)
        self.assertIn("/x/signal_logs", msg)

    def test_explain_when_files_exist_but_are_empty(self):
        info = {"logged_contracts": 0, "resolved_trades": 0, "still_open": 0, "excluded_other": {}, "status_counts": {},
                "sources": {"log_dir": "/x", "tracker_found": True, "daily_files": 2}}
        self.assertIn("hold no triggers yet", bg.explain(info))

    def test_explain_names_the_exclusion_reasons(self):
        trades, _, info = load([row(alert_id="1", contract="C 1", lot_size=None), row(alert_id="2", contract="C 2", status="ACTIVE", realized_r=0.0)], lots={})
        msg = bg.explain(info)
        self.assertIn("1 with no lot size could be found", msg)

    def test_explain_with_finished_trades_mentions_open_ones(self):
        _, _, info = load([row(alert_id="1", contract="C 1"), row(alert_id="2", contract="C 2", status="ACTIVE", realized_r=0.0)])
        self.assertEqual(bg.explain(info), "1 finished Gamma trades, 1 still open (not counted).")

    def test_explain_reports_a_pdf_failure(self):
        _, _, info = load([row()])
        self.assertIn("PDF could not be written: boom", bg.explain(info, pdf_error="boom"))


class Files(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.logs = os.path.join(self.root, "signal_logs")
        os.makedirs(self.logs)
        self._old = (gel.LOG_DIR, gtt.SIGNAL_LOGS, gtt.TRACKER_PATH, bg.LOG_DIR)
        gel.LOG_DIR = bg.LOG_DIR = self.logs
        gtt.SIGNAL_LOGS = gtt.Path(self.logs)
        gtt.TRACKER_PATH = gtt.Path(self.logs) / bg.TRACKER_FILENAME
        os.environ.pop("GAMMA_TRADE_TRACKER_XLSX", None)

    def tearDown(self):
        gel.LOG_DIR, gtt.SIGNAL_LOGS, gtt.TRACKER_PATH, bg.LOG_DIR = self._old
        shutil.rmtree(self.root, ignore_errors=True)

    @staticmethod
    def alert(i, **over):
        day = datetime(2026, 9, 24, 9, 40) + timedelta(minutes=10 * i)
        a = {"alert_id": f"ALT_{i}", "symbol": "RELIANCE", "option_type": "CE", "strike": 1300 + i, "expiry": "2026-10-27", "dte": 5,
             "contract": f"RELIANCE 2026-10-27 {1300 + i} CE", "fyers_symbol": f"NSE:RELIANCE26OCT{1300 + i}CE", "security_id": f"S{i}",
             "lot_size": 250, "entry_price": 20.0, "stop_loss": 15.0, "trailing_sl": 15.0, "target_1": 28.0, "target_2": 34.0,
             "risk_reward": "1:1.6 to 1:2.8", "spot_cmp": 1300.0, "trigger_candle": "5m_CONFIRMED",
             "metrics": {"oi_drop_prior_pct": 1.5, "volume_expansion_ratio": 2.2, "price_lift_from_base_pct": 3.1},
             "status": "ACTIVE", "highest_ltp": 20.0, "lowest_ltp": 20.0, "mfe_pct": 0.0, "mae_pct": 0.0, "realized_r": 0.0,
             "exit_price": None, "exit_time_ist": None, "timestamp_ist": day.strftime("%Y-%m-%d %H:%M:%S IST")}
        a.update(over)
        return a

    def finish(self, a, status, r, minutes=30, **extra):
        t = datetime.strptime(a["timestamp_ist"][:19], "%Y-%m-%d %H:%M:%S") + timedelta(minutes=minutes)
        a.update(status=status, realized_r=r, exit_time_ist=t.strftime("%Y-%m-%d %H:%M:%S IST"), **extra)
        return a

    def log_daily(self, *alerts):
        for a in alerts:
            os.makedirs(os.path.join(self.logs, a["timestamp_ist"][:10]), exist_ok=True)
            gel.log_new_trigger(a)

    def test_end_to_end_with_the_real_logger_and_tracker(self):
        a0 = self.finish(self.alert(0), "STOPPED_OUT", -1.0, sl_hit_at_ist="x")
        a1 = self.finish(self.alert(1), "TARGET_2_HIT", 2.8, t2_hit_at_ist="2026-09-24 10:10:00 IST")
        a2 = self.alert(2)                                                     # still open
        self.log_daily(a0, a1, a2)
        tracker = gtt.GammaTradeTracker(gtt.TRACKER_PATH)
        for a in (a0, a1, a2):
            tracker.record_alert(a)
        tracker.sync_alerts([a0, a1, a2])
        trades, excluded, info = bg.load_gamma_trades()
        self.assertEqual((len(trades), info["still_open"], info["logged_contracts"]), (2, 1, 3))
        self.assertEqual(sorted(t["pnl"] for t in trades), [-1250.0, 3500.0])     # 250 x 5 x (-1R, +2.8R)
        self.assertEqual({t["qty"] for t in trades}, {250})                       # lot size came from the daily file, the tracker has none
        self.assertEqual(trades[0]["oi_drop_pct"], 1.5)                           # trigger metrics merged in from the daily file

    def test_daily_files_alone_are_enough_when_there_is_no_tracker(self):
        a0 = self.finish(self.alert(0), "TARGET_2_HIT", 2.8, t2_hit_at_ist="2026-09-24 10:10:00 IST")
        self.log_daily(a0)
        a0["status"] = "TARGET_2_HIT"
        gel.sync_alert_outcomes([a0])
        trades, _, _ = bg.load_gamma_trades()
        self.assertEqual(len(trades), 1)

    def test_a_contract_that_triggered_twice_is_one_trade(self):
        first = self.finish(self.alert(0), "STOPPED_OUT", -1.0, sl_hit_at_ist="x")
        again = self.alert(5, contract=first["contract"], strike=first["strike"], alert_id="ALT_AGAIN")
        again["timestamp_ist"] = "2026-09-25 09:50:00 IST"
        self.log_daily(first, again)
        gel.sync_alert_outcomes([first])
        trades, _, info = bg.load_gamma_trades()
        self.assertEqual((len(trades), info["logged_contracts"]), (1, 1))

    def test_tracker_still_open_but_daily_file_already_finished_takes_the_finish(self):
        a = self.finish(self.alert(0), "TARGET_2_HIT", 2.8, t2_hit_at_ist="2026-09-24 10:10:00 IST")
        self.log_daily(a)
        gel.sync_alert_outcomes([a])
        tracker = gtt.GammaTradeTracker(gtt.TRACKER_PATH)
        still_open = dict(a, status="ACTIVE", realized_r=0.0, exit_time_ist=None)
        tracker.record_alert(still_open)
        trades, _, _ = bg.load_gamma_trades()
        self.assertEqual((len(trades), trades[0]["pnl"]), (1, 3500.0))

    def test_no_files_means_no_trades_not_an_error(self):
        trades, excluded, info = bg.load_gamma_trades()
        self.assertEqual((trades, excluded, info["logged_contracts"], info["status_counts"]), ([], 0, 0, {}))
        self.assertEqual(info["sources"], {"log_dir": self.logs, "tracker_found": False, "daily_files": 0})

    def test_archived_files_are_ignored(self):
        # Archives hold a DIFFERENT trade (B). If the reader picked them up, B would show as a second contract.
        b = self.finish(self.alert(7), "TARGET_2_HIT", 2.8, t2_hit_at_ist="2026-09-24 11:10:00 IST")
        self.log_daily(b)
        live_file, _ = gel._today_path()                 # the daily logger files rows under the day it runs, not the alert's timestamp
        day_dir = os.path.dirname(live_file)
        for junk in ("gamma_blast_2026-09-24_pre-update.xlsx", "gamma_blast_2026-09-24_corrupted_101010.xlsx"):
            shutil.copy(live_file, os.path.join(day_dir, junk))
        os.remove(live_file)
        a = self.finish(self.alert(0), "STOPPED_OUT", -1.0, sl_hit_at_ist="x")
        self.log_daily(a)
        gel.sync_alert_outcomes([a])
        trades, _, info = bg.load_gamma_trades()
        self.assertEqual((info["logged_contracts"], [t["contract"] for t in trades]), (1, [a["contract"]]))

    def test_the_pdf_is_written_separately_with_the_gamma_title(self):
        from screener import backtest_signal_pnl as eng, daily_backtest as db
        old = (eng.LOG_DIR, db.LOG_DIR)
        eng.LOG_DIR = db.LOG_DIR = self.logs
        try:
            alerts = [self.finish(self.alert(i), "TARGET_2_HIT" if i % 2 else "STOPPED_OUT", 2.8 if i % 2 else -1.0,
                                  sl_hit_at_ist="2026-09-24 10:30:00 IST", t2_hit_at_ist="2026-09-24 10:30:00 IST") for i in range(6)]
            self.log_daily(*alerts)
            gel.sync_alert_outcomes(alerts)
            out = bg.run_gamma_cycle("2026-10-03")
        finally:
            eng.LOG_DIR, db.LOG_DIR = old
        self.assertIsNone(out["pdf_error"])
        self.assertEqual(os.path.basename(out["pdf"]), "gamma_blast_2026-10-03.pdf")
        self.assertEqual(out["summary"]["total_trades"], 6)
        from pypdf import PdfReader
        text = "\n".join(p.extract_text() for p in PdfReader(out["pdf"]).pages)
        self.assertIn("Gamma Blast Strategy", text)
        self.assertNotIn("Signal P&L Backtest", text)

    def test_run_gamma_now_fills_only_the_gamma_fields_and_does_not_fake_a_full_cycle(self):
        from screener import backtest_signal_pnl as eng, daily_backtest as db
        old = (eng.LOG_DIR, db.LOG_DIR, dict(db._last_run))
        eng.LOG_DIR = db.LOG_DIR = self.logs
        try:
            alerts = [self.finish(self.alert(i), "TARGET_2_HIT" if i % 2 else "STOPPED_OUT", 2.8 if i % 2 else -1.0,
                                  sl_hit_at_ist="2026-09-24 10:30:00 IST", t2_hit_at_ist="2026-09-24 10:30:00 IST") for i in range(4)]
            self.log_daily(*alerts)
            gel.sync_alert_outcomes(alerts)
            db._last_run.update(started_at=None, stock_pdf="keep-me", gamma_pdf=None, gamma_summary=None, gamma_message=None)
            got = db.run_gamma_now()
            last = db.get_last_run()
        finally:
            eng.LOG_DIR, db.LOG_DIR = old[0], old[1]
            db._last_run.clear(); db._last_run.update(old[2])
        self.assertTrue(got["pdf"] and os.path.exists(got["pdf"]))
        self.assertEqual((last["gamma_pdf"], last["gamma_summary"]["total_trades"]), (got["pdf"], 4))
        self.assertIn("4 finished Gamma trades", last["gamma_message"])
        self.assertIsNone(last["started_at"])                      # a Gamma-only run must never make the tab think a full cycle ran
        self.assertEqual(last["stock_pdf"], "keep-me")             # and must not touch the Sniper fields

    def test_nothing_resolved_gives_empty_values_and_no_pdf(self):
        out = bg.run_gamma_cycle("2026-10-03")
        self.assertEqual((out["pdf"], out["summary"], out["equity_curve"], out["recent_trades"]), (None, None, None, None))
        self.assertIn("No Gamma log files found", out["message"])


if __name__ == "__main__":
    unittest.main()
