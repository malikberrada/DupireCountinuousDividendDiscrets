"""Exact clock invariance and pointwise coefficients in calendar time, ACT/365F."""

from datetime import datetime, time, timedelta, timezone
from fractions import Fraction as F

from pointwise.calendar_model import days_between


def target(book, at, level, coordinate):
    if not book.t0 < at < book.closes[-1]:
        raise ValueError("Point must lie strictly inside the panel horizon")
    level = F(level)
    if level <= 0:
        raise ValueError("Positive target level required")
    if coordinate not in ("gains", "stock"):
        raise ValueError("Choose gains or stock")
    # Winter trading, CET=UTC+1 over this entire archived horizon.
    local = at.astimezone(timezone(timedelta(hours=1)))
    d = local.date()
    if coordinate == "stock":
        if d not in book.dates or local.time() == time(0):
            raise ValueError("Use a regular trading instant for the quoted stock")
        denominator = level * book.market.disc(book.market.settle(d, 2))
        k = book.paid(d) + denominator
    else:
        k = denominator = level
    if k < book.flat_from:
        raise ValueError(
            "This rational point certificate covers gains states at or above the flat cutoff"
        )
    return k, denominator


def radius_seconds(book, at):
    # Cutoffs, calendar-day changes, ex-dates and valuation endpoints are fixed by the clock.
    cet = timezone(timedelta(hours=1))
    dates = [
        book.market.today + timedelta(days=n)
        for n in range((book.dates[-1] - book.market.today).days + 2)
    ]
    landmarks = [book.t0, *book.closes, *[datetime.combine(d, time(0), cet) for d in dates]]
    distances = [abs(days_between(at, s)) * 86400 for s in landmarks if s != at]
    return min(F(1800), min(distances) / 2)


def point(book, at, level, coordinate, sigmas):
    k, den = target(book, at, level, coordinate)
    t = days_between(book.t0, at)
    speed = 365 * book.speed(t)
    if speed <= 0:
        raise ValueError("Base diffusion is inactive at the target")
    witnesses = []
    for rate in map(F, sigmas):
        if rate < 0:
            raise ValueError("Volatility must be nonnegative")
        r = rate**2 * den**2 / speed
        if speed * r / den**2 != rate**2:
            raise ArithmeticError("Clock slope does not realize the request")
        witnesses.append(
            {
                "volatility": str(rate),
                "clock_derivative": str(r),
                "variance_at_point": str(speed * r / den**2),
            }
        )
    return {
        "k": k,
        "denominator": den,
        "base_variance": speed / den**2,
        "warp_radius_seconds": radius_seconds(book, at),
        "target_witnesses": witnesses,
    }


def warp_coordinate(u, r):
    """Convenience evaluation only; exact proof uses the analytic monotone map and its inverse."""
    import math

    if not math.isfinite(u) or not math.isfinite(r) or r < 0:
        raise ValueError("Finite coordinate and nonnegative slope required")
    if abs(u) >= 1 or u == 0 or r == 1:
        return u

    def slow(x, b):
        if abs(x) >= 1:
            return x
        # expm1 avoids cancellation near zero when b=0.
        return x * (b - (1 - b) * math.expm1(-(x**4) / (1 - x * x)))

    if r <= 1:
        return slow(u, r)
    lo, hi = -1.0, 1.0
    for _ in range(70):
        mid = (lo + hi) / 2
        if slow(mid, 1 / r) < u:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2
