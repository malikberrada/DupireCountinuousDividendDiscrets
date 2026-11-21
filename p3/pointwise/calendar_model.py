"""Cash dividends, daily exercise barriers and a smooth, positive Markov diffusion."""

import math
import re
from datetime import datetime, time, timezone
from fractions import Fraction as F

from model import Market

from pointwise.gaussian import sqrt_hi

UTC = timezone.utc
DAY = 86400


def instant(text):
    # Python 3.10 requires exactly 3 or 6 fractional digits. Preserve microseconds.
    def microseconds(match):
        digits = match[1]
        if any(c != "0" for c in digits[6:]):
            raise ValueError("The point must be representable in microseconds")
        return "." + digits[:6].ljust(6, "0")

    q = datetime.fromisoformat(
        re.sub(r"(?<=:\d\d)\.(\d+)", microseconds, text).replace("Z", "+00:00")
    )
    if q.utcoffset() is None:
        raise ValueError("Include a timezone in the timestamp")
    return q.astimezone(UTC)


def days_between(a, b):
    d = b - a
    return F((d.days * DAY + d.seconds) * 10**6 + d.microseconds, DAY * 10**6)


class CalendarModel:
    def __init__(self, panel, parameters):
        self.market = m = Market(panel)
        self.t0 = instant(panel["asof"])
        self.dates = sorted(d for d in m.trading_dates if m.today <= d <= m.expiries[-1])
        self.closes = [datetime.combine(d, time(19), UTC) for d in self.dates]
        self.ages = [F(0)] + [days_between(self.t0, t) for t in self.closes]
        self.z, self.a, self.b = (
            F(parameters[k]) for k in ("prepaid_spot", "variance_intercept", "variance_slope")
        )
        self.floor = F(parameters["floor"])
        self.flat_from = F(parameters["flat_from"])
        if not (
            m.zlo <= self.z <= m.zhi
            and m.floor < self.floor < self.flat_from < self.z
            and self.ages[1] > 0
            and min(self.speed(self.ages[0]), self.speed(self.ages[-1])) > 0
        ):
            raise ValueError("Invalid diffusion, reserve, calendar or spot")
        self.variances = [
            (v - u) * (self.a + self.b * (u + v) / 2) for u, v in zip(self.ages, self.ages[1:])
        ]
        self.thresholds = []
        for d in self.dates:
            q = self.paid(d)
            self.thresholds.append([q + c["K"] * m.disc(m.settle(d, 2)) for c in m.contracts])

    def state_factor(self, x):
        """Floating evaluation of the smooth cutoff defined in POINTWISE.md."""
        if x <= self.floor:
            return 0.0
        if x >= self.flat_from:
            return 1.0
        y = float((x - self.floor) / (self.flat_from - self.floor))
        if y <= 0 or y >= 1:
            return float(y >= 1)
        log_ratio = 1 / (1 - y) - 1 / y
        if log_ratio >= 0:
            return 1 / (1 + math.exp(-log_ratio))
        e = math.exp(log_ratio)
        return e / (1 + e)

    def speed(self, t):
        return self.a + self.b * t

    def paid(self, d):
        return sum(
            (a * self.market.disc(p) for e, p, a in self.market.divs if self.market.today < e <= d),
            F(0),
        )

    def coupling_error(self, variance):
        # Reflection, Chernoff and Doob L2 control every stopping policy.
        x = (self.z - self.flat_from) ** 2 / (2 * variance)
        hit = min(F(1), 2 * (1 + x / 256) ** (-256))
        return 2 * sqrt_hi(variance * hit, 10**12)
