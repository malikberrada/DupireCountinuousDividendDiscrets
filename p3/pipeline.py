"""Download the study inputs, rebuild the as-of panel, then verify or fit on that panel."""

import csv
import os
import sys
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import capture
import euronext
import market
from certify import digest, verify
from p3_results import run_summary
from pointwise import runner as pointwise


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def market_data(cache, stage, offline, strict):
    distributed = market.check_files()
    all_sources = market.load(market.DATA / "sources.json")["originals"]
    spec = market.load(euronext.SOURCE / "source.json")
    paris_reference = market.load(euronext.SOURCE / "FIRDS-XMON.json")
    if digest(paris_reference) != spec["firds_projection_sha256"]:
        raise ValueError("Bundled Paris contract reference failed its checksum")
    original_paths = [cache / i["file"] for i in all_sources if i["service"] != "Deutsche Boerse"]
    if offline and not strict and not all(p.is_file() for p in original_paths):
        verified = []
        for item in all_sources:
            path = cache / item["file"]
            if path.is_file():
                if market.sha(path) != item["sha256"]:
                    raise ValueError("Original mismatch: " + str(path))
                verified.append(path.name)
        return distributed, market.trade_table(distributed), paris_reference, {
            "mode": "bundled_evidence", "originals_matched": len(verified), "originals_used": 0,
            "verified_cached_files": verified,
            "reason": "offline; original reference files missing",
        }

    evidence = stage / "evidence"
    acquisition = capture.replay(
        cache, evidence, download=not offline, pipeline=True, allow_archived=not strict
    )
    actual = market.panel(evidence)
    trades = market.trade_table(actual, evidence)
    paris = market.load(evidence / "FIRDS-XMON.json")
    if actual != distributed or trades != market.trade_table(distributed) or paris != paris_reference:
        raise ValueError("Newly reconstructed panel, trade ledger or Paris reference differs")
    acquisition["mode"] = (
        "originals" if acquisition["originals_matched"] == len(all_sources)
        else "originals_and_bundled_book_extracts"
    )
    return actual, trades, paris, acquisition


def run(args):
    cache = args.cache.resolve()
    out = args.out.resolve()
    offline = getattr(args, "offline", False)
    cache.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=out, prefix=".p3-") as temporary:
        tmp = Path(temporary)
        stage = tmp / "result"
        stage.mkdir()
        print("Acquisition du fichier de transactions d'Euronext Paris.", file=sys.stderr)
        paris_zip, paris_source = euronext.acquire(cache, offline, args.require_originals)
        print("Reconstruction du panel avec les sources Eurex, Xetra, ESMA, BCE et DILA.", file=sys.stderr)
        panel, trades, paris, sources = market_data(cache, stage, offline, args.require_originals)
        market.save(stage / "panel.json", panel)
        write_csv(stage / "eurex_trades.csv", trades)
        paris_summary = euronext.matched_trades(paris_zip, panel, paris, stage)

        print("Vérification des témoins et des bornes sur le panel reconstruit.", file=sys.stderr)
        proof = market.load(pointwise.BASELINE)
        joint, european_prices, poly = verify(panel, proof)
        market.save(stage / "joint.json", joint)
        write_csv(stage / "european_bounds.csv", european_prices)
        inputs = (panel, proof, poly)
        point_dir = stage / "pointwise"
        if args.action == "pointwise-fit":
            fit_args = Namespace(**vars(args))
            fit_args.out = point_dir
            report = pointwise.run(fit_args, inputs)
        else:
            certificate = market.load(args.certificate)
            report, prices = pointwise.replay_requested(inputs, args, certificate)
            point_dir.mkdir()
            market.save(point_dir / "summary.json", report)
            write_csv(point_dir / "american_prices.csv", prices)
            market.save(point_dir / "certificate.json", certificate)

        receipt = {
            "schema": "p3-acquisition/1", "asof": panel["asof"],
            "underlying": panel["underlying"], "product": panel["product"],
            "calibration_venue": "XEUR", "spot_venue": panel["spot"]["mic"],
            "contracts": len(panel["contracts"]), "panel_sha256": digest(panel),
            "joint_certificate_sha256": digest(proof),
            "point_certificate_sha256": market.sha(point_dir / "certificate.json"),
            "pointwise_models": len(report["certified_models"]),
            "market_sources": sources, "euronext": dict(paris_source, **paris_summary),
            "results": {"joint": joint, "pointwise": report, "european_bounds": european_prices},
        }
        market.save(stage / "pipeline.json", receipt)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_name = "run-" + stamp + "-" + uuid4().hex[:12]
        market.save(tmp / "latest.json", {"run": run_name, "report": run_name + "/pipeline.json"})
        os.replace(stage, out / run_name)
        os.replace(tmp / "latest.json", out / "latest.json")
    return run_summary(out / run_name, receipt)
