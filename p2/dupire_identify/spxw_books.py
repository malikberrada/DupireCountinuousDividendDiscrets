"""Shared book records and rational parity geometry from Dupire Identify 0.5.1."""
from dataclasses import dataclass
from fractions import Fraction as F
from .interval import I


@dataclass(frozen=True)
class Book:
    id: str
    strike: F
    bid: F
    ask: F


@dataclass(frozen=True)
class Pair:
    k: F                         # listed strike, in index points
    call: Book
    put: Book

    @property
    def strip(self):
        return self.call.bid-self.put.ask, self.call.ask-self.put.bid


def clip(poly, inequality):
    """Exact half-plane intersection, including points and line segments."""
    out = []
    for i, point in enumerate(poly):
        other = poly[i-1]
        u, v = inequality(other), inequality(point)
        if (u < 0 < v) or (v < 0 < u):
            f = u/(u-v)
            out.append(tuple(a+f*(b-a) for a,b in zip(other,point)))
        if v >= 0:
            out.append(point)
    return list(dict.fromkeys(out))


def parity(pairs, discount=None):
    """Vertices (D,A=DF) enclosing all feasible curves, no assumed rate band."""
    p, q = pairs[0], pairs[-1]
    width = q.k-p.k
    dl = max(max(v.put.bid/v.k for v in pairs),(p.strip[0]-q.strip[1])/width)
    dh = (p.strip[1]-q.strip[0])/width
    if discount:
        dl, dh = max(dl, F(discount[0])), min(dh,F(discount[1]))
    al, ah = max(v.call.bid for v in pairs), p.strip[1]+p.k*dh
    if dl > dh or al > ah:
        return []
    poly = list(dict.fromkeys([(dl,al),(dh,al),(dh,ah),(dl,ah)]))
    for pair in pairs:
        lo, hi = pair.strip
        poly = clip(poly,lambda x:x[1]-pair.k*x[0]-lo)
        poly = clip(poly,lambda x:hi-x[1]+pair.k*x[0])
        if not poly:
            break
    return poly


def span(poly, func):
    values = [func(d,a) for d,a in poly]
    return I(min(values),max(values))


def endpoints(interval):
    return [str(interval.lo),str(interval.hi)]
