"""Commands for portable uniform P2 proofs and exact outer-LP verification."""

import argparse
import csv
from bisect import bisect_right
from fractions import Fraction as F
import json
from pathlib import Path
from .io import read_quotes, sha256, quote_payload, payload_quotes
from .p2_uniform import Bands, certify, read_prices, rat
from . import p2_bridge
from .p2_mesh import mesh, reference_price
from .p2_plateau import from_plateau


def plain(x):
    if isinstance(x, F):
        return str(x)
    if isinstance(x, (tuple, list)):
        return [plain(v) for v in x]
    if isinstance(x, dict):
        return {k: plain(v) for k, v in x.items()}
    return x


def unique(pairs):
    d = {}
    for key, val in pairs:
        if key in d:
            raise ValueError("Duplicate JSON field: " + key)
        d[key] = val
    return d


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique)


def write_content(path, emit):
    import os, tempfile

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as f:
        name = f.name
        try:
            emit(f)
        except BaseException:
            f.close()
            Path(name).unlink(missing_ok=True)
            raise
    try:
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write(path, doc):
    def emit(f):
        json.dump(plain(doc), f, indent=1, allow_nan=False)
        f.write("\n")

    write_content(path, emit)


def options(cfg):
    o = cfg.copy()
    for key in ("left", "right", "target", "domain_tol"):
        if o.get(key) is not None:
            o[key] = rat(o[key])
    return o


def make(inputs, cfg, replay=None):
    bands = Bands.read(inputs["bands"])
    quotes = payload_quotes(inputs["quotes"])
    prices = {key: rat(v) for key, v in inputs["prices"].items()}
    return plain(certify(bands, quotes, prices, **options(cfg), replay=replay))


def verify(path, inputs=None):
    return verify_document(read(path), inputs)


def verify_document(doc, inputs=None):
    if doc["format"] != "dupire-p2-proof-v1":
        raise ValueError("Unknown P2 proof")
    if inputs is not None and inputs != doc["inputs"]:
        raise ValueError("Proof inputs differ from supplied inputs")
    report = doc["result"]
    witness = {r["id"]: r["levels"] for r in report["quotes"]}
    if make(doc["inputs"], doc["options"], witness) != report:
        raise ValueError("P2 proof does not replay")
    return report


def inputs_from(args):
    quotes = read_quotes(args.quotes)
    return dict(
        bands=read(args.bands),
        quotes=quote_payload(quotes),
        prices=plain(read_prices(args.prices, quotes)),
    )


def add_commands(p):
    sub = p.add_subparsers(dest="action", required=True)
    convert = sub.add_parser("from-plateau")
    convert.add_argument("--model", required=True)
    convert.add_argument("--subcells", type=int, default=2)
    convert.add_argument("--out", required=True)
    proposal = sub.add_parser("propose")
    for key in ("bands", "quotes", "out"):
        proposal.add_argument("--" + key, required=True)
    for key, default in (("cells", 128), ("steps", 64), ("digits", 8)):
        proposal.add_argument("--" + key, type=int, default=default)
    proposal.add_argument("--left", type=F, default=F(1, 2))
    proposal.add_argument("--right", type=F, default=F(3, 2))
    run = sub.add_parser("certify")
    seen = sub.add_parser("verify")
    for cmd in (run, seen):
        for name in ("bands", "quotes", "prices"):
            cmd.add_argument("--" + name, required=cmd is run)
    for key, default in (("left", "1/2"), ("right", "3/2"), ("target", None)):
        run.add_argument("--" + key, default=default, type=F)
    for key, default in (
        ("cells", 16),
        ("steps", 4),
        ("levels", 1),
        ("bits", 48),
        ("max-work", 200000),
    ):
        run.add_argument("--" + key, default=default, type=int)
    run.add_argument("--method", choices=["float", "exact"], default="float")
    run.add_argument("--auto-domain", action="store_true")
    run.add_argument("--domain-tol", type=F)
    run.add_argument("--out", required=True)
    seen.add_argument("--report", required=True)
    window = sub.add_parser("p1-window")
    window.add_argument("--report", required=True)
    window.add_argument("--window", type=F, nargs=4, metavar=("T", "K", "HT", "HK"), required=True)
    window.add_argument("--cells", type=int, default=8)
    window.add_argument("--out", required=True)
    vw = sub.add_parser("verify-window")
    vw.add_argument("--report", required=True)
    vw.add_argument("--proof", required=True)
    bridge = sub.add_parser("p1")
    bridge.add_argument("--reports", nargs="+", required=True)
    bridge.add_argument("--objective", nargs="+", required=True, type=F)
    bridge.add_argument("--weights", nargs="+", type=F)
    bridge.add_argument("--out", required=True)
    check = sub.add_parser("verify-p1")
    check.add_argument("--reports", nargs="+", required=True)
    check.add_argument("--proof", required=True)


def dispatch(args):
    if args.action == "from-plateau":
        if Path(args.out).resolve() == Path(args.model).resolve():
            raise ValueError("Output equals input model")
        bands = from_plateau(read(args.model), args.subcells)
        write(args.out, bands)
        return dict(path=args.out, slabs=len(bands["slabs"]), spot_edges=len(bands["spot_edges"]))
    if args.action == "propose":
        if (
            min(args.steps, args.cells) < 1
            or args.digits < 0
            or not 0 < args.left < 1 < args.right
            or Path(args.out).resolve() in [Path(p).resolve() for p in (args.bands, args.quotes)]
        ):
            raise ValueError("Invalid proposal grid or output")
        bands = Bands.read(read(args.bands))
        quotes = read_quotes(args.quotes)

        def emit(f):
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(("id", "t", "k", "price"))
            for q in quotes:
                if not args.left < q.k < args.right:
                    raise ValueError("Strike outside the proposal domain")
                grid = mesh(args.left, args.right, args.cells, bands.edges, q.k)
                index = [bisect_right(bands.edges, (a + b) / 2) for a, b in zip(grid, grid[1:])]
                p = reference_price(grid, index, bands.until(q.t), q.k, args.steps, "float", 53)
                writer.writerow((q.id, q.t, q.k, round(p, args.digits)))

        write_content(args.out, emit)
        return dict(path=args.out, contracts=len(quotes), price_type="numerical_midpoint_model")
    if args.action == "certify":
        for name in ("bands", "quotes", "prices"):
            if Path(args.out).resolve() == Path(getattr(args, name)).resolve():
                raise ValueError("Output equals an input")
        inp = inputs_from(args)
        names = (
            "left",
            "right",
            "target",
            "cells",
            "steps",
            "levels",
            "method",
            "bits",
            "max_work",
            "auto_domain",
            "domain_tol",
        )
        cfg = plain({k: getattr(args, k) for k in names})
        report = make(inp, cfg)
        write(args.out, dict(format="dupire-p2-proof-v1", inputs=inp, options=cfg, result=report))
        return dict(
            path=args.out,
            all_in_spreads=report["all_in_spreads"],
            global_fit=report["optimization"]["global_optimum"],
            target_met=report["target_met"],
            prices=[
                dict(
                    id=r["id"],
                    eta=float(F(r["eta"])),
                    status=r["market_status"],
                    mesh=r["mesh_status"],
                )
                for r in report["quotes"]
            ],
        )
    if args.action == "verify":
        files = [args.bands, args.quotes, args.prices]
        if any(files) and not all(files):
            raise ValueError("Pass all three source files for external binding")
        report = verify(args.report, inputs_from(args) if all(files) else None)
        return dict(verified=True, contracts=len(report["quotes"]), external_inputs=all(files))
    if args.action in ("p1-window", "verify-window"):
        doc = read(args.report)
        report = verify_document(doc)
        digest = sha256(args.report)
        if args.action == "p1-window":
            if Path(args.out).resolve() == Path(args.report).resolve():
                raise ValueError("Output equals P2 input")
            cfg = dict(window=plain(args.window), cells=args.cells)
            result = plain(
                p2_bridge.window_outer(report, doc["inputs"]["bands"], cfg["window"], cfg["cells"])
            )
            write(
                args.out, dict(format="dupire-p2-window-v1", p2=digest, options=cfg, result=result)
            )
            weak = result.get("weak_moment_certificate", {})
            return dict(
                path=args.out,
                empty_class=result["empty_class"],
                variance=result.get("variance_for_positive_denominator"),
                denominator_positive_proved=result.get("denominator_positive_proved"),
                denominator_method=result.get("denominator_method"),
                weak_moments_status=weak.get("status"),
            )
        proof = read(args.proof)
        if proof["format"] != "dupire-p2-window-v1" or proof["p2"] != digest:
            raise ValueError("P2 input changed")
        check = p2_bridge.window_outer(report, doc["inputs"]["bands"], **proof["options"])
        if plain(check) != proof["result"]:
            raise ValueError("P1 window certificate differs")
        return dict(verified=True, scope=check["scope"])
    reports = [verify(p) for p in args.reports]
    hashes = [sha256(p) for p in args.reports]
    if args.action == "p1":
        if Path(args.out).resolve() in [Path(p).resolve() for p in args.reports]:
            raise ValueError("Output equals an input")
        if args.weights is not None:
            rows, rhs = p2_bridge.rows_for_reports(reports)
            p2_bridge.checked_bound(rows, rhs, args.objective, [F(0)] * len(rows), args.weights)
        result = plain(p2_bridge.optimize(reports, args.objective, args.weights))
        write(
            args.out,
            dict(
                format="dupire-p2-p1-v1",
                reports=hashes,
                objective=plain(args.objective),
                result=result,
            ),
        )
        return dict(
            path=args.out,
            objective_outer=result["objective_outer"],
            proves_empty=result["proves_empty"],
        )
    doc = read(args.proof)
    if doc["format"] != "dupire-p2-p1-v1" or hashes != doc["reports"]:
        raise ValueError("P1 input proof mismatch")
    rebuilt = p2_bridge.optimize(
        reports, list(map(rat, doc["objective"])), replay=doc["result"]["proofs"]
    )
    if plain(rebuilt) != doc["result"]:
        raise ValueError("Incorrect P1 objective certificate")
    return dict(verified=True, objective_outer=doc["result"]["objective_outer"])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    add_commands(p)
    try:
        print(json.dumps(dispatch(p.parse_args()), indent=2))
    except (OSError, ValueError, KeyError, ArithmeticError, IndexError, TypeError) as e:
        p.exit(2, str(e) + "\n")


if __name__ == "__main__":
    main()
