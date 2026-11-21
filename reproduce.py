"""Reproduce the P2 and P3 results and write a fresh review run."""

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

ROOT = Path(__file__).resolve().parent


def verify_inputs():
    entries = json.loads((ROOT / "checksums.json").read_bytes())
    for name, expected in entries.items():
        path = ROOT / name
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Archived input mismatch in {name}: expected {expected}, obtained {actual}")
    return len(entries)


def run_script(script, arguments):
    subprocess.run([sys.executable, "-B", str(ROOT / script), *map(str, arguments)],
                   cwd=ROOT, env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                   stdout=subprocess.DEVNULL, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true",
                        help="fetch both Taiwanese responses and use the P3 market acquisition pipeline")
    parser.add_argument("--require-originals", action="store_true",
                        help="require all 28 P3 originals from providers or cache, including with offline replay")
    parser.add_argument("--out", type=Path, default=ROOT / "runs", help="parent of each new verification run")
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache" / "p3",
                        help="directory for P3 provider originals, used in acquisition or strict replay")
    args = parser.parse_args()
    out = args.out.resolve()
    count = verify_inputs()
    out.mkdir(parents=True, exist_ok=True)
    print(f"Validated {count} archived inputs and reference files (SHA-256).", flush=True)
    with TemporaryDirectory(prefix=".review-", dir=out) as tmp:
        stage = Path(tmp) / "review"
        stage.mkdir()
        options = ["--download"] if args.download else []
        print("P2 | TAIFEX/TWSE, 95 pairs, and two synthetic diffusion proofs", flush=True)
        run_script("p2/review.py", ["--out", stage / "p2", *options])
        print("P3 | Eurex/Xetra, joint witnesses, point volatility and Euronext trades", flush=True)
        # A normal offline review uses only committed evidence, independently of any local cache.
        cache = args.cache.resolve() if args.download or args.require_originals else Path(tmp) / "offline-cache"
        strict = ["--require-originals"] if args.require_originals else []
        run_script("p3/review.py", ["--out", stage / "p3", "--cache", cache, *options, *strict])
        p2 = json.loads((stage / "p2/summary.json").read_bytes())
        p3 = json.loads((stage / "p3/summary.json").read_bytes())
        stamp = datetime.now(timezone.utc)
        receipt = {"verified": True, "completed_utc": stamp.isoformat(), "python": sys.version.split()[0],
                   "archived_files_checked": count, "download_requested": args.download,
                   "p2_sources": p2["official_inputs"]["origin"], "p2_panel_sha256": p2["official_inputs"]["panel_sha256"],
                   "p3_sources": p3["sources"]["mode"], "euronext_origin": p3["euronext"]["origin"],
                   "p3_panel_sha256": p3["panel_sha256"], "p2_summary": "p2/summary.json",
                   "p3_summary": "p3/summary.json", "p3_run": "p3/" + p3["run"]}
        (stage / "verification.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        dest = out / ("review-" + stamp.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
        stage.rename(dest)
    select, full = p2["selected"], p2["full_panel"]
    point = p3["stock"]
    print(f"P2 | {select['fixed_both_in_spread']}/{select['contracts']} selected TXO contracts. The "
          f"maximum fixed-model tree error is {select['max_fixed_eta_points']:.8f} index points.")
    print(f"P2 | {full['continuous_inside']}/{full['contracts']} contracts inside on the full panel.")
    print(f"P3 | {p3['joint']['common_witnesses']} common witnesses for {p3['joint']['contracts']} contracts.")
    lo, hi = point['affine_speed_volatility_pct_outer']
    print(f"P3 | stock at EUR {point['level_eur']} on {point['at_utc']}. "
          f"The affine-speed volatility bounds are {lo}% to {hi}%.")
    print(f"Verified. Results are in {dest}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(f"Review failed: {error}")
