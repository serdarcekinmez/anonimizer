"""Command line interface. Thin layer over ``anonimizer.pipeline``.

Messages never contain cell contents. Unexpected errors are reported by type and location
only, because exception texts can quote data; set ANONIMIZER_DEBUG=1 to see a full traceback.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

from . import NON_CERTIFICATION_STATEMENT, __version__
from .contract import ContractError, build_contract, dumps
from .export import ExportRefused, check_new_file, write_new_file
from .grid import GridError
from .policy import POLICIES, PolicyError, get_policy
from .recipe import ParseRecipe, RecipeError
from .synth import SynthError

EXIT_OK, EXIT_INPUT, EXIT_COVERAGE, EXIT_REFUSED, EXIT_INTERNAL = 0, 2, 3, 4, 70


def _recipe(args) -> ParseRecipe:
    r = ParseRecipe.load(args.recipe) if getattr(args, "recipe", None) else ParseRecipe()
    if getattr(args, "delimiter", None):
        r.delimiter = {"tab": "\t", "\\t": "\t"}.get(args.delimiter, args.delimiter)
    if getattr(args, "encoding", None):
        r.encoding = args.encoding
    for m in getattr(args, "marker", None) or []:
        r.extra_markers.append(m)
    return r


def _not_the_source(output: str, source: str) -> None:
    """A single output file named by the user may replace an earlier output, never the input file."""
    if os.path.exists(output) and os.path.exists(source) and os.path.samefile(output, source):
        raise ExportRefused("the output file would replace the input file")


def _split_ref(ref: str, tables: list[str]) -> tuple[str, str]:
    for t in sorted(tables, key=len, reverse=True):
        if ref.startswith(t + "."):
            return t, ref[len(t) + 1:]
    if len(tables) == 1:
        return tables[0], ref
    raise ContractError("column references must be written as TABLE.COLUMN; tables: " + ", ".join(tables))


def _print_regions(recipe: dict) -> None:
    print(f"{'name':<22} {'kind':<6} {'sheet':<16} {'header':>6} {'data rows':>15} {'columns':>9} {'conf':>5}  notes")
    for t in recipe["tables"]:
        rows = f"{t['first_data_row']}-{t['last_data_row']}"
        cols = f"{t['first_col']}-{t['last_col']}"
        print(f"{t['name']:<22} {t['kind']:<6} {str(t['sheet']):<16} {str(t['header_row'] or '-'):>6} {rows:>15} "
              f"{cols:>9} {t['confidence']:>5}  {'; '.join(t['notes'])}")


def cmd_inspect(args) -> int:
    from .pipeline import inspect

    if args.recipe_out:
        _not_the_source(args.recipe_out, args.file)
    res = inspect(args.file, _recipe(args))
    f = res["file"]
    if f["format"] == "csv":
        print(f"CSV  encoding={f['encoding']['encoding']} (confidence {f['encoding']['confidence']})  "
              f"delimiter={f['delimiter']['delimiter']!r} (confidence {f['delimiter']['confidence']})  "
              f"records={f.get('records')}")
    else:
        print(f"XLSX  sheets={f['sheet_count']}  hidden sheets={f['hidden_sheets']}")
    _print_regions(res["recipe"])
    if args.recipe_out:
        with open(args.recipe_out, "w", encoding="utf-8") as fh:
            json.dump(res["recipe"], fh, indent=2, ensure_ascii=False)
        print(f"\nRecipe written to {args.recipe_out}. Edit table boundaries there (rows and columns are 1-based) "
              f"and pass it back with --recipe.")
    return EXIT_OK


def _print_catalogue(report: dict) -> None:
    for t in report["tables"]:
        print(f"\nTable {t['name']}: {t['rows']} rows x {t['columns']} columns "
              f"(detection confidence {t['detection_confidence']})")
        for c in t["column_summaries"]:
            print(f"  {c['name'][:28]:<28} {c['logical_type']:<11} missing={c['missing']:<8} distinct={c['distinct']:<8} "
                  f"key={c['key_role']:<9} sensitivity hint={c['sensitivity_hint']}")
    print("\nException Catalogue")
    if not report["exception_catalogue"]:
        print("  (nothing exceptional found)")
    for e in report["exception_catalogue"]:
        where = f"{e['table'] or 'file'}.{e['column']}" if e["column"] else (e["table"] or "file")
        print(f"  P{e['priority']} {where[:38]:<38} {e['description'][:70]:<70} x{e['count']}")
    for a in report["unresolved_ambiguities"]:
        print(f"  ? {a['scope']}: {a['message']} (confidence {a['confidence']})")


def cmd_profile(args) -> int:
    from .pipeline import PRIVATE_PROFILE_NAME, profile_source
    from .reports import summarize_profile

    policy = get_policy(args.policy)
    report_path = os.path.join(args.out, "source_report.json") if args.out else None
    private_path = os.path.join(args.private_dir, PRIVATE_PROFILE_NAME) if args.private_dir else None
    for path in (report_path, private_path):
        if path:
            check_new_file(path, (args.file,))
    private, shareable = profile_source(args.file, _recipe(args), policy)
    report = summarize_profile(shareable, "source")
    _print_catalogue(report)
    if report_path:
        write_new_file(report_path, (json.dumps(report, indent=2, ensure_ascii=False)).encode("utf-8"))
        print(f"\nShareable source report written to {report_path}")
    if private_path:
        write_new_file(private_path, json.dumps(private, indent=2, ensure_ascii=False).encode("utf-8"))
        print(f"PRIVATE diagnostic profile (source row numbers, category values) written to {private_path}. "
              f"Do not share it.")
    return EXIT_OK


def cmd_contract(args) -> int:
    from .pipeline import profile_source

    _not_the_source(args.output, args.file)
    policy = get_policy(args.policy)
    _private, shareable = profile_source(args.file, _recipe(args), policy)
    contract = build_contract(shareable, policy)
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(dumps(contract) + "\n")
    n_cols = sum(len(t["columns"]) for t in contract["tables"])
    n_sc = sum(len(t["scenarios"]) for t in contract["tables"])
    print(f"Proposed Dataset Contract written to {args.output}: {len(contract['tables'])} table(s), {n_cols} column(s), "
          f"{n_sc} scenario(s). Review keep, sensitivity and key roles, then pass it with --contract.")
    return EXIT_OK


def cmd_generate(args) -> int:
    from .pipeline import CoverageError, run

    policy = get_policy(args.policy)
    recipe = _recipe(args)
    contract = None
    if args.contract:
        try:
            with open(args.contract, encoding="utf-8") as fh:
                contract = json.load(fh)
        except (OSError, json.JSONDecodeError):
            raise ContractError("the contract file cannot be read as JSON") from None
    rows: dict = {"*": args.rows}
    for item in args.rows_for or []:
        name, _, n = item.rpartition("=")
        if not name or not n.isdigit():
            raise SynthError("--rows-for expects TABLE=N")
        rows[name] = int(n)
    # Table names are needed to resolve TABLE.COLUMN references before the run.
    from .pipeline import inspect

    names = [t["name"] for t in inspect(args.file, recipe)["recipe"]["tables"] if t["kind"] == "table"]
    opts: dict = {}
    if args.drop:
        opts["drop"] = [_split_ref(x, names) for x in args.drop]
    if args.sensitivity:
        sens = []
        for x in args.sensitivity:
            ref, _, cls = x.rpartition("=")
            sens.append((*_split_ref(ref, names), cls))
        opts["sensitivity"] = sens
    if args.keep_categories:
        opts["keep_categories"] = [_split_ref(x, names) for x in args.keep_categories]
        opts["approved_by"] = args.approved_by
    if args.confirm_contract:
        opts["confirm_by"] = args.confirm_contract
    try:
        result = run(args.file, policy_id=policy.id, rows=rows, seed=args.seed, packing=args.packing, recipe=recipe,
                     contract=contract, out_dir=args.out, private_dir=args.private_dir, requested_tier=args.tier,
                     require_full_coverage=args.require_full_coverage, skip_assessment=args.skip_assessment, **opts)
        code = EXIT_OK
    except CoverageError as exc:
        result = exc.result  # type: ignore[attr-defined]
        code = EXIT_COVERAGE
    exp = result.export
    print(f"Synthetic dataset: {os.path.join(exp['out_dir'], exp['dataset_file'])}")
    for c in result.coverage["tables"]:
        print(f"  {c['table']}: {c['generated_data_rows']} data rows (+{c['blank_rows']} blank), "
              f"{c['scenarios_covered']}/{c['scenarios_total']} scenarios covered; "
              f"rows needed for full coverage: {c['n_min_isolated']} isolated, {c['n_min_packed']} packed")
        for u in c["uncovered"]:
            print(f"    not represented: {u['description']} [{u['reason']}]")
    sv = result.comparison["scenario_verification"]
    print(f"Self-check on the generated file: {sv['covered_scenarios_found_again']} covered scenario(s) found again, "
          f"{len(sv['covered_scenarios_not_found_again'])} not found again.")
    a = result.assessment
    print(f"Privacy assessment: {a['assessment_status']}  |  release tier: {a['release_tier']}")
    for r in a["tier_reasons"]:
        print(f"  - {r}")
    for k, v in a.get("criteria", {}).items():
        print(f"  {k.replace('_', ' ')}: {v['status']}")
    print(f"Report: {os.path.join(exp['out_dir'], 'report.md')}")
    print(NON_CERTIFICATION_STATEMENT)
    if code == EXIT_COVERAGE:
        print("Full coverage was required and not reached.", file=sys.stderr)
    return code


def cmd_check_record(args) -> int:
    from .privacy import effective_tier

    try:
        with open(args.record, encoding="utf-8") as fh:
            record = json.load(fh)
    except (OSError, json.JSONDecodeError):
        raise ContractError("the assessment record cannot be read as JSON") from None
    tier, status = effective_tier(record)
    print(f"Recorded tier: {record.get('release_tier')}  |  tier in force today: {tier}  |  status: {status}  |  "
          f"review by: {record.get('review_by')}")
    return EXIT_OK


def cmd_policies(_args) -> int:
    for p in POLICIES.values():
        print(f"{p.id} (v{p.version}): {p.description}\n  maximum tier: {p.max_tier}; review every "
              f"{p.review_interval_days} days\n  {p.rationale}\n  Limits: {p.limits}\n")
    return EXIT_OK


def cmd_transform(_args) -> int:
    print("Mode A (full dataset conversion: pseudonymisation, generalisation, synthetic at scale) is not available "
          "in this release. None of its strategies has been implemented and assessed, so none is offered. "
          "Use 'generate' (Mode B) to produce a synthetic test dataset.", file=sys.stderr)
    return EXIT_INPUT


def cmd_ui(args) -> int:
    from .ui.server import serve

    return serve(port=args.port, open_browser=not args.no_browser)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="anonimizer", description="Discover the structure and anomalies of a CSV/XLSX "
                                "file and generate a synthetic test dataset that preserves them. Runs offline.")
    p.add_argument("--version", action="version", version=f"anonimizer {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp, policy=True):
        sp.add_argument("file", help="CSV, TSV or XLSX input file")
        sp.add_argument("--recipe", help="parse recipe (JSON) to use instead of automatic detection")
        sp.add_argument("--delimiter", help="CSV delimiter (single character or 'tab')")
        sp.add_argument("--encoding", help="CSV text encoding")
        sp.add_argument("--marker", action="append", help="additional literal to treat as a missing-value marker")
        if policy:
            sp.add_argument("--policy", required=True, choices=sorted(POLICIES), help="privacy policy (no default)")

    sp = sub.add_parser("inspect", help="detect tables and regions; write a parse recipe")
    common(sp, policy=False)
    sp.add_argument("--recipe-out", help="write the proposed recipe to this file")
    sp.set_defaults(func=cmd_inspect)

    sp = sub.add_parser("profile", help="profile the file and print the Exception Catalogue")
    common(sp)
    sp.add_argument("--out", help="directory for the shareable source report")
    sp.add_argument("--private-dir", help="directory for the PRIVATE diagnostic profile")
    sp.set_defaults(func=cmd_profile)

    sp = sub.add_parser("contract", help="write a proposed Dataset Contract")
    common(sp)
    sp.add_argument("-o", "--output", required=True)
    sp.set_defaults(func=cmd_contract)

    sp = sub.add_parser("generate", help="generate a synthetic test dataset (Mode B)")
    common(sp)
    sp.add_argument("-n", "--rows", type=int, required=True, help="number of synthetic data rows")
    sp.add_argument("--rows-for", action="append", metavar="TABLE=N", help="row count for one table")
    sp.add_argument("--seed", default="0", help="seed (same contract and seed give identical output)")
    sp.add_argument("--contract", help="reviewed Dataset Contract (JSON)")
    sp.add_argument("--out", required=True, help="output directory; must be new or empty (nothing is overwritten)")
    sp.add_argument("--packing", choices=["auto", "isolate", "packed"], default="auto")
    sp.add_argument("--require-full-coverage", action="store_true", help="exit with status 3 if a scenario is left out")
    sp.add_argument("--drop", action="append", metavar="TABLE.COLUMN", help="drop a column")
    sp.add_argument("--sensitivity", action="append", metavar="TABLE.COLUMN=CLASS")
    sp.add_argument("--keep-categories", action="append", metavar="TABLE.COLUMN",
                    help="approve copying the frequent literal values of a categorical column")
    sp.add_argument("--approved-by", help="name of the person approving --keep-categories")
    sp.add_argument("--confirm-contract", metavar="NAME", help="record that NAME reviewed the contract")
    sp.add_argument("--tier", choices=["LOCAL_ONLY", "RESTRICTED", "EXTERNAL_CANDIDATE"],
                    help="release tier to label the export with; refused if above the assessed tier")
    sp.add_argument("--private-dir", help="directory for the PRIVATE diagnostic profile")
    sp.add_argument("--skip-assessment", action="store_true", help="skip the privacy assessment (output is LOCAL_ONLY)")
    sp.set_defaults(func=cmd_generate)

    sp = sub.add_parser("check-record", help="show the tier of an assessment record that is in force today")
    sp.add_argument("record")
    sp.set_defaults(func=cmd_check_record)

    sp = sub.add_parser("policies", help="list the shipped privacy policies")
    sp.set_defaults(func=cmd_policies)

    sp = sub.add_parser("transform", help="Mode A, full dataset conversion (not available in this release)")
    sp.add_argument("file", nargs="?")
    sp.set_defaults(func=cmd_transform)

    sp = sub.add_parser("ui", help="start the local web interface (loopback only)")
    sp.add_argument("--port", type=int, default=0, help="port (default: a free random port)")
    sp.add_argument("--no-browser", action="store_true")
    sp.set_defaults(func=cmd_ui)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ExportRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except (GridError, RecipeError, ContractError, PolicyError, SynthError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 - last resort; message withheld because it may quote data
        if os.environ.get("ANONIMIZER_DEBUG") == "1":
            traceback.print_exc()
        else:
            tb = traceback.extract_tb(exc.__traceback__)[-1]
            print(f"internal error: {type(exc).__name__} at {os.path.basename(tb.filename)}:{tb.lineno}. The message "
                  f"is withheld because it may quote data; set ANONIMIZER_DEBUG=1 to see it.", file=sys.stderr)
        return EXIT_INTERNAL


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
