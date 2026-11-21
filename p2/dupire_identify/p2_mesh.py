"""Stopped natural-scale diffusion. Float solves are proposals; all checks use rationals."""

from fractions import Fraction as F
from math import ceil, isqrt

ZERO = F(0)


def sqrt_up(value, bits):
    """Outward square root with precision that can increase with refinement."""
    scale = 1 << bits
    k = isqrt(value.numerator * scale * scale // value.denominator)
    return F(k if k * k * value.denominator == value.numerator * scale * scale else k + 1, scale)


def mesh(left, right, cells, edges, strike):
    """The kink, initial spot and discontinuities are actual nodes."""
    anchors = sorted({left, right, F(1), strike, *(x for x in edges if left < x < right)})
    step = (right - left) / cells
    grid = [left]
    for l, r in zip(anchors, anchors[1:]):
        count = ceil((r - l) / step)
        grid.extend(l + (r - l) * i / count for i in range(1, count + 1))
    return grid


def generator(grid, variance):
    """Bounds on the speed-measure mean exit time in each two-cell interval."""
    lower, upper = [ZERO], [ZERO]
    relative = ZERO
    for j in range(1, len(grid) - 1):
        l, x, r = grid[j - 1 : j + 2]
        dl, dr = x - l, r - x
        w, v = dr / (dl + dr), dl / (dl + dr)
        a, b = variance[j - 1 : j + 1]
        ml, mr = w * dl * dl / a, v * dr * dr / b
        mlo, mhi = ml / (x * x) + mr / (r * r), ml / (l * l) + mr / (x * x)
        m = (mlo + mhi) / 2
        relative = max(relative, (mhi - mlo) / (2 * m))
        lower.append(w / m)
        upper.append(v / m)
    return lower + [ZERO], upper + [ZERO], relative


def factor_solver(lower, upper, dt, method, bits):
    left = [dt * x for x in lower]
    right = [dt * x for x in upper]
    diag = [1 + l + r for l, r in zip(left, right)]
    if method == "float":
        import numpy as np
        from scipy.linalg import solve_banded

        matrix = np.zeros((3, len(diag)))
        matrix[0, 1:] = [-float(x) for x in right[:-1]]
        matrix[1] = [float(x) for x in diag]
        matrix[2, :-1] = [-float(x) for x in left[1:]]

        def solve(values):
            result = solve_banded((1, 1), matrix, np.asarray(values, dtype=float))
            return [values[0], *(F.from_float(float(v)) for v in result[1:-1]), values[-1]]

        return solve

    weights = [ZERO] * len(diag)
    for i in range(1, len(diag)):
        weights[i] = left[i] / diag[i - 1]
        diag[i] -= weights[i] * right[i - 1]
    scale = 1 << bits

    def solve(values):
        row = values.copy()
        for i in range(1, len(row)):
            row[i] += weights[i] * row[i - 1]
        row[-1] /= diag[-1]
        for i in range(len(row) - 2, -1, -1):
            row[i] = (row[i] + right[i] * row[i + 1]) / diag[i]
        return [values[0], *(F(round(x * scale), scale) for x in row[1:-1]), values[-1]]

    return solve


def spline(grid, values, variance=None):
    """C1 cubic Hermite in Bernstein form. Slopes use the nonuniform quadratic stencil."""
    dx = [r - l for l, r in zip(grid, grid[1:])]
    sec = [(v - u) / h for u, v, h in zip(values, values[1:], dx)]
    weight = dx if variance is None else [h / a for h, a in zip(dx, variance)]
    slope = (
        [sec[0]]
        + [
            (sec[i - 1] * weight[i] + sec[i] * weight[i - 1]) / (weight[i - 1] + weight[i])
            for i in range(1, len(sec))
        ]
        + [sec[-1]]
    )
    return [
        (
            values[i],
            values[i] + h * slope[i] / 3,
            values[i + 1] - h * slope[i + 1] / 3,
            values[i + 1],
        )
        for i, h in enumerate(dx)
    ]


def diffusion_term(control, l, r, variance):
    """Bernstein coefficients of a*x^2*S''/2 on a single cell."""
    b0, b1, b2, b3 = control
    k0 = 3 * variance * (b2 - 2 * b1 + b0) / (r - l) ** 2
    k1 = 3 * variance * (b3 - 2 * b2 + b1) / (r - l) ** 2
    return (
        l * l * k0,
        (2 * l * r * k0 + l * l * k1) / 3,
        (r * r * k0 + 2 * l * r * k1) / 3,
        r * r * k1,
    )


def endpoint(grid, index, slabs, side, strike, steps, method, bits, trace=None):
    values = [max(ZERO, strike - x) for x in grid]
    saved = []
    if trace is not None and len(trace) != len(slabs) * steps:
        raise ValueError("Incorrect number of witness rows")
    previous = spline(grid, values)
    # Payoff is linear on each cell because the strike is a mesh node.
    initial = max(
        abs(old - ((3 - i) * u + i * v) / 3)
        for ctrl, u, v in zip(previous, values, values[1:])
        for i, old in enumerate(ctrl)
    )
    defect = disc = space = temporal = ZERO
    h = max(b - a for a, b in zip(grid, grid[1:]))
    for duration, band, _ in reversed(slabs):
        variance = [band[side][j] for j in index]
        lower, upper, relative = generator(grid, variance)
        widths = [duration * ((i + 1) ** 3 - i**3) / steps**3 for i in range(steps)]
        space += steps * (2 * h + strike * relative)
        # A stopped spot is bounded and its diffusion coefficient is at most R*sqrt(A).
        precision = max(112, bits + 8)
        temporal += grid[-1] * sqrt_up(
            max(variance) * sqrt_up(sum(dt * dt for dt in widths), precision), precision
        )
        for dt in widths:
            if trace is None:
                new = factor_solver(lower, upper, dt, method, bits)(values)
            else:
                new = list(map(F, trace[len(saved)]))
                if len(new) != len(grid) or new[0] != values[0] or new[-1] != values[-1]:
                    raise ValueError("Invalid stopped boundary or witness dimensions")
            saved.append(list(map(str, new)))
            current = spline(grid, new, variance)
            d = (
                [ZERO]
                + [
                    new[j]
                    - values[j]
                    - dt * (lower[j] * (new[j - 1] - new[j]) + upper[j] * (new[j + 1] - new[j]))
                    for j in range(1, len(grid) - 1)
                ]
                + [ZERO]
            )
            defect += max(map(abs, d))
            rho0 = rho1 = ZERO
            for j, (l, r) in enumerate(zip(grid, grid[1:])):
                c0, c1 = previous[j], current[j]
                term0 = diffusion_term(c0, l, r, variance[j])
                term1 = diffusion_term(c1, l, r, variance[j])
                for i in range(4):
                    delta = c1[i] - c0[i] - ((3 - i) * d[j] + i * d[j + 1]) / 3
                    rho0 = max(rho0, abs(delta - dt * term0[i]))
                    rho1 = max(rho1, abs(delta - dt * term1[i]))
            disc += (rho0 + rho1) / 2
            values, previous = new, current
    center = values[grid.index(F(1))] + 1 - strike
    pde = initial + disc
    apriori = space + temporal
    return dict(
        center=center,
        grid_put_rows=saved,
        initial=initial,
        space_time_residual=disc,
        linear_solve=defect,
        resolvent_space=space,
        erlang_time=temporal,
        error=defect + min(pde, apriori),
        method="hermite_residual" if pde <= apriori else "resolvent_bound",
    )


def reference_price(grid, index, slabs, strike, steps, method, bits):
    """Independent numerical proposal for the midpoint coefficient of the input bands."""
    values = [max(ZERO, strike - x) for x in grid]
    for duration, (lo, hi), _ in reversed(slabs):
        variance = [(lo[j] + hi[j]) / 2 for j in index]
        lower, upper, _ = generator(grid, variance)
        solve = factor_solver(lower, upper, duration / steps, method, bits)
        for _ in range(steps):
            values = solve(values)
    return values[grid.index(F(1))] + 1 - strike
