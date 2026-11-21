"""Generate and replay the inner and outer set, support bounds and discrete Dupire projection."""

import csv
import hashlib
import json
from fractions import Fraction as F
from pathlib import Path

from joint import inner, mix
from market import save
from model import Market, evaluate
from outer import Outer, Proposer, ratio_bound, read_interval, scale, value


def digest(data):
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def decimal_out(x, side=0, n=8):
    step = 10**n
    units = (
        (x * step).__floor__()
        if side < 0
        else ((x * step).__ceil__() if side > 0 else round(x * step))
    )
    return (
        ("-" if units < 0 else "") + str(abs(units) // step) + "." + str(abs(units) % step).zfill(n)
    )


def build(data, k, h):
    from fit import fit

    m = Market(data)
    p = Outer(m, k, h)
    solver = Proposer(p)
    witnesses = [fit(m, v) for v in (0, 0.02, -0.02)]
    fixed = inner(m, witnesses)
    cases = [("euro", s, c["id"]) for c in m.contracts for s in (1, -1)]
    dproof = solver.interval(p.den)
    dmin = read_interval(p, p.den, dproof)[0]
    rproof = {}
    if dmin > 0:
        cases += [("ratio", s, (k, h)) for s in (1, -1)]
        rproof = {str(s): solver.ratio(s) for s in (1, -1)}
    seen = {digest(w) for w in witnesses}
    unresolved = []
    for label in cases:
        try:
            w = fit(m, goal=label)
        except (ArithmeticError, ValueError, RuntimeError) as e:
            unresolved.append([list(map(str, label)), str(e)])
            continue
        if digest(w) not in seen:
            witnesses.append(w)
            seen.add(digest(w))
    for spot in ("bid", "ask"):
        try:
            w = fit(m, spot=spot)
        except (ArithmeticError, ValueError, RuntimeError) as e:
            unresolved.append([["spot", spot], str(e)])
            continue
        if digest(w) not in seen:
            witnesses.append(w)
            seen.add(digest(w))
    calls = [c for c in m.contracts if c["m"] == 1 and c["kind"] == "call"]
    puts = {c["K"]: c for c in m.contracts if c["m"] == 1 and c["kind"] == "put"}
    pairs = [c for c in calls if c["K"] in puts]
    directions = {}
    if pairs:
        c = min(pairs, key=lambda a: abs(a["K"] - k))
        weights = {c["id"]: "1", puts[c["K"]]["id"]: "-1"}
        directions["call_minus_put"] = {
            "weights": weights,
            "proof": solver.interval(p.direction(weights)),
        }
    return dict(
        version=1,
        panel_sha256=digest(data),
        center=str(k),
        spacing=str(h),
        witnesses=witnesses,
        core_witness_count=3,
        inner=fixed,
        extra_fit_unresolved=unresolved,
        european_proofs={i: solver.interval(f) for i, f in p.european.items()},
        directions=directions,
        local_time_proof=solver.interval(scale(p.num, m.yeargap)),
        denominator_proof=dproof,
        ratio_proofs=rproof,
        outer_description_sha256=digest(p.image()),
    )


def verify(data, cert):
    if cert["version"] != 1 or cert["panel_sha256"] != digest(data):
        raise ValueError("Certificate is for a different panel")
    m = Market(data)
    p = Outer(m, F(cert["center"]), F(cert["spacing"]))
    if digest(p.image()) != cert["outer_description_sha256"]:
        raise ValueError("Different outer constraints")
    if set(cert["european_proofs"]) != set(p.european):
        raise ValueError("Some instruments have no certificate")
    ws = cert["witnesses"]
    n = cert["core_witness_count"]
    if not 1 <= n <= len(ws):
        raise ValueError("Bad witness count")
    points = []
    columns = []
    slacks = []
    pairs = []
    for w in ws:
        prices, call = evaluate(m, w)
        x = p.witness_state(w, call)
        p.check_point(x)
        if any(value(f, x) != prices[i][0] for i, f in p.european.items()):
            raise ValueError("Inconsistent parity or units")
        points.append(x)
        columns.append(prices)
        slacks.append(min(v[2] for v in prices.values()))
        pairs.append((value(p.num, x), value(p.den, x)))
    if cert["inner"] != inner(m, ws[:n]):
        raise ValueError("Different inner-set policy or column")
    if cert["inner"]["full_simplex_certified"]:
        mixture = mix(ws[:n], [F(1, n)] * n)
        pp, _ = evaluate(m, mixture)
        if any(pp[i][0] != sum(col[i][0] for col in columns[:n]) / n for i in pp):
            raise ValueError("Inconsistent joint mixture")
    bounds = {i: read_interval(p, f, cert["european_proofs"][i]) for i, f in p.european.items()}
    quotes = {q["isin"]: q for q in data["contracts"]}
    records = []
    for i, (lo, hi) in bounds.items():
        euros = [q[i][0] for q in columns]
        mn = min(euros)
        mx = max(euros)
        if not lo <= mn <= mx <= hi:
            raise ValueError("Outer certificate excludes a witness")
        q = quotes[i]
        e, a, _ = columns[0][i]
        records.append(
            dict(
                isin=i,
                expiry=q["expiry"],
                kind=q["kind"],
                strike=q["strike"],
                american_bid=q["bid"],
                american_ask=q["ask"],
                book_time_utc=q["timestamp"],
                outer_lo=decimal_out(lo, -1),
                attained_min=decimal_out(mn),
                central_euro=decimal_out(e),
                central_american=decimal_out(a),
                central_early_premium=decimal_out(a - e),
                attained_max=decimal_out(mx),
                outer_hi=decimal_out(hi, 1),
                lower_gap_max=decimal_out(mn - lo, 1),
                upper_gap_max=decimal_out(hi - mx, 1),
                min_witness=euros.index(mn),
                max_witness=euros.index(mx),
            )
        )
    ds = {}
    for key, o in cert["directions"].items():
        f = p.direction(o["weights"])
        lo, hi = read_interval(p, f, o["proof"])
        actual = [value(f, x) for x in points]
        if not lo <= min(actual) <= max(actual) <= hi:
            raise ValueError("Incorrect portfolio range")
        ds[key] = dict(
            weights=o["weights"],
            outer=[decimal_out(lo, -1), decimal_out(hi, 1)],
            witness=[decimal_out(min(actual)), decimal_out(max(actual))],
        )
    dmin, dmax = read_interval(p, p.den, cert["denominator_proof"])
    if not all(dmin <= d <= dmax for a, d in pairs):
        raise ValueError("Incorrect curvature enclosure")
    dup = dict(
        center=str(p.k),
        spacing=str(p.h),
        denominator=[decimal_out(dmin, -1), decimal_out(dmax, 1)],
        status="unresolved_denominator",
    )
    if dmin > 0:
        lo = -ratio_bound(p, dmin, -1, cert["ratio_proofs"]["-1"])
        hi = ratio_bound(p, dmin, 1, cert["ratio_proofs"]["1"])
        vals = [a / d for a, d in pairs]
        if not lo <= min(vals) <= max(vals) <= hi:
            raise ValueError("Invalid Dupire enclosure")
        dup.update(
            status="certified_finite_difference",
            outer=[decimal_out(lo, -1), decimal_out(hi, 1)],
            attained_extrema=[decimal_out(min(vals)), decimal_out(max(vals))],
            witness_indices=[vals.index(min(vals)), vals.index(max(vals))],
        )
    elif cert["ratio_proofs"]:
        raise ValueError("Unproved denominator")
    time_form = scale(p.num, m.yeargap)
    ltlo, lthi = read_interval(p, time_form, cert["local_time_proof"])
    local = [value(time_form, x) for x in points]
    if not ltlo <= min(local) <= max(local) <= lthi:
        raise ValueError("Incorrect Tanaka enclosure")
    local_time = dict(
        strike=str(p.k),
        outer=[decimal_out(ltlo, -1), decimal_out(lthi, 1)],
        attained_extrema=[decimal_out(min(local)), decimal_out(max(local))],
    )
    result = dict(
        expected_local_time_increment_continuous_models=local_time,
        asof=data["asof"],
        contracts=len(records),
        expiries=data["expiries"],
        common_witnesses=len(ws),
        core_models=n,
        full_core_simplex_certified=cert["inner"]["full_simplex_certified"],
        central_minimum_slack_eur=decimal_out(slacks[0], -1),
        max_option_age_seconds=decimal_out(
            max(F(q.get("age_ns", 0), 10**9) for q in data["contracts"]), 1, 9
        ),
        directions=ds,
        dupire=dup,
        extra_witness_searches_unresolved=len(cert["extra_fit_unresolved"]),
    )
    return result, records, p


def exports(folder, data, cert):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    report, rows, p = verify(data, cert)
    save(folder / "certificate.json", cert)
    save(folder / "outer.json", p.image())
    save(folder / "summary.json", report)
    with open(folder / "european_bounds.csv", "w", newline="", encoding="utf-8") as fh:
        tab = csv.DictWriter(fh, fieldnames=list(rows[0]))
        tab.writeheader()
        tab.writerows(rows)
    return report
