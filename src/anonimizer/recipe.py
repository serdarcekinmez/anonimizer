"""ParseRecipe: the reviewable, user-correctable description of how a file is read.

Rows and columns in the JSON form are 1-based, as in a spreadsheet. The recipe holds layout
decisions only, never cell contents.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .grid import GridError, GridSource, open_source
from .regions import Region, detect_regions

RECIPE_VERSION = 1


class RecipeError(ValueError):
    pass


@dataclass
class ParseRecipe:
    encoding: str | None = None
    delimiter: str | None = None
    quotechar: str = '"'
    extra_markers: list[str] = field(default_factory=list)
    tables: list[dict] | None = None  # None: detect automatically

    def to_dict(self) -> dict:
        return {"recipe_version": RECIPE_VERSION, "file": {"encoding": self.encoding, "delimiter": self.delimiter,
                                                           "quotechar": self.quotechar},
                "extra_markers": list(self.extra_markers), "tables": self.tables}

    @classmethod
    def from_dict(cls, d: dict) -> ParseRecipe:
        if not isinstance(d, dict) or d.get("recipe_version") != RECIPE_VERSION:
            raise RecipeError(f"unsupported recipe: expected recipe_version {RECIPE_VERSION}")
        f = d.get("file") or {}
        delim = f.get("delimiter")
        if delim is not None and (not isinstance(delim, str) or len(delim) != 1):
            raise RecipeError("file.delimiter must be a single character")
        q = f.get("quotechar") or '"'
        if not isinstance(q, str) or len(q) != 1:
            raise RecipeError("file.quotechar must be a single character")
        markers = d.get("extra_markers") or []
        if not isinstance(markers, list) or not all(isinstance(m, str) and 0 < len(m) <= 32 for m in markers):
            raise RecipeError("extra_markers must be a list of short strings")
        tables = d.get("tables")
        if tables is not None and not isinstance(tables, list):
            raise RecipeError("tables must be a list or null")
        return cls(f.get("encoding"), delim, q, list(markers), tables)

    @classmethod
    def load(cls, path: str) -> ParseRecipe:
        try:
            with open(path, encoding="utf-8") as fh:
                return cls.from_dict(json.load(fh))
        except (OSError, json.JSONDecodeError):
            raise RecipeError("the recipe file cannot be read as JSON") from None

    def open(self, path: str) -> GridSource:
        return open_source(path, encoding=self.encoding, delimiter=self.delimiter, quotechar=self.quotechar)


def region_to_spec(r: Region) -> dict:
    return {
        "name": r.name, "sheet": r.sheet_name, "kind": r.kind, "include": r.include,
        "header_row": None if r.header_row is None else r.header_row + 1,
        "first_row": r.top + 1,
        "first_data_row": r.data_start + 1, "last_data_row": r.bottom + 1,
        "first_col": r.col_start + 1, "last_col": r.col_end,
        "source": r.source, "confidence": r.confidence, "notes": list(r.notes),
    }


def _int(spec: dict, key: str, *, optional: bool = False) -> int | None:
    v = spec.get(key)
    if v is None and optional:
        return None
    if not isinstance(v, int) or isinstance(v, bool) or v < 1:
        raise RecipeError(f"table '{spec.get('name', '?')}': {key} must be a positive integer")
    return v


def spec_to_region(spec: dict, source: GridSource) -> Region:
    if not isinstance(spec, dict):
        raise RecipeError("each table entry must be an object")
    sheet_name = spec.get("sheet")
    sheets = {s.name: s.index for s in source.sheets}
    if sheet_name is None and len(source.sheets) == 1:
        sheet = 0
    elif sheet_name in sheets:
        sheet = sheets[sheet_name]
    else:
        raise RecipeError(f"table '{spec.get('name', '?')}': unknown sheet")
    header = _int(spec, "header_row", optional=True)
    first_data = _int(spec, "first_data_row")
    last_data = _int(spec, "last_data_row", optional=True)
    first_col = _int(spec, "first_col")
    last_col = _int(spec, "last_col")
    first_row = _int(spec, "first_row", optional=True) or (header or first_data)
    if header is not None and header >= first_data:
        raise RecipeError(f"table '{spec.get('name', '?')}': header_row must be above first_data_row")
    if last_data is not None and last_data < first_data - 1:
        raise RecipeError(f"table '{spec.get('name', '?')}': last_data_row is above first_data_row")
    if last_col < first_col:
        raise RecipeError(f"table '{spec.get('name', '?')}': last_col is left of first_col")
    kind = spec.get("kind", "table")
    if kind not in ("table", "note"):
        raise RecipeError("kind must be 'table' or 'note'")
    name = spec.get("name") or ""
    if not isinstance(name, str) or len(name) > 120:
        raise RecipeError("table name must be a string of at most 120 characters")
    top = min(first_row, header or first_data) - 1
    return Region(sheet, source.sheets[sheet].name, kind, top, (last_data - 1) if last_data else -1,
                  first_col - 1, last_col, None if header is None else header - 1, first_data - 1,
                  preamble_rows=max(0, (header or first_data) - 1 - top),
                  confidence=float(spec.get("confidence", 1.0)) if spec.get("source") != "user" else 1.0,
                  notes=[str(n) for n in spec.get("notes", [])][:20], name=name,
                  source=spec.get("source", "user") if spec.get("source") in ("auto", "user") else "user",
                  include=bool(spec.get("include", True)))


def resolve_regions(recipe: ParseRecipe, source: GridSource) -> tuple[list[Region], list[Region]]:
    """Return (regions in force, automatically detected candidates)."""
    detected = detect_regions(source)
    if recipe.tables is None:
        return detected, detected
    regions = [spec_to_region(s, source) for s in recipe.tables]
    last_rows: dict[int, int] = {}
    for r in regions:
        if r.bottom < 0:  # open-ended: runs to the last row of the sheet
            if r.sheet not in last_rows:
                last = -1
                for row in source.rows(r.sheet):
                    last = row.index
                last_rows[r.sheet] = last
            r.bottom = last_rows[r.sheet]
    seen = set()
    for i, r in enumerate(regions):
        if not r.name:
            r.name = f"table_{i + 1}"
        if r.name in seen:
            raise RecipeError("table names must be unique")
        seen.add(r.name)
    active = [r for r in regions if r.include]
    for i, a in enumerate(active):
        for b in active[i + 1:]:
            if a.sheet == b.sheet and a.top <= b.bottom and b.top <= a.bottom \
                    and a.col_start < b.col_end and b.col_start < a.col_end:
                raise RecipeError(f"tables '{a.name}' and '{b.name}' overlap")
    return regions, detected


def propose_recipe(path: str, recipe: ParseRecipe | None = None) -> tuple[ParseRecipe, GridSource, list[Region]]:
    recipe = recipe or ParseRecipe()
    source = recipe.open(path)
    regions, _ = resolve_regions(recipe, source)
    out = ParseRecipe(recipe.encoding, recipe.delimiter, recipe.quotechar, list(recipe.extra_markers),
                      [region_to_spec(r) for r in regions])
    return out, source, regions


__all__ = ["ParseRecipe", "RecipeError", "GridError", "propose_recipe", "resolve_regions", "region_to_spec",
           "spec_to_region"]
