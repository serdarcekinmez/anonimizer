"""Generator and coverage planner."""

from __future__ import annotations

import copy

import pytest

from anonimizer.contract import build_contract
from anonimizer.patterns import BOOL_WORDS, DEFAULT_MARKERS, ERROR_CODES
from anonimizer.policy import get_policy
from anonimizer.profile import to_shareable
from anonimizer.synth import SynthError, generate, plan_table


@pytest.fixture(scope="module")
def contracts(profiles):
    pol = get_policy("internal-dev")
    return {name: build_contract(to_shareable(p, pol), pol) for name, p in profiles.items()}


def _rows(ds, table):
    return [r for r in ds["tables"][table]["rows"] if r["kind"] == "data"]


def _column(ds, table, cid):
    t = ds["tables"][table]
    j = t["columns"].index(cid)
    return [r["cells"][j] if j < len(r["cells"]) else None for r in _rows(ds, table)]


@pytest.mark.parametrize("n", [1, 2, 7, 31, 60, 250])
def test_requested_row_count_is_honoured(contracts, n):
    ds = generate(contracts["customers_hidden.csv"], n, seed=1)
    assert len(_rows(ds, "table_1")) == n
    cov = ds["coverage"]["tables"][0]
    assert cov["requested_rows"] == n and cov["generated_data_rows"] == n


def test_small_request_reports_what_is_left_out(contracts):
    ds = generate(contracts["customers_hidden.csv"], 5, seed=1)
    cov = ds["coverage"]["tables"][0]
    assert not cov["full_coverage"] and cov["scenarios_covered"] < cov["scenarios_total"]
    assert cov["n_min_packed"] <= cov["n_min_isolated"] and cov["n_min_packed"] > 5
    assert all(u["reason"] for u in cov["uncovered"])
    assert len(cov["covered"]) + len(cov["uncovered"]) == cov["scenarios_total"]
    covered_ids = {m["scenario_id"] for m in ds["manifest"]}
    assert covered_ids == set(cov["covered"])


def test_a_scenario_is_never_displaced_by_a_lower_priority_one(contracts):
    c = contracts["customers_hidden.csv"]
    ds = generate(c, 5, seed=1)
    by_id = {s["id"]: s for s in c["tables"][0]["scenarios"]}
    cov = ds["coverage"]["tables"][0]
    left = [by_id[u["id"]] for u in cov["uncovered"] if u["reason"] == "row budget too small"]
    assert left
    for u in left:
        same_slot = [by_id[i] for i in cov["covered"] if by_id[i]["column"] == u["column"]]
        assert all(s["priority"] <= u["priority"] for s in same_slot)


def test_enough_rows_gives_full_isolated_coverage(contracts):
    c = contracts["customers_hidden.csv"]
    need = plan_table(c["tables"][0], 10**6)["n_min_isolated"]
    ds = generate(c, need + 20, seed=3)
    cov = ds["coverage"]["tables"][0]
    assert cov["full_coverage"] and cov["max_scenarios_per_row"] == 1
    per_row: dict = {}
    for m in ds["manifest"]:
        if m["column"] is not None:
            for r in m["data_rows"]:
                per_row[r] = per_row.get(r, 0) + 1
    assert max(per_row.values()) == 1


def test_isolate_and_packed_modes(contracts):
    c = contracts["customers_hidden.csv"]
    iso = generate(c, 12, seed=1, packing="isolate")
    assert iso["coverage"]["tables"][0]["max_scenarios_per_row"] == 1
    packed = generate(c, 12, seed=1, packing="packed")
    assert packed["coverage"]["tables"][0]["scenarios_covered"] > iso["coverage"]["tables"][0]["scenarios_covered"]
    with pytest.raises(SynthError):
        generate(c, 12, packing="nonsense")


@pytest.mark.parametrize("rows", [0, -3, "ten", 10**9])
def test_invalid_row_counts(contracts, rows):
    with pytest.raises(SynthError):
        generate(contracts["customers_hidden.csv"], rows)


def test_unique_key_stays_unique_except_for_the_planned_duplicates(contracts):
    ds = generate(contracts["customers_hidden.csv"], 200, seed=5)
    ids = [c.text for c in _column(ds, "table_1", "c1") if c is not None and c.text]
    planned = [m for m in ds["manifest"] if m["class"] in ("key.duplicate", "row.duplicate")]
    assert planned and len(ids) - len(set(ids)) == sum(len(m["data_rows"]) for m in planned)


def test_references_point_at_generated_parent_keys(contracts):
    ds = generate(contracts["orders_multi.tsv"], 80, seed=2)
    parents = {c.text for c in _column(ds, "table_2", "c1") if c.text}
    dangling_rows = {r for m in ds["manifest"] if m["class"] == "key.dangling_reference" for r in m["data_rows"]}
    special = {r for m in ds["manifest"] if m["column"] == "c2" for r in m["data_rows"]} - dangling_rows
    refs = _column(ds, "table_1", "c2")
    assert dangling_rows
    for i, cell in enumerate(refs, start=1):
        if i in dangling_rows:
            assert cell.text not in parents
        elif i not in special:
            assert cell.text in parents
    mult = {m["note"] or m["scenario_id"]: m for m in ds["manifest"] if m["class"] == "key.multiplicity"}
    for m in mult.values():
        vals = {refs[r - 1].text for r in m["data_rows"]}
        assert len(vals) == 1
        times = sum(1 for cell in refs if cell.text in vals)
        label = m["scenario_id"].rsplit("/", 1)[-1]
        assert times == {"1": 1, "2": 2}.get(label, times) and (label != "3+" or times >= 3)


def test_only_public_literals_are_ever_copied(contracts):
    """Every 'literal' the generator may emit comes from the allowlist."""
    allowed = set(DEFAULT_MARKERS) | set(BOOL_WORDS) | {c.casefold() for c in ERROR_CODES}

    def walk(g):
        if isinstance(g, dict):
            if g.get("g") == "literal":
                assert g["value"].casefold() in allowed
            for v in g.values():
                walk(v)
        elif isinstance(g, list):
            for v in g:
                walk(v)

    for c in contracts.values():
        walk(c)


def test_dropped_columns_and_disabled_scenarios(contracts):
    c = copy.deepcopy(contracts["customers_hidden.csv"])
    t = c["tables"][0]
    t["columns"][5]["keep"] = False  # balance
    off = next(s for s in t["scenarios"] if s["class"] == "row.duplicate")
    off["enabled"] = False
    ds = generate(c, 80, seed=1)
    assert "balance" not in ds["tables"]["table_1"]["header"] and len(ds["tables"]["table_1"]["header"]) == 9
    reasons = {u["id"]: u["reason"] for u in ds["coverage"]["tables"][0]["uncovered"]}
    assert reasons[off["id"]] == "disabled in the contract"
    assert any("dropped" in r for r in reasons.values())
    assert not any(m["column"] == "c6" for m in ds["manifest"])


def test_pinned_scenario_survives_a_tiny_budget(contracts):
    c = copy.deepcopy(contracts["customers_hidden.csv"])
    first = generate(c, 3, seed=1)["coverage"]["tables"][0]
    left_out = next(u["id"] for u in first["uncovered"] if u["reason"] == "row budget too small")
    next(s for s in c["tables"][0]["scenarios"] if s["id"] == left_out)["pinned"] = True
    assert left_out in generate(c, 3, seed=1)["coverage"]["tables"][0]["covered"]


def test_secondary_tables_keep_their_size(contracts):
    ds = generate(contracts["inventory_mixed.xlsx"], 50, seed=1)
    counts = ds["params"]["rows"]
    assert counts["Stock#1"] == 50 and counts["Stock#2"] == 4 and counts["Archive"] == 3 and counts["Suppliers"] == 41
    ds = generate(contracts["inventory_mixed.xlsx"], {"*": 50, "Suppliers": 12}, seed=1)
    assert ds["params"]["rows"]["Suppliers"] == 12


def test_first_data_row_is_an_ordinary_row(contracts):
    for seed in range(8):
        ds = generate(contracts["customers_hidden.csv"], 60, seed=seed)
        flagged = {r for m in ds["manifest"] for r in m["data_rows"]}
        assert 1 not in flagged


def test_synthetic_emails_use_reserved_domains(contracts):
    ds = generate(contracts["customers_hidden.csv"], 80, seed=4)
    emails = [c.text.strip() for c in _column(ds, "table_1", "c3") if c is not None and "@" in (c.text or "")]
    assert emails and all(e.split("@")[1] in ("example.com", "example.org", "example.net") for e in emails)


# ASTRA-04: a zero in scientific notation is a zero, in scenarios and in ordinary rows.
def _sci_contract(tmp_path, with_zero_rows=1):
    from anonimizer.pipeline import profile_source
    from anonimizer.recipe import ParseRecipe

    vals = [f"{(i % 9) + 1}.{(i * 7) % 100:02d}E+{(i % 7) + 2:02d}" for i in range(50 - with_zero_rows)]
    vals += ["0.00E+00"] * with_zero_rows
    p = tmp_path / "sci.csv"
    p.write_text("id,measure\n" + "".join(f"{i + 1},{v}\n" for i, v in enumerate(vals)), encoding="utf-8")
    pol = get_policy("internal-dev")
    _private, share = profile_source(str(p), ParseRecipe(), pol)
    return str(p), build_contract(share, pol)


def _is_zero(text):
    return float(text) == 0.0


def test_scientific_zero_scenario_is_zero(tmp_path):
    _p, c = _sci_contract(tmp_path)
    assert any(s["class"] == "numeric.zero" for s in c["tables"][0]["scenarios"])
    for seed in range(8):
        ds = generate(c, 50, seed=seed)
        cells = _column(ds, "table_1", "c2")
        zero_rows = [r for e in ds["manifest"] if e["class"] == "numeric.zero" for r in e["data_rows"]]
        assert zero_rows, seed
        for r in zero_rows:
            assert _is_zero(cells[r - 1].text), (seed, r)


def test_scientific_zero_in_ordinary_rows_is_zero(tmp_path):
    _p, c = _sci_contract(tmp_path, with_zero_rows=15)  # common: also drawn in ordinary rows
    ds = generate(c, 200, seed=4)
    texts = [x.text for x in _column(ds, "table_1", "c2") if x is not None and x.text]
    zeros = [t for t in texts if t.startswith("0.")]
    assert zeros and all(_is_zero(t) for t in zeros)
