"""Uniform P2 per-contract certificates for normalized European calls."""

from bisect import bisect_right
from dataclasses import dataclass
from fractions import Fraction as F
from functools import lru_cache
from math import ceil
import csv
from .interval import black_call, exp_point
from .p2_mesh import mesh, endpoint


def rat(x):
    if isinstance(x, bool) or not isinstance(x, (F, str, int)):
        raise ValueError("Use integer or quoted rational/decimal values")
    return F(x)


@dataclass(frozen=True)
class Bands:
    edges: tuple
    rows: tuple

    @classmethod
    def read(cls, doc):
        if doc.get("schema") != "p2-variance-bands-v1":
            raise ValueError("Unknown variance band schema")
        edges = tuple(map(rat, doc["spot_edges"]))
        if any(x <= 0 for x in edges) or any(l >= r for l, r in zip(edges, edges[1:])):
            raise ValueError("Spot edges must be positive and strictly increasing")
        rows = []
        last = F(0)
        for row in doc["slabs"]:
            end = rat(row["end"])
            lo, hi = (tuple(map(rat, row[key])) for key in ("lower", "upper"))
            if (
                end <= last
                or len(lo) != len(edges) + 1
                or len(hi) != len(lo)
                or any(not 0 < l <= r for l, r in zip(lo, hi))
            ):
                raise ValueError("Invalid variance slab or incomplete tails")
            rows.append((end, (lo, hi)))
            last = end
        if not rows:
            raise ValueError("At least one variance slab is required")
        return cls(edges, tuple(rows))

    def until(self, t):
        if not 0 < t <= self.rows[-1][0]:
            raise ValueError("Maturity outside the variance band horizon")
        result = []
        last = F(0)
        for end, band in self.rows:
            result.append((min(end, t) - last, band, last))
            if end >= t:
                break
            last = end
        return result


def read_prices(path, quotes):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    prices = {}
    expected = {q.id: (q.t, q.k) for q in quotes}
    for row in rows:
        key = row["id"]
        if key in prices or expected.get(key) != (rat(row["t"]), rat(row["k"])):
            raise ValueError("Duplicate or mismatched numerical quote: " + key)
        prices[key] = rat(row["price"])
    if set(prices) != set(expected):
        raise ValueError("Numerical prices and quotes have different IDs")
    return prices


def interval(lo, hi):
    if lo > hi:
        raise ArithmeticError("Inconsistent independently certified bounds")
    return [lo, hi]


def intersect(*bounds):
    return interval(max(b[0] for b in bounds), min(b[1] for b in bounds))


@lru_cache(maxsize=16384)
def time_value(spot, k, variance):
    if spot is None or spot == 0:
        return F(0)
    intrinsic = max(F(0), spot - k)
    # Inverse and forward moment estimates also converge in the deep wings
    # below the precision of the rational normal-CDF routine.
    moment = F(2) ** ceil(2 * variance)  # exp(v) <= 2**ceil(2v)
    coarse = min(spot, k, spot * spot * moment / (4 * k), k * k * moment / (4 * spot))
    return min(coarse, spot * black_call(k / spot, variance).hi - intrinsic)


@lru_cache(maxsize=16384)
def hit_probability(edge, v):
    """Doob bound for the first hit from spot one under an integrated variance cap."""
    if edge is None or edge == 0:
        return F(0)
    if edge == 1:
        return F(1)
    upper = edge > 1
    best = F(1)
    for power in range(1, 65):
        exponent = power * (power - 1 if upper else power + 1) * v / 2
        if exponent > 24:
            break
        factor = edge ** (-power if upper else power)
        best = min(best, factor * exp_point(exponent).hi)
    return best


@lru_cache(maxsize=8192)
def exit_budget(left, right, k, v):
    """Split the deterministic variance budget into four time windows."""
    full = max(time_value(s, k, v) for s in (left, right))
    cost = F(0)
    for s in (left, right):
        if s is None or not s:
            continue
        caps = []
        for j in range(4):
            cap = time_value(s, k, v * (4 - j) / 4)
            caps.append(min(cap, caps[-1]) if caps else cap)
        caps.append(F(0))
        cost += sum((caps[j] - caps[j + 1]) * hit_probability(s, v * (j + 1) / 4) for j in range(4))
    return min(full, cost)


def black_strips(bands, slabs, q, side):
    edges = (F(0),) + bands.edges + (None,)
    global_v = sum(dt * max(b[side]) for dt, b, _ in slabs)
    # Full domain, then the innermost strip and symmetric successive expansions.
    # The proof applies separately to every strip actually visited.
    left = (
        bisect_right(bands.edges, F(1)) - 1
        if F(1) in bands.edges
        else bisect_right(bands.edges, F(1))
    )
    right = bisect_right(bands.edges, F(1)) + 1
    strips = {(0, len(edges) - 1)}
    while True:
        strips.add((left, right))
        if left == 0 and right == len(edges) - 1:
            break
        left = max(0, left - 1)
        right = min(len(edges) - 1, right + 1)
    low, high = max(F(0), 1 - q.k), F(1)
    for l, r in sorted(strips):
        vmin = sum(dt * min(b[side][l:r]) for dt, b, _ in slabs)
        vmax = sum(dt * max(b[side][l:r]) for dt, b, _ in slabs)
        tail_low = exit_budget(edges[l], edges[r], q.k, vmin)
        tail_high = exit_budget(edges[l], edges[r], q.k, global_v)
        low = max(low, black_call(q.k, vmin).lo - tail_low)
        high = min(high, black_call(q.k, vmax).hi + tail_high)
    return interval(low, high)


def certify(
    bands,
    quotes,
    prices,
    *,
    left=F(1, 2),
    right=F(3, 2),
    cells=16,
    steps=4,
    levels=1,
    target=None,
    method="float",
    bits=48,
    max_work=200000,
    auto_domain=False,
    domain_tol=None,
    replay=None,
):
    if (
        not 0 < left < 1 < right
        or min(cells, steps, levels, bits, max_work) < 1
        or method not in ("float", "exact")
        or (target is not None and target <= 0)
        or (domain_tol is not None and domain_tol <= 0)
        or (domain_tol is not None and not auto_domain)
        or (auto_domain and target is None and domain_tol is None)
    ):
        raise ValueError("Invalid grid, solver or target")
    if not quotes or any(not left < q.k < right for q in quotes) and not auto_domain:
        raise ValueError("Provide quotes strictly inside the stopped domain")
    if len({q.id for q in quotes}) != len(quotes) or set(prices) != {q.id for q in quotes}:
        raise ValueError("Quote IDs and numerical prices must match")
    if any(
        q.style != "european" or not (q.t > 0 and q.k > 0 and 0 <= q.bid <= q.ask) for q in quotes
    ):
        raise ValueError("Expected valid European quotes")
    if auto_domain:
        domain_tol = domain_tol if domain_tol is not None else target / 4
        left = min(left, min(q.k for q in quotes) / 2)
        right = max(right, max(q.k for q in quotes) * 2)
    data = []
    for q in quotes:
        slabs = bands.until(q.t)
        v = sum(dt * max(b[1]) for dt, b, _ in slabs)
        if auto_domain:
            while time_value(left, q.k, v) > domain_tol:
                left /= 2
            while time_value(right, q.k, v) > domain_tol:
                right *= 2
        analytic = [black_strips(bands, slabs, q, side) for side in (0, 1)]
        data.append((q, slabs, v, analytic))
    results = []
    total = 0
    for q, slabs, v, analytic in data:
        enclosures = [x.copy() for x in analytic]
        history = []
        p = prices[q.id]
        tail = exit_budget(left, right, q.k, v)
        for level in range(levels):
            n = steps * 2**level
            count = cells * 4**level
            sides = 1 if all(b[0] == b[1] for _, b, _ in slabs) else 2
            # Upper bound on generated node count, checked before allocation.
            cost = (count + len(bands.edges) + 4) * len(slabs) * n * sides
            if total + cost > max_work:
                break
            grid = mesh(left, right, count, bands.edges, q.k)
            index = [bisect_right(bands.edges, (l + r) / 2) for l, r in zip(grid, grid[1:])]
            total += cost
            records = []
            for side in range(sides):
                rows = (
                    None
                    if replay is None
                    else replay[q.id][level]["endpoints"][side]["grid_put_rows"]
                )
                e = endpoint(grid, index, slabs, side, q.k, n, method, bits + 8 * level, rows)
                e["reported_price_minus_chain"] = p - e["center"]
                raw = [e["center"] - e["error"], e["center"] + e["error"] + tail]
                enclosures[side] = intersect(enclosures[side], raw)
                records.append(e)
            if sides == 1:
                enclosures[1] = enclosures[0].copy()
            history.append(dict(level=level, nodes=len(grid), steps_per_slab=n, endpoints=records))
            if target is not None and max(p - enclosures[0][0], enclosures[1][1] - p) <= target:
                break
        low, high = interval(enclosures[0][0], enclosures[1][1])
        eta = max(p - low, high - p)
        floor = max(F(0), p - enclosures[0][1], enclosures[1][0] - p)
        if low >= q.bid and high <= q.ask:
            status = "all_in_spread"
        elif high < q.bid or low > q.ask:
            status = "all_outside_spread"
        else:
            status = "undecided"
        results.append(
            dict(
                id=q.id,
                t=q.t,
                k=q.k,
                bid=q.bid,
                ask=q.ask,
                numerical_price=p,
                continuous_price=[low, high],
                grid_spread_violation=max(F(0), q.bid - p, p - q.ask),
                continuous_spread_violation_upper=max(F(0), q.bid - low, high - q.ask),
                eta=eta,
                necessary_grid_bid_ask=[q.bid - eta, q.ask + eta],
                uniform_midpoint=(low + high) / 2,
                uniform_midpoint_eta=(high - low) / 2,
                fixed_price_eta_lower_bound=floor,
                market_status=status,
                domain_tail=tail,
                analytic_endpoint_intervals=analytic,
                endpoint_intervals=enclosures,
                levels=history,
                target_met=None if target is None else eta <= target,
                mesh_status="work_budget"
                if not history or (len(history) < levels and (target is None or eta > target))
                else "checked",
            )
        )
    # The same endpoint coefficient (lower, respectively upper) is used for every maturity.
    common_upper = []
    for side in (0, 1):
        common_upper.append(
            max(
                max(
                    F(0),
                    r["bid"] - r["endpoint_intervals"][side][0],
                    r["endpoint_intervals"][side][1] - r["ask"],
                )
                for r in results
            )
        )
    fit_lower = max(
        max(F(0), r["bid"] - r["continuous_price"][1], r["continuous_price"][0] - r["ask"])
        for r in results
    )
    fit_upper = min(common_upper)
    if fit_lower > fit_upper:
        raise ArithmeticError("Inconsistent minimax fit bounds")
    return dict(
        schema="p2-uniform-report-v1",
        scope="all_diffusions_in_declared_pointwise_variance_bands",
        optimization=dict(
            objective="maximum_absolute_normalized_spread_violation",
            global_optimum=[fit_lower, fit_upper],
            optimality_gap=fit_upper - fit_lower,
            common_endpoint_upper=common_upper,
            numerical_fit=max(r["grid_spread_violation"] for r in results),
        ),
        normalized_spot=1,
        domain=[left, right],
        quotes=results,
        all_in_spreads=all(r["market_status"] == "all_in_spread" for r in results),
        target_met=None if target is None else all(r["target_met"] for r in results),
        work_reserved=total,
    )
