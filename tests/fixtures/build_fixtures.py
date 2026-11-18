"""Builds the synthetic product fixtures and their ground truth.

Everything here is invented: names are random syllables, e-mail addresses use example.org.
This script does not import anonimizer. The ground truth is written from what the script
plants, so it is independent of the detector it is later compared with.

Usage:  python tests/fixtures/build_fixtures.py [output_dir]
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import random
import re
import sys
import zipfile
from collections import Counter

CONS, VOW = "bcdfghjklmnprstvz", "aeiou"
CANARY_NAME = "Xqzvanta Wolfhaven77"
CANARY_NOTE = "CANARY-NOTE-7731 call back"
CANARY_COMMENT = "ZZTOP-SECRET-4242"
CANARY_SKU_DESC = "Quuxinator Prototype-K9"


def word(rng: random.Random, n: int, cap: bool = False) -> str:
    start = rng.randrange(2)
    w = "".join(rng.choice(CONS if (i + start) % 2 == 0 else VOW) for i in range(n))
    return w.capitalize() if cap else w


def rand_date(rng: random.Random, y0: int, y1: int) -> dt.date:
    a = dt.date(y0, 1, 1).toordinal()
    b = dt.date(y1, 12, 31).toordinal()
    return dt.date.fromordinal(rng.randint(a, b))


def csv_line(fields: list, delim: str = ",", force_quote: set | None = None) -> str:
    out = []
    for i, f in enumerate(fields):
        if (force_quote and i in force_quote) or delim in f or '"' in f or "\n" in f or "\r" in f:
            f = '"' + f.replace('"', '""') + '"'
        out.append(f)
    return delim.join(out)


class Truth:
    def __init__(self, fixture: str):
        self.fixture = fixture
        self.items: dict[tuple, dict] = {}
        self.tables: list[dict] = []
        self.relationships: list[dict] = []
        self.canaries: list[str] = []

    def add(self, table: str, column: str | None, cls: str, count: int = 1, rows: list[int] | None = None,
            note: str = "") -> None:
        key = (table, column, cls)
        it = self.items.setdefault(key, {"table": table, "column": column, "class": cls, "count": 0, "rows": [],
                                         "notes": []})
        it["count"] += count
        it["rows"] += rows or []
        if note and note not in it["notes"]:
            it["notes"].append(note)

    def to_dict(self) -> dict:
        return {"fixture": self.fixture, "tables": self.tables, "relationships": self.relationships,
                "canaries": self.canaries,
                "anomalies": sorted(self.items.values(), key=lambda x: (x["table"], x["column"] or "", x["class"]))}


# ---------------------------------------------------------------------------------------------
# Fixture 1: conventional CSV with rare, hidden anomalies
# ---------------------------------------------------------------------------------------------
NOTES = ["Prefers contact by email", "Asked for a paper invoice", "Second address on file", "Call after six",
         "Uses the mobile app", "Pays by transfer", "Requested a callback", "Moved last year"]
COUNTRIES = ["FR", "DE", "ES", "IT", "TR", "NL", "BE", "PT"]
HEADER1 = ["customer_id", "full_name", "email", "signup_date", "country", "balance", "loyalty_points", "status",
           "last_contact", "notes"]


def build_customers(path: str, n_rows: int = 5000, seed: int = 20261116, deep_text: str = "pending review") -> dict:
    """Conventional CSV. The single text value in ``balance`` sits at 97.5 % of the file."""
    rng = random.Random(seed)
    t = Truth(os.path.basename(path))
    T = "table_1"
    rows: list[list[str]] = []
    for i in range(n_rows):
        first, last = word(rng, rng.randint(4, 7), True), word(rng, rng.randint(5, 8), True)
        rows.append([
            str(100001 + i), f"{first} {last}", f"{first.lower()}.{last.lower()}{i % 100}@example.org",
            rand_date(rng, 2015, 2023).isoformat(), rng.choices(COUNTRIES, [30, 20, 12, 10, 10, 8, 6, 4])[0],
            f"{rng.uniform(10, 9000):.2f}", str(rng.randint(10, 5000)),
            rng.choices(["active", "inactive", "pending"], [70, 20, 10])[0],
            rand_date(rng, 2022, 2024).isoformat(), rng.choice(NOTES) if rng.random() < 0.10 else "",
        ])
    C = {h: i for i, h in enumerate(HEADER1)}
    free = list(range(20, n_rows - 20))
    rng.shuffle(free)
    used: set[int] = set()

    def pick() -> int:
        while True:
            i = free.pop()
            if i not in used:
                used.add(i)
                return i

    def rownum(i: int) -> int:  # 1-based record number in the file (header is record 1)
        return i + 2

    force_quote: dict[int, set] = {}
    # -- balance ---------------------------------------------------------------------------
    deep = int(n_rows * 0.975)
    used.add(deep)
    rows[deep][C["balance"]] = deep_text
    t.add(T, "balance", "type.text_in_number", 1, [rownum(deep)], "single text value deep in the file")
    for _ in range(3):
        i = pick()
        rows[i][C["balance"]] = "N/A"
        t.add(T, "balance", "missing.marker", 1, [rownum(i)], "N/A")
    i = pick()
    rows[i][C["balance"]] = "-"
    t.add(T, "balance", "missing.marker", 1, [rownum(i)], "-")
    for _ in range(2):
        i = pick()
        rows[i][C["balance"]] = ""
        t.add(T, "balance", "missing.empty", 1, [rownum(i)])
    for _ in range(4):
        i = pick()
        rows[i][C["balance"]] = "0.00"
        t.add(T, "balance", "numeric.zero", 1, [rownum(i)])
    for _ in range(2):
        i = pick()
        rows[i][C["balance"]] = "-125.50"
        t.add(T, "balance", "numeric.negative", 1, [rownum(i)])
    i = pick()
    rows[i][C["balance"]] = "1234,56"
    t.add(T, "balance", "format.number_deviation", 1, [rownum(i)], "decimal comma")
    # -- loyalty_points --------------------------------------------------------------------
    i = pick()
    rows[i][C["loyalty_points"]] = "NaN"
    t.add(T, "loyalty_points", "missing.marker", 1, [rownum(i)], "NaN")
    i = pick()
    rows[i][C["loyalty_points"]] = "  "
    t.add(T, "loyalty_points", "missing.whitespace", 1, [rownum(i)])
    i = pick()
    rows[i][C["loyalty_points"]] = "12 pts"
    t.add(T, "loyalty_points", "type.text_in_number", 1, [rownum(i)])
    # -- signup_date -----------------------------------------------------------------------
    for bad in ("2023-02-30", "2021-13-01"):
        i = pick()
        rows[i][C["signup_date"]] = bad
        t.add(T, "signup_date", "value.invalid_date", 1, [rownum(i)])
    for alt in ("25/12/2019", "17/03/2021", "31/08/2016"):
        i = pick()
        rows[i][C["signup_date"]] = alt
        t.add(T, "signup_date", "format.date_deviation", 1, [rownum(i)], "DD/MM/YYYY")
    i = pick()
    rows[i][C["signup_date"]] = ""
    t.add(T, "signup_date", "missing.empty", 1, [rownum(i)])
    # -- email -------------------------------------------------------------------------------
    i = pick()
    rows[i][C["email"]] = "null"
    t.add(T, "email", "missing.marker", 1, [rownum(i)], "null")
    i = pick()
    rows[i][C["email"]] = " " + rows[i][C["email"]] + " "
    t.add(T, "email", "text.padded", 1, [rownum(i)])
    # -- country -----------------------------------------------------------------------------
    i = pick()
    rows[i][C["country"]] = "fr"
    t.add(T, "country", "text.rare_pattern", 1, [rownum(i)], "lower-case code")
    t.add(T, "country", "category.rare_value", 1, [], "one category occurs once")
    i = pick()
    rows[i][C["country"]] = "UNKNOWN"
    t.add(T, "country", "missing.marker", 1, [rownum(i)], "UNKNOWN")
    # -- notes -------------------------------------------------------------------------------
    i = pick()
    rows[i][C["notes"]] = "First line\nsecond line"
    t.add(T, "notes", "text.multiline", 1, [rownum(i)])
    t.add(T, "notes", "text.rare_pattern", 1, [rownum(i)])
    i = pick()
    rows[i][C["notes"]] = '=HYPERLINK("http://example.org")'
    t.add(T, "notes", "text.formula_like", 1, [rownum(i)])
    t.add(T, "notes", "text.rare_pattern", 1, [rownum(i)])
    i = pick()
    rows[i][C["notes"]] = CANARY_NOTE
    t.add(T, "notes", "text.rare_pattern", 1, [rownum(i)], "canary")
    for _ in range(2):
        i = pick()
        rows[i][C["notes"]] = ""
        force_quote[i] = {C["notes"]}
        t.add(T, "notes", "missing.quoted_empty", 1, [rownum(i)])
    # -- canary name -------------------------------------------------------------------------
    i = pick()
    rows[i][C["full_name"]] = CANARY_NAME
    t.add(T, "full_name", "text.rare_pattern", 1, [rownum(i)], "canary")
    t.canaries += [CANARY_NAME, "Wolfhaven77", CANARY_NOTE, "CANARY-NOTE-7731", deep_text]
    # -- keys and rows -----------------------------------------------------------------------
    i, j = pick(), pick()
    rows[max(i, j)][C["customer_id"]] = rows[min(i, j)][C["customer_id"]]
    t.add(T, "customer_id", "key.duplicate", 1, [rownum(max(i, j))])
    for _ in range(2):
        i, j = pick(), pick()
        rows[max(i, j)] = list(rows[min(i, j)])
        t.add(T, None, "row.duplicate", 1, [rownum(max(i, j))])
        t.add(T, "customer_id", "key.duplicate", 1, [rownum(max(i, j))], "from a duplicate row")
    i = pick()
    rows[i] = rows[i] + ["EXTRA"]
    t.add(T, None, "row.ragged_long", 1, [rownum(i)])
    i = pick()
    rows[i] = rows[i][:-2]
    t.add(T, None, "row.ragged_short", 1, [rownum(i)])
    # Counts that follow from the base data.
    empty_notes = sum(1 for i, r in enumerate(rows) if len(r) > C["notes"] and r[C["notes"]] == "" and i not in force_quote)
    t.add(T, "notes", "missing.empty", empty_notes, [], "most rows have no note")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(csv_line(HEADER1) + "\n")
        for i, r in enumerate(rows):
            fh.write(csv_line(r, ",", force_quote.get(i)) + "\n")
    t.tables.append({"name": T, "rows": n_rows, "columns": len(HEADER1), "header_row": 1})
    return t.to_dict()


# ---------------------------------------------------------------------------------------------
# Fixture 2: irregular TSV, several regions, cp1252, CRLF, decimal commas
# ---------------------------------------------------------------------------------------------
COMMENTS = ["livraison différée", "client fidèle", "à rappeler", "remise accordée"]
CITIES = ["Ventoux", "Marcilly", "Brenac", "Solane", "Thivet", "Ormesse"]


def build_orders_tsv(path: str, n_orders: int = 1200, n_customers: int = 150, seed: int = 4242) -> dict:
    rng = random.Random(seed)
    t = Truth(os.path.basename(path))
    A, B = "table_1", "table_2"
    lines: list[str] = []
    lines.append("Export des commandes – région Ouest")
    lines.append("Généré le 05.01.2024\tservice comptabilité")
    lines.append("")
    header_a = ["order_no", "customer_ref", "order_date", "quantity", "amount_eur", "channel", "comment"]
    lines.append("\t".join(header_a))
    first_data_record = len(lines) + 1
    codes = [f"C-{k:04d}" for k in range(1, n_customers + 1)]
    orders = []
    refs = codes + [rng.choice(codes) for _ in range(n_orders - n_customers)]
    rng.shuffle(refs)
    for i in range(n_orders):
        d = rand_date(rng, 2022, 2023)
        amount = rng.uniform(5, 4000)
        orders.append([f"ORD-{i + 1:06d}", refs[i], d.strftime("%d.%m.%Y"), str(rng.randint(1, 40)),
                       f"{amount:.2f}".replace(".", ","), rng.choices(["web", "store", "phone"], [6, 3, 1])[0],
                       rng.choice(COMMENTS) if rng.random() < 0.08 else ""])
    CA = {h: i for i, h in enumerate(header_a)}
    free = list(range(10, n_orders - 10))
    rng.shuffle(free)
    blank_after = n_orders // 2

    def rownum(i: int) -> int:
        return first_data_record + i + (1 if i >= blank_after else 0)

    def pick() -> int:
        return free.pop()

    for dangling in ("C-9999", "C-9998"):
        i = pick()
        orders[i][CA["customer_ref"]] = dangling
        t.add(A, "customer_ref", "key.dangling_reference", 1, [rownum(i)])
    i = pick()
    orders[i][CA["customer_ref"]] = "n/a"
    t.add(A, "customer_ref", "missing.marker", 1, [rownum(i)], "n/a")
    i = pick()
    orders[i][CA["order_date"]] = "31.02.2023"
    t.add(A, "order_date", "value.invalid_date", 1, [rownum(i)])
    for _ in range(2):
        i = pick()
        orders[i][CA["order_date"]] = "2023-07-14"
        t.add(A, "order_date", "format.date_deviation", 1, [rownum(i)], "ISO date among dotted dates")
    i = pick()
    orders[i][CA["quantity"]] = "douze"
    t.add(A, "quantity", "type.text_in_number", 1, [rownum(i)])
    t.canaries.append("douze")
    i = pick()
    orders[i][CA["quantity"]] = ""
    t.add(A, "quantity", "missing.empty", 1, [rownum(i)])
    i = pick()
    orders[i][CA["quantity"]] = "-3"
    t.add(A, "quantity", "numeric.negative", 1, [rownum(i)])
    for v in ("1.234,50", "2.019,00"):
        i = pick()
        orders[i][CA["amount_eur"]] = v
        t.add(A, "amount_eur", "format.number_deviation", 1, [rownum(i)], "thousands dot")
    i = pick()
    orders[i][CA["amount_eur"]] = "45,00 €"
    t.add(A, "amount_eur", "format.number_deviation", 1, [rownum(i)], "currency suffix")
    i = pick()
    orders[i][CA["amount_eur"]] = "0,00"
    t.add(A, "amount_eur", "numeric.zero", 1, [rownum(i)])
    i = pick()
    orders[i][CA["amount_eur"]] = "-"
    t.add(A, "amount_eur", "missing.marker", 1, [rownum(i)], "-")
    i = pick()
    orders[i][CA["order_no"]] = " " + orders[i][CA["order_no"]]
    t.add(A, "order_no", "text.padded", 1, [rownum(i)])
    i = pick()
    orders[i][CA["comment"]] = CANARY_COMMENT
    t.add(A, "comment", "text.rare_pattern", 1, [rownum(i)], "canary")
    t.canaries.append(CANARY_COMMENT)
    ragged = pick()
    t.add(A, None, "row.ragged_long", 1, [rownum(ragged)], "one trailing empty field")
    t.add(A, None, "row.blank_inside_table", 1, [first_data_record + blank_after])
    n_accent = sum(1 for o in orders if any(ord(ch) > 127 for ch in o[CA["comment"]]))
    t.add(A, "comment", "text.non_ascii", n_accent, [], "accented comments")
    t.add(A, "comment", "missing.empty", sum(1 for o in orders if o[CA["comment"]] == ""), [])
    mult = Counter(Counter(o[CA["customer_ref"]] for o in orders if o[CA["customer_ref"]] != "n/a").values())
    t.add(A, "customer_ref", "key.multiplicity", sum(mult.values()), [], "distinct reference values")
    for i, o in enumerate(orders):
        if i == blank_after:
            lines.append("")
        lines.append("\t".join(o) + ("\t" if i == ragged else ""))
    lines += ["", ""]
    header_b = ["customer_code", "name", "city", "since", "vip"]
    lines.append("\t".join(header_b))
    b_first = len(lines) + 1
    custs = []
    for code in codes:
        custs.append([code, f"{word(rng, rng.randint(5, 8), True)} SARL", rng.choice(CITIES),
                      str(rng.randint(2012, 2023)), rng.choices(["oui", "non"], [1, 4])[0]])
    custs[37][4] = "OUI"
    t.add(B, "vip", "format.boolean_deviation", 1, [b_first + 37])
    custs[90][4] = "?"
    t.add(B, "vip", "missing.marker", 1, [b_first + 90], "?")
    custs[12][2] = ""
    t.add(B, "city", "missing.empty", 1, [b_first + 12])
    lines += ["\t".join(c) for c in custs]
    lines += ["", f"Fin du fichier - {n_orders} commandes"]
    with open(path, "wb") as fh:
        fh.write(("\r\n".join(lines) + "\r\n").encode("cp1252"))
    t.tables += [{"name": A, "rows": n_orders, "columns": 7, "header_row": 4},
                 {"name": B, "rows": n_customers, "columns": 5, "header_row": b_first - 1}]
    t.relationships.append({"from": f"{A}.customer_ref", "to": f"{B}.customer_code", "dangling_rows": 2})
    d = t.to_dict()
    d["file"] = {"encoding": "cp1252", "delimiter": "\t", "newline": "crlf", "notes": 2}
    return d


# ---------------------------------------------------------------------------------------------
# Fixture 3: XLSX workbook with mixed cell types
# ---------------------------------------------------------------------------------------------
DESCRIPTIONS = ["Widget blue", "Widget red", "Gasket small", "Gasket large", "Bracket steel", "Bracket alu",
                "Valve brass", "Valve inox", "Cable short", "Cable long"]


def build_inventory_xlsx(path: str, n_stock: int = 400, n_suppliers: int = 40, seed: int = 777) -> dict:
    import openpyxl
    from openpyxl.comments import Comment
    from openpyxl.workbook.defined_name import DefinedName

    rng = random.Random(seed)
    t = Truth(os.path.basename(path))
    S1, S2, SUP, ARC = "Stock#1", "Stock#2", "Suppliers", "Archive"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Stock"
    ws["A1"] = "Inventory snapshot (fictional)"
    ws.merge_cells("A1:D1")
    header = ["sku", "description", "supplier_id", "qty", "unit_price", "received", "active", "total"]
    for j, h in enumerate(header, start=1):
        ws.cell(row=3, column=j, value=h)
    first = 4
    cached: dict[str, str] = {}
    plan = list(range(10, n_stock - 10))
    rng.shuffle(plan)

    def pick() -> int:
        return plan.pop()

    special = {name: pick() for name in ("dangling", "qty_text1", "qty_text2", "qty_err", "qty_tbd", "qty_e1", "qty_e2",
                                         "qty_e3", "qty_zero", "price_text", "price_neg", "date_text", "date_marker",
                                         "date_e1", "date_e2", "bool_text", "canary")}
    for i in range(n_stock):
        r = first + i
        qty = rng.randint(1, 500)
        price = round(rng.uniform(1, 300), 2)
        ws.cell(row=r, column=1, value=f"SKU-{10000 + i}")
        ws.cell(row=r, column=2, value=rng.choice(DESCRIPTIONS))
        ws.cell(row=r, column=3, value=rng.randint(1, n_suppliers))
        ws.cell(row=r, column=4, value=qty)
        c = ws.cell(row=r, column=5, value=price)
        c.number_format = "0.00"
        c = ws.cell(row=r, column=6, value=rand_date(rng, 2021, 2023))
        c.number_format = "yyyy-mm-dd"
        ws.cell(row=r, column=7, value=rng.random() < 0.8)
        ws.cell(row=r, column=8, value=f"=D{r}*E{r}")
        cached[f"H{r}"] = repr(round(qty * price, 2))

    def row_of(key: str) -> int:
        return first + special[key]

    def bad_total(key: str) -> None:
        cached[f"H{row_of(key)}"] = "#VALUE!"
        t.add(S1, "total", "xlsx.error_value", 1, [row_of(key)], "formula over a non-numeric cell")

    ws.cell(row=row_of("dangling"), column=3, value=99)
    t.add(S1, "supplier_id", "key.dangling_reference", 1, [row_of("dangling")])
    for key, val in (("qty_text1", "15"), ("qty_text2", "230")):
        ws.cell(row=row_of(key), column=4, value=val).data_type = "s"
        t.add(S1, "qty", "storage.number_as_text", 1, [row_of(key)])
    c = ws.cell(row=row_of("qty_err"), column=4, value="#N/A")
    c.data_type = "e"
    t.add(S1, "qty", "xlsx.error_value", 1, [row_of("qty_err")])
    bad_total("qty_err")
    ws.cell(row=row_of("qty_tbd"), column=4, value="TBD")
    t.add(S1, "qty", "missing.marker", 1, [row_of("qty_tbd")], "TBD")
    bad_total("qty_tbd")
    for key in ("qty_e1", "qty_e2", "qty_e3"):
        ws.cell(row=row_of(key), column=4).value = None
        cached[f"H{row_of(key)}"] = "0"
        t.add(S1, "qty", "missing.empty", 1, [row_of(key)])
        t.add(S1, "total", "numeric.zero", 1, [row_of(key)], "formula over an empty cell")
    ws.cell(row=row_of("qty_zero"), column=4, value=0)
    cached[f"H{row_of('qty_zero')}"] = "0"
    t.add(S1, "qty", "numeric.zero", 1, [row_of("qty_zero")])
    t.add(S1, "total", "numeric.zero", 1, [row_of("qty_zero")])
    ws.cell(row=row_of("price_text"), column=5, value="12,50").data_type = "s"
    t.add(S1, "unit_price", "format.number_deviation", 1, [row_of("price_text")], "decimal comma typed as text")
    t.add(S1, "unit_price", "storage.number_as_text", 1, [row_of("price_text")])
    bad_total("price_text")
    ws.cell(row=row_of("price_neg"), column=5, value=-5.25)
    qty_neg = ws.cell(row=row_of("price_neg"), column=4).value
    cached[f"H{row_of('price_neg')}"] = repr(round(qty_neg * -5.25, 2))
    t.add(S1, "unit_price", "numeric.negative", 1, [row_of("price_neg")])
    t.add(S1, "total", "numeric.negative", 1, [row_of("price_neg")])
    ws.cell(row=row_of("date_text"), column=6, value="2023-13-45").data_type = "s"
    t.add(S1, "received", "value.invalid_date", 1, [row_of("date_text")])
    t.add(S1, "received", "storage.date_as_text", 1, [row_of("date_text")])
    ws.cell(row=row_of("date_marker"), column=6, value="unknown").data_type = "s"
    t.add(S1, "received", "missing.marker", 1, [row_of("date_marker")], "unknown")
    for key in ("date_e1", "date_e2"):
        ws.cell(row=row_of(key), column=6).value = None
        t.add(S1, "received", "missing.empty", 1, [row_of(key)])
    ws.cell(row=row_of("bool_text"), column=7, value="yes").data_type = "s"
    t.add(S1, "active", "format.boolean_deviation", 1, [row_of("bool_text")])
    ws.cell(row=row_of("canary"), column=2, value=CANARY_SKU_DESC)
    t.add(S1, "description", "text.rare_pattern", 1, [row_of("canary")], "canary")
    t.add(S1, "description", "category.rare_value", 1, [], "one description occurs once")
    t.canaries += [CANARY_SKU_DESC, "Quuxinator", "Prototype-K9"]
    t.add(S1, "total", "xlsx.formula_cell", n_stock, [], "every total is a formula")
    ws.row_dimensions[first + 46].hidden = True
    ws.column_dimensions["J"].hidden = True
    ws["B5"].comment = Comment("Checked by the fixture builder", "Fixture Author")
    # Legend table side by side with the stock table.
    ws.cell(row=3, column=11, value="code")
    ws.cell(row=3, column=12, value="meaning")
    for k, (code, meaning) in enumerate([("A", "Available"), ("B", "Backorder"), ("C", "Cancelled"), ("D", "Damaged")]):
        ws.cell(row=4 + k, column=11, value=code)
        ws.cell(row=4 + k, column=12, value=meaning)
    # Suppliers sheet.
    sup = wb.create_sheet("Suppliers")
    for j, h in enumerate(["supplier_id", "supplier_name", "country", "rating"], start=1):
        sup.cell(row=1, column=j, value=h)
    for k in range(1, n_suppliers + 1):
        sup.cell(row=k + 1, column=1, value=k)
        sup.cell(row=k + 1, column=2, value=f"{word(rng, rng.randint(5, 8), True)} GmbH")
        sup.cell(row=k + 1, column=3, value=rng.choice(["DE", "FR", "PL", "CZ"]))
        sup.cell(row=k + 1, column=4, value=round(rng.uniform(1, 5), 1)).number_format = "0.0"
    sup.cell(row=8, column=4).value = None
    sup.cell(row=19, column=4).value = None
    t.add(SUP, "rating", "missing.empty", 2, [8, 19])
    sup.cell(row=27, column=4, value="n/a")
    t.add(SUP, "rating", "missing.marker", 1, [27], "n/a")
    dup_row = n_suppliers + 2
    for j in range(1, 5):
        sup.cell(row=dup_row, column=j, value=sup.cell(row=6, column=j).value)
    sup.cell(row=dup_row, column=4).number_format = "0.0"
    t.add(SUP, None, "row.duplicate", 1, [dup_row])
    t.add(SUP, "supplier_id", "key.duplicate", 1, [dup_row])
    # Hidden sheet.
    arc = wb.create_sheet("Archive")
    arc.sheet_state = "hidden"
    arc.append(["year", "closed_items"])
    for y, n in ((2019, 120), (2020, 98), (2021, 143)):
        arc.append([y, n])
    wb.defined_names["StockRange"] = DefinedName("StockRange", attr_text=f"Stock!$A$3:$H${first + n_stock - 1}")
    wb.properties.creator = "Fixture Author"
    wb.properties.lastModifiedBy = "Fixture Author"
    fixed = dt.datetime(2026, 1, 1)
    wb.properties.created = fixed
    wb.properties.modified = fixed
    buf = io.BytesIO()
    wb.save(buf)
    # Insert cached formula results, as a spreadsheet application would store them.
    src = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
    pattern = re.compile(r'<c r="(H\d+)"([^>]*)><f>([^<]*)</f><v\s*/>\s*</c>')

    def fill(m: re.Match) -> str:
        val = cached.get(m.group(1))
        if val is None:
            return m.group(0)
        attrs = m.group(2)
        if val.startswith("#"):
            attrs += ' t="e"'
        return f'<c r="{m.group(1)}"{attrs}><f>{m.group(3)}</f><v>{val}</v></c>'

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                data = pattern.sub(fill, data.decode("utf-8")).encode("utf-8")
            info = zipfile.ZipInfo(item.filename, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            dst.writestr(info, data)
    mult = Counter(Counter(ws.cell(row=first + i, column=3).value for i in range(n_stock)).values())
    t.add(S1, "supplier_id", "key.multiplicity", sum(mult.values()), [], "distinct reference values")
    t.tables += [{"name": S1, "rows": n_stock, "columns": 8, "header_row": 3},
                 {"name": S2, "rows": 4, "columns": 2, "header_row": 3},
                 {"name": SUP, "rows": n_suppliers + 1, "columns": 4, "header_row": 1},
                 {"name": ARC, "rows": 3, "columns": 2, "header_row": 1}]
    t.relationships.append({"from": f"{S1}.supplier_id", "to": f"{SUP}.supplier_id", "dangling_rows": 1})
    d = t.to_dict()
    d["workbook"] = {"hidden_sheets": 1, "merged_ranges": 1, "hidden_rows": 1, "comments": True, "defined_names": 1,
                     "author_metadata": True, "formula_cells": n_stock}
    return d


def build_all(out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    truths = {
        "customers_hidden.csv": build_customers(os.path.join(out_dir, "customers_hidden.csv")),
        "orders_multi.tsv": build_orders_tsv(os.path.join(out_dir, "orders_multi.tsv")),
        "inventory_mixed.xlsx": build_inventory_xlsx(os.path.join(out_dir, "inventory_mixed.xlsx")),
    }
    for name, truth in truths.items():
        with open(os.path.join(out_dir, name + ".truth.json"), "w", encoding="utf-8") as fh:
            json.dump(truth, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    return truths


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "product")
    build_all(target)
    print(f"fixtures written to {target}")
