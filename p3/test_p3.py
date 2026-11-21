import copy
import unittest
from datetime import date
from fractions import Fraction as F

from certify import verify
from dividends import sensitivity
from joint import mix
from market import ROOT, book, check_files, latest, load, ns
from model import Market, evaluate, intrinsic
from outer import Outer, dual_bound, form, ratio_bound, read_interval


class P3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = check_files()
        cls.m = Market(cls.data)
        cls.cert = load(ROOT / "certified/certificate.json")
        cls.w = cls.cert["witnesses"][0]

    def test_books_and_reference(self):
        self.assertEqual(len(self.data["contracts"]), 20)
        self.assertEqual({q["style"] for q in self.data["contracts"]}, {"AMER"})
        self.assertEqual(self.data["day_posttrade_messages_before_asof"], 95)
        self.assertEqual(self.data["spot"]["mic"], "XETB")
        self.assertIsNone(book([{"price": 5, "quantity": 1}], [{"price": 4, "quantity": 1}]))

    def test_no_forward_timestamp_or_filling_cancel(self):
        key = "instrumentIdentificationCode"
        iso = "2026-11-20T12:00:00."
        rows = [
            {key: "a", "ts": iso + v + "Z", "status": v}
            for v in ["000000001", "000000003", "000000002"]
        ]
        self.assertEqual(latest(rows, "ts", ns(iso + "000000002Z"))["a"]["status"], "000000002")
        self.assertIsNone(book([], [{"price": "5", "quantity": "2"}]))

    def test_date_basis(self):
        from model import roll

        d = self.data["dividends"][0]
        self.assertEqual(d["ex_date"], "2026-12-31")
        self.assertEqual(d["pay_date"], "2027-01-05")
        self.assertEqual(roll(date(2026, 11, 20), 2), date(2026, 11, 24))
        self.assertEqual(self.m.rate, F(2441, 100000))

    def test_generic_calendar_missing_rejected(self):
        data = copy.deepcopy(self.data)
        data["asof"] = "2026-11-19T12:00:50Z"
        with self.assertRaises(ValueError):
            Market(data)

    def test_altered_witness(self):
        w = copy.deepcopy(self.w)
        key = next(iter(w["states"]))
        w["states"][key]["p"] = "0"
        with self.assertRaises(ValueError):
            evaluate(self.m, w)

    def test_early_stop_by_full_calendar_recursion(self):
        m = self.m
        w = self.w
        exact, _ = evaluate(m, w)
        z = F(w["z"])
        states = w["states"]
        # Explicitly exercise or continue on each day, with an independent pre/post
        # observation step on the two revelation days. No threshold reduction here.
        for c in m.contracts:
            expiry = m.expiries[c["m"]]
            days = sorted(d for d in m.trading_dates if d <= expiry)

            def pay(d, x, spec=c):
                delta = sum(a * m.disc(p) for e, p, a in m.divs if e <= d)
                return intrinsic(spec["kind"], x, delta + spec["K"] * m.disc(m.settle(d, 2)))

            after_first = {}
            for xs, branch in states.items():
                x = F(xs)
                val = F(0)
                if c["m"] == 1:
                    val = sum(F(q) * pay(expiry, F(y)) for y, q in branch["next"].items())
                for day in reversed([d for d in days if d >= m.expiries[0]]):
                    val = max(pay(day, x), val)
                after_first[xs] = val
            american = sum(F(s["p"]) * after_first[x] for x, s in states.items())
            for day in reversed([d for d in days if d <= m.expiries[0]]):
                american = max(pay(day, z), american)
            self.assertEqual(american / m.prem, exact[c["id"]][1])

    def test_joint_convex_inner(self):
        ws = self.cert["witnesses"][:3]
        weights = [F(1, 4), F(1, 2), F(1, 4)]
        mixp, _ = evaluate(self.m, mix(ws, weights))
        cols = [evaluate(self.m, w)[0] for w in ws]
        for i in mixp:
            self.assertEqual(mixp[i][0], sum(v * col[i][0] for v, col in zip(weights, cols)))

    def test_incompatible_coordinates(self):
        cid = "DE000F4E4YY7"
        pid = "DE000F4E4YZ4"
        columns = [evaluate(self.m, w)[0] for w in self.cert["witnesses"]]
        combined = max(q[cid][0] for q in columns) - min(q[pid][0] for q in columns)
        p = Outer(self.m)
        spec = self.cert["directions"]["call_minus_put"]
        _, upper = read_interval(p, p.direction(spec["weights"]), spec["proof"])
        self.assertGreater(combined, upper)

    def test_sharp_parity_endpoints(self):
        cols = [evaluate(self.m, w)[0] for w in self.cert["witnesses"]]
        ref = next(c for c in self.m.contracts if c["id"] == "DE000F4E4YY7")
        dif = [c[ref["id"]][0] - c["DE000F4E4YZ4"][0] for c in cols]
        self.assertEqual(
            [min(dif), max(dif)], [(z - ref["h"]) / self.m.prem for z in (self.m.zlo, self.m.zhi)]
        )

    def test_bad_dual_and_zero_denominator(self):
        p = Outer(self.m)
        with self.assertRaises(ValueError):
            dual_bound(p, form(), {"0": "-1"})
        with self.assertRaises(ValueError):
            dual_bound(p, form(), {"-1": "1"})
        with self.assertRaises(ValueError):
            ratio_bound(p, 0, 1, {"alpha": "0", "dual": {}})

    def test_dividend_stress_and_endpoint_repricing(self):
        bound = sensitivity(self.m, self.w, "0.85", "0.95")
        self.assertTrue(bound["jointly_robust"])
        for amount in ("0.85", "0.95"):
            data = copy.deepcopy(self.data)
            data["dividends"][0]["amount"] = amount
            stressed = Market(data)
            p, _ = evaluate(stressed, self.w)
            base, _ = evaluate(self.m, self.w)
            for r in bound["per_contract"]:
                i = r["isin"]
                self.assertLessEqual(abs(p[i][1] - base[i][1]), F(r["optimal_stop_error_upper"]))
        with self.assertRaises(ValueError):
            sensitivity(self.m, self.w, "1", "0")

    def test_shifted_ex_day_budget(self):
        unchanged = sensitivity(self.m, self.w, ".90", ".90")
        self.assertEqual(
            max(F(r["optimal_stop_error_upper"]) for r in unchanged["per_contract"]), 0
        )
        shifted = sensitivity(self.m, self.w, ".9", ".9", "2026-12-29", "2026-12-31")
        self.assertGreater(
            max(F(r["optimal_stop_error_upper"]) for r in shifted["per_contract"]), F(".8")
        )

    def test_certificate_bound_to_input(self):
        data = copy.deepcopy(self.data)
        data["rate_pct"] = "0"
        with self.assertRaises(ValueError):
            verify(data, self.cert)

    def test_all_exports(self):
        from p3_eurex import main

        r = main(["verify"])
        self.assertEqual(r["contracts"], 20)
        self.assertTrue(r["full_core_simplex_certified"])
        self.assertGreater(F(r["dupire"]["denominator"][0]), 0)
        self.assertGreater(F(r["expected_local_time_increment_continuous_models"]["outer"][0]), 0)


if __name__ == "__main__":
    unittest.main()
