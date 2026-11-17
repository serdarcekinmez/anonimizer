"""Before/after quality reports. Built from shareable profiles only: no row numbers, no values."""

from __future__ import annotations

from . import NON_CERTIFICATION_STATEMENT, __version__
from .contract import describe
from .profile import iter_exceptions


def _col_summary(col: dict) -> dict:
    out = {
        "id": col["id"], "name": col["name"], "logical_type": col["logical_type"],
        "type_share": col["type_share"], "cells": col["n_cells"], "values": col["n_values"],
        "missing": col["n_missing"], "missing_kinds": col["missing"], "markers": col["markers"],
        "error_values": col.get("error_values", 0),
        "distinct": col["distinct"]["n_distinct"], "key_role": col["key"]["role"],
        "references": col["key"].get("references"),
        "sensitivity_hint": col["sensitivity_hint"]["class"],
    }
    if "number" in col:
        out["number_formats"] = col["number"]["formats"]
        out["zero"] = col["number"]["zero"]
        out["negative"] = col["number"]["negative"]
    if "date" in col:
        out["date_formats"] = col["date"]["formats"]
        out["date_order"] = col["date"]["order"]
    if "text" in col:
        out["text_structure"] = col["text"]["structure"]
        out["text_kinds"] = {k: v["count"] for k, v in col["text"]["kinds"].items()}
    if "categorical" in col:
        out["categories"] = col["categorical"]["n_categories"]
    if col.get("storage"):
        out["storage"] = col["storage"]
    return out


def _exception_row(ex: dict) -> dict:
    return {"id": ex["id"], "class": ex["class"], "table": ex.get("table"), "column": ex.get("column_name"),
            "description": describe(ex), "count": ex.get("count_display", str(ex.get("count"))),
            "share": ex.get("share"), "priority": ex["priority"], "common": ex.get("common", False),
            "reproducible": ex.get("gen") is not None}


def summarize_profile(profile: dict, role: str) -> dict:
    """Readable summary of a shareable profile (role: 'source' or 'generated')."""
    src = profile["source"]
    file_info = {"format": src["format"], "size_bytes": src.get("size_bytes")}
    if src["format"] == "csv":
        file_info.update(encoding=src["encoding"]["encoding"], encoding_confidence=src["encoding"]["confidence"],
                         byte_order_mark=src["encoding"].get("bom"), delimiter=src["delimiter"]["delimiter"],
                         delimiter_confidence=src["delimiter"]["confidence"], newlines=src.get("newlines"),
                         records=src.get("records"), multiline_records=src.get("multiline_records"))
    else:
        file_info.update(sheets=[s["name"] for s in profile["sheets"]], hidden_sheets=src.get("hidden_sheets"),
                         metadata_inventory=src.get("metadata_inventory"))
    tables = []
    for tab in profile["tables"]:
        tables.append({
            "name": tab["name"], "sheet": tab["sheet"], "rows": tab["n_rows"], "columns": tab["n_columns"],
            "header_present": tab["header_present"], "introductory_rows": len(tab["preamble"]),
            "region": tab["region"], "detection_confidence": tab["region"]["confidence"],
            "detection_notes": tab["region"]["notes"], "duplicate_rows": tab["duplicate_rows"],
            "column_summaries": [_col_summary(c) for c in tab["columns"]],
        })
    catalogue = [_exception_row(e) for e in iter_exceptions(profile)]
    return {
        "report": f"{role}_quality_report", "tool_version": __version__, "policy": profile.get("policy"),
        "file": file_info, "regions": profile["regions"],
        "other_regions": [{"name": n["name"], "sheet": n["sheet"], "rows": len(n["rows"])} for n in profile["notes"]],
        "tables": tables, "relationships": profile["relationships"],
        "exception_catalogue": catalogue,
        "exception_classes": sorted({e["class"] for e in catalogue}),
        "unresolved_ambiguities": profile["ambiguities"],
        "statement": NON_CERTIFICATION_STATEMENT,
    }


def _missing_literals(gen, out: set) -> None:
    if isinstance(gen, dict):
        if gen.get("g") == "literal" and isinstance(gen.get("value"), str):
            out.add(gen["value"])
        for v in gen.values():
            _missing_literals(v, out)
    elif isinstance(gen, list):
        for v in gen:
            _missing_literals(v, out)


def verify_relationships(contract: dict, dataset: dict) -> list[dict]:
    """Measure every declared reference on the generated cells: containment, dangling rows and,
    for one-to-one references, repeated keys. Counts only; no value is reported.

    Cells that carry a planned exception of the column (a missing value, an error code, a
    negative number...) are not keys and are left out. Dangling keys are expected only where the
    Scenario Manifest planned a dangling-reference case.
    """
    tables = {t["name"]: t for t in contract["tables"]}
    planned: dict = {}
    for e in dataset["manifest"]:
        if e.get("column") is not None:
            kind = "dangling" if e["class"] == "key.dangling_reference" else \
                "key" if e["class"].startswith("key.") else "exception"
            for r in e["data_rows"]:
                planned.setdefault((e["table"], e["column"], r), set()).add(kind)

    def keys(tname, cid):
        t = dataset["tables"].get(tname)
        if t is None or cid not in t["columns"]:
            return None
        j = t["columns"].index(cid)
        out = []
        for r in t["rows"]:
            if r["kind"] != "data":
                continue
            cell = r["cells"][j] if j < len(r["cells"]) else None
            out.append((r["data_row"], None if cell is None or cell.kind == "" else cell.text))
        return out

    results = []
    for tab in contract["tables"]:
        for col in tab["columns"]:
            ref = col["key"].get("references")
            if not col["keep"] or col["key"]["role"] != "reference" or not ref:
                continue
            target = next((c for c in tables.get(ref["table"], {}).get("columns", []) if c["id"] == ref["column"]), None)
            child = keys(tab["name"], col["id"])
            parent = keys(ref["table"], ref["column"])
            entry = {"from_table": tab["name"], "from_column": col["id"], "from_column_name": col["name"],
                     "to_table": ref["table"], "to_column": ref["column"],
                     "to_column_name": target["name"] if target else None,
                     "one_to_one": bool(ref.get("one_to_one")), "key_cells": 0, "distinct_keys": 0,
                     "containment": None, "dangling_rows": 0, "planned_dangling_rows": 0,
                     "repeated_values": 0 if ref.get("one_to_one") else None, "status": "not_evaluable"}
            results.append(entry)
            if child is None or parent is None:
                entry["status"] = "broken"
                continue
            skip: set = set()
            _missing_literals(col.get("missing"), skip)
            parent_set = {t for _r, t in parent if t}
            counts: dict = {}
            for data_row, text in child:
                kinds = planned.get((tab["name"], col["id"], data_row), set())
                if text is None or not text.strip() or text in skip or "exception" in kinds:
                    continue
                if "dangling" in kinds:
                    entry["planned_dangling_rows"] += 1
                    continue
                entry["key_cells"] += 1
                counts[text] = counts.get(text, 0) + 1
                if text not in parent_set:
                    entry["dangling_rows"] += 1
            if not counts:
                continue
            entry["distinct_keys"] = len(counts)
            entry["containment"] = round(sum(1 for t in counts if t in parent_set) / len(counts), 4)
            if ref.get("one_to_one"):
                entry["repeated_values"] = sum(n - 1 for n in counts.values())
            broken = entry["dangling_rows"] > 0 or bool(entry["repeated_values"])
            entry["status"] = "broken" if broken else "preserved"
    return results


def compare(src: dict, out: dict, dataset: dict, contract: dict) -> dict:
    """Compare the source profile with the profile of the generated file."""
    cov = {c["table"]: c for c in dataset["coverage"]["tables"]}
    out_tabs = {t["name"]: t for t in out["tables"]}
    ctabs = {t["name"]: t for t in contract["tables"]}
    tables = []
    structural = []
    verified = 0
    unverified = []
    for st in src["tables"]:
        ot = out_tabs.get(st["name"])
        ct = ctabs[st["name"]]
        if ot is None:
            structural.append(f"table '{st['name']}' was not found again in the generated file")
            continue
        kept = [c["id"] for c in ct["columns"] if c["keep"]]
        dropped = [c["name"] for c in ct["columns"] if not c["keep"]]
        scols = {c["id"]: c for c in st["columns"]}
        cols = []
        out_classes: dict = {}
        for k, cid in enumerate(kept):
            sc = scols[cid]
            oc = ot["columns"][k] if k < len(ot["columns"]) else None
            s_cls = {e["class"] for e in sc["exceptions"]}
            o_cls = {e["class"] for e in oc["exceptions"]} if oc else set()
            out_classes[cid] = o_cls
            cols.append({
                "name": sc["name"], "source_type": sc["logical_type"],
                "generated_type": oc["logical_type"] if oc else None,
                "type_preserved": bool(oc) and oc["logical_type"] == sc["logical_type"],
                "name_preserved": bool(oc) and (oc["name"] == sc["name"] or not st["header_present"]),
                "classes_preserved": sorted(s_cls & o_cls),
                "classes_not_represented": sorted(s_cls - o_cls),
                "classes_new_in_output": sorted(o_cls - s_cls),
            })
        s_row = {e["class"] for e in st["row_exceptions"]}
        o_row = {e["class"] for e in ot["row_exceptions"]}
        out_classes[None] = o_row
        if dropped:
            structural.append(f"table '{st['name']}': {len(dropped)} column(s) dropped by the contract")
        if st["header_present"] != ot["header_present"]:
            structural.append(f"table '{st['name']}': header presence differs")
        if len(kept) != ot["n_columns"]:
            structural.append(f"table '{st['name']}': {len(kept)} kept column(s), {ot['n_columns']} found in the output")
        c = cov.get(st["name"], {})
        sc_by_id = {s["id"]: s for s in ct["scenarios"]}
        for sid in c.get("covered", []):
            s = sc_by_id.get(sid)
            if s is None:
                continue
            if s["class"] in out_classes.get(s.get("column"), set()):
                verified += 1
            else:
                unverified.append({"id": sid, "class": s["class"], "column": s.get("column"),
                                   "note": "generated, but the profiler did not classify it the same way in "
                                           "the small output"})
        tables.append({
            "name": st["name"], "source_rows": ct["source_rows"], "generated_rows": ot["n_rows"],
            "requested_rows": c.get("requested_rows"), "columns": cols,
            "row_classes_preserved": sorted(s_row & o_row), "row_classes_not_represented": sorted(s_row - o_row),
            "row_classes_new_in_output": sorted(o_row - s_row),
        })
    if len(src["tables"]) != len(out["tables"]):
        structural.append(f"{len(src['tables'])} table(s) in the source, {len(out['tables'])} detected in the output")
    relationships = verify_relationships(contract, dataset)
    for r in relationships:
        if r["status"] == "broken":
            what = []
            if r["dangling_rows"]:
                what.append(f"{r['dangling_rows']} generated key(s) not found in the referenced column")
            if r["repeated_values"]:
                what.append(f"{r['repeated_values']} repeated key(s) in a one-to-one reference")
            structural.append(f"relationship {r['from_table']}.{r['from_column_name']} -> {r['to_table']}."
                              f"{r['to_column_name']} not preserved: " + ("; ".join(what) or "a column is missing"))
    s_file = {e["class"] for e in src["file_exceptions"]}
    o_file = {e["class"] for e in out["file_exceptions"]}
    return {
        "report": "before_after_comparison", "tool_version": __version__, "tables": tables,
        "structural_differences": structural,
        "file_level_classes_not_represented": sorted(s_file - o_file),
        "scenario_verification": {"covered_scenarios_found_again": verified,
                                  "covered_scenarios_not_found_again": unverified},
        "relationship_verification": relationships,
        "statement": NON_CERTIFICATION_STATEMENT,
    }


def _md_table(headers: list[str], rows: list[list]) -> str:
    def esc(v) -> str:
        return str(v).replace("|", "\\|").replace("\n", " ").replace("\r", " ")

    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def render_markdown(source: dict, generated: dict, comparison: dict, coverage: dict, manifest: list[dict],
                    assessment: dict | None) -> str:
    p = []
    p.append("# Anonimizer quality report\n")
    p.append(f"Tool version {__version__}. {NON_CERTIFICATION_STATEMENT}\n")
    if assessment:
        p.append("## Classification\n")
        p.append(_md_table(["Item", "Value"], [
            ["Release tier", assessment["release_tier"]], ["Transformation class", assessment["transformation_class"]],
            ["Assessment status", assessment["assessment_status"]],
            ["Policy", f"{assessment['policy']['id']} v{assessment['policy']['version']}"],
            ["Review by", assessment["review_by"]], ["Record", assessment["record_id"]]]))
        if assessment.get("tier_reasons"):
            p.append("\nWhy the tier is not higher:\n")
            p += [f"- {r}" for r in assessment["tier_reasons"]]
        if assessment.get("criteria"):
            p.append("\n" + _md_table(["Criterion", "Status"],
                                      [[k.replace("_", " "), v["status"]] for k, v in assessment["criteria"].items()]))
        for s in assessment.get("residual_risk_statements", []):
            p.append(f"\n- Residual risk: {s}")
        p.append("")
    p.append("## Source data (before)\n")
    f = source["file"]
    p.append(_md_table(["Property", "Value"], [[k.replace("_", " "), v] for k, v in f.items() if v not in (None, {}, [])]))
    p.append("\n### Tables\n")
    p.append(_md_table(["Table", "Rows", "Columns", "Header", "Intro rows", "Detection confidence", "Notes"],
                       [[t["name"], t["rows"], t["columns"], "yes" if t["header_present"] else "no",
                         t["introductory_rows"], t["detection_confidence"], "; ".join(t["detection_notes"]) or "-"]
                        for t in source["tables"]]))
    for t in source["tables"]:
        p.append(f"\n### Columns of {t['name']}\n")
        p.append(_md_table(["Column", "Type", "Type share", "Missing", "Markers", "Distinct", "Key role", "Sensitivity hint"],
                           [[c["name"], c["logical_type"], c["type_share"], c["missing"],
                             ", ".join(f"{k} x{v}" for k, v in c["markers"].items()) or "-", c["distinct"],
                             c["key_role"], c["sensitivity_hint"]] for c in t["column_summaries"]]))
    p.append("\n### Exception Catalogue\n")
    cat = source["exception_catalogue"]
    if cat:
        p.append(_md_table(["Priority", "Table", "Column", "Exception", "Count", "Reproducible"],
                           [[e["priority"], e["table"] or "(file)", e["column"] or "(row/file)", e["description"],
                             e["count"], "yes" if e["reproducible"] else "no"] for e in cat]))
    else:
        p.append("No exceptional pattern was found.")
    if source["unresolved_ambiguities"]:
        p.append("\n### Unresolved ambiguities\n")
        p += [f"- {a['scope']}: {a['message']} (confidence {a['confidence']})" for a in source["unresolved_ambiguities"]]
    p.append("\n## Generated data (after)\n")
    p.append(_md_table(["Table", "Requested rows", "Generated data rows", "Blank rows", "Scenarios", "Covered",
                        "Max scenarios per row", "Rows needed (isolated)", "Rows needed (packed)"],
                       [[c["table"], c["requested_rows"], c["generated_data_rows"], c["blank_rows"], c["scenarios_total"],
                         c["scenarios_covered"], c["max_scenarios_per_row"] or "unlimited", c["n_min_isolated"],
                         c["n_min_packed"]] for c in coverage["tables"]]))
    unc = [(c["table"], u) for c in coverage["tables"] for u in c["uncovered"]]
    p.append("\n### Exception classes not represented\n")
    if unc:
        p.append(_md_table(["Table", "Scenario", "Reason"], [[t, u["description"], u["reason"]] for t, u in unc]))
    else:
        p.append("Every catalogued scenario is represented.")
    p.append("\n### Scenario Manifest\n")
    if manifest:
        def loc(e):
            out = []
            for item in e["locations"]:
                out.append(item.get("cell") or (f"line {item['line']}" + (f", field {item['field']}" if "field" in item else "")
                                                if "line" in item else f"row {item['row']}"))
            return "; ".join(out) or "-"
        p.append(_md_table(["Table", "Column", "Scenario", "Data rows", "Location", "Note"],
                           [[e["table"], e["column_name"] or "(row)", e["description"],
                             " ".join(map(str, e["data_rows"])) or "-", loc(e), e["note"] or "-"] for e in manifest]))
    else:
        p.append("No scenario was generated.")
    p.append("\n## Before/after comparison\n")
    for t in comparison["tables"]:
        p.append(f"\n### {t['name']}: {t['source_rows']} source rows, {t['generated_rows']} generated rows\n")
        p.append(_md_table(["Column", "Source type", "Generated type", "Classes preserved", "Not represented", "New in output"],
                           [[c["name"], c["source_type"], c["generated_type"], ", ".join(c["classes_preserved"]) or "-",
                             ", ".join(c["classes_not_represented"]) or "-", ", ".join(c["classes_new_in_output"]) or "-"]
                            for c in t["columns"]]))
        p.append(f"\nRow-level classes preserved: {', '.join(t['row_classes_preserved']) or '-'}; not represented: "
                 f"{', '.join(t['row_classes_not_represented']) or '-'}; new in output: "
                 f"{', '.join(t['row_classes_new_in_output']) or '-'}.")
    if comparison["structural_differences"]:
        p.append("\n### Structural differences\n")
        p += [f"- {d}" for d in comparison["structural_differences"]]
    if comparison["file_level_classes_not_represented"]:
        p.append("\nFile-level characteristics not reproduced: " + ", ".join(comparison["file_level_classes_not_represented"]) + ".")
    sv = comparison["scenario_verification"]
    p.append(f"\nSelf-check: {sv['covered_scenarios_found_again']} covered scenario(s) were found again when the "
             f"generated file was profiled; {len(sv['covered_scenarios_not_found_again'])} were not.")
    rel = comparison.get("relationship_verification") or []
    if rel:
        broken = sum(1 for r in rel if r["status"] == "broken")
        p.append(f"\nRelationships between tables, measured on the generated cells: {len(rel) - broken} preserved, "
                 f"{broken} not preserved.")
    if assessment:
        p.append("\n## Limitations\n")
        p += [f"- {x}" for x in assessment.get("limitations", [])]
    return "\n".join(p) + "\n"
