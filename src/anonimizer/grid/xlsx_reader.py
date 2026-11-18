"""Thin streaming XLSX reader over the sheet XML.

It keeps the stored text of every cell (no float round trip), the storage type, the number
format and formula *presence*. Formula text is never retained. Workbook metadata is only
inventoried as counts and booleans. Macros are never executed; nothing outside the archive
is ever resolved.
"""

from __future__ import annotations

import os
import posixpath
import re
import zipfile
from collections.abc import Iterator
from xml.etree import ElementTree as ET

from .model import BLANK, BOOL, ERROR, FSTRING, ISODATE, ISTRING, NUMBER, SSTRING, GridError, Row, SheetInfo

MAX_UNCOMPRESSED = 8 * 1024**3
MAX_RATIO = 1000
MAX_COLUMNS = 16384
MAX_SHARED_STRINGS = 20_000_000

BUILTIN_FORMATS = {
    0: "General", 1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00", 9: "0%", 10: "0.00%", 11: "0.00E+00",
    12: "# ?/?", 13: "# ??/??", 14: "mm-dd-yy", 15: "d-mmm-yy", 16: "d-mmm", 17: "mmm-yy",
    18: "h:mm AM/PM", 19: "h:mm:ss AM/PM", 20: "h:mm", 21: "h:mm:ss", 22: "m/d/yy h:mm",
    37: "#,##0 ;(#,##0)", 38: "#,##0 ;[Red](#,##0)", 39: "#,##0.00;(#,##0.00)",
    40: "#,##0.00;[Red](#,##0.00)", 45: "mm:ss", 46: "[h]:mm:ss", 47: "mmss.0", 48: "##0.0E+0", 49: "@",
}
_DATE_BUILTIN = set(range(14, 23)) | set(range(27, 37)) | {45, 46, 47} | set(range(50, 59))
_FMT_STRIP = re.compile(r'"[^"]*"|\[[^\]]*\]|\\.|_.|\*.')


def is_date_format(code: str | None) -> bool:
    if not code or code == "General" or code == "@":
        return False
    bare = _FMT_STRIP.sub("", code).lower()
    return any(ch in bare for ch in "ymdhs") and "e+" not in bare


def date_format_kind(code: str) -> str:
    bare = _FMT_STRIP.sub("", code).lower()
    has_date = "y" in bare or "d" in bare
    has_time = "h" in bare or "s" in bare
    if has_date and has_time:
        return "datetime"
    if has_time and not has_date:
        return "time"
    return "date"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _col_index(ref: str, cache: dict[str, int]) -> int:
    letters = ref.rstrip("0123456789")
    c = cache.get(letters)
    if c is None:
        c = 0
        for ch in letters:
            c = c * 26 + (ord(ch) & 31)
        c -= 1
        cache[letters] = c
    return c


_PROLOG_LIMIT = 1 << 20


def _scan_prolog(head: bytes) -> bool:
    """True once the root element is reached. Raises if a document type declaration comes first.

    OOXML parts never need a DTD. Refusing it removes entity tricks at the door instead of
    relying on the XML library's defaults.
    """
    if head[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in head[:4]:
        try:
            text = head.decode("utf-16" if head[:2] in (b"\xff\xfe", b"\xfe\xff") else
                               "utf-16-le" if head[1:2] == b"\x00" else "utf-16-be", errors="ignore")
        except LookupError:  # pragma: no cover
            text = ""
    else:
        text = head.decode("latin-1")
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch != "<":
            i += 1
            continue
        if text.startswith("<?", i):
            j = text.find("?>", i)
        elif text.startswith("<!--", i):
            j = text.find("-->", i)
        elif text[i:i + 9].upper() == "<!DOCTYPE" or text.startswith("<!", i):
            raise GridError("XML document type declarations are not accepted in workbook parts")
        else:
            return True
        if j < 0:
            return False
        i = j + 2
    return False


class _CheckedStream:
    """File-like wrapper that inspects the XML prolog before the parser sees anything."""

    def __init__(self, fh):
        self._fh = fh
        head = b""
        done = False
        while not done and len(head) < _PROLOG_LIMIT:
            chunk = fh.read(65536)
            if not chunk:
                break
            head += chunk
            done = _scan_prolog(head)
        if not done and head:
            raise GridError("a workbook XML part has no root element within the allowed prolog size")
        self._head = head

    def read(self, n: int = -1) -> bytes:
        if self._head:
            if n is None or n < 0:
                out, self._head = self._head + self._fh.read(), b""
                return out
            out, self._head = self._head[:n], self._head[n:]
            return out
        return self._fh.read(n)


class XlsxSource:
    format = "xlsx"

    def __init__(self, path: str):
        if not os.path.isfile(path):
            raise GridError("input file does not exist or is not a regular file")
        self.path = path
        try:
            self._zip = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError):
            raise GridError("the file is not a readable XLSX (zip) archive") from None
        total = 0
        for zi in self._zip.infolist():
            total += zi.file_size
            if zi.compress_size and zi.file_size > 50 * 1024**2 and zi.file_size / zi.compress_size > MAX_RATIO:
                raise GridError("workbook part exceeds the allowed compression ratio (zip bomb guard)")
        if total > MAX_UNCOMPRESSED:
            raise GridError("workbook exceeds the allowed uncompressed size (zip bomb guard)")
        names = set(self._zip.namelist())
        if "xl/workbook.xml" not in names:
            raise GridError("the archive has no xl/workbook.xml part; not an XLSX workbook")
        self._names = names
        self._read_workbook()
        self._read_styles()
        self._shared: list[str] | None = None
        self.info = {
            "format": "xlsx", "size_bytes": os.path.getsize(path), "date1904": self.date1904,
            "sheet_count": len(self.sheets),
            "hidden_sheets": sum(1 for s in self.sheets if s.state != "visible"),
            "metadata_inventory": self._inventory(),
        }

    # -- workbook parts -------------------------------------------------------------------
    def _parse(self, name: str) -> ET.Element:
        try:
            with self._zip.open(name) as fh:
                return ET.parse(_CheckedStream(fh)).getroot()
        except ET.ParseError:
            raise GridError("a workbook XML part is malformed") from None

    def _read_workbook(self) -> None:
        root = self._parse("xl/workbook.xml")
        rels: dict[str, str] = {}
        if "xl/_rels/workbook.xml.rels" in self._names:
            for rel in self._parse("xl/_rels/workbook.xml.rels"):
                target = rel.get("Target", "")
                target = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
                rels[rel.get("Id", "")] = target
        self.date1904 = False
        self.defined_names = 0
        self.sheets: list[SheetInfo] = []
        self._sheet_parts: list[str] = []
        for el in root.iter():
            tag = _local(el.tag)
            if tag == "workbookPr":
                self.date1904 = el.get("date1904") in ("1", "true")
            elif tag == "definedName":
                self.defined_names += 1
            elif tag == "sheet":
                rid = next((v for k, v in el.attrib.items() if _local(k) == "id"), "")
                part = rels.get(rid)
                if part is None or part not in self._names:
                    continue
                if not part.startswith("xl/worksheets/"):
                    continue  # chart sheets, macro sheets: inventoried, not read
                self.sheets.append(SheetInfo(len(self.sheets), el.get("name", ""), el.get("state", "visible")))
                self._sheet_parts.append(part)
        if not self.sheets:
            raise GridError("the workbook contains no readable worksheet")

    def _read_styles(self) -> None:
        self._xf_formats: list[str | None] = []
        if "xl/styles.xml" not in self._names:
            return
        root = self._parse("xl/styles.xml")
        custom: dict[int, str] = {}
        for el in root.iter():
            if _local(el.tag) == "numFmt":
                try:
                    custom[int(el.get("numFmtId", "0"))] = el.get("formatCode", "")
                except ValueError:
                    continue
        for el in root:
            if _local(el.tag) == "cellXfs":
                for xf in el:
                    try:
                        fid = int(xf.get("numFmtId", "0"))
                    except ValueError:
                        fid = 0
                    code = custom.get(fid) or BUILTIN_FORMATS.get(fid)
                    if code is None and fid in _DATE_BUILTIN:
                        code = "yyyy-mm-dd"
                    self._xf_formats.append(None if code in (None, "General") else code)

    def _shared_strings(self) -> list[str]:
        if self._shared is not None:
            return self._shared
        out: list[str] = []
        name = "xl/sharedStrings.xml"
        if name in self._names:
            try:
                with self._zip.open(name) as fh:
                    for _ev, el in ET.iterparse(_CheckedStream(fh), events=("end",)):
                        if _local(el.tag) == "si":
                            out.append(_string_item(el))
                            el.clear()
                            if len(out) > MAX_SHARED_STRINGS:
                                raise GridError("shared string table exceeds the supported size")
            except ET.ParseError:
                raise GridError("the shared string table is malformed") from None
        self._shared = out
        return out

    def _inventory(self) -> dict:
        n = self._names
        inv = {
            "defined_names": self.defined_names,
            "has_macros": any(x.endswith("vbaProject.bin") for x in n),
            "comment_parts": sum(1 for x in n if x.startswith("xl/comments") or x.startswith("xl/threadedComments")),
            "external_link_parts": sum(1 for x in n if x.startswith("xl/externalLinks/") and x.endswith(".xml")),
            "has_data_connections": "xl/connections.xml" in n,
            "pivot_table_parts": sum(1 for x in n if x.startswith("xl/pivotTables/")),
            "drawing_parts": sum(1 for x in n if x.startswith("xl/drawings/") and x.endswith(".xml")),
            "embedded_media_parts": sum(1 for x in n if x.startswith("xl/media/") or x.startswith("xl/embeddings/")),
            "custom_xml_parts": sum(1 for x in n if x.startswith("customXml/")),
            "has_core_properties": "docProps/core.xml" in n,
            "has_custom_properties": "docProps/custom.xml" in n,
            "author_recorded": False,
        }
        if inv["has_core_properties"]:
            try:
                for el in self._parse("docProps/core.xml"):
                    if _local(el.tag) in ("creator", "lastModifiedBy") and (el.text or "").strip():
                        inv["author_recorded"] = True
            except GridError:
                pass
        return inv

    # -- rows -------------------------------------------------------------------------------
    def rows(self, sheet: int = 0) -> Iterator[Row]:
        info = self.sheets[sheet]
        shared = self._shared_strings()
        xf = self._xf_formats
        cache: dict[str, int] = {}
        post = {"merged_ranges": 0, "hidden_rows": 0, "hidden_columns": 0, "formula_cells": 0,
                "data_validations": 0, "rows_read": 0}
        next_index = 0
        try:
            with self._zip.open(self._sheet_parts[sheet]) as fh:
                sheet_data = None
                for ev, el in ET.iterparse(_CheckedStream(fh), events=("start", "end")):
                    tag = _local(el.tag)
                    if ev == "start":
                        if tag == "sheetData":
                            sheet_data = el
                        continue
                    if tag == "row":
                        r = el.get("r")
                        index = int(r) - 1 if r and r.isdigit() else next_index
                        next_index = index + 1
                        raw: list[str | None] = []
                        stypes: list[str] = []
                        formats: dict[int, str] | None = None
                        formulas: set[int] | None = None
                        pos = 0
                        for c in el:
                            ref = c.get("r")
                            col = _col_index(ref, cache) if ref else pos
                            if col >= MAX_COLUMNS or col < 0:
                                continue
                            pos = col + 1
                            t = c.get("t", "n")
                            v = None
                            has_f = False
                            inline = None
                            for ch in c:
                                lt = _local(ch.tag)
                                if lt == "v":
                                    v = ch.text or ""
                                elif lt == "f":
                                    has_f = True
                                elif lt == "is":
                                    inline = _string_item(ch)
                            if t == "s":
                                st = SSTRING
                                try:
                                    val = shared[int(v)] if v is not None else ""
                                except (ValueError, IndexError):
                                    val, st = "", BLANK
                            elif t == "inlineStr":
                                st, val = ISTRING, inline if inline is not None else (v or "")
                            elif t == "str":
                                st, val = FSTRING, v or ""
                            elif t == "b":
                                st, val = BOOL, v or ""
                            elif t == "e":
                                st, val = ERROR, v or ""
                            elif t == "d":
                                st, val = ISODATE, v or ""
                            elif v is None or v == "":
                                st, val = BLANK, ""
                            else:
                                st, val = NUMBER, v
                            while len(raw) < col:
                                raw.append(None)
                                stypes.append(BLANK)
                            if len(raw) == col:
                                raw.append(val)
                                stypes.append(st)
                            else:  # duplicate reference: last one wins, as in spreadsheet apps
                                raw[col], stypes[col] = val, st
                            if has_f:
                                formulas = formulas or set()
                                formulas.add(col)
                            s = c.get("s")
                            if s and st in (NUMBER, ISODATE):
                                try:
                                    code = xf[int(s)]
                                except (ValueError, IndexError):
                                    code = None
                                if code:
                                    formats = formats or {}
                                    formats[col] = code
                        hidden = el.get("hidden") in ("1", "true")
                        if hidden:
                            post["hidden_rows"] += 1
                        if formulas:
                            post["formula_cells"] += len(formulas)
                        post["rows_read"] += 1
                        if sheet_data is not None:
                            sheet_data.clear()
                        yield Row(index, raw, stypes=stypes, formats=formats,
                                  formulas=frozenset(formulas) if formulas else (), hidden=hidden)
                    elif tag == "mergeCell":
                        post["merged_ranges"] += 1
                    elif tag == "dataValidation":
                        post["data_validations"] += 1
                    elif tag == "col" and el.get("hidden") in ("1", "true"):
                        try:
                            post["hidden_columns"] += int(el.get("max", "1")) - int(el.get("min", "1")) + 1
                        except ValueError:
                            post["hidden_columns"] += 1
        except ET.ParseError:
            raise GridError("a worksheet XML part is malformed") from None
        except zipfile.BadZipFile:
            raise GridError("a worksheet part is corrupt") from None
        info.post = post


def _string_item(el: ET.Element) -> str:
    """Concatenate the text runs of a string item, ignoring phonetic runs."""
    parts: list[str] = []
    for ch in el:
        lt = _local(ch.tag)
        if lt == "t":
            parts.append(ch.text or "")
        elif lt == "r":
            for t in ch:
                if _local(t.tag) == "t":
                    parts.append(t.text or "")
    return "".join(parts)
