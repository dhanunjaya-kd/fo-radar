import unittest

from screener.scanner_levels import range_setup


def _flat(n=20, hi=110.0, lo=100.0):
    return [(105.0, hi, lo, 105.0)] * n


class RangeSetup(unittest.TestCase):
    def test_bullish_levels_and_rr(self):
        s = range_setup(_flat(), 108.0, "BULLISH", atr=4.0)
        self.assertEqual((s["breakout"], s["stop"], s["target"]), (110.0, 106.0, 120.0))   # stop = 110-4, target = 110+10
        self.assertEqual(s["rr"], 2.5)                                                       # 10 / 4
        self.assertEqual(s["status"], "NEAR")                                                # 0.5 ATR under the trigger

    def test_tall_range_gets_a_wider_stop_than_one_atr(self):
        # height 40, ATR 2 -> stop distance floor is 35% of 40 = 14, not 2; R:R = 40/14
        s = range_setup(_flat(hi=140, lo=100), 135.0, "BULLISH", atr=2.0)
        self.assertEqual((s["breakout"], s["stop"], s["target"]), (140.0, 126.0, 180.0))
        self.assertEqual(s["rr"], 2.9)

    def test_bullish_stop_never_below_range_low(self):
        s = range_setup(_flat(hi=102, lo=100), 101.0, "BULLISH", atr=8.0)
        self.assertEqual(s["stop"], 100.0)

    def test_bearish_mirrors(self):
        s = range_setup(_flat(), 102.0, "BEARISH", atr=4.0)
        self.assertEqual((s["breakout"], s["stop"], s["target"]), (100.0, 104.0, 90.0))
        self.assertEqual(s["status"], "NEAR")

    def test_broke_out_and_watching(self):
        self.assertEqual(range_setup(_flat(), 111.0, "BULLISH", atr=4.0)["status"], "BROKE_OUT")
        self.assertEqual(range_setup(_flat(), 99.0, "BEARISH", atr=4.0)["status"], "BROKE_OUT")
        self.assertEqual(range_setup(_flat(), 101.0, "BULLISH", atr=4.0)["status"], "WATCHING")

    def test_pct_vs_trigger(self):
        self.assertEqual(range_setup(_flat(), 112.2, "BULLISH", atr=4.0)["pct_vs_trigger"], 2.0)

    def test_neutral_has_range_but_no_levels(self):
        s = range_setup(_flat(), 105.0, "NEUTRAL", atr=4.0)
        self.assertEqual((s["range_high"], s["range_low"]), (110.0, 100.0))
        self.assertIsNone(s["breakout"])
        self.assertIsNone(s["rr"])

    def test_uses_only_the_lookback_window(self):
        old_spike = [(200.0, 300.0, 50.0, 200.0)] + _flat(20)
        s = range_setup(old_spike, 105.0, "BULLISH", atr=4.0)
        self.assertEqual(s["range_high"], 110.0)

    def test_not_enough_data_or_flat_range_returns_none(self):
        self.assertIsNone(range_setup(_flat(4), 105.0, "BULLISH", atr=4.0))
        self.assertIsNone(range_setup([(1, 1, 1, 1)] * 20, 1.0, "BULLISH", atr=1.0))
        self.assertIsNone(range_setup(_flat(), None, "BULLISH", atr=4.0))

    def test_missing_atr_gives_range_only(self):
        s = range_setup(_flat(), 108.0, "BULLISH", atr=None)
        self.assertIsNone(s["breakout"])


if __name__ == "__main__":
    unittest.main()
