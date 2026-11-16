"""The privacy checks themselves: each must fail on a planted problem and pass without it."""

from __future__ import annotations

import copy
import datetime as dt
import json
import os

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from anonimizer.contract import approve_categories, build_contract
from anonimizer.export import ExportRefused, export_bundle, render_dataset
from anonimizer.grid import open_source
from anonimizer.pipeline import profile_source, run
from anonimizer.policy import EXTERNAL_CANDIDATE, LOCAL_ONLY, POLICIES, RESTRICTED, TIER_ORDER, get_policy
from anonimizer.privacy import FAILED, PASSED, assess, derive_tier, effective_tier
from anonimizer.recipe import ParseRecipe
from anonimizer.synth import OutCell, generate
from tests.conftest import confirm_all, product_path

SRC = product_path("customers_hidden.csv")


@pytest.fixture(scope="module")
def base():
    pol = get_policy("internal-dev")
    private, share = profile_source(SRC, ParseRecipe(), pol)
    contract = build_contract(share, pol)
    return pol, private, share, contract


def _source_rows(n=5, start=100):
    rows = []
    for i, row in enumerate(open_source(SRC).rows()):
        if i >= start and len(row.raw) == 10 and all(row.raw[:9]):
            rows.append(list(row.raw))
        if len(rows) == n:
            break
    return rows


def _assess(base, dataset, contract=None, artifacts=None):
    pol, private, _share, c = base
    return assess(SRC, ParseRecipe(), contract or c, dataset, private, pol, artifacts=artifacts or {},
                  today=dt.date(2026, 11, 16))


@pytest.mark.cnil("CNIL-10")
def test_clean_synthetic_output_passes(base):
    ds = generate(base[3], 60, seed=1)
    rec = _assess(base, ds)
    assert rec["assessment_status"] == PASSED
    m = rec["criteria"]["singling_out"]["metrics"]
    assert m["rows_at_or_above_threshold"] == 0 and m["source_rows_equal_to_a_synthetic_row"] == 0
    assert m["rows_evaluated"] > 50 and m["max_similarity"] < 0.6


@pytest.mark.cnil("CNIL-10")
@pytest.mark.cnil("ANON-01")
def test_copied_source_rows_are_detected(base):
    ds = generate(base[3], 60, seed=1)
    rows = [r for r in ds["tables"]["table_1"]["rows"] if r["kind"] == "data"]
    for target, src in zip(rows[10:13], _source_rows(3)):
        target["cells"] = [OutCell(v) for v in src]
    rec = _assess(base, ds)
    m = rec["criteria"]["singling_out"]["metrics"]
    assert rec["criteria"]["singling_out"]["status"] == FAILED
    assert m["rows_at_or_above_threshold"] == 3 and m["source_rows_equal_to_a_synthetic_row"] == 3
    assert rec["assessment_status"] == FAILED and rec["release_tier"] == LOCAL_ONLY


@pytest.mark.cnil("CNIL-10")
def test_near_copies_are_caught_by_the_strict_policy(base):
    strict = get_policy("external-strict")
    private, share = profile_source(SRC, ParseRecipe(), strict)
    contract = build_contract(share, strict)
    ds = generate(contract, 60, seed=1)
    rows = [r for r in ds["tables"]["table_1"]["rows"] if r["kind"] == "data"]
    src = _source_rows(1)[0]
    cells = [OutCell(v) for v in src]
    cells[5] = OutCell("77.77")  # one attribute changed: still the same person
    rows[20]["cells"] = cells
    rec = assess(SRC, ParseRecipe(), contract, ds, private, strict, today=dt.date(2026, 11, 16))
    assert rec["criteria"]["singling_out"]["metrics"]["rows_at_or_above_threshold"] == 1
    assert rec["assessment_status"] == FAILED


@pytest.mark.cnil("CNIL-11")
def test_copied_identifiers_are_detected(base):
    ds = generate(base[3], 60, seed=1)
    t = ds["tables"]["table_1"]
    j = t["columns"].index("c3")  # email
    rows = [r for r in t["rows"] if r["kind"] == "data" and len(r["cells"]) > j]
    for target, src in zip(rows[5:9], _source_rows(4, start=900)):
        target["cells"][j] = OutCell(src[2])
    rec = _assess(base, ds)
    link = rec["criteria"]["linkability"]
    email = next(c for c in link["metrics"]["identifier_columns"] if c["column"] == "email")
    assert email["values_also_in_source"] == 4 and email["verdict"] == "exceeds_chance"
    assert link["status"] == FAILED and rec["release_tier"] == LOCAL_ONLY


@pytest.mark.cnil("CNIL-11")
def test_dense_key_space_is_reported_as_residual_risk_not_as_a_leak(tmp_path):
    p = tmp_path / "dense.csv"
    p.write_text("item_id,qty\n" + "\n".join(f"{i},{(i * 7) % 90 + 10}" for i in range(1, 100)) + "\n")
    res = run(str(p), policy_id="internal-dev", rows=30, seed=1, out_dir=str(tmp_path / "o"))
    link = res.assessment["criteria"]["linkability"]
    col = link["metrics"]["identifier_columns"][0]
    assert col["dense_value_space"] and col["values_also_in_source"] > 0 and col["verdict"] == "within_chance"
    assert link["status"] == "passed_with_residual_risk"
    assert any("dense value space" in s for s in res.assessment["residual_risk_statements"])


@pytest.mark.cnil("CNIL-10")
def test_replicated_source_unique_combination_is_detected(base):
    pol, private, _share, c0 = base
    contract = copy.deepcopy(c0)
    for col in contract["tables"][0]["columns"]:
        if col["name"] in ("signup_date", "country"):
            col["sensitivity"]["class"] = "quasi_identifier"
    ds = generate(contract, 60, seed=1)
    rec = _assess(base, ds, contract)
    m = rec["criteria"]["singling_out"]["metrics"]
    assert m["quasi_identifiers_evaluable"] and m["source_unique_combinations_replicated"] == 0
    t = ds["tables"]["table_1"]
    rows = [r for r in t["rows"] if r["kind"] == "data" and len(r["cells"]) == 10]
    src = _source_rows(1, start=2000)[0]
    rows[7]["cells"][3], rows[7]["cells"][4] = OutCell(src[3]), OutCell(src[4])
    rec = _assess(base, ds, contract)
    assert rec["criteria"]["singling_out"]["metrics"]["source_unique_combinations_replicated"] == 1
    assert rec["criteria"]["singling_out"]["status"] == FAILED


@pytest.mark.cnil("ANON-03")
def test_source_value_in_a_report_is_detected(base):
    ds = generate(base[3], 30, seed=1)
    src = _source_rows(1, start=300)[0]
    clean = {"report.json": json.dumps({"note": "nothing to see"})}
    assert _assess(base, ds, artifacts=clean)["criteria"]["source_leakage"]["status"] == PASSED
    leaky = {"report.json": json.dumps({"example": src[1]})}
    rec = _assess(base, ds, artifacts=leaky)
    assert rec["criteria"]["source_leakage"]["status"] == FAILED
    assert rec["criteria"]["source_leakage"]["metrics"]["source_values_found_in_reports"] == 1
    assert src[1] not in json.dumps(rec)  # the record counts the hit, it does not repeat the value
    private_leak = {"p.json": json.dumps({"_private": {"rows": [1]}})}
    assert _assess(base, ds, artifacts=private_leak)["criteria"]["source_leakage"]["status"] == FAILED


@pytest.mark.cnil("CNIL-12")
def test_approved_literals_on_a_sensitive_column_leave_a_residual_statement(base):
    pol, private, _share, c0 = base
    contract = copy.deepcopy(c0)
    approve_categories(contract, private, "table_1", "country", "Data Owner")
    ds = generate(contract, 60, seed=1)
    values = {r["cells"][4].text for r in ds["tables"]["table_1"]["rows"] if r["kind"] == "data" and len(r["cells"]) > 4}
    assert {"FR", "DE"} <= values
    rec = _assess(base, ds, contract)
    inf = rec["criteria"]["inference"]
    assert inf["status"] == "passed_with_residual_risk"
    assert inf["metrics"]["columns_with_approved_literals"][0]["approved_by"] == "Data Owner"
    assert rec["criteria"]["singling_out"]["status"] != FAILED


@pytest.mark.cnil("CNIL-02")
@pytest.mark.cnil("CNIL-16")
def test_tier_rules(base):
    pol, private, _share, c0 = base
    ds = generate(c0, 40, seed=1)
    rec = _assess(base, ds)
    assert rec["release_tier"] == LOCAL_ONLY and "not confirmed by a person" in rec["tier_reasons"][0]
    confirmed = copy.deepcopy(c0)
    confirm_all(confirmed)
    rec = _assess(base, generate(confirmed, 40, seed=1), confirmed)
    assert rec["release_tier"] == RESTRICTED
    assert rec["designated_columns"]["confirmed_by_a_person"] is True


@pytest.mark.cnil("CNIL-16")
@settings(max_examples=200, deadline=None)
@given(status=st.sampled_from(["passed", "failed", "none", "expired"]),
       crit=st.lists(st.sampled_from(["passed", "passed_with_residual_risk", "failed", "not_evaluable"]), min_size=4, max_size=4),
       confirmed=st.booleans(), policy=st.sampled_from(sorted(POLICIES)),
       attest=st.one_of(st.none(), st.just({"name": "A. Controller", "role": "DPO"})))
def test_tier_never_reaches_external_candidate_and_only_goes_down(status, crit, confirmed, policy, attest):
    criteria = {k: {"status": s} for k, s in zip(["singling_out", "linkability", "inference", "source_leakage"], crit)}
    contract = {"review": {"confirmed": confirmed}}
    tier, reasons = derive_tier(status, criteria, contract, get_policy(policy), attest)
    assert tier in (LOCAL_ONLY, RESTRICTED) and tier != EXTERNAL_CANDIDATE
    if status != "passed" or not confirmed:
        assert tier == LOCAL_ONLY and reasons
    # Removing the confirmation or failing the assessment can never raise the tier.
    worse, _ = derive_tier("failed", criteria, contract, get_policy(policy), attest)
    assert TIER_ORDER[worse] <= TIER_ORDER[tier]


@pytest.mark.cnil("CNIL-01")
def test_export_gate_refuses_a_higher_tier_and_has_no_override(base, tmp_path):
    ds = generate(base[3], 20, seed=1)
    rec = _assess(base, ds)
    data, ext, _ = render_dataset(base[3], ds)
    with pytest.raises(ExportRefused):
        export_bundle(str(tmp_path / "a"), dataset_bytes=data, dataset_ext=ext, documents={}, assessment=rec,
                      requested_tier=RESTRICTED)
    assert not os.path.exists(tmp_path / "a")
    forged = dict(rec, release_tier=EXTERNAL_CANDIDATE)
    with pytest.raises(ExportRefused):
        export_bundle(str(tmp_path / "b"), dataset_bytes=data, dataset_ext=ext, documents={}, assessment=forged)
    with pytest.raises(ExportRefused):
        export_bundle(str(tmp_path / "c"), dataset_bytes=data, dataset_ext=ext, documents={"../x.json": {}}, assessment=rec)
    ok = export_bundle(str(tmp_path / "d"), dataset_bytes=data, dataset_ext=ext, documents={}, assessment=rec,
                       requested_tier=LOCAL_ONLY)
    assert ok["release_tier"] == LOCAL_ONLY
    assert "LOCAL_ONLY" in open(tmp_path / "d" / "CLASSIFICATION.txt").read()


def test_skipped_assessment_is_local_only(tmp_path):
    res = run(SRC, policy_id="internal-dev", rows=10, seed=1, out_dir=str(tmp_path / "o"), skip_assessment=True)
    assert res.assessment["assessment_status"] == "none" and res.assessment["release_tier"] == LOCAL_ONLY


@pytest.mark.cnil("CNIL-14")
def test_expired_assessment_falls_back_to_local_only(base):
    confirmed = copy.deepcopy(base[3])
    confirm_all(confirmed)
    rec = _assess(base, generate(confirmed, 20, seed=1), confirmed)
    assert rec["review_by"] == "2027-05-15"  # 180 days under internal-dev
    assert effective_tier(rec, dt.date(2027, 5, 15)) == (RESTRICTED, "passed")
    assert effective_tier(rec, dt.date(2027, 5, 16)) == (LOCAL_ONLY, "expired")
    assert effective_tier({}, dt.date(2027, 1, 1))[0] == LOCAL_ONLY


@pytest.mark.cnil("CNIL-13")
@pytest.mark.cnil("CNIL-07")
def test_record_contents(base):
    rec = _assess(base, generate(base[3], 30, seed=1))
    for key in ("policy", "attacker_assumptions", "criteria", "residual_risk_statements", "limitations",
                "review_by", "date", "record_id", "statement", "information_flow", "designated_columns"):
        assert key in rec
    assert rec["attacker_assumptions"] and rec["policy"]["id"] == "internal-dev"
    assert "not a certification" in rec["statement"]
    assert set(rec["criteria"]) == {"singling_out", "linkability", "inference", "source_leakage"}
    partial = [k for k, v in rec["criteria"].items() if v["status"] == "passed_with_residual_risk"]
    assert len(rec["residual_risk_statements"]) >= len(partial)
    assert rec["information_flow"]["generator_inputs"] == ["Dataset Contract", "row counts", "seed"]


@pytest.mark.cnil("CNIL-15")
def test_release_register_is_written(tmp_path, monkeypatch):
    reg = tmp_path / "reg" / "register.jsonl"
    for seed in (1, 2):
        run(SRC, policy_id="internal-dev", rows=10, seed=seed, out_dir=str(tmp_path / f"o{seed}"), register_path=str(reg))
    lines = [json.loads(x) for x in reg.read_text().splitlines()]
    assert len(lines) == 2 and lines[0]["release_tier"] == LOCAL_ONLY
    assert lines[0]["record_id"] != lines[1]["record_id"] and "synthetic.csv" in lines[0]["files"]


@pytest.mark.cnil("CNIL-05")
def test_the_single_extreme_value_is_not_reproduced(tmp_path):
    """The CNIL page's own example: one very old person in a table of ordinary ages."""
    import random

    rng = random.Random(3)
    rows = ["person_ref,age,town"] + [f"P{i:05d},{rng.randint(20, 79)},T{rng.randint(1, 9)}" for i in range(2000)]
    rows[1500] = "P01499,104,T3"
    p = tmp_path / "ages.csv"
    p.write_text("\n".join(rows) + "\n")
    res = run(str(p), policy_id="external-strict", rows=200, seed=1, out_dir=str(tmp_path / "o"))
    out = (tmp_path / "o" / "synthetic.csv").read_text().splitlines()[1:]
    ages = [line.split(",")[1] for line in out]
    assert "104" not in ages
    cat = {e["class"]: e for e in res.source_report["exception_catalogue"] if e["column"] == "age"}
    assert cat["numeric.magnitude_outlier"]["count"] == "<10"  # the class is reported, the exact count is masked
    assert sum(1 for a in ages if len(a) == 3) >= 1  # the pattern (a three-digit age) is still represented
