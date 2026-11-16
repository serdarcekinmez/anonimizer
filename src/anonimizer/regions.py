"""Table and region detection on a streamed sketch of each sheet.

One pass per sheet. Rows are grouped into blocks separated by blank rows; blocks are split
on blank columns (side-by-side tables), given a header guess, and merged again when a blank
row turns out to sit inside one table. Every decision carries a confidence and notes so the
user can correct the result through the parse recipe.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field

from .grid.model import GridSource, Row
from .patterns import BOOLEAN, DATE, ERR, MISSING, NUM, TXT, classify

HEAD_ROWS = 30
MAX_MERGE_GAP = 3


@dataclass
class Region:
    sheet: int
    sheet_name: str
    kind: str  # "table" | "note"
    top: int  # first physical row (0-based), preamble included
    bottom: int  # last physical row (inclusive)
    col_start: int
    col_end: int  # exclusive
    header_row: int | None
    data_start: int
    preamble_rows: int = 0
    confidence: float = 0.5
    notes: list[str] = field(default_factory=list)
    name: str = ""
    source: str = "auto"
    include: bool = True
    blank_rows_inside: int = 0

    @property
    def n_data_rows(self) -> int:
        return max(0, self.bottom - self.data_start + 1)

    def to_dict(self) -> dict:
        return asdict(self)


class _Block:
    __slots__ = ("start", "end", "col_counts", "col_first", "col_last", "n_rows", "head", "gap_before")

    def __init__(self, start: int, gap_before: int):
        self.start = start
        self.end = start
        self.col_counts: list[int] = []
        self.col_first: list[int] = []
        self.col_last: list[int] = []
        self.n_rows = 0
        self.head: list[Row] = []
        self.gap_before = gap_before


def _nonempty_cols(row: Row) -> list[int]:
    return [i for i, v in enumerate(row.raw) if v is not None and v != "" and not v.isspace()]


def _scan_blocks(source: GridSource, sheet: int) -> list[_Block]:
    blocks: list[_Block] = []
    cur: _Block | None = None
    prev_index = -1
    gap = 0
    for row in source.rows(sheet):
        if row.index > prev_index + 1:  # sparse sheet: missing rows are blank rows
            gap += row.index - prev_index - 1
            cur = None
        prev_index = row.index
        cols = _nonempty_cols(row)
        if not cols:
            gap += 1
            cur = None
            continue
        if cur is None:
            cur = _Block(row.index, gap)
            blocks.append(cur)
            gap = 0
        cur.end = row.index
        cur.n_rows += 1
        cc = cur.col_counts
        last = cols[-1]
        if last >= len(cc):
            pad = last + 1 - len(cc)
            cc.extend([0] * pad)
            cur.col_first.extend([row.index] * pad)
            cur.col_last.extend([row.index] * pad)
        cl = cur.col_last
        idx = row.index
        for i in cols:
            if not cc[i]:
                cur.col_first[i] = idx
            cc[i] += 1
            cl[i] = idx
        if len(cur.head) < HEAD_ROWS:
            cur.head.append(row)
    return blocks


def _col_groups(col_counts: list[int]) -> list[tuple[int, int]]:
    groups: list[tuple[int, int]] = []
    start = None
    for i, n in enumerate(col_counts):
        if n and start is None:
            start = i
        elif not n and start is not None:
            groups.append((start, i))
            start = None
    if start is not None:
        groups.append((start, len(col_counts)))
    return groups


def _family(row: Row, i: int, date1904: bool = False) -> str:
    if i >= len(row.raw):
        return MISSING
    fmt = row.formats.get(i) if row.formats else None
    return classify(row.raw[i], row.stype(i), i in row.quoted, fmt, date1904=date1904).family


def _segment(block: _Block, c0: int, c1: int, sheet: int, sheet_name: str, n_groups: int) -> Region:
    width = c1 - c0
    top = min(block.col_first[c0:c1])
    bottom = max(block.col_last[c0:c1])
    head = [r for r in block.head if top <= r.index <= bottom]
    if not head:
        # The region starts below the rows kept for header detection; expose it for manual review.
        return Region(sheet, sheet_name, "table", top, bottom, c0, c1, None, top, confidence=0.3,
                      notes=["region starts far below the top of its block; header not analysed"])
    n_rows = min(block.n_rows, bottom - top + 1)
    fams = [[_family(r, i) for i in range(c0, c1)] for r in head]
    fills = [sum(1 for f in fr if f != MISSING) for fr in fams]
    rows_in_group = max(block.col_counts[c0:c1]) if width else 0
    # Expected table width: columns filled in a meaningful share of the block's rows.
    strong = [i for i in range(c0, c1) if block.col_counts[i] >= max(1, 0.2 * rows_in_group)]
    exp_width = len(strong) if strong else width
    dense_min = 1 if exp_width == 1 else max(2, -(-exp_width // 2))
    notes: list[str] = []
    conf = 0.9
    first_dense = next((k for k, f in enumerate(fills) if f >= dense_min), None)
    tiny_table = exp_width == 2 and n_rows >= 2 and all(f == 2 for f in fills[: n_rows])
    if first_dense is None or (n_rows <= 3 and exp_width <= 2 and not tiny_table):
        return Region(sheet, sheet_name, "note", top, bottom, c0, c1, None, top,
                      confidence=0.6, notes=["short region without a table structure"])
    preamble = first_dense
    header_k = first_dense
    hf = fams[header_k]
    nonmissing = [f for f in hf if f != MISSING]
    # Header cells are words; a one-letter name such as "y" reads as a boolean word, so both count.
    wordy = sum(1 for f in nonmissing if f in (TXT, BOOLEAN))
    text_share = wordy / len(nonmissing) if nonmissing and any(f == TXT for f in nonmissing) else 0.0
    hrow = head[header_k]
    has_header = text_share >= 0.6
    if has_header and len(head) > header_k + 1:
        nxt = fams[header_k + 1]
        if all(f in (TXT, MISSING) for f in nxt) and all(f in (TXT, MISSING) for f in hf):
            # Text-only table: a header cannot be told from data by type alone.
            later = fams[header_k + 1:]
            typed = any(f in (NUM, DATE, BOOLEAN, ERR) for fr in later for f in fr)
            if not typed:
                conf -= 0.1
                notes.append("all columns are text; the first row is assumed to be the header")
    elif has_header and n_rows == header_k + 1:
        notes.append("header row without data rows")
        conf -= 0.2
    if not has_header:
        conf -= 0.3
        notes.append("no header row recognised; columns are numbered")
    if preamble:
        conf -= 0.05
        notes.append(f"{preamble} introductory row(s) before the table")
    header_row = head[header_k].index if has_header else None
    data_start_k = header_k + 1 if has_header else header_k
    data_start = head[data_start_k].index if data_start_k < len(head) else bottom + 1
    col_end = c1
    if has_header:
        cells = [i for i in range(c0, c1) if i < len(hrow.raw) and hrow.raw[i] not in (None, "")
                 and not hrow.raw[i].isspace()]
        h_end = cells[-1] + 1 if cells else c1
        beyond = [i for i in range(h_end, c1) if block.col_counts[i] >= 0.5 * rows_in_group]
        if beyond:
            notes.append(f"{len(beyond)} data column(s) without a header name")
            conf -= 0.1
        else:
            if h_end < c1:
                notes.append("some rows have more cells than the header")
            col_end = h_end
        names = [hrow.raw[i].strip() for i in cells]
        if len(set(names)) < len(names):
            notes.append("duplicate header names")
    else:
        col_end = (strong[-1] + 1) if strong else c1
    if col_end - c0 == 1:
        conf -= 0.2
        notes.append("single-column table")
    if n_groups > 1:
        conf -= 0.1
        notes.append("separated from a neighbouring region by an empty column")
    if bottom - data_start + 1 < 2:
        conf -= 0.2
    return Region(sheet, sheet_name, "table", top, bottom, c0, col_end, header_row, data_start,
                  preamble_rows=preamble, confidence=round(max(0.05, conf), 2), notes=notes)


def _data_signature(block: _Block, region: Region) -> list[str]:
    sig = []
    rows = [r for r in block.head if r.index >= region.data_start]
    for i in range(region.col_start, region.col_end):
        c = Counter(_family(r, i) for r in rows)
        c.pop(MISSING, None)
        sig.append(c.most_common(1)[0][0] if c else MISSING)
    return sig


def detect_regions(source: GridSource) -> list[Region]:
    regions: list[Region] = []
    for sh in source.sheets:
        blocks = _scan_blocks(source, sh.index)
        prev: list[tuple[_Block, Region, list[str]]] = []
        sheet_regions: list[Region] = []
        for block in blocks:
            groups = _col_groups(block.col_counts)
            current: list[tuple[_Block, Region, list[str]]] = []
            for c0, c1 in groups:
                reg = _segment(block, c0, c1, sh.index, sh.name, len(groups))
                merged = False
                for pb, preg, psig in prev:
                    if preg.kind != "table" or block.gap_before > MAX_MERGE_GAP or block.gap_before < 1:
                        continue
                    if preg.col_start != c0:
                        continue
                    first = block.head[0]
                    f2 = [_family(first, i) for i in range(preg.col_start, preg.col_end)]
                    typed_match = sum(1 for a, b in zip(psig, f2) if a == b and a not in (TXT, MISSING))
                    text_clash = sum(1 for a, b in zip(psig, f2) if a not in (TXT, MISSING) and b == TXT)
                    if typed_match >= 1 and text_clash == 0:
                        preg.bottom = block.end
                        preg.blank_rows_inside += block.gap_before
                        if "blank row(s) inside the table" not in preg.notes:
                            preg.notes.append("blank row(s) inside the table")
                        current.append((pb, preg, psig))
                        merged = True
                        break
                    if reg.kind == "table" and reg.col_end == preg.col_end and all(a in (TXT, MISSING) for a in psig):
                        note = "same width as the region above; they may be one table split by a blank row"
                        if note not in reg.notes:
                            reg.notes.append(note)
                            reg.confidence = round(max(0.05, reg.confidence - 0.1), 2)
                if not merged:
                    sheet_regions.append(reg)
                    current.append((block, reg, _data_signature(block, reg) if reg.kind == "table" else []))
            prev = current
        regions.extend(sheet_regions)
    _name_regions(regions, source)
    return regions


def _name_regions(regions: list[Region], source: GridSource) -> None:
    per_sheet: Counter = Counter()
    tables_in_sheet = Counter(r.sheet for r in regions if r.kind == "table")
    n_tab = n_note = 0
    for r in regions:
        if r.name:
            continue
        if r.kind == "note":
            n_note += 1
            r.name = f"note_{n_note}"
            continue
        n_tab += 1
        per_sheet[r.sheet] += 1
        if source.format == "xlsx":
            base = r.sheet_name or f"sheet{r.sheet + 1}"
            r.name = base if tables_in_sheet[r.sheet] == 1 else f"{base}#{per_sheet[r.sheet]}"
        else:
            r.name = f"table_{n_tab}"


def layout_kinds(source: GridSource, region: Region, max_rows: int = 8, max_cols: int = 40) -> dict:
    """Kinds of the first cells of a region (text, number, date ...), for a preview. Never a cell value."""
    last_col = min(region.col_end, region.col_start + max_cols)
    date1904 = bool(getattr(source, "info", {}).get("date1904"))
    rows = []
    for row in source.rows(region.sheet):
        if row.index < region.top:
            continue
        if row.index > region.bottom or len(rows) >= max_rows:
            break
        role = "header" if row.index == region.header_row else "data" if row.index >= region.data_start else "intro"
        kinds = ["empty" if i >= len(row.raw) or row.raw[i] is None else _family(row, i, date1904)
                 for i in range(region.col_start, last_col)]
        rows.append({"row": row.index + 1, "role": role, "kinds": kinds})
    return {"first_col": region.col_start + 1, "columns": last_col - region.col_start,
            "columns_total": region.col_end - region.col_start, "rows": rows,
            "rows_total": region.bottom - region.top + 1}
