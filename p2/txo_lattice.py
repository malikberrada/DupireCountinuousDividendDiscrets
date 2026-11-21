"""Recombining Brownian lattice, including all atoms and certified dyadic arithmetic."""

from bisect import bisect_right
from fractions import Fraction as F
from functools import lru_cache

from dupire_identify.interval import I, exp_point
from dupire_identify.spxw_witness import intercepts

BITS = 96
UNIT = 1 << BITS


def floor(x):
    return x.numerator // x.denominator


def ceil(x):
    return -((-x.numerator) // x.denominator)


def scaled(interval):
    return floor(UNIT * interval.lo), ceil(UNIT * interval.hi)


def binomial_weights(n):
    mass = 1
    for j in range(n + 1):
        yield mass
        if j < n:
            mass = mass * (n - j) // (j + 1)


@lru_cache(maxsize=8)
def lattice(knots, slopes, m):
    """Bounds on exp(h(z_j)) in units 2^-96, and the exact tree expectation enclosed."""
    n = m * m
    constants = intercepts(knots, slopes)
    steps = [scaled(exp_point(2 * s / m)) for s in slopes]
    nodes = []
    last = None
    lower_total = upper_total = 0
    for j, weight in enumerate(binomial_weights(n)):
        z = F(2 * j - n, m)
        i = bisect_right(knots, z)
        if i != last:
            lo, hi = scaled(exp_point(constants[i] + slopes[i] * z))
            last = i
        else:
            rlo, rhi = steps[i]
            lo = lo * rlo // UNIT
            hi = (hi * rhi + UNIT - 1) // UNIT
        nodes.append((lo, hi))
        lower_total += weight * lo
        upper_total += weight * hi
    denom = UNIT << n
    moment = I(F(lower_total, denom), F(upper_total, denom)).rounded(BITS)
    if moment.lo <= 0:
        raise ArithmeticError("Unproved positive binomial normalization")
    return nodes, moment


def payoffs(nodes, scale, discount, pairs, m):
    """Price calls and puts directly, with identical discount and terminal map."""
    n = m * m
    if len(nodes) != n + 1 or scale.lo <= 0 or discount <= 0:
        raise ValueError("Invalid lattice, scale or discount")
    strike_units = [p.k * UNIT for p in pairs]
    if any(k.denominator != 1 for k in strike_units):
        raise ValueError("This TXO panel runner expects dyadic strikes in index points")
    strikes = [int(k) for k in strike_units]
    lo_scale, hi_scale = scaled(scale)
    accum = [[0, 0, 0, 0] for _ in strikes]
    for weight, (lo, hi) in zip(binomial_weights(n), nodes):
        slo = lo_scale * lo // UNIT
        shi = (hi_scale * hi + UNIT - 1) // UNIT
        for k, a in zip(strikes, accum):
            if shi > k:
                a[1] += weight * (shi - k)
                if slo > k:
                    a[0] += weight * (slo - k)
            if slo < k:
                a[3] += weight * (k - slo)
                if shi < k:
                    a[2] += weight * (k - shi)
    denom = UNIT << n
    prices = {}
    for pair, (cl, cu, pl, pu) in zip(pairs, accum):
        prices[pair.call.id] = (discount * I(F(cl, denom), F(cu, denom))).rounded(BITS)
        prices[pair.put.id] = (discount * I(F(pl, denom), F(pu, denom))).rounded(BITS)
    return prices


def fixed_grid(knots, slopes, forward, discount, pairs, m):
    nodes, mean = lattice(knots, slopes, m)
    return payoffs(nodes, forward / mean, discount, pairs, m)


def combine_maps(pairs, low_prices, high_prices):
    """Terminal amount is ordered, so put order is reversed."""
    out = {}
    for p in pairs:
        c, u = p.call.id, p.put.id
        out[c] = I(low_prices[c].lo, high_prices[c].hi)
        out[u] = I(high_prices[u].lo, low_prices[u].hi)
    return out


def family_grid(knots, low_map, high_map, forward, discount, pairs, m):
    low_nodes, low_mean = lattice(knots, low_map, m)
    high_nodes, high_mean = lattice(knots, high_map, m)
    low = payoffs(low_nodes, I(forward.lo / high_mean.hi), discount, pairs, m)
    high = payoffs(high_nodes, I(forward.hi / low_mean.lo), discount, pairs, m)
    return combine_maps(pairs, low, high)
