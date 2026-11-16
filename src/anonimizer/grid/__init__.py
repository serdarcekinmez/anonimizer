"""Lossless streaming readers (CSV, XLSX)."""

from __future__ import annotations

from .csv_reader import CsvSource
from .model import GridError, GridSource, Row, SheetInfo
from .xlsx_reader import XlsxSource

__all__ = ["CsvSource", "XlsxSource", "GridError", "GridSource", "Row", "SheetInfo", "open_source"]

CSV_EXT = (".csv", ".tsv", ".tab", ".txt")
XLSX_EXT = (".xlsx", ".xlsm")


def open_source(path: str, *, encoding: str | None = None, delimiter: str | None = None,
                quotechar: str = '"') -> GridSource:
    """Open a file by content first, extension second."""
    try:
        with open(path, "rb") as fh:
            magic = fh.read(4)
    except OSError:
        raise GridError("input file cannot be opened") from None
    low = path.lower()
    if magic.startswith(b"PK\x03\x04"):
        return XlsxSource(path)
    if magic.startswith(b"\xd0\xcf\x11\xe0") or low.endswith((".xls", ".xlsb")):
        raise GridError("legacy .xls/.xlsb workbooks (and password-protected workbooks) are not supported; "
                        "save the file as .xlsx")
    if low.endswith(XLSX_EXT):
        raise GridError("the file has an XLSX extension but is not a zip archive")
    return CsvSource(path, encoding=encoding, delimiter=delimiter, quotechar=quotechar)
