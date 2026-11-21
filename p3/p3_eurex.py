"""P3 Eurex joint inverse-set verification and computation."""

import argparse
import csv
import json
import sys
from fractions import Fraction as F
from pathlib import Path

from capture import dividend_proof, grab_minute, replay
from certify import build, decimal_out, exports, verify
from dividends import sensitivity
from market import ROOT, check_files, load
from model import Market
from outer import Proposer, read_interval
from p3_results import format_results, read_results
from pointwise import runner as pointwise


def parse_args(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="action", required=True)
    for command in ("verify", "certify", "portfolio", "div-risk"):
        p = sub.add_parser(command)
        p.add_argument("--panel", type=Path, help="custom normalized EUR two-expiry panel")
        if command != "certify":
            p.add_argument("--certificate", type=Path, default=ROOT / "certified/certificate.json")
        if command == "verify":
            p.add_argument("--official-dividend", action="store_true")
            p.add_argument("--cache", type=Path, default=Path("p3_cache"))
        elif command == "certify":
            p.add_argument("--center", default="78")
            p.add_argument("--spacing", default="4")
            p.add_argument("--out", type=Path, required=True)
        elif command == "portfolio":
            p.add_argument("--weights", required=True, action="append", metavar="ISIN=RATIONAL")
        else:
            p.add_argument("--amount-lo", required=True)
            p.add_argument("--amount-hi", required=True)
            for flag in ("ex-lo", "ex-hi", "pay-lo", "pay-hi"):
                p.add_argument("--" + flag)
    p = sub.add_parser("replay-originals")
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--download", action="store_true")
    p = sub.add_parser("capture-minute")
    p.add_argument("--utc", required=True)
    p.add_argument("--out", type=Path, required=True)
    pointwise.add_commands(sub)
    a = cli.parse_args(argv)
    if getattr(a, "require_originals", False) and a.action != "pipeline" and not a.download:
        cli.error("--require-originals requires pipeline or --download")
    return a


def execute(a):
    if a.action == "results":
        return read_results(a.out, a.run)
    if a.action == "pipeline" or (
        a.action in ("pointwise", "pointwise-fit") and a.download
    ):
        from pipeline import run

        return run(a)
    if a.action.startswith("pointwise"):
        return pointwise.run(a)
    if a.action == "capture-minute":
        return grab_minute(a.utc, a.out)
    if a.action == "replay-originals":
        return replay(a.cache, a.out, a.download)
    data = load(a.panel) if a.panel else check_files()
    if a.action == "certify":
        return exports(a.out, data, build(data, F(a.center), F(a.spacing)))
    cert = load(a.certificate)
    report, rows, p = verify(data, cert)
    if a.action == "verify":
        if (
            not a.panel
            and a.certificate.resolve() == (ROOT / "certified/certificate.json").resolve()
        ):
            with open(ROOT / "certified/european_bounds.csv", encoding="utf-8", newline="") as f:
                tab = list(csv.DictReader(f))
            if (
                tab != [{k: str(v) for k, v in row.items()} for row in rows]
                or load(ROOT / "certified/outer.json") != p.image()
                or load(ROOT / "certified/summary.json") != report
            ):
                raise ValueError(
                    "A distributed result differs from the independently replayed proof"
                )
            report = dict(
                report,
                xetra=data["spot"],
                estr_pct=data["rate_pct"],
                earlier_eurex_transaction_messages=data["day_posttrade_messages_before_asof"],
            )
        if a.official_dividend:
            report["official_dividend"] = dividend_proof(a.cache)
        return report
    if a.action == "portfolio":
        weights = {}
        for pair in a.weights:
            key, v = pair.split("=", 1)
            weights[key] = weights.get(key, F(0)) + F(v)
        objective = p.direction(weights)
        proof = Proposer(p).interval(objective)
        lo, hi = read_interval(p, objective, proof)
        return dict(
            weights={k: str(v) for k, v in weights.items()},
            outer=[decimal_out(lo, -1), decimal_out(hi, 1)],
            dual=proof,
        )
    return sensitivity(
        Market(data),
        cert["witnesses"][0],
        a.amount_lo,
        a.amount_hi,
        a.ex_lo,
        a.ex_hi,
        a.pay_lo,
        a.pay_hi,
    )


def main(argv=None):
    return execute(parse_args(argv))


if __name__ == "__main__":
    try:
        args = parse_args()
        result = execute(args)
        output_format = getattr(args, "format", "json")
        if output_format == "text" or (output_format is None and sys.stdout.isatty()):
            print(format_results(result))
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
    except (ValueError, ArithmeticError, RuntimeError, OSError, ImportError, KeyError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
