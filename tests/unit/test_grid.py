"""Lossless readers: CSV quoting and emptiness kinds, XLSX storage types, untrusted input."""

from __future__ import annotations

import io
import os
import zipfile

import openpyxl
import pytest

from anonimizer.grid import GridError, open_source
from anonimizer.grid.model import ABSENT, EMPTY, QUOTED_EMPTY, WHITESPACE
from tests.conftest import product_path


def _csv(tmp_path, text: str, name="a.csv", **kw):
    p = tmp_path / name
    p.write_bytes(text.encode(kw.pop("encoding", "utf-8")))
    return open_source(str(p), **kw)


def test_csv_emptiness_kinds_are_distinct(tmp_path):
    src = _csv(tmp_path, 'a,b,c,d\n1,,"",  \n2\n')
    rows = list(src.rows())
    r = rows[1]
    assert [r.cell(i).empty_kind for i in range(4)] == [None, EMPTY, QUOTED_EMPTY, WHITESPACE]
    assert rows[2].cell(1).empty_kind == ABSENT and len(rows[2].raw) == 1


def test_csv_quotes_escapes_and_multiline(tmp_path):
    src = _csv(tmp_path, 'a,b\n"x, ""y""","l1\nl2"\n3,"q"z\n')
    rows = list(src.rows())
    assert rows[1].raw == ['x, "y"', "l1\nl2"] and rows[1].quoted == frozenset({0, 1})
    assert rows[2].raw == ["3", "qz"]
    assert src.info["text_after_closing_quote"] == 1 and src.info["multiline_records"] == 1
    assert src.info["records"] == 3 and src.info["physical_lines"] == 4


def test_csv_unterminated_quote_is_counted_not_fatal(tmp_path):
    src = _csv(tmp_path, 'a,b\n1,"never closed\n2,3\n')
    rows = list(src.rows())
    assert len(rows) == 2 and src.info["unterminated_quote"] == 1


def test_csv_trailing_delimiter_and_blank_lines(tmp_path):
    src = _csv(tmp_path, "a,b\n1,2,\n\n3,4")
    rows = list(src.rows())
    assert rows[1].raw == ["1", "2", ""] and rows[2].raw == [] and rows[3].raw == ["3", "4"]
    assert src.info["final_newline"] is False


def test_csv_nul_bytes_counted(tmp_path):
    src = _csv(tmp_path, "a,b\n1,x\x00y\n")
    assert src.info["encoding"]["nul_bytes"] == 1


def test_row_repr_never_shows_cell_contents(tmp_path):
    src = _csv(tmp_path, "a,b\nSECRETVALUE,2\n")
    for row in src.rows():
        assert "SECRETVALUE" not in repr(row)


def test_recipe_overrides_encoding_and_delimiter(tmp_path):
    src = _csv(tmp_path, "a|b\n1|é\n", encoding="cp1252", delimiter="|")
    assert src.info["encoding"]["encoding"] == "cp1252"
    src2 = open_source(str(tmp_path / "a.csv"), encoding="cp1252", delimiter="|")
    assert list(src2.rows())[1].raw == ["1", "é"]
    with pytest.raises(GridError):
        open_source(str(tmp_path / "a.csv"), encoding="no-such-codec")


def test_xlsx_reader_agrees_with_openpyxl_on_every_cell():
    path = product_path("inventory_mixed.xlsx")
    src = open_source(path)
    wb = openpyxl.load_workbook(path)  # independent reader used as an oracle
    checked = 0
    for sh in src.sheets:
        ws = wb[sh.name]
        seen = {}
        for row in src.rows(sh.index):
            for i, raw in enumerate(row.raw):
                if raw is not None:
                    seen[(row.index + 1, i + 1)] = (raw, row.stypes[i], i in row.formulas)
        for r in ws.iter_rows():
            for c in r:
                if c.value is None:
                    continue
                raw, stype, has_formula = seen[(c.row, c.column)]
                if c.data_type == "f":
                    assert has_formula
                elif c.data_type == "n":
                    assert stype == "number" and float(raw) == pytest.approx(float(c.value))
                elif c.data_type == "d":
                    assert stype == "number" and row is not None
                elif c.data_type == "b":
                    assert stype == "boolean" and raw == ("1" if c.value else "0")
                elif c.data_type == "e":
                    assert stype == "error" and raw == c.value
                else:
                    assert stype.endswith("string") and raw == c.value
                checked += 1
    assert checked > 3000


def test_xlsx_inventory_and_states():
    src = open_source(product_path("inventory_mixed.xlsx"))
    for sh in src.sheets:
        for _ in src.rows(sh.index):
            pass
    assert [s.state for s in src.sheets] == ["visible", "visible", "hidden"]
    inv = src.info["metadata_inventory"]
    assert inv["author_recorded"] and inv["comment_parts"] == 1 and inv["defined_names"] == 1
    post = src.sheets[0].post
    assert post["formula_cells"] == 400 and post["merged_ranges"] == 1 and post["hidden_rows"] == 1
    assert post["hidden_columns"] == 1


def test_formula_text_is_never_retained():
    src = open_source(product_path("inventory_mixed.xlsx"))
    for row in src.rows(0):
        for raw in row.raw:
            assert raw is None or not raw.startswith("=")
            assert raw is None or "*E" not in raw


def test_not_a_workbook_is_refused(tmp_path):
    p = tmp_path / "fake.xlsx"
    p.write_bytes(b"this is not a zip archive")
    with pytest.raises(GridError):
        open_source(str(p))
    legacy = tmp_path / "old.xls"
    legacy.write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 64)
    with pytest.raises(GridError) as exc:
        open_source(str(legacy))
    assert "not supported" in str(exc.value)
    z = tmp_path / "plain.zip.xlsx"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("hello.txt", "x")
    with pytest.raises(GridError):
        open_source(str(z))
    with pytest.raises(GridError):
        open_source(str(tmp_path / "missing.csv"))


def _rewrite(path_in: str, path_out: str, part: str, transform) -> None:
    with zipfile.ZipFile(path_in) as src, zipfile.ZipFile(path_out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == part:
                data = transform(data)
            dst.writestr(item.filename, data)


def test_doctype_in_a_sheet_part_is_refused(tmp_path):
    wb = openpyxl.Workbook()
    wb.active["A1"] = "x"
    base = tmp_path / "base.xlsx"
    wb.save(base)
    evil = tmp_path / "evil.xlsx"
    doctype = b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/hostname">]>'
    _rewrite(str(base), str(evil), "xl/worksheets/sheet1.xml",
             lambda d: d.replace(b"?>", b"?>" + doctype, 1) if b"?>" in d else doctype + d)
    src = open_source(str(evil))
    with pytest.raises(GridError):
        list(src.rows(0))


def test_zip_bomb_guard(tmp_path):
    wb = openpyxl.Workbook()
    base = tmp_path / "base.xlsx"
    wb.save(base)
    bomb = tmp_path / "bomb.xlsx"
    with zipfile.ZipFile(base) as src, zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as dst:
        for item in src.infolist():
            dst.writestr(item.filename, src.read(item.filename))
        dst.writestr("xl/media/pad.bin", b"\x00" * (120 * 1024 * 1024))
    with pytest.raises(GridError) as exc:
        open_source(str(bomb))
    assert "zip bomb" in str(exc.value)


def test_xlsx_with_csv_extension_is_detected_by_content(tmp_path):
    buf = io.BytesIO()
    wb = openpyxl.Workbook()
    wb.active.append(["a", "b"])
    wb.save(buf)
    p = tmp_path / "really_xlsx.csv"
    p.write_bytes(buf.getvalue())
    assert open_source(str(p)).format == "xlsx"
    assert os.path.getsize(p) > 0
