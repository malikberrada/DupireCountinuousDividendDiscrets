"""Replay the published joint set, the two point coordinates and the dated market panel."""

import argparse
import json
from fractions import Fraction as F
from pathlib import Path

from market import ROOT, load, save
from model import Market, evaluate
from outer import Outer, read_interval
from p3_eurex import main


def check_equal(actual, reference, context):
    if actual != reference:
        raise ValueError(f"Reproduction differs from {context}")


def joint_geometry(panel, certificate):
    """Check the dimension of the guaranteed triangle and the sharp portfolio endpoints."""
    columns = certificate["inner"]["european_columns"]
    if len(columns) != 3 or not certificate["inner"]["full_simplex_certified"]:
        raise ValueError("The three core witnesses do not certify the complete simplex")
    ids = sorted(columns[0])
    a, b = [[F(col[k]) - F(columns[0][k]) for k in ids] for col in columns[1:]]
    independent = next(((ids[i], ids[j]) for i in range(len(ids)) for j in range(i + 1, len(ids))
                        if a[i] * b[j] != a[j] * b[i]), None)
    if independent is None:
        raise ValueError("The three European price vectors are affinely dependent")

    market = Market(panel)
    poly = Outer(market, F(certificate["center"]), F(certificate["spacing"]))
    direction = certificate["directions"]["call_minus_put"]
    weights = direction["weights"]
    outer = read_interval(poly, poly.direction(weights), direction["proof"])
    values = []
    for witness in certificate["witnesses"]:
        prices, _ = evaluate(market, witness)
        values.append(sum(F(weight) * prices[isin][0] for isin, weight in weights.items()))
    attained = [min(values), max(values)]
    check_equal(list(outer), attained, "exact European call-minus-put extrema")
    return {"triangle_affine_dimension": 2, "nonzero_minor_coordinates": list(independent),
            "portfolio_weights": weights, "exact_attained_endpoints": list(map(str, attained)),
            "endpoint_witness_indices_zero_based": [values.index(v) for v in attained]}


def review(out, cache, download, strict):
    # This command also compares the distributed joint CSV, polyhedron and summary.
    main(["verify"])
    gains = main(["pointwise", "--coordinate", "gains"])
    check_equal(gains, load(ROOT / "certified_pointwise/summary.json"), "gains-coordinate summary")
    command = ["pipeline", "--coordinate", "stock", "--cache", str(cache), "--out", str(out / "study")]
    if not download:
        command.append("--offline")
    if strict:
        command.append("--require-originals")
    result = main(command)
    folder = Path(result["run"])
    receipt = load(folder / "pipeline.json")
    archive = load(ROOT / "certified/acquisition.json")
    for key in ("asof", "product", "underlying", "contracts", "panel_sha256",
                "joint_certificate_sha256", "point_certificate_sha256", "pointwise_models"):
        check_equal(receipt[key], archive[key], key)
    paris = receipt["euronext"]
    for key in ("csv_sha256", "session", "venue", "rows_in_source_csv", "matched_series_in_reference",
                "ordinary_messages_before_cut", "flagged_ids_before_cut", "trades_retained", "series_with_trades"):
        check_equal(paris[key], archive["euronext"][key], "Euronext " + key)
    joint = result["results"]["joint"]
    check_equal(joint, load(ROOT / "certified/summary.json"), "joint result")
    stock = result["results"]["pointwise"]
    check_equal(stock, load(ROOT / "certified_pointwise/stock_78.json"), "stock-coordinate summary")
    geometry = joint_geometry(load(folder / "panel.json"), load(ROOT / "certified/certificate.json"))
    save(out / "gains.json", gains)
    save(out / "geometry.json", geometry)
    return {"run": "study/" + folder.name, "sources": receipt["market_sources"], "euronext": paris,
            "panel_sha256": receipt["panel_sha256"], "joint_certificate_sha256": receipt["joint_certificate_sha256"],
            "point_certificate_sha256": receipt["point_certificate_sha256"], "joint": joint,
            "joint_geometry": geometry, "stock": stock["point"], "point_models": stock["certified_models"]}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--out", type=Path, required=True)
    cli.add_argument("--cache", type=Path, required=True)
    cli.add_argument("--download", action="store_true")
    cli.add_argument("--require-originals", action="store_true")
    args = cli.parse_args()
    report = review(args.out, args.cache, args.download, args.require_originals)
    save(args.out / "summary.json", report)
    print(json.dumps(report, indent=2))
