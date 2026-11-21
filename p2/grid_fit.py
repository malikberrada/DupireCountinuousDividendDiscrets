"""Panel-calibrated lattice proposal. The optimizer evaluates terminal binomial sums only."""

from fractions import Fraction as F

from dupire_identify.spxw_books import clip


def curves(panel):
    """Select the midpoint of the 95-pair discount range, then midpoint of its DF slice."""
    poly = [tuple(map(F, v)) for v in panel["expected_parity"]["vertices_D_DF"]]
    discount = (max(p[0] for p in poly) + min(p[0] for p in poly)) / 2
    section = clip(clip(poly, lambda p: p[0] - discount), lambda p: discount - p[0])
    if not section or any(x[0] != discount for x in section):
        raise ArithmeticError("Empty conditional parity section")
    prepaid = (min(x[1] for x in section) + max(x[1] for x in section)) / 2
    return discount, prepaid / discount


def propose(panel, pairs, t, amin, amax, m=32):
    import numpy as np
    import scipy
    from scipy.optimize import least_squares, minimize
    from scipy.stats import binom

    d, f = curves(panel)
    k = np.array([float(p.k) for p in pairs])
    q = [x for side in ("call", "put") for p in pairs for x in [getattr(p, side)]]
    bid = np.array([float(x.bid) for x in q])
    ask = np.array([float(x.ask) for x in q])
    mid = (bid + ask) / 2
    half = (ask - bid) / 2
    if np.any(half <= 0):
        raise ValueError("Finite positive bid-ask width required for the proposal")
    n = m * m
    z = (2 * np.arange(n + 1) - n) / m
    w = binom.pmf(np.arange(n + 1), n, 0.5)
    # h(z)=integral from zero to z of one slope per fixed segment.
    knots = np.array([-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0])
    edges = np.r_[-np.inf, knots, np.inf]
    basis = np.zeros((len(z), len(edges) - 1))
    for j, (l, r) in enumerate(zip(edges, edges[1:])):
        basis[:, j] = np.maximum(0, np.minimum(np.maximum(z, 0), r) - max(0, l)) - np.maximum(
            0, min(0, r) - np.maximum(np.minimum(z, 0), l)
        )

    def fit_error(x):
        raw = np.exp(basis @ x)
        values = float(f) * raw / (w @ raw)
        c = float(d) * (w @ np.maximum(values[:, None] - k, 0))
        p = c + float(d) * (k - float(f))
        return (np.r_[c, p] - mid) / half

    near = int(np.argmin(abs(k - float(f))))
    # Data-based initialization from the forward-ATM straddle.
    initial = (mid[near] + mid[len(k) + near]) * np.sqrt(np.pi / 2) / (float(d) * float(f))
    lo, hi = np.sqrt([float(amin * t), float(amax * t)])
    guard = (hi - lo) * 1e-8
    lower, upper = lo + guard, hi - guard
    flat = np.full(len(knots) + 1, np.clip(initial, lower, upper))
    fit = least_squares(
        fit_error, flat, bounds=(lower, upper), max_nfev=650, ftol=1e-11, xtol=1e-11, gtol=1e-11
    )
    x = fit.x
    for attempt in range(2):
        if attempt or max(np.abs(fit_error(x))) > 0.75:

            def inequalities(v):
                err = fit_error(v[:-1])
                return np.r_[v[-1] - err, v[-1] + err]

            opt = minimize(
                lambda v: v[-1],
                np.r_[x, max(np.abs(fit_error(x)))],
                method="SLSQP",
                bounds=[(lower, upper)] * len(x) + [(0, None)],
                constraints=dict(type="ineq", fun=inequalities),
                options=dict(maxiter=450, ftol=1e-11),
            )
            if max(np.abs(fit_error(opt.x[:-1]))) < max(np.abs(fit_error(x))):
                x = opt.x[:-1]
        if max(np.abs(fit_error(x))) < 0.98:
            break
    slopes = [F(format(float(s), ".14g")) for s in x]
    return dict(
        schema="txo-grid-fit-v1",
        fit_steps=n,
        fit_root=m,
        discount=str(d),
        forward=str(f),
        knots=["-2", "-1", "-1/2", "0", "1/2", "1", "2"],
        slopes=list(map(str, slopes)),
        criterion="maximum absolute distance from midpoint divided by half-spread, numerical proposal",
        initial_curve="single common slope from the observed nearest-forward straddle",
        fitted_relative_error_diagnostic=float(
            max(np.abs(fit_error(np.array(list(map(float, slopes))))))
        ),
        scipy_version=scipy.__version__,
        numpy_version=np.__version__,
    )


if __name__ == "__main__":
    from argparse import ArgumentParser
    from datetime import date
    import json
    from pathlib import Path
    from p2_txo import ROOT, archived_pairs, write
    from dupire_identify.taifex_books import clocks

    p = ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    doc = json.loads((ROOT / "panel.json").read_bytes())
    s = doc["settings"]
    t = clocks(date.fromisoformat(s["date"]), date.fromisoformat(s["expiry"]))[2]
    res = propose(doc, archived_pairs(doc), t, F(s["amin"]), F(s["amax"]))
    write(args.out, res)
    print("Grid-only fit, maximum relative deviation:", res["fitted_relative_error_diagnostic"])
