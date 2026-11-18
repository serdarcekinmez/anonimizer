"""Golden parser fixtures: detection results against hand-written expectations."""

from __future__ import annotations

import json
import os

import pytest

from anonimizer.profile import build_profile
from tests.conftest import PARSER

with open(os.path.join(os.path.dirname(__file__), "expected_parser.json"), encoding="utf-8") as _fh:
    EXPECTED = {k: v for k, v in json.load(_fh).items() if not k.startswith("_")}


def test_every_parser_fixture_has_an_expectation():
    files = {f for f in os.listdir(PARSER) if not f.endswith(".py")}
    assert files == set(EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_parser_golden(name):
    exp = EXPECTED[name]
    p = build_profile(os.path.join(PARSER, name))
    src = p["source"]
    if "delimiter" in exp:
        assert src["delimiter"]["delimiter"] == exp["delimiter"]
    if "encoding" in exp:
        assert src["encoding"]["encoding"] == exp["encoding"]
    if "bom" in exp:
        assert src["encoding"]["bom"] == exp["bom"]
    if "undecodable_bytes" in exp:
        assert src["encoding"]["undecodable_bytes"] == exp["undecodable_bytes"]
    for key in ("records", "physical_lines", "newlines"):
        if key in exp:
            assert src[key] == exp[key]
    assert len(p["tables"]) == len(exp["tables"])
    for tab, et in zip(p["tables"], exp["tables"]):
        reg = tab["region"]
        for key in ("header_row", "first_data_row", "last_data_row", "first_col", "last_col"):
            if key in et:
                assert reg[key] == et[key], f"{name}: {key}"
        assert tab["n_rows"] == et["rows"]
        if "names" in et:
            assert [c["name"] for c in tab["columns"]] == et["names"]
        if "types" in et:
            assert [c["logical_type"] for c in tab["columns"]] == et["types"]
        if "intro_rows" in et:
            assert len(tab["preamble"]) == et["intro_rows"]
        if "row_classes" in et:
            got: dict = {}
            for e in tab["row_exceptions"]:
                got[e["class"]] = got.get(e["class"], 0) + e["count"]
            assert got == et["row_classes"]
        for cname, classes in et.get("classes", {}).items():
            col = next(c for c in tab["columns"] if c["name"] == cname)
            got = {e["class"]: e["count"] for e in col["exceptions"]}
            for cls, n in classes.items():
                assert got.get(cls) == n, f"{name}: {cname} {cls}"
    if "file_classes" in exp:
        assert sorted(e["class"] for e in p["file_exceptions"]) == sorted(exp["file_classes"])
