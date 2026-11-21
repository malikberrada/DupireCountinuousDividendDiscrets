"""Operational-time bounds for deterministic variance clocks and a specified state cutoff."""

from fractions import Fraction as F
from math import ceil, erfc, exp, floor, pi, sqrt

from outer import read_interval

from pointwise.calendar_model import days_between
from pointwise.gaussian import BASE, density, sqrt_hi, sqrt_lo
from pointwise.identified import target


def normal_vanilla(z, k, kind, v):
    gap = z - k
    intrinsic = max(F(0), gap if kind == "call" else -gap)
    if v == 0:
        return intrinsic, intrinsic
    s = sqrt_lo(v)
    if s == 0:
        return intrinsic, intrinsic + sqrt_hi(v)
    x = abs(gap) / s
    serr = sqrt_hi(v) - s
    if x >= 8:
        return intrinsic, intrinsic + s * F(density(F(8))[1], BASE) + serr
    n = max(1, ceil(24 * x))
    d = x / n
    vals = [density(d * j / 2) for j in range(2 * n + 1)]
    weights = [1] + [4 if j % 2 else 2 for j in range(1, 2 * n)] + [1]
    rem = 16 * x * d**4 / 2880
    il = d * sum(w * ab[0] for w, ab in zip(weights, vals)) / (6 * BASE) - rem
    ih = d * sum(w * ab[1] for w, ab in zip(weights, vals)) / (6 * BASE) + rem
    lo = s * F(vals[-1][0], BASE) - abs(gap) * (F(1, 2) - il)
    hi = s * F(vals[-1][1], BASE) - abs(gap) * (F(1, 2) - ih)
    return intrinsic + max(0, lo), intrinsic + hi + serr


def eu_bounds(book, p, cert):
    return {
        k: tuple(
            x * book.market.prem
            for x in read_interval(p, p.european[k], cert["european_proofs"][k])
        )
        for k in p.european
    }


def budget(book, cap):
    # Common, independent of the fit parameters and of the spot inside the bid/ask.
    distance = book.market.zlo - book.flat_from
    if distance <= 0:
        raise ValueError("The whole underlying spread must exceed the cutoff")
    return 2 * sqrt_hi(cap * min(F(1), 2 * (1 + distance**2 / (2 * cap * 256)) ** (-256)), 10**12)


def floating_price(z, c, v):
    d = (z - float(c["h"])) * (1 if c["kind"] == "call" else -1)
    if v <= 0:
        return max(0.0, d)
    s = sqrt(v)
    u = d / s
    return d * 0.5 * erfc(-u / sqrt(2)) + s * exp(-u * u / 2) / sqrt(2 * pi)


def propose(book, p, cert, slices=8):
    cap = F(96)
    err = float(budget(book, cap))
    bounds = eu_bounds(book, p, cert)
    m = book.market

    def inverse(z, c, y):
        lo = 0.0
        hi = float(cap)
        for _ in range(44):
            v = (lo + hi) / 2
            if floating_price(float(z), c, v) < y:
                lo = v
            else:
                hi = v
        return (lo + hi) / 2

    rows = []
    for i in range(slices):
        za = m.zlo + (m.zhi - m.zlo) * i / slices
        zb = m.zlo + (m.zhi - m.zlo) * (i + 1) / slices
        segments = []
        for stage in (0, 1):
            lower = (F(0), None)
            upper = (cap, None)
            for c in m.contracts:
                if c["m"] != stage:
                    continue
                best, worst = (zb, za) if c["kind"] == "call" else (za, zb)
                l, u = bounds[c["id"]]
                lv = F(floor(inverse(best, c, float(l) - err) * 10000) - 2, 10000)
                hv = F(ceil(inverse(worst, c, float(u) + err) * 10000) + 2, 10000)
                if lv > lower[0]:
                    lower = (lv, c["id"])
                if hv < upper[0]:
                    upper = (hv, c["id"])
            segments.append(
                {"lo": str(lower[0]), "lo_isin": lower[1], "hi": str(upper[0]), "hi_isin": upper[1]}
            )
        rows.append(segments)
    return {"cap": str(cap), "slices": rows}


def check_ranges(book, p, cert, proof):
    """Prove operational-variance bounds for any positive deterministic speed and the fixed cutoff."""
    m = book.market
    cap = F(proof["cap"])
    if not cap > 0:
        raise ValueError("Invalid operational-time cap")
    err = budget(book, cap)
    bounds = eu_bounds(book, p, cert)
    lookup = {c["id"]: c for c in m.contracts}
    for j in (0, 1):
        proved = False
        for c in m.contracts:
            if c["m"] != j:
                continue
            worst = m.zlo if c["kind"] == "call" else m.zhi
            if normal_vanilla(worst, c["h"], c["kind"], cap)[0] - err > bounds[c["id"]][1]:
                proved = True
                break
        if not proved:
            raise ValueError("Total variance cap unproved")
    boxes = []
    slices = proof["slices"]
    if not slices:
        raise ValueError("No spot coverage")
    for i, segments in enumerate(slices):
        za = m.zlo + (m.zhi - m.zlo) * i / len(slices)
        zb = m.zlo + (m.zhi - m.zlo) * (i + 1) / len(slices)
        if len(segments) != 2:
            raise ValueError("Both maturities required")
        box = []
        for j, g in enumerate(segments):
            for side in ("lo", "hi"):
                v = F(g[side])
                key = g[side + "_isin"]
                if not 0 <= v <= cap:
                    raise ValueError("Variance bound outside cap")
                if key is None:
                    if v != (0 if side == "lo" else cap):
                        raise ValueError("Missing certificate for range endpoint")
                    continue
                c = lookup[key]
                if c["m"] != j:
                    raise ValueError("Wrong maturity on variance bound")
                best, worst = (zb, za) if c["kind"] == "call" else (za, zb)
                if side == "lo":
                    if normal_vanilla(best, c["h"], c["kind"], v)[1] + err >= bounds[key][0]:
                        raise ValueError("Unproved variance floor " + key)
                elif normal_vanilla(worst, c["h"], c["kind"], v)[0] - err <= bounds[key][1]:
                    raise ValueError("Unproved variance ceiling " + key)
            box.append((F(g["lo"]), F(g["hi"])))
        if all(l <= h for l, h in box):
            boxes.append(box)
    if not boxes:
        raise ValueError("All spot intervals were excluded")
    return boxes


def variance_at(book, at, level, coordinate, boxes):
    _, den = target(book, at, level, coordinate)
    t = days_between(book.t0, at)
    t1 = book.ages[1 + book.dates.index(book.market.expiries[0])]
    t2 = book.ages[-1]
    w = (2 * t - t1) / (t2 - t1)
    coef = [(1 - w) / t1, w / t2]
    intervals = []
    for box in boxes:
        parts = [sorted((c * l, c * h)) for c, (l, h) in zip(coef, box)]
        intervals.append((sum(a for a, b in parts), sum(b for a, b in parts)))
    return max(0, min(l for l, h in intervals)) * 365 / den**2, max(
        h for l, h in intervals
    ) * 365 / den**2


def lipschitz_at(book, at, level, coordinate, boxes, limit):
    """Any positive deterministic variance speed with this Lipschitz constant and the fixed state cutoff."""
    limit = F(limit)
    if limit < 0:
        raise ValueError("The variance-speed Lipschitz bound must be nonnegative")
    _, den = target(book, at, level, coordinate)
    t = days_between(book.t0, at)
    t1 = book.ages[1 + book.dates.index(book.market.expiries[0])]
    t2 = book.ages[-1]

    def mean_distance(left, right):
        if t <= left:
            return (left + right) / 2 - t
        if t >= right:
            return t - (left + right) / 2
        return ((t - left) ** 2 + (right - t) ** 2) / (2 * (right - left))

    kept = []
    for (l1, h1), (l2, h2) in boxes:
        ranges = [(F(0), t1, l1, h1), (t1, t2, l2 - h1, h2 - l1), (F(0), t2, l2, h2)]
        low = F(0)
        high = None
        for start, end, l, h in ranges:
            pad = limit * mean_distance(start, end)
            low = max(low, l / (end - start) - pad)
            upper = h / (end - start) + pad
            high = upper if high is None else min(high, upper)
        if low <= high:
            kept.append((low, high))
    if not kept:
        return None
    factor = 365 / den**2
    return min(a for a, b in kept) * factor, max(b for a, b in kept) * factor
