"""Read the supplied provider records, select the common as-of panel, and audit inputs."""

import csv
import gzip
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction as F
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
EVIDENCE = DATA / "evidence"
SPOT_FEED, OPT_FEED, TRADE_FEED = "DETR-pretrade", "DEUR-pretradeMDOptions", "DEUR-posttrade"
UNDERLYING = "FR0000120271"
ASOF = "2026-11-20T12:00:50.000000000Z"
EXPIRIES = ("2026-12-18", "2027-01-15")
RATE_KEY = "EST.B.EU000A2X2A25.WT"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, obj):
    Path(path).write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def sha(path):
    with open(path, "rb") as f:
        h = hashlib.sha256()
        while chunk := f.read(1 << 20):
            h.update(chunk)
        return h.hexdigest()


def ns(stamp):
    m = re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?Z", stamp)
    if not m:
        raise ValueError("Expected a UTC exchange timestamp: " + stamp)
    base = datetime.fromisoformat(m[1]).replace(tzinfo=timezone.utc)
    return int(base.timestamp()) * 10**9 + int((m[2] or "").ljust(9, "0"))


def latest(rows, time_key, limit):
    found = {}
    for r in rows:
        t = ns(r[time_key])
        key = r["instrumentIdentificationCode"]
        if t <= limit and (key not in found or t >= ns(found[key][time_key])):
            found[key] = r
    return found


def book(bids, asks):
    bb = [Decimal(str(x["price"])) for x in bids if Decimal(str(x["quantity"])) > 0]
    aa = [Decimal(str(x["price"])) for x in asks if Decimal(str(x["quantity"])) > 0]
    if not bb or not aa or not (0 < max(bb) <= min(aa)):
        return None
    return max(bb), min(aa)


def read_feed(feed, evidence=EVIDENCE):
    with gzip.open(evidence / (feed + ".ndjson.gz"), "rt", encoding="utf-8") as fh:
        return [json.loads(line, parse_float=str) for line in fh if line.strip()]


def contract(e, venue="XEUR"):
    g = e.find("FinInstrmGnlAttrbts")
    v = e.find("TradgVnRltdAttrbts")
    d = e.find("DerivInstrmAttrbts")
    if None in (g, v, d):
        return None
    amt = d.find("StrkPric/Pric/MntryVal/Amt")
    expiry = d.findtext("XpryDt")
    name = g.findtext("FullNm", "")
    sign = d.findtext("StrkPric/Pric/MntryVal/Sgn")
    if venue == "XEUR":
        if not (name.startswith("TOTB SI ") and name.endswith(" 0") and sign == "true"):
            return None
    elif venue == "XMON":
        if not name.startswith("TotalEnergi (100) OPTN PHYS AMER ") or sign not in (None, "true"):
            return None
    else:
        raise ValueError("Unknown derivatives venue: " + venue)
    if (
        v.findtext("Id") != venue
        or d.findtext("UndrlygInstrm/Sngl/ISIN") != UNDERLYING
        or expiry not in EXPIRIES
        or d.findtext("OptnExrcStyle") != "AMER"
        or d.findtext("DlvryTp") != "PHYS"
        or d.findtext("OptnTp") not in ("CALL", "PUTO")
        or amt is None
        or amt.get("Ccy") != "EUR"
        or g.findtext("NtnlCcy") != "EUR"
        or F(amt.text) <= 0
        or F(d.findtext("PricMltplr") or "0") != 100
        or not v.findtext("FrstTradDt")
        or ns(v.findtext("FrstTradDt")) > ns(ASOF)
        or e.findtext("TechAttrbts/PblctnPrd/FrDt", "0000") > ASOF[:10]
        or e.findtext("TechAttrbts/PblctnPrd/ToDt", "9999") < ASOF[:10]
        or v.findtext("TermntnDt", "9999")[:10] < ASOF[:10]
    ):
        return None
    return dict(
        isin=g.findtext("Id"),
        expiry=expiry,
        kind="call" if d.findtext("OptnTp") == "CALL" else "put",
        strike=str(Decimal(amt.text).normalize().quantize(1))
        if F(amt.text).denominator == 1
        else amt.text,
        multiplier=100,
        style="AMER",
        settlement="PHYS",
        underlying=UNDERLYING,
    )


def metadata(evidence=EVIDENCE):
    rows = [contract(r) for r in ET.parse(evidence / "FIRDS.xml").getroot()]
    out = {}
    for r in filter(None, rows):
        if r["isin"] in out and r != out[r["isin"]]:
            raise ValueError("Conflicting FIRDS records")
        out[r["isin"]] = r
    return out


def panel(evidence=EVIDENCE):
    limit = ns(ASOF)
    spotrows = [
        r
        for r in read_feed(SPOT_FEED, evidence)
        if r["instrumentIdentificationCode"] == UNDERLYING
        and r["venue"] == "XETB"
        and r["priceCurrency"] == "EUR"
    ]
    s = latest(spotrows, "publicationDateAndTime", limit)[UNDERLYING]
    if s.get("tradingSystem") != "CLOB" or s.get("tradingSystemPhase") != "COTR":
        raise ValueError("Spot book outside continuous trading")
    levels = book(s["side"].get("BUYI", []), s["side"].get("SELL", []))
    if levels is None or limit - ns(s["publicationDateAndTime"]) > 15 * 10**9:
        raise ValueError("Invalid spot book")
    sb, sa = levels
    mid = (sb + sa) / 2
    near = sorted(range(2, max(12, int(mid) + 15), 2), key=lambda k: (abs(k - mid), k))[:5]
    ref = metadata(evidence)
    opts = latest(read_feed(OPT_FEED, evidence), "mdupdateDateAndTime", limit)
    contracts = []
    for r in ref.values():
        if F(r["strike"]) not in near or r["isin"] not in opts:
            continue
        row = opts[r["isin"]]
        t = row["mdupdateDateAndTime"]
        quotes = book(row["mdBidMktDepthGroup1"], row["mdAskMktDepthGroup1"])
        if quotes is None or limit - ns(t) > 15 * 10**9:
            continue
        contracts.append(
            dict(r, bid=str(quotes[0]), ask=str(quotes[1]), timestamp=t, age_ns=limit - ns(t))
        )
    contracts.sort(key=lambda q: (q["expiry"], F(q["strike"]), q["kind"]))
    keys = {(q["expiry"], F(q["strike"]), q["kind"]) for q in contracts}
    expected = {(e, F(k), c) for e in EXPIRIES for k in near for c in ("call", "put")}
    if keys != expected or len(keys) != len(contracts):
        raise ValueError("Incomplete, duplicated or stale strike panel")
    ids = {r["isin"] for r in contracts}
    trades = [
        r
        for r in read_feed(TRADE_FEED, evidence)
        if r["instrumentIdentificationCode"] in ids
        and ns(r["publicationDateAndTime"]) <= limit
        and ns(r["tradingDateAndTime"]) <= limit
    ]
    day_trades = [
        r
        for r in read_feed(TRADE_FEED + "-daily", evidence)
        if r["instrumentIdentificationCode"] in ids
        and r["venueOfExecution"] == "XEUR"
        and ns(r["publicationDateAndTime"]) <= limit
        and ns(r["tradingDateAndTime"]) <= limit
    ]
    with open(evidence / "ECB.csv", encoding="utf-8-sig", newline="") as f:
        rate = [
            r
            for r in csv.DictReader(f)
            if r["KEY"] == RATE_KEY and r["TIME_PERIOD"] == "2026-11-19"
        ]
    if len(rate) != 1 or rate[0]["OBS_STATUS"] != "A":
        raise ValueError("Missing rate observation")
    div = load(evidence / "dividend.json")
    if (
        div["underlying"] != UNDERLYING
        or div["currency"] != "EUR"
        or div["status"] != "declared"
        or div["published_at"][:10] >= ASOF[:10]
        or div["ex_date"] > div["pay_date"]
        or F(div["amount"]) <= 0
    ):
        raise ValueError("Invalid or forward-looking dividend record")
    return dict(
        asof=ASOF,
        underlying=UNDERLYING,
        product="TOTB",
        spot=dict(
            bid=str(sb),
            ask=str(sa),
            mic="XETB",
            timestamp=s["publicationDateAndTime"],
            age_ns=limit - ns(s["publicationDateAndTime"]),
        ),
        rate_pct=rate[0]["OBS_VALUE"],
        rate_reference_date=rate[0]["TIME_PERIOD"],
        dividends=[div],
        expiries=list(EXPIRIES),
        contracts=contracts,
        posttrade_matches_before_asof=len(trades),
        day_posttrade_messages_before_asof=len(day_trades),
    )


def check_files():
    manifest = load(DATA / "sources.json")
    for name, digest in manifest["offline_sha256"].items():
        if sha(EVIDENCE / name) != digest:
            raise ValueError("Source hash mismatch: " + name)
    event = load(EVIDENCE / "dividend.json")
    register = load(EVIDENCE / "DILA_record.json")
    pdf = next(i for i in manifest["originals"] if i["service"] == "DILA / AMF")
    if (
        event["dila_id"] != register["uin_idt_uin"]
        or event["source_url"] != register["url_de_recuperation"]
        or event["dila_filed_at"] != register["uin_dat_amf"]
        or register["uin_dat_amf"][:10] >= ASOF[:10]
        or register["identificationsociete_iso_cd_isi"] != UNDERLYING
        or pdf["url"] != event["source_url"]
        or pdf["sha256"] != event["source_sha256"]
    ):
        raise ValueError("Dividend record does not match the regulatory filing")
    p = panel()
    if p != load(DATA / "panel.json"):
        raise ValueError("Market extraction differs from the frozen panel")
    with open(DATA / "trades.csv", newline="", encoding="utf-8") as f:
        if list(csv.DictReader(f)) != trade_table(p):
            raise ValueError("Trade ledger differs from the captured messages")
    return p


def trade_table(p, evidence=EVIDENCE):
    ids = {r["isin"] for r in p["contracts"]}
    rows = []
    for q in read_feed(TRADE_FEED + "-daily", evidence):
        if (
            q["instrumentIdentificationCode"] in ids
            and q["venueOfExecution"] == "XEUR"
            and max(ns(q["publicationDateAndTime"]), ns(q["tradingDateAndTime"])) <= ns(ASOF)
        ):
            rows.append(
                {
                    "isin": q["instrumentIdentificationCode"],
                    "executed_utc": q["tradingDateAndTime"],
                    "published_utc": q["publicationDateAndTime"],
                    "id": q["transactionIdentificationCode"],
                    "price": str(q["price"]),
                    "currency": q["priceCurrency"],
                    "quantity": str(q["quantity"]),
                    "flags": q["flags"],
                }
            )
    return sorted(rows, key=lambda r: (r["published_utc"], r["id"]))
