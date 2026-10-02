import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from screener import pattern_scanner as ps
from screener.tests.test_chart_patterns import build


def series(points, **kw):
    o, h, l, c, v = build(points, **kw)
    t0 = datetime(2026, 6, 1)
    ts = [(t0 + timedelta(days=i)).timestamp() for i in range(len(c))]
    return o, h, l, c, v, ts


DOUBLE_TOP = [(0, 80), (35, 100), (47, 90), (59, 100), (70, 85)]
FLAT = [(0, 100), (80, 100)]


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        p = patch.object(ps, "RUNTIME_DIR", self.tmp)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        ps._state.clear()
        ps._threads.clear()

    def test_payload_is_drawable_and_window_relative(self):
        s = series(DOUBLE_TOP)
        items = ps.payloads_for_symbol("TEST", *s)
        p = next(x for x in items if x["name"] == "Double Top")
        n_window = len(p["candles"])
        self.assertLess(n_window, len(s[3]) + 1)
        self.assertTrue(all(0 <= m["x"] < n_window for m in p["markers"]))
        self.assertTrue(all(0 <= ln["x1"] <= ln["x2"] <= n_window for ln in p["lines"]))
        self.assertEqual(p["last_close"], round(s[3][-1], 2))
        self.assertIsNotNone(p["end_date"])
        json.dumps(items)                                             # must be JSON-serialisable as is

    def test_short_history_is_distinguished_from_nothing_found(self):
        short = series([(0, 100), (30, 101)])
        self.assertIsNone(ps.payloads_for_symbol("S", *short))
        self.assertEqual(ps.payloads_for_symbol("F", *series(FLAT, noise=0.05)), [])

    def test_run_scan_counts_persists_and_reloads(self):
        data = {"AAA": series(DOUBLE_TOP), "BBB": series(FLAT, noise=0.05), "CCC": series([(0, 100), (30, 101)]), "DDD": None}
        st = ps.run_scan("test", list(data), lambda s: data[s])
        self.assertEqual((st["total"], st["scanned"], st["failed"], st["skipped_short"]), (4, 4, 1, 1))
        self.assertEqual(st["state"], "done")
        self.assertEqual(st["with_patterns"], 1)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "chart_patterns_test.json")))
        ps._state.clear()                                             # simulate a restart
        self.assertEqual(ps.status("test")["state"], "done")
        self.assertTrue(any(p["symbol"] == "AAA" for p in ps.patterns("test")))
        self.assertNotIn("patterns", ps.status("test"))               # status stays small

    def test_scan_measures_base_rates_and_past_instances(self):
        from screener import pattern_backtest as pb
        pts = [(0, 60), (80, 80), (115, 100), (127, 90), (139, 100), (150, 85), (185, 70), (230, 66)]
        data = {"AAA": series(pts)}
        st = ps.run_scan("br", ["AAA"], lambda s: data[s])
        self.assertGreaterEqual(st["instance_count"], 1)
        self.assertIn("Double Top|Bearish", ps.rates("br"))
        self.assertEqual(ps.rates("br")["Double Top|Bearish"]["hit_target"], 1.0)
        self.assertTrue(any(x["name"] == "Double Top" and x["outcome"] == "target" for x in ps.past("br", "AAA")))
        self.assertNotIn("instances", ps.status("br"))
        self.assertNotIn("rates", ps.status("br"))
        ps._state.clear()                                             # and it survives a restart
        self.assertIn("Double Top|Bearish", ps.rates("br"))
        self.assertEqual(ps.past("br", "ZZZ"), [])

    def test_relaxed_returns_weaker_candidates_flagged_below_bar(self):
        s = series([(0, 80), (35, 100), (47, 91), (59, 98.4), (70, 88)], noise=0.7)
        strict = ps.payloads_for_symbol("T", *s) or []
        relaxed = ps.payloads_for_symbol("T", *s, relaxed=True) or []
        self.assertGreaterEqual(len(relaxed), len(strict))
        self.assertTrue(all(not p["below_bar"] for p in strict))

    def test_history_exception_counts_as_failed_not_crash(self):
        def boom(sym):
            raise RuntimeError("429")
        st = ps.run_scan("t2", ["X", "Y"], boom)
        self.assertEqual((st["failed"], st["scanned"]), (2, 2))

    def test_scan_waits_while_rate_limited(self):
        waits = []
        flags = iter([True, True, False])
        ps.run_scan("t3", ["X"], lambda s: None, should_pause=lambda: next(flags, False), sleep=lambda s: waits.append(s))
        self.assertEqual(waits, [3, 3])

    def test_never_scanned_universe(self):
        self.assertEqual(ps.status("nope")["state"], "never")
        self.assertEqual(ps.patterns("nope"), [])

    def test_single_flight(self):
        import threading
        gate = threading.Event()
        ok, _ = ps.start_scan("u1", ["A"], lambda s: (gate.wait(5) and None))
        self.assertTrue(ok)
        ok2, reason = ps.start_scan("u2", ["B"], lambda s: None)
        self.assertFalse(ok2)
        self.assertIn("already running", reason)
        gate.set()
        ps._threads["u1"].join(5)


def P(**kw):
    base = {"symbol": "AAA", "company": "Alpha Ltd", "family": "Reversal", "direction": "Bearish", "status": "Forming",
            "quality": "Strong", "score": 80, "bars_ago": 3, "volume_confirmed": False}
    base.update(kw)
    return base


class QueryTests(unittest.TestCase):
    def test_filters(self):
        items = [P(), P(symbol="BBB", family="Range", direction="Bullish", quality="Fair", score=62, bars_ago=40),
                 P(symbol="CCC", status="Confirmed", quality="Textbook", score=92, volume_confirmed=True, bars_ago=1)]
        q = lambda **kw: [p["symbol"] for p in ps.query(items, **kw)]
        self.assertEqual(q(family="Range"), ["BBB"])
        self.assertEqual(q(direction="Bearish"), ["CCC", "AAA"])
        self.assertEqual(q(quality="Strong"), ["CCC", "AAA"])
        self.assertEqual(q(quality="Textbook"), ["CCC"])
        self.assertEqual(q(within=10), ["CCC", "AAA"])
        self.assertEqual(q(volume=True), ["CCC"])
        self.assertEqual(q(status="Confirmed"), ["CCC"])
        self.assertEqual(q(text="alpha"), ["CCC", "AAA", "BBB"])
        self.assertEqual(q(text="bbb"), ["BBB"])

    def test_sorting(self):
        items = [P(symbol="OLD", score=95, bars_ago=60), P(symbol="NEW", score=70, bars_ago=0), P(symbol="MID", score=85, bars_ago=10)]
        self.assertEqual([p["symbol"] for p in ps.query(items, sort="recent")], ["NEW", "MID", "OLD"])
        self.assertEqual([p["symbol"] for p in ps.query(items, sort="cleanest")], ["OLD", "MID", "NEW"])
        self.assertEqual(ps.query(items)[0]["symbol"], "MID")        # composite: clean AND fresh beats merely clean

    def test_facets(self):
        f = ps.facets([P(), P(family="Range", direction="Bullish", status="Confirmed")])
        self.assertEqual(f["family"], {"Reversal": 1, "Range": 1})
        self.assertEqual(f["status"], {"Forming": 1, "Confirmed": 1})


if __name__ == "__main__":
    unittest.main()
