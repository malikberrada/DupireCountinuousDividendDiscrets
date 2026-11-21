# Computational review

The default command checks the reference inputs in `checksums.json` before running either study. It reruns the pricing calculations and compares their outputs with the archived results. Numerically proposed probabilities, slopes, kernels and dual multipliers are inputs to independent arithmetic checks. Reoptimization is available separately and can produce different admissible witnesses. Commands below start at the repository root unless a change of directory is shown.

## P2 — continuous and grid prices

The TXO analysis uses one date, one weekly maturity and a common discount factor and forward. The original selection ledger covers 126 session–expiry combinations over 33 sessions. The review rechecks the ranking and target counts and binds the selected row to the market panel and witness. It reuses the recorded outcomes for the other 125 combinations. The original ranking objective concerns a separate gamma-weighted variance study. The P2 results reported here concern option prices in index points. [Selection ledger](../p2/data/selection/panels.csv)

The TAIFEX/TWSE replay reduces 318 regular-session quote rows to 95 eligible pairs, verifies their common call–put parity region and recovers the five strikes nearest the prespecified spot multiples. It checks the continuous witness on the selected ten contracts. The grid coefficients were fitted on a 1,024-step binomial tree. A finer tree has 16,384 steps and 16,385 terminal nodes. The proof checks both the fixed fitted coefficients and a family of slope perturbations with radius 1/16,384. For the ten selected contracts, the maximum fixed-model grid-to-continuous error rounds upward to 0.008077 index points. The corresponding family bound rounds upward to 6.177250 points. The model is evaluated on the other 180 contracts as an additional check, of which 106 lie in spread. Last bid/ask and the index close are treated as representative of the valuation date. Exchange reporting leaves their joint simultaneity unverified.

The synthetic examples treat normalized prices under cellwise lower and upper bands on continuous local variance. The verifier binds each certificate to its band definition, quotes and reported grid prices. It checks both extremal dynamics and the discretization and domain error budgets. The example with three contracts meets the 0.001 target on the three-month at-the-money and six-month out-of-the-money calls. The one-year at-the-money call remains inside its spread with a larger certified error. The one-contract skew example records the nodal proposals in a portable certificate. [Detailed derivation](../p2/METHOD.md)

## P3 — European prices consistent with American books

For model `m`, let `A_i(m)` be the American value with optimal exercise and `E_i(m)` the corresponding European value. Every coordinate of a European vector must use the same model. The verifier constructs an inner set of jointly attainable vectors and an outer set containing every compatible vector under the stated model and market conventions. A point belonging only to the outer set can have unresolved feasibility.

The 20 American options are standard TotalEnergies TOTB contracts, in EUR per share, with strikes 74, 76, 78, 80 and 82 and expiries December 18, 2026 and January 15, 2027. The cutoff is November 20, 2026 at 12:00:50 UTC. The model uses the Xetra spot spread, deterministic €STR-based discounting, a gross cash dividend of EUR 0.90 with ex-date December 31, 2026 and payment January 5, 2027, and the stated exercise and settlement calendars. It treats the selected books as representative at the cutoff.

The first witness computation replays 47 rational martingale laws with optimal exercise. A common admissible exercise policy per contract certifies all convex combinations of the first three European vectors. The verifier also checks a nonzero two-by-two minor of their difference vectors, proving the triangle has affine dimension two. The portfolio call minus put, strike 78, January maturity, provides a sharp direction. The exact outer endpoints coincide with two witness values before display rounding. This one-direction result leaves the full twenty-dimensional inverse set enclosed.

A separate one-factor diffusion computation checks 60 American price enclosures across three models. The pointwise comparison uses the stock at EUR 78, December 18, 2026 at 19:00 UTC. Admissible smooth clock changes give identical American and European model prices with point volatility anywhere in the nonnegative half-line. The affine-speed and Lipschitz intervals require the specified spatial factor and restrictions on the variance speed. The finite-difference quotient instead acts on discounted gains, with strike 78 and strike increment 4. [Joint method](../p3/METHOD.md) · [Pointwise model and proof](../p3/POINTWISE.md)

## Audit files

Paths in the table are relative to the new directory printed by `reproduce.py`.

| Question | Output |
|---|---|
| Did both studies finish, and which data were used? | `verification.json`, `p2/summary.json`, `p3/summary.json` |
| Can I see the exact TXO errors and the full-panel check? | `p2/result.json`, `p2/contracts.csv`, `p2/comparison_95.json` |
| Which two witnesses attain the sharp P3 call-minus-put bounds? | `p3/geometry.json` lists zero-based witness indices, rational endpoints and portfolio weights. The laws are in the repository at `p3/certified/certificate.json`. |
| How do I find European prices, margins and their source inputs? | `p3/study/latest.json` names the run. Inside it, read `pipeline.json`, `european_bounds.csv`, `pointwise/american_prices.csv` and `pointwise/summary.json`. |
| How do stock and discounted-gains coordinates differ? | The stock result is in `p3/summary.json` and the corresponding gains result is in `p3/gains.json`. |

The reference values and exact rational endpoints are deterministic. The run identifier, execution time, Python version and source origins describe the local execution.

## Individual commands

To replay all 95 Taiwanese pairs directly against the included responses, use the command below. Replacing the two local file options by `--official` downloads both source responses.

```console
python p2/p2_txo.py verify --all-pairs --options p2/data/txo/sources/taifex.csv --index p2/data/txo/sources/twse.json
```

To recompute the Taiwanese numerical proposal with the pinned NumPy/SciPy versions and certify the resulting fit, use separate output files. The native market command accepts a custom fit. The combined review uses the archived fit.

```console
python p2/grid_fit.py --out runs/refit/grid_fit.json
python p2/p2_txo.py run --fit runs/refit/grid_fit.json --result runs/refit/txo.json
python p2/p2_txo.py verify --fit runs/refit/grid_fit.json --result runs/refit/txo.json
```

To regenerate and verify the synthetic skew certificate with SciPy, run these commands **from the `p2/` directory**.

```console
python -m dupire_identify.p2_cert certify --bands data/synthetic/skew.json --quotes data/synthetic/skew_quotes.csv --prices data/synthetic/skew_grid.csv --left 1/4 --right 2 --cells 256 --steps 80 --out ../runs/skew.json
python -m dupire_identify.p2_cert verify --report ../runs/skew.json --bands data/synthetic/skew.json --quotes data/synthetic/skew_quotes.csv --prices data/synthetic/skew_grid.csv
```

From the repository root, the native P3 command independently checks the joint proof and CSV, and the pipeline replays the market data and displays the results. The third command reads the existing completed run. The optional fourth command checks the dividend text on page 53 against the provider PDF using the original cache and Poppler or pypdf. The P3 guide gives the additional witness fitting and portfolio commands. [P3 commands](../p3/README.md)

```console
python p3/p3_eurex.py verify
python p3/p3_eurex.py pipeline --offline --out runs/p3
python p3/p3_eurex.py results --out runs/p3 --format text
python p3/p3_eurex.py verify --official-dividend --cache .cache/p3
```

The complete regression suites use the optional packages. Run the following commands from the repository root.

```console
cd p2
python -m unittest discover -s tests -p "test_*.py"
cd ../p3
python -m unittest discover -s . -p "test_*.py"
```

P2 and P3 each have a scope-specific entry point. The shared P2 package contains the arithmetic, witness and uniform-grid components needed by these experiments. The Windows and Linux jobs in GitHub Actions run the same archived-input review and tests.
