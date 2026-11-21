"""Recompute both P2 market tables and verify the two uniform diffusion proofs."""

import argparse
import csv
import json
from collections import Counter
from fractions import Fraction
from math import ceil, floor
from pathlib import Path
from types import SimpleNamespace

from dupire_identify import p2_cert
from dupire_identify.taifex_books import fetch
from p2_txo import ROOT, check_official, compute, expanded, summary, validate_reference, write

DATA = ROOT.parent
F = Fraction


def load(path):
    return json.loads(path.read_bytes())


def check(actual, expected, label):
    if actual != expected:
        raise ValueError(f"Reproduction differs from {label}")


def uniform_case(report, bands, quotes, prices):
    folder = DATA / "synthetic"
    args = SimpleNamespace(bands=folder / bands, quotes=folder / quotes, prices=folder / prices)
    result = p2_cert.verify(folder / report, p2_cert.inputs_from(args))
    return {
        "all_in_spreads": result["all_in_spreads"], "target_met": result["target_met"],
        "contracts": [{key: row[key] for key in ("id", "continuous_price", "eta", "market_status", "target_met")}
                      for row in result["quotes"]],
    }


def check_selection(panel):
    """Verify the panel's retrospective selection against the archived screening ledger."""
    folder = DATA / "selection"
    with (folder / "panels.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    table = load(folder / "summary.json")
    candidate = load(folder / "20261007_202610F3.json")
    eligible = [r for r in rows if r["objective"]]
    for row in eligible:
        check(F(row["objective"]), max(F(row["fixed_error"]), F(row["auto_error"])), "screen objective")
    within = [r for r in eligible if F(r["objective"]) <= F(panel["settings"]["epsilon"])]
    check({(r["date"], r["series"]) for r in within},
          {(r["date"], r["series"]) for r in rows if r["both"] == "True"}, "screen target flags")
    best = min(eligible, key=lambda r: (F(r["objective"]), r["date"], r["expiry"], r["series"]))
    winner = dict(best, eligible_pairs=int(best["eligible_pairs"]), contracts=int(best["contracts"]),
                  both=best["both"] == "True")
    calculated = dict(protocol=table["protocol"], sessions=len({r["date"] for r in rows}),
                      panels=len(rows), two_verified_bounds=len(eligible), both_within_target=len(within),
                      dates_with_both=len({r["date"] for r in within}), winner=winner,
                      status_counts=dict(Counter(r["status"] for r in rows)))
    check(calculated, table, "selection/summary.json")
    check(candidate["panel_sha256"], winner["panel_sha256"], "selected screen row")
    check(candidate["panel_sha256"], panel["panel_sha256"], "market panel identity")
    check(candidate["result_sha256"], panel["source_result_sha256"], "parent certificate identity")
    check(candidate["decisions"]["model"], panel["model"], "parent continuous witness")
    return calculated


def decimals(value, rounding):
    units = rounding(F(value) * 10**6)
    return f"{'-' if units < 0 else ''}{abs(units) // 10**6}.{abs(units) % 10**6:06d}"


def contract_rows(result):
    table = []
    for row in result["rows"]:
        rec = {k: row[k] for k in ("id", "strike", "side")}
        rec.update(bid_points=row["bid"], ask_points=row["ask"])
        for field, label in (("fitting_grid_points", "fitting_grid_points_approx"),
                             ("grid_points", "fine_grid_points_approx"),
                             ("continuous_points", "continuous_points_approx")):
            lo, hi = map(F, row[field])
            rec[label] = decimals((lo + hi) / 2, round)
        lo, hi = row["family_continuous_points"]
        rec.update(fitting_error_cap_points_up=decimals(row["fitting_eta_points"], ceil),
                   fine_error_cap_points_up=decimals(row["fixed_eta_points"], ceil),
                   family_continuous_lower_points_down=decimals(lo, floor),
                   family_continuous_upper_points_up=decimals(hi, ceil),
                   family_continuous_slack_points_down=decimals(row["family_continuous_slack_points"], floor),
                   fine_error_cap_normalized_exact=row["fixed_eta_normalized"])
        table.append(rec)
    return table


def review(out, download):
    out.mkdir(parents=True, exist_ok=True)
    panel, fit = load(ROOT / "panel.json"), load(ROOT / "grid_fit.json")
    validate_reference(panel, None)
    selection = check_selection(panel)
    originals = ROOT / "sources"
    spec = load(originals / "sources.json")
    if download:
        originals = out / "sources"
        originals.mkdir()
        for item in spec["files"]:
            (originals / item["file"]).write_bytes(fetch(item["url"]))
    pairs, sources = check_official(panel, (originals / "taifex.csv").read_bytes(),
                                   (originals / "twse.json").read_bytes())
    check(sources["panel_sha256"], spec["canonical_panel_sha256"], "canonical provider panel")
    sources["origin"] = "download" if download else "archive"
    archive_hashes = {item["file"]: item["sha256"] for item in spec["files"]}
    sources["same_response_bytes_as_archive"] = {
        "taifex.csv": sources["options_file_sha256"] == archive_hashes["taifex.csv"],
        "twse.json": sources["index_file_sha256"] == archive_hashes["twse.json"],
    }
    result = compute(panel, fit)
    check(result, load(ROOT / "result.json"), "txo/result.json")
    extended = expanded(panel, fit, result, pairs)
    check(extended, load(ROOT / "comparison_95.json"), "txo/comparison_95.json")
    table = contract_rows(result)
    with (ROOT / "contrats.csv").open(encoding="utf-8", newline="") as stream:
        check(table, list(csv.DictReader(stream)), "txo/contrats.csv")
    with (out / "contracts.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    write(out / "result.json", result)
    write(out / "comparison_95.json", extended)
    uniform = uniform_case("verified_demo.json", "bands.json", "quotes.csv", "grid_prices.csv")
    skew = uniform_case("verified_skew.json", "skew.json", "skew_quotes.csv", "skew_grid.csv")
    return dict(official_inputs=sources, selected=summary(result), full_panel=extended["all_pairs"],
                other_strikes=extended["other_strikes"], selection_ledger=selection,
                synthetic_uniform=uniform, synthetic_skew=skew)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--out", required=True, type=Path)
    cli.add_argument("--download", action="store_true")
    args = cli.parse_args()
    report = review(args.out, args.download)
    write(args.out / "summary.json", report)
    print(json.dumps(report, indent=2))
