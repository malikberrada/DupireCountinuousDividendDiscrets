"""Passage from a joint finite-difference certificate to a point with supplied derivative bounds."""

from fractions import Fraction as F

from certify import decimal_out
from outer import add, dual_bound, read_interval, scale

from pointwise.gaussian import sqrt_hi, sqrt_lo


def percentages(var_lo, var_hi):
    return [decimal_out(100 * sqrt_lo(var_lo), -1, 6), decimal_out(100 * sqrt_hi(var_hi), 1, 6)]


def dupire_at_stencil(p, cert, time_curvature, strike_fourth):
    """Bounds on |C_TT| (year scale) at k and |C_KKKK| (EUR scale) at the first expiry."""
    lt, lk = F(time_curvature), F(strike_fourth)
    if min(lt, lk) < 0:
        raise ValueError("Derivative bounds must be nonnegative")
    dt = p.m.yeargap
    temporal = lt * dt
    spatial = lk * p.k**2 * p.h**2 / 12
    dmin = read_interval(p, p.den, cert["denominator_proof"])[0]
    floor = dmin - spatial
    report = {
        "coordinate": "discounted_total_gains",
        "level": str(p.k),
        "maturity": str(p.m.expiries[0]),
        "expiry_cutoff_utc": "19:00:00",
        "time_unit": "ACT/365F years",
        "assumed_max_abs_C_TT": str(lt),
        "assumed_max_abs_C_KKKK": str(lk),
        "numerator_bias_eur_per_year": decimal_out(temporal, 1),
        "denominator_bias_eur": decimal_out(spatial, 1),
        "point_denominator_lower_eur": decimal_out(floor, -1),
        "strict_strike_fourth_ceiling_for_positive_floor": str(12 * dmin / (p.k**2 * p.h**2)),
        "regularity_source": "user_supplied",
    }
    if floor <= 0:
        return dict(report, status="unresolved_positive_density", volatility_pct_outer=None)
    bounds = []
    for sign in (-1, 1):
        evidence = cert["ratio_proofs"][str(sign)]
        alpha = F(evidence["alpha"])
        residual = dual_bound(p, add(scale(p.num, sign), scale(p.den, -alpha)), evidence["dual"])
        upper = alpha + max(F(0), residual + temporal + abs(alpha) * spatial) / floor
        bounds.append(upper if sign > 0 else max(F(0), -upper))
    if bounds[1] < bounds[0]:
        return dict(report, status="incompatible_assumptions", volatility_pct_outer=None)
    return dict(
        report,
        status="conditional_on_both_derivative_bounds",
        volatility_pct_outer=percentages(*bounds),
    )
