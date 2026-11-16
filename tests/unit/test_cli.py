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
