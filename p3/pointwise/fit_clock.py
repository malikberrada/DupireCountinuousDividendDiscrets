"""Numerical proposals for a reference clock and two compatible spot-volatility extrema."""

from fractions import Fraction as F


def optimize(panel, at):
    import numpy as np
    from model import Market
    from scipy.optimize import minimize
    from scipy.signal import fftconvolve

    from pointwise.calendar_model import CalendarModel, days_between

    market = Market(panel)
    initial = {
        "prepaid_spot": str(market.z),
        "variance_intercept": "1.2",
        "variance_slope": "0",
        "floor": "1",
        "flat_from": "12",
    }
    book = CalendarModel(panel, initial)
    dt = np.array([float(v - u) for u, v in zip(book.ages, book.ages[1:])])
    midpoint = np.array([float((v + u) / 2) for u, v in zip(book.ages, book.ages[1:])])
    h = np.array(book.thresholds, dtype=float)
    cs = market.contracts
    signs = np.array([1 if c["kind"] == "call" else -1 for c in cs])
    short = np.array([c["m"] == 0 for c in cs])
    spread_scale = float(market.prem)
    bids = np.array([float(c["bid"]) for c in cs]) / spread_scale
    asks = np.array([float(c["ask"]) for c in cs]) / spread_scale
    first = book.dates.index(market.expiries[0])
    t = float(days_between(book.t0, at))
    # A fast Gaussian convolution proposes parameters. The certified integer recursion
    # uses its own transition law, larger spatial domain and explicit truncation bounds.
    dx = 0.10
    wing = 700
    grid = np.arange(-wing, wing + 1) * dx

    def prices(theta):
        z, a, b = theta[:3]
        vars = dt * (a + b * midpoint)
        if np.min(vars) <= 0:
            return bids - 100
        x = z + grid
        pay = np.maximum(0, signs[None, None, :] * (x[None, :, None] - h[:, None, :]))
        val = pay[-1].copy()
        for j in reversed(range(len(book.dates))):
            if j == first:
                val[:, short] = pay[j][:, short]
            val = np.maximum(val, pay[j])
            n = int(np.ceil(8 * np.sqrt(vars[j]) / dx))
            offsets = np.arange(-n, n + 1) * dx
            weights = np.exp(-(offsets**2) / (2 * vars[j]))
            weights /= weights.sum()
            ext = np.pad(val, ((n, n), (0, 0)), mode="edge")
            val = fftconvolve(ext, weights[:, None], mode="valid", axes=0)
        return np.maximum(val[wing], np.maximum(signs * (z - h[0]), 0)) / spread_scale

    def margins(theta):
        p = prices(theta)
        return np.r_[p - bids, asks - p]

    opts = {"maxiter": 110, "ftol": 2e-11}
    box = [(float(market.zlo), float(market.zhi)), (0.4, 2), (-0.022, 0.02)]
    res = minimize(
        lambda x: -x[3],
        [float(market.z), 1.25, -0.008, 0.0],
        method="SLSQP",
        bounds=box + [(-1, 0.3)],
        constraints=[{"type": "ineq", "fun": lambda x: margins(x) - x[3]}],
        options=opts,
    )
    if not res.success:
        raise RuntimeError("Reference clock optimization failed: " + res.message)
    candidates = {"reference": res.x[:3]}
    for name, sign in (("lower_example", 1), ("upper_example", -1)):
        opt = minimize(
            lambda x, direction=sign: direction * (x[1] + t * x[2]),
            res.x[:3],
            method="SLSQP",
            bounds=box,
            constraints=[{"type": "ineq", "fun": lambda x: margins(x) - 0.0035}],
            options=opts,
        )
        if (
            not np.all(np.isfinite(opt.x))
            or np.min(margins(opt.x)) < 0.0034
            or sign * ((opt.x[1] - res.x[1]) + t * (opt.x[2] - res.x[2])) >= 0
        ):
            raise RuntimeError("No feasible directional improvement: " + opt.message)
        candidates[name] = opt.x

    def param(x):
        # A boundary proposal must keep the exact rational underlying bid or ask.
        z = F(str(round(float(x[0]), 8)))
        z = min(market.zhi, max(market.zlo, z))
        return {
            "prepaid_spot": str(z),
            "variance_intercept": str(round(float(x[1]), 8)),
            "variance_slope": str(round(float(x[2]), 10)),
            "floor": "1",
            "flat_from": "12",
        }

    return {name: param(x) for name, x in candidates.items()}
