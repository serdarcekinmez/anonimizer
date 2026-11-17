"""Command line behaviour and exit codes."""

from __future__ import annotations

import json

import pytest

from anonimizer.cli import main
from tests.conftest import parser_path, product_path


def test_inspect_writes_an_editable_recipe(tmp_path, capsys):
    out = tmp_path / "recipe.json"
    assert main(["inspect", product_path("orders_multi.tsv"), "--recipe-out", str(out)]) == 0
    recipe = json.loads(out.read_text())
    assert [t["name"] for t in recipe["tables"]] == ["note_1", "table_1", "table_2", "note_2"]
    printed = capsys.readouterr().out
    assert "cp1252" in printed and "table_2" in printed
    recipe["tables"][2]["name"] = "clients"
    out.write_text(json.dumps(recipe))
    assert main(["profile", product_path("orders_multi.tsv"), "--policy", "internal-dev", "--recipe", str(out)]) == 0
    assert "Table clients" in capsys.readouterr().out


def test_policy_is_mandatory(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["generate", product_path("customers_hidden.csv"), "-n", "5", "--out", "x"])
    assert exc.value.code == 2 and "--policy" in capsys.readouterr().err


def test_generate_with_decisions_reaches_restricted(tmp_path, capsys):
    out = tmp_path / "o"
    args = ["generate", parser_path("two_tables_blank_sep.csv"), "--policy", "internal-dev", "-n", "12", "--seed", "9",
            "--out", str(out), "--sensitivity", "table_1.name=direct_identifier",
            "--sensitivity", "table_2.price=non_sensitive", "--sensitivity", "table_2.stock=non_sensitive",
            "--confirm-contract", "A. Reviewer", "--tier", "RESTRICTED", "--private-dir", str(tmp_path / "priv")]
    assert main(args) == 0
    printed = capsys.readouterr().out
    assert "release tier: RESTRICTED" in printed
    label = json.loads((out / "release_label.json").read_text())
    assert label["release_tier"] == "RESTRICTED" and "RESTRICTED" in (out / "CLASSIFICATION.txt").read_text()
    contract = json.loads((out / "contract.json").read_text())
    assert contract["review"]["confirmed_by"] == "A. Reviewer"
    assert (tmp_path / "priv" / "source_profile.PRIVATE.json").exists()
    assert main(["check-record", str(out / "assessment_record.json")]) == 0
    assert "tier in force today: RESTRICTED" in capsys.readouterr().out


def test_contract_file_round_trip_and_policy_mismatch(tmp_path, capsys):
    cpath = tmp_path / "c.json"
    src = product_path("customers_hidden.csv")
    assert main(["contract", src, "--policy", "internal-dev", "-o", str(cpath)]) == 0
    c = json.loads(cpath.read_text())
    c["tables"][0]["columns"][9]["keep"] = False
    cpath.write_text(json.dumps(c))
    assert main(["generate", src, "--policy", "internal-dev", "-n", "20", "--contract", str(cpath),
                 "--out", str(tmp_path / "o")]) == 0
    header = (tmp_path / "o" / "synthetic.csv").read_text().splitlines()[0]
    assert header.split(",")[-1] == "last_contact"
    assert main(["generate", src, "--policy", "external-strict", "-n", "20", "--contract", str(cpath),
                 "--out", str(tmp_path / "o2")]) == 2
    assert "different policy" in capsys.readouterr().err


@pytest.mark.parametrize("extra,code", [
    (["--tier", "RESTRICTED"], 4),
    (["--tier", "EXTERNAL_CANDIDATE"], 4),
    (["--require-full-coverage"], 3),
    (["--confirm-contract", "X"], 2),
    (["--drop", "table_1.nope"], 2),
    (["--keep-categories", "table_1.status"], 2),
    (["--rows-for", "table_1"], 2),
])
def test_exit_codes(tmp_path, extra, code, capsys):
    args = ["generate", product_path("customers_hidden.csv"), "--policy", "internal-dev", "-n", "4",
            "--out", str(tmp_path / "o")] + extra
    assert main(args) == code
    capsys.readouterr()


def test_missing_and_unsupported_inputs(tmp_path, capsys):
    assert main(["inspect", str(tmp_path / "nope.csv")]) == 2
    legacy = tmp_path / "old.xls"
    legacy.write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 32)
    assert main(["profile", str(legacy), "--policy", "internal-dev"]) == 2
    err = capsys.readouterr().err
    assert "error:" in err and "Traceback" not in err


def test_empty_file_is_handled(tmp_path, capsys):
    assert main(["generate", parser_path("empty.csv"), "--policy", "internal-dev", "-n", "5", "--out", str(tmp_path / "o")]) == 0
    assert (tmp_path / "o" / "synthetic.csv").read_bytes() == b""
    capsys.readouterr()


def test_keep_categories_and_drop(tmp_path, capsys):
    out = tmp_path / "o"
    assert main(["generate", product_path("customers_hidden.csv"), "--policy", "internal-dev", "-n", "60", "--out", str(out),
                 "--keep-categories", "status", "--approved-by", "Data Owner", "--drop", "notes",
                 "--delimiter", ","]) == 0
    lines = (out / "synthetic.csv").read_text().splitlines()
    assert "notes" not in lines[0]
    statuses = {line.split(",")[7] for line in lines[1:] if len(line.split(",")) > 7}
    assert {"active", "inactive", "pending"} <= statuses
    rec = json.loads((out / "assessment_record.json").read_text())
    approved = rec["criteria"]["inference"]["metrics"]["columns_with_approved_literals"]
    assert approved[0]["column"] == "status" and approved[0]["approved_by"] == "Data Owner"
    capsys.readouterr()


def test_policies_command(capsys):
    assert main(["policies"]) == 0
    out = capsys.readouterr().out
    assert "internal-dev" in out and "external-strict" in out


# ASTRA-01: the output of a run never replaces the source or an existing file.

def _source_dir(tmp_path):
    """A synthetic source file alone in its own directory."""
    d = tmp_path / "data"
    d.mkdir()
    src = d / "synthetic.csv"
    src.write_text("id,amount\n" + "".join(f"{i},{i * 3}.5\n" for i in range(1, 51)), encoding="utf-8")
    return d, src


def _gen(src, out, *extra):
    return main(["generate", str(src), "--policy", "internal-dev", "-n", "7", "--out", str(out), *extra])


def test_output_into_the_source_directory_is_refused_and_the_source_is_unchanged(tmp_path, capsys):
    d, src = _source_dir(tmp_path)
    before = src.read_bytes()
    assert _gen(src, d) == 4
    assert src.read_bytes() == before
    assert sorted(p.name for p in d.iterdir()) == ["synthetic.csv"]
    err = capsys.readouterr().err
    assert "refused" in err and "new or empty directory" in err and "synthetic" not in err


def test_output_onto_the_source_file_itself_is_refused(tmp_path, capsys):
    _d, src = _source_dir(tmp_path)
    before = src.read_bytes()
    assert _gen(src, src) == 4
    assert src.read_bytes() == before
    capsys.readouterr()


def test_a_second_run_into_the_same_directory_is_refused_and_the_first_bundle_is_kept(tmp_path, capsys):
    _d, src = _source_dir(tmp_path)
    out = tmp_path / "o"
    assert _gen(src, out) == 0
    first = {p.name: p.read_bytes() for p in out.iterdir()}
    assert _gen(src, out, "--seed", "2") == 4
    assert {p.name: p.read_bytes() for p in out.iterdir()} == first
    capsys.readouterr()


def test_an_existing_empty_directory_is_accepted(tmp_path, capsys):
    _d, src = _source_dir(tmp_path)
    out = tmp_path / "empty"
    out.mkdir()
    assert _gen(src, out) == 0
    assert (out / "synthetic.csv").exists() and (out / "report.md").exists()
    capsys.readouterr()


def test_a_symbolic_link_to_the_source_directory_is_refused(tmp_path, capsys):
    d, src = _source_dir(tmp_path)
    before = src.read_bytes()
    link = tmp_path / "link"
    link.symlink_to(d, target_is_directory=True)
    assert _gen(src, link) == 4
    assert src.read_bytes() == before and sorted(p.name for p in d.iterdir()) == ["synthetic.csv"]
    capsys.readouterr()


def test_an_existing_private_profile_is_not_overwritten(tmp_path, capsys):
    _d, src = _source_dir(tmp_path)
    priv = tmp_path / "priv"
    priv.mkdir()
    old = priv / "source_profile.PRIVATE.json"
    old.write_text("{}", encoding="utf-8")
    assert _gen(src, tmp_path / "o", "--private-dir", str(priv)) == 4
    assert old.read_text(encoding="utf-8") == "{}"
    assert not (tmp_path / "o").exists()  # refused before anything was written
    capsys.readouterr()


@pytest.mark.parametrize("command", [["contract", "--policy", "internal-dev", "-o"], ["inspect", "--recipe-out"]])
def test_single_file_outputs_never_replace_the_source(tmp_path, command, capsys):
    _d, src = _source_dir(tmp_path)
    before = src.read_bytes()
    assert main([command[0], str(src), *command[1:], str(src)]) == 4
    assert src.read_bytes() == before
    capsys.readouterr()


def test_profile_outputs_never_replace_the_source(tmp_path, capsys):
    d = tmp_path / "data"
    d.mkdir()
    src = d / "source_report.json"  # a CSV that happens to carry the report's file name
    src.write_text("id,amount\n" + "".join(f"{i},{i}\n" for i in range(1, 21)), encoding="utf-8")
    before = src.read_bytes()
    assert main(["profile", str(src), "--policy", "internal-dev", "--out", str(d)]) == 4
    assert src.read_bytes() == before
    capsys.readouterr()


# ASTRA-05: naming from the command line, with a preview.
def test_names_preview_prints_the_plan_and_writes_nothing(tmp_path, capsys):
    out = tmp_path / "o"
    code = main(["generate", product_path("customers_hidden.csv"), "--policy", "internal-dev", "-n", "5",
                 "--out", str(out), "--names-sequence", "--names-for", "c1", "--names-for", "c3", "--names-preview"])
    assert code == 0 and not out.exists()
    printed = capsys.readouterr().out
    assert "Alpha" in printed and "Beta" in printed and "2 column name(s) would change" in printed


def test_names_list_file_renames_selected_columns_in_the_output(tmp_path, capsys):
    names = tmp_path / "names.txt"
    names.write_text("First\n\nThird\n", encoding="utf-8")
    out = tmp_path / "o"
    assert main(["generate", product_path("customers_hidden.csv"), "--policy", "internal-dev", "-n", "5",
                 "--out", str(out), "--names-list", str(names), "--names-for", "c1", "--names-for", "c2",
                 "--names-for", "c3", "--rename", "c4=Fourth"]) == 0
    header = (out / "synthetic.csv").read_text(encoding="utf-8").splitlines()[0].split(",")
    contract = json.loads((out / "contract.json").read_text(encoding="utf-8"))
    original = [c["name"] for c in contract["tables"][0]["columns"]]
    assert header[0] == "First" and header[2] == "Third" and header[3] == "Fourth" and header[1] == original[1]
    capsys.readouterr()


def test_names_list_length_mismatch_is_an_input_error(tmp_path, capsys):
    names = tmp_path / "names.txt"
    names.write_text("A\nB\n", encoding="utf-8")
    assert main(["generate", product_path("customers_hidden.csv"), "--policy", "internal-dev", "-n", "5",
                 "--out", str(tmp_path / "o"), "--names-list", str(names)]) == 2
    err = capsys.readouterr().err
    assert "2 name(s) were given for 10 selected column(s)" in err and not (tmp_path / "o").exists()


def test_contract_command_applies_names_too(tmp_path, capsys):
    cpath = tmp_path / "c.json"
    assert main(["contract", product_path("orders_multi.tsv"), "--policy", "internal-dev", "-o", str(cpath),
                 "--names-sequence", "--names-table", "table_2"]) == 0
    c = json.loads(cpath.read_text(encoding="utf-8"))
    t2 = next(t for t in c["tables"] if t["name"] == "table_2")
    t1 = next(t for t in c["tables"] if t["name"] == "table_1")
    assert t2["columns"][0]["name"] == "Alpha" and t1["columns"][0]["name"] != "Alpha"
    capsys.readouterr()
