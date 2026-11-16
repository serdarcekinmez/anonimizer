"""A plain schema-driven mock generator, used only as a comparison baseline.

It does what a typical "make me N rows like this schema" request does: it looks at the header
and a sample of the first rows, guesses one type per column and emits clean values of that
type. It has no knowledge of anomalies outside the sample. Standard library and openpyxl only;
it does not use anonimizer.
"""

from __future__ import annotations

import csv
import datetime as dt
import random
import re

SAMPLE_ROWS = 200
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}$")
_DATE_DOT = re.compile(r"\d{2}\.\d{2}\.\d{4}$")
_INT = re.compile(r"-?\d+$")
_DEC = re.compile(r"-?\d+[.,]\d+$")


def _sample_csv(path: str, delimiter: str, encoding: str, header_row: int) -> tuple[list[str], list[list[str]]]:
    with open(path, encoding=encoding, newline="") as fh:
        rows = list(csv.reader(fh, delimiter=delimiter))
    header = rows[header_row - 1]
    data = [r for r in rows[header_row:header_row + SAMPLE_ROWS] if len(r) == len(header)]
    return header, data


def _sample_xlsx(path: str, sheet: str, header_row: int, n_cols: int) -> tuple[list[str], list[list[str]]]:
    import openpyxl

    ws = openpyxl.load_workbook(path, read_only=True, data_only=True)[sheet]
    rows = list(ws.iter_rows(min_row=header_row, max_row=header_row + SAMPLE_ROWS, max_col=n_cols, values_only=True))
    header = [str(h) for h in rows[0]]
    data = [["" if v is None else (v.isoformat()[:10] if isinstance(v, (dt.date, dt.datetime)) else str(v)) for v in r]
            for r in rows[1:]]
    return header, data


def _guess(values: list[str]) -> str:
    vals = [v for v in values if v != ""]
    if not vals:
        return "text"
    for name, rx in (("int", _INT), ("decimal", _DEC), ("date", _DATE), ("date_dot", _DATE_DOT)):
        if sum(1 for v in vals if rx.match(v)) >= 0.9 * len(vals):
            return name
    if all(v in ("True", "False") for v in vals):
        return "bool"
    return "category" if len(set(vals)) <= 12 else "text"


def generate(header: list[str], sample: list[list[str]], n: int, seed: int = 0) -> list[list[str]]:
    rng = random.Random(seed)
    cols = list(zip(*sample)) if sample else [[] for _ in header]
    kinds = [_guess(list(c)) for c in cols]
    nullable = [sum(1 for v in c if v == "") / max(1, len(c)) for c in cols]
    out = []
    for i in range(n):
        row = []
        for j, kind in enumerate(kinds):
            if nullable[j] > 0.05 and rng.random() < nullable[j]:
                row.append("")
            elif kind == "int":
                row.append(str(rng.randint(1, 9999) if j else 1 + i))
            elif kind == "decimal":
                comma = any("," in v for v in cols[j])
                v = f"{rng.uniform(1, 5000):.2f}"
                row.append(v.replace(".", ",") if comma else v)
            elif kind == "date":
                row.append((dt.date(2020, 1, 1) + dt.timedelta(days=rng.randint(0, 1400))).isoformat())
            elif kind == "date_dot":
                row.append((dt.date(2020, 1, 1) + dt.timedelta(days=rng.randint(0, 1400))).strftime("%d.%m.%Y"))
            elif kind == "bool":
                row.append(rng.choice(["True", "False"]))
            elif kind == "category":
                row.append(f"cat_{rng.randint(1, max(2, len(set(cols[j]))))}")
            else:
                row.append(f"text_{rng.randint(1000, 999999)}")
        out.append(row)
    return out


def write_csv(path: str, header: list[str], rows: list[list[str]], delimiter: str = ",") -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=delimiter, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def baseline_for_table(path: str, out_path: str, n: int, *, fmt: str, header_row: int, n_cols: int,
                       delimiter: str = ",", encoding: str = "utf-8", sheet: str | None = None, seed: int = 0) -> None:
    if fmt == "xlsx":
        header, sample = _sample_xlsx(path, sheet or "", header_row, n_cols)
    else:
        header, sample = _sample_csv(path, delimiter, encoding, header_row)
    write_csv(out_path, header, generate(header, sample, n, seed))
