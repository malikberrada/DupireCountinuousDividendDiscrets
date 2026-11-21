"""Reproduce the P2 market certificate on the retained TAIFEX TXO expiry."""

import argparse
from datetime import date
from fractions import Fraction as F
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from dupire_identify.interval import I
from dupire_identify.p2_uniform import Bands, black_strips
from dupire_identify.spxw_books import Book, Pair, parity
from dupire_identify.spxw_witness import price_quantile, verify_model
from dupire_identify.taifex_books import ANCHORS, clocks, fetch, index_url, option_url, prepare
from txo_lattice import fixed_grid, family_grid, combine_maps
from grid_fit import curves

ROOT = Path(__file__).resolve().parent / "data" / "txo"
MESH_ROOTS = (8, 16, 32, 64, 128)
RADIUS_POWERS = range(11, 26)
PRICE_GOAL = F(1, 100)  # index point per contract for the fixed-model tree


def fingerprint(obj):
    return sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def bounds(v):
    return [str(v.lo), str(v.hi)]


def gap(a, b):
    return max(a.hi - b.lo, b.hi - a.lo)


def validate_reference(panel, archive):
    if panel["schema"] != "txo-p2-panel-v1":
        raise ValueError("Unrecognized market input")
    if archive is not None:
        saved = json.loads(Path(archive).read_bytes())
        if (
            fingerprint(saved) != panel["source_result_sha256"]
            or saved["model"] != panel["model"]
            or saved["witness"] != panel["expected_witness"]
            or saved["all_pairs_parity"] != panel["expected_parity"]
        ):
            raise ValueError("Published research certificate does not match these inputs")


def archived_pairs(panel):
    lookup = {}
    for x in panel["expected_witness"]["raw_prices"]:
        prefix, series, side, strike = x["id"].split(":")
        if prefix != "TXO" or series != panel["settings"]["series"] or side not in ("C", "P"):
            raise ValueError("Unexpected contract identity")
        k = F(strike)
        if (k, side) in lookup:
            raise ValueError("Duplicate contract")
        lookup[k, side] = Book(x["id"], k, F(x["bid"]), F(x["ask"]))
    ks = list(map(F, panel["selected_strikes"]))
    if len(ks) != len(set(ks)) or len(lookup) != 2 * len(ks):
        raise ValueError("Mismatched strikes")
    return [Pair(k, lookup[k, "C"], lookup[k, "P"]) for k in ks]


def check_official(panel, raw, index):
    pairs, spot, t, audit = prepare(raw, index, panel["settings"])
    chosen = sorted(
        {min(pairs, key=lambda p: (abs(p.k - spot * x), p.k)) for x in ANCHORS}, key=lambda p: p.k
    )
    vertices = [[str(d), str(df)] for d, df in parity(pairs)]
    if (
        audit["panel_sha256"] != panel["panel_sha256"]
        or chosen != archived_pairs(panel)
        or len(pairs) != panel["expected_parity"]["pairs"]
        or vertices != panel["expected_parity"]["vertices_D_DF"]
    ):
        raise ValueError("Source panel, parity or selected contracts differ from the reference")
    return pairs, dict(
        panel_sha256=audit["panel_sha256"],
        options_file_sha256=sha256(raw).hexdigest(),
        index_file_sha256=sha256(index).hexdigest(),
        observed_at=audit["valuation_taipei"],
        settles_at=audit["fixing_end_taipei"],
        spot_close=audit["index_close"],
        act365f=str(t),
        eligible_pairs=len(pairs),
        regular_rows=audit["regular_rows_at_expiry"],
        selected=len(chosen) * 2,
    )


def flat_prior(pairs, df, forward, t, amin, amax):
    """Unmodified P2 full-domain comparison in normalized units, with outward curve conversion."""
    bands = Bands.read(
        dict(
            schema="p2-variance-bands-v1",
            spot_edges=[],
            slabs=[dict(end=str(t), lower=[str(amin)], upper=[str(amax)])],
        )
    )
    slabs = bands.until(t)
    pric = {}
    for p in pairs:
        # Calls increase in the forward; puts decrease. Pairwise parity holds at each endpoint.
        values = {}
        for f in (forward.lo, forward.hi):
            normalized = SimpleNamespace(k=p.k / f)
            for side in (0, 1):
                c = df * f * I(*black_strips(bands, slabs, normalized, side))
                values[f, side] = (c, c + df * (p.k - f))
        low_call = I(values[forward.lo, 0][0].lo, values[forward.hi, 0][0].hi)
        high_call = I(values[forward.lo, 1][0].lo, values[forward.hi, 1][0].hi)
        low_put = I(values[forward.hi, 0][1].lo, values[forward.lo, 0][1].hi)
        high_put = I(values[forward.hi, 1][1].lo, values[forward.lo, 1][1].hi)
        for book, low, high in ((p.call, low_call, high_call), (p.put, low_put, high_put)):

            def outside(iv):
                return iv.hi < book.bid or iv.lo > book.ask

            pric[book.id] = dict(
                continuous_points=bounds(I(low.lo, high.hi)),
                constant_low_outside=outside(low),
                constant_high_outside=outside(high),
                full_prior_inside=book.bid <= low.lo and high.hi <= book.ask,
            )
    return pric


def slope_box(knots, slopes, radius):
    low = [max(min(slopes), x - radius) for x in slopes]
    high = [min(max(slopes), x + radius) for x in slopes]
    zero = knots.index(F(0))
    # Negative integration direction reverses derivative order at z<0.
    return (
        low,
        high,
        tuple(high[: zero + 1] + low[zero + 1 :]),
        tuple(low[: zero + 1] + high[zero + 1 :]),
    )


def continuous_family(model, lo, hi, fw, pairs, t, amin, amax):
    def variant(slopes, median):
        return dict(model, slopes=list(map(str, slopes)), median_spot=str(median))

    ml = price_quantile(variant(lo, 1), [], t, amin, amax)[1]
    mh = price_quantile(variant(hi, 1), [], t, amin, amax)[1]
    if ml.lo <= 0 or mh.hi <= 0:
        raise ArithmeticError("Unproved continuous normalizer")

    def prices(slopes, level):
        return {b.id: v for b, v in price_quantile(variant(slopes, level), pairs, t, amin, amax)[2]}

    return combine_maps(pairs, prices(lo, fw.lo / mh.hi), prices(hi, fw.hi / ml.lo))


def compute(panel, proposal):
    settings = panel["settings"]
    start, end = map(date.fromisoformat, (settings["date"], settings["expiry"]))
    _, _, t = clocks(start, end)
    amin, amax = map(F, (settings["amin"], settings["amax"]))
    pairs = archived_pairs(panel)
    books = [b for p in pairs for b in (p.call, p.put)]
    witness = verify_model(panel["model"], pairs, t, amin, amax)
    if witness != panel["expected_witness"]:
        raise ValueError("Continuous witness differs from the archived result")
    df, f = curves(panel)
    if proposal["schema"] != "txo-grid-fit-v1" or (
        F(proposal["discount"]),
        F(proposal["forward"]),
    ) != (df, f):
        raise ValueError("Grid fit uses other curves")
    fw = I(f)
    knots = tuple(map(F, proposal["knots"]))
    slopes = tuple(map(F, proposal["slopes"]))
    train_m = proposal["fit_root"]
    if train_m not in MESH_ROOTS or train_m**2 != proposal["fit_steps"]:
        raise ValueError("Unexpected calibration grid")
    # price_quantile with the two normalizer endpoints encloses the true median F/E[exp h].
    model = dict(
        kind="gaussian_terminal_loglinear",
        discount=str(df),
        knots=proposal["knots"],
        slopes=proposal["slopes"],
    )
    if (
        tuple(sorted(set(knots))) != knots
        or 0 not in knots
        or len(slopes) != len(knots) + 1
        or any(s <= 0 or not amin * t <= s * s <= amax * t for s in slopes)
    ):
        raise ValueError("Invalid quantile model")
    exact = continuous_family(model, slopes, slopes, fw, pairs, t, amin, amax)
    prior = flat_prior(pairs, df, fw, t, amin, amax)
    levels = []
    for m in MESH_ROOTS:
        grid = fixed_grid(knots, slopes, fw, df, pairs, m)
        err = max(gap(grid[b.id], exact[b.id]) for b in books)
        levels.append(
            dict(
                time_steps=m * m,
                terminal_nodes=m * m + 1,
                max_eta_points=str(err),
                grid_in_spread=sum(b.bid <= grid[b.id].lo <= grid[b.id].hi <= b.ask for b in books),
            )
        )
        if m == train_m:
            training = grid
        if m >= train_m and err <= PRICE_GOAL:
            break
    history = []
    for n in RADIUS_POWERS:
        radius = F(1, 2**n)
        lo, hi, low_map, high_map = slope_box(knots, slopes, radius)
        cont = continuous_family(model, low_map, high_map, fw, pairs, t, amin, amax)
        n_cont = sum(b.bid <= cont[b.id].lo and cont[b.id].hi <= b.ask for b in books)
        if n_cont < len(books) and n != RADIUS_POWERS[-1]:
            history.append(
                dict(radius=str(radius), continuous_in_spread=n_cont, all_three_in_spread=None)
            )
            continue
        tree = family_grid(knots, low_map, high_map, fw, df, pairs, m)
        tree_train = (
            tree if m == train_m else family_grid(knots, low_map, high_map, fw, df, pairs, train_m)
        )
        if any(
            not (
                cont[b.id].lo <= exact[b.id].lo <= exact[b.id].hi <= cont[b.id].hi
                and tree[b.id].lo <= grid[b.id].lo <= grid[b.id].hi <= tree[b.id].hi
                and tree_train[b.id].lo
                <= training[b.id].lo
                <= training[b.id].hi
                <= tree_train[b.id].hi
            )
            for b in books
        ):
            raise ArithmeticError("Central model not contained in verified family")
        passed = sum(
            b.bid <= min(cont[b.id].lo, tree[b.id].lo, tree_train[b.id].lo)
            and max(cont[b.id].hi, tree[b.id].hi, tree_train[b.id].hi) <= b.ask
            for b in books
        )
        history.append(
            dict(radius=str(radius), continuous_in_spread=n_cont, all_three_in_spread=passed)
        )
        if passed == len(books):
            break
    rows = []
    for b in books:
        i = b.id
        sample = grid[i]
        target = exact[i]
        eta = gap(sample, target)
        emax = gap(tree[i], cont[i])
        rows.append(
            dict(
                id=i,
                strike=str(b.strike),
                side=i.split(":")[2],
                bid=str(b.bid),
                ask=str(b.ask),
                grid_points=bounds(sample),
                continuous_points=bounds(target),
                fixed_eta_points=str(eta),
                fixed_eta_normalized=str(eta / (df * fw.lo)),
                fixed_both_in_spread=(
                    b.bid <= min(sample.lo, target.lo) and max(sample.hi, target.hi) <= b.ask
                ),
                fitting_grid_points=bounds(training[i]),
                fitting_eta_points=str(gap(training[i], target)),
                fit_grid_in_spread=b.bid <= training[i].lo and training[i].hi <= b.ask,
                fixed_continuous_slack_points=str(min(target.lo - b.bid, b.ask - target.hi)),
                family_fitting_grid_points=bounds(tree_train[i]),
                family_fitting_eta_points=str(gap(tree_train[i], cont[i])),
                family_grid_points=bounds(tree[i]),
                family_continuous_points=bounds(cont[i]),
                family_eta_points=str(emax),
                family_eta_normalized=str(emax / (df * fw.lo)),
                family_continuous_slack_points=str(min(cont[i].lo - b.bid, b.ask - cont[i].hi)),
                family_both_in_spread=b.bid <= min(tree[i].lo, tree_train[i].lo, cont[i].lo)
                and max(tree[i].hi, tree_train[i].hi, cont[i].hi) <= b.ask,
                prior=prior[i],
            )
        )
    return dict(
        schema="p2-txo-market-proof-v1",
        date=settings["date"],
        expiry=settings["expiry"],
        series=settings["series"],
        clock=str(t),
        discount=str(df),
        forward=bounds(fw),
        inputs_sha256=fingerprint(panel),
        model={
            "kind": "forward_normalized_gaussian_loglinear",
            "discount": str(df),
            "forward": str(f),
            "knots": proposal["knots"],
            "slopes": proposal["slopes"],
        },
        prior=[str(amin), str(amax)],
        synchronization_verified=False,
        fitting_grid_steps=train_m**2,
        grid_proposal_sha256=fingerprint(proposal),
        fitting_worst_midpoint_distance_in_half_spreads=str(
            max(
                max(
                    abs(2 * training[b.id].lo - b.bid - b.ask),
                    abs(2 * training[b.id].hi - b.bid - b.ask),
                )
                / (b.ask - b.bid)
                for b in books
            )
        ),
        archived_witness_reverified=True,
        archived_witness_contracts=witness["checked_contracts"],
        fixed_tree_target_points=str(PRICE_GOAL),
        fixed_tree_target_met=err <= PRICE_GOAL,
        grid_refinements=levels,
        terminal_nodes=m * m + 1,
        steps=m * m,
        box_radius=str(radius),
        slope_lower=list(map(str, lo)),
        slope_upper=list(map(str, hi)),
        radius_search=history,
        rows=rows,
    )


def summary(result):
    rows = result["rows"]

    def upper(key):
        return max(F(x[key]) for x in rows)

    return dict(
        contracts=len(rows),
        steps=result["steps"],
        fitting_grid_steps=result["fitting_grid_steps"],
        max_fitting_eta_points=float(upper("fitting_eta_points")),
        max_fitting_family_eta_points=float(upper("family_fitting_eta_points")),
        fitting_grid_in_spread=sum(r["fit_grid_in_spread"] for r in rows),
        fixed_both_in_spread=sum(r["fixed_both_in_spread"] for r in rows),
        max_fixed_eta_points=float(upper("fixed_eta_points")),
        box_radius=result["box_radius"],
        family_both_in_spread=sum(r["family_both_in_spread"] for r in rows),
        max_family_eta_points=float(upper("family_eta_points")),
        min_family_continuous_slack_points=float(
            min(F(r["family_continuous_slack_points"]) for r in rows)
        ),
        full_prior_wholly_in_spread=sum(x["prior"]["full_prior_inside"] for x in rows),
    )


def classify(iv, book):
    if book.bid <= iv.lo and iv.hi <= book.ask:
        return "in"
    if iv.hi < book.bid or iv.lo > book.ask:
        return "out"
    return "open"


def expanded(panel, proposal, result, pairs):
    """The 90 extra strikes are used for parity but excluded from the smile optimization."""
    t = F(result["clock"])
    amin, amax = map(F, result["prior"])
    d, f = curves(panel)
    fw = I(f)
    knots = tuple(map(F, proposal["knots"]))
    slopes = tuple(map(F, proposal["slopes"]))
    model = dict(
        kind="gaussian_terminal_loglinear",
        knots=proposal["knots"],
        slopes=proposal["slopes"],
        discount=str(d),
    )
    train = fixed_grid(knots, slopes, fw, d, pairs, proposal["fit_root"])
    from math import isqrt

    fine = fixed_grid(knots, slopes, fw, d, pairs, isqrt(result["steps"]))
    cont = continuous_family(model, slopes, slopes, fw, pairs, t, amin, amax)
    selected = set(panel["selected_strikes"])
    details = []
    for p in pairs:
        for book in (p.call, p.put):
            k = book.id
            details.append(
                dict(
                    id=k,
                    strike=str(p.k),
                    side=k.split(":")[2],
                    smile_fit=str(p.k) in selected,
                    fit=classify(train[k], book),
                    fine=classify(fine[k], book),
                    continuous=classify(cont[k], book),
                    fitted_eta=str(gap(train[k], cont[k])),
                    fine_eta=str(gap(fine[k], cont[k])),
                )
            )

    def group(records):
        ids = sorted({r["strike"] for r in records}, key=F)
        return dict(
            contracts=len(records),
            strikes=len(ids),
            fit_inside=sum(r["fit"] == "in" for r in records),
            fine_inside=sum(r["fine"] == "in" for r in records),
            continuous_inside=sum(r["continuous"] == "in" for r in records),
            calls_continuous_inside=sum(
                r["side"] == "C" and r["continuous"] == "in" for r in records
            ),
            puts_continuous_inside=sum(
                r["side"] == "P" and r["continuous"] == "in" for r in records
            ),
            pairs_both_continuous_inside=sum(
                all(r["continuous"] == "in" for r in records if r["strike"] == k) for k in ids
            ),
            fit_inside_to_continuous_outside=[
                r["id"] for r in records if r["fit"] == "in" and r["continuous"] == "out"
            ],
            fit_outside_to_continuous_inside=[
                r["id"] for r in records if r["fit"] == "out" and r["continuous"] == "in"
            ],
            any_undecided=[
                r["id"] for r in records if "open" in (r["fit"], r["fine"], r["continuous"])
            ],
            max_fitted_eta_points=str(max(F(r["fitted_eta"]) for r in records)),
            max_fine_eta_points=str(max(F(r["fine_eta"]) for r in records)),
        )

    return dict(
        schema="p2-txo-all-pairs-v1",
        input_panel=panel["panel_sha256"],
        grid_proposal=fingerprint(proposal),
        all_pairs=group(details),
        selected=group([r for r in details if r["smile_fit"]]),
        other_strikes=group([r for r in details if not r["smile_fit"]]),
        contract_checks_sha256=fingerprint(details),
    )


def write(path, obj):
    from tempfile import NamedTemporaryFile
    import os

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as out:
        temp = Path(out.name)
        try:
            json.dump(obj, out, indent=2, allow_nan=False)
            out.write("\n")
        except BaseException:
            out.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("run", "verify"))
    p.add_argument(
        "--official", action="store_true", help="re-download and validate both exchange sources"
    )
    p.add_argument("--options", type=Path, help="local file from TAIFEX")
    p.add_argument("--index", type=Path, help="local file from TWSE")
    p.add_argument("--archived-result", type=Path, help="original TXO research certificate")
    p.add_argument(
        "--all-pairs", action="store_true", help="also assess all 95 pairs on official data"
    )
    p.add_argument("--extra-result", type=Path, default=ROOT / "comparison_95.json")
    p.add_argument("--fit", type=Path, default=ROOT / "grid_fit.json")
    p.add_argument("--result", type=Path, default=ROOT / "result.json")
    args = p.parse_args()
    if bool(args.options) != bool(args.index) or args.official and args.options:
        p.error("Provide --official, or both --options and --index, or neither")
    if args.all_pairs and not (args.official or args.options):
        p.error("--all-pairs requires the official source data")
    outputs = [args.result] + ([args.extra_result] if args.all_pairs else [])
    if args.action == "run" and (
        len({f.resolve() for f in outputs}) != len(outputs)
        or {f.resolve() for f in outputs}
        & {
            f.resolve()
            for f in (ROOT / "panel.json", args.fit, args.options, args.index, args.archived_result)
            if f is not None
        }
    ):
        p.error("Conflicting input or output paths")
    panel = json.loads((ROOT / "panel.json").read_bytes())
    validate_reference(panel, args.archived_result)
    source = None
    if args.official:
        day = date.fromisoformat(panel["settings"]["date"])
        all_pairs, source = check_official(panel, fetch(option_url(day)), fetch(index_url(day)))
    elif args.options:
        all_pairs, source = check_official(
            panel, args.options.read_bytes(), args.index.read_bytes()
        )
    proposal = json.loads(args.fit.read_bytes())
    result = compute(panel, proposal)
    extra = expanded(panel, proposal, result, all_pairs) if args.all_pairs else None
    artifacts = [(args.result, result)] + (
        [(args.extra_result, extra)] if extra is not None else []
    )
    if args.action == "verify":
        for path, doc in artifacts:
            if doc != json.loads(path.read_bytes()):
                raise ValueError("Certificate differs from recomputation: " + path.name)
    else:
        for path, doc in artifacts:
            write(path, doc)
    out = dict(action=args.action, official_sources=source, **summary(result))
    if extra is not None:
        out["other_strikes"] = dict(
            strikes=extra["other_strikes"]["strikes"],
            contracts=extra["other_strikes"]["contracts"],
            continuous_inside=extra["other_strikes"]["continuous_inside"],
        )
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
