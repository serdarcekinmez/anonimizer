"""The generated file really contains what the Scenario Manifest says, where it says."""

from __future__ import annotations

import json
import os

import pytest

from anonimizer.grid import open_source
from anonimizer.patterns import INVALID, MISSING, NEG, NUM, PADDED, TXT, ZERO, classify
from anonimizer.pipeline import CoverageError, run
from tests.conftest import PRODUCT_FILES, product_path

CHECKS = {
    "missing.marker": lambda v, c: v.family == MISSING and v.sub.startswith("marker:"),
    "missing.empty": lambda v, c: v.family == MISSING and v.sub in ("empty", "absent"),
    "missing.quoted_empty": lambda v, c: v.sub == "quoted_empty",
    "missing.whitespace": lambda v, c: v.sub == "whitespace",
    "type.text_in_number": lambda v, c: v.family == TXT,
    "value.invalid_date": lambda v, c: bool(v.flags & INVALID),
    "numeric.zero": lambda v, c: v.family == NUM and bool(v.flags & ZERO),
    "numeric.negative": lambda v, c: v.family == NUM and bool(v.flags & NEG),
    "text.padded": lambda v, c: bool(v.flags & PADDED),
    "xlsx.error_value": lambda v, c: c.stype == "error",
    "storage.number_as_text": lambda v, c: c.stype.endswith("string") and v.family == NUM,
    "storage.date_as_text": lambda v, c: c.stype.endswith("string"),
    "format.boolean_deviation": lambda v, c: v.family == "bool",
}


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    out = {}
    for name in PRODUCT_FILES:
        d = str(tmp_path_factory.mktemp("gen") / name.split(".")[0])
        out[name] = (run(product_path(name), policy_id="internal-dev", rows=70, seed=21, out_dir=d), d)
    return out


@pytest.mark.parametrize("name", PRODUCT_FILES)
def test_every_reproducible_scenario_is_covered_at_70_rows(name, runs):
    res, _d = runs[name]
    assert res.coverage["full_coverage_of_reproducible"]
    for t in res.coverage["tables"]:
        for u in t["uncovered"]:
            assert u["reason"] != "row budget too small"


@pytest.mark.parametrize("name", PRODUCT_FILES)
def test_manifest_locations_hold_the_described_condition(name, runs):
    res, d = runs[name]
    path = os.path.join(d, res.export["dataset_file"])
    src = open_source(path)
    sheets = {s.name: s.index for s in src.sheets}
    grids = {s.name: {r.index + 1: r for r in src.rows(s.index)} for s in src.sheets}
    tables = {t["name"]: t for t in res.contract["tables"]}
    checked = 0
    for e in res.manifest:
        check = CHECKS.get(e["class"])
        if check is None or not e["column"]:
            continue
        sheet = tables[e["table"]]["sheet"] if src.format == "xlsx" else "csv"
        assert sheet in sheets
        for loc in e["locations"]:
            row = grids[sheet][loc["row"]]
            col = (loc["field"] if "field" in loc else _col_index(loc["cell"])) - 1
            cell = row.cell(col)
            v = classify(cell.raw, cell.stype, cell.quoted, cell.number_format)
            assert check(v, cell), (name, e["scenario_id"], loc)
            checked += 1
    assert checked >= 8


def _col_index(ref: str) -> int:
    n = 0
    for ch in ref.rstrip("0123456789"):
        n = n * 26 + (ord(ch) - 64)
    return n


@pytest.mark.parametrize("name", PRODUCT_FILES)
def test_structure_is_preserved(name, runs):
    res, _d = runs[name]
    assert res.comparison["structural_differences"] == []
    for t in res.comparison["tables"]:
        assert t["generated_rows"] == t["requested_rows"]
        for c in t["columns"]:
            assert c["name_preserved"], (name, c["name"])
    types = [(c["name"], c["source_type"], c["generated_type"]) for t in res.comparison["tables"] for c in t["columns"]]
    preserved = sum(1 for _n, a, b in types if a == b)
    assert preserved / len(types) >= 0.9, [x for x in types if x[1] != x[2]]


@pytest.mark.parametrize("name", PRODUCT_FILES)
def test_self_check_finds_most_scenarios_again(name, runs):
    res, _d = runs[name]
    sv = res.comparison["scenario_verification"]
    lost = {u["class"] for u in sv["covered_scenarios_not_found_again"]}
    assert lost <= {"category.rare_value", "text.rare_pattern", "key.multiplicity"}, lost
    assert sv["covered_scenarios_found_again"] >= 20


def test_layout_of_the_irregular_file_is_kept(runs):
    res, d = runs["orders_multi.tsv"]
    raw = open(os.path.join(d, res.export["dataset_file"]), "rb").read()
    assert raw.count(b"\r\n") == raw.count(b"\n") and b"\t" in raw
    raw.decode("cp1252")
    lines = raw.decode("cp1252").split("\r\n")
    assert lines[2] == "" and lines[3].split("\t")[0] == "order_no"
    regions = [r["name"] for r in res.generated_report["regions"]]
    assert regions == ["table_1", "table_2"]
    assert res.generated_report["tables"][0]["rows"] == 70


def test_workbook_output_is_a_fresh_file(runs):
    import zipfile

    res, d = runs["inventory_mixed.xlsx"]
    path = os.path.join(d, res.export["dataset_file"])
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        blob = b"".join(z.read(n) for n in names)
    assert not any("comments" in n or "vbaProject" in n or "externalLinks" in n for n in names)
    assert b"Fixture Author" not in blob and b"<f>" not in blob and b"definedName " not in blob
    src = open_source(path)
    assert [s.name for s in src.sheets] == ["Stock", "Suppliers", "Archive"]
    assert all(s.state == "visible" for s in src.sheets)


def test_require_full_coverage_fails_loudly(tmp_path):
    with pytest.raises(CoverageError) as exc:
        run(product_path("customers_hidden.csv"), policy_id="internal-dev", rows=4, seed=1,
            out_dir=str(tmp_path / "o"), require_full_coverage=True)
    res = exc.value.result
    assert not res.coverage["full_coverage_of_reproducible"]
    report = json.load(open(tmp_path / "o" / "coverage_report.json"))
    assert report["tables"][0]["uncovered"]
