"""Uniform optimal-stop perturbation bound for a declared single cash distribution."""

from datetime import date
from fractions import Fraction as F

from certify import decimal_out
from model import evaluate


def sensitivity(m, w, amount_lo, amount_hi, ex_lo=None, ex_hi=None, pay_lo=None, pay_hi=None):
    if len(m.divs) != 1:
        raise ValueError("Sensitivity expects one dividend in this horizon")
    ex, pay, amount = m.divs[0]

    def dt(arg, default):
        return date.fromisoformat(arg) if arg else default

    dl, du = dt(ex_lo, ex), dt(ex_hi, ex)
    pl, pu = dt(pay_lo, pay), dt(pay_hi, pay)
    low, high = F(amount_lo), F(amount_hi)
    if not (0 <= low <= high and m.today < dl <= du <= pl <= pu):
        raise ValueError("Inconsistent dividend range")
    pmin, pmax = sorted((m.disc(pl), m.disc(pu)))
    reserve_low, reserve_high = low * pmin, high * pmax
    minimum_state = min(
        [
            F(w["z"]),
            *(F(x) for x in w["states"]),
            *(F(y) for row in w["states"].values() for y in row["next"]),
        ]
    )
    if minimum_state < reserve_high:
        raise ValueError("The same paths cannot cover the largest dividend reserve")
    prices, _ = evaluate(m, w)
    rows = []
    for c in m.contracts:
        T = m.expiries[c["m"]]

        def delta(d):
            old = amount * m.disc(pay) if d >= ex else F(0)
            lower = reserve_low if d >= du else F(0)
            upper = reserve_high if d >= dl else F(0)
            return max(abs(old - lower), abs(upper - old)) / m.prem

        budget = max(delta(d) for d in m.trading_dates if d <= T)
        _, _, slack = prices[c["id"]]
        rows.append(
            dict(
                isin=c["id"],
                optimal_stop_error_upper=decimal_out(budget, 1),
                european_error_upper=decimal_out(delta(T), 1),
                slack_after_lower=decimal_out(slack - budget, -1),
                robust=slack >= budget,
            )
        )
    return dict(
        contracts=len(rows),
        jointly_robust=all(r["robust"] for r in rows),
        robust_contracts=sum(r["robust"] for r in rows),
        amount=[str(low), str(high)],
        ex_dates=[dl.isoformat(), du.isoformat()],
        pay_dates=[pl.isoformat(), pu.isoformat()],
        minimum_remaining_slack_lower=min((r["slack_after_lower"] for r in rows), key=F),
        per_contract=rows,
    )
