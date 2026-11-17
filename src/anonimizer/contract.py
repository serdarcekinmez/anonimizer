"""Dataset Contract v1: everything the generator is allowed to know.

The contract is built from the *shareable* profile only. It holds structure, pattern classes,
rates and generator specifications; the only literal values it may carry are column and sheet
names (flagged for review), allowlisted missing markers, boolean words, spreadsheet error
codes, and category values a person explicitly approved.
"""

from __future__ import annotations

import datetime as _dt
import json
import re

from . import __version__
from .patterns import BOOL_STYLES, DEFAULT_MARKERS, ERROR_CODES, safe_number_format
from .policy import PrivacyPolicy, get_policy

CONTRACT_VERSION = 1
SENSITIVITY_CLASSES = ("direct_identifier", "quasi_identifier", "sensitive", "free_text", "non_sensitive", "unreviewed")
KEY_ROLES = ("none", "unique", "repeating", "reference")
GEN_KINDS = {
    "empty", "quoted_empty", "empty_string", "whitespace", "absent", "literal", "error", "number", "date", "bool",
    "text", "text_shape", "text_gshape", "text_kind", "mix", "pool", "pool_rare", "category", "base",
    "formula_like", "duplicate_row", "blank_row", "ragged_short", "ragged_long", "duplicate_key",
    "dangling_reference", "key_multiplicity",
}

DESCRIPTIONS = {
    "missing.empty": "empty cell",
    "missing.quoted_empty": 'empty quoted field ("")',
    "missing.empty_string": "string cell holding an empty string",
    "missing.whitespace": "cell holding only whitespace",
    "missing.marker": "literal missing-value marker",
    "type.text_in_number": "text value in a numeric column",
    "type.text_in_date": "text value in a date column",
    "type.text_in_boolean": "text value in a boolean column",
    "type.number_in_date": "number in a date column",
    "type.number_in_text": "number in a text column",
    "type.number_in_boolean": "number in a boolean column",
    "type.date_in_number": "date in a numeric column",
    "type.date_in_text": "date in a text column",
    "type.date_in_boolean": "date in a boolean column",
    "type.boolean_in_number": "boolean word in a numeric column",
    "type.boolean_in_date": "boolean word in a date column",
    "type.boolean_in_text": "boolean word in a text column",
    "value.invalid_date": "date-shaped value that is not a real calendar date",
    "xlsx.error_value": "spreadsheet error value",
    "xlsx.formula_cell": "cell computed by a formula",
    "storage.number_as_text": "number stored as text in a numeric column",
    "storage.date_as_text": "date stored as text in a date column",
    "row.duplicate": "row identical to another row",
    "row.blank_inside_table": "blank row inside the table",
    "row.ragged_short": "row with fewer fields than the header",
    "row.ragged_long": "row with more fields than the header",
    "key.duplicate": "repeated value in an otherwise unique key column",
    "key.dangling_reference": "reference value with no match in the referenced table",
    "key.multiplicity": "key value occurring a given number of times",
    "format.number_deviation": "number written in a different format from the rest of the column",
    "format.date_deviation": "date written in a different format from the rest of the column",
    "format.date_order_conflict": "day-first and month-first dates in the same column",
    "format.boolean_deviation": "boolean written in a different style",
    "numeric.zero": "numeric zero (distinct from a missing value)",
    "numeric.negative": "negative number",
    "numeric.magnitude_outlier": "number with unusually many digits",
    "numeric.precision_deviation": "number with unusually many decimals",
    "numeric.leading_zero": "number written with leading zeros",
    "numeric.explicit_plus": "number written with an explicit plus sign",
    "text.padded": "value with leading or trailing whitespace",
    "text.multiline": "value containing a line break",
    "text.non_ascii": "value containing non-ASCII characters",
    "text.control_chars": "value containing control characters",
    "text.formula_like": "text starting like a spreadsheet formula",
    "text.rare_pattern": "rare text layout",
    "text.unexpected_free_text": "free text in an otherwise structured column",
    "text.length_outlier": "unusually long text",
    "category.rare_value": "category value that occurs very rarely",
    "header.empty_name": "column without a header name",
    "header.duplicate_name": "header name used by more than one column",
    "header.padded_name": "header name with surrounding whitespace",
}
NOT_REPRODUCED_REASON = {
    "xlsx.formula_cell": "formulas are inventoried only; the generated cell holds a plain value",
    "text.rare_pattern": "aggregated rare layouts beyond the per-column limit are not reproduced individually",
    "header.empty_name": "reproduced through the header row itself",
    "header.duplicate_name": "reproduced through the header row itself",
    "header.padded_name": "reproduced through the header row itself",
}


class ContractError(ValueError):
    pass


def describe(ex: dict) -> str:
    base = DESCRIPTIONS.get(ex["class"], ex["class"])
    d = ex.get("detail") or {}
    extra = []
    for key in ("literal", "code", "kind", "format", "style", "pattern", "side", "integer_digits",
                "decimal_digits", "missing_trailing_fields", "extra_fields", "occurrences_per_value", "length"):
        if key in d:
            extra.append(f"{key.replace('_', ' ')}: {d[key]}")
    return base + (" (" + ", ".join(extra) + ")" if extra else "")


def _approx(n: int, policy: PrivacyPolicy) -> int:
    if not policy.small_count_threshold or n < 100:
        return n if not policy.small_count_threshold else max(policy.small_count_threshold, n - n % 10)
    digits = len(str(n)) - 2
    return round(n, -digits)


def _rate(count, total) -> float:
    if count is None or not total:
        return 0.0
    return round(min(1.0, count / total), 6)


def build_contract(shareable: dict, policy: PrivacyPolicy) -> dict:
    if shareable.get("view") != "shareable":
        raise ContractError("the contract can only be built from a shareable profile")
    src = shareable["source"]
    layout: dict = {"format": src["format"]}
    if src["format"] == "csv":
        nl = src.get("newlines") or {}
        layout.update(
            delimiter=src["delimiter"]["delimiter"], quotechar=src.get("quotechar", '"'),
            encoding=src["encoding"]["encoding"],
            newline=max(nl, key=nl.get) if nl else "lf",
            final_newline=src.get("final_newline") is not False,
        )
    else:
        layout.update(date1904=bool(src.get("date1904")), sheets=[s["name"] for s in shareable["sheets"]])
    regions = []
    for tab in shareable["tables"]:
        r = tab["region"]
        regions.append({"name": tab["name"], "kind": "table", "sheet": tab["sheet"], "first_row": r["first_row"],
                        "last_row": r["last_data_row"], "first_col": r["first_col"], "last_col": r["last_col"]})
    for note in shareable["notes"]:
        r = note["region"]
        regions.append({"name": note["name"], "kind": "note", "sheet": note["sheet"], "first_row": r["first_row"],
                        "last_row": r["last_data_row"], "first_col": r["first_col"], "last_col": r["last_col"]})
    layout["regions"] = sorted(regions, key=lambda x: (x["sheet"], x["first_row"], x["first_col"]))
    tables = []
    for tab in shareable["tables"]:
        cols = []
        scenarios = []
        for col in tab["columns"]:
            missing = []
            for ex in col["exceptions"]:
                if ex["class"].startswith("missing.") and ex.get("gen"):
                    missing.append({"class": ex["class"], "gen": ex["gen"], "rate": _rate(ex["count"], col["n_cells"])})
            ds = col["distinct"]
            hint = col["sensitivity_hint"]
            cols.append({
                "id": col["id"], "name": col["name"], "keep": True,
                "logical_type": col["logical_type"],
                "sensitivity": {"class": hint["class"], "basis": hint["basis"], "confirmed": False},
                "key": {"role": col["key"]["role"], "confirmed": False, "references": col["key"]["references"],
                        "distinct_ratio": round(ds["n_distinct"] / ds["n_values"], 4) if ds["n_values"] else 1.0},
                "base_gen": col["base_gen"], "missing": missing,
                "value_policy": {"mode": "synthetic", "approved_literals": []},
                "numeric_storage": bool(col.get("numeric_storage")),
                "number_format": next(iter(col.get("number_formats") or {}), None)
                if col["logical_type"] in ("integer", "decimal") else None,
                "categorical": col.get("categorical", {}).get("n_categories"),
            })
            for ex in col["exceptions"]:
                scenarios.append(_scenario(ex))
        for ex in tab["row_exceptions"]:
            scenarios.append(_scenario(ex))
        tables.append({
            "name": tab["name"], "output_name": tab["name"], "sheet": tab["sheet"],
            "header_present": tab["header_present"], "source_rows": _approx(tab["n_rows"], policy),
            "preamble": tab["preamble"], "columns": cols, "scenarios": scenarios,
        })
    return {
        "contract_version": CONTRACT_VERSION, "tool_version": __version__,
        "policy": {"id": policy.id, "version": policy.version},
        "layout": layout, "tables": tables,
        "notes": [{"name": n["name"], "sheet": n["sheet"], "rows": n["rows"]} for n in shareable["notes"]],
        "relationships": shareable["relationships"],
        "extra_markers": [m for m in shareable.get("recipe", {}).get("extra_markers", [])],
        "review": {"confirmed": False, "confirmed_by": None, "confirmed_at": None},
    }


def _scenario(ex: dict) -> dict:
    reproducible = ex.get("gen") is not None
    return {
        "id": ex["id"], "class": ex["class"], "column": ex.get("column"), "priority": ex["priority"],
        "detail": ex["detail"], "description": describe(ex), "gen": ex.get("gen"),
        "source_count": ex.get("count_display", str(ex["count"])), "common": bool(ex.get("common")),
        "enabled": True, "pinned": False, "reproducible": reproducible,
        "not_reproduced_reason": None if reproducible else NOT_REPRODUCED_REASON.get(
            ex["class"], "no generator exists for this class"),
    }


# -- validation -------------------------------------------------------------------------------
def _check_number_format(fmt, where: str) -> None:
    if fmt is None:
        return
    if not isinstance(fmt, str) or safe_number_format(fmt) != fmt:
        raise ContractError(f"{where}: a number format may hold layout codes only (digits, separators, date and "
                            f"time codes); quoted text, escaped letters and bracketed tags are not accepted")


def _check_gen(gen, allowed_literals: set, where: str) -> None:
    if gen is None:
        return
    if not isinstance(gen, dict) or gen.get("g") not in GEN_KINDS:
        raise ContractError(f"{where}: unknown generator")
    _check_number_format(gen.get("number_format"), where)
    g = gen["g"]
    if g == "literal":
        v = gen.get("value")
        if not isinstance(v, str) or (v.casefold() not in allowed_literals and v not in ERROR_CODES):
            raise ContractError(f"{where}: a literal value is neither an allowlisted marker nor an approved literal")
    elif g == "error":
        if gen.get("code") not in ERROR_CODES:
            raise ContractError(f"{where}: unknown spreadsheet error code")
    elif g == "bool":
        if str(gen.get("style", "")).split(":")[0] not in BOOL_STYLES:
            raise ContractError(f"{where}: unknown boolean style")
    elif g == "category":
        vals = gen.get("values")
        if not isinstance(vals, list) or any(not isinstance(v, str) or v.casefold() not in allowed_literals for v in vals):
            raise ContractError(f"{where}: category values must be listed in approved_literals")
        if gen.get("other"):
            _check_gen(gen["other"].get("of"), allowed_literals, where)
    elif g == "mix":
        for item in gen.get("of", []):
            _check_gen(item[1], allowed_literals, where)
    elif g == "pool":
        _check_gen(gen.get("of"), allowed_literals, where)


def validate_contract(contract: dict) -> PrivacyPolicy:
    if not isinstance(contract, dict) or contract.get("contract_version") != CONTRACT_VERSION:
        raise ContractError(f"unsupported contract: expected contract_version {CONTRACT_VERSION}")
    policy = get_policy((contract.get("policy") or {}).get("id"))
    extra = {str(m).casefold() for m in contract.get("extra_markers", [])}
    names = set()
    for tab in contract.get("tables", []):
        if tab["name"] in names:
            raise ContractError("table names must be unique")
        names.add(tab["name"])
        ids = {c["id"] for c in tab["columns"]}
        for col in tab["columns"]:
            where = f"{tab['name']}.{col['id']}"
            if col["sensitivity"]["class"] not in SENSITIVITY_CLASSES:
                raise ContractError(f"{where}: unknown sensitivity class")
            if col["key"]["role"] not in KEY_ROLES:
                raise ContractError(f"{where}: unknown key role")
            if not isinstance(col.get("keep"), bool):
                raise ContractError(f"{where}: keep must be true or false")
            if not isinstance(col.get("name"), str) or len(col["name"]) > 300:
                raise ContractError(f"{where}: column name must be a string of at most 300 characters")
            _check_number_format(col.get("number_format"), where)
            allowed = set(DEFAULT_MARKERS) | extra | {str(v).casefold() for v in col["value_policy"].get("approved_literals", [])}
            _check_gen(col["base_gen"], allowed, where)
            for m in col["missing"]:
                _check_gen(m["gen"], allowed, where)
        for sc in tab["scenarios"]:
            col = next((c for c in tab["columns"] if c["id"] == sc.get("column")), None)
            if sc.get("column") is not None and sc["column"] not in ids:
                raise ContractError(f"{tab['name']}: scenario refers to an unknown column")
            allowed = set(DEFAULT_MARKERS) | extra
            if col is not None:
                allowed |= {str(v).casefold() for v in col["value_policy"].get("approved_literals", [])}
            _check_gen(sc.get("gen"), allowed, f"{tab['name']} scenario")
    _check_references(contract)
    return policy


def _check_references(contract: dict) -> None:
    """A kept reference column must point at a kept key column (unique, repeating or none) of a
    table in the contract. A reference to a dropped column or to another reference would be
    generated without its parent and silently break the relationship."""
    cols = {(t["name"], c["id"]): c for t in contract.get("tables", []) for c in t["columns"]}
    for tab in contract.get("tables", []):
        for col in tab["columns"]:
            if not col["keep"] or col["key"]["role"] != "reference":
                continue
            where = f"{tab['name']}.{col['id']}"
            ref = col["key"].get("references")
            if not isinstance(ref, dict) or not isinstance(ref.get("table"), str) or not isinstance(ref.get("column"), str):
                raise ContractError(f"{where}: a reference column must name the table and column it refers to")
            target = cols.get((ref["table"], ref["column"]))
            to = f"{ref['table']}.{ref['column']}" if target is not None else "an unknown table or column"
            if target is None:
                raise ContractError(f"{where} refers to {to}; set its key role to none or correct the reference")
            if not target["keep"]:
                raise ContractError(f"{where} refers to {to}, which is not kept; keep {to} as well, drop {where}, "
                                    f"or set the key role of {where} to none")
            if target["key"]["role"] == "reference":
                raise ContractError(f"{where} refers to {to}, which is itself a reference; point it at the key "
                                    f"column that {to} refers to")


# -- column names -----------------------------------------------------------------------------
# One naming layer for the interface and the command line: plan (a preview that changes
# nothing), then apply. Messages name column ids and counts, never a column name.
SEQUENCE_WORDS = ("Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta", "Iota", "Kappa", "Lambda",
                  "Mu", "Nu", "Xi", "Omicron", "Pi", "Rho", "Sigma", "Tau", "Upsilon", "Phi", "Chi", "Psi", "Omega")
NAMING_MODES = ("edit", "sequence", "list")
NAMING_STYLES = ("", "snake", "lower", "upper")
MAX_NAME = 300
_SNAKE = re.compile(r"[\s!-/:-@\[-`{-~]+")


def sequence_name(i: int) -> str:
    """0 -> Alpha, 1 -> Beta, ... 23 -> Omega, 24 -> Alpha2."""
    word = SEQUENCE_WORDS[i % len(SEQUENCE_WORDS)]
    return word if i < len(SEQUENCE_WORDS) else f"{word}{i // len(SEQUENCE_WORDS) + 1}"


def plan_names(columns: list[tuple[str, str]], *, mode: str = "edit", names: list[str] | None = None,
               style: str = "", find: str = "", replace: str = "", prefix: str = "", suffix: str = "",
               others: list[str] | tuple = ()) -> list[dict]:
    """Propose new names for ``columns`` ((id, current name) pairs, in table order).

    mode ``edit`` starts from the current names, ``sequence`` from Alpha, Beta, Gamma...,
    ``list`` from ``names`` (one per column, in order; an empty entry keeps the current name).
    Then, in this order: find/replace, spelling (``style``), prefix and suffix. ``others`` are
    the names of the table's other kept columns: a new name may not repeat any of them.
    """
    if mode not in NAMING_MODES:
        raise ContractError("unknown naming mode; use edit, sequence or list")
    if style not in NAMING_STYLES:
        raise ContractError("unknown spelling; use snake, lower or upper, or leave it empty")
    if mode == "list":
        names = [str(n).strip() for n in (names or [])]
        if len(names) != len(columns):
            raise ContractError(f"{len(names)} name(s) were given for {len(columns)} selected column(s); give exactly "
                                f"one name per selected column, in table order (an empty line keeps a column's name)")
    plan = []
    for i, (cid, current) in enumerate(columns):
        if mode == "sequence":
            v = sequence_name(i)
        elif mode == "list":
            v = names[i] or current
        else:
            v = current
        if mode == "list" and not names[i]:
            plan.append({"id": cid, "current": current, "new": current, "changed": False})
            continue
        if find:
            v = v.replace(find, replace)
        if style == "snake":
            v = _SNAKE.sub("_", v.strip().lower()).strip("_")
        elif style == "lower":
            v = v.lower()
        elif style == "upper":
            v = v.upper()
        v = f"{prefix}{v}{suffix}"
        plan.append({"id": cid, "current": current, "new": v, "changed": v != current})
    empty = [p["id"] for p in plan if not p["new"].strip()]
    if empty:
        raise ContractError(f"the new name would be empty for column(s) {', '.join(empty)}")
    long = [p["id"] for p in plan if len(p["new"]) > MAX_NAME]
    if long:
        raise ContractError(f"column names have at most {MAX_NAME} characters; too long for column(s) {', '.join(long)}")
    seen: dict[str, str] = {}
    clash = []
    taken = set(others)
    for p in plan:
        if p["changed"] and (p["new"] in taken or p["new"] in seen):
            clash.append(p["id"])
        seen.setdefault(p["new"], p["id"])
    if clash:
        raise ContractError(f"the new names would repeat another column's name for column(s) {', '.join(clash)}")
    return plan


def apply_naming(contract: dict, spec: dict) -> list[dict]:
    """Apply a naming request to the contract; returns the plan with the table of each column.

    ``spec``: mode, names, style, find, replace, prefix, suffix as in ``plan_names``; ``columns``
    a list of (table, column id or name) to rename, or ``table`` to rename every kept column of
    one table, or neither for every kept column of every table (not for a list of names when the
    contract has several tables).
    """
    opts = {k: spec[k] for k in ("mode", "names", "style", "find", "replace", "prefix", "suffix") if spec.get(k) is not None}
    selected: dict[str, set] = {}
    for table, column in spec.get("columns") or []:
        col = find_column(contract, table, column)
        if not col["keep"]:
            raise ContractError(f"{table}.{col['id']} is not kept, so it has no output name to change")
        selected.setdefault(table, set()).add(col["id"])
    if spec.get("table") is not None and spec["table"] not in {t["name"] for t in contract["tables"]}:
        raise ContractError("unknown table")
    if selected:
        tables = [t for t in contract["tables"] if t["name"] in selected]
    else:
        tables = [t for t in contract["tables"] if spec.get("table") in (None, t["name"])]
    if opts.get("mode") == "list" and len(tables) > 1:
        raise ContractError("a list of names applies to one table; choose the table or the columns")
    plan_all = []
    for t in tables:
        kept = [c for c in t["columns"] if c["keep"]]
        targets = [c for c in kept if c["id"] in selected[t["name"]]] if selected else kept
        others = [c["name"] for c in kept if c not in targets]
        plan = plan_names([(c["id"], c["name"]) for c in targets], others=others, **opts)
        by_id = {c["id"]: c for c in targets}
        for p in plan:
            by_id[p["id"]]["name"] = p["new"]
            plan_all.append({"table": t["name"], **p})
    return plan_all


# -- user decisions ---------------------------------------------------------------------------
def find_column(contract: dict, table: str, column: str) -> dict:
    for tab in contract["tables"]:
        if tab["name"] == table:
            for col in tab["columns"]:
                if column in (col["id"], col["name"]):
                    return col
    raise ContractError("unknown table or column")


def approve_categories(contract: dict, private_profile: dict, table: str, column: str, approved_by: str) -> dict:
    """Approve copying the frequent literal values of one categorical column.

    Only values above the policy's count and share limits are copied; rarer ones stay synthetic.
    """
    if not approved_by or not approved_by.strip():
        raise ContractError("approving literal values requires the name of the approver")
    policy = get_policy(contract["policy"]["id"])
    col = find_column(contract, table, column)
    pcol = None
    for tab in private_profile["tables"]:
        if tab["name"] == table:
            pcol = next((c for c in tab["columns"] if c["id"] == col["id"]), None)
    values = (pcol or {}).get("_private", {}).get("category_values")
    if not values:
        raise ContractError("this column is not categorical in the source profile; nothing can be approved")
    total = sum(values.values())
    keep = {v: c for v, c in values.items() if c >= policy.category_min_count and c / total >= policy.category_min_share}
    if not keep:
        raise ContractError("no category value reaches the policy's minimum count and share")
    rest = [c for v, c in values.items() if v not in keep]
    gen: dict = {"g": "category", "values": list(keep), "weights": [round(c / total, 6) for c in keep.values()]}
    if rest:
        inner = col["base_gen"]["of"] if col["base_gen"].get("g") == "pool" else col["base_gen"]
        gen["other"] = {"size": len(rest), "weight": round(sum(rest) / total, 6), "of": inner}
    col["base_gen"] = gen
    col["value_policy"] = {"mode": "literal_categories", "approved_literals": list(keep), "approved_by": approved_by.strip(),
                           "approved_at": _dt.date.today().isoformat(),
                           "basis": f"count >= {policy.category_min_count} and share >= {policy.category_min_share}",
                           "kept_synthetic": len(rest)}
    return col


def confirm_contract(contract: dict, confirmed_by: str) -> None:
    """Record that a person reviewed keep decisions, sensitivity classes and key roles."""
    if not confirmed_by or not confirmed_by.strip():
        raise ContractError("confirmation requires the reviewer's name")
    pending = [f"{t['name']}.{c['name']}" for t in contract["tables"] for c in t["columns"]
               if c["keep"] and c["sensitivity"]["class"] == "unreviewed"]
    if pending:
        raise ContractError("these kept columns still have sensitivity 'unreviewed': " + ", ".join(pending[:12])
                            + (" ..." if len(pending) > 12 else ""))
    for t in contract["tables"]:
        for c in t["columns"]:
            c["sensitivity"]["confirmed"] = True
            c["key"]["confirmed"] = True
    contract["review"] = {"confirmed": True, "confirmed_by": confirmed_by.strip(),
                          "confirmed_at": _dt.date.today().isoformat()}


def dumps(contract: dict) -> str:
    return json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=False)
