"""Deterministic checks on the compliance baseline (traceability matrix, findings, source record).

    python tools/check_rtm.py             integrity checks; source staleness is a warning
    python tools/check_rtm.py --release   adds the release rule on the findings register and makes staleness an error

The gate reads the register and the files. It never reads a model's verdict.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPLIANCE = os.path.join(ROOT, "docs", "compliance")
BASIS = {"CNIL-direct", "CNIL-derived", "ANON-policy"}
KINDS = {"A", "H", "A+H"}
STATUSES = {"implemented", "partial", "planned", "not_applicable"}
STRENGTHS = {"definition", "advice", "criterion", "required-if", "description"}
CATEGORIES = {"DEFECT", "RISK", "EVIDENCE-GAP", "JUDGMENT", "SOURCE-DRIFT"}
SEVERITIES = {"blocker", "high", "medium", "low"}
MARKER = re.compile(r"""@pytest\.mark\.cnil\(\s*["']([A-Z0-9-]+)["']\s*\)""")
ROW_FIELDS = ("id", "requirement", "basis", "components", "control", "control_basis", "kind", "status", "evidence", "notes")


def _load(*parts):
    with open(os.path.join(COMPLIANCE, *parts), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_markers() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for base, _dirs, files in os.walk(os.path.join(ROOT, "tests")):
        for f in files:
            if f.endswith(".py"):
                with open(os.path.join(base, f), encoding="utf-8") as fh:
                    for m in MARKER.finditer(fh.read()):
                        found.setdefault(m.group(1), []).append(os.path.relpath(os.path.join(base, f), ROOT))
    return found


def check(release: bool = False, today: dt.date | None = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    today = today or dt.date.today()
    reqs = _load("cnil", "requirements.yaml")
    rtm = _load("rtm.yaml")
    findings = _load("findings.yaml")
    req_ids = []
    for r in reqs.get("requirements", []):
        for key in ("id", "section", "quote", "strength", "interpretation"):
            if not r.get(key):
                errors.append(f"requirements.yaml: {r.get('id', '?')} lacks '{key}'")
        if r.get("strength") not in STRENGTHS:
            errors.append(f"requirements.yaml: {r.get('id', '?')} has an unknown strength")
        req_ids.append(r.get("id"))
    if len(set(req_ids)) != len(req_ids):
        errors.append("requirements.yaml: duplicate requirement ids")
    markers = test_markers()
    row_ids = []
    covered = set()
    for row in rtm.get("rows", []):
        rid = row.get("id", "?")
        row_ids.append(rid)
        for key in ROW_FIELDS:
            if key not in row:
                errors.append(f"rtm.yaml: row {rid} lacks '{key}'")
        if row.get("requirement") not in req_ids:
            errors.append(f"rtm.yaml: row {rid} points at an unknown requirement")
        covered.add(row.get("requirement"))
        if row.get("basis") not in BASIS or row.get("control_basis") not in BASIS:
            errors.append(f"rtm.yaml: row {rid} has an unknown basis")
        if row.get("kind") not in KINDS:
            errors.append(f"rtm.yaml: row {rid} has an unknown kind")
        status = row.get("status")
        if status not in STATUSES:
            errors.append(f"rtm.yaml: row {rid} has an unknown status")
        if rid.startswith("ANON-") and row.get("basis") != "ANON-policy":
            errors.append(f"rtm.yaml: row {rid} is a project rule and must have basis ANON-policy")
        automated = "A" in str(row.get("kind", "")).split("+")
        if status in ("implemented", "partial"):
            if automated and rid not in markers:
                errors.append(f"rtm.yaml: row {rid} is {status} and automated but no test carries cnil(\"{rid}\")")
            if not row.get("evidence"):
                errors.append(f"rtm.yaml: row {rid} is {status} without evidence")
            else:
                path = str(row["evidence"]).split("::")[0]
                if not os.path.exists(os.path.join(ROOT, path)):
                    errors.append(f"rtm.yaml: row {rid} cites evidence that does not exist")
                elif "::" in str(row["evidence"]):
                    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
                        if f"def {str(row['evidence']).split('::')[1]}(" not in fh.read():
                            errors.append(f"rtm.yaml: row {rid} cites a test function that does not exist")
        if status == "partial" and not row.get("notes"):
            errors.append(f"rtm.yaml: row {rid} is partial and must say what is missing")
    if len(set(row_ids)) != len(row_ids):
        errors.append("rtm.yaml: duplicate row ids")
    for rid in req_ids:
        if rid not in covered:
            errors.append(f"rtm.yaml: requirement {rid} has no row")
    for mid in markers:
        if mid not in row_ids:
            errors.append(f"tests: marker cnil(\"{mid}\") matches no matrix row ({markers[mid][0]})")
    # Source record.
    with open(os.path.join(COMPLIANCE, "cnil", "SOURCE.md"), encoding="utf-8") as fh:
        source = fh.read()
    sha = re.search(r"Normalised SHA-256 \| `([0-9a-f]{64})`", source)
    got = re.search(r"\| Retrieved \| (\d{4}-\d{2}-\d{2})", source)
    interval = re.search(r"Review interval \| (\d+) days", source)
    if not sha or not got or not interval:
        errors.append("SOURCE.md: hash, retrieval date or review interval missing")
    else:
        if sha.group(1) != reqs.get("source_sha256"):
            errors.append("requirements.yaml was written for a different source hash than SOURCE.md records")
        age = (today - dt.date.fromisoformat(got.group(1))).days
        if age > int(interval.group(1)):
            (errors if release else warnings).append(f"SOURCE.md: the reference was retrieved {age} days ago; review is due")
    if "Drift status | none recorded" not in source:
        (errors if release else warnings).append("SOURCE.md: a source drift is recorded and not resolved")
    # Findings register.
    ids = set()
    for f in findings.get("findings", []):
        fid = f.get("id", "?")
        if fid in ids:
            errors.append(f"findings.yaml: duplicate id {fid}")
        ids.add(fid)
        if f.get("category") not in CATEGORIES or f.get("severity") not in SEVERITIES:
            errors.append(f"findings.yaml: {fid} has an unknown category or severity")
        if f.get("status") not in ("open", "dispositioned", "closed"):
            errors.append(f"findings.yaml: {fid} has an unknown status")
        if f.get("rtm_row") not in row_ids:
            errors.append(f"findings.yaml: {fid} points at an unknown matrix row")
        if f.get("status") == "dispositioned" and not f.get("disposition"):
            errors.append(f"findings.yaml: {fid} is dispositioned without a disposition")
        if release and f.get("status") == "open" and f.get("severity") in ("blocker", "high"):
            if f.get("category") == "DEFECT":
                errors.append(f"release: {fid} is an open {f['severity']} DEFECT; it cannot be waived")
            else:
                errors.append(f"release: {fid} ({f['category']}, {f['severity']}) has no disposition")
        if release and f.get("status") == "dispositioned" and f.get("severity") in ("blocker", "high"):
            decision = os.path.join(COMPLIANCE, "decisions", f"{fid}.md")
            if not os.path.exists(decision):
                errors.append(f"release: {fid} needs a signed decision file docs/compliance/decisions/{fid}.md")
    return errors, warnings


def summary() -> dict:
    rtm = _load("rtm.yaml")
    out: dict[str, int] = {}
    for row in rtm.get("rows", []):
        out[row["status"]] = out.get(row["status"], 0) + 1
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    errors, warnings = check(release="--release" in argv)
    for w in warnings:
        print(f"check_rtm: warning: {w}")
    for e in errors:
        print(f"check_rtm: {e}")
    print(f"check_rtm: rows by status {summary()}; {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
