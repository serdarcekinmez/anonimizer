"""Detection against ground truth that was written by the fixture builder, not by the detector."""

from __future__ import annotations

import pytest

from anonimizer.profile import build_profile, iter_exceptions
from score_detection import score
from tests.conftest import PRODUCT_FILES

# Findings the builder did not list, each checked by hand. They are real properties of the
# fixture: the planted one-off values are also, by construction, categories that occur once.
KNOWN_ADDITIONAL = {
    "customers_hidden.csv": {("table_1", "notes", "category.rare_value")},
    "orders_multi.tsv": {("table_1", "comment", "category.rare_value")},
    "inventory_mixed.xlsx": set(),
}


@pytest.mark.parametrize("name", PRODUCT_FILES)
def test_every_planted_anomaly_is_found_with_the_exact_count(name, profiles, truths):
    s = score(profiles[name], truths[name])
    assert s["missed"] == [] and s["count_mismatch"] == []
    assert s["matched_exactly"] == s["planted_classes"] > 15


@pytest.mark.parametrize("name", PRODUCT_FILES)
def test_no_unexplained_findings(name, profiles, truths):
    s = score(profiles[name], truths[name])
    extra = {(a["table"], a["column"], a["class"]) for a in s["additional_findings"]}
    assert extra == KNOWN_ADDITIONAL[name]


@pytest.mark.parametrize("name", PRODUCT_FILES)
def test_table_structure_matches(name, profiles, truths):
    got = [(t["name"], t["n_rows"], t["n_columns"], t["region"]["header_row"]) for t in profiles[name]["tables"]]
    exp = [(t["name"], t["rows"], t["columns"], t["header_row"]) for t in truths[name]["tables"]]
    assert got == exp


@pytest.mark.parametrize("name", ["orders_multi.tsv", "inventory_mixed.xlsx"])
def test_relationships_match(name, profiles, truths):
    got = [(f"{r['from_table']}.{r['from_column_name']}", f"{r['to_table']}.{r['to_column_name']}", r["dangling_rows"])
           for r in profiles[name]["relationships"]]
    exp = [(r["from"], r["to"], r["dangling_rows"]) for r in truths[name]["relationships"]]
    assert got == exp


def test_private_locations_point_at_the_planted_rows(profiles, truths):
    """Row numbers stay in the private profile and must be right, or the diagnostics are useless."""
    for name in PRODUCT_FILES:
        located: dict = {}
        for ex in iter_exceptions(profiles[name]):
            if ex.get("table"):
                located.setdefault((ex["table"], ex.get("column_name"), ex["class"]), set()).update(ex["_private"]["rows"])
        checked = 0
        for a in truths[name]["anomalies"]:
            rows = set(a["rows"])
            if not rows or len(rows) > 5 or a["class"].startswith(("key.", "row.duplicate", "category.")):
                continue
            got = located[(a["table"], a["column"], a["class"])]
            if name.endswith(".xlsx") or a["class"] != "row.blank_inside_table":
                assert got == rows, (name, a)
            checked += 1
        assert checked >= 10


def test_file_level_facts(profiles):
    orders = profiles["orders_multi.tsv"]["source"]
    assert orders["encoding"]["encoding"] == "cp1252" and orders["delimiter"]["delimiter"] == "\t"
    assert orders["newlines"] == {"crlf": 1360}  # 2 notes, 4 blank lines, 2 headers, 1350 data rows, 1 blank row inside, 1 footer
    classes = {e["class"] for e in profiles["inventory_mixed.xlsx"]["file_exceptions"]}
    assert {"workbook.hidden_sheets", "workbook.merged_cells", "workbook.hidden_rows", "workbook.comments",
            "workbook.defined_names", "workbook.author_metadata"} <= classes


def test_single_text_value_deep_in_a_numeric_column(tmp_path):
    """The directive's named case: one text value far down a large numeric column."""
    from build_fixtures import build_customers

    from anonimizer.contract import build_contract
    from anonimizer.policy import get_policy
    from anonimizer.profile import to_shareable
    from anonimizer.synth import generate

    path = str(tmp_path / "deep.csv")
    n = 120_000
    truth = build_customers(path, n_rows=n, seed=99, deep_text="awaiting audit")
    prof = build_profile(path)
    planted = next(a for a in truth["anomalies"] if a["column"] == "balance" and a["class"] == "type.text_in_number")
    assert planted["rows"] == [int(n * 0.975) + 2]
    found = [e for e in iter_exceptions(prof) if e["column_name"] == "balance" and e["class"] == "type.text_in_number"]
    assert len(found) == 1 and found[0]["count"] == 1
    assert found[0]["_private"]["rows"] == planted["rows"]
    bal = next(c for c in prof["tables"][0]["columns"] if c["name"] == "balance")
    assert bal["logical_type"] == "decimal" and bal["families"]["text"] == 1
    assert score(prof, truth)["missed"] == []
    # ... and its pattern is represented in the generated data, without the source text.
    pol = get_policy("internal-dev")
    ds = generate(build_contract(to_shareable(prof, pol), pol), 60, seed=11)
    entry = next(m for m in ds["manifest"] if m["class"] == "type.text_in_number" and m["column_name"] == "balance")
    t = ds["tables"]["table_1"]
    cell = t["rows"][entry["data_rows"][0] - 1]["cells"][t["columns"].index("c6")]
    assert cell.text != "awaiting audit" and " " in cell.text and cell.text.replace(" ", "").isalpha()
