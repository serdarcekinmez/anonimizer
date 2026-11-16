"""Local source inspector: lets the user look at their own file.

EVERYTHING RETURNED BY THIS MODULE CONTAINS ORIGINAL VALUES (cells, headers, notes, exact counts).

It exists for one consumer, the local interface, which shows the result to the person who opened
the file and keeps it in the page's memory only. It is deliberately outside the path that produces
anything leaving the machine: the contract, the generator, the privacy assessment, the reports, the
export and the pipeline must never import it (``tests/architecture`` enforces this), and nothing here
writes a file or takes a policy.
"""

from __future__ import annotations

import datetime as _dt

from .grid.model import BOOL, NUMBER
from .patterns import DATE, classify, excel_serial_to_date
from .recipe import ParseRecipe, propose_recipe

MAX_ROWS = 200  # rows per answer, whatever is asked for
MAX_COLS = 60  # columns per answer
MAX_CELL_CHARS = 300  # longer cell texts are cut for display
CONTEXT_ROWS = 3  # rows shown above a region when it is selected
CONTEXT_COLS = 1  # columns shown to the left of it
FREQUENT_VALUES = 10


class InspectError(ValueError):
    """A request the inspector cannot serve. The message never quotes a cell."""


def _int(value, name: str, default: int, lo: int, hi: int | None = None) -> int:
    if value is None:
        value = default
    if isinstance(value, bool) or not isinstance(value, int) or value < lo:
        raise InspectError(f"{name} must be a whole number of at least {lo}")
    return value if hi is None else min(value, hi)


def _display(row, i: int, date1904: bool) -> str | None:
    """The cell as a person expects to read it. ``None``: the cell does not exist."""
    if i >= len(row.raw) or row.raw[i] is None:
        return None
    raw = row.raw[i]
    stype = row.stype(i)
    if stype == BOOL:
        return "TRUE" if raw.strip() in ("1", "true", "TRUE") else "FALSE"
    if stype == NUMBER and row.formats and row.formats.get(i):
        # A spreadsheet stores a date as a day count; show the date its format displays.
        if classify(raw, stype, False, row.formats.get(i), date1904=date1904).family == DATE:
            try:
                serial = float(raw)
            except ValueError:
                return raw
            day = excel_serial_to_date(serial, date1904)
            if day is not None:
                seconds = round((serial - int(serial)) * 86400)
                if not seconds:
                    return day.isoformat()
                return f"{day.isoformat()} {_dt.timedelta(seconds=seconds)}"
    return raw


def window(path: str, recipe: ParseRecipe | None, *, region=None, sheet=None, first_row=None, first_col=None,
           n_rows=None, n_cols=None) -> dict:
    """A bounded rectangle of original cells. Rows and columns are numbered from 1.

    With ``region`` and no position, the rectangle starts a few rows above and one column to the
    left of that region, so that its surroundings are visible.
    """
    _proposed, source, regions = propose_recipe(path, recipe)
    n_rows = _int(n_rows, "rows", 50, 1, MAX_ROWS)
    n_cols = _int(n_cols, "cols", 30, 1, MAX_COLS)
    row_default = col_default = 1
    sheet_default = 0
    if region is not None:
        if isinstance(region, bool) or not isinstance(region, int) or not 0 <= region < len(regions):
            raise InspectError("no such region")
        reg = regions[region]
        sheet_default = reg.sheet
        row_default = max(1, reg.top + 1 - CONTEXT_ROWS)
        col_default = max(1, reg.col_start + 1 - CONTEXT_COLS)
    sheet_i = _int(sheet, "sheet", sheet_default, 0)
    if sheet_i >= len(source.sheets):
        raise InspectError("no such sheet")
    r0 = _int(first_row, "row", row_default, 1) - 1
    c0 = _int(first_col, "col", col_default, 1) - 1
    date1904 = bool(getattr(source, "info", {}).get("date1904"))

    found: dict = {}
    more = False
    for row in source.rows(sheet_i):
        if row.index < r0:
            continue
        if row.index >= r0 + n_rows:
            more = True
            break
        found[row.index] = row
    here = [r for r in regions if r.sheet == sheet_i]
    width = max([len(r.raw) for r in found.values()] + [r.col_end for r in here] + [0])
    c1 = min(c0 + n_cols, width)
    last = r0 + n_rows - 1 if more else max(found, default=r0 - 1)
    truncated = 0
    rows = []
    for index in range(r0, last + 1):
        row = found.get(index)
        cells: list = []
        for i in range(c0, c1):
            text = _display(row, i, date1904) if row is not None else None
            if text is not None and len(text) > MAX_CELL_CHARS:
                text = text[:MAX_CELL_CHARS] + "…"
                truncated += 1
            cells.append(text)
        rows.append({"row": index + 1, "hidden": bool(row is not None and row.hidden), "cells": cells})
    return {
        "contains_source_values": True,
        "sheet": sheet_i, "sheet_name": source.sheets[sheet_i].name,
        "sheets": [{"index": s.index, "name": s.name, "state": s.state} for s in source.sheets],
        "first_row": r0 + 1, "first_col": c0 + 1, "columns": max(0, c1 - c0), "columns_total": width,
        "rows": rows, "more_rows": more, "truncated_cells": truncated,
        "regions": [{
            "index": regions.index(r), "name": r.name, "kind": r.kind, "include": r.include,
            "first_row": r.top + 1, "last_row": r.bottom + 1, "first_col": r.col_start + 1, "last_col": r.col_end,
            "header_row": None if r.header_row is None else r.header_row + 1, "first_data_row": r.data_start + 1,
        } for r in here],
    }


def statistics(private_profile: dict) -> dict:
    """Exact counts per table and column, read from the private profile (never from the shareable view)."""
    tables = []
    for tab in private_profile["tables"]:
        columns = []
        for col in tab["columns"]:
            distinct = col.get("distinct") or {}
            frequent = sorted((col.get("_private") or {}).get("category_values", {}).items(),
                              key=lambda kv: (-kv[1], kv[0]))[:FREQUENT_VALUES]
            columns.append({
                "id": col["id"], "name": col["name"], "type": col.get("logical_type"), "type_share": col.get("type_share"),
                "cells": col["n_cells"], "values": col["n_values"], "missing": col["n_missing"],
                "missing_kinds": col.get("missing") or {}, "markers": col.get("markers") or {},
                "kinds": col.get("families") or {}, "distinct": distinct.get("n_distinct"),
                "repeated_values": distinct.get("repeated_values"), "most_repeats": distinct.get("max_multiplicity"),
                "formula_cells": col.get("formula_cells", 0), "error_values": col.get("error_values", 0),
                "exceptions": len(col.get("exceptions") or []),
                "frequent_values": [[value, n] for value, n in frequent],
            })
        tables.append({
            "name": tab["name"], "sheet": tab["sheet"], "rows": tab["n_rows"], "columns_total": tab["n_columns"],
            "header_present": tab["header_present"], "hidden_rows": tab.get("hidden_rows", 0),
            "duplicate_extra_rows": (tab.get("duplicate_rows") or {}).get("extra_rows", 0), "columns": columns,
        })
    return {"contains_source_values": True, "tables": tables,
            "notes": [{"name": n["name"], "sheet": n["sheet"], "rows": len(n.get("rows") or [])}
                      for n in private_profile.get("notes", [])]}
