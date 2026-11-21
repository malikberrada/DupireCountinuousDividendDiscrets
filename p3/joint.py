"""A convex inner set from common martingale flows and one certified exercise policy per option."""

from fractions import Fraction as F

from model import evaluate, intrinsic


def flows(w):
    return {
        F(x): (F(record["p"]), {F(y): F(record["p"]) * F(q) for y, q in record["next"].items()})
        for x, record in w["states"].items()
    }


def inner(m, witnesses):
    if len({F(w["z"]) for w in witnesses}) != 1:
        raise ValueError("Mixtures require the same spot")
    laws = [flows(w) for w in witnesses]
    prices = [evaluate(m, w)[0] for w in witnesses]
    first = sorted(set().union(*laws))
    z = F(witnesses[0]["z"])
    rows = []
    full = True
    for c in m.contracts:
        stop = []
        if c["m"]:
            for x in first:
                ex = cont = F(0)
                for law in laws:
                    if x not in law:
                        continue
                    p, branch = law[x]
                    ex += p * intrinsic(c["kind"], x, c["h1"])
                    cont += sum(w * intrinsic(c["kind"], y, c["h"]) for y, w in branch.items())
                if ex >= cont:
                    stop.append(x)
        pay = []
        for idx, law in enumerate(laws):
            if c["m"] == 0:
                v = prices[idx][c["id"]][0] * m.prem
            else:
                v = sum(
                    (
                        p * intrinsic(c["kind"], x, c["h1"])
                        if x in stop
                        else sum(w * intrinsic(c["kind"], y, c["h"]) for y, w in branch.items())
                    )
                    for x, (p, branch) in law.items()
                )
            pay.append(v)
        early = intrinsic(c["kind"], z, c["h0"])
        take_root = early >= min(pay)
        if take_root and early >= c["bid"]:
            pay = [early] * len(laws)
        else:
            take_root = False
        row = dict(
            isin=c["id"],
            exercise_before_first=take_root,
            stop_at_interim_states=list(map(str, stop)),
            policy_values_pv=list(map(str, pay)),
            required_lower_pv=str(c["bid"]),
        )
        if min(pay) < c["bid"]:
            full = False
        rows.append(row)
    return dict(
        simplex_dimension=len(witnesses) - 1,
        full_simplex_certified=full,
        lower_policy_rows=rows,
        european_columns=[{k: str(v[0]) for k, v in col.items()} for col in prices],
    )


def mix(witnesses, weights):
    weights = list(map(F, weights))
    if len(weights) != len(witnesses) or min(weights) < 0 or sum(weights) != 1:
        raise ValueError("Invalid simplex weights")
    joint = {}
    for w, v in zip(witnesses, weights):
        if not v:
            continue
        for x, (p, branch) in flows(w).items():
            acc = joint.setdefault(x, {})
            for y, f in branch.items():
                acc[y] = acc.get(y, 0) + v * f
    states = {}
    for x, branch in joint.items():
        p = sum(branch.values())
        states[str(x)] = {"p": str(p), "next": {str(y): str(f / p) for y, f in branch.items()}}
    return {"z": witnesses[0]["z"], "states": states}
