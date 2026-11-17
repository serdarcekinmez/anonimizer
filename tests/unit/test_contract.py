"""Dataset Contract: built from the shareable profile only, validated, explicit human decisions."""

from __future__ import annotations

import copy
import json

import pytest

from anonimizer.contract import (
    ContractError,
    approve_categories,
    build_contract,
    confirm_contract,
    find_column,
    validate_contract,
)
from anonimizer.policy import PolicyError, get_policy
from anonimizer.profile import to_shareable


@pytest.fixture()
def contract(profiles):
    pol = get_policy("internal-dev")
    return build_contract(to_shareable(profiles["customers_hidden.csv"], pol), pol)


def test_contract_cannot_be_built_from_the_private_profile(profiles):
    with pytest.raises(ContractError):
        build_contract(profiles["customers_hidden.csv"], get_policy("internal-dev"))


def test_policy_must_be_explicit():
    with pytest.raises(PolicyError):
        get_policy(None)
    with pytest.raises(PolicyError):
        get_policy("default")


def test_contract_holds_no_source_values(contract, truths):
    text = json.dumps(contract, ensure_ascii=False)
    for canary in truths["customers_hidden.csv"]["canaries"]:
        assert canary not in text
    for value in ("active", "inactive", "example.org", "Prefers contact", "100001"):
        assert value not in text


def test_contract_round_trips_and_validates(contract):
    again = json.loads(json.dumps(contract))
    assert again == contract
    assert validate_contract(again).id == "internal-dev"


@pytest.mark.cnil("CNIL-04")
def test_every_column_carries_a_keep_decision_and_a_sensitivity_class(contract):
    for col in contract["tables"][0]["columns"]:
        assert col["keep"] is True and col["sensitivity"]["confirmed"] is False
    c = copy.deepcopy(contract)
    c["tables"][0]["columns"][0]["keep"] = None
    with pytest.raises(ContractError):
        validate_contract(c)


def test_unapproved_literal_values_are_rejected(contract):
    c = copy.deepcopy(contract)
    c["tables"][0]["columns"][7]["base_gen"] = {"g": "literal", "value": "Jane Doe"}
    with pytest.raises(ContractError) as exc:
        validate_contract(c)
    assert "Jane Doe" not in str(exc.value)
    c = copy.deepcopy(contract)
    c["tables"][0]["columns"][7]["base_gen"] = {"g": "category", "values": ["active"], "weights": [1]}
    with pytest.raises(ContractError):
        validate_contract(c)


@pytest.mark.cnil("ANON-03")
def test_number_formats_with_literal_text_are_rejected(contract):
    """ASTRA-02: an edited contract cannot carry text inside a number format to the output."""
    for path, fmt in ((("number_format",), '0.00" Firm"'),
                      (("base_gen", "number_format"), "[$Firm-409]yyyy-mm-dd")):
        c = copy.deepcopy(contract)
        col = c["tables"][0]["columns"][0]
        target = col
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = fmt
        with pytest.raises(ContractError) as exc:
            validate_contract(c)
        assert "Firm" not in str(exc.value) and "number format" in str(exc.value)
    c = copy.deepcopy(contract)
    c["tables"][0]["columns"][0]["number_format"] = "#,##0.00"
    validate_contract(c)


@pytest.mark.cnil("CNIL-05")
def test_category_approval_needs_a_person_and_respects_the_policy(contract, profiles):
    private = profiles["customers_hidden.csv"]
    with pytest.raises(ContractError):
        approve_categories(contract, private, "table_1", "country", "")
    col = approve_categories(contract, private, "table_1", "country", "Data Owner")
    vals = col["base_gen"]["values"]
    assert set(vals) == {"FR", "DE", "ES", "IT", "TR", "NL", "BE", "PT"}  # the value seen once is not copied
    assert "fr" not in vals and col["base_gen"]["other"]["size"] == 1
    assert col["value_policy"]["approved_by"] == "Data Owner"
    validate_contract(contract)
    with pytest.raises(ContractError):
        approve_categories(contract, private, "table_1", "email", "Data Owner")


def test_strict_policy_refuses_small_categories(profiles):
    pol = get_policy("external-strict")
    c = build_contract(to_shareable(profiles["orders_multi.tsv"], pol), pol)
    col = approve_categories(c, profiles["orders_multi.tsv"], "table_1", "channel", "Data Owner")
    assert set(col["base_gen"]["values"]) == {"web", "store", "phone"}
    with pytest.raises(ContractError):
        approve_categories(c, profiles["orders_multi.tsv"], "table_2", "city", "Data Owner")


@pytest.mark.cnil("CNIL-06")
def test_confirmation_requires_every_kept_column_to_be_reviewed(contract):
    with pytest.raises(ContractError) as exc:
        confirm_contract(contract, "Reviewer")
    assert "unreviewed" in str(exc.value)
    for col in contract["tables"][0]["columns"]:
        if col["sensitivity"]["class"] == "unreviewed":
            col["keep"] = False  # dropping a column is an accepted decision
    confirm_contract(contract, "Reviewer")
    assert contract["review"]["confirmed"] and contract["review"]["confirmed_by"] == "Reviewer"
    with pytest.raises(ContractError):
        confirm_contract(contract, "  ")


def test_find_column_by_id_or_name(contract):
    assert find_column(contract, "table_1", "c6")["name"] == "balance"
    assert find_column(contract, "table_1", "balance")["id"] == "c6"
    with pytest.raises(ContractError):
        find_column(contract, "table_1", "nope")


# ASTRA-05: one naming layer for the interface and the command line.
from anonimizer.contract import apply_naming, plan_names, sequence_name  # noqa: E402


def test_sequence_names_continue_past_the_alphabet():
    assert [sequence_name(i) for i in (0, 1, 2, 23, 24, 25)] == ["Alpha", "Beta", "Gamma", "Omega", "Alpha2", "Beta2"]


def test_plan_names_modes_and_partial_lists():
    cols = [("c1", "Customer Name"), ("c2", "Birth Date"), ("c3", "City")]
    assert [p["new"] for p in plan_names(cols, mode="sequence")] == ["Alpha", "Beta", "Gamma"]
    assert [p["new"] for p in plan_names(cols, mode="sequence", style="lower", prefix="col_")] == \
        ["col_alpha", "col_beta", "col_gamma"]
    assert [p["new"] for p in plan_names(cols, mode="list", names=["a", "", "  c  "])] == ["a", "Birth Date", "c"]
    assert [p["new"] for p in plan_names(cols, mode="edit", style="snake")] == ["customer_name", "birth_date", "city"]
    assert [p["new"] for p in plan_names(cols, mode="edit", find=" ", replace="-", style="upper")] == \
        ["CUSTOMER-NAME", "BIRTH-DATE", "CITY"]
    plan = plan_names(cols, mode="list", names=["x", "Birth Date", "z"])
    assert [p["changed"] for p in plan] == [True, False, True]


@pytest.mark.parametrize("kwargs,needle", [
    ({"mode": "list", "names": ["a", "b"]}, "2 name(s) were given for 3 selected column(s)"),
    ({"mode": "list", "names": ["a", "b", "c", "d"]}, "4 name(s) were given for 3 selected column(s)"),
    ({"mode": "list", "names": ["a", "a", "b"]}, "would repeat"),
    ({"mode": "list", "names": ["Other", "b", "c"]}, "would repeat"),
    ({"mode": "edit", "find": "Name", "replace": "", "prefix": "", "style": ""}, None),
    ({"mode": "list", "names": ["x" * 301, "b", "c"]}, "at most 300"),
    ({"mode": "spell"}, "unknown naming mode"),
    ({"mode": "edit", "style": "camel"}, "unknown spelling"),
])
def test_plan_names_rejects_with_a_clear_message(kwargs, needle):
    cols = [("c1", "Customer Name"), ("c2", "Birth Date"), ("c3", "City")]
    if needle is None:
        assert plan_names(cols, others=["Other"], **kwargs)[0]["new"] == "Customer "
        return
    with pytest.raises(ContractError) as exc:
        plan_names(cols, others=["Other"], **kwargs)
    assert needle in str(exc.value)
    assert "Customer" not in str(exc.value) and "Birth" not in str(exc.value)  # ids and counts only


def test_apply_naming_on_selected_or_all_kept_columns(contract):
    c = copy.deepcopy(contract)
    c["tables"][0]["columns"][1]["keep"] = False
    kept = [col for col in c["tables"][0]["columns"] if col["keep"]]
    plan = apply_naming(c, {"columns": [("table_1", "c3"), ("table_1", "c1")], "mode": "list", "names": ["First", "Third"]})
    assert [(p["id"], p["new"]) for p in plan] == [("c1", "First"), ("c3", "Third")]  # table order, not typing order
    assert find_column(c, "table_1", "c1")["name"] == "First" and find_column(c, "table_1", "c3")["name"] == "Third"
    plan = apply_naming(c, {"mode": "sequence"})
    assert len(plan) == len(kept) and find_column(c, "table_1", "c1")["name"] == "Alpha"
    assert find_column(c, "table_1", "c2")["name"] == contract["tables"][0]["columns"][1]["name"]  # not kept: untouched
    with pytest.raises(ContractError) as exc:
        apply_naming(c, {"columns": [("table_1", "c2")], "mode": "sequence"})
    assert "not kept" in str(exc.value)
    validate_contract(c)
