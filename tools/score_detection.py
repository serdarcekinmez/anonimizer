"""Compare an Exception Catalogue with a fixture's ground truth.

The ground truth comes from tests/fixtures/build_fixtures.py, which does not use the
detector. Matching is on (table, column, class) with exact counts.
"""

from __future__ import annotations

from collections import defaultdict


def detected_counts(profile: dict) -> dict[tuple, int]:
    from anonimizer.profile import iter_exceptions

    out: dict[tuple, int] = defaultdict(int)
    for ex in iter_exceptions(profile):
        if ex.get("table") is None:
            continue
        out[(ex["table"], ex.get("column_name"), ex["class"])] += ex["count"] or 0
    return dict(out)


def score(profile: dict, truth: dict) -> dict:
    det = detected_counts(profile)
    matched, missed, mismatched = [], [], []
    truth_keys = set()
    for a in truth["anomalies"]:
        key = (a["table"], a["column"], a["class"])
        truth_keys.add(key)
        got = det.get(key)
        item = {"table": a["table"], "column": a["column"], "class": a["class"], "expected": a["count"], "detected": got or 0}
        if got == a["count"]:
            matched.append(item)
        elif not got:
            missed.append(item)
        else:
            mismatched.append(item)
    additional = [{"table": k[0], "column": k[1], "class": k[2], "detected": v}
                  for k, v in sorted(det.items(), key=lambda kv: (kv[0][0], kv[0][1] or "", kv[0][2])) if k not in truth_keys]
    total = len(truth["anomalies"])
    return {"fixture": truth["fixture"], "planted_classes": total, "matched_exactly": len(matched),
            "count_mismatch": mismatched, "missed": missed, "additional_findings": additional,
            "recall_exact": round(len(matched) / total, 4) if total else 1.0,
            "recall_any": round((len(matched) + len(mismatched)) / total, 4) if total else 1.0}
