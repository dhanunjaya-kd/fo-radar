import unittest

from screener import pattern_backtest as pb
from screener.tests.test_chart_patterns import build

# flat 100-bar prefix helpers: arrays long enough for a 40-bar horizon
def arrays(prices, wick=0.2):
    c = list(prices)
    o = [c[0]] + c[:-1]
    h = [max(a, b) + wick for a, b in zip(o, c)]
    l = [min(a, b) - wick for a, b in zip(o, c)]
    return h, l, c


class Simulate(unittest.TestCase):
    def setUp(self):
        self.base = [100.0] * 5                           # entry bar index 4, close 100

    def test_bullish_target_first(self):
        h, l, c = arrays(self.base + [101, 103, 106, 110] + [110] * 40)
        r = pb.simulate("Bullish", 4, trigger=99.0, target=105.0, stop=95.0, h=h, l=l, c=c)
        self.assertEqual((r["outcome"], r["bars"]), ("target", 3))

    def test_bearish_stop_first(self):
        h, l, c = arrays(self.base + [101, 104, 108] + [108] * 45)
        r = pb.simulate("Bearish", 4, trigger=101.0, target=90.0, stop=105.0, h=h, l=l, c=c)
        self.assertEqual(r["outcome"], "stop")

    def test_same_bar_touching_both_counts_as_stop(self):
        h, l, c = arrays(self.base + [100] + [100] * 45)
        h[5], l[5] = 106.0, 94.0
        r = pb.simulate("Bullish", 4, trigger=99.0, target=105.0, stop=95.0, h=h, l=l, c=c)
        self.assertEqual(r["outcome"], "stop")

    def test_timeout_when_nothing_is_hit_over_the_full_horizon(self):
        h, l, c = arrays(self.base + [100] * 60)
        self.assertEqual(pb.simulate("Bullish", 4, 99.0, 110.0, 90.0, h, l, c)["outcome"], "timeout")

    def test_unresolved_when_history_ends_first(self):
        h, l, c = arrays(self.base + [100] * 10)
        self.assertIsNone(pb.simulate("Bullish", 4, 99.0, 110.0, 90.0, h, l, c))

    def test_entry_already_past_target_is_skipped(self):
        h, l, c = arrays([100.0] * 5 + [100] * 50)
        self.assertIsNone(pb.simulate("Bullish", 4, 90.0, 99.0, 80.0, h, l, c))

    def test_pullback_and_double_height(self):
        path = self.base + [98, 103, 112, 125] + [125] * 40
        h, l, c = arrays(path)
        r = pb.simulate("Bullish", 4, trigger=99.0, target=105.0, stop=90.0, h=h, l=l, c=c)
        self.assertTrue(r["pullback"])                     # dipped to the trigger within 10 bars
        self.assertTrue(r["double"])                       # ran >= 2 x the 6-point height


class WalkForward(unittest.TestCase):
    def test_finds_a_confirmed_double_top_without_peeking_and_scores_it(self):
        # prefix with an uptrend + double top + break down, then a continued fall to the target
        pts = [(0, 60), (80, 80), (115, 100), (127, 90), (139, 100), (150, 85), (185, 70), (230, 66)]
        o, h, l, c, v = build(pts, noise=0.5, seed=1)
        inst = pb.instances("TEST", o, h, l, c, v)
        dts = [x for x in inst if x["name"] == "Double Top"]
        self.assertTrue(dts, [x["name"] for x in inst])
        self.assertEqual(dts[0]["direction"], "Bearish")
        self.assertEqual(dts[0]["outcome"], "target")      # it kept falling well past the measured move
        self.assertLessEqual(dts[0]["entry_i"] - dts[0]["break_i"], pb.FRESH)

    def test_no_instances_when_history_is_too_short(self):
        o, h, l, c, v = build([(0, 100), (80, 120)], noise=0.3)
        self.assertEqual(pb.instances("S", o, h, l, c, v), [])


class Aggregate(unittest.TestCase):
    def test_rates_by_pattern_family_and_overall(self):
        mk = lambda out, bars=None: {"name": "Double Top", "direction": "Bearish", "family": "Reversal", "outcome": out, "bars": bars, "pullback": True, "double": False}
        items = [mk("target", 10), mk("target", 20), mk("stop"), mk("timeout")]
        r = pb.aggregate(items)
        s = r["Double Top|Bearish"]
        self.assertEqual((s["n"], s["hit_target"], s["hit_stop"], s["timeout"]), (4, 0.5, 0.25, 0.25))
        self.assertEqual(s["median_bars_to_target"], 20)
        self.assertEqual(r["family:Reversal|Bearish"]["n"], 4)
        self.assertEqual(r["all"]["n"], 4)
        self.assertEqual(pb.aggregate([]), {})


if __name__ == "__main__":
    unittest.main()
