import csv
import io
import json
import shutil
import subprocess
import sys
import unittest
import urllib.error
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import capture
import euronext
from market import ASOF, EVIDENCE, ROOT, check_files, load, save, sha
from p3_eurex import main


def windows_open(path, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
    if "w" in mode and "b" not in mode and newline is None:
        newline = "\r\n"
    return open(path, mode, buffering, encoding, errors, newline)


class FirdsReplay(unittest.TestCase):
    def weekly_archive(self, folder, records):
        report = ET.Element("FinInstrmRptgRefDataRpt")
        ET.SubElement(report, "CreDt").text = "2026-11-14T00:00:00Z"
        report.extend(records)
        path = folder / "FULINS_test.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("reference.xml", ET.tostring(report, encoding="utf-8"))
        return path

    def test_windows_writer_matches_published_firds_bytes(self):
        reference = EVIDENCE / "FIRDS.xml"
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            weekly = self.weekly_archive(folder, ET.parse(reference).getroot())
            with (
                patch.object(ET, "open", windows_open, create=True),
                patch.object(Path, "open", windows_open),
            ):
                refs = capture.extract_refs([weekly], folder)
            self.assertEqual(len(refs), 185)
            self.assertEqual((folder / "FIRDS.xml").read_bytes(), reference.read_bytes())

    def test_changed_strike_fails_replay(self):
        reference = EVIDENCE / "FIRDS.xml"
        records = ET.parse(reference).getroot()
        amount = records[0].find("DerivInstrmAttrbts/StrkPric/Pric/MntryVal/Amt")
        amount.text = str(int(amount.text) + 1)
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            weekly = self.weekly_archive(folder, records)
            source = {"file": weekly.name, "service": "ESMA", "sha256": sha(weekly)}
            save(folder / "sources.json", {"originals": [source]})
            out = folder / "out"
            with patch.object(capture, "DATA", folder), self.assertRaises(ValueError) as raised:
                capture.replay(folder, out)
            self.assertIn("Replay differs: FIRDS.xml", str(raised.exception))
            self.assertIn(sha(reference), str(raised.exception))
            self.assertIn(sha(out / "FIRDS.xml"), str(raised.exception))


class Acquisition(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = check_files()
        cls.spec = load(euronext.SOURCE / "source.json")
        cls.frozen = euronext.SOURCE / cls.spec["file"]
        cls.refs = load(euronext.SOURCE / "FIRDS-XMON.json")

    def small_zip(self, path, rows):
        csv_text = io.StringIO()
        csv_text.write("(c) Euronext N.V. All Rights Reserved. Test fixture.\n")
        w = csv.DictWriter(csv_text, fieldnames=sorted(euronext.FIELDS))
        w.writeheader()
        w.writerows(rows)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(self.spec["csv_member"], csv_text.getvalue())

    def row(self, **changes):
        return dict({
            "TradingDateTime": ASOF, "PublicationDateTime": ASOF, "TradeUniqueIdentifier": "id",
            "MifidInstrumentID": self.refs[0]["isin"], "Venue": "XMON", "MifidCurrency": "EUR",
            "MifidPriceNotation": "MONE", "MifidPrice": "3.25", "MifidQuantity": "2",
            "MmtModificationIndicator": "-",
        }, **changes)

    def test_download_validates_csv_and_reuses_cache(self):
        with TemporaryDirectory() as tmp:
            cache = Path(tmp)

            def repack(url, dest):
                self.assertEqual(url, self.spec["url"])
                with zipfile.ZipFile(self.frozen) as source, zipfile.ZipFile(dest, "w") as output:
                    name = self.spec["csv_member"]
                    output.writestr(name, source.read(name))

            with patch("euronext.download", side_effect=repack) as network:
                file, first = euronext.acquire(cache, require_originals=True)
                reused, second = euronext.acquire(cache, require_originals=True)
            network.assert_called_once()
            self.assertEqual(file, reused)
            self.assertEqual((first["origin"], second["origin"]), ("downloaded", "cache"))
            self.assertNotEqual(first["zip_sha256"], self.spec["bundled_zip_sha256"])
            self.assertEqual(first["csv_sha256"], self.spec["csv_sha256"])

    def test_rolling_url_and_revision_are_distinct(self):
        later = self.row(PublicationDateTime="2026-11-23T12:00:00Z")
        with TemporaryDirectory() as tmp:
            cache = Path(tmp)
            with patch("euronext.download", side_effect=lambda u, p: self.small_zip(p, [later])):
                path, receipt = euronext.acquire(cache)
                self.assertEqual(path, self.frozen)
                self.assertEqual(receipt["origin"], "bundled_original")
                with self.assertRaisesRegex(RuntimeError, "2026-11-23"):
                    euronext.acquire(cache, require_originals=True)
            with patch("euronext.download", side_effect=lambda u, p: self.small_zip(p, [self.row()])):
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    euronext.acquire(cache)
            self.assertFalse((cache / self.spec["file"]).exists())

    def test_http_failure_and_damaged_cache(self):
        with TemporaryDirectory() as tmp:
            cache = Path(tmp)
            error = urllib.error.HTTPError(self.spec["url"], 403, "denied", {}, None)
            with patch("euronext.download", side_effect=error), self.assertRaises(urllib.error.HTTPError):
                euronext.acquire(cache)
            target = cache / self.spec["file"]
            target.write_bytes(b"interrupted")
            with self.assertRaisesRegex(ValueError, "cache"):
                euronext.acquire(cache, offline=True)
            with patch("euronext.download", side_effect=lambda u, p: shutil.copyfile(self.frozen, p)):
                self.assertEqual(euronext.acquire(cache)[1]["origin"], "downloaded")

    def test_match_requires_both_times_and_processing_flags(self):
        terms = {(q["kind"], q["expiry"], q["strike"]) for q in self.panel["contracts"]}
        isin = next(q["isin"] for q in self.refs if (q["kind"], q["expiry"], q["strike"]) in terms)
        base = self.row(MifidInstrumentID=isin)
        later = "2026-11-20T12:00:50.000000001Z"
        rows = [
            base, base, dict(base, TradeUniqueIdentifier="canceled"),
            dict(base, TradeUniqueIdentifier="canceled", MmtModificationIndicator="CANC"),
            dict(base, TradeUniqueIdentifier="future-trade", TradingDateTime=later),
            dict(base, TradeUniqueIdentifier="future-publication", PublicationDateTime=later),
            dict(base, Venue="XEUR"), dict(base, MifidInstrumentID="unmatched"),
        ]
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.small_zip(out / "paris.zip", rows)
            stats = euronext.matched_trades(out / "paris.zip", self.panel, self.refs, out)
            with (out / "euronext_trades.csv").open(encoding="utf-8", newline="") as src:
                retained = list(csv.DictReader(src))
            self.assertEqual(stats["trades_retained"], 1)
            self.assertEqual(stats["flagged_ids_before_cut"], 1)
            self.assertEqual(retained[0]["trade_id"], "id")
            self.assertNotEqual(retained[0]["euronext_isin"], retained[0]["eurex_isin"])

    def test_offline_pipeline_and_failed_rerun(self):
        with (
            TemporaryDirectory() as tmp,
            patch("p3_https.open_url", side_effect=AssertionError),
            patch("p3_https.download_db", side_effect=AssertionError),
        ):
            root = Path(tmp)
            args = ["pipeline", "--offline", "--cache", str(root / "cache"), "--out", str(root / "out")]
            with patch.object(Path, "open", windows_open):
                result = main(args)
            output = Path(result["run"])
            receipt = load(output / "pipeline.json")
            self.assertEqual(receipt["contracts"], 20)
            self.assertEqual(receipt["pointwise_models"], 3)
            self.assertEqual(
                receipt["point_certificate_sha256"], sha(ROOT / "certified_pointwise/certificate.json")
            )
            self.assertEqual(receipt["euronext"]["origin"], "bundled_original")
            self.assertEqual(receipt["euronext"]["rows_in_source_csv"], 46037)
            self.assertEqual(receipt["euronext"]["trades_retained"], 8)
            self.assertEqual(receipt["euronext"]["series_with_trades"], 6)
            point = load(output / "pointwise" / "summary.json")["point"]
            self.assertEqual(point["affine_speed_volatility_pct_outer"], ["23.136334", "25.617386"])
            results = result["results"]
            self.assertEqual(results, receipt["results"])
            self.assertEqual(results["joint"], load(output / "joint.json"))
            self.assertEqual(results["pointwise"], load(output / "pointwise" / "summary.json"))
            self.assertEqual(len(results["european_bounds"]), 20)
            replay_args = ["results", "--out", str(root / "out")]
            self.assertEqual(main(replay_args), result)
            # A run written before the display change has no embedded results.
            del receipt["results"]
            save(output / "pipeline.json", receipt)
            self.assertEqual(main(["results", "--run", str(output)]), result)
            cli = [sys.executable, str(ROOT / "p3_eurex.py"), *replay_args]
            text_report = subprocess.check_output(cli + ["--format", "text"], text=True)
            self.assertIn("47 témoins", text_report)
            self.assertIn("[0.01315423, 0.07774606]", text_report)
            self.assertIn("[23.136334, 25.617386]", text_report)
            price_lines = [line for line in text_report.splitlines() if line.startswith(tuple(results["joint"]["expiries"]))]
            self.assertEqual(len(price_lines), len(results["european_bounds"]))
            self.assertEqual(json.loads(subprocess.check_output(cli, text=True)), result)
            self.assertNotIn("results", load(output / "pipeline.json"))
            with self.assertRaisesRegex(RuntimeError, "Euronext"):
                main(args + ["--require-originals"])
            self.assertEqual(load(root / "out" / "latest.json")["run"], output.name)
            self.assertEqual(len(list((root / "out").glob("run-*"))), 1)


if __name__ == "__main__":
    unittest.main()
