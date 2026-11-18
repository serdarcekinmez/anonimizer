"""Key relationships between tables, measured on the generated cells (ASTRA-03).

All workbooks are synthetic and built here: integer keys, no real values.
"""

from __future__ import annotations

import copy

import pytest
from openpyxl import Workbook

from anonimizer.contract import ContractError, build_contract, find_column, validate_contract
from anonimizer.pipeline import profile_source, run
from anonimizer.policy import get_policy
from anonimizer.recipe import ParseRecipe
from anonimizer.reports import verify_relationships
from anonimizer.synth import OutCell, generate

POL = get_policy("internal-dev")


def _book(path, sheets: dict[str, tuple[list[str], list[list]]]) -> str:
    wb = Workbook()
    wb.remove(wb.active)
    for name, (header, rows) in sheets.items():
        ws = wb.create_sheet(name)
        ws.append(header)
        for r in rows:
            ws.append(r)
    wb.save(path)
    return str(path)


def _one_to_one(tmp_path) -> str:
    keys = [1000 + 7 * i for i in range(50)]
    return _book(tmp_path / "one_to_one.xlsx", {
        "customers": (["customer_id", "city_code"], [[k, 10 + i % 7] for i, k in enumerate(keys)]),
        "details": (["customer_id", "score_band"], [[k, i % 5] for i, k in enumerate(reversed(keys))]),
    })


def _cycle(tmp_path) -> str:
    """customers.last_order_id -> orders.order_id and orders.customer_id -> customers.customer_id."""
    cust = [500 + 3 * i for i in range(40)]
    orders = [90000 + 11 * i for i in range(60)]
    return _book(tmp_path / "cycle.xlsx", {
        "customers": (["customer_id", "last_order_id"], [[c, orders[i]] for i, c in enumerate(cust)]),
        "orders": (["order_id", "customer_id"], [[o, cust[i % 40]] for i, o in enumerate(orders)]),
    })


def _contract(path):
    _private, share = profile_source(path, ParseRecipe(), POL)
    return build_contract(share, POL)


def _keys(dataset, table, column_id):
    t = dataset["tables"][table]
    j = t["columns"].index(column_id)
    return [r["cells"][j].text for r in t["rows"] if r["kind"] == "data" and j < len(r["cells"])]


def test_one_to_one_tables_get_one_direction_only(tmp_path):
    c = _contract(_one_to_one(tmp_path))
    refs = [(r["from_table"], r["to_table"]) for r in c["relationships"]]
    assert refs == [("details", "customers")]
    child = find_column(c, "details", "customer_id")
    assert child["key"]["role"] == "reference" and child["key"]["references"]["one_to_one"] is True
    assert find_column(c, "customers", "customer_id")["key"]["role"] == "unique"


def test_one_to_one_keys_join_in_the_output(tmp_path):
    src = _one_to_one(tmp_path)
    res = run(src, policy_id="internal-dev", rows=30, seed=1, out_dir=str(tmp_path / "o"))
    ds = generate(res.contract, 30, seed=1)
    parent, child = _keys(ds, "customers", "c1"), _keys(ds, "details", "c1")
    assert len(set(child)) == len(child) == 30          # still unique
    assert set(child) <= set(parent)                    # every detail joins a customer
    rel = res.comparison["relationship_verification"]
    assert [(r["from_table"], r["status"]) for r in rel] == [("details", "preserved")]
    assert rel[0]["dangling_rows"] == 0 and rel[0]["repeated_values"] == 0
    assert res.coverage["full_coverage_of_reproducible"] is True


def test_reference_cycles_are_generated_with_every_relationship_intact(tmp_path):
    src = _cycle(tmp_path)
    c = _contract(src)
    declared = {(r["from_table"], r["to_table"]) for r in c["relationships"]}
    assert declared == {("customers", "orders"), ("orders", "customers")}
    res = run(src, policy_id="internal-dev", rows=25, seed=3, out_dir=str(tmp_path / "o"))
    ds = generate(res.contract, 25, seed=3)
    for ft, fc, tt, tc in (("customers", "c2", "orders", "c1"), ("orders", "c2", "customers", "c1")):
        child = [k for k in _keys(ds, ft, fc) if k]
        assert child and set(child) <= set(_keys(ds, tt, tc)), (ft, tt)
    assert all("\x00" not in (k or "") for t in ds["tables"] for k in _keys(ds, t, "c1") + _keys(ds, t, "c2"))
    statuses = {(r["from_table"], r["status"]) for r in res.comparison["relationship_verification"]}
    assert statuses == {("customers", "preserved"), ("orders", "preserved")}
    # Same contract and seed, same output.
    assert generate(res.contract, 25, seed=3)["tables"] == ds["tables"]


def test_a_reference_inside_one_table_is_resolved(tmp_path):
    src = _book(tmp_path / "self.xlsx", {"staff": (["employee_id", "manager_id"],
                                                    [[100 + i, 100 + i // 4] for i in range(40)])})
    c = _contract(src)
    mgr = find_column(c, "staff", "manager_id")
    mgr["key"]["role"] = "reference"
    mgr["key"]["references"] = {"table": "staff", "column": "c1", "column_name": "employee_id"}
    ds = generate(c, 20, seed=2)
    assert set(_keys(ds, "staff", "c2")) <= set(_keys(ds, "staff", "c1"))
    assert [r["status"] for r in verify_relationships(c, ds)] == ["preserved"]


def test_a_broken_relationship_is_reported_and_fails_full_coverage(tmp_path):
    src = _one_to_one(tmp_path)
    c = _contract(src)
    ds = generate(c, 20, seed=1)
    t = ds["tables"]["details"]
    j = t["columns"].index("c1")
    data = [r for r in t["rows"] if r["kind"] == "data"]
    data[0]["cells"][j] = OutCell("424242", "n")          # dangling
    data[1]["cells"][j] = data[2]["cells"][j]              # repeated in a one-to-one child
    rel = verify_relationships(c, ds)
    assert rel[0]["status"] == "broken" and rel[0]["dangling_rows"] == 1 and rel[0]["repeated_values"] == 1
    assert "424242" not in repr(rel)
    from anonimizer.pipeline import reconcile_coverage

    cov = copy.deepcopy(ds["coverage"])
    assert cov["full_coverage_of_reproducible"] is True
    reconcile_coverage(cov, {"relationship_verification": rel})
    assert cov["full_coverage_of_reproducible"] is False
    assert [u["class"] for c in cov["tables"] for u in c["uncovered"]] == ["key.relationship"]


def test_references_to_a_dropped_or_non_key_column_are_rejected(tmp_path):
    c = _contract(_one_to_one(tmp_path))
    dropped = copy.deepcopy(c)
    find_column(dropped, "customers", "customer_id")["keep"] = False
    with pytest.raises(ContractError) as exc:
        validate_contract(dropped)
    assert "details" in str(exc.value) and "not kept" in str(exc.value)
    chained = copy.deepcopy(c)
    find_column(chained, "details", "customer_id")["key"]["references"]["column"] = "c2"
    find_column(chained, "customers", "city_code")["key"]["role"] = "reference"
    find_column(chained, "customers", "city_code")["key"]["references"] = {"table": "details", "column": "c1"}
    with pytest.raises(ContractError):
        validate_contract(chained)
    unknown = copy.deepcopy(c)
    find_column(unknown, "details", "customer_id")["key"]["references"]["table"] = "nowhere"
    with pytest.raises(ContractError):
        validate_contract(unknown)
