"""Integer Bellman recursion on the complete set of reachable lattice states."""

import sys
from array import array
from fractions import Fraction as F
from itertools import accumulate

from pointwise.gaussian import MASS, check_kernel, fixed_lo

PRICE = 1 << 22


def packed(values):
    v = array("Q", values)
    if v.itemsize != 8:
        raise ValueError("An unsigned 64-bit array type is needed")
    if sys.byteorder != "little":
        v.byteswap()
    return v.tobytes()


def unpacked(raw):
    v = array("Q")
    v.frombytes(raw)
    if sys.byteorder != "little":
        v.byteswap()
    return v


class Convolution:
    def __init__(self, backend):
        self.np = None
        if backend in ("auto", "numpy"):
            try:
                import numpy as np
            except ImportError:
                if backend == "numpy":
                    raise
            else:
                self.np = np
        elif backend != "python":
            raise ValueError("Unknown convolution backend")
        self.cached = {}

    def __call__(self, values, wing):
        if not values or min(values) < 0 or max(values) * MASS >= 2**63:
            raise ValueError("Integer accumulation outside proved bounds")
        key = tuple(wing)
        symmetric = wing[:0:-1] + wing
        count = len(values) - len(symmetric) + 1
        if count <= 0:
            raise ValueError("Unreachable leading grid")
        if self.np is not None:
            weights = self.cached.get(key)
            if weights is None:
                weights = self.np.asarray(symmetric, dtype=self.np.int64)
                self.cached[key] = weights
            dot = self.np.convolve(
                self.np.asarray(values, dtype=self.np.int64), weights, mode="valid"
            )
            return (dot // MASS).tolist()
        kernel = self.cached.get(key)
        if kernel is None:
            kernel = int.from_bytes(packed(symmetric), "little")
            self.cached[key] = kernel
        # Polynomial product in radix 2^64. Every coefficient is nonnegative and
        # bounded by MASS*max(values); no carry can reach an adjacent coefficient.
        product = int.from_bytes(packed(values), "little") * kernel
        product >>= 64 * (len(symmetric) - 1)
        vals = unpacked((product & ((1 << (64 * count)) - 1)).to_bytes(8 * count, "little"))
        return [n // MASS for n in vals]


def lattice_prices(book, step, kernels, backend):
    dh = step * PRICE
    if dh.denominator != 1:
        raise ValueError("The spatial mesh must be representable in the payoff units")
    radii = list(accumulate(len(w) - 1 for w in kernels))
    conv = Convolution(backend)

    def exercise(i, j, r):
        c = book.market.contracts[i]
        sign = 1 if c["kind"] == "call" else -1
        at_zero = fixed_lo(sign * (book.z - book.thresholds[j][i]), PRICE)
        delta = sign * dh.numerator
        return [max(0, at_zero + delta * k) for k in range(-r, r + 1)]

    answers = []
    for i, c in enumerate(book.market.contracts):
        end = book.dates.index(book.market.expiries[c["m"]])
        v = exercise(i, end, radii[end])
        for j in range(end, -1, -1):
            v = conv(v, kernels[j])
            if j:
                floor = exercise(i, j - 1, radii[j - 1])
                v = [max(pay, hold) for pay, hold in zip(floor, v, strict=True)]
        today = exercise(i, 0, 0)[0]
        answers.append(F(max(today, v[0]), PRICE))
    return answers


def certify_prices(book, step, kernels, backend="auto"):
    if len(kernels) != len(book.dates):
        raise ValueError("Wrong kernel count")
    errors = [check_kernel(v, step, w) for v, w in zip(book.variances, kernels, strict=True)]
    discrete = lattice_prices(book, step, kernels, backend)
    records = []
    budgets = {}
    for low, c in zip(discrete, book.market.contracts, strict=True):
        end = book.dates.index(book.market.expiries[c["m"]])
        if end not in budgets:
            budgets[end] = (
                sum(errors[: end + 1]),
                book.coupling_error(sum(book.variances[: end + 1])),
                F(end + 2, PRICE),
            )
        gaussian, localize, rounding = budgets[end]
        lower = low - gaussian - localize
        upper = low + rounding + gaussian + localize
        slack = min(lower - c["bid"], c["ask"] - upper) / book.market.prem
        records.append(
            {
                "isin": c["id"],
                "lower": lower / book.market.prem,
                "upper": upper / book.market.prem,
                "margin": slack,
                "gaussian_budget": gaussian / book.market.prem,
                "localization_budget": localize / book.market.prem,
                "rounding_budget": rounding / book.market.prem,
            }
        )
    return records
