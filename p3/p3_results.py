"""Read and display the scientific results of a completed P3 run."""

import csv
from fractions import Fraction
from pathlib import Path

from market import load


def run_summary(folder, receipt):
    return {
        "run": str(folder),
        "asof": receipt["asof"],
        "contracts": receipt["contracts"],
        "pointwise_models": receipt["pointwise_models"],
        "market_sources": receipt["market_sources"]["mode"],
        "euronext": receipt["euronext"],
        "report": str(folder / "pipeline.json"),
        "results": receipt["results"],
    }


def read_results(out, run):
    if run is None:
        latest = out / "latest.json"
        if not latest.is_file():
            raise FileNotFoundError(f"Aucun dernier run dans {out}. Utilisez --run avec le dossier du run.")
        run = out / load(latest)["run"]
    folder = run.resolve()
    receipt = load(folder / "pipeline.json")
    if "results" not in receipt:
        # Older receipts have only acquisition metadata. Use this run's own outputs.
        with (folder / "european_bounds.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            for index in ("min_witness", "max_witness"):
                row[index] = int(row[index])
        receipt["results"] = {
            "joint": load(folder / "joint.json"),
            "pointwise": load(folder / "pointwise" / "summary.json"),
            "european_bounds": rows,
        }
    return run_summary(folder, receipt)


def interval(pair):
    return f"[{pair[0]}, {pair[1]}]"


def format_results(summary):
    results = summary["results"]
    joint = results["joint"]
    rows = results["european_bounds"]
    report = results["pointwise"]
    point = report["point"]
    dupire = joint["dupire"]
    local_time = joint["expected_local_time_increment_continuous_models"]
    lines = [
        f"P3 | {report['product']} ({report['underlying']}) | {joint['asof']}",
        f"{joint['contracts']} contrats américains | Échéances du " + " et du ".join(joint["expiries"]),
        "",
        "Désaméricanisation conjointe",
        f"  {joint['common_witnesses']} témoins compatibles chacun avec les {joint['contracts']} fourchettes.",
        f"  La marge du témoin central atteint au moins {joint['central_minimum_slack_eur']} EUR/action.",
    ]
    if joint["full_core_simplex_certified"]:
        lines.append(f"  Toutes les combinaisons convexes des {joint['core_models']} témoins de base sont certifiées.")
    spread = joint["directions"].get("call_minus_put")
    if spread:
        call = next(row for row in rows if row["isin"] in spread["weights"] and row["kind"] == "call")
        lines.append(f"  Écart européen call - put (K = {call['strike']}, {call['expiry']})  "
                     f"{interval(spread['outer'])} EUR/action")
    lines.extend([
        "",
        f"Dupire en différences finies sur les gains actualisés (K = {dupire['center']}, pas = {dupire['spacing']})",
        f"  Dénominateur  {interval(dupire['denominator'])}",
    ])
    if dupire["status"] == "certified_finite_difference":
        lines.append(f"  Variance annualisée, bornes extérieures  {interval(dupire['outer'])}")
        lines.append(f"  Valeurs extrêmes atteintes par les témoins  {interval(dupire['attained_extrema'])}")
    else:
        lines.append("  Le signe du dénominateur reste indéterminé.")
    lines.append(f"  Espérance de l'accroissement du temps local en {local_time['strike']} "
                 f"(modèles continus)  {interval(local_time['outer'])}")

    coordinate = {"stock": "action", "gains": "gains actualisés"}[point["coordinate"]]
    exact_set = point["exact_nonnegative_volatility_set"].replace("+infinity)", "+infini[")
    sigmas = ", ".join(f"{100 * Fraction(w['volatility'])} %" for w in point["shared_price_witnesses"])
    lines.extend([
        "",
        f"Volatilité locale annualisée | {point['at_utc']} | {coordinate} = {point['level_eur']} EUR",
        f"  Ensemble exact avec changements de temps admissibles  {exact_set}",
        f"  Volatilités donnant les mêmes prix américains et européens  {sigmas}",
        "  Bornes extérieures avec le facteur spatial du certificat",
        f"    Vitesse de variance affine  {interval(point['affine_speed_volatility_pct_outer'])} %",
    ])
    lipschitz = point["lipschitz_speed_volatility_pct_outer"]
    limit = point["lipschitz_speed_limit_eur2_per_day2"]
    bound = "famille exclue par les contraintes" if lipschitz is None else interval(lipschitz) + " %"
    lines.append(f"    Vitesse lipschitzienne (L <= {limit} EUR²/jour²)  {bound}")
    names = {"reference": "de référence", "lower_example": "(exemple bas)", "upper_example": "(exemple haut)"}
    for key, stats in report["certified_models"].items():
        attained = point["affine_speed_attained_volatility_pct"][key]
        lines.append(f"  Modèle affine {names[key]}  {interval(attained)} %  |  "
                     f"{stats['contracts_certified']} contrats, marge >= {stats['minimum_margin_eur']} EUR/action")

    lines.extend([
        "",
        "Prix par action en EUR | Fourchettes américaines et bornes extérieures européennes",
        f"{'Échéance':10} {'Type':4} {'Strike':>6} {'Bid am.':>7} {'Ask am.':>7} "
        f"{'Borne inf.':>11} {'Euro témoin':>11} {'Borne sup.':>11}",
    ])
    for row in rows:
        lines.append(f"{row['expiry']:10} {row['kind']:4} {row['strike']:>6} "
                     f"{row['american_bid']:>7} {row['american_ask']:>7} "
                     f"{row['outer_lo']:>11} {row['central_euro']:>11} {row['outer_hi']:>11}")
    paris = summary["euronext"]
    folder = Path(summary["run"])
    lines.extend([
        "",
        f"Le contrôle Euronext Paris retient {paris['trades_retained']} transactions sur "
        f"{paris['series_with_trades']} séries.",
        f"Dossier du run  {folder}",
        "  european_bounds.csv            Prix et bornes par contrat",
        "  pointwise/american_prices.csv  Prix américains et marges par modèle et contrat",
    ])
    return "\n".join(lines)
