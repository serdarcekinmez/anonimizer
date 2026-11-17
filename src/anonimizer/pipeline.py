"""Mode B orchestration: recipe -> profile -> contract -> synthetic data -> assessment -> export."""

from __future__ import annotations

import datetime as _dt
import json
import os
import tempfile
from dataclasses import dataclass, field

from . import contract as contract_mod
from .export import (
    check_new_file,
    check_output_dir,
    export_bundle,
    manifest_csv,
    render_dataset,
    write_new_file,
)
from .policy import PrivacyPolicy, get_policy
from .privacy import assess, not_assessed
from .profile import build_profile, to_shareable
from .recipe import ParseRecipe
from .reports import compare, render_markdown, summarize_profile
from .synth import generate


class CoverageError(Exception):
    """Raised after export when full coverage was required and not reached."""


@dataclass
class RunResult:
    export: dict
    assessment: dict
    coverage: dict
    manifest: list
    contract: dict
    source_report: dict
    generated_report: dict
    comparison: dict
    report_markdown: str
    private_files: list = field(default_factory=list)


PRIVATE_PROFILE_NAME = "source_profile.PRIVATE.json"


def reconcile_coverage(coverage: dict, comparison: dict) -> None:
    """Coverage states what the planner placed; it is full only if the generated file confirms it.

    A declared relationship that does not hold in the generated cells is reported as not
    represented, and full coverage is withdrawn.
    """
    by_table = {c["table"]: c for c in coverage["tables"]}
    for r in comparison.get("relationship_verification", []):
        if r["status"] != "broken":
            continue
        c = by_table.get(r["from_table"])
        if c is None:
            continue
        c["uncovered"].append({"id": None, "class": "key.relationship", "column": r["from_column"],
                               "description": f"reference to {r['to_table']}.{r['to_column_name']}",
                               "reason": "not preserved in the generated cells"})
        c["full_coverage"] = c["full_coverage_of_reproducible"] = False
    coverage["full_coverage"] = all(c["full_coverage"] for c in coverage["tables"])
    coverage["full_coverage_of_reproducible"] = all(c["full_coverage_of_reproducible"] for c in coverage["tables"])


def check_targets(source: str, out_dir: str, private_dir: str | None = None) -> None:
    """Refuse, before any work, output locations that could replace the source or an earlier output."""
    check_output_dir(out_dir)
    if private_dir:
        check_new_file(os.path.join(private_dir, PRIVATE_PROFILE_NAME), (source,))


def inspect(path: str, recipe: ParseRecipe | None = None) -> dict:
    """Detect regions only (no profiling). Returns the proposed recipe and file facts."""
    from .recipe import propose_recipe

    proposed, source, _regions = propose_recipe(path, recipe)
    return {"recipe": proposed.to_dict(), "file": dict(source.info),
            "sheets": [{"name": s.name, "state": s.state} for s in source.sheets]}


def profile_source(path: str, recipe: ParseRecipe | None, policy: PrivacyPolicy) -> tuple[dict, dict]:
    private = build_profile(path, recipe)
    return private, to_shareable(private, policy)


def apply_decisions(contract: dict, private_profile: dict, *, drop: list[tuple[str, str]] = (),
                    sensitivity: list[tuple[str, str, str]] = (), keep_categories: list[tuple[str, str]] = (),
                    approved_by: str | None = None, confirm_by: str | None = None,
                    rename: list[tuple[str, str, str]] = ()) -> None:
    for table, column in drop:
        contract_mod.find_column(contract, table, column)["keep"] = False
    for table, column, cls in sensitivity:
        if cls not in contract_mod.SENSITIVITY_CLASSES:
            raise contract_mod.ContractError("unknown sensitivity class")
        contract_mod.find_column(contract, table, column)["sensitivity"].update({"class": cls, "basis": "set by the user"})
    for table, column in keep_categories:
        contract_mod.approve_categories(contract, private_profile, table, column, approved_by or "")
    for table, column, new_name in rename:
        contract_mod.find_column(contract, table, column)["name"] = new_name
    if confirm_by:
        contract_mod.confirm_contract(contract, confirm_by)


def generate_and_export(path: str, recipe: ParseRecipe, private_profile: dict, shareable: dict, contract: dict,
                        *, rows, seed=0, packing: str = "auto", out_dir: str, private_dir: str | None = None,
                        requested_tier: str | None = None, require_full_coverage: bool = False,
                        skip_assessment: bool = False, register_path: str | None = None,
                        today: _dt.date | None = None) -> RunResult:
    check_targets(path, out_dir, private_dir)
    policy = contract_mod.validate_contract(contract)
    dataset = generate(contract, rows, seed=seed, packing=packing)
    data, ext, out_recipe = render_dataset(contract, dataset)

    # Profile the generated file with the same engine: this is the "after" evidence.
    tmpdir = tempfile.mkdtemp(prefix="anonimizer-")
    tmp = os.path.join(tmpdir, "generated" + ext)
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        out_profile = to_shareable(build_profile(tmp, ParseRecipe.from_dict(out_recipe)), policy)
    finally:
        try:
            os.remove(tmp)
        finally:
            os.rmdir(tmpdir)
    source_report = summarize_profile(shareable, "source")
    generated_report = summarize_profile(out_profile, "generated")
    generated_report["generation"] = dataset["params"]
    comparison = compare(shareable, out_profile, dataset, contract)
    coverage = dataset["coverage"]
    reconcile_coverage(coverage, comparison)
    manifest = dataset["manifest"]
    recipe_doc = private_profile["recipe"]
    documents = {
        "scenario_manifest.json": {"manifest": manifest, "note": "Rows are 1-based data rows of each generated table. "
                                   "Classes marked common in the coverage report also occur in other rows."},
        "scenario_manifest.csv": manifest_csv(manifest),
        "coverage_report.json": coverage,
        "source_report.json": source_report,
        "generated_report.json": generated_report,
        "comparison.json": comparison,
        "contract.json": contract,
        "recipe.json": recipe_doc,
    }
    texts = {k: (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)) for k, v in documents.items()}
    if skip_assessment:
        assessment = not_assessed(contract, dataset, policy, today)
    else:
        assessment = assess(path, recipe, contract, dataset, private_profile, policy, artifacts=texts, today=today)
    report_md = render_markdown(source_report, generated_report, comparison, coverage, manifest, assessment)
    documents["report.md"] = report_md
    export = export_bundle(out_dir, dataset_bytes=data, dataset_ext=ext, documents=documents,
                           assessment=assessment, requested_tier=requested_tier, register_path=register_path)
    private_files = []
    if private_dir:
        ppath = os.path.join(private_dir, PRIVATE_PROFILE_NAME)
        write_new_file(ppath, json.dumps(private_profile, ensure_ascii=False, indent=2).encode("utf-8"))
        private_files.append(ppath)
    result = RunResult(export, assessment, coverage, manifest, contract, source_report, generated_report,
                       comparison, report_md, private_files)
    if require_full_coverage and not coverage["full_coverage_of_reproducible"]:
        err = CoverageError("full scenario coverage was required but not reached; see coverage_report.json")
        err.result = result  # type: ignore[attr-defined]
        raise err
    return result


def run(path: str, *, policy_id: str, rows, seed=0, packing: str = "auto", recipe: ParseRecipe | None = None,
        contract: dict | None = None, out_dir: str, **options) -> RunResult:
    """One-shot Mode B run."""
    policy = get_policy(policy_id)
    recipe = recipe or ParseRecipe()
    decisions = {k: options.pop(k) for k in ("drop", "sensitivity", "keep_categories", "approved_by", "confirm_by",
                                              "rename") if k in options}
    check_targets(path, out_dir, options.get("private_dir"))
    private, shareable = profile_source(path, recipe, policy)
    if contract is None:
        contract = contract_mod.build_contract(shareable, policy)
    elif contract.get("policy", {}).get("id") != policy.id:
        raise contract_mod.ContractError("the contract was built under a different policy than the one selected")
    if decisions:
        apply_decisions(contract, private, **decisions)
    return generate_and_export(path, recipe, private, shareable, contract, rows=rows, seed=seed, packing=packing,
                               out_dir=out_dir, **options)
