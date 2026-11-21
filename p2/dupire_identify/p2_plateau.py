"""Exact rectangular bounds for the repository's quintic plateau parameterization."""

from bisect import bisect_right
from .p2_uniform import Bands, rat


def from_plateau(cfg, subcells=2):
    if cfg.get("kind") != "piecewise_quintic_plateau_diffusion_v1" or subcells < 1:
        raise ValueError("Expected a piecewise quintic P1 model and positive subdivision")
    amin, amax = rat(cfg["amin"]), rat(cfg["amax"])
    base = list(map(rat, cfg["strike_knots"]))
    t0, a0 = rat(cfg["prefix_end"]), rat(cfg["prefix_variance"])
    if (
        not 0 < amin <= a0 <= amax
        or t0 <= 0
        or len(base) < 2
        or base[0] <= 0
        or any(l >= r for l, r in zip(base, base[1:]))
    ):
        raise ValueError("Invalid plateau prefix")
    knots = set(base)
    phases = []
    last = t0
    for p in cfg["phases"]:
        grid = list(map(rat, p.get("knots", base)))
        vals = list(map(rat, p["variance"]))
        end = rat(p["right"])
        if (
            rat(p["left"]) != last
            or end <= last
            or len(grid) != len(vals)
            or len(grid) < 2
            or grid[0] != base[0]
            or grid[-1] != base[-1]
            or any(l >= r for l, r in zip(grid, grid[1:]))
            or any(not amin <= v <= amax for v in vals)
        ):
            raise ValueError("Invalid quintic phase")
        phases.append((end, grid, vals))
        for l, r in zip(grid, grid[1:]):
            knots.update(l + (r - l) * i / subcells for i in range(subcells))
        knots.add(grid[-1])
        last = end
    edges = sorted(knots)
    rows = [dict(end=t0, lower=[a0] * (len(edges) + 1), upper=[a0] * (len(edges) + 1))]
    for end, grid, vals in phases:

        def value(x):
            if x <= grid[0]:
                return vals[0]
            if x >= grid[-1]:
                return vals[-1]
            j = bisect_right(grid, x) - 1
            u = (x - grid[j]) / (grid[j + 1] - grid[j])
            return vals[j] + (vals[j + 1] - vals[j]) * u**3 * (10 - 15 * u + 6 * u * u)

        at = [vals[0], *(value(x) for x in edges), vals[-1]]
        rows.append(
            dict(
                end=end,
                lower=[min(l, r) for l, r in zip(at, at[1:])],
                upper=[max(l, r) for l, r in zip(at, at[1:])],
            )
        )
    out = dict(schema="p2-variance-bands-v1", spot_edges=edges, slabs=rows)
    Bands.read(out)
    return out
