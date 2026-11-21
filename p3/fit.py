"""Generate rational common-model witnesses. HiGHS only proposes transition laws."""

from fractions import Fraction as F
from math import erf, exp, pi, sqrt

from model import evaluate, intrinsic


def correct_law(grid, values, mean):
    import numpy as np

    v = np.maximum(np.asarray(values), 0)
    v = v / v.sum()
    k = max(range(len(v)), key=lambda j: v[j])
    if grid[k] == mean and v[k] > 1 - 1e-8:
        return {mean: F(1)}
    left = [j for j, x in enumerate(grid) if x < mean and v[j] > 0]
    right = [j for j, x in enumerate(grid) if x > mean and v[j] > 0]
    if not left or not right:
        if mean in grid:
            return {mean: F(1)}
        raise ValueError("No barycentric support at the requested mean")
    a = max(left, key=lambda j: v[j])
    b = max(right, key=lambda j: v[j])
    for den in (10**10, 10**13, 10**16):
        law = {x: F(round(float(v[j]) * den), den) for j, x in enumerate(grid) if j not in (a, b)}
        mass = 1 - sum(law.values())
        moment = mean - sum(x * w for x, w in law.items())
        high = (moment - grid[a] * mass) / (grid[b] - grid[a])
        law[grid[a]] = mass - high
        law[grid[b]] = high
        if min(law.values()) >= 0:
            return {x: w for x, w in law.items() if w}
    raise ArithmeticError("Rationalization failed")


def normal_payoff(kind, x, k, sd):
    diff = (x - k) * (1 if kind == "call" else -1)
    return diff * (1 + erf(diff / (sd * sqrt(2)))) / 2 + sd * exp(-0.5 * (diff / sd) ** 2) / sqrt(
        2 * pi
    )


def fit(m, tilt=0, goal=None, spot=None):
    import numpy as np
    from scipy.optimize import linprog
    from scipy.sparse import coo_matrix

    # A finite support is used exclusively for constructing inner witnesses.
    if spot is not None:
        from copy import copy

        m = copy(m)
        m.z = {"bid": m.zlo, "ask": m.zhi}[spot]
    strikes = sorted({c["K"] for c in m.contracts})
    gaps = sorted(b - a for a, b in zip(strikes, strikes[1:]))
    step = gaps[len(gaps) // 2] / 2 if gaps else m.z / 78
    center = round(m.z / step) * step
    nodes = {center + s * step for s in [-45, 50, *range(-22, 23)]}
    reserve = max(m.floor, F(0))
    grid = sorted({max(reserve, x) for x in nodes})
    center = float(center)
    if not grid[0] <= m.z <= grid[-1]:
        raise ValueError("Support does not bracket spot")
    n = len(grid)
    x = np.array([float(a) for a in grid])
    z = float(m.z)
    opts = m.contracts
    flows = n * n
    long = [c for c in opts if c["m"] == 1]
    aux = {c["id"]: flows + j * n for j, c in enumerate(long)}
    si = flows + len(long) * n
    width = si + 1
    ind = np.arange(flows).reshape(n, n)

    def arrays(rows):
        rr = []
        cc = []
        dd = []
        rhs = []
        for i, (idx, val, b) in enumerate(rows):
            idx = np.asarray(idx).ravel()
            val = np.broadcast_to(val, idx.shape).ravel()
            nz = val != 0
            rr.extend([i] * int(nz.sum()))
            cc.extend(idx[nz])
            dd.extend(val[nz])
            rhs.append(b)
        return coo_matrix((dd, (rr, cc)), shape=(len(rows), width)).tocsr(), np.array(rhs)

    def payoff(c, x, key="h"):
        return np.maximum(0, (x - float(c[key])) * (1 if c["kind"] == "call" else -1))

    allidx = ind.ravel()
    eq = [(allidx, 1, 1), (allidx, np.repeat(x - z, n), 0)]
    for j in range(n):
        eq.append((ind[j], x - x[j], 0))
    ae, be = arrays(eq)
    bounds = [(0, None)] * si + [(None, 0.5)]
    policy = {
        c["id"]: np.array(
            [
                float(intrinsic(c["kind"], y, c["h1"]))
                > normal_payoff(
                    c["kind"], float(y), float(c["h"]), max(1, z * 0.21 * sqrt(float(m.yeargap)))
                )
                for y in grid
            ]
        )
        for c in long
    }
    for iteration in range(14):
        rows = []

        def le(idx, val, b, margin=False, target=rows):
            ids = np.asarray(idx).ravel()
            vs = np.broadcast_to(val, ids.shape)
            if margin:
                ids = np.append(ids, si)
                vs = np.append(vs, 1.0)
            target.append((ids, vs, b))

        for c in opts:
            bid, ask = float(c["bid"]), float(c["ask"])
            le([si], [1], ask - float(intrinsic(c["kind"], m.z, c["h0"])))
            if c["m"] == 0:
                coeff = np.repeat(payoff(c, x), n)
                le(allidx, coeff, ask, True)
            else:
                start = aux[c["id"]]
                block = np.arange(start, start + n)
                stop = payoff(c, x, "h1")
                term = payoff(c, x)
                for j in range(n):
                    ij = np.append(ind[j], start + j)
                    le(ij, np.append(np.full(n, stop[j]), -1), 0)
                    le(ij, np.append(term, -1), 0)
                le(block, 1, ask, True)
                coeff = np.where(policy[c["id"]][:, None], stop[:, None], term[None, :]).ravel()
            if intrinsic(c["kind"], m.z, c["h0"]) >= c["bid"]:
                le([si], [1], float(intrinsic(c["kind"], m.z, c["h0"]) - c["bid"]))
            else:
                le(allidx, -coeff, -bid, True)
        a, b = arrays(rows)
        obj = np.zeros(width)
        obj[si] = -1
        if tilt:
            # Break ties towards different European vectors while retaining a positive margin.
            obj[allidx] = tilt * np.tile(np.maximum(x - center, 0), n)
        res = linprog(obj, A_ub=a, b_ub=b, A_eq=ae, b_eq=be, bounds=bounds, method="highs")
        if not res.success:
            raise RuntimeError(res.message)
        if goal is not None and res.x[si] > 1.0e-6:
            # Refine an attainable projected extremum for this policy. Upper Snell epigraphs
            # and an explicit lower policy remain imposed on all strikes simultaneously.
            tag, sign, arg = goal
            guarded = bounds.copy()
            guarded[si] = (min(1e-4, float(res.x[si]) / 4), None)

            def minimize_flows(weights, inequality_matrix=a, rhs=b, box=guarded):
                obj2 = np.zeros(width)
                obj2[:flows] = weights
                rr = linprog(
                    obj2,
                    A_ub=inequality_matrix,
                    b_ub=rhs,
                    A_eq=ae,
                    b_eq=be,
                    bounds=box,
                    method="highs",
                )
                if not rr.success:
                    raise RuntimeError(rr.message)
                return rr

            if tag == "euro":
                quote = next(c for c in opts if c["id"] == arg)
                single = payoff(quote, x)
                res = minimize_flows(
                    sign * (np.repeat(single, n) if quote["m"] == 0 else np.tile(single, n))
                )
            elif tag == "ratio":
                k, delta = map(float, arg)
                centre = np.maximum(x - k, 0)
                numerator = 2 * (np.tile(centre, n) - np.repeat(centre, n)) / float(m.yeargap)
                curvature = (
                    np.maximum(x - (k - delta), 0) - 2 * centre + np.maximum(x - (k + delta), 0)
                )
                denominator = k * k / (delta * delta) * np.repeat(curvature, n)
                alpha = 0.0
                for _ in range(14):
                    res = minimize_flows(sign * (numerator - alpha * denominator))
                    mass = res.x[:flows]
                    den = denominator @ mass
                    if den <= 1e-10:
                        raise ValueError("Unresolved witness curvature")
                    nxt = (numerator @ mass) / den
                    if abs(nxt - alpha) < 1e-11:
                        break
                    alpha = nxt
            else:
                raise ValueError("Unknown fit objective")
        w = np.maximum(0, res.x[:flows].reshape(n, n))
        mx = w.sum(axis=1)
        if res.x[si] > 1e-7:
            first = correct_law(grid, mx, m.z)
            states = {}
            for j, y in enumerate(grid):
                if y not in first:
                    continue
                trans = correct_law(grid, w[j], y)
                states[str(y)] = dict(
                    p=str(first[y]), next={str(k): str(p) for k, p in trans.items()}
                )
            result = dict(z=str(m.z), states=states)
            evaluate(m, result)
            return result
        changed = False
        for c in long:
            updated = payoff(c, x, "h1") * mx > w @ payoff(c, x) + 1e-10
            changed |= np.any(updated != policy[c["id"]])
            policy[c["id"]] = updated
        if not changed:
            break
    raise RuntimeError("No certified witness found in the proposed support/policies")
