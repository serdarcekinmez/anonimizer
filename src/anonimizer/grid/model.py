"""Lossless grid model: one record per physical row, nothing coerced at ingestion.

A ``Row`` keeps, for every cell, the raw text exactly as stored, the storage type and the
flags needed to tell the different kinds of emptiness apart. Interpretation (numbers, dates,
missing markers) happens later, in ``anonimizer.patterns`` and ``anonimizer.profile``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import NamedTuple, Protocol

# Storage types -----------------------------------------------------------------------------
TEXT = "text"  # CSV field
NUMBER = "number"  # XLSX numeric cell (raw is the stored XML text, no float round trip)
SSTRING = "shared_string"
ISTRING = "inline_string"
FSTRING = "formula_string"  # cached string result of a formula
BOOL = "boolean"
ERROR = "error"
ISODATE = "iso_date"  # XLSX t="d"
BLANK = "blank"  # XLSX cell element present without a value

STRING_TYPES = frozenset({TEXT, SSTRING, ISTRING, FSTRING})

# Empty kinds -------------------------------------------------------------------------------
ABSENT = "absent"  # no cell at all (short row, sparse sheet)
EMPTY = "empty"  # cell present, zero-length, unquoted / XLSX blank cell
QUOTED_EMPTY = "quoted_empty"  # CSV ""
EMPTY_STRING = "empty_string"  # XLSX string cell holding ""
WHITESPACE = "whitespace"  # only whitespace characters


class Cell(NamedTuple):
    raw: str | None
    stype: str
    empty_kind: str | None
    quoted: bool
    number_format: str | None
    has_formula: bool


def empty_kind(raw: str | None, stype: str = TEXT, quoted: bool = False) -> str | None:
    if raw is None:
        return ABSENT
    if raw == "":
        if quoted:
            return QUOTED_EMPTY
        if stype in (SSTRING, ISTRING, FSTRING):
            return EMPTY_STRING
        return EMPTY
    if raw.strip() == "" and raw.strip("    \t\r\n\x0b\x0c") == "":
        return WHITESPACE
    return None


class Row:
    """One physical row. ``raw[i] is None`` means the cell does not exist."""

    __slots__ = ("index", "line", "raw", "stypes", "quoted", "formats", "formulas", "hidden")

    def __init__(self, index, raw, *, line=None, stypes=None, quoted=(), formats=None, formulas=(), hidden=False):
        self.index: int = index  # 0-based record / sheet row index
        self.line: int | None = line  # CSV: 1-based physical line where the record starts
        self.raw: list[str | None] = raw
        self.stypes: list[str] | None = stypes  # None means every cell is TEXT (CSV)
        self.quoted = quoted  # indexes of quoted CSV fields
        self.formats: dict[int, str] | None = formats  # XLSX number formats (non-General only)
        self.formulas = formulas  # indexes of cells carrying a formula
        self.hidden: bool = hidden

    def stype(self, i: int) -> str:
        if self.stypes is None:
            return TEXT
        return self.stypes[i] if i < len(self.stypes) else BLANK

    def cell(self, i: int) -> Cell:
        if i >= len(self.raw) or self.raw[i] is None:
            return Cell(None, BLANK if self.stypes is not None else TEXT, ABSENT, False, None, False)
        raw = self.raw[i]
        st = self.stype(i)
        q = i in self.quoted
        fmt = self.formats.get(i) if self.formats else None
        return Cell(raw, st, empty_kind(raw, st, q), q, fmt, i in self.formulas)

    def is_blank(self) -> bool:
        for v in self.raw:
            if v is not None and v != "" and v.strip() != "":
                return False
        return True

    def __repr__(self) -> str:  # never prints cell contents
        return f"Row(index={self.index}, cells={len(self.raw)})"


@dataclass
class SheetInfo:
    index: int
    name: str
    state: str = "visible"
    post: dict = field(default_factory=dict)  # filled once the sheet has been fully read


class GridSource(Protocol):
    format: str
    info: dict
    sheets: list[SheetInfo]

    def rows(self, sheet: int = 0) -> Iterator[Row]: ...


class GridError(Exception):
    """Raised for unreadable inputs. Messages never contain cell contents."""
