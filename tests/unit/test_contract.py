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
