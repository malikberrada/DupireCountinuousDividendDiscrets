"""Acquire the dated Paris post-trade file and match its messages to P3 contracts."""

import csv
import hashlib
import http.client
import io
import shutil
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from datetime import date, datetime, timezone
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

import p3_https
from market import DATA, load, ns, sha

SOURCE = DATA / "euronext"
FIELDS = {
    "TradingDateTime", "PublicationDateTime", "MifidInstrumentID", "MifidPrice",
    "MifidQuantity", "MifidPriceNotation", "MifidCurrency", "Venue",
    "MmtModificationIndicator", "TradeUniqueIdentifier",
}
EXPORT_FIELDS = (
    "venue", "euronext_isin", "eurex_isin", "expiry", "kind", "strike",
    "executed_utc", "published_utc", "trade_id", "price_eur", "quantity",
)


class WindowRolled(RuntimeError):
    """The rolling URL supplied a complete CSV from a later session."""


def provider_csv(stream):
    # The service places a single copyright/terms line before the CSV header.
    first = stream.readline()
    if "Euronext" not in first or "Rights Reserved" not in first:
        raise ValueError("Missing Euronext CSV source notice")
    rows = csv.DictReader(stream)
    if not FIELDS.issubset(rows.fieldnames or ()):
        raise ValueError("Unexpected Euronext post-trade columns")
    return rows


def verify_zip(path, spec):
    """Check the CSV bytes. ZIP timestamps may change on a second HTTP request."""
    try:
        with zipfile.ZipFile(path) as archive:
            members = [f for f in archive.infolist() if not f.is_dir()]
            if len(members) != 1 or members[0].filename != spec["csv_member"]:
                raise ValueError("Unexpected Euronext archive member")
            h = hashlib.sha256()
            with archive.open(members[0]) as binary:
                while chunk := binary.read(1 << 20):
                    h.update(chunk)
            if h.hexdigest() == spec["csv_sha256"]:
                return
            # Only a genuine later session permits the documented rolling-window fallback.
            # A revision to the target date or an invalid CSV must surface as an error.
            with archive.open(members[0]) as binary, io.TextIOWrapper(
                binary, encoding="utf-8-sig", newline=""
            ) as stream:
                sessions = set()
                for row in provider_csv(stream):
                    ns(row["PublicationDateTime"])
                    sessions.add(date.fromisoformat(row["PublicationDateTime"][:10]))
            if sessions and min(sessions) > date.fromisoformat(spec["session"]):
                raise WindowRolled("Euronext now serves " + ", ".join(map(str, sorted(sessions))))
            raise ValueError("Euronext CSV differs from the recorded session or its SHA-256")
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid or incomplete Euronext ZIP: " + str(path)) from exc


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "DupireIdentify/1.0"})
    for attempt in range(3):
        try:
            p3_https.download(req, dest, timeout=90)
            return
        except urllib.error.HTTPError as exc:
            if exc.code not in (408, 429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (TimeoutError, urllib.error.URLError, http.client.IncompleteRead, ConnectionError) as exc:
            if attempt == 2:
                raise OSError("Euronext download failed after three attempts: " + str(exc)) from exc
        time.sleep(2 ** attempt)


def acquire(cache, offline=False, require_originals=False):
    spec = load(SOURCE / "source.json")
    target = Path(cache) / spec["file"]
    target.parent.mkdir(parents=True, exist_ok=True)

    def result(path, origin, reason=None, retrieved=None):
        return path, {
            "origin": origin, "url": spec["url"], "session": spec["session"],
            "file": path.name, "zip_sha256": sha(path), "csv_sha256": spec["csv_sha256"],
            "retrieved_this_run_utc": retrieved, "fallback_reason": reason,
        }

    if target.is_file():
        try:
            verify_zip(target, spec)
            return result(target, "cache")
        except (ValueError, WindowRolled):
            if offline:
                raise ValueError("Invalid Euronext cache entry: " + str(target))
    reason = "offline"
    if not offline:
        with TemporaryDirectory(dir=target.parent, prefix=".euronext-") as temporary:
            part = Path(temporary) / target.name
            try:
                download(spec["url"], part)
                verify_zip(part, spec)
            except WindowRolled as exc:
                reason = str(exc)
            except urllib.error.HTTPError as exc:
                if exc.code not in (404, 410):
                    raise
                reason = "Euronext HTTP " + str(exc.code)
            else:
                part.replace(target)
                return result(target, "downloaded", retrieved=datetime.now(timezone.utc).isoformat())
    if require_originals:
        raise RuntimeError("Dated Euronext file unavailable (" + reason + "). Expected " + str(target))
    frozen = SOURCE / spec["file"]
    if sha(frozen) != spec["bundled_zip_sha256"]:
        raise ValueError("Bundled Euronext original failed SHA-256")
    verify_zip(frozen, spec)
    return result(frozen, "bundled_original", reason)


def matched_trades(path, panel, paris_refs, out):
    spec = load(SOURCE / "source.json")
    if panel["asof"][:10] != spec["session"]:
        raise ValueError("Euronext file and P3 panel have different trading dates")
    limit = ns(panel["asof"])

    def key(q):
        return (q["underlying"], q["expiry"], Fraction(q["strike"]), q["kind"],
                q["style"], q["settlement"], q["multiplier"])

    by_terms = {key(q): q["isin"] for q in panel["contracts"]}
    if len(by_terms) != len(panel["contracts"]):
        raise ValueError("Ambiguous Eurex contract terms")
    matches = {p["isin"]: (p, by_terms[key(p)]) for p in paris_refs if key(p) in by_terms}
    rows = {}
    flagged = set()
    ordinary_messages = 0
    total = 0
    sessions = Counter()
    with zipfile.ZipFile(path) as archive, archive.open(spec["csv_member"]) as binary, \
            io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as stream:
        for r in provider_csv(stream):
            total += 1
            sessions[r["PublicationDateTime"][:10]] += 1
            isin = r["MifidInstrumentID"]
            if r["Venue"] != spec["venue"] or isin not in matches:
                continue
            published = r["PublicationDateTime"]
            executed = r["TradingDateTime"]
            if ns(published) > limit or executed[:10] != spec["session"] or ns(executed) > limit:
                continue
            trade_id = r["TradeUniqueIdentifier"]
            if not trade_id:
                raise ValueError("Missing Euronext trade identifier")
            identifier = (isin, trade_id)
            if r["MmtModificationIndicator"] != "-":
                flagged.add(identifier)
                continue
            if r["MifidCurrency"] != "EUR" or r["MifidPriceNotation"] != "MONE":
                continue
            if Fraction(r["MifidPrice"]) < 0 or Fraction(r["MifidQuantity"]) <= 0:
                raise ValueError("Invalid price or quantity on a matched Euronext message")
            p, eurex_isin = matches[isin]
            ordinary_messages += 1
            row = dict(
                venue=r["Venue"], euronext_isin=isin, eurex_isin=eurex_isin,
                expiry=p["expiry"], kind=p["kind"], strike=p["strike"], executed_utc=executed,
                published_utc=published, trade_id=trade_id, price_eur=r["MifidPrice"],
                quantity=r["MifidQuantity"],
            )
            if identifier in rows and rows[identifier] != row:
                raise ValueError("Conflicting unflagged Euronext trade identifier: " + trade_id)
            rows[identifier] = row
    if set(sessions) != {spec["session"]}:
        raise ValueError("Euronext publication dates do not match the certified session")
    kept = sorted((row for k, row in rows.items() if k not in flagged),
                  key=lambda r: (ns(r["published_utc"]), r["trade_id"], r["euronext_isin"]))
    with (out / "euronext_trades.csv").open("w", encoding="utf-8", newline="") as stream:
        w = csv.DictWriter(stream, fieldnames=EXPORT_FIELDS)
        w.writeheader()
        w.writerows(kept)
    shutil.copyfile(SOURCE / "NOTICE.txt", out / "EURONEXT-NOTICE.txt")
    return {
        "venue": spec["venue"], "role": "post_trade_context", "rows_in_source_csv": total,
        "matched_series_in_reference": len(matches), "ordinary_messages_before_cut": ordinary_messages,
        "flagged_ids_before_cut": len(flagged), "trades_retained": len(kept),
        "series_with_trades": len({r["euronext_isin"] for r in kept}),
    }
