"""
Oct 2 2026: tests for sniper_v3.py. Plain unittest (no Django, no Fyers,
no network) so they run anywhere:  python -m unittest screener.tests.test_sniper_v3
"""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from screener import sniper_v3 as v3


def _day(h, m, base=None):
    base = base or datetime(2026, 10, 1)
    return base.replace(hour=h, minute=m, second=0, microsecond=0)


def _candles(rows, start=(9, 15)):
    """rows: (o, h, l, c, v) tuples, 5 minutes apart from `start`."""
    t0 = _day(*start)
    return [[(t0 + timedelta(minutes=5 * i)).timestamp(), o, h, l, c, v] for i, (o, h, l, c, v) in enumerate(rows)]


OR_ROWS = [  # opening range: high 100.5, low 99.5
    (100.0, 100.5, 99.6, 100.0, 1000),
    (100.0, 100.4, 99.5, 99.8, 1000),
    (99.8, 100.2, 99.5, 99.9, 1000),
]


class DirectionalGates(unittest.TestCase):
    def test_rsi_side(self):
        self.assertTrue(v3.rsi_direction_ok("SELL", 45))
        self.assertFalse(v3.rsi_direction_ok("SELL", 55))
        self.assertTrue(v3.rsi_direction_ok("BUY", 55))
        self.assertFalse(v3.rsi_direction_ok("BUY", 45))
        self.assertTrue(v3.rsi_direction_ok("SELL", None))  # missing data is not evidence

    def test_rsi_gate_can_be_disabled(self):
        with patch.dict(v3.CONFIG, {"REQUIRE_DIRECTIONAL_RSI": False}):
            self.assertTrue(v3.rsi_direction_ok("SELL", 70))

    def test_buy_needs_adx_sell_does_not(self):
        with patch.dict(v3.CONFIG, {"BUY_MIN_ADX": 35}):
            self.assertFalse(v3.adx_gate_ok("BUY", 30))
            self.assertTrue(v3.adx_gate_ok("BUY", 36))
            self.assertTrue(v3.adx_gate_ok("SELL", 26))
            self.assertTrue(v3.adx_gate_ok("BUY", None))

    def test_master_switch_off_disables_every_gate(self):
        with patch.dict(v3.CONFIG, {"ENABLED": False}):
            self.assertTrue(v3.rsi_direction_ok("SELL", 70))
            self.assertTrue(v3.adx_gate_ok("BUY", 10))
            self.assertTrue(v3.cost_to_risk_ok(5.0))
            self.assertFalse(v3.trigger_active())


class CostToRisk(unittest.TestCase):
    def test_value(self):
        # premium 8.15, SL 5.83 -> risk 2.32; spread 0.40 -> 0.172R
        self.assertAlmostEqual(v3.cost_to_risk(8.0, 8.4, 8.15, 5.83), 0.172, places=3)

    def test_unknown_inputs(self):
        self.assertIsNone(v3.cost_to_risk(None, 8.4, 8.15, 5.83))
        self.assertIsNone(v3.cost_to_risk(8.0, 8.4, 5.0, 5.0))   # zero risk
        self.assertIsNone(v3.cost_to_risk(8.4, 8.0, 8.15, 5.83))  # crossed book

    def test_gate(self):
        with patch.dict(v3.CONFIG, {"MAX_COST_TO_RISK": 0.30}):
            self.assertTrue(v3.cost_to_risk_ok(0.25))
            self.assertFalse(v3.cost_to_risk_ok(0.45))
            self.assertTrue(v3.cost_to_risk_ok(None))  # unknown passes; legacy 15% gate still applies


class RelativeRvol(unittest.TestCase):
    def test_median(self):
        self.assertEqual(v3.median([1, 3, 2]), 2)
        self.assertEqual(v3.median([1, 2, 3, 4]), 2.5)
        self.assertIsNone(v3.median([]))
        self.assertEqual(v3.median([None, 4]), 4)

    def test_relative_removes_time_of_day_effect(self):
        # at 09:23 a typical stock has done ~3% of its 20d daily average
        self.assertEqual(v3.relative_rvol(0.06, 0.03), 2.0)
        self.assertIsNone(v3.relative_rvol(0.06, None))
        self.assertIsNone(v3.relative_rvol(0.06, 0))


class Trigger(unittest.TestCase):
    def test_insufficient_candles_is_unknown_not_reject(self):
        r = v3.evaluate_trigger("SELL", _candles(OR_ROWS[:2]), 2.0)
        self.assertEqual(r["state"], "UNKNOWN")

    def test_sell_orb_breakdown(self):
        rows = OR_ROWS + [
            (99.9, 100.0, 99.4, 99.45, 1200),   # closes below OR low 99.5
            (99.45, 99.5, 99.2, 99.3, 1500),    # holds below
        ]
        r = v3.evaluate_trigger("SELL", _candles(rows), 2.0)
        self.assertEqual((r["state"], r["type"]), ("TRIGGERED", "ORB_BREAKDOWN"), r)

    def test_buy_orb_breakout_mirror(self):
        rows = [(100.0, 100.4, 99.5, 100.0, 1000), (100.0, 100.5, 99.6, 100.2, 1000), (100.2, 100.5, 99.8, 100.1, 1000),
                (100.1, 100.7, 100.0, 100.65, 1200), (100.65, 100.9, 100.5, 100.8, 1500)]
        r = v3.evaluate_trigger("BUY", _candles(rows), 2.0)
        self.assertEqual((r["state"], r["type"]), ("TRIGGERED", "ORB_BREAKOUT"), r)

    def test_wrong_side_of_vwap(self):
        rows = OR_ROWS + [(99.9, 100.6, 99.9, 100.5, 1200), (100.5, 100.8, 100.4, 100.7, 1500)]
        r = v3.evaluate_trigger("SELL", _candles(rows), 2.0)
        self.assertEqual(r["state"], "NO_TRIGGER")
        self.assertIn("wrong side", r["reason"])

    def test_extended_move_is_not_chased(self):
        rows = OR_ROWS + [(99.9, 100.0, 98.0, 98.2, 1200), (98.2, 98.3, 97.0, 97.2, 1500)]
        r = v3.evaluate_trigger("SELL", _candles(rows), 2.0)  # ~2.6 away from VWAP = 1.3 ATR
        self.assertEqual(r["state"], "NO_TRIGGER")
        self.assertIn("extended", r["reason"])

    def test_fading_volume_blocks(self):
        rows = OR_ROWS + [(99.9, 100.0, 99.4, 99.45, 300), (99.45, 99.5, 99.2, 99.3, 300), (99.3, 99.4, 99.15, 99.25, 300)]
        r = v3.evaluate_trigger("SELL", _candles(rows), 2.0)
        self.assertEqual(r["state"], "NO_TRIGGER")
        self.assertIn("fading", r["reason"])

    def test_stale_break_is_not_a_fresh_trigger(self):
        rows = OR_ROWS + [(99.9, 100.0, 99.4, 99.45, 1200)]
        rows += [(99.45, 99.5, 99.35, 99.4, 1100)] * 6    # break is now 6 candles old, drifting flat
        r = v3.evaluate_trigger("SELL", _candles(rows), 2.0)
        self.assertEqual(r["state"], "NO_TRIGGER", r)

    def test_vwap_rejection_confirmed(self):
        # no OR break; price pops up to session VWAP, rejects, then closes below the rejection low
        rows = [
            (100.0, 100.6, 99.4, 100.2, 1000),
            (100.2, 100.6, 99.8, 100.4, 1000),
            (100.4, 100.7, 99.9, 100.3, 1000),
            (100.3, 100.4, 99.9, 100.0, 1000),
            (100.0, 100.35, 99.85, 99.9, 1400),   # probes VWAP, bearish close below it
            (99.9, 99.95, 99.7, 99.75, 1500),     # confirmation: closes under the rejection low 99.85, still inside OR
        ]
        r = v3.evaluate_trigger("SELL", _candles(rows), 2.0)
        self.assertEqual((r["state"], r["type"]), ("TRIGGERED", "VWAP_REJECTION"), r)


class CandleFetch(unittest.TestCase):
    def setUp(self):
        v3._candle_cache.clear()
        self.now = _day(10, 7).replace(second=30)

    def _resp(self):
        yday = datetime(2026, 9, 30, 15, 25).timestamp()
        rows = [[yday, 1, 1, 1, 1, 1]]
        t0 = _day(9, 15)
        for i in range(12):  # 09:15 ... 10:10 starts; 10:05 and 10:10 not complete at 10:07:30
            rows.append([(t0 + timedelta(minutes=5 * i)).timestamp(), 1, 2, 0.5, 1.5, 100])
        return {"s": "ok", "candles": list(reversed(rows))}  # deliberately unsorted

    def test_only_todays_completed_candles_sorted_and_cached_per_period(self):
        calls = []

        def fake(symbol, resolution, range_from, range_to):
            calls.append((symbol, resolution))
            return self._resp()

        got = v3.fetch_session_candles("ABC", now=self.now, history_fn=fake)
        self.assertEqual(len(got), 10)                          # 09:15..10:00 inclusive
        self.assertEqual([c[0] for c in got], sorted(c[0] for c in got))
        self.assertEqual(calls, [("NSE:ABC-EQ", "5")])
        v3.fetch_session_candles("ABC", now=self.now + timedelta(seconds=40), history_fn=fake)
        self.assertEqual(len(calls), 1)                         # same 5-min period -> no new call
        v3.fetch_session_candles("ABC", now=self.now + timedelta(minutes=5), history_fn=fake)
        self.assertEqual(len(calls), 2)                         # new period -> refetch

    def test_failure_is_unknown_never_raises(self):
        def boom(*a, **k):
            raise RuntimeError("429")
        r = v3.trigger_for("ABC", "SELL", 2.0, now=self.now, history_fn=boom)
        self.assertEqual(r["state"], "UNKNOWN")
        r = v3.trigger_for("XYZ", "SELL", 2.0, now=self.now, history_fn=lambda *a, **k: {"s": "error"})
        self.assertEqual(r["state"], "UNKNOWN")


class TriggerBlocking(unittest.TestCase):
    def test_modes(self):
        no = {"state": "NO_TRIGGER"}
        with patch.dict(v3.CONFIG, {"TRIGGER_MODE": "shadow"}):
            self.assertFalse(v3.trigger_blocks(no, False))      # shadow never blocks
        with patch.dict(v3.CONFIG, {"TRIGGER_MODE": "enforce"}):
            self.assertTrue(v3.trigger_blocks(no, False))
            self.assertFalse(v3.trigger_blocks(no, True))       # held call is never kicked out by an ENTRY check
            self.assertFalse(v3.trigger_blocks({"state": "UNKNOWN"}, False))  # data gap fails open
            self.assertFalse(v3.trigger_blocks({"state": "TRIGGERED"}, False))


class Rank(unittest.TestCase):
    def test_better_inputs_rank_higher_and_components_returned(self):
        lo, _ = v3.rank_score("SELL", 26, 0.6, 0.45, None, 49)
        hi, comps = v3.rank_score("SELL", 45, 2.5, 0.05, "ORB_BREAKDOWN", 32)
        self.assertGreater(hi, lo)
        self.assertEqual(set(comps), {"adx", "rvol", "cost", "trigger", "rsi_room"})
        self.assertLessEqual(hi, 100)

    def test_rsi_room_is_directional(self):
        sell, _ = v3.rank_score("SELL", 30, 1, 0.2, None, 30)
        buy_wrong, _ = v3.rank_score("BUY", 30, 1, 0.2, None, 30)
        self.assertGreater(sell, buy_wrong)


def _sig(sym, action="SELL", sector="X", rank=50, **kw):
    return {"symbol": sym, "action": action, "sector": sector, "rank_score": rank, **kw}


CFG = dict(v3.CONFIG, SAME_DAY_LOCK=True, MAX_ACTIVE=8, MAX_ACTIVE_PER_DIRECTION=6, MAX_ACTIVE_PER_SECTOR=2,
           MAX_NEW_PER_30MIN=3, ENTRY_START_MIN=9 * 60 + 15, ENTRY_END_MIN=14 * 60, MAX_HOLD_MIN=150, MISSING_GRACE_CYCLES=1)


def _book(**over):
    return v3.SignalBook(dict(CFG, **over))


class BookTests(unittest.TestCase):
    def test_sticky_rank_churn_does_not_drop_or_duplicate(self):
        b = _book(MAX_ACTIVE=2, MAX_NEW_PER_30MIN=9)
        t = _day(10, 0)
        shown, _ = b.select([_sig("A", sector="S1", rank=60), _sig("B", sector="S2", rank=55), _sig("C", sector="S3", rank=40)], t)
        self.assertEqual({s["symbol"] for s in shown}, {"A", "B"})
        # next cycle C outranks both -- must NOT displace the active calls
        shown, dec = b.select([_sig("A", sector="S1", rank=10), _sig("B", sector="S2", rank=10), _sig("C", sector="S3", rank=99)], t + timedelta(minutes=2))
        self.assertEqual({s["symbol"] for s in shown}, {"A", "B"})
        self.assertEqual(dec["C"], "book full")

    def test_same_day_lock_after_close(self):
        b = _book(MAX_HOLD_MIN=10)
        t = _day(10, 0)
        b.select([_sig("A")], t)
        shown, dec = b.select([_sig("A")], t + timedelta(minutes=20))   # held >10 min -> closed
        self.assertEqual(shown, [])
        self.assertIn("held", dec["A"])
        shown, dec = b.select([_sig("A")], t + timedelta(minutes=25))   # fires again -> locked out
        self.assertEqual(shown, [])
        self.assertIn("locked", dec["A"])
        self.assertIsNotNone(b.precheck("A", "SELL", t + timedelta(minutes=25)))

    def test_lock_can_be_disabled(self):
        b = _book(MAX_HOLD_MIN=10, SAME_DAY_LOCK=False)
        t = _day(10, 0)
        b.select([_sig("A")], t)
        b.select([_sig("A")], t + timedelta(minutes=20))
        shown, _ = b.select([_sig("A")], t + timedelta(minutes=25))
        self.assertEqual([s["symbol"] for s in shown], ["A"])

    def test_sector_and_direction_caps(self):
        b = _book(MAX_NEW_PER_30MIN=9, MAX_ACTIVE_PER_DIRECTION=3)
        t = _day(10, 0)
        shown, dec = b.select([_sig("A", sector="Fin", rank=90), _sig("B", sector="Fin", rank=80), _sig("C", sector="Fin", rank=70),
                               _sig("D", sector="Pwr", rank=60), _sig("E", sector="Def", rank=50)], t)
        self.assertEqual({s["symbol"] for s in shown}, {"A", "B", "D"})        # 3rd Fin skipped, then SELL cap (3) hit
        self.assertIn("sector", dec["C"])
        self.assertIn("SELL cap", dec["E"])

    def test_new_call_budget_per_30_minutes(self):
        b = _book(MAX_NEW_PER_30MIN=2, MAX_ACTIVE_PER_SECTOR=9)
        t = _day(10, 0)
        shown, dec = b.select([_sig(s, sector=s, rank=r) for s, r in [("A", 9), ("B", 8), ("C", 7)]], t)
        self.assertEqual({s["symbol"] for s in shown}, {"A", "B"})
        self.assertIn("budget", dec["C"])
        shown, _ = b.select([_sig("C", sector="C")], t + timedelta(minutes=31))
        self.assertIn("C", {s["symbol"] for s in shown})

    def test_entry_window(self):
        b = _book()
        shown, dec = b.select([_sig("A")], _day(14, 30))
        self.assertEqual(shown, [])
        self.assertEqual(dec["A"], "outside entry window")
        self.assertEqual(b.precheck("A", "SELL", _day(14, 30)), "outside new-entry window")
        self.assertIsNone(b.precheck("A", "SELL", _day(10, 0)))

    def test_active_call_survives_after_entry_window_closes(self):
        b = _book()
        b.select([_sig("A")], _day(13, 50))
        shown, _ = b.select([_sig("A")], _day(14, 20))
        self.assertEqual([s["symbol"] for s in shown], ["A"])
        self.assertIsNone(b.precheck("A", "SELL", _day(14, 20)))

    def test_missing_grace_then_close(self):
        b = _book()
        t = _day(10, 0)
        b.select([_sig("A")], t)
        shown, _ = b.select([], t + timedelta(minutes=2))
        self.assertEqual([(s["symbol"], s.get("carried_over")) for s in shown], [("A", True)])
        shown, dec = b.select([], t + timedelta(minutes=4))
        self.assertEqual(shown, [])
        self.assertIn("dropped", dec["A"])

    def test_resolved_via_callback_closes_and_locks(self):
        b = _book()
        t = _day(10, 0)
        b.select([_sig("A")], t)
        shown, dec = b.select([_sig("A")], t + timedelta(minutes=3), is_resolved=lambda s, a: True)
        self.assertEqual(shown, [])
        self.assertIn("resolved", dec["A"])
        self.assertTrue(b.is_locked("A", t + timedelta(minutes=3)))

    def test_resolution_not_checked_for_just_admitted_call(self):
        b = _book()
        t = _day(10, 0)
        b.select([_sig("A")], t)   # excel row not written yet -> "no open position" must not be read as resolved
        shown, _ = b.select([_sig("A")], t + timedelta(seconds=20), is_resolved=lambda s, a: True)
        self.assertEqual([s["symbol"] for s in shown], ["A"])

    def test_resolved_flags_on_candidate(self):
        b = _book()
        t = _day(10, 0)
        b.select([_sig("A")], t)
        shown, _ = b.select([_sig("A", furthest_target_hit=3)], t + timedelta(minutes=3))
        self.assertEqual(shown, [])

    def test_trigger_required_blocks_only_new_entries(self):
        b = _book()
        t = _day(10, 0)
        shown, dec = b.select([_sig("A", trigger_state="NO_TRIGGER")], t, trigger_required=True)
        self.assertEqual(shown, [])
        shown, _ = b.select([_sig("A", trigger_state="TRIGGERED")], t, trigger_required=True)
        self.assertEqual(len(shown), 1)
        shown, _ = b.select([_sig("A", trigger_state="NO_TRIGGER")], t + timedelta(minutes=5), trigger_required=True)
        self.assertEqual(len(shown), 1)   # already active -- not kicked out

    def test_direction_flip_closes_and_locks(self):
        b = _book()
        t = _day(10, 0)
        b.select([_sig("A", "SELL")], t)
        shown, dec = b.select([_sig("A", "BUY")], t + timedelta(minutes=3))
        self.assertEqual(shown, [])
        self.assertTrue(b.is_locked("A", t))

    def test_seed_after_restart(self):
        b = _book()
        t = _day(11, 0)
        b.seed([
            {"symbol": "ACT", "action": "SELL", "exited_at": None, "created_at": t - timedelta(minutes=30), "resolved": False},
            {"symbol": "OLD", "action": "SELL", "exited_at": t - timedelta(minutes=40), "created_at": None, "resolved": False},
            {"symbol": "HIT", "action": "BUY", "exited_at": None, "created_at": None, "resolved": True},
        ], t)
        self.assertTrue(b.is_active("ACT", "SELL", t))
        self.assertTrue(b.is_locked("OLD", t))
        self.assertTrue(b.is_locked("HIT", t))
        shown, dec = b.select([_sig("ACT"), _sig("OLD"), _sig("NEW", sector="N")], t)
        self.assertEqual({s["symbol"] for s in shown}, {"ACT", "NEW"})

    def test_day_rollover_resets(self):
        b = _book(MAX_HOLD_MIN=1)
        b.select([_sig("A")], _day(10, 0))
        b.select([_sig("A")], _day(10, 30))      # closed + locked today
        shown, _ = b.select([_sig("A")], _day(10, 0, base=datetime(2026, 10, 2)))
        self.assertEqual([s["symbol"] for s in shown], ["A"])


class ExcelBridge(unittest.TestCase):
    """The book relies on two excel_logger helpers -- exercised against a real temp workbook."""

    def setUp(self):
        import shutil, tempfile
        from screener import excel_logger as el
        self.el = el
        self.tmp = tempfile.mkdtemp()
        self._p = patch.object(el, "LOG_DIR", self.tmp)
        self._p.start()
        el._row_index, el._open_positions, el._current_date, el._initialized_today = {}, {}, None, False
        self.addCleanup(lambda: (self._p.stop(), shutil.rmtree(self.tmp, ignore_errors=True)))

    def _sig(self, sym="RELIANCE", action="SELL"):
        return {"symbol": sym, "action": action, "strike": 1400, "option_symbol": f"NSE:{sym}26OCT1400PE", "grade": "A",
                "confidence": "80%", "price": 100.0, "change_percent": -1.0, "entry": 10.0, "sl": 5.0, "target1": 15.0,
                "target2": 18.0, "target3": 22.0, "quantity": 1, "risk_reward": 1.5, "oi_confirmation": "CONFIRMED",
                "sector": "T", "signal_logic_version": "v2", "expiry_date": "2026-10-27"}

    def test_new_row_is_open_then_sl_hit_marks_resolved(self):
        el = self.el
        el.sync_active_signals([self._sig()])
        self.assertFalse(el.is_signal_resolved("RELIANCE", "SELL"))      # open: must NOT read as resolved
        rows = el.get_today_book_rows()
        self.assertEqual([(r["symbol"], r["resolved"], r["exited_at"]) for r in rows], [("RELIANCE", False, None)])
        el.check_outcomes(lambda syms: {"s": "ok", "d": [{"s": "ok", "n": "NSE:RELIANCE26OCT1400PE", "v": {"lp": 4.0}}]})
        self.assertTrue(el.is_signal_resolved("RELIANCE", "SELL"))       # SL hit -> position no longer watched
        self.assertTrue(el.get_today_book_rows()[0]["resolved"])

    def test_dropped_row_still_unresolved_until_sl_or_t3(self):
        el = self.el
        el.sync_active_signals([self._sig()])
        el.sync_active_signals([])                                         # falls off the list -> exited_at set
        r = el.get_today_book_rows()[0]
        self.assertIsNotNone(r["exited_at"])
        self.assertFalse(r["resolved"])
        self.assertFalse(el.is_signal_resolved("RELIANCE", "SELL"))

    def test_unknown_symbol_is_not_resolved(self):
        self.assertFalse(self.el.is_signal_resolved("NOPE", "BUY"))


if __name__ == "__main__":
    unittest.main()
