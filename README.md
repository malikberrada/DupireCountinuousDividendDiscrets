# DupireCountinuousDividendDiscrets

Computational materials for verifying two results on local volatility and option prices. **P2** controls the error between numerical prices and continuous-model prices using European options on the TAIEX. **P3** bounds the joint set of European prices compatible with American options on TotalEnergies under a declared cash dividend.

## Reproduce the results

Extract the source or clone the repository, open a terminal in the directory containing `reproduce.py`, and run the following command with CPython 3.12.

```console
python reproduce.py
```

The command uses the archived exchange inputs and the Python standard library. It checks their SHA-256 digests, reconstructs both market panels, replays the pricing proofs and compares the resulting tables with their archived values. The printed directory contains a machine-readable `verification.json` and the complete numerical results. A failed comparison exits with a nonzero status. Each successful run gets its own directory under `runs/`.

NumPy speeds up P3. The pinned packages also support the regression tests, numerical refits and issuer PDF text check.

```console
python -m pip install -r requirements-review.txt
```

## Reacquire the market data

```console
python reproduce.py --download --require-originals --cache .cache/p3
```

With an empty cache, this requests the TAIFEX and TWSE responses and all 28 European originals. P3 reuses cache entries after checking their digests. The Deutsche Börse minute feeds and Euronext's previous-session endpoint have limited retention. When an original has expired, `--require-originals` reports the missing source. To reproduce the dated inputs from the committed evidence, use the first command above. To use the available online sources with the documented fallback for expired feeds, run `python reproduce.py --download`. Each acquisition is identified in the output. [Data sources and terms](DATA.md)

## Results to check

| Study | Quantity | Reference result |
|---|---|---|
| P2 synthetic | Uniform price enclosure on the three-call example | All three lie inside their spreads. Two meet the normalized error target of 0.001. The additional skew example puts the continuous call between 0.0659797 and 0.0990641. |
| P2 TXO, October 7, 2026 | Discretization error for the fitted model on 10 selected contracts | The model fits on a 1,024-step tree. The 16,384-step tree has a certified maximum error below **0.008077 index points**. |
| P2 TXO, same expiry | Pricing all 95 eligible call–put pairs | A common parity region exists for all 95 pairs. The fitted continuous model lies inside **116 of 190** spreads, including the 10 selected contracts. |
| P3 Eurex, November 20, 2026 | Joint de-Americanization of the 20 TOTB options | **47 common witnesses**. Convex combinations of three witnesses give a two-dimensional feasible triangle. At strike EUR 78 in January 2027 the sharp European call-minus-put endpoints lie in the outward-rounded interval **[−0.15245998, −0.09246403] EUR/share**. |
| P3, discounted gains | Annualized finite-difference variance at strike 78, strike step 4 | Outer bounds **[0.01315423, 0.07774606]**. Witness values span **[0.02465868, 0.06835897]** after rounding. |
| P3, stock at EUR 78 on December 18, 2026 at 19:00 UTC | Pointwise annualized stock volatility | Every finite nonnegative volatility is compatible in the stated class of time changes. With the specified spatial factor and affine variance speed the outer bounds are **23.136334% to 25.617386%**. The affine reference model gives **25.02710%** after rounding. |

P2 selects one session and expiry retrospectively. The 10 fitted contracts and the 180 other contracts are tracked separately. P3 uses Eurex bid–ask prices for calibration and Xetra for the underlying. Its Euronext check matches eight earlier trades across six Paris series. The exercise and settlement calculations place the EUR 0.90 dividend detachment between the two maturities. [Reviewer guide, assumptions and output files](docs/REVIEW.md)

## Repository layout

| Path | Contents |
|---|---|
| `p2/` | Portable uniform-pricing proofs, TXO model, lattice, full-panel comparison, synthetic examples, tests and retrospective selection ledger |
| `p3/` | Market reconstruction, American exercise and dividend conventions, joint and pointwise verifiers, certificates, tests and source notices |
| `checksums.json` | SHA-256 hashes of the distributed scientific inputs and references |
| `.github/workflows/reproduce.yml` | Archived-data review and regression suites on Windows and Linux |

The code is distributed under the MIT license. Market data, issuer materials and the bundled third-party software carry their respective notices. [Code license](LICENSE) · [Data and third-party notices](DATA.md)
