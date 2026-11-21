"""Build or independently replay the TotalEnergies point-volatility certificate."""

import csv
import os
from fractions import Fraction as F
from pathlib import Path
from tempfile import TemporaryDirectory

from certify import decimal_out, digest
from certify import verify as verify_p3
from market import ROOT, check_files, load, save

from pointwise.calendar_model import CalendarModel, instant
from pointwise.conditional import check_ranges, lipschitz_at, propose, variance_at
from pointwise.gaussian import propose_kernel
from pointwise.identified import point
from pointwise.pricer import certify_prices
from pointwise.regularity import dupire_at_stencil, percentages

PUBLISHED = ROOT / "certified_pointwise"
BASELINE = ROOT / "certified/certificate.json"
DEFAULT_AT = "2026-12-18T19:00:00Z"
MODELS = ("reference", "lower_example", "upper_example")
DEFAULT_SIGMAS = ("0", "0.15", "0.45")


class SpreadNotCertified(ValueError):
    """The price enclosure meets a bid or ask, so a finer mesh may decide feasibility."""


def market_inputs():
    panel = check_files()
    original = load(BASELINE)
    _, _, poly = verify_p3(panel, original)
    return panel, original, poly


def assemble(inputs, parameters, fit_at, step):
    panel, original, poly = inputs
    if F(step) not in (F(1, 16), F(1, 32), F(1, 64)):
        raise ValueError("The supported meshes are 1/16, 1/32 and 1/64 EUR")
    models = {}
    for name in MODELS:
        pars = parameters[name]
        book = CalendarModel(panel, pars)
        models[name] = {
            "parameters": pars,
            "kernels": [propose_kernel(v, F(step)) for v in book.variances],
        }
    outer = propose(CalendarModel(panel, parameters["reference"]), poly, original)
    return {
        "schema": "p3-point-volatility/1",
        "panel_sha256": digest(panel),
        "p3_proof_sha256": digest(original),
        "fit_at": fit_at.isoformat(),
        "mesh_eur": str(step),
        "models": models,
        "operational_variance_proof": outer,
    }


def describe_point(books, boxes, at, level, coordinate, sigmas, slope):
    base = books["reference"]
    ref = point(base, at, level, coordinate, sigmas)
    outer = variance_at(base, at, level, coordinate, boxes)
    lipschitz = lipschitz_at(base, at, level, coordinate, boxes, slope)
    attained = {}
    for name, book in books.items():
        var = point(book, at, level, coordinate, ())["base_variance"]
        if not outer[0] <= var <= outer[1]:
            raise ValueError("Conditional outer excludes a compatible affine clock")
        if abs(book.b) <= slope and (lipschitz is None or not lipschitz[0] <= var <= lipschitz[1]):
            raise ValueError("Lipschitz outer excludes a compatible clock")
        attained[name] = percentages(var, var)
    return {
        "at_utc": at.isoformat().replace("+00:00", "Z"),
        "coordinate": coordinate,
        "level_eur": str(level),
        "discounted_gains_state_eur": str(ref["k"]),
        "relative_volatility_denominator_eur": str(ref["denominator"]),
        "exact_nonnegative_volatility_set": "[0, +infinity)",
        "strictly_positive_at_target_set": "(0, +infinity)",
        "shared_price_witnesses": ref["target_witnesses"],
        "warp_half_window_seconds": str(ref["warp_radius_seconds"]),
        "affine_speed_volatility_pct_outer": percentages(*outer),
        "affine_speed_attained_volatility_pct": attained,
        "lipschitz_speed_limit_eur2_per_day2": str(slope),
        "lipschitz_speed_volatility_pct_outer": None
        if lipschitz is None
        else percentages(*lipschitz),
    }


def replay(
    inputs,
    certificate,
    at=None,
    level="78",
    coordinate="gains",
    sigmas=DEFAULT_SIGMAS,
    slope="0.02",
    backend="auto",
):
    panel, original, poly = inputs
    if (
        certificate["schema"] != "p3-point-volatility/1"
        or certificate["panel_sha256"] != digest(panel)
        or certificate["p3_proof_sha256"] != digest(original)
    ):
        raise ValueError("Different point certificate, market panel or P3 evidence")
    if set(certificate["models"]) != set(MODELS):
        raise ValueError("The three calibration witnesses are required")
    step = F(certificate["mesh_eur"])
    fit_at = instant(certificate["fit_at"])
    at = instant(at) if at else fit_at
    level = F(level)
    slope = F(slope)
    lookup = {c["isin"]: c for c in panel["contracts"]}
    records = []
    stats = {}
    books = {}
    for name in MODELS:
        entry = certificate["models"][name]
        book = CalendarModel(panel, entry["parameters"])
        books[name] = book
        if (book.floor, book.flat_from) != (1, 12):
            raise ValueError("The stated family uses its specified smooth state factor")
        rows = certify_prices(book, step, entry["kernels"], backend)
        tightest = min(rows, key=lambda r: r["margin"])
        if tightest["margin"] <= 0:
            raise SpreadNotCertified(
                name + " lacks a strict certified margin for " + tightest["isin"]
            )
        stats[name] = {
            "contracts_certified": len(rows),
            "minimum_margin_eur": decimal_out(tightest["margin"], -1),
            "binding_isin": tightest["isin"],
            "variance_intercept_eur2_per_day": str(book.a),
            "variance_slope_eur2_per_day2": str(book.b),
            "prepaid_spot_eur": str(book.z),
        }
        for row in rows:
            q = lookup[row["isin"]]
            records.append(
                {
                    "model": name,
                    "isin": row["isin"],
                    "expiry": q["expiry"],
                    "kind": q["kind"],
                    "strike": q["strike"],
                    "american_bid": q["bid"],
                    "american_ask": q["ask"],
                    "american_lower_eur": decimal_out(row["lower"], -1),
                    "american_upper_eur": decimal_out(row["upper"], 1),
                    "minimum_margin_eur": decimal_out(row["margin"], -1),
                    "gaussian_budget_eur": decimal_out(row["gaussian_budget"], 1),
                    "state_localization_budget_eur": decimal_out(row["localization_budget"], 1),
                    "rounding_budget_eur": decimal_out(row["rounding_budget"], 1),
                }
            )
    directional = [
        point(books[n], fit_at, "78", "gains", ())["base_variance"]
        for n in ("lower_example", "reference", "upper_example")
    ]
    if not directional[0] < directional[1] < directional[2]:
        raise ValueError("Directional examples do not improve the fitted reference at its target")
    base = books["reference"]
    boxes = check_ranges(base, poly, original, certificate["operational_variance_proof"])
    result = describe_point(books, boxes, at, level, coordinate, sigmas, slope)
    return {
        "asof": panel["asof"],
        "product": panel["product"],
        "underlying": panel["underlying"],
        "exercise_cutoffs": len(base.dates),
        "minimum_exercise_date": str(base.dates[0]),
        "maximum_exercise_date": str(base.dates[-1]),
        "certified_models": stats,
        "mesh_eur": str(step),
        "point": result,
    }, records


def export(folder, certificate, report, records):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=folder) as tmp:
        stage = Path(tmp)
        save(stage / "certificate.json", certificate)
        save(stage / "summary.json", report)
        with open(stage / "american_prices.csv", "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
        for filename in ("american_prices.csv", "summary.json", "certificate.json"):
            os.replace(stage / filename, folder / filename)


def add_commands(sub):
    point_cli = sub.add_parser("pointwise", help="replay point volatility; --download includes acquisition")
    replay_options(point_cli)
    point_cli.add_argument("--download", action="store_true", help="run the complete acquisition pipeline")
    point_cli.add_argument("--cache", type=Path, default=Path("p3_cache"))
    point_cli.add_argument("--out", type=Path, default=Path("runs/p3"))
    point_cli.add_argument("--require-originals", action="store_true", help="require independent originals with --download")
    pipe = sub.add_parser("pipeline", help="download, reconstruct and verify the dated P3 study")
    replay_options(pipe)
    pipe.set_defaults(coordinate="stock")
    pipe.add_argument("--cache", type=Path, default=Path("p3_cache"))
    pipe.add_argument("--out", type=Path, default=Path("runs/p3"))
    pipe.add_argument("--offline", action="store_true", help="read cached originals or dated bundled evidence")
    pipe.add_argument("--require-originals", action="store_true", help="require originals from the providers or cache")
    results = sub.add_parser("results", help="afficher les résultats d'un run P3 déjà terminé")
    location = results.add_mutually_exclusive_group()
    location.add_argument("--out", type=Path, default=Path("runs/p3"), help="dossier contenant latest.json")
    location.add_argument("--run", type=Path, help="dossier du run à afficher")
    for command in (pipe, results):
        command.add_argument("--format", choices=("text", "json"),
                             help="format de sortie (texte en console, JSON si la sortie est redirigée)")
    fit_cli = sub.add_parser(
        "pointwise-fit", help="optimize and certify three scalar diffusion witnesses"
    )
    fit_cli.add_argument("--out", type=Path, required=True)
    fit_cli.add_argument("--at", default=DEFAULT_AT)
    fit_cli.add_argument("--mesh", choices=("1/16", "1/32", "1/64"), default="1/32")
    fit_cli.add_argument("--download", action="store_true", help="acquire and audit the market inputs before fitting")
    fit_cli.add_argument("--cache", type=Path, default=Path("p3_cache"))
    fit_cli.add_argument("--require-originals", action="store_true", help="require independent originals with --download")
    general = sub.add_parser(
        "pointwise-dupire",
        help="conditional point interval for general diffusions from call smoothness bounds",
    )
    general.add_argument(
        "--time-curvature", required=True, help="upper bound on |C_TT| in EUR/year^2"
    )
    general.add_argument("--strike-fourth", required=True, help="upper bound on |C_KKKK| in EUR^-3")


def replay_options(point_cli):
    point_cli.add_argument("--certificate", type=Path, default=PUBLISHED / "certificate.json")
    point_cli.add_argument(
        "--at", help="ISO timestamp with timezone; defaults to the fitting target"
    )
    point_cli.add_argument("--level", default="78", help="target level in EUR")
    point_cli.add_argument("--coordinate", choices=("gains", "stock"), default="gains")
    point_cli.add_argument(
        "--sigma", action="append", help="target annualized volatility as a fraction, e.g. 0.15"
    )
    point_cli.add_argument(
        "--slope-limit",
        default="0.02",
        help="extra Lipschitz assumption on the variance speed, EUR^2/day^2",
    )
    point_cli.add_argument("--backend", choices=("auto", "python", "numpy"), default="auto")


def run(args, inputs=None):
    if inputs is None:
        inputs = market_inputs()
    if args.action == "pointwise-dupire":
        return dupire_at_stencil(inputs[2], inputs[1], args.time_curvature, args.strike_fourth)
    if args.action == "pointwise-fit":
        from pointwise.fit_clock import optimize

        at = instant(args.at)
        pars = optimize(inputs[0], at)
        for mesh in (F(1, 16), F(1, 32), F(1, 64)):
            if mesh > F(args.mesh):
                continue
            certificate = assemble(inputs, pars, at, mesh)
            try:
                report, records = replay(inputs, certificate)
            except SpreadNotCertified:
                if mesh == F(1, 64):
                    raise
                continue
            export(args.out, certificate, report, records)
            return report
        raise ValueError("Unsupported mesh")
    return replay_requested(inputs, args)[0]


def replay_requested(inputs, args, certificate=None):
    if certificate is None:
        certificate = load(args.certificate)
    report, records = replay(
        inputs,
        certificate,
        args.at,
        args.level,
        args.coordinate,
        args.sigma or DEFAULT_SIGMAS,
        args.slope_limit,
        args.backend,
    )
    if args.certificate.resolve() == (PUBLISHED / "certificate.json").resolve():
        with open(PUBLISHED / "american_prices.csv", newline="", encoding="utf-8") as stream:
            if list(csv.DictReader(stream)) != records:
                raise ValueError("Distributed American price enclosures differ")
        if (
            not args.at
            and F(args.level) == 78
            and args.coordinate == "gains"
            and not args.sigma
            and F(args.slope_limit) == F("0.02")
        ) and load(PUBLISHED / "summary.json") != report:
            raise ValueError("Distributed point summary differs")
    return report, records
