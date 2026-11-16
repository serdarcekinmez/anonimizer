"""Profiler behaviour that the Exception Catalogue depends on."""

from __future__ import annotations

import json

import anonimizer.profile as profile_mod
from anonimizer.policy import get_policy
from anonimizer.profile import build_profile, iter_exceptions, to_shareable
from anonimizer.recipe import ParseRecipe
from tests.conftest import product_path


def _col(prof, name, table=0):
    return next(c for c in prof["tables"][table]["columns"] if c["name"] == name)


def _classes(col):
    out = {}
    for e in col["exceptions"]:
        out[e["class"]] = out.get(e["class"], 0) + e["count"]
    return out


def _write(tmp_path, text, name="t.csv"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_null_like_values_are_counted_separately(tmp_path):
    rows = ["id,v"] + [f"{i},{i * 3}" for i in range(1, 41)]
    rows += ["41,", '42,""', "43,  ", "44,N/A", "45,NaN", "46,null", "47,-", "48,0", "49,0", "50"]
    prof = build_profile(_write(tmp_path, "\n".join(rows) + "\n"))
    c = _col(prof, "v")
    assert c["missing"] == {"absent": 1, "empty": 1, "quoted_empty": 1, "whitespace": 1}
    assert c["markers"] == {"-": 1, "N/A": 1, "NaN": 1, "null": 1}
    assert c["number"]["zero"] == 2 and c["logical_type"] == "integer"
    cls = _classes(c)
    assert cls["numeric.zero"] == 2 and cls["missing.marker"] == 4 and cls["missing.quoted_empty"] == 1
    assert prof["tables"][0]["row_exceptions"][0]["class"] == "row.ragged_short"


def test_user_defined_marker(tmp_path):
    rows = ["id,v"] + [f"{i},{i}" for i in range(1, 30)] + ["30,sans objet"]
    path = _write(tmp_path, "\n".join(rows) + "\n")
    assert "type.text_in_number" in _classes(_col(build_profile(path), "v"))
    prof = build_profile(path, ParseRecipe(extra_markers=["sans objet"]))
    assert _col(prof, "v")["markers"] == {"sans objet": 1}


def test_day_month_order_is_resolved_from_the_column(tmp_path):
    rows = ["d"] + ["05/01/2024"] * 20 + ["25/01/2024"]
    c = _col(build_profile(_write(tmp_path, "\n".join(rows) + "\n")), "d")
    assert c["date"]["order"] == "DMY" and c["date"]["dominant_format"] == "D/M/Y"
    rows = ["d"] + ["05/01/2024"] * 20
    prof = build_profile(_write(tmp_path, "\n".join(rows) + "\n", "u.csv"))
    assert _col(prof, "d")["date"]["order"] == "ambiguous"
    assert any("day/month order" in a["message"] for a in prof["ambiguities"])
    rows = ["d"] + ["25/01/2024"] * 20 + ["01/25/2024"]
    c = _col(build_profile(_write(tmp_path, "\n".join(rows) + "\n", "c.csv")), "d")
    assert _classes(c).get("format.date_order_conflict") == 1


def test_thousands_versus_decimal_comma_uses_context(tmp_path):
    rows = ['"12,5"'] * 20 + ['"1,234"']
    c = _col(build_profile(_write(tmp_path, "v\n" + "\n".join(rows) + "\n")), "v")
    assert c["number"]["comma_resolution"] == "decimal_comma" and c["logical_type"] == "decimal"
    rows = ['"1,234,567"'] * 20 + ['"1,234"']
    c = _col(build_profile(_write(tmp_path, "v\n" + "\n".join(rows) + "\n", "k.csv")), "v")
    assert c["number"]["comma_resolution"] == "thousands_separator"


def test_leading_zero_codes_are_not_treated_as_integers(tmp_path):
    rows = ["zip"] + [f"0{1000 + i}" for i in range(30)]
    c = _col(build_profile(_write(tmp_path, "\n".join(rows) + "\n")), "zip")
    assert c["logical_type"] == "digit_code"


def test_mixed_column_is_reported_as_ambiguous(tmp_path):
    rows = ["v"] + ["12"] * 10 + ["abc"] * 9 + ["2024-01-01"] * 8
    prof = build_profile(_write(tmp_path, "\n".join(rows) + "\n"))
    assert _col(prof, "v")["logical_type"] == "mixed"
    assert any("mixed" in a["message"] for a in prof["ambiguities"])


def test_distinct_tracking_modes_agree(tmp_path, monkeypatch):
    rows = ["k"] + [f"K{i:05d}" for i in range(3000)] + ["K00007", "K00007", "K01234"]
    path = _write(tmp_path, "\n".join(rows) + "\n")
    base = _col(build_profile(path), "k")["distinct"]
    assert base["n_distinct"] == 3000 and base["extra_occurrences"] == 3 and base["max_multiplicity"] == 3
    monkeypatch.setattr(profile_mod, "CAT_CAP", 10)
    assert _col(build_profile(path), "k")["distinct"] == base
    monkeypatch.setattr(profile_mod, "HASH_CAP", 50)
    assert _col(build_profile(path), "k")["distinct"] == base


def test_private_profile_has_row_numbers_and_shareable_has_none(profiles):
    private = profiles["customers_hidden.csv"]
    ex = next(e for e in iter_exceptions(private) if e["class"] == "type.text_in_number" and e["column_name"] == "balance")
    assert ex["_private"]["rows"] == [4877]
    share = to_shareable(private, get_policy("internal-dev"))
    text = json.dumps(share)
    assert "_private" not in text and "category_values" not in text and "exact_shapes" not in text
    assert share["view"] == "shareable" and share["policy"]["id"] == "internal-dev"


def test_strict_policy_masks_small_counts_and_rounds_years(profiles):
    share = to_shareable(profiles["customers_hidden.csv"], get_policy("external-strict"))
    ex = next(e for e in iter_exceptions(share) if e["class"] == "type.text_in_number" and e["column_name"] == "balance")
    assert ex["count"] is None and ex["count_display"] == "<10"
    d = _col(share, "signup_date")["date"]
    assert d["year_min"] % 5 == 0 and d["year_max"] % 5 == 0 and d["year_min"] <= 2015 and d["year_max"] >= 2023


def test_rare_layouts_are_generalised_before_they_reach_the_contract(profiles):
    share = to_shareable(profiles["customers_hidden.csv"], get_policy("internal-dev"))
    ex = next(e for e in iter_exceptions(share) if e["class"] == "text.rare_pattern" and e["column_name"] == "full_name")
    assert ex["gen"]["g"] == "text_gshape" and all(len(item) == 3 for item in ex["gen"]["shape"])


def test_sensitivity_hints_are_proposals_from_names_and_patterns(profiles):
    p = profiles["customers_hidden.csv"]
    hints = {c["name"]: c["sensitivity_hint"]["class"] for c in p["tables"][0]["columns"]}
    assert hints["email"] == "direct_identifier" and hints["full_name"] == "direct_identifier"
    assert hints["country"] == "quasi_identifier" and hints["customer_id"] == "direct_identifier"
    assert hints["balance"] == "unreviewed"


def test_key_roles_and_reference(profiles):
    p = profiles["orders_multi.tsv"]
    orders, custs = p["tables"]
    assert _col(p, "order_no")["key"]["role"] == "unique"
    ref = _col(p, "customer_ref")["key"]
    assert ref["role"] == "reference" and ref["references"]["table"] == custs["name"]
    assert _col(p, "customer_code", 1)["key"]["role"] == "unique"
    assert orders["name"] == "table_1" and p["relationships"][0]["dangling_rows"] == 2
