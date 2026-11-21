"""Discounted total-gains martingale, calendar, exercise thresholds and exact Snell replay."""

from datetime import date, timedelta
from fractions import Fraction as F

CLOSED = {date.fromisoformat(s) for s in ("2026-12-24", "2026-12-25", "2026-12-31", "2027-01-01")}


def trading(d):
    return d.weekday() < 5 and d not in CLOSED


def roll(d, n):
    while n:
        d += timedelta(days=1)
        if trading(d):
            n -= 1
    return d


def intrinsic(kind, y, h):
    return max(F(0), y - h if kind == "call" else h - y)


class Market:
    def __init__(self, panel):
        self.panel = panel
        self.today = date.fromisoformat(panel["asof"][:10])
        self.expiries = [date.fromisoformat(s) for s in panel["expiries"]]
        if len(self.expiries) != 2 or not self.today < self.expiries[0] < self.expiries[1]:
            raise ValueError("Two increasing future expiries are required")
        if "calendar" in panel:
            cal = panel["calendar"]
            self.trading_dates = {date.fromisoformat(d) for d in cal["exercise_days"]}
            settlement_dates = sorted({date.fromisoformat(d) for d in cal["settlement_days"]})
            if not {self.today, *self.expiries} <= self.trading_dates:
                raise ValueError("Incomplete exercise calendar")

            def settle(d, n):
                future = [v for v in settlement_dates if v > d]
                if len(future) < n:
                    raise ValueError("Incomplete settlement calendar")
                return future[n - 1]
        else:
            if self.today != date(2026, 11, 20) or self.expiries != [
                date(2026, 12, 18),
                date(2027, 1, 15),
            ]:
                raise ValueError("Supply exercise_days and settlement_days for this panel")
            self.trading_dates = {
                self.today + timedelta(days=n)
                for n in range((self.expiries[-1] - self.today).days + 1)
                if trading(self.today + timedelta(days=n))
            }
            settle = roll
        self.settle = settle
        ids = [q["isin"] for q in panel["contracts"]]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("Missing or duplicate contracts")
        for q in panel["contracts"]:
            if (
                q["style"] != "AMER"
                or q["settlement"] != "PHYS"
                or q["underlying"] != panel["underlying"]
                or q["kind"] not in ("call", "put")
                or F(q["strike"]) <= 0
                or not 0 <= F(q["bid"]) <= F(q["ask"])
            ):
                raise ValueError("Invalid option record")
        if not 0 < F(panel["spot"]["bid"]) <= F(panel["spot"]["ask"]):
            raise ValueError("Invalid spot quote")
        for d in panel["dividends"]:
            if (
                d["underlying"] != panel["underlying"]
                or d["currency"] != "EUR"
                or d["status"] not in ("declared", "scenario")
                or F(d["amount"]) < 0
                or d["pay_date"] < d["ex_date"]
            ):
                raise ValueError("Invalid dividend scenario")
        self.rate = F(panel["rate_pct"]) / 100
        self.divs = [
            (date.fromisoformat(d["ex_date"]), date.fromisoformat(d["pay_date"]), F(d["amount"]))
            for d in panel["dividends"]
        ]
        self.prem = self.disc(settle(self.today, 1))
        self.zlo, self.zhi = [
            F(panel["spot"][s]) * self.disc(settle(self.today, 2)) for s in ("bid", "ask")
        ]
        self.z = (self.zlo + self.zhi) / 2
        self.floor = sum(
            (
                self.disc(pay) * amount
                for ex, pay, amount in self.divs
                if self.today < ex <= self.expiries[-1]
            ),
            F(0),
        )
        self.contracts = []
        for market_quote in panel["contracts"]:
            T = date.fromisoformat(market_quote["expiry"])
            if T not in self.expiries or T not in self.trading_dates:
                raise ValueError("Invalid expiry")
            maturity = self.expiries.index(T)
            K = F(market_quote["strike"])
            days = [self.today + timedelta(days=n) for n in range((T - self.today).days + 1)]
            days = [d for d in days if d in self.trading_dates]

            def barrier(d, strike):
                paid = sum(
                    (amt * self.disc(pay) for ex, pay, amt in self.divs if self.today < ex <= d),
                    F(0),
                )
                return strike * self.disc(settle(d, 2)) + paid

            hs = {d: barrier(d, K) for d in days}
            kind = market_quote["kind"]
            h = hs[T]
            best = min if kind == "call" else max
            # Each reveal occurs during its expiry day, before the exercise cutoff.
            h0 = best(v for d, v in hs.items() if d <= self.expiries[0])
            h1 = best(v for d, v in hs.items() if self.expiries[0] <= d <= T)
            early = best(hs.values())
            self.contracts.append(
                dict(
                    id=market_quote["isin"],
                    m=maturity,
                    K=K,
                    kind=kind,
                    h=h,
                    h0=h0,
                    h1=h1,
                    premium=abs(h - early),
                    now=hs[self.today],
                    bid=F(market_quote["bid"]) * self.prem,
                    ask=F(market_quote["ask"]) * self.prem,
                )
            )

    def disc(self, d):
        den = 1 + self.rate * F((d - self.today).days, 360)
        if den <= 0:
            raise ValueError("Nonpositive discount factor")
        return 1 / den

    @property
    def yeargap(self):
        return F((self.expiries[1] - self.expiries[0]).days, 365)


def evaluate(market, witness):
    rows = [
        (F(k), F(v["p"]), [(F(y), F(p)) for y, p in v["next"].items()])
        for k, v in witness["states"].items()
    ]
    z = F(witness["z"])
    if (
        not market.zlo <= z <= market.zhi
        or sum(p for x, p, T in rows) != 1
        or sum(x * p for x, p, T in rows) != z
    ):
        raise ValueError("Invalid root spot or martingale")
    for x, p, trans in rows:
        if p <= 0 or x < market.floor or any(q <= 0 or y < market.floor for y, q in trans):
            raise ValueError("Invalid mass or cash-dividend floor")
        if sum(q for y, q in trans) != 1 or sum(y * q for y, q in trans) != x:
            raise ValueError("Invalid conditional martingale")
    prices = {}
    for c in market.contracts:
        american = european = F(0)
        for x, p, t in rows:
            if c["m"] == 0:
                e = intrinsic(c["kind"], x, c["h"])
                a = e
            else:
                e = sum(q * intrinsic(c["kind"], y, c["h"]) for y, q in t)
                a = max(intrinsic(c["kind"], x, c["h1"]), e)
            american += p * a
            european += p * e
        american = max(intrinsic(c["kind"], z, c["h0"]), american)
        if not c["bid"] <= american <= c["ask"]:
            raise ValueError("American spread violated: " + c["id"])
        if not european <= american <= european + c["premium"]:
            raise ValueError("Exercise bound failed")
        prices[c["id"]] = (
            european / market.prem,
            american / market.prem,
            min(american - c["bid"], c["ask"] - american) / market.prem,
        )

    def call(j, k):
        return sum(
            p
            * (
                intrinsic("call", x, k)
                if j == 0
                else sum(q * intrinsic("call", y, k) for y, q in t)
            )
            for x, p, t in rows
        )

    return prices, call
