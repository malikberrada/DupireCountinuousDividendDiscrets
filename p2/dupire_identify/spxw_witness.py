"""Verified continuous terminal-quantile pricing from Dupire Identify 0.5.1."""
from fractions import Fraction as F
from functools import lru_cache
from .interval import I, black_call, exp_point, log_point, normal_cdf
from .spxw_books import endpoints


def intercepts(knots, slopes):
    """Enforce h(0)=0 and continuity at every knot (0 is a knot)."""
    constants = [0]
    for i,x in enumerate(knots):
        constants.append(constants[-1]+(slopes[i]-slopes[i+1])*x)
    offset = constants[list(knots).index(0)]
    return [b-offset for b in constants]


@lru_cache(maxsize=8192)
def _phi_point(x):
    return normal_cdf(I(x))


def phi(x):
    return I(_phi_point(x.lo).lo, _phi_point(x.hi).hi)


def at(bound, shift=0):
    return I(0 if bound == '-inf' else 1) if isinstance(bound,str) else phi(bound-shift)


def price_quantile(model, pairs, t, amin, amax):
    if model['kind'] != 'gaussian_terminal_loglinear':
        raise ValueError('Unknown diffusion witness')
    knots = tuple(map(F,model['knots']))
    slopes = tuple(map(F,model['slopes']))
    med, d = F(model['median_spot']), F(model['discount'])
    if (len(slopes) != len(knots)+1 or list(knots) != sorted(set(knots)) or 0 not in knots
            or med <= 0 or d <= 0 or any(s <= 0 or not amin*t <= s*s <= amax*t for s in slopes)):
        raise ValueError('Invalid diffusion coefficients, rates, or knots')
    constants = intercepts(knots,slopes)
    breaks = ['-inf',*map(I,knots),'+inf']
    pieces = []
    for i,(s,b) in enumerate(zip(slopes,constants)):
        l,r = breaks[i:i+2]
        weight = med*exp_point(b+s*s/2)
        pieces.append((l,r,s,b,weight,at(l,s),at(r,s),at(l),at(r)))
    forward = sum((weight*(pr-pl) for _,_,_,_,weight,pl,pr,_,_ in pieces), I(0))
    rows = []
    for p in pairs:
        log_k = log_point(p.k/med)
        call = I(0)
        for l,r,s,b,weight,pl,pr,ql,qr in pieces:
            threshold = (log_k-b)/s
            if r != '+inf' and threshold.lo >= r.hi:
                continue
            if l != '-inf' and threshold.hi <= l.lo:
                gm, prob = pr-pl, qr-ql
            else:
                low,high = threshold.lo,threshold.hi
                if l != '-inf':
                    low,high=max(low,l.lo),max(high,l.hi)
                if r != '+inf':
                    low,high=min(low,r.lo),min(high,r.hi)
                cut = I(low,high).rounded(80)
                gm, prob = pr-phi(cut-s), qr-phi(cut)
            call += weight*gm-p.k*prob
        call = (d*call).rounded()
        put = (call+d*(p.k-forward)).rounded()
        rows.extend([(p.call,call),(p.put,put)])
    return d,forward,rows


def verify_model(model,pairs,t,amin,amax,discount=None):
    if model['kind'] == 'constant_variance':
        d, fwd, a = (F(model[k]) for k in ('discount','forward','variance'))
        if min(d,fwd) <= 0 or not amin <= a <= amax:
            raise ValueError('Invalid constant-variance witness')
        fw = I(fwd)
        rows = []
        for p in pairs:
            call = d*fwd*black_call(p.k/fwd,a*t)
            rows.extend([(p.call,call),(p.put,call+d*(p.k-fwd))])
    else:
        d,fw,rows = price_quantile(model,pairs,t,amin,amax)
    if discount and not F(discount[0]) <= d <= F(discount[1]):
        raise ValueError('Witness outside explicit discount bounds')
    proof = []
    for book,value in rows:
        if value.lo < book.bid or value.hi > book.ask:
            raise ValueError(f'Witness outside raw bid/ask for {book.id}')
        proof.append(dict(id=book.id,bid=str(book.bid),ask=str(book.ask),price=endpoints(value),
                          slack_lower=str(min(value.lo-book.bid,book.ask-value.hi))))
    return dict(verified=True,discount=str(d),forward=endpoints(fw),prepaid_forward=endpoints(d*fw),
                checked_contracts=len(proof),minimum_slack_points=str(min(F(row['slack_lower']) for row in proof)),
                raw_prices=proof)
