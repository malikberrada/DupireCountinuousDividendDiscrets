import copy
import itertools
import math
import unittest
from datetime import timedelta
from fractions import Fraction as F

from certify import digest
from market import load
from pointwise.calendar_model import CalendarModel, days_between, instant
from pointwise.conditional import (
    check_ranges,
    lipschitz_at,
    normal_vanilla,
    variance_at,
)
from pointwise.gaussian import (
    BASE,
    MASS,
    check_kernel,
    density,
    normal_peak,
    propose_kernel,
)
from pointwise.identified import point, radius_seconds, target, warp_coordinate
from pointwise.pricer import Convolution
from pointwise.regularity import dupire_at_stencil
from pointwise.runner import DEFAULT_AT, PUBLISHED, market_inputs, replay


class PointwiseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = market_inputs()
        cls.panel, cls.p3, cls.poly = cls.inputs
        cls.cert = load(PUBLISHED / "certificate.json")
        cls.at = instant(DEFAULT_AT)
        cls.book = CalendarModel(cls.panel, cls.cert["models"]["reference"]["parameters"])

    def test_exact_shared_volatilities_and_clock_map(self):
        p = point(self.book, self.at, "78", "gains", ["0", "3/20", "9/20", "10"])
        self.assertEqual(p["warp_radius_seconds"], 1800)
        self.assertEqual(
            [F(w["variance_at_point"]) for w in p["target_witnesses"]],
            [0, F(9, 400), F(81, 400), 100],
        )
        for w in p["target_witnesses"]:
            r = float(F(w["clock_derivative"]))
            xs = [-1.5, -1, -0.8, -0.4, -0.001, 0, 0.001, 0.4, 0.8, 1, 1.5]
            ys = [warp_coordinate(x, r) for x in xs]
            self.assertEqual(ys[:2], xs[:2])
            self.assertEqual(ys[-2:], xs[-2:])
            self.assertEqual(warp_coordinate(0, r), 0)
            self.assertTrue(all(a < b for a, b in itertools.pairwise(ys)))
            self.assertAlmostEqual(warp_coordinate(1e-7, r) / 1e-7, r, delta=5e-6)
        for dt in self.book.closes:
            u = float(days_between(self.at, dt) * 86400 / p["warp_radius_seconds"])
            self.assertEqual(warp_coordinate(u, 2), u)

    def test_radius_separates_close_and_ex_date(self):
        t = self.at - timedelta(seconds=10)
        self.assertEqual(radius_seconds(self.book, t), 5)
        eve = instant("2026-12-30T22:59:59Z")
        self.assertEqual(radius_seconds(self.book, eve), F(1, 2))
        self.assertEqual(instant("2026-12-18T20:00:00.000000000+01:00"), self.at)
        with self.assertRaises(ValueError):
            instant("2026-12-18T20:00:00.000000002+01:00")

    def test_coordinates_and_dividend(self):
        at = instant("2027-01-04T12:00:00Z")
        k, s = target(self.book, at, 78, "stock")
        self.assertEqual(k - s, self.book.paid(at.date()))
        self.assertGreater(k, s)
        self.assertEqual(target(self.book, at, 78, "gains"), (78, 78))
        for t, k, coord in [
            (self.book.t0, 78, "gains"),
            (self.at, 1, "gains"),
            (instant("2026-12-30T23:00:00Z"), 78, "stock"),
        ]:
            with self.assertRaises(ValueError):
                target(self.book, t, k, coord)
        with self.assertRaises(ValueError):
            point(self.book, self.at, 78, "stock", ["-.1"])
        xs = [0, 1, 3, 6, 10, 12, 78]
        values = [self.book.state_factor(x) for x in xs]
        self.assertEqual(values, sorted(values))
        self.assertEqual((values[0], values[-1]), (0.0, 1.0))
        self.assertEqual(self.book.state_factor(F(13, 2)), 0.5)

    def test_normal_enclosures(self):
        # Reference decimal intervals contain the known high-precision constants.
        lo, hi = normal_peak()
        self.assertLessEqual(F(lo, BASE), F("0.398942280401432677939946060"))
        self.assertGreaterEqual(F(hi, BASE), F("0.398942280401432677939946059"))
        for x, expected in [
            ("1", "0.241970724519143349797830193"),
            ("3", "0.004431848411938007175602352"),
        ]:
            lo, hi = density(F(x))
            self.assertLessEqual(F(lo, BASE), F(expected) + F(1, 10**27))
            self.assertGreaterEqual(F(hi, BASE), F(expected) - F(1, 10**27))
        for v in (F(0), F(1), F(20), F(96)):
            for gap in (F(0), F(1), F(19), F(30)):
                s = math.sqrt(v)
                x = float(gap)
                call = (
                    x
                    if s == 0
                    else x * (1 + math.erf(x / (s * math.sqrt(2)))) / 2
                    + s * math.exp(-x * x / (2 * s * s)) / math.sqrt(2 * math.pi)
                )
                for typ, num in (("call", call), ("put", call - x)):
                    lo, hi = normal_vanilla(gap, F(0), typ, v)
                    self.assertLessEqual(float(lo) - 3e-14, num)
                    self.assertGreaterEqual(float(hi) + 3e-14, num)

    def test_kernel_and_integer_convolution(self):
        weights = propose_kernel(F(3, 2), F(1, 16))
        self.assertLess(check_kernel(F(3, 2), F(1, 16), weights), F(1, 1000))
        weights[1] += 1
        with self.assertRaises(ValueError):
            check_kernel(F(3, 2), F(1, 16), weights)
        w = [MASS // 2, MASS // 4]
        values = [5, 13, 21, 97, 101]
        expect = [(u + 2 * v + w) // 4 for u, v, w in zip(values, values[1:], values[2:])]
        self.assertEqual(Convolution("python")(values, w), expect)
        try:
            c = Convolution("numpy")
        except ImportError:
            return
        self.assertEqual(c(values, w), expect)

    def test_tampering_and_outer_ranges(self):
        bad = dict(self.cert, panel_sha256=digest({"wrong": "panel"}))
        with self.assertRaisesRegex(ValueError, "Different point certificate"):
            replay(self.inputs, bad)
        proof = self.cert["operational_variance_proof"]
        boxes = check_ranges(self.book, self.poly, self.p3, proof)
        self.assertEqual(len(boxes), 8)
        bad = copy.deepcopy(proof)
        bad["slices"][0][0]["lo"] = "95"
        with self.assertRaisesRegex(ValueError, "Unproved variance floor"):
            check_ranges(self.book, self.poly, self.p3, bad)
        vt = point(self.book, self.at, 78, "gains", ())["base_variance"]
        for bounds in (
            variance_at(self.book, self.at, 78, "gains", boxes),
            lipschitz_at(self.book, self.at, 78, "gains", boxes, F(".02")),
        ):
            self.assertLess(bounds[0], vt)
            self.assertGreater(bounds[1], vt)
        cut = lipschitz_at(self.book, self.at, 78, "gains", boxes, 0)
        loose = lipschitz_at(self.book, self.at, 78, "gains", boxes, F(".02"))
        self.assertLessEqual(loose[0], cut[0])
        self.assertGreaterEqual(loose[1], cut[1])
        impossible = [[(F(1), F(1)), (F(20), F(20))]]
        self.assertIsNone(lipschitz_at(self.book, self.at, 78, "gains", impossible, 0))

    def test_archived_spreads_and_default_report(self):
        report, rows = replay(self.inputs, self.cert)
        self.assertEqual(report, load(PUBLISHED / "summary.json"))
        self.assertEqual(len(rows), 60)
        self.assertEqual(report["exercise_cutoffs"], 37)
        for row in rows:
            self.assertLess(F(row["american_bid"]), F(row["american_lower_eur"]))
            self.assertLess(F(row["american_upper_eur"]), F(row["american_ask"]))

    def test_derivative_data_and_denominator(self):
        tight = dupire_at_stencil(self.poly, self.p3, 0, 0)
        wide = dupire_at_stencil(self.poly, self.p3, 40, "0.003")
        l, h = map(F, tight["volatility_pct_outer"])
        ll, hh = map(F, wide["volatility_pct_outer"])
        self.assertLessEqual(ll, l)
        self.assertGreaterEqual(hh, h)
        self.assertIsNone(dupire_at_stencil(self.poly, self.p3, 0, 1)["volatility_pct_outer"])
        with self.assertRaises(ValueError):
            dupire_at_stencil(self.poly, self.p3, -1, 0)


if __name__ == "__main__":
    unittest.main()
