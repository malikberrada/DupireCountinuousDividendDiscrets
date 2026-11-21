"""Rational stop-loss distance for a symmetric lattice approximation to Brownian noise."""

from fractions import Fraction as F
from functools import lru_cache
from math import isqrt

BASE = 1 << 86
MASS = 1 << 28
SD_UNIT = 10**10


def ceildiv(a, b):
    return -((-a) // b)


def fixed_lo(x, unit=BASE):
    return x.numerator * unit // x.denominator


def fixed_hi(x, unit=BASE):
    return ceildiv(x.numerator * unit, x.denominator)


def sqrt_lo(x, unit=SD_UNIT):
    return F(isqrt(x.numerator * unit * unit // x.denominator), unit)


def sqrt_hi(x, unit=SD_UNIT):
    low = sqrt_lo(x, unit)
    return low if low * low == x else low + F(1, unit)


@lru_cache(maxsize=1)
def normal_peak():
    def atan(q):
        total = sum((F((-1) ** k, (2 * k + 1) * q ** (2 * k + 1)) for k in range(26)), F(0))
        return total, total + F(1, 53 * q**53)

    a, b = atan(5)
    c, d = atan(239)
    pmin = 16 * a - 4 * d
    pmax = 16 * b - 4 * c
    return fixed_lo(sqrt_lo(1 / (2 * pmax), 10**26)), fixed_hi(sqrt_hi(1 / (2 * pmin), 10**26))


def density(u):
    """Enclose the standard normal density at a rational |u| < 10 in units of 2^-86."""
    y = u * u / 256
    if y > 1:
        raise ValueError("Density argument outside the certified expansion range")
    yl, yh = fixed_lo(y), fixed_hi(y)
    tl = th = lo = hi = BASE
    for j in range(1, 21):
        tl = tl * yl // (BASE * j)
        th = ceildiv(th * yh, BASE * j)
        if j % 2:
            lo -= th
            hi -= tl
        else:
            if j < 20:
                lo += tl  # lower endpoint retains the odd partial sum through order 19
            hi += th
    # (exp(-u^2/256))^128 = exp(-u^2/2).
    for _ in range(7):
        lo = lo * lo // BASE
        hi = ceildiv(hi * hi, BASE)
    cl, ch = normal_peak()
    return lo * cl // BASE, ceildiv(hi * ch, BASE)


def propose_kernel(v, step):
    """Only a proposal. Its stop-loss error is verified without libm."""
    from math import ceil, erfc, exp, pi, sqrt

    s = float(sqrt_lo(v))
    h = float(step)
    n = ceil(8 * s / h)

    def call(j):
        k = j * h
        y = k / s
        return s * exp(-y * y / 2) / sqrt(2 * pi) - k * erfc(y / sqrt(2)) / 2

    c = [call(j) for j in range(n)] + [0.0, 0.0]
    wings = [max(0, round(MASS * (c[j - 1] - 2 * c[j] + c[j + 1]) / h)) for j in range(1, n + 1)]
    return [MASS - 2 * sum(wings), *wings]


def check_kernel(v, step, weights):
    """Uniform call-payoff error for a normal increment of variance v, over every strike."""
    if not (F(0) < v and F(0) < step):
        raise ValueError("Positive variance and mesh required")
    if (
        not weights
        or not all(type(w) is int and w >= 0 for w in weights)
        or weights[0] + 2 * sum(weights[1:]) != MASS
    ):
        raise ValueError("Invalid symmetric probability kernel")
    s = sqrt_lo(v)
    if not s:
        raise ValueError("Increase SD_UNIT for this variance")
    d = step / s
    n = len(weights) - 1
    if not 1 <= n or n * d > 10:
        raise ValueError("Uncertified lattice support")
    # A normal stop-loss is linear in its density and integrated density.
    # Composite Simpson on [0,j*d]. |phi''''| <= 16 suffices on the whole real line.
    phi = [density(F(j, 2) * d) for j in range(2 * n + 1)]
    mass_above = sum(weights[1:])
    moment = sum(j * w for j, w in enumerate(weights))
    sim_lo = sim_hi = 0
    err = F(0)
    for j in range(n + 1):
        x = j * d
        remainder = 16 * x * d**4 / 2880
        int_lo = d * sim_lo / (6 * BASE) - remainder
        int_hi = d * sim_hi / (6 * BASE) + remainder
        lo = s * (F(phi[2 * j][0], BASE) - x * (F(1, 2) - int_lo))
        hi = s * (F(phi[2 * j][1], BASE) - x * (F(1, 2) - int_hi))
        discrete = step * F(moment - j * mass_above, MASS)
        err = max(err, discrete - lo, hi - discrete)
        if j < n:
            sim_lo += phi[2 * j][0] + 4 * phi[2 * j + 1][0] + phi[2 * j + 2][0]
            sim_hi += phi[2 * j][1] + 4 * phi[2 * j + 1][1] + phi[2 * j + 2][1]
            mass_above -= weights[j + 1]
            moment -= (j + 1) * weights[j + 1]
    peak_hi = F(normal_peak()[1], BASE)
    error = err + step**2 * peak_hi / (8 * s) + sqrt_hi(v) - s
    return F(fixed_hi(error, 10**12), 10**12)
