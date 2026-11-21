"""Exact LP dual checks for an outer P1 problem on represented mixture weights."""

from fractions import Fraction as F


def rows_for_reports(reports):
    if not reports:
        raise ValueError("At least one P2 proof is required")
    books = []
    for report in reports:
        book = {r["id"]: r for r in report["quotes"]}
        if not book or len(book) != len(report["quotes"]):
            raise ValueError("Invalid contract book")
        books.append(book)
    rows, rhs = [], []
    for key, ref in books[0].items():
        identity = tuple(ref[k] for k in ("t", "k", "bid", "ask"))
        if any(
            set(book) != set(books[0])
            or tuple(book[key][k] for k in ("t", "k", "bid", "ask")) != identity
            for book in books
        ):
            raise ValueError("P2 proofs must refer to the same observations")
        intervals = [book[key]["continuous_price"] for book in books]
        rows.extend([[F(iv[0]) for iv in intervals], [-F(iv[1]) for iv in intervals]])
        rhs.extend([F(ref["ask"]), -F(ref["bid"])])
    return rows, rhs


def dot(a, b):
    if len(a) != len(b):
        raise ValueError("LP dimension mismatch")
    return sum((x * y for x, y in zip(a, b)), F(0))


def checked_bound(rows, rhs, c, y, w):
    if len(y) != len(rows) or any(v < 0 for v in y):
        raise ValueError("Invalid dual multipliers")
    lag = [v + dot(y, col) for v, col in zip(c, zip(*rows))]
    bound = min(lag) - dot(rhs, y)
    primal = None
    if w is not None:
        if (
            len(w) != len(c)
            or sum(w) != 1
            or min(w) < 0
            or any(dot(a, w) > b for a, b in zip(rows, rhs))
        ):
            raise ValueError("Infeasible proposed rational primal")
        primal = dot(c, w)
        if primal < bound:
            raise ArithmeticError("Weak duality failed")
    return dict(
        lower=bound,
        dual=y,
        weights=w,
        primal=primal,
        outer_lp_gap=None if primal is None else primal - bound,
    )


def optimize(reports, c, weights=None, replay=None):
    rows, rhs = rows_for_reports(reports)
    if len(c) != len(reports):
        raise ValueError("One objective coefficient per P2 proof required")
    bounds = {}
    for direction, objective in (("minimum", c), ("negative_maximum", [-x for x in c])):
        if replay is not None:
            proof = replay[direction]
            y = list(map(F, proof["dual"]))
            w = None if proof["weights"] is None else list(map(F, proof["weights"]))
        else:
            from scipy.optimize import linprog

            res = linprog(
                list(map(float, objective)),
                A_ub=[[float(x) for x in a] for a in rows],
                b_ub=list(map(float, rhs)),
                A_eq=[[1.0] * len(c)],
                b_eq=[1.0],
                bounds=(0, 1),
                method="highs",
            )
            y = [F(0)] * len(rows)
            w = weights
            if res.success:
                y = [max(F(0), F.from_float(-float(v))) for v in res.ineqlin.marginals]
                for limit in (10**6, 10**12):
                    trial = [F(float(v)).limit_denominator(limit) for v in res.x]
                    trial[max(range(len(c)), key=lambda i: trial[i])] += 1 - sum(trial)
                    if min(trial) >= 0 and all(dot(a, trial) <= b for a, b in zip(rows, rhs)):
                        if w is None or dot(objective, trial) < dot(objective, w):
                            w = trial
                        break
        bounds[direction] = checked_bound(rows, rhs, objective, y, w)
    low = bounds["minimum"]["lower"]
    high = -bounds["negative_maximum"]["lower"]
    return dict(objective_outer=[low, high], proves_empty=low > high, proofs=bounds)


def window_outer(report, band_doc, window, cells):
    """Invoke the existing continuous weak P1 enclosure on certified observations."""
    from .continuous import Window, outer_bounds
    from .io import Quote
    from .p2_uniform import Bands

    bands = Bands.read(band_doc)
    w = Window.make(*window)
    if w.t + w.ht > bands.rows[-1][0]:
        raise ValueError("P1 kernel extends beyond declared variance priors")
    amin = min(min(b[0]) for _, b in bands.rows)
    amax = max(max(b[1]) for _, b in bands.rows)
    revised = []
    for p in report["quotes"]:
        lo = max(F(p["bid"]), F(p["continuous_price"][0]))
        hi = min(F(p["ask"]), F(p["continuous_price"][1]))
        if lo > hi:
            return dict(
                scope="market_feasible_subset_of_input_bands",
                empty_class=True,
                excluded_by=p["id"],
                window=w.json(),
            )
        revised.append(Quote(p["id"], F(p["t"]), F(p["k"]), lo, hi))
    result = outer_bounds(revised, w, amin, amax, cells)
    values = []
    lefts = (F(0),) + bands.edges
    rights = bands.edges + (None,)
    for duration, band, start in bands.until(w.t + w.ht):
        if start + duration <= w.t - w.ht:
            continue
        for j, (lo, hi) in enumerate(zip(lefts, rights)):
            if lo < w.k + w.hk and (hi is None or hi > w.k - w.hk):
                values.append((band[0][j], band[1][j]))
    support = [min(v[0] for v in values), max(v[1] for v in values)]
    if result["empty_class"]:
        return dict(
            scope="market_feasible_subset_of_input_bands",
            empty_class=True,
            coefficient_on_window=support,
            weak_moment_certificate=result,
        )
    # Prefer the global positivity proof already implemented by 0.5.1. Older
    # checkouts can still replay their original weak-only window proofs.
    from importlib.util import find_spec

    floor_proof = None
    floor_status = "weak_moments_only"
    floor = max(F(0), F(result["denominator"]["lo"]))
    if find_spec(__package__ + ".denominator") is not None:
        from . import denominator

        try:
            floor_proof = denominator.brownian_floor(w, amin, amax)
        except ValueError as exc:
            if "exceeds the validated log/arithmetic budget" not in str(exc):
                raise
            floor_status = "brownian_budget_exhausted"
        else:
            floor = max(floor, denominator.verify_brownian(floor_proof, w, amin, amax))
            floor_status = "brownian_and_weak_moments"
    ratio = [max(support[0], F(result["lower"])), min(support[1], F(result["upper"]))]
    if floor > 0:
        ratio[1] = min(ratio[1], F(result["numerator"]["hi"]) / floor)
    impossible = floor > F(result["denominator"]["hi"]) or ratio[0] > ratio[1]
    return dict(
        coefficient_on_window=support,
        variance_for_positive_denominator=None if impossible else ratio,
        no_compatible_positive_denominator=impossible,
        denominator_positive_proved=floor > 0,
        denominator_lower=floor,
        denominator_method=floor_status,
        brownian_proof=floor_proof,
        scope="market_feasible_subset_of_input_bands",
        empty_class=impossible and floor > 0,
        weak_moment_certificate=result,
    )
