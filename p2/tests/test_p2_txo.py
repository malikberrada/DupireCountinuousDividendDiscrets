"""Regression checks on exact arithmetic, terminal mapping, market units and repeatability."""

from fractions import Fraction as F
from unittest import TestCase, main
from copy import deepcopy
from bisect import bisect_right
from math import comb
import json

from dupire_identify.interval import I, exp_point
from dupire_identify.spxw_witness import intercepts
from p2_txo import ROOT, archived_pairs, classify, continuous_family, gap, slope_box, validate_reference
from txo_lattice import lattice, fixed_grid, family_grid, binomial_weights, UNIT
from grid_fit import curves


PANEL = json.loads((ROOT / "panel.json").read_bytes())
DOC = json.loads((ROOT / "result.json").read_bytes())
PAR = DOC["model"]
KNOTS = tuple(map(F, PAR["knots"]))
SLOPES = tuple(map(F, PAR["slopes"]))
PAIRS = archived_pairs(PANEL)
D, FORWARD = curves(PANEL)
T = F(DOC["clock"])
AMIN, AMAX = map(F, DOC["prior"])


class TestMarketP2(TestCase):
    def test_binomial_weights_and_interval_recurrence(self):
        m = 4
        n = m * m
        nodes, mean = lattice(KNOTS, SLOPES, m)
        self.assertEqual(list(binomial_weights(n)), [comb(n, j) for j in range(n + 1)])
        self.assertEqual(sum(binomial_weights(n)), 1 << n)
        constants = intercepts(KNOTS, SLOPES)
        for j, (lo, hi) in enumerate(nodes):
            z = F(2 * j - n, m)
            i = bisect_right(KNOTS, z)
            oracle = exp_point(SLOPES[i] * z + constants[i])
            self.assertLessEqual(F(lo, UNIT), oracle.lo)
            self.assertGreaterEqual(F(hi, UNIT), oracle.hi)
        self.assertGreater(mean.lo, 0)

    def test_reported_refinements_and_inclusion(self):
        rows = DOC["rows"]
        self.assertEqual(len(rows), 10)
        self.assertEqual(DOC["fitting_grid_steps"], 1024)
        self.assertTrue(
            all(
                r["fit_grid_in_spread"] and r["fixed_both_in_spread"] and r["family_both_in_spread"]
                for r in rows
            )
        )
        self.assertTrue(
            all(
                r["prior"]["constant_low_outside"] and r["prior"]["constant_high_outside"]
                for r in rows
            )
        )
        self.assertGreater(F(DOC["box_radius"]), 0)
        self.assertTrue(all(F(r["fixed_eta_points"]) < F(1, 100) for r in rows))

    def test_call_put_parity_in_each_valuation(self):
        rows = DOC["rows"]
        for call, put in zip(rows[::2], rows[1::2]):
            parity = D * (FORWARD - F(call["strike"]))
            for key in ("grid_points", "fitting_grid_points", "continuous_points"):
                ci, pi = (I(*map(F, b[key])) for b in (call, put))
                self.assertLessEqual((ci - pi).lo, parity)
                self.assertGreaterEqual((ci - pi).hi, parity)

    def test_nonconstant_slope_inside_one_original_segment(self):
        low, high, lo_map, hi_map = slope_box(KNOTS, SLOPES, F(DOC["box_radius"]))
        # The second half of the segment (0, 1/2) uses a different derivative.
        kk = tuple(sorted((*KNOTS, F(1, 4))))
        ss = tuple(low[:4] + [high[4]] + low[4:])
        c = continuous_family(
            dict(PAR, kind="gaussian_terminal_loglinear", knots=list(map(str, kk))),
            ss,
            ss,
            I(FORWARD),
            PAIRS,
            T,
            AMIN,
            AMAX,
        )
        f = fixed_grid(kk, ss, I(FORWARD), D, PAIRS, 8)
        env = family_grid(KNOTS, lo_map, hi_map, I(FORWARD), D, PAIRS, 8)
        for row in DOC["rows"]:
            k = row["id"]
            l, u = map(F, row["family_continuous_points"])
            self.assertLessEqual(l, c[k].lo)
            self.assertGreaterEqual(u, c[k].hi)
            self.assertLessEqual(env[k].lo, f[k].lo)
            self.assertGreaterEqual(env[k].hi, f[k].hi)

    def test_bound_is_in_points_and_normalized(self):
        for r in DOC["rows"]:
            a = I(*map(F, r["continuous_points"]))
            b = I(*map(F, r["grid_points"]))
            self.assertEqual(gap(a, b), F(r["fixed_eta_points"]))
            self.assertEqual(gap(a, b) / (D * FORWARD), F(r["fixed_eta_normalized"]))

    def test_curves_meet_all_selected_parity_strips(self):
        self.assertEqual((D, FORWARD), (F(PAR["discount"]), F(PAR["forward"])))
        for p in PAIRS:
            lo, hi = p.strip
            self.assertLessEqual(lo, D * (FORWARD - p.k))
            self.assertGreaterEqual(hi, D * (FORWARD - p.k))

    def test_scope_and_crossing_classification(self):
        b = PAIRS[0].call
        self.assertEqual(classify(I(b.bid, b.ask), b), "in")
        self.assertEqual(classify(I(b.bid - 1, b.bid), b), "open")
        self.assertEqual(classify(I(b.ask + 1, b.ask + 2), b), "out")
        doc = deepcopy(PANEL)
        doc["schema"] = "unrecognized"
        with self.assertRaises(ValueError):
            validate_reference(doc, None)


if __name__ == "__main__":
    main()
