"""Rebuild provider evidence extracts from the archived original files (UTC timestamps)."""

import gzip
import http.client
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import p3_https
from market import (
    ASOF,
    DATA,
    EVIDENCE,
    OPT_FEED,
    SPOT_FEED,
    TRADE_FEED,
    UNDERLYING,
    contract,
    load,
    ns,
    save,
    sha,
)


def records(stream, end_tag):
    tail = b""
    while block := stream.read(2**20):
        chunks = (tail + block).split(end_tag)
        tail = chunks.pop()
        for rec in chunks:
            yield rec + end_tag
    if tail and end_tag in tail:
        raise ValueError("Unconsumed FIRDS record")


def reference_records(paths, venue):
    prefix = {"XEUR": b"<FullNm>TOTB ", "XMON": b"<FullNm>TotalEnergi (100) "}[venue]
    venue_tag = b">" + venue.encode("ascii") + b"<"
    refs = {}
    idtag = re.compile(rb"<FinInstrmGnlAttrbts><Id>([^<]+)</Id>")
    for path in paths:
        full = path.name.startswith("FULINS")
        tag = b"RefData" if full else b"FinInstrm"
        with zipfile.ZipFile(path) as archive, archive.open(archive.namelist()[0]) as stream:
            head = stream.read(1100)
            created = re.search(rb"<CreDt>([^<]+)</CreDt>", head)
            if created is None or ns(created[1].decode()) > ns(ASOF):
                raise ValueError("FIRDS file outside information set")
            stream.seek(0)
            for raw in records(stream, b"</" + tag + b">"):
                if venue_tag not in raw:
                    continue
                rid = idtag.search(raw)
                if prefix not in raw and (not rid or rid[1].decode() not in refs):
                    if b"Canc" not in raw and b"Cxl" not in raw:
                        continue
                start = raw.find(b"<" + tag + b">")
                if start < 0:
                    raise ValueError("Malformed FIRDS record")
                node = ET.fromstring(raw[start:])
                rec = node if full else node[0]
                if rec.findtext("TradgVnRltdAttrbts/Id") != venue:
                    if not full and rec.tag.startswith(("Canc", "Cxl")) and venue_tag in raw:
                        for field in rec.iter():
                            if field.text in refs:
                                refs.pop(field.text)
                    continue
                isin = rec.findtext("FinInstrmGnlAttrbts/Id")
                old = refs.get(isin)
                model = contract(rec, venue)
                if not model:
                    refs.pop(isin, None)
                elif full and old is not None and ET.tostring(old) != ET.tostring(rec):
                    raise ValueError("Ambiguous weekly FIRDS record: " + isin)
                else:
                    rec.tag = "RefData"
                    refs[isin] = rec
    return refs


def extract_refs(paths, out):
    refs = reference_records(paths, "XEUR")
    root = ET.Element("FIRDSExtract")
    for isin in sorted(refs):
        root.append(refs[isin])
    # A binary stream keeps the XML declaration's LF identical on Windows and Unix.
    with (out / "FIRDS.xml").open("wb") as stream:
        ET.ElementTree(root).write(stream, encoding="utf-8", xml_declaration=True)
    return set(refs)


def extract_books(folder, out, refs, archived_feeds=()):
    pat = re.compile(rb'"instrumentIdentificationCode"\s*:\s*"([^"]+)"')
    for feed in (SPOT_FEED, OPT_FEED, TRADE_FEED, TRADE_FEED + "-daily"):
        symbols = {s.encode() for s in (refs if feed != SPOT_FEED else [UNDERLYING])}
        target = out / (feed + ".ndjson.gz")
        if feed in archived_feeds:
            shutil.copyfile(EVIDENCE / target.name, target)
            continue
        suffix = "-2026-11-20.json.gz" if feed.endswith("-daily") else "-2026-11-20T12_00.json.gz"
        with gzip.open(folder / (feed + suffix), "rb") as source, open(target, "wb") as file:
            with gzip.GzipFile(filename="", mode="wb", fileobj=file, mtime=0) as gz:
                for line in source:
                    match = pat.search(line)
                    if match and match[1] in symbols:
                        if feed.endswith("-daily"):
                            r = json.loads(line)
                            if ns(r["publicationDateAndTime"]) > ns(ASOF) or ns(
                                r["tradingDateAndTime"]
                            ) > ns(ASOF):
                                continue
                        gz.write(line.rstrip() + b"\n")


class SourceExpired(RuntimeError):
    """The provider's successful listing no longer offers the pinned file."""


def listed_files(feed):
    with p3_https.open_url("https://mfs.deutsche-boerse.com/api/" + feed, timeout=45) as response:
        return json.load(response)["CurrentFiles"]


def fetch(item, folder):
    target = folder / item["file"]
    if target.exists() and sha(target) == item["sha256"]:
        return target
    if item["service"] == "Deutsche Boerse":
        if item["file"] not in listed_files(item["feed"]):
            raise SourceExpired(
                item["file"]
                + " has expired from the minute-file service; use archived evidence or an original copy."
            )
    with TemporaryDirectory(dir=folder, prefix=".fetch-") as temporary:
        return fetch_checked(item, Path(temporary) / target.name, target)


def fetch_checked(item, work, target):
    url = item["url"]
    for attempt in range(3):
        try:
            if item["service"] == "Deutsche Boerse":
                p3_https.download_db(url, work)
            else:
                p3_https.download(url, work, timeout=120)
            if sha(work) != item["sha256"]:
                raise ValueError("Provider revision or incomplete file: " + target.name)
            work.replace(target)
            return target
        except (ValueError, OSError, http.client.IncompleteRead) as exc:
            work.unlink(missing_ok=True)
            if attempt == 2:
                if isinstance(exc, http.client.IncompleteRead):
                    raise OSError("Incomplete download: " + target.name) from exc
                raise


def replay(folder, out, download=False, *, pipeline=False, allow_archived=False):
    folder = Path(folder)
    out = Path(out)
    folder.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    sources = load(DATA / "sources.json")
    origins = {}
    archived_feeds = set()
    # The minute files disappear first. Secure them before processing the reference data.
    for item in sorted(sources["originals"], key=lambda i: i["service"] != "Deutsche Boerse"):
        path = folder / item["file"]
        if path.is_file() and sha(path) == item["sha256"]:
            origins[path.name] = "cache"
            continue
        if path.exists() and not download:
            raise ValueError("Original mismatch: " + item["file"])
        if download:
            try:
                fetch(item, folder)
                origins[path.name] = "downloaded"
                continue
            except SourceExpired:
                if not allow_archived:
                    raise
        if allow_archived and item["service"] == "Deutsche Boerse":
            feed = item["feed"] + ("-daily" if "-daily-" in path.name else "")
            archived_feeds.add(feed)
            origins[path.name] = "bundled_extract"
        else:
            raise FileNotFoundError("Missing cached original: " + str(path))
    paths = [folder / i["file"] for i in sources["originals"] if i["service"] == "ESMA"]
    refs = extract_refs(paths, out)
    rebuilt = out / "FIRDS.xml"
    reference = EVIDENCE / "FIRDS.xml"
    if rebuilt.read_bytes() != reference.read_bytes():
        raise ValueError(
            f"Replay differs: FIRDS.xml (expected SHA-256 {sha(reference)}, rebuilt {sha(rebuilt)})"
        )
    extract_books(folder, out, refs, archived_feeds)
    for feed in (OPT_FEED, SPOT_FEED, TRADE_FEED, TRADE_FEED + "-daily"):
        name = feed + ".ndjson.gz"
        with gzip.open(out / name) as left, gzip.open(EVIDENCE / name) as right:
            if left.read() != right.read():
                raise ValueError("Replay differs: " + name)
    if (folder / "ECB.csv").read_bytes() != (EVIDENCE / "ECB.csv").read_bytes():
        raise ValueError("ECB record differs")
    result = {
        "originals_matched": len(sources["originals"]) - len(archived_feeds),
        "references": len(refs),
        "feed_extracts_matched": 4,
        "dividend_source_pdf_sha256": sha(folder / "half.pdf"),
    }
    if pipeline:
        shutil.copyfile(folder / "ECB.csv", out / "ECB.csv")
        # Structured facts transcribed from the pinned issuer filing, as in check_files().
        for name in ("DILA_record.json", "dividend.json"):
            shutil.copyfile(EVIDENCE / name, out / name)
        paris = reference_records(paths, "XMON")
        save(out / "FIRDS-XMON.json", [contract(paris[i], "XMON") for i in sorted(paris)])
        result["source_by_original"] = origins
    return result


def dividend_proof(folder):
    """Verify the archived PDF and the amount/ex/pay sentence on the cited page."""
    import unicodedata

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rec = load(EVIDENCE / "dividend.json")
    registered = load(EVIDENCE / "DILA_record.json")
    if (
        rec["dila_id"] != registered["uin_idt_uin"]
        or rec["source_url"] != registered["url_de_recuperation"]
        or rec["dila_filed_at"] != registered["uin_dat_amf"]
        or registered["identificationsociete_iso_cd_isi"] != UNDERLYING
    ):
        raise ValueError("DILA metadata mismatch")
    item = next(i for i in load(DATA / "sources.json")["originals"] if i["service"] == "DILA / AMF")
    source = fetch(item, folder)
    if sha(source) != rec["source_sha256"]:
        raise ValueError("Dividend source mismatch")
    page = rec["printed_page"]
    if shutil.which("pdftotext"):
        raw = subprocess.check_output(
            ["pdftotext", "-layout", "-f", str(page), "-l", str(page), str(source), "-"]
        ).decode()
    else:
        from pypdf import PdfReader

        raw = PdfReader(source).pages[page - 1].extract_text()
    plain = " ".join(unicodedata.normalize("NFKC", raw).lower().split())
    if not all(
        s in plain
        for s in ("0,90 euro par action", "31 décembre 2026", "5 janvier 2027", "22 juillet 2026")
    ):
        raise ValueError("Dividend entry not found on source page")
    return dict(
        issuer="TotalEnergies SE",
        record=rec["dila_id"],
        page=page,
        amount_eur=rec["amount"],
        ex_date=rec["ex_date"],
        pay_date=rec["pay_date"],
        source_sha256=rec["source_sha256"],
    )


def grab_minute(minute, folder):
    """Collect exactly the minute listed by each official MiFID service; keep its source hashes."""
    from datetime import datetime
    from tempfile import NamedTemporaryFile

    stamp = datetime.strptime(minute, "%Y-%m-%dT%H:%M").strftime("%Y-%m-%dT%H_%M")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    saved = []
    for feed in (OPT_FEED, SPOT_FEED, TRADE_FEED):
        name = f"{feed}-{stamp}.json.gz"
        url = "https://mfs.deutsche-boerse.com/api/download/" + name
        if name not in listed_files(feed):
            raise RuntimeError(feed + " does not list this UTC minute")
        path = folder / name
        if not path.exists():
            with NamedTemporaryFile(dir=folder, delete=False) as f:
                temp = Path(f.name)
            try:
                for i in range(3):
                    try:
                        p3_https.download_db(url, temp)
                        with gzip.open(temp) as f:
                            while f.read(2**20):
                                pass
                        temp.replace(path)
                        break
                    except (OSError, EOFError, http.client.IncompleteRead):
                        if i == 2:
                            raise
            finally:
                temp.unlink(missing_ok=True)
        saved.append(dict(file=name, url=url, sha256=sha(path)))
    save(folder / ("capture-" + stamp + ".json"), saved)
    return saved
