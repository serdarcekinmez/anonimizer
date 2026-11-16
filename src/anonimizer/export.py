"""Export gate and writers. This module is the only place that writes output datasets.

Outputs are always fresh files built from generated cells: nothing is copied from the source
file, so workbook metadata, comments, formulas, hidden content and styles cannot carry over.
The gate refuses any release tier above the one derived by the privacy assessment.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import json
import os
import re
import zipfile

from . import NON_CERTIFICATION_STATEMENT, __version__
from .policy import EXTERNAL_CANDIDATE, LOCAL_ONLY, RESTRICTED, TIER_ORDER

_NEWLINES = {"lf": "\n", "crlf": "\r\n", "cr": "\r"}
_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_FIXED_TIME = (2000, 1, 1, 0, 0, 0)
MAX_LEAD = 50
MAX_GAP = 20

TIER_LABELS = {
    LOCAL_ONLY: "LOCAL_ONLY - keep on this machine. Not assessed for sharing. Treat as confidential.",
    RESTRICTED: "RESTRICTED - may be shared only inside the organisation that controls the source data, "
                "under its own rules. Not assessed as anonymous.",
    EXTERNAL_CANDIDATE: "EXTERNAL_CANDIDATE",
}


class ExportRefused(Exception):
    pass


def col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _place(contract: dict, dataset: dict) -> dict[str, dict]:
    """Compute where each region goes in the output: {name: {sheet, top, col, height}} (0-based)."""
    heights = {}
    for name, t in dataset["tables"].items():
        heights[name] = len(t["preamble"]) + (1 if t["header"] is not None else 0) + len(t["rows"])
    for name, rows in dataset["notes"].items():
        heights[name] = len(rows)
    by_sheet: dict[str, list] = {}
    for r in contract["layout"]["regions"]:
        if r["name"] in heights:
            by_sheet.setdefault(r["sheet"], []).append(r)
    out = {}
    for sheet, regs in by_sheet.items():
        regs.sort(key=lambda r: (r["first_row"], r["first_col"]))
        bands: list[list] = []
        for r in regs:
            if bands and r["first_row"] <= max(x["last_row"] for x in bands[-1]):
                bands[-1].append(r)
            else:
                bands.append([r])
        prev_src_bottom = 0
        cursor = 0
        for bi, band in enumerate(bands):
            src_top = min(x["first_row"] for x in band)
            gap = max(0, src_top - prev_src_bottom - 1)
            top = cursor + min(gap, MAX_LEAD if bi == 0 else MAX_GAP)
            bottom = top
            for r in band:
                rtop = top + min(r["first_row"] - src_top, MAX_LEAD)
                out[r["name"]] = {"sheet": sheet, "top": rtop, "col": r["first_col"] - 1, "height": heights[r["name"]]}
                bottom = max(bottom, rtop + heights[r["name"]])
            cursor = bottom
            prev_src_bottom = max(x["last_row"] for x in band)
    return out


def build_grids(contract: dict, dataset: dict) -> tuple[dict[str, dict], dict]:
    """Return ({sheet: {(row, col): OutCell}}, positions) with positions[(table, data_row)] = row index."""
    from .synth import OutCell

    place = _place(contract, dataset)
    grids: dict[str, dict] = {}
    positions: dict = {}
    for name, rows in dataset["notes"].items():
        p = place[name]
        g = grids.setdefault(p["sheet"], {})
        for i, cells in enumerate(rows):
            for col, text in cells:
                g[(p["top"] + i, p["col"] + col)] = OutCell(text)
    for name, t in dataset["tables"].items():
        p = place[name]
        g = grids.setdefault(p["sheet"], {})
        r = p["top"]
        for cells in t["preamble"]:
            for col, text in cells:
                g[(r, p["col"] + col)] = OutCell(text)
            r += 1
        if t["header"] is not None:
            for j, h in enumerate(t["header"]):
                g[(r, p["col"] + j)] = OutCell(h)
            positions[(name, "header")] = r
            r += 1
        for row in t["rows"]:
            if row["kind"] == "data":
                positions[(name, row["data_row"])] = r
                for j, cell in enumerate(row["cells"] + row["extra"]):
                    if cell.text is not None:
                        g.setdefault((r, p["col"] + j), cell)
            else:
                positions[(name, "blank", row["after_data_row"])] = r
                g.setdefault(("blank", r), None)
            r += 1
        positions[(name, "origin")] = (p["top"], p["col"])
    return grids, positions


def _csv_bytes(grid: dict, layout: dict) -> tuple[bytes, dict[int, int]]:
    d = layout.get("delimiter") or ","
    q = layout.get("quotechar") or '"'
    nl = _NEWLINES.get(layout.get("newline") or "lf", "\n")
    by_row: dict[int, dict[int, object]] = {}
    last = -1
    for key, cell in grid.items():
        if key[0] == "blank":
            last = max(last, key[1])
            continue
        r, c = key
        by_row.setdefault(r, {})[c] = cell
        last = max(last, r)
    lines = []
    line_of: dict[int, int] = {}
    line = 1
    for r in range(last + 1):
        cells = by_row.get(r)
        line_of[r] = line
        if not cells:
            lines.append("")
            line += 1
            continue
        fields = []
        for c in range(max(cells) + 1):
            cell = cells.get(c)
            text = "" if cell is None or cell.text is None else cell.text
            if (cell is not None and cell.quoted) or d in text or q in text or "\n" in text or "\r" in text:
                text = q + text.replace(q, q + q) + q
            fields.append(text)
        rec = d.join(fields)
        lines.append(rec)
        line += 1 + rec.count("\n") + rec.count("\r") - rec.count("\r\n")
    body = nl.join(lines)
    if lines and layout.get("final_newline", True):
        body += nl
    enc = layout.get("encoding") or "utf-8"
    try:
        data = body.encode(enc, errors="replace")
    except LookupError:
        data = body.encode("utf-8")
    return data, line_of


def _xlsx_bytes(grids: dict[str, dict], layout: dict) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    fixed = _dt.datetime(*_FIXED_TIME)
    wb.properties.creator = "Anonimizer"
    wb.properties.lastModifiedBy = "Anonimizer"
    wb.properties.created = fixed
    wb.properties.modified = fixed
    if layout.get("date1904"):
        from openpyxl.utils.datetime import CALENDAR_MAC_1904
        wb.epoch = CALENDAR_MAC_1904
    names = [s for s in layout.get("sheets", []) if s in grids] or list(grids)
    for name in names:
        ws = wb.create_sheet(title=name[:31] or "Sheet")
        grid = grids.get(name, {})
        for key in sorted(k for k in grid if k[0] != "blank"):
            cell = grid[key]
            if cell is None or cell.text is None or cell.kind == "":
                continue
            r, c = key
            target = ws.cell(row=r + 1, column=c + 1)
            text = cell.text
            if cell.kind == "n":
                try:
                    target.value = int(text) if text.lstrip("-").isdigit() else float(text)
                except ValueError:
                    target.value = text
                    target.data_type = "s"
                if cell.fmt:
                    target.number_format = cell.fmt
            elif cell.kind == "d":
                try:
                    if "T" in text:
                        target.value = _dt.datetime.fromisoformat(text)
                    elif ":" in text:
                        target.value = _dt.time.fromisoformat(text)
                    else:
                        target.value = _dt.date.fromisoformat(text)
                except ValueError:
                    target.value = text
                    target.data_type = "s"
                target.number_format = cell.fmt or ("yyyy-mm-dd hh:mm:ss" if "T" in text else
                                                    "hh:mm:ss" if ":" in text else "yyyy-mm-dd")
            elif cell.kind == "b":
                target.value = text == "1"
            elif cell.kind == "e":
                target.value = text
                target.data_type = "e"
            else:
                target.value = _ILLEGAL_XML.sub("", text)
                target.data_type = "s"
    if not wb.sheetnames:
        wb.create_sheet("Sheet1")
    buf = io.BytesIO()
    wb.save(buf)
    # Normalise archive timestamps so the same contract and seed give identical bytes.
    src = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            info = zipfile.ZipInfo(item.filename, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            dst.writestr(info, src.read(item.filename))
    return out.getvalue()


def render_dataset(contract: dict, dataset: dict) -> tuple[bytes, str, dict]:
    """Serialise the dataset. Returns (bytes, extension, output recipe) and fills manifest locations."""
    layout = contract["layout"]
    grids, positions = build_grids(contract, dataset)
    fmt = layout["format"]
    if fmt == "csv":
        grid = next(iter(grids.values()), {})
        data, line_of = _csv_bytes(grid, layout)
        ext = ".tsv" if layout.get("delimiter") == "\t" else ".csv"
    else:
        data, line_of = _xlsx_bytes(grids, layout), {}
        ext = ".xlsx"
    tables = []
    for name, t in dataset["tables"].items():
        top, col = positions[(name, "origin")]
        hrow = positions.get((name, "header"))
        first = top + len(t["preamble"]) + (1 if t["header"] is not None else 0)
        width = len(t["columns"])
        tables.append({"name": name, "sheet": t["sheet"] if fmt == "xlsx" else None, "kind": "table",
                       "include": True, "header_row": None if hrow is None else hrow + 1,
                       "first_row": top + 1, "first_data_row": first + 1,
                       "last_data_row": first + len(t["rows"]), "first_col": col + 1, "last_col": col + width,
                       "source": "user"})
    for e in dataset["manifest"]:
        t = dataset["tables"][e["table"]]
        _top, col0 = positions[(e["table"], "origin")]
        cpos = t["columns"].index(e["column"]) + 1 if e["column"] in t["columns"] else None
        e["column_position"] = cpos
        locs = []
        rows = [(positions.get((e["table"], dr)), dr) for dr in e["data_rows"]]
        if e.get("blank_after_data_row") is not None:
            rows.append((positions.get((e["table"], "blank", e["blank_after_data_row"])), None))
        for r, _dr in rows:
            if r is None:
                continue
            loc = {"row": r + 1}
            if fmt == "csv":
                loc["line"] = line_of.get(r, r + 1)
                if cpos:
                    loc["field"] = col0 + cpos
            elif cpos:
                loc["cell"] = f"{col_letter(col0 + cpos)}{r + 1}"
            locs.append(loc)
        e["locations"] = locs
    recipe = {"recipe_version": 1,
              "file": {"encoding": layout.get("encoding"), "delimiter": layout.get("delimiter"),
                       "quotechar": layout.get("quotechar") or '"'},
              "extra_markers": contract.get("extra_markers", []), "tables": tables}
    return data, ext, recipe


def manifest_csv(manifest: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["scenario_id", "class", "description", "table", "column", "data_rows", "locations", "note"])
    for e in manifest:
        locs = "; ".join(loc.get("cell") or (f"line {loc['line']}" + (f" field {loc['field']}" if "field" in loc else ""))
                         if ("cell" in loc or "line" in loc) else f"row {loc['row']}" for loc in e["locations"])
        w.writerow([e["scenario_id"], e["class"], e["description"], e["table"], e["column_name"] or "",
                    " ".join(str(r) for r in e["data_rows"]), locs, e["note"] or ""])
    return buf.getvalue()


def _write(path: str, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def _json(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def default_register_path() -> str:
    env = os.environ.get("ANONIMIZER_REGISTER")
    if env:
        return env
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(state, "anonimizer", "release_register.jsonl")


def export_bundle(out_dir: str, *, dataset_bytes: bytes, dataset_ext: str, documents: dict[str, object],
                  assessment: dict, requested_tier: str | None = None, base_name: str = "synthetic",
                  register_path: str | None = None, now: _dt.datetime | None = None) -> dict:
    """Write the bundle. ``documents`` maps file names to JSON-serialisable objects or text.

    The release tier comes from the assessment record. A higher requested tier is refused;
    there is no override.
    """
    tier = assessment["release_tier"]
    if tier not in TIER_ORDER:
        raise ExportRefused("the assessment record carries an unknown release tier")
    if requested_tier is not None:
        if requested_tier not in TIER_ORDER:
            raise ExportRefused("unknown release tier requested")
        if TIER_ORDER[requested_tier] > TIER_ORDER[tier]:
            reasons = "; ".join(assessment.get("tier_reasons", [])) or "see the assessment record"
            raise ExportRefused(f"release tier {requested_tier} refused: the assessment allows {tier} ({reasons})")
        tier = requested_tier
    if tier == EXTERNAL_CANDIDATE:
        raise ExportRefused("the EXTERNAL_CANDIDATE tier is not available in this release")
    now = now or _dt.datetime.now(_dt.timezone.utc)
    os.makedirs(out_dir, mode=0o700, exist_ok=True)
    files = []
    name = base_name + dataset_ext
    _write(os.path.join(out_dir, name), dataset_bytes)
    files.append(name)
    label = {
        "release_tier": tier, "label": TIER_LABELS[tier], "transformation_class": assessment["transformation_class"],
        "assessment_status": assessment["assessment_status"], "policy": assessment["policy"]["id"],
        "policy_version": assessment["policy"]["version"], "record_id": assessment["record_id"],
        "created_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "tool_version": __version__,
        "statement": NON_CERTIFICATION_STATEMENT,
    }
    docs = dict(documents)
    docs["assessment_record.json"] = assessment
    docs["release_label.json"] = label
    docs["CLASSIFICATION.txt"] = (
        f"{TIER_LABELS[tier]}\n\nTransformation class: {assessment['transformation_class']}\n"
        f"Assessment status: {assessment['assessment_status']} (policy {assessment['policy']['id']} "
        f"v{assessment['policy']['version']})\nRecord: {assessment['record_id']}\n\n{NON_CERTIFICATION_STATEMENT}\n"
    )
    for fname, obj in sorted(docs.items()):
        if os.path.basename(fname) != fname or fname.startswith("."):
            raise ExportRefused("document names must be plain file names")
        data = obj.encode("utf-8") if isinstance(obj, str) else obj if isinstance(obj, bytes) else _json(obj)
        _write(os.path.join(out_dir, fname), data)
        files.append(fname)
    entry = {"created_utc": label["created_utc"], "record_id": assessment["record_id"], "release_tier": tier,
             "transformation_class": assessment["transformation_class"],
             "assessment_status": assessment["assessment_status"], "policy": assessment["policy"]["id"],
             "output_directory": os.path.abspath(out_dir), "files": sorted(files)}
    register_path = register_path or default_register_path()
    registered = False
    try:
        os.makedirs(os.path.dirname(register_path), mode=0o700, exist_ok=True)
        fd = os.open(register_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        registered = True
    except OSError:
        registered = False
    return {"out_dir": os.path.abspath(out_dir), "files": sorted(files), "release_tier": tier,
            "dataset_file": name, "register": register_path if registered else None}
