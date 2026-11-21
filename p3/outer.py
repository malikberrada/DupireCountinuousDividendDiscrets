"""Joint rational outer polyhedron and independently replayable support certificates."""

from fractions import Fraction as F


def form(co=None, offset=0):
    return ({k: F(v) for k, v in (co or {}).items() if v}, F(offset))


def scale(f, a):
    return form({j: a * v for j, v in f[0].items()}, a * f[1])


def add(*forms):
    weights = {}
    constant = F(0)
    for terms, offset in forms:
        constant += offset
        for j, v in terms.items():
            weights[j] = weights.get(j, 0) + v
    return form(weights, constant)


def value(f, x):
    return f[1] + sum(x[j] * w for j, w in f[0].items())


class Outer:
    def __init__(self, m, k=78, h=4):
        self.m = m
        self.k = F(k)
        self.h = F(h)
        k = self.k
        h = self.h
        if not 0 < h < k:
            raise ValueError("Need 0 < stencil spacing < centre")
        barriers = {c["h"] for c in m.contracts} | {c["h1"] for c in m.contracts if c["m"]}
        self.knots = sorted({F(0), k - h, k, k + h} | barriers)
        if self.knots[0] < 0:
            raise ValueError("Need nonnegative effective strikes")
        self.names = ["prepaid_spot"]
        self.ub = [m.zhi]
        self.rows = []
        self.rhs = []
        self.labels = []
        self.z = form({0: 1})
        self.calls = {}
        self.european = {}
        self.row(scale(self.z, -1), -m.zlo, "spot bid")
        for t in (0, 1):
            for strike_node in self.knots:
                if not strike_node:
                    self.calls[t, strike_node] = self.z
                    continue
                j = len(self.names)
                self.names.append(f"call[{t},{strike_node}]")
                self.ub.append(m.zhi)
                self.calls[t, strike_node] = form({j: 1})

            def call_at(strike_node, stage=t):
                return self.calls[stage, strike_node]

            for a, b in zip(self.knots, self.knots[1:]):
                delta = add(call_at(b), scale(call_at(a), -1))
                self.row(delta, 0, "decreasing")
                self.row(scale(delta, -1), b - a, "one-Lipschitz")
            for a, b, e in zip(self.knots, self.knots[1:], self.knots[2:]):
                self.row(
                    add(
                        scale(call_at(b), e - a), scale(call_at(a), b - e), scale(call_at(e), a - b)
                    ),
                    0,
                    "convexity",
                )
        for strike_node in self.knots[1:]:
            self.row(
                add(self.calls[0, strike_node], scale(self.calls[1, strike_node], -1)),
                0,
                "convex order",
            )
        for c in m.contracts:
            t, strike_node = c["m"], c["h"]

            def european_at(stage, strike, kind=c["kind"]):
                call = self.calls[stage, strike]
                return call if kind == "call" else add(call, form(offset=strike), scale(self.z, -1))

            euro = european_at(t, strike_node)
            self.european[c["id"]] = scale(euro, 1 / m.prem)
            self.row(euro, c["ask"], "expiry exercise " + c["id"])
            self.row(scale(euro, -1), c["premium"] - c["bid"], "premium cap " + c["id"])
            early = c["h0"]
            exercise = add(self.z, form(offset=-early))
            self.row(
                exercise if c["kind"] == "call" else scale(exercise, -1),
                c["ask"],
                "known-time exercise " + c["id"],
            )
            if t:
                self.row(
                    european_at(0, c["h1"]), c["ask"], "interim exercise via Jensen " + c["id"]
                )
        self.num = scale(add(self.calls[1, k], scale(self.calls[0, k], -1)), 2 / m.yeargap)
        self.den = scale(
            add(self.calls[0, k - h], scale(self.calls[0, k], -2), self.calls[0, k + h]),
            k * k / (h * h),
        )

    def row(self, f, b, label):
        self.rows.append(f[0])
        self.rhs.append(F(b) - f[1])
        self.labels.append(label)

    def image(self):
        def fmt(f):
            return dict(weights={self.names[j]: str(v) for j, v in f[0].items()}, offset=str(f[1]))

        return dict(
            variables=self.names,
            lower="0",
            upper=list(map(str, self.ub)),
            inequalities=[
                dict(label=label, **fmt(form(a)), upper=str(b))
                for label, a, b in zip(self.labels, self.rows, self.rhs)
            ],
            european_quote_units={k: fmt(v) for k, v in self.european.items()},
            stencil=dict(
                center=str(self.k),
                spacing=str(self.h),
                numerator=fmt(self.num),
                denominator=fmt(self.den),
            ),
        )

    def witness_state(self, w, call):
        return [F(w["z"])] + [call(t, strike) for t in (0, 1) for strike in self.knots if strike]

    def check_point(self, x):
        if len(x) != len(self.ub) or any(not 0 <= v <= u for v, u in zip(x, self.ub)):
            raise ValueError("Outside variable bounds")
        for a, b, label in zip(self.rows, self.rhs, self.labels):
            if value((a, 0), x) > b:
                raise ValueError("Witness violates outer constraint " + label)

    def direction(self, weights):
        if not weights or any(k not in self.european for k in weights):
            raise ValueError("Unknown contract in portfolio")
        return add(*(scale(self.european[k], F(v)) for k, v in weights.items()))


def dual_bound(poly, f, multipliers):
    resid = dict(f[0])
    out = f[1]
    for key, raw in multipliers.items():
        i = int(key)
        a = F(raw)
        if not 0 <= i < len(poly.rows) or a < 0:
            raise ValueError("Invalid dual multiplier")
        out += a * poly.rhs[i]
        for j, v in poly.rows[i].items():
            resid[j] = resid.get(j, 0) - a * v
    return out + sum(poly.ub[j] * d for j, d in resid.items() if d > 0)


class Proposer:
    def __init__(self, poly):
        import numpy as np

        self.p = poly
        self.a = np.zeros((len(poly.rows), len(poly.ub)))
        for i, row in enumerate(poly.rows):
            for j, w in row.items():
                self.a[i, j] = float(w)
        self.b = list(map(float, poly.rhs))
        self.box = [(0, float(v)) for v in poly.ub]

    def maximize(self, f):
        import numpy as np
        from scipy.optimize import linprog

        c = np.zeros(len(self.p.ub))
        for j, v in f[0].items():
            c[j] = -float(v)
        res = linprog(c, A_ub=self.a, b_ub=self.b, bounds=self.box, method="highs")
        if not res.success:
            raise RuntimeError(res.message)
        dual = {
            str(i): str(F(float(-a)).limit_denominator(10**9))
            for i, a in enumerate(res.ineqlin.marginals)
            if a < -1e-13
        }
        return dual, res.x

    def interval(self, f):
        lo, _ = self.maximize(scale(f, -1))
        hi, _ = self.maximize(f)
        return {"lo": lo, "hi": hi}

    def ratio(self, sgn):
        # Dinkelbach only proposes a slope. The saved rational residual proves the bound.
        p = self.p
        n = scale(p.num, sgn)
        alpha = F(0)
        for _ in range(16):
            f = add(n, scale(p.den, -alpha))
            dual, x = self.maximize(f)
            den = float(value(p.den, x))
            if den <= 0:
                raise ValueError("Numerical denominator is nonpositive")
            nxt = F(float(value(n, x)) / den).limit_denominator(10**8)
            if abs(float(nxt - alpha)) < 1e-11:
                break
            alpha = nxt
        dual, _ = self.maximize(add(n, scale(p.den, -alpha)))
        return {"alpha": str(alpha), "dual": dual}


def read_interval(p, f, proof):
    return -dual_bound(p, scale(f, -1), proof["lo"]), dual_bound(p, f, proof["hi"])


def ratio_bound(p, dmin, sgn, proof):
    if dmin <= 0:
        raise ValueError("Denominator has no certified positive floor")
    alpha = F(proof["alpha"])
    residual = dual_bound(p, add(scale(p.num, sgn), scale(p.den, -alpha)), proof["dual"])
    return alpha + max(F(0), residual) / dmin
