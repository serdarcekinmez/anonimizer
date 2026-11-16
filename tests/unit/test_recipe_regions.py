"""Region detection candidates and user-corrected parse recipes."""

from __future__ import annotations

import pytest

from anonimizer.profile import build_profile
from anonimizer.recipe import ParseRecipe, RecipeError, propose_recipe
from tests.conftest import parser_path, product_path


def test_recipe_round_trip_and_candidates():
    rec, _src, regions = propose_recipe(product_path("orders_multi.tsv"))
    d = rec.to_dict()
    again = ParseRecipe.from_dict(d)
    assert again.to_dict() == d
    kinds = [(t["name"], t["kind"]) for t in d["tables"]]
    assert kinds == [("note_1", "note"), ("table_1", "table"), ("table_2", "table"), ("note_2", "note")]
    assert all(0 < r.confidence <= 1 for r in regions)


def test_user_can_move_the_header_and_boundaries(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("x,y\nid,amount\n1,10\n2,20\n3,30\nTOTAL,60\n")
    auto = build_profile(str(p))
    assert auto["tables"][0]["region"]["header_row"] == 1  # the automatic guess is wrong here
    recipe = ParseRecipe(tables=[{"name": "ledger", "header_row": 2, "first_data_row": 3, "last_data_row": 5,
                                  "first_col": 1, "last_col": 2}])
    fixed = build_profile(str(p), recipe)
    t = fixed["tables"][0]
    assert t["name"] == "ledger" and t["n_rows"] == 3
    assert [c["name"] for c in t["columns"]] == ["id", "amount"]
    assert [c["logical_type"] for c in t["columns"]] == ["integer", "integer"]
    assert fixed["detected_candidates"] is not None  # automatic candidates stay visible next to the user's choice


def test_user_can_exclude_a_region_and_leave_the_end_open(tmp_path):
    rec, _s, _r = propose_recipe(parser_path("two_tables_blank_sep.csv"))
    d = rec.to_dict()
    d["tables"][0]["include"] = False
    d["tables"][1]["last_data_row"] = None
    prof = build_profile(parser_path("two_tables_blank_sep.csv"), ParseRecipe.from_dict(d))
    assert [t["name"] for t in prof["tables"]] == ["table_2"] and prof["tables"][0]["n_rows"] == 3


def test_side_by_side_tables_can_be_merged_by_the_user():
    recipe = ParseRecipe(tables=[{"name": "wide", "header_row": 1, "first_data_row": 2, "last_data_row": 4,
                                  "first_col": 1, "last_col": 5}])
    prof = build_profile(parser_path("side_by_side.csv"), recipe)
    assert prof["tables"][0]["n_columns"] == 5
    assert prof["tables"][0]["columns"][2]["logical_type"] == "empty"


@pytest.mark.parametrize("tables,msg", [
    ([{"name": "a", "first_data_row": 2, "first_col": 1, "last_col": 2, "header_row": 5}], "above"),
    ([{"name": "a", "first_data_row": 2, "first_col": 3, "last_col": 2}], "left"),
    ([{"name": "a", "first_data_row": 0, "first_col": 1, "last_col": 2}], "positive integer"),
    ([{"name": "a", "first_data_row": 2, "first_col": 1, "last_col": 2, "sheet": "nope"}], "unknown sheet"),
    ([{"name": "a", "first_data_row": 2, "last_data_row": 4, "first_col": 1, "last_col": 2},
      {"name": "b", "first_data_row": 3, "last_data_row": 5, "first_col": 2, "last_col": 3}], "overlap"),
    ([{"name": "a", "first_data_row": 2, "last_data_row": 3, "first_col": 1, "last_col": 1},
      {"name": "a", "first_data_row": 5, "last_data_row": 6, "first_col": 1, "last_col": 1}], "unique"),
])
def test_invalid_recipes_are_rejected_with_a_reason(tables, msg):
    with pytest.raises(RecipeError) as exc:
        build_profile(parser_path("ragged.csv"), ParseRecipe(tables=tables))
    assert msg in str(exc.value)


def test_recipe_file_validation(tmp_path):
    bad = tmp_path / "r.json"
    bad.write_text("{not json")
    with pytest.raises(RecipeError):
        ParseRecipe.load(str(bad))
    with pytest.raises(RecipeError):
        ParseRecipe.from_dict({"recipe_version": 99})
    with pytest.raises(RecipeError):
        ParseRecipe.from_dict({"recipe_version": 1, "file": {"delimiter": "ab"}})


def test_low_confidence_detection_is_reported_as_ambiguity():
    prof = build_profile(parser_path("headerless_numeric.csv"))
    assert any("low confidence" in a["message"] for a in prof["ambiguities"])
    reg = prof["tables"][0]["region"]
    assert reg["confidence"] < 0.75 and any("no header" in n for n in reg["notes"])


def test_xlsx_regions_title_side_table_and_hidden_sheet():
    prof = build_profile(product_path("inventory_mixed.xlsx"))
    regs = {r["name"]: r for r in prof["regions"]}
    assert regs["note_1"]["kind"] == "note" and regs["note_1"]["first_data_row"] == 1
    assert (regs["Stock#1"]["header_row"], regs["Stock#1"]["last_data_row"], regs["Stock#1"]["last_col"]) == (3, 403, 8)
    assert (regs["Stock#2"]["first_col"], regs["Stock#2"]["last_col"], regs["Stock#2"]["last_data_row"]) == (11, 12, 7)
    assert regs["Archive"]["sheet"] == "Archive"
    assert any(e["class"] == "workbook.hidden_sheets" for e in prof["file_exceptions"])
