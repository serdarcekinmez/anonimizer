"""Deterministic privacy assessment of a synthetic output against its source.

This is the runtime control. It involves no model and no network. It measures, in one
streaming pass over the source, whether generated values, rows or reports coincide with
source content, evaluates the three CNIL criteria separately, and derives a release tier.

What it does not do: prove anonymity. See docs/privacy-limitations.md.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import re
from collections import Counter

from . import NON_CERTIFICATION_STATEMENT, __version__
from .patterns import BOOL_WORDS, DEFAULT_MARKERS, ERROR_CODES
from .policy import (
    EXTERNAL_CANDIDATE,
    LOCAL_ONLY,
    RELEASE_TIER_CAP,
    RELEASE_TIER_CAP_REASON,
    RESTRICTED,
    TIER_ORDER,
    PrivacyPolicy,
    min_tier,
)
from .recipe import ParseRecipe, resolve_regions
from .synth import generate

PASSED, RESIDUAL, FAILED, NOT_EVALUABLE = "passed", "passed_with_residual_risk", "failed", "not_evaluable"
MAX_QI_COMBINATIONS = 2_000_000
MAX_CONTROL_SAMPLES = 30
CONTROL_ROW_BUDGET = 60_000
_TOKEN = re.compile(r"[^\s\"',;:|()\[\]{}<>=]+")
_NUMERIC = re.compile(r"[+\-]?[\d.,\s%]+")

LIMITATIONS = [
    "Equal-value and closest-record checks only detect verbatim or near-verbatim coincidence with the source file "
    "that was assessed; they say nothing about other data an attacker may hold.",
    "No attack-based evaluation (singling-out, linkability, inference attacks against a held-out baseline) is run.",
    "Quasi-identifier and sensitivity classes are human decisions; the tool's proposals are name- and "
    "pattern-based guesses.",
    "Column names, sheet names and table names are copied from the source and must be reviewed by a person.",
    "Per-column statistics that shape the output (formats, digit counts, year range, category frequency profile, "
    "missing-value rates) are disclosed by the output and the reports.",
    "Values in dense identifier spaces (for example short integer keys) can equal real identifiers by coincidence.",
]


def _canon(text: str | None, numeric: bool) -> str | None:
    if text is None:
        return None
    t = text.strip()
    if not t:
        return None
    if numeric:
        try:
            return repr(float(t))
        except ValueError:
            return t
    return t


def _is_identifier(col: dict) -> bool:
    return col["sensitivity"]["class"] == "direct_identifier" or col["key"]["role"] in ("unique", "reference", "repeating")


def _control_values(contract: dict, dataset: dict) -> dict[str, list[list[set]]]:
    """Identifier values of independent datasets generated from the same contract with other seeds.

    They estimate how many values coincide with the source by chance alone: the generator never
    sees the source, so anything the real output shows beyond these controls needs explaining.
    """
    params = dataset.get("params") or {}
    rows = params.get("rows")
    if not rows:
        return {}
    n_total = sum(rows.values())
    k = max(2, min(MAX_CONTROL_SAMPLES, CONTROL_ROW_BUDGET // max(1, n_total)))
    out: dict[str, list[list[set]]] = {}
    for i in range(k):
        ctrl = generate(contract, dict(rows), seed=f"{params.get('seed')}/control/{i}", packing=params.get("packing", "auto"))
        for name, gt in ctrl["tables"].items():
            ct = next(t for t in contract["tables"] if t["name"] == name)
            cols = [c for c in ct["columns"] if c["keep"]]
            sets: list[set] = [set() for _ in cols]
            for r in gt["rows"]:
                if r["kind"] != "data":
                    continue
                for p, col in enumerate(cols):
                    if p < len(r["cells"]) and _is_identifier(col):
                        cell = r["cells"][p]
                        key = _canon(cell.text, cell.kind == "n") if cell.kind != "" else None
                        if key is not None:
                            sets[p].add(key)
            out.setdefault(name, []).append(sets)
    return out


def _artifact_tokens(artifacts: dict[str, str]) -> set[str]:
    tokens: set[str] = set()

    def walk(node):
        if isinstance(node, str):
            s = node.strip()
            if len(s) >= 5:
                tokens.add(s)
            for m in _TOKEN.finditer(node):
                if len(m.group()) >= 5:
                    tokens.add(m.group())
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(k)
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for name, text in artifacts.items():
        if name.endswith(".json"):
            try:
                walk(json.loads(text))
                continue
            except json.JSONDecodeError:
                pass
        walk(text)
    return tokens


_VOCAB: set[str] | None = None


def tool_vocabulary() -> set[str]:
    """Every token of this package's own source text.

    Reports are written with these words, so a source value equal to one of them (for example
    a status column holding "passed") is not evidence of a leak.
    """
    global _VOCAB
    if _VOCAB is None:
        import os

        vocab: set[str] = set()
        root = os.path.dirname(os.path.abspath(__file__))
        for base, _dirs, files in os.walk(root):
            for f in files:
                if f.endswith((".py", ".js", ".html", ".css")):
                    try:
                        with open(os.path.join(base, f), encoding="utf-8") as fh:
                            text = fh.read()
                    except OSError:
                        continue
                    for m in re.finditer(r"[^\W_]+(?:[-'][^\W_]+)*", text):
                        w = m.group()
                        vocab.update((w, w.lower(), w.capitalize(), w.upper()))
        _VOCAB = vocab
    return _VOCAB


def derive_tier(status: str, criteria: dict, contract: dict, policy: PrivacyPolicy,
                attestation: dict | None = None) -> tuple[str, list[str]]:
    """Release tier from the assessment. Monotone: every rule can only lower the tier."""
    reasons: list[str] = []
    if status != PASSED:
        return LOCAL_ONLY, [f"privacy assessment status is '{status}'"]
    if not contract.get("review", {}).get("confirmed"):
        return LOCAL_ONLY, ["the Dataset Contract (keep decisions, sensitivity classes, key roles) was not "
                            "confirmed by a person"]
    tier = RESTRICTED
    all_clear = all(c["status"] == PASSED for c in criteria.values())
    if policy.max_tier == EXTERNAL_CANDIDATE and all_clear and attestation and attestation.get("name") \
            and attestation.get("role"):
        tier = EXTERNAL_CANDIDATE
    else:
        if policy.max_tier != EXTERNAL_CANDIDATE:
            reasons.append(f"policy '{policy.id}' allows at most {policy.max_tier}")
        if not all_clear:
            reasons.append("at least one criterion is not fully met or not evaluable")
        if not attestation:
            reasons.append("no attestation by the data controller is recorded")
    tier = min_tier(tier, policy.max_tier)
    if TIER_ORDER[tier] > TIER_ORDER[RELEASE_TIER_CAP]:
        tier = RELEASE_TIER_CAP
        reasons.append(RELEASE_TIER_CAP_REASON)
    return tier, reasons


def effective_tier(record: dict, today: _dt.date | None = None) -> tuple[str, str]:
    """Tier in force today: an expired assessment falls back to LOCAL_ONLY."""
    today = today or _dt.date.today()
    try:
        review_by = _dt.date.fromisoformat(record["review_by"])
    except (KeyError, ValueError):
        return LOCAL_ONLY, "expired"
    if today > review_by:
        return LOCAL_ONLY, "expired"
    return record["release_tier"], record["assessment_status"]


def assess(path: str, recipe: ParseRecipe, contract: dict, dataset: dict, private_profile: dict,
           policy: PrivacyPolicy, artifacts: dict[str, str] | None = None, attestation: dict | None = None,
           today: _dt.date | None = None) -> dict:
    today = today or _dt.date.today()
    artifacts = artifacts or {}
    source = recipe.open(path)
    regions, _ = resolve_regions(recipe, source)
    by_name = {r.name: r for r in regions if r.include and r.kind == "table"}
    ctables = {t["name"]: t for t in contract["tables"]}
    extra_markers = {str(m).casefold() for m in contract.get("extra_markers", [])}
    public_words = set(DEFAULT_MARKERS) | extra_markers | set(BOOL_WORDS) | {c.casefold() for c in ERROR_CODES}

    # Names copied by design (reviewed by a person, reported below).
    copied_names: set[str] = set()
    for t in contract["tables"]:
        copied_names.update(x for x in (t["name"], t.get("output_name"), t.get("sheet")) if x)
        copied_names.update(c["name"].strip() for c in t["columns"])
    tokens = _artifact_tokens(artifacts) - tool_vocabulary()
    today_tokens = {today.isoformat()}

    controls = _control_values(contract, dataset)
    states = {}
    for name, gt in dataset["tables"].items():
        ct = ctables[name]
        cols = [c for c in ct["columns"] if c["keep"]]
        src_idx = [int(c["id"][1:]) - 1 for c in cols]
        approved = [{str(v).casefold() for v in c["value_policy"].get("approved_literals", [])} for c in cols]
        data_rows = [r for r in gt["rows"] if r["kind"] == "data"]
        n_out = len(data_rows)
        cap = max(1, min(20, int(0.05 * n_out)))
        postings: list[dict] = [dict() for _ in cols]
        row_keys = []
        for rid, r in enumerate(data_rows):
            keys = []
            for p in range(len(cols)):
                cell = r["cells"][p] if p < len(r["cells"]) else None
                key = _canon(cell.text, cell.kind == "n") if cell is not None and cell.kind != "" else None
                if key is not None and (key.casefold() in public_words or key.casefold() in approved[p]):
                    key = None
                keys.append(key)
                if key is not None:
                    postings[p].setdefault(key, []).append(rid)
            row_keys.append(keys)
        informative = [sum(1 for p, k in enumerate(keys) if k is not None and len(postings[p][k]) <= cap)
                       for keys in row_keys]
        qi = [p for p, c in enumerate(cols) if c["sensitivity"]["class"] == "quasi_identifier"]
        ctrl = controls.get(name, [])
        id_cols = [p for p, c in enumerate(cols) if _is_identifier(c)]
        states[name] = {
            "ctrl": ctrl, "ctrl_hits": [[set() for _ in cols] for _ in ctrl], "id_cols": set(id_cols),
            "cols": cols, "src_idx": src_idx, "approved": approved, "postings": postings, "cap": cap,
            "row_keys": row_keys, "informative": informative, "best": [0] * n_out, "n_out": n_out,
            "full_rows": {hash(tuple(k)) for k in row_keys}, "full_hits": 0,
            "overlap": [set() for _ in cols], "qi": qi, "qi_counts": Counter() if len(qi) >= 1 else None,
            "qi_overflow": False, "artifact_hits": Counter(), "rows_seen": 0,
        }

    for sh in source.sheets:
        active = [(by_name[n], st) for n, st in states.items() if n in by_name and by_name[n].sheet == sh.index]
        if not active:
            continue
        for row in source.rows(sh.index):
            idx = row.index
            for reg, st in active:
                if not reg.data_start <= idx <= reg.bottom:
                    continue
                raw = row.raw
                n = len(raw)
                c0 = reg.col_start
                stypes = row.stypes
                keys = []
                hits: dict[int, int] = {}
                postings = st["postings"]
                cap = st["cap"]
                any_value = False
                for p, j in enumerate(st["src_idx"]):
                    i = c0 + j
                    v = raw[i] if i < n else None
                    if v is None or not v or v.isspace():
                        keys.append(None)
                        continue
                    any_value = True
                    key = _canon(v, stypes is not None and stypes[i] == "number")
                    low = key.casefold()
                    if low in public_words or low in st["approved"][p]:
                        keys.append(None)
                        continue
                    keys.append(key)
                    if p in st["id_cols"]:
                        for ci, sets in enumerate(st["ctrl"]):
                            if key in sets[p]:
                                st["ctrl_hits"][ci][p].add(key)
                    post = postings[p].get(key)
                    if post is not None:
                        st["overlap"][p].add(key)
                        if len(post) <= cap:
                            for rid in post:
                                hits[rid] = hits.get(rid, 0) + 1
                    if len(key) >= 5 and key in tokens and key not in copied_names and key not in today_tokens \
                            and not _NUMERIC.fullmatch(key):
                        st["artifact_hits"][st["cols"][p]["id"]] += 1
                if not any_value:
                    continue
                st["rows_seen"] += 1
                best = st["best"]
                for rid, m in hits.items():
                    if m > best[rid]:
                        best[rid] = m
                if hash(tuple(keys)) in st["full_rows"] and sum(1 for k in keys if k is not None) >= policy.min_informative_cells:
                    st["full_hits"] += 1
                qc = st["qi_counts"]
                if qc is not None and not st["qi_overflow"]:
                    qc[hash(tuple(keys[p] for p in st["qi"]))] += 1
                    if len(qc) > MAX_QI_COMBINATIONS:
                        st["qi_overflow"] = True

    # ---- metrics --------------------------------------------------------------------------------
    single = {"rows_evaluated": 0, "rows_skipped_low_information": 0, "max_similarity": 0.0,
              "rows_at_or_above_threshold": 0, "threshold": policy.max_row_similarity,
              "source_rows_equal_to_a_synthetic_row": 0, "quasi_identifier_columns": [],
              "source_unique_combinations_replicated": None, "quasi_identifiers_evaluable": False}
    link_cols = []
    info_cols = []
    link_failed = dense = False
    artifact_hits = 0
    literal_cols = []
    sensitive_literals = False
    for name, st in states.items():
        for rid in range(st["n_out"]):
            inf = st["informative"][rid]
            if inf < policy.min_informative_cells:
                single["rows_skipped_low_information"] += 1
                continue
            single["rows_evaluated"] += 1
            sim = st["best"][rid] / inf
            single["max_similarity"] = max(single["max_similarity"], round(sim, 4))
            if sim >= policy.max_row_similarity:
                single["rows_at_or_above_threshold"] += 1
        single["source_rows_equal_to_a_synthetic_row"] += st["full_hits"]
        if st["qi"]:
            single["quasi_identifier_columns"] += [f"{name}.{st['cols'][p]['name']}" for p in st["qi"]]
            if not st["qi_overflow"]:
                single["quasi_identifiers_evaluable"] = True
                rep = sum(1 for keys in st["row_keys"]
                          if any(keys[p] is not None for p in st["qi"])
                          and st["qi_counts"].get(hash(tuple(keys[p] for p in st["qi"]))) == 1)
                single["source_unique_combinations_replicated"] = (single["source_unique_combinations_replicated"] or 0) + rep
        for p, col in enumerate(st["cols"]):
            distinct_syn = len(st["postings"][p])
            observed = len(st["overlap"][p])
            entry = {"table": name, "column": col["name"], "distinct_synthetic_values": distinct_syn,
                     "values_also_in_source": observed}
            is_id = _is_identifier(col)
            if col["value_policy"]["mode"] != "synthetic":
                literal_cols.append({"table": name, "column": col["name"],
                                     "approved_values": len(col["value_policy"].get("approved_literals", [])),
                                     "approved_by": col["value_policy"].get("approved_by"),
                                     "sensitivity": col["sensitivity"]["class"]})
                if col["sensitivity"]["class"] in ("sensitive", "quasi_identifier", "direct_identifier"):
                    sensitive_literals = True
            if not is_id:
                if observed:
                    info_cols.append(entry)
                continue
            chance = [len(h[p]) for h in st["ctrl_hits"]]
            mean = sum(chance) / len(chance) if chance else 0.0
            allowed = min(distinct_syn, max(max(chance, default=0), int(mean + 3 * math.sqrt(mean) + 0.5))
                          + policy.identifier_overlap_slack)
            is_dense = mean >= max(0.5, 0.01 * distinct_syn)
            entry.update(control_samples=len(chance), most_coincidences_in_a_control_sample=max(chance, default=0),
                         expected_by_chance=round(mean, 2), allowed=allowed,
                         verdict="within_chance" if observed <= allowed else "exceeds_chance",
                         dense_value_space=is_dense)
            if observed > allowed:
                link_failed = True
            if observed and is_dense:
                dense = True
            link_cols.append(entry)
        artifact_hits += sum(st["artifact_hits"].values())

    residual: list[str] = []
    s_failed = single["rows_at_or_above_threshold"] > 0 or (single["source_unique_combinations_replicated"] or 0) > 0
    if s_failed:
        s_status = FAILED
    elif not single["quasi_identifier_columns"]:
        s_status = RESIDUAL
        residual.append("Singling out: no column is designated as a quasi-identifier, so replication of rare "
                        "combinations could not be evaluated; only whole-row closeness to source rows was measured.")
    elif not single["quasi_identifiers_evaluable"]:
        s_status = NOT_EVALUABLE
    else:
        s_status = PASSED
    if link_failed:
        l_status = FAILED
    elif dense:
        l_status = RESIDUAL
        residual.append("Linkability: some identifier-like columns use a dense value space, so a synthetic key can "
                        "equal a real key by coincidence. Such a key carries no attribute of the real record.")
    else:
        l_status = PASSED
    if sensitive_literals:
        i_status = RESIDUAL
        residual.append("Inference: literal category values were approved on a column classed as identifying or "
                        "sensitive; their existence and approximate frequency are disclosed.")
    else:
        i_status = PASSED
    private_keys = sum(1 for text in artifacts.values() if '"_private"' in text)
    k_status = FAILED if artifact_hits or private_keys else PASSED
    criteria = {
        "singling_out": {"status": s_status, "metrics": single,
                         "method": "closest source row per synthetic row on informative cells; replication of "
                                   "source-unique quasi-identifier combinations"},
        "linkability": {"status": l_status, "metrics": {"identifier_columns": link_cols},
                        "method": "synthetic identifier values found in the source, compared with the same count "
                                  "for independent control datasets generated from the same contract with other seeds",
                        "note": "Fictional keys repeating inside or across synthetic tables are intended "
                                "structure and are not counted as a risk."},
        "inference": {"status": i_status,
                      "metrics": {"columns_with_approved_literals": literal_cols},
                      "method": "by construction: columns are generated independently of each other from "
                                "pattern classes, so no relationship between attributes of a record is carried"},
        "source_leakage": {"status": k_status,
                           "metrics": {"source_values_found_in_reports": artifact_hits,
                                       "documents_with_private_fields": private_keys,
                                       "documents_scanned": sorted(artifacts),
                                       "other_columns_with_coincident_values": info_cols},
                           "method": "every source cell of five characters or more is looked up among the "
                                     "strings of the exported reports, manifest and contract"},
    }
    status = FAILED if any(c["status"] == FAILED for c in criteria.values()) else PASSED
    tier, reasons = derive_tier(status, criteria, contract, policy, attestation)
    headers = sum(len([c for c in t["columns"] if c["keep"]]) for t in contract["tables"] if t["header_present"])
    suspicious = sum(1 for t in contract["tables"] if t["header_present"] for c in t["columns"]
                     if c["keep"] and (len(c["name"]) > 60 or "@" in c["name"] or sum(ch.isdigit() for ch in c["name"]) >= 6))
    record = {
        "record_version": 1, "tool_version": __version__, "date": today.isoformat(),
        "review_by": (today + _dt.timedelta(days=policy.review_interval_days)).isoformat(),
        "transformation_class": "synthetic", "assessment_status": status, "release_tier": tier,
        "tier_reasons": reasons, "policy": policy.to_dict(),
        "attacker_assumptions": list(policy.attacker_assumptions),
        "contract_review": contract.get("review"),
        "designated_columns": {
            "quasi_identifiers": [f"{t['name']}.{c['name']}" for t in contract["tables"] for c in t["columns"]
                                  if c["keep"] and c["sensitivity"]["class"] == "quasi_identifier"],
            "sensitive": [f"{t['name']}.{c['name']}" for t in contract["tables"] for c in t["columns"]
                          if c["keep"] and c["sensitivity"]["class"] == "sensitive"],
            "direct_identifiers": [f"{t['name']}.{c['name']}" for t in contract["tables"] for c in t["columns"]
                                   if c["keep"] and c["sensitivity"]["class"] == "direct_identifier"],
            "confirmed_by_a_person": bool(contract.get("review", {}).get("confirmed")),
        },
        "information_flow": {
            "generator_inputs": ["Dataset Contract", "row counts", "seed"],
            "statement": "The generator has no access to source values. The contract carries pattern classes, "
                         "rates and the literal values listed under copied_literals.",
            "copied_literals": {"column_names": headers, "column_names_needing_review": suspicious,
                                "missing_markers_and_boolean_words": "allowlist",
                                "approved_category_columns": literal_cols},
        },
        "criteria": criteria, "residual_risk_statements": residual, "limitations": LIMITATIONS,
        "attestation": attestation, "generation": dataset.get("params"),
        "statement": NON_CERTIFICATION_STATEMENT,
    }
    record["record_id"] = hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return record


def not_assessed(contract: dict, dataset: dict, policy: PrivacyPolicy, today: _dt.date | None = None) -> dict:
    """Record for a run where the assessment was skipped: always LOCAL_ONLY."""
    today = today or _dt.date.today()
    record = {
        "record_version": 1, "tool_version": __version__, "date": today.isoformat(),
        "review_by": today.isoformat(), "transformation_class": "synthetic", "assessment_status": "none",
        "release_tier": LOCAL_ONLY, "tier_reasons": ["the privacy assessment was not run"],
        "policy": policy.to_dict(), "attacker_assumptions": list(policy.attacker_assumptions),
        "contract_review": contract.get("review"), "criteria": {}, "residual_risk_statements": [],
        "limitations": LIMITATIONS, "attestation": None, "generation": dataset.get("params"),
        "statement": NON_CERTIFICATION_STATEMENT,
    }
    record["record_id"] = hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return record
