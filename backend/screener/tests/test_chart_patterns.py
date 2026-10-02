"""
Oct 2 2026: tests for chart_patterns.py -- synthetic price paths with a known shape (+ noise),
mirror-symmetry checks, status transitions, and a random-walk baseline so the quality
labels are at least calibrated against pattern-shaped noise.   python -m unittest screener.tests.test_chart_patterns
"""
import math
import random
import unittest

from screener import chart_patterns as cp


def build(points, noise=0.5, seed=1):
    """points: [(bar, price)] linearly interpolated; returns o, h, l, c, v."""
    rnd = random.Random(seed)
    path = []
    for (b0, p0), (b1, p1) in zip(points, points[1:]):
        path += [p0 + (p1 - p0) * (b - b0) / (b1 - b0) for b in range(b0, b1)]
    path.append(points[-1][1])
    c = [p + rnd.gauss(0, noise) for p in path]
    o = [c[0]] + c[:-1]
    h = [max(a, b) + abs(rnd.gauss(0, noise * 0.6)) for a, b in zip(o, c)]
    l = [min(a, b) - abs(rnd.gauss(0, noise * 0.6)) for a, b in zip(o, c)]
    v = [1e6 * (1 + rnd.random() * 0.2) for _ in c]
    return o, h, l, c, v


def mirror(o, h, l, c, v, pivot=200.0):
    f = lambda xs: [pivot - x for x in xs]
    return f(o), f(l), f(h), f(c), v


def names(res):
    return [(p["name"], p["direction"]) for p in res]


def best(res, name):
    return next((p for p in res if p["name"] == name), None)


class Primitives(unittest.TestCase):
    def test_zigzag_alternates_and_respects_threshold(self):
        o, h, l, c, v = build([(0, 80), (30, 100), (45, 88), (60, 101)], noise=0.2)
        piv = cp.zigzag(h, l, 5.0)
        self.assertEqual([p["t"] for p in piv], ["L", "H", "L"][: len(piv)] if piv[0]["t"] == "L" else ["H", "L", "H"][: len(piv)])
        self.assertTrue(all(a["t"] != b["t"] for a, b in zip(piv, piv[1:])))
        self.assertTrue(all(a["i"] < b["i"] for a, b in zip(piv, piv[1:])))     # strictly increasing, no duplicate bar

    def test_quadratic_fit_recovers_a_parabola(self):
        ys = [100 + 20 * ((i - 25) / 25) ** 2 for i in range(51)]
        a, b, c0, r2 = cp._quad_fit(ys)
        self.assertGreater(a, 0)
        self.assertGreater(r2, 0.999)
        self.assertAlmostEqual(-b / (2 * a), 0.5, places=2)

    def test_too_short_or_flat_series_returns_nothing(self):
        self.assertEqual(cp.detect([1] * 30, [1] * 30, [1] * 30, [1] * 30), [])
        self.assertEqual(cp.detect([5] * 80, [5] * 80, [5] * 80, [5] * 80), [])


class Reversal(unittest.TestCase):
    def test_double_top_and_its_mirror(self):
        s = build([(0, 80), (35, 100), (47, 90), (59, 100), (70, 88)])
        r = cp.detect(*s)
        p = best(r, "Double Top")
        self.assertIsNotNone(p, names(r))
        self.assertEqual((p["direction"], p["family"]), ("Bearish", "Reversal"))
        self.assertLess(p["target"], p["trigger"] < p["stop"] and p["trigger"])   # target below the neckline, stop above the tops
        rb = best(cp.detect(*mirror(*s)), "Double Bottom")
        self.assertIsNotNone(rb)
        self.assertEqual(rb["direction"], "Bullish")
        self.assertEqual([m["label"] for m in rb["markers"]], ["Bottom", "Bottom"])    # labels are mirrored too
        self.assertGreater(rb["target"], rb["trigger"])
        self.assertLess(rb["stop"], rb["trigger"])

    def test_triple_top(self):
        r = cp.detect(*build([(0, 80), (30, 100), (40, 90), (50, 100), (60, 90), (70, 100), (82, 89)]))
        self.assertIsNotNone(best(r, "Triple Top"), names(r))

    def test_head_and_shoulders_and_inverse(self):
        s = build([(0, 80), (25, 100), (35, 90), (50, 112), (62, 90), (75, 101), (88, 88)])
        p = best(cp.detect(*s), "Head & Shoulders")
        self.assertIsNotNone(p)
        self.assertGreater(p["score"], 75)
        self.assertEqual(len([m for m in p["markers"] if m["label"] in ("LS", "Head", "RS")]), 3)
        self.assertIsNotNone(best(cp.detect(*mirror(*s)), "Inverse Head & Shoulders"))

    def test_status_confirmed_vs_forming(self):
        confirmed = best(cp.detect(*build([(0, 80), (35, 100), (47, 90), (59, 100), (70, 85)])), "Double Top")
        forming = best(cp.detect(*build([(0, 80), (35, 100), (47, 90), (59, 100), (68, 94)])), "Double Top")
        self.assertEqual(confirmed["status"], "Confirmed")
        self.assertIsNotNone(forming)
        self.assertEqual(forming["status"], "Forming")

    def test_failed_when_price_recovers_above_the_tops(self):
        r = cp.detect(*build([(0, 80), (35, 100), (47, 90), (59, 100), (66, 87), (75, 104)]))
        p = best(r, "Double Top")
        self.assertTrue(p is None or p["status"] == "Failed", names(r))


class Continuation(unittest.TestCase):
    def test_ascending_triangle_and_mirror(self):
        s = build([(0, 50), (25, 80), (35, 65), (45, 80), (55, 70), (65, 80), (75, 75), (85, 80), (90, 81)])
        p = best(cp.detect(*s), "Ascending Triangle")
        self.assertIsNotNone(p)
        self.assertEqual((p["direction"], p["family"]), ("Bullish", "Continuation"))
        self.assertGreater(p["target"], p["trigger"])
        self.assertIsNotNone(best(cp.detect(*mirror(*s)), "Descending Triangle"))

    def test_bear_flag_and_mirror(self):
        s = build([(0, 100), (40, 100), (55, 66), (60, 74), (65, 70), (70, 78), (75, 74), (80, 82)], noise=0.7)
        p = best(cp.detect(*s), "Bear Flag")
        self.assertIsNotNone(p)
        self.assertEqual(p["status"], "Forming")
        self.assertTrue(any(ln["kind"] == "pole" for ln in p["lines"]))
        self.assertLess(p["target"], p["trigger"])
        pb = best(cp.detect(*mirror(*s)), "Bull Flag")
        self.assertIsNotNone(pb)
        self.assertGreater(pb["target"], pb["trigger"])


class RangeAndWedge(unittest.TestCase):
    def test_rectangle_is_range_family_with_bias(self):
        r = cp.detect(*build([(0, 70), (25, 90), (35, 78), (45, 90), (55, 78), (65, 90), (75, 78), (85, 90)]))
        p = best(r, "Rectangle")
        self.assertIsNotNone(p, names(r))
        self.assertEqual(p["family"], "Range")
        self.assertTrue(p.get("unresolved"))

    def test_ascending_channel_has_no_levels(self):
        r = cp.detect(*build([(0, 60), (20, 72), (30, 64), (45, 80), (55, 72), (70, 88), (80, 80), (90, 96)]))
        p = best(r, "Ascending Channel")
        self.assertIsNotNone(p, names(r))
        self.assertEqual(p["direction"], "Neutral")
        self.assertIsNone(p["target"])
        self.assertIsNone(p["stop"])

    def test_rising_wedge_and_mirror_falling_wedge(self):
        s = build([(0, 60), (25, 90), (37, 80), (52, 100), (62, 92), (75, 106), (85, 100), (95, 101)])
        p = best(cp.detect(*s), "Rising Wedge")
        self.assertIsNotNone(p)
        self.assertEqual(p["direction"], "Bearish")
        self.assertIsNotNone(best(cp.detect(*mirror(*s)), "Falling Wedge"))


class Curves(unittest.TestCase):
    def test_rounded_top_and_bottom(self):
        s = build([(0, 80)] + [(i, 130 - 0.025 * (i - 45) ** 2) for i in range(5, 86, 5)] + [(90, 80)], noise=0.8)
        p = best(cp.detect(*s), "Rounded Top")
        self.assertIsNotNone(p)
        self.assertTrue(p["curve"])
        self.assertIsNotNone(best(cp.detect(*mirror(*s)), "Rounded Bottom"))

    def test_cup_and_handle(self):
        pts = [(0, 92), (10, 120)] + [(i, 100 + 20 / 35 ** 2 * (i - 45) ** 2) for i in range(15, 80, 5)] + [(80, 120), (88, 114), (96, 119), (100, 120)]
        r = cp.detect(*build(pts, noise=0.6))
        p = best(r, "Cup & Handle")
        self.assertIsNotNone(p, names(r))
        self.assertEqual((p["direction"], p["family"]), ("Bullish", "Curve & Cup"))
        self.assertNotIn("Double Top", [x["name"] for x in r])        # the equal rims are not also reported as a double top


class Output(unittest.TestCase):
    def test_every_pattern_is_drawable_and_well_formed(self):
        s = build([(0, 80), (25, 100), (35, 90), (50, 112), (62, 90), (75, 101), (88, 88)])
        for p in cp.detect(*s):
            self.assertIn(p["family"], cp.FAMILIES)
            self.assertIn(p["status"], ("Forming", "Confirmed", "Failed"))
            self.assertIn(p["quality"], ("Fair", "Strong", "Textbook"))
            self.assertGreaterEqual(p["score"], cp.MIN_SCORE)
            self.assertTrue(p["lines"] or p.get("curve"))
            for ln in p["lines"]:
                self.assertTrue(0 <= ln["x1"] <= ln["x2"] < len(s[3]) + 1)
            self.assertGreaterEqual(p["bars_ago"], 0)

    def test_stop_is_never_closer_than_one_atr(self):
        s = build([(0, 110), (25, 80), (35, 95), (45, 80), (55, 90), (65, 80), (75, 85), (85, 80), (90, 79)])
        for p in cp.detect(*s):
            if p["stop"] is not None and p["trigger"] is not None:
                self.assertGreaterEqual(abs(p["stop"] - p["trigger"]), p["atr"] * 0.999)

    def test_one_reading_per_stretch_of_bars(self):
        r = cp.detect(*build([(0, 70), (25, 90), (35, 78), (45, 90), (55, 78), (65, 90), (75, 78), (85, 90)]))
        for i, a_ in enumerate(r):
            for b_ in r[i + 1:]:
                self.assertLessEqual(cp._overlap(a_, b_), 0.6)


class RandomWalkBaseline(unittest.TestCase):
    """
    Calibration, not decoration: on pure random walks (no structure by construction) the
    detector must not shout. Bounds are the measured rates (n=1500: Fair+ 39%, Strong+ 12%,
    Textbook 3%) plus headroom, so a future change that makes it noisier fails here.
    """

    @staticmethod
    def walk(seed, n=100, sig=0.018):
        r = random.Random(seed)
        p, o, h, l, c, v = 100.0, [], [], [], [], []
        for _ in range(n):
            op, cl = p, p * math.exp(r.gauss(0, sig))
            o.append(op)
            h.append(max(op, cl) * (1 + abs(r.gauss(0, sig * 0.5))))
            l.append(min(op, cl) * (1 - abs(r.gauss(0, sig * 0.5))))
            c.append(cl)
            v.append(1e6 * (1 + r.random()))
            p = cl
        return o, h, l, c, v

    def test_false_positive_rates(self):
        N = 400
        fair = strong = textbook = 0
        for seed in range(N):
            qs = {p["quality"] for p in cp.detect(*self.walk(10_000 + seed))}
            fair += bool(qs)
            strong += bool(qs & {"Strong", "Textbook"})
            textbook += "Textbook" in qs
        self.assertLess(fair / N, 0.50)
        self.assertLess(strong / N, 0.20)
        self.assertLess(textbook / N, 0.06)


if __name__ == "__main__":
    unittest.main()
