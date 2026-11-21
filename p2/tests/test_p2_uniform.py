"""Regression checks for the P2 proof, the P1 bridge and source-bound replay."""

from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main, mock

from dupire_identify.interval import black_call
from dupire_identify.io import Quote, quote_payload
from dupire_identify import p2_mesh, p2_bridge, p2_cert
from dupire_identify.p2_plateau import from_plateau
from dupire_identify.p2_uniform import Bands, certify, exit_budget, hit_probability, read_prices

Q = Quote("call", F(1, 4), F(1), F(3, 100), F(5, 100))
CONST = {
    "schema": "p2-variance-bands-v1",
    "spot_edges": [],
    "slabs": [{"end": "1", "lower": ["1/25"], "upper": ["1/25"]}],
}
CFG = dict(
    left="1/2",
    right="3/2",
    cells=8,
    steps=3,
    levels=1,
    target=None,
    method="exact",
    bits=42,
    max_work=5000,
    auto_domain=False,
)


def inputs(bands=CONST, quotes=(Q,)):
    return dict(bands=bands, quotes=quote_payload(quotes), prices={q.id: "1/25" for q in quotes})


def replay_doc():
    inp = inputs()
    return dict(format="dupire-p2-proof-v1", inputs=inp, options=CFG, result=p2_cert.make(inp, CFG))


class TestUniformP2(TestCase):
    def test_cash_and_pde_cover_analytic_reference_without_black_intersection(self):
        b = deepcopy(CONST)
        b["slabs"] = [
            {"end": "1/8", "lower": ["0.01"], "upper": ["0.01"]},
            {"end": "1", "lower": ["0.09"], "upper": ["0.09"]},
        ]
        report = certify(Bands.read(b), [Q], {Q.id: F(1, 25)}, steps=3, cells=8, method="exact")
        r = report["quotes"][0]
        oracle = black_call(Q.k, F(1, 8) * (F(1, 100) + F(9, 100)))
        e = r["levels"][0]["endpoints"][0]
        self.assertLessEqual(e["center"] - e["error"], oracle.lo)
        self.assertGreaterEqual(e["center"] + e["error"] + r["domain_tail"], oracle.hi)
        self.assertEqual(r["continuous_price"], [oracle.lo, oracle.hi])
        self.assertLessEqual(
            max(abs(r["numerical_price"] - oracle.lo), abs(r["numerical_price"] - oracle.hi)),
            r["eta"],
        )

    def test_time_dependent_band_covers_two_exact_admissible_extremes(self):
        b = deepcopy(CONST)
        b["slabs"][0]["lower"] = ["0.01"]
        b["slabs"][0]["upper"] = ["0.09"]
        r = certify(Bands.read(b), [Q], {Q.id: F(1, 25)}, cells=6, steps=2, method="float")[
            "quotes"
        ][0]
        self.assertEqual(r["market_status"], "undecided")
        for a in [F(1, 100), F(4, 100), F(9, 100)]:
            val = black_call(Q.k, a * Q.t)
            self.assertLessEqual(r["continuous_price"][0], val.lo)
            self.assertGreaterEqual(r["continuous_price"][1], val.hi)
        self.assertGreater(r["fixed_price_eta_lower_bound"], F(1, 100))

    def test_nodal_only_counterexample(self):
        # The integral of 16*u**2*(1-u)**2 is 8/15 in every cell.
        mean = 16 * (F(1, 3) - F(1, 2) + F(1, 5))
        self.assertEqual(mean, F(8, 15))
        a, b = F(1, 100), F(9, 100)
        for n in (1, 4, 128):
            integrated = sum((a + (b - a) * mean) / n for _ in range(n))
            difference = black_call(1, integrated).lo - black_call(1, a).hi
            self.assertGreater(difference, F(1, 25))

    def test_bernstein_operator_and_mesh_alignment(self):
        l, r = F(2, 3), F(5, 4)
        c = (F(1), F(-3, 5), F(7, 8), F(2))
        a = F(1, 8)
        ctrl = p2_mesh.diffusion_term(c, l, r, a)
        for u in [F(0), F(2, 7), F(1)]:
            bez = (
                ctrl[0] * (1 - u) ** 3
                + 3 * ctrl[1] * u * (1 - u) ** 2
                + 3 * ctrl[2] * u * u * (1 - u)
                + ctrl[3] * u**3
            )
            second = (
                6
                * ((1 - u) * (c[2] - 2 * c[1] + c[0]) + u * (c[3] - 2 * c[2] + c[1]))
                / (r - l) ** 2
            )
            self.assertEqual(bez, a * (l + u * (r - l)) ** 2 * second / 2)
        grid = p2_mesh.mesh(F(1, 2), F(3, 2), 8, [F(7, 8)], F(11, 10))
        self.assertTrue({F(7, 8), F(1), F(11, 10)}.issubset(grid))
        self.assertLessEqual(max(b - a for a, b in zip(grid, grid[1:])), F(1, 8))

    def test_mass_contains_exact_constant_absolute_speed(self):
        grid = [F(1, 2), F(3, 4), F(1)]
        low, high, rel = p2_mesh.generator(grid, [F(1, 25)] * 2)
        m = 1 / (low[1] + high[1])
        # log integral independently from the interval engine for this node.
        from dupire_identify.interval import log_point

        l, x, r = grid
        exact = 25 * (log_point(x / l) + l / x - 1 + r / x - 1 - log_point(r / x))
        self.assertLessEqual(m * (1 - rel), exact.lo)
        self.assertGreaterEqual(m * (1 + rel), exact.hi)

    def test_boundary_and_adaptive_budget(self):
        self.assertEqual(exit_budget(F(0), None, F(1), F(1, 25)), 0)
        self.assertLess(hit_probability(F(2), F(1, 100)), F(1, 1000))
        b = Bands.read(CONST)
        r = certify(b, [Q], {Q.id: F(0)}, target=F(1, 200), max_work=1, auto_domain=True)["quotes"][
            0
        ]
        self.assertFalse(r["target_met"])
        self.assertGreater(r["fixed_price_eta_lower_bound"], F(1, 200))
        self.assertEqual(r["mesh_status"], "work_budget")
        self.assertEqual(r["levels"], [])

    def test_prices_bind_ids_strikes_and_expiries(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "prices.csv"
            for csv in [
                "id,t,k,price\ncall,1/2,1,0.04\n",
                "id,t,k,price\ncall,1/4,1,0.04\ncall,1/4,1,0.04\n",
            ]:
                p.write_text(csv, encoding="utf8")
                with self.assertRaises(ValueError):
                    read_prices(p, [Q])

    def test_plateau_controls_and_phase_specific_knots(self):
        cfg = dict(
            kind="piecewise_quintic_plateau_diffusion_v1",
            amin="0.01",
            amax="0.09",
            prefix_end="1/4",
            prefix_variance="1/25",
            strike_knots=["1/2", "2"],
            phases=[
                dict(
                    left="1/4",
                    right="1",
                    knots=["1/2", "1", "2"],
                    variance=["0.01", "0.09", "0.02"],
                )
            ],
        )
        b = Bands.read(from_plateau(cfg, 2))
        self.assertEqual(b.edges, (F(1, 2), F(3, 4), F(1), F(3, 2), F(2)))
        band = b.rows[-1][1]
        self.assertEqual((band[0][1], band[1][1]), (F(1, 100), F(5, 100)))
        self.assertEqual(band[0][-1], F(2, 100))
        bad = deepcopy(cfg)
        bad["phases"][0]["left"] = "1/8"
        with self.assertRaises(ValueError):
            from_plateau(bad)

    def test_replay_does_not_call_solver_and_binds_originals(self):
        doc = replay_doc()
        with mock.patch.object(
            p2_mesh, "factor_solver", side_effect=AssertionError("solver called")
        ):
            self.assertEqual(p2_cert.verify_document(doc, inputs())["quotes"][0]["id"], "call")
        altered = inputs()
        altered["prices"]["call"] = "0"
        with self.assertRaises(ValueError):
            p2_cert.verify_document(doc, altered)
        changed = deepcopy(doc)
        changed["result"]["quotes"][0]["eta"] = "0"
        with self.assertRaises(ValueError):
            p2_cert.verify_document(changed)
        changed = deepcopy(doc)
        changed["result"]["quotes"][0]["levels"][0]["endpoints"][0]["grid_put_rows"][0][0] = "11"
        with self.assertRaises(ValueError):
            p2_cert.verify_document(changed)

    def test_untrusted_interior_node_enlarges_defect(self):
        doc = replay_doc()
        r = doc["result"]["quotes"][0]
        trace = deepcopy(r["levels"])
        e = trace[0]["endpoints"][0]
        e["grid_put_rows"][1][3] = "10"
        rebuilt = p2_cert.make(doc["inputs"], doc["options"], {"call": trace})
        bound = F(rebuilt["quotes"][0]["levels"][0]["endpoints"][0]["linear_solve"])
        self.assertGreater(bound, 1)

    def test_p1_exact_mixture_primal_dual(self):
        def report(lo, hi):
            return dict(
                quotes=[
                    dict(id="q", t="1", k="1", bid="0.38", ask="0.42", continuous_price=[lo, hi])
                ]
            )

        reports = [report("0.2", "0.3"), report("0.7", "0.8")]
        cert = p2_bridge.optimize(reports, [F(0), F(1)])
        low, high = cert["objective_outer"]
        self.assertLessEqual(low, F(4, 25))
        self.assertGreaterEqual(high, F(11, 25))
        self.assertLess(F(4, 25) - low, F(1, 10**10))
        self.assertLess(high - F(11, 25), F(1, 10**10))
        for pf in cert["proofs"].values():
            self.assertIsNotNone(pf["outer_lp_gap"])
            self.assertLess(pf["outer_lp_gap"], F(1, 10**10))
        self.assertEqual(p2_bridge.optimize(reports, [F(0), F(1)], replay=cert["proofs"]), cert)
        with self.assertRaises(ValueError):
            p2_bridge.checked_bound([[F(0), F(1)]], [F(1, 2)], [F(0), F(1)], [F(0)], [F(0), F(1)])

    def test_p1_window_and_empty_market(self):
        doc = replay_doc()
        args = (CONST, ["1/4", 1, "1/16", "1/10"], 3)
        outcome = p2_bridge.window_outer(doc["result"], *args)
        self.assertEqual(outcome["variance_for_positive_denominator"], [F(1, 25)] * 2)
        self.assertFalse(outcome["empty_class"])
        from importlib.util import find_spec

        if find_spec("dupire_identify.denominator") is not None:
            self.assertTrue(outcome["denominator_positive_proved"])
            self.assertGreater(outcome["denominator_lower"], 0)
            self.assertIsNotNone(outcome["brownian_proof"])
        bad = deepcopy(doc["result"])
        bad["quotes"][0]["bid"] = "1/2"
        bad["quotes"][0]["ask"] = "3/4"
        self.assertEqual(p2_bridge.window_outer(bad, *args)["excluded_by"], "call")
        with self.assertRaises(ValueError):
            p2_bridge.window_outer(doc["result"], CONST, [1, 1, "1/16", "1/10"], 3)

    def test_global_calibration_gap_is_for_one_common_diffusion(self):
        report = replay_doc()["result"]
        self.assertEqual(report["optimization"]["global_optimum"], ["0", "0"])
        quote = Quote("q", F(1, 4), F(1), F(1, 10), F(1, 5))
        r = certify(Bands.read(CONST), [quote], {"q": F(1, 8)}, max_work=1)
        opt = r["optimization"]
        self.assertEqual(opt["numerical_fit"], 0)
        self.assertGreater(opt["global_optimum"][0], F(5, 100))
        self.assertLessEqual(opt["global_optimum"][0], opt["global_optimum"][1])
        self.assertEqual(r["quotes"][0]["market_status"], "all_outside_spread")

    def test_invalid_priors_and_targets(self):
        for bad in [
            dict(schema="p2-variance-bands-v1", spot_edges=["1", "1"], slabs=[]),
            dict(schema="p2-variance-bands-v1", spot_edges=["1"], slabs=CONST["slabs"]),
            dict(
                schema="p2-variance-bands-v1",
                spot_edges=[],
                slabs=[dict(end="1", lower=["0"], upper=["1"])],
            ),
        ]:
            with self.assertRaises(ValueError):
                Bands.read(bad)
        with self.assertRaises(ValueError):
            Bands.read(CONST).until(F(2))
        with self.assertRaises(ValueError):
            certify(Bands.read(CONST), [Q], {Q.id: F(1)}, target=F(0))
        with self.assertRaises(ValueError):
            certify(Bands.read(CONST), [], {}, auto_domain=True, target=F(1, 10))


if __name__ == "__main__":
    main()
