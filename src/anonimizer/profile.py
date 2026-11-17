"""Profiler and Exception Catalogue.

A single streaming pass feeds per-column accumulators. Every cell is classified (no sampling),
so a single odd value deep in a large file is found. The result is the *private* profile: it
holds source row numbers, exact text layouts and category values under ``_private`` keys.
``to_shareable`` removes or generalises all of that under an explicit PrivacyPolicy; the
Dataset Contract and every exported report are built from the shareable form only.
"""

from __future__ import annotations

import copy
import re
from array import array
from collections import Counter

from . import __version__
from .grid.model import ABSENT, EMPTY, EMPTY_STRING, NUMBER, QUOTED_EMPTY, STRING_TYPES, TEXT, WHITESPACE, Row
from .patterns import (
    AMBIG,
    BOOLEAN,
    CONTROL,
    DATE,
    DEFAULT_MARKERS,
    ERR,
    FORMULA_LIKE,
    INVALID,
    LEADZERO,
    MISSING,
    MULTILINE,
    NEG,
    NONASCII,
    NUM,
    PAD_LEAD,
    PADDED,
    PLUS,
    TXT,
    UNPADDED,
    ZERO,
    bucket,
    classify,
    generalize_shape,
    safe_number_format,
    shape_display,
    shape_of,
)
from .policy import PrivacyPolicy
from .recipe import ParseRecipe, region_to_spec, resolve_regions
from .regions import Region

PROFILE_VERSION = 1
RARE_SHARE = 0.05
CAT_CAP = 1000
HASH_CAP = 200_000
SHAPE_CAP = 3000
MEMO_CAP = 50_000
LOC_CAP = 5
MAX_RARE_PATTERNS = 6

PRIORITY = {
    "type": 1, "missing": 1, "value": 1, "xlsx": 1, "storage": 1,
    "key": 2, "row": 2,
    "format": 3, "numeric": 3,
    "text": 4, "category": 4, "header": 4, "file": 5, "workbook": 5,
}
_FAMILY_NAME = {NUM: "number", DATE: "date", BOOLEAN: "boolean", TXT: "text"}
_ID_TOKEN = re.compile(r"(?:^|[^a-z0-9])(id|ids|key|code|ref|no|nr|num|number|uuid|guid|sku|numero|matricule|identifiant)(?:$|[^a-z0-9])")
_CAMEL_ID = re.compile(r"[a-z](Id|ID|Key|Code|Ref|No)$")
_SENSITIVE_HINTS = [
    ("direct_identifier", re.compile(r"e-?mail|courriel|phone|t[ée]l|mobile|fax|\bssn\b|\bnir\b|passport|passeport|iban|\bbic\b|account|compte|licen[cs]e|login|username|user_name|\bip\b|siret|siren|social")),
    ("direct_identifier", re.compile(r"(first|last|sur|full|given|family|maiden)[ _-]?name|\bnom\b|pr[ée]nom|\bname\b|contact[ _-]?(name|person)|customer[ _-]?name|client[ _-]?name")),
    ("quasi_identifier", re.compile(r"birth|naiss|\bdob\b|\bage\b|gender|\bsex|sexe|zip|postal|postcode|city|ville|town|country|pays|region|address|adresse|street|\brue\b|nationalit|profession|job|occupation|employer|department|d[ée]partement|commune|marital")),
    ("sensitive", re.compile(r"salary|salaire|income|revenu|diagnos|health|sant[ée]|medical|disease|maladie|religio|ethnic|politic|union|syndic|orientation|criminal|judici|disab|handicap|credit|debt|dette|password|secret")),
]


def _id_named(name: str) -> bool:
    return bool(_ID_TOKEN.search(name.lower()) or _CAMEL_ID.search(name))


def _rare(count: int, n: int) -> bool:
    return n > 0 and count <= max(1, int(0.01 * n)) and count / n < 0.2


def _rare_shape(count: int, n: int) -> bool:
    return n > 0 and count <= max(1, int(0.01 * n)) and count / n < 0.05


class ColumnAcc:
    __slots__ = ("index", "name", "markers", "date1904", "n", "classes", "memo", "vals", "hcount", "harr",
                 "formulas", "nfmt", "n_shapes", "n_gshapes")

    def __init__(self, index: int, name: str, markers: frozenset, date1904: bool):
        self.index = index
        self.name = name
        self.markers = markers
        self.date1904 = date1904
        self.n = 0
        self.classes: dict[tuple, list] = {}
        self.memo: dict = {}
        self.vals: dict[str, int] | None = {}
        self.hcount: dict[int, int] | None = None
        self.harr: array | None = None
        self.formulas = 0
        self.nfmt: Counter = Counter()
        self.n_shapes = 0
        self.n_gshapes = 0

    def _intern(self, raw, stype, quoted, fmt) -> list:
        v = classify(raw, stype, quoted, fmt, self.markers, self.date1904)
        fam, sub, flags, a, b = v
        shape = None
        if fam == TXT:
            s = raw.strip()
            a, b = bucket(a)[1], min(b, 64)
            if self.n_shapes < SHAPE_CAP:
                shape = shape_of(s)
            elif self.n_gshapes < SHAPE_CAP:
                shape = generalize_shape(shape_of(s))
        elif fam == MISSING:
            flags = 0
            a = min(a, 8) if sub == WHITESPACE else 0
        ckey = (fam, sub, flags, a, b, shape, stype)
        ent = self.classes.get(ckey)
        if ent is None:
            ent = self.classes[ckey] = [0, [], fam != MISSING and fam != ERR]
            if shape is not None:
                if len(shape[0]) == 2:
                    self.n_shapes += 1
                else:
                    self.n_gshapes += 1
        return ent

    def add(self, raw, stype, quoted, fmt, row_idx) -> None:
        self.n += 1
        if fmt is None and not quoted:
            mkey = raw if stype == TEXT else (raw, stype)
        else:
            mkey = (raw, stype, quoted, fmt)
            if fmt is not None:
                self.nfmt[fmt] += 1
        ent = self.memo.get(mkey)
        if ent is None:
            ent = self._intern(raw, stype, quoted, fmt)
            if len(self.memo) < MEMO_CAP:
                self.memo[mkey] = ent
        ent[0] += 1
        if len(ent[1]) < LOC_CAP:
            ent[1].append(row_idx + 1)
        if ent[2]:
            vals = self.vals
            if vals is not None:
                vals[raw] = vals.get(raw, 0) + 1
                if len(vals) > CAT_CAP:
                    self.hcount = {hash(k): c for k, c in vals.items()}
                    self.vals = None
            elif self.hcount is not None:
                hc = self.hcount
                h = hash(raw)
                hc[h] = hc.get(h, 0) + 1
                if len(hc) > HASH_CAP:
                    arr = array("q")
                    for hh, c in hc.items():
                        arr.extend([hh] * c)
                    self.harr = arr
                    self.hcount = None
            else:
                self.harr.append(hash(raw))

    # -- distinct values ------------------------------------------------------------------
    def distinct_stats(self) -> dict:
        if self.vals is not None:
            counts = list(self.vals.values())
        elif self.hcount is not None:
            counts = list(self.hcount.values())
        else:
            counts = _run_lengths(self.harr)
        n_distinct = len(counts)
        total = sum(counts)
        m1 = sum(1 for c in counts if c == 1)
        m2 = sum(1 for c in counts if c == 2)
        return {"n_distinct": n_distinct, "n_values": total, "repeated_values": n_distinct - m1,
                "extra_occurrences": total - n_distinct,
                "multiplicity": {"1": m1, "2": m2, "3+": n_distinct - m1 - m2},
                "max_multiplicity": max(counts, default=0)}

    def hash_set(self) -> set[int]:
        if self.vals is not None:
            return {hash(k) for k in self.vals}
        if self.hcount is not None:
            return set(self.hcount)
        return set(self.harr)

    def hash_counts(self) -> dict[int, int]:
        if self.vals is not None:
            return {hash(k): c for k, c in self.vals.items()}
        if self.hcount is not None:
            return self.hcount
        return dict(Counter(self.harr))


def _run_lengths(arr: array) -> list[int]:
    out: list[int] = []
    prev = None
    run = 0
    for h in sorted(arr):
        if h == prev:
            run += 1
        else:
            if run:
                out.append(run)
            prev, run = h, 1
    if run:
        out.append(run)
    return out


class _Feats:
    def __init__(self):
        self.d: dict[tuple, dict] = {}

    def add(self, cls: str, dkey, count: int, rows, gen=None, detail=None) -> dict:
        f = self.d.get((cls, dkey))
        if f is None:
            f = self.d[(cls, dkey)] = {"class": cls, "detail": dict(detail or {}), "count": 0, "rows": [],
                                       "gen": gen}
        f["count"] += count
        if len(f["rows"]) < LOC_CAP or (rows and rows[0] < f["rows"][-1]):
            f["rows"] = sorted(set(f["rows"]) | set(rows))[:LOC_CAP]
        return f


def _num_base(sub: str) -> str:
    return sub.split("|", 1)[0]


def _resolve_numbers(classes: dict) -> tuple[list, str | None, bool]:
    """Normalise number classes: resolve the ``1,234`` ambiguity from column context."""
    subs = Counter()
    for k, e in classes.items():
        if k[0] == NUM:
            subs[_num_base(k[1])] += e[0]
    target = resolution = None
    unresolved = False
    if "comma_ambiguous" in subs:
        dec_comma = subs.keys() & {"dec_comma", "thou_dot_dec_comma", "thou_space_dec_comma"}
        dot_side = subs.keys() & {"thou_comma", "thou_comma_dec_dot", "dec_dot"}
        if dec_comma and not dot_side:
            target, resolution = "dec_comma", "decimal_comma"
        elif dot_side and not dec_comma:
            target, resolution = "thou_comma", "thousands_separator"
        else:
            target, resolution, unresolved = "thou_comma", "assumed_thousands_separator", True
    recs = []
    for k, e in classes.items():
        if k[0] != NUM:
            continue
        sub, a, b = k[1], k[3], k[4]
        if target and _num_base(sub) == "comma_ambiguous":
            sub = sub.replace("comma_ambiguous", target, 1)
            if target == "dec_comma":
                a, b = max(1, a - 3), 3
        recs.append((sub, k[2], a, b, k[6], e[0], e[1]))
    return recs, resolution, unresolved


def _resolve_dates(classes: dict) -> tuple[list, str, bool]:
    d_cnt = m_cnt = x_cnt = 0
    for k, e in classes.items():
        if k[0] != DATE:
            continue
        if k[1].startswith("D/M/"):
            d_cnt += e[0]
        elif k[1].startswith("M/D/"):
            m_cnt += e[0]
        elif k[1].startswith("X/X/") and not k[2] & INVALID:
            x_cnt += e[0]
    if d_cnt and m_cnt:
        order = "DMY" if d_cnt >= m_cnt else "MDY"
    elif d_cnt:
        order = "DMY"
    elif m_cnt:
        order = "MDY"
    else:
        order = "ambiguous" if x_cnt else "n/a"
    conflict = bool(d_cnt and m_cnt)
    prefix = {"DMY": "D/M/", "MDY": "M/D/"}.get(order)
    full = sum(e[0] for k, e in classes.items() if k[0] == DATE and "B" in k[1])
    abbr = sum(e[0] for k, e in classes.items() if k[0] == DATE and "b" in k[1])
    month_tok = "B" if full > abbr else "b"
    recs = []
    for k, e in classes.items():
        if k[0] != DATE:
            continue
        sub = k[1]
        if prefix and sub.startswith("X/X/"):
            sub = prefix + sub[4:]
        if "e" in sub and not sub.startswith("excel"):
            sub = sub.replace("e", month_tok)  # "May" takes the form the rest of the column uses
        recs.append((sub, k[2], k[3], k[6], e[0], e[1]))
    return recs, order, conflict


def _demote_letter_booleans(classes: dict) -> dict:
    """Single letters Y/N only count as booleans in a column that is mostly boolean."""
    counts: Counter = Counter()
    for k, e in classes.items():
        if k[0] not in (MISSING, ERR):
            counts[k[0]] += e[0]
    if not counts.get(BOOLEAN) or counts[BOOLEAN] * 2 >= sum(counts.values()):
        return classes
    out: dict = {}
    for k, e in classes.items():
        if k[0] == BOOLEAN and k[1].startswith("y_n"):
            shape = (("A" if k[1].endswith("upper") or k[1].endswith("title") else "a", 1),)
            nk = (TXT, "alpha", k[2], 1, 1, shape, k[6])
            if nk in out:
                out[nk] = [out[nk][0] + e[0], sorted(out[nk][1] + e[1])[:LOC_CAP], True]
            else:
                out[nk] = e
        elif k in out:
            out[k] = [out[k][0] + e[0], sorted(out[k][1] + e[1])[:LOC_CAP], True]
        else:
            out[k] = e
    return out


def finalize_column(acc: ColumnAcc, xlsx: bool) -> dict:
    cl = _demote_letter_booleans(acc.classes)
    missing: Counter = Counter()
    markers: Counter = Counter()
    fam: Counter = Counter()
    storage: Counter = Counter()
    feats = _Feats()
    for k, e in cl.items():
        f, sub, c = k[0], k[1], e[0]
        if f == MISSING:
            if sub.startswith("marker:"):
                lit = sub[7:]
                markers[lit] += c
                feats.add("missing.marker", lit, c, e[1], {"g": "literal", "value": lit}, {"literal": lit})
                continue
            if sub == ABSENT:
                if not xlsx:
                    missing[ABSENT] += c  # counted at row level (ragged rows)
                    continue
                sub = EMPTY
            missing[sub] += c
            gen = {"g": "whitespace", "n": k[3]} if sub == WHITESPACE else {"g": sub}
            feats.add("missing." + sub, k[3] if sub == WHITESPACE else None, c, e[1], gen,
                      {"length": k[3]} if sub == WHITESPACE else None)
        elif f == ERR:
            storage[k[6]] += c
            feats.add("xlsx.error_value", sub, c, e[1], {"g": "error", "code": sub}, {"code": sub})
        else:
            fam[f] += c
            storage[k[6]] += c
    n_values = sum(fam.values())
    n_err = sum(e[0] for k, e in cl.items() if k[0] == ERR)
    order = {NUM: 3, DATE: 2, BOOLEAN: 1, TXT: 0}
    dom = max(fam, key=lambda f: (fam[f], order[f])) if fam else None
    out: dict = {
        "index": acc.index, "name": acc.name, "n_cells": acc.n,
        "n_values": n_values, "n_missing": acc.n - n_values - n_err,
        "missing": {k: v for k, v in sorted(missing.items())},
        "markers": {k: v for k, v in sorted(markers.items())},
        "families": {_FAMILY_NAME[f]: c for f, c in fam.most_common()},
        "error_values": n_err,
        "storage": dict(storage.most_common()) if xlsx else {},
        "numeric_storage": xlsx and storage.get(NUMBER, 0) > 0
        and storage.get(NUMBER, 0) >= sum(v for k, v in storage.items() if k in STRING_TYPES),
        "number_formats": dict(acc.nfmt.most_common(10)) if xlsx else {},
        "formula_cells": acc.formulas,
        "ambiguities": [],
    }
    family_gens: dict[str, dict] = {}
    logical = "empty"

    # ---- numbers --------------------------------------------------------------------------
    nums, comma_res, comma_unresolved = _resolve_numbers(cl)
    if nums:
        n_num = fam[NUM]
        fm: Counter = Counter()
        for sub, _fl, _a, _b, _st, c, _r in nums:
            fm[sub] += c
        n_int = fm.get("int", 0)
        non_int = Counter({s: c for s, c in fm.items() if s != "int"})
        decimalish = sum(c for s, c in non_int.items() if not _num_base(s).startswith("thou") or "dec" in s
                         ) - sum(c for s, c in non_int.items() if _num_base(s) in ("sci",))
        if non_int and (non_int.most_common(1)[0][1] > n_int or decimalish / n_num >= RARE_SHARE):
            dom_fmt = non_int.most_common(1)[0][0]
        else:
            dom_fmt = "int"
        compatible = {dom_fmt} | ({"int"} if "dec" in dom_fmt else set())
        idig: Counter = Counter()
        ddig: Counter = Counter()
        neg = zero = lz = plus = 0
        for sub, fl, a, b, _st, c, _r in nums:
            if sub in compatible:
                idig[a] += c
                ddig[b] += c
            neg += c if fl & NEG else 0
            zero += c if fl & ZERO else 0
            lz += c if fl & LEADZERO else 0
            plus += c if fl & PLUS else 0
        digit_code = dom_fmt == "int" and lz / n_num >= 0.3
        typ_i = {d for d, c in idig.items() if not _rare(c, n_num)} or set(idig)
        typ_d = {d for d, c in ddig.items() if not _rare(c, n_num)} or set(ddig)
        out_i = {d for d in idig if d not in typ_i and d > max(typ_i)}
        out_d = {d for d in ddig if d not in typ_d and d > max(typ_d)}
        logical = "digit_code" if digit_code else ("decimal" if "dec" in dom_fmt or _num_base(dom_fmt) == "sci" else "integer")
        base = {"g": "number", "fmt": dom_fmt,
                "int_digits": {str(d): c for d, c in sorted(idig.items()) if d not in out_i},
                "dec_digits": {str(d): c for d, c in sorted(ddig.items()) if d not in out_d},
                "p_neg": round(neg / n_num, 4) if neg / n_num >= RARE_SHARE else 0.0,
                "p_zero": round(zero / n_num, 4) if zero / n_num >= RARE_SHARE else 0.0,
                "leading_zeros": digit_code}
        family_gens[NUM] = base
        out["number"] = {"formats": dict(fm.most_common()), "dominant_format": dom_fmt,
                         "int_digits": {str(d): c for d, c in sorted(idig.items())},
                         "dec_digits": {str(d): c for d, c in sorted(ddig.items())},
                         "negative": neg, "zero": zero, "leading_zero": lz, "explicit_plus": plus,
                         "comma_resolution": comma_res}
        if comma_unresolved:
            out["ambiguities"].append("values such as 1,234 could be thousands or decimal comma; "
                                      "treated as thousands separators")
        if dom == NUM:
            for sub, fl, a, b, _st, c, rows in nums:
                if sub not in compatible:
                    feats.add("format.number_deviation", sub, c, rows,
                              {"g": "number", "fmt": sub, "int_digits": {str(a): 1}, "dec_digits": {str(b): 1}},
                              {"format": sub, "dominant_format": dom_fmt})
                else:
                    if a in out_i:
                        feats.add("numeric.magnitude_outlier", a, c, rows,
                                  {"g": "base", "int_digits": a}, {"integer_digits": a})
                    if b in out_d:
                        feats.add("numeric.precision_deviation", b, c, rows,
                                  {"g": "base", "dec_digits": b}, {"decimal_digits": b})
                if fl & NEG:
                    feats.add("numeric.negative", None, c, rows, {"g": "base", "neg": True})
                if fl & ZERO:
                    feats.add("numeric.zero", None, c, rows, {"g": "base", "zero": True})
                if fl & LEADZERO and not digit_code:
                    feats.add("numeric.leading_zero", None, c, rows, {"g": "base", "leading_zero": True})
                if fl & PLUS:
                    feats.add("numeric.explicit_plus", None, c, rows, {"g": "base", "plus": True})

    # ---- dates ----------------------------------------------------------------------------
    dates, order_res, conflict = _resolve_dates(cl)
    if dates:
        dm: Counter = Counter()
        years = []
        padded = unpadded = invalid = 0
        for sub, fl, yr, _st, c, _r in dates:
            dm[sub] += c
            if fl & INVALID:
                invalid += c
            elif yr:
                years.append(yr)
            padded += c if fl & LEADZERO else 0
            unpadded += c if fl & UNPADDED else 0
        dom_dfmt = dm.most_common(1)[0][0]
        has_time = "h:m" in dom_dfmt or dom_dfmt in ("excel_datetime",)
        only_time = dom_dfmt in ("h:m", "h:m:s", "excel_time")
        dlogical = "time" if only_time else "datetime" if has_time else "date"
        dbase = {"g": "date", "fmt": dom_dfmt, "year_min": min(years) if years else None,
                 "year_max": max(years) if years else None,
                 "padding": "unpadded" if unpadded > padded else "padded"}
        if xlsx and dom_dfmt.startswith("excel_") and acc.nfmt:
            dbase["number_format"] = acc.nfmt.most_common(1)[0][0]
        family_gens[DATE] = dbase
        out["date"] = {"formats": dict(dm.most_common()), "dominant_format": dom_dfmt, "order": order_res,
                       "invalid": invalid, "year_min": dbase["year_min"], "year_max": dbase["year_max"],
                       "padding": dbase["padding"]}
        if order_res == "ambiguous":
            out["ambiguities"].append("day/month order cannot be decided from the values (no day above 12)")
        if dom == DATE:
            logical = dlogical
            for sub, fl, _yr, _st, c, rows in dates:
                if fl & INVALID:
                    feats.add("value.invalid_date", sub, c, rows,
                              {"g": "date", "fmt": dom_dfmt if sub.startswith("X/X/") else sub, "invalid": True},
                              {"format": sub})
                elif sub != dom_dfmt:
                    cls = "format.date_order_conflict" if conflict and sub[:4] in ("D/M/", "M/D/") \
                        and dom_dfmt[:4] in ("D/M/", "M/D/") and sub[4:] == dom_dfmt[4:] else "format.date_deviation"
                    feats.add(cls, sub, c, rows, {"g": "date", "fmt": sub},
                              {"format": sub, "dominant_format": dom_dfmt})

    # ---- booleans -------------------------------------------------------------------------
    if fam.get(BOOLEAN):
        bs: Counter = Counter()
        true = 0
        for k, e in cl.items():
            if k[0] == BOOLEAN:
                bs[k[1]] += e[0]
                true += e[0] if k[3] else 0
        dom_style = bs.most_common(1)[0][0]
        family_gens[BOOLEAN] = {"g": "bool", "style": dom_style, "p_true": round(true / fam[BOOLEAN], 3)}
        out["boolean"] = {"styles": dict(bs.most_common()), "true": true, "false": fam[BOOLEAN] - true}
        if dom == BOOLEAN:
            logical = "boolean"
            for k, e in cl.items():
                if k[0] == BOOLEAN and k[1] != dom_style:
                    feats.add("format.boolean_deviation", k[1], e[0], e[1], {"g": "bool", "style": k[1]},
                              {"style": k[1], "dominant_style": dom_style})

    # ---- text -----------------------------------------------------------------------------
    private: dict = {}
    if fam.get(TXT):
        n_txt = fam[TXT]
        kinds: dict[str, dict] = {}
        exact: Counter = Counter()
        gen_only: Counter = Counter()
        rows_by_shape: dict = {}
        for k, e in cl.items():
            if k[0] != TXT:
                continue
            kind, fl, a, b, shape, c = k[1], k[2], k[3], k[4], k[5], e[0]
            ks = kinds.setdefault(kind, {"count": 0, "length": Counter(), "words": Counter(), "case": Counter()})
            ks["count"] += c
            ks["case"][_case_of(shape)] += c
            ks["length"][a] += c
            ks["words"][b] += c
            if shape is not None:
                (exact if len(shape[0]) == 2 else gen_only)[shape] += c
                rows_by_shape.setdefault(shape, [kind, []])[1].extend(e[1])
        gen_all = Counter(gen_only)
        for shape, c in exact.items():
            gen_all[generalize_shape(shape)] += c
        top = exact.most_common(20)
        cov5 = sum(c for _s, c in top[:5]) / n_txt
        cov20 = sum(c for _s, c in top) / n_txt
        if cov20 >= 0.8 and cov5 >= 0.5:
            structure = "structured"
        elif sum(c for _s, c in gen_all.most_common(20)) / n_txt >= 0.8:
            structure = "patterned"
        else:
            structure = "free"
        out["text"] = {
            "structure": structure, "distinct_layouts": len(exact) + len(gen_only),
            "kinds": {kd: {"count": v["count"], "length": {str(a): c for a, c in sorted(v["length"].items())},
                           "words": {str(w): c for w, c in sorted(v["words"].items())},
                           "case": dict(v["case"].most_common())}
                      for kd, v in sorted(kinds.items(), key=lambda kv: -kv[1]["count"])},
        }
        private["exact_shapes"] = [[list(map(list, s)), c] for s, c in exact.most_common(400)]
        private["general_shapes"] = [[list(map(list, s)), c] for s, c in gen_all.most_common(200)]
        family_gens[TXT] = {"g": "text"}
        if dom == TXT:
            logical = "text"
            typical_kinds = {kd for kd, v in kinds.items() if v["count"] / n_txt >= RARE_SHARE}
            spaced = {"words", "sentence", "phrase"}
            rare: list[tuple] = []
            # Rarity of a layout only means something in a column that is otherwise regular.
            pool = exact if structure == "structured" else gen_all
            regular = sum(c for c in pool.values() if not _rare_shape(c, n_txt)) / n_txt >= 0.9
            if structure == "structured" and regular:
                for shape, c in exact.items():
                    if _rare_shape(c, n_txt):
                        rare.append((c, generalize_shape(shape), rows_by_shape[shape]))
            elif structure == "patterned" and regular:
                for shape, c in gen_all.items():
                    if _rare_shape(c, n_txt):
                        rr = rows_by_shape.get(shape)
                        if rr is None:
                            rr = [None, []]
                            for s2, v2 in rows_by_shape.items():
                                if len(s2[0]) == 2 and generalize_shape(s2) == shape:
                                    rr[0] = v2[0]
                                    rr[1].extend(v2[1])
                        rare.append((c, shape, rr))
            merged: dict = {}
            for c, gshape, (kind, rows) in rare:
                m = merged.setdefault(gshape, [0, kind, []])
                m[0] += c
                m[2].extend(rows)
            ranked = sorted(merged.items(), key=lambda kv: (-kv[1][0], min(kv[1][2], default=0)))
            for gshape, (c, kind, rows) in ranked[:MAX_RARE_PATTERNS]:
                cls = "text.unexpected_free_text" if kind in spaced and not typical_kinds & spaced else "text.rare_pattern"
                feats.add(cls, gshape, c, sorted(rows)[:LOC_CAP],
                          {"g": "text_gshape", "shape": [list(x) for x in gshape]},
                          {"pattern": shape_display(gshape), "kind": kind})
            if len(ranked) > MAX_RARE_PATTERNS:
                rest = ranked[MAX_RARE_PATTERNS:]
                feats.add("text.rare_pattern", "__other__", sum(v[0] for _g, v in rest),
                          sorted(r for _g, v in rest for r in v[2])[:LOC_CAP], None,
                          {"other_rare_layouts": len(rest)})
            if structure == "free":
                for kd, v in kinds.items():
                    if _rare(v["count"], n_txt) and kd in ("email", "url", "uuid", "ipv4", "phone", "digits", "symbols"):
                        rows = sorted(r for k, e in cl.items() if k[0] == TXT and k[1] == kd for r in e[1])[:LOC_CAP]
                        feats.add("text.rare_pattern", "kind:" + kd, v["count"], rows,
                                  {"g": "text_kind", "kind": kd, "length": {str(max(v["length"])): 1},
                                   "words": {"1": 1}}, {"kind": kd})
                lens: Counter = Counter()
                for v in kinds.values():
                    lens.update(v["length"])
                typ = [a for a, c in lens.items() if not _rare(c, n_txt)] or list(lens)
                for a, c in lens.items():
                    if a > 2 * max(typ) and _rare(c, n_txt):
                        rows = sorted(r for k, e in cl.items() if k[0] == TXT and k[3] == a for r in e[1])[:LOC_CAP]
                        feats.add("text.length_outlier", a, c, rows,
                                  {"g": "text_kind", "kind": "sentence", "length": {str(a): 1},
                                   "words": {str(max(4, a // 6)): 1}}, {"length_up_to": a})
            for k, e in cl.items():
                if k[0] != TXT:
                    continue
                fl = k[2]
                if fl & MULTILINE:
                    feats.add("text.multiline", None, e[0], e[1], {"g": "base", "multiline": True})
                if fl & NONASCII:
                    feats.add("text.non_ascii", None, e[0], e[1], {"g": "base", "non_ascii": True})
                if fl & CONTROL:
                    feats.add("text.control_chars", None, e[0], e[1], {"g": "base", "control": True})
                if fl & FORMULA_LIKE:
                    feats.add("text.formula_like", None, e[0], e[1], {"g": "formula_like"})

    # ---- cross-family and cross-cutting features --------------------------------------------
    if dom is not None:
        dname = _FAMILY_NAME[dom]
        dom_storage = Counter()
        for k, e in cl.items():
            if k[0] == dom:
                dom_storage[k[6]] += e[0]
        main_storage = dom_storage.most_common(1)[0][0] if dom_storage else None
        for k, e in cl.items():
            f, sub, fl, a, b, _shape, st = k
            c, rows = e[0], e[1]
            if f in (MISSING, ERR):
                continue
            if fl & PADDED:
                side = "both" if fl & PADDED == PADDED else "leading" if fl & PAD_LEAD else "trailing"
                feats.add("text.padded", side, c, rows, {"g": "base", "pad": side}, {"side": side})
            if xlsx and f == dom and dom in (NUM, DATE) and main_storage == NUMBER and st in STRING_TYPES:
                feats.add(f"storage.{dname}_as_text", None, c, rows, {"g": "base", "as_text": True})
            if f == dom:
                continue
            cls = f"type.{_FAMILY_NAME[f]}_in_{dname}"
            if f == TXT:
                ft = feats.add(cls, sub, c, rows, None, {"kind": sub})
                g = ft["gen"] or {"g": "text_kind", "kind": sub, "length": {}, "words": {}}
                g["length"][str(a)] = g["length"].get(str(a), 0) + c
                g["words"][str(b)] = g["words"].get(str(b), 0) + c
                ft["gen"] = g
            elif f == NUM:
                ft = feats.add(cls, sub, c, rows, None, {"format": sub})
                g = ft["gen"] or {"g": "number", "fmt": sub, "int_digits": {}, "dec_digits": {}}
                g["int_digits"][str(a)] = g["int_digits"].get(str(a), 0) + c
                g["dec_digits"][str(b)] = g["dec_digits"].get(str(b), 0) + c
                ft["gen"] = g
            elif f == DATE:
                feats.add(cls, sub, c, rows, {"g": "date", "fmt": sub, "invalid": bool(fl & INVALID),
                                             "year_min": a or None, "year_max": a or None}, {"format": sub})
            else:
                feats.add(cls, sub, c, rows, {"g": "bool", "style": sub}, {"style": sub})
    if acc.formulas:
        feats.add("xlsx.formula_cell", None, acc.formulas, [], None,
                  {"note": "formulas are inventoried, never evaluated or copied"})

    # ---- type summary and base generator ---------------------------------------------------
    share = fam[dom] / n_values if dom is not None and n_values else 0.0
    if dom is not None and share < 0.6:
        logical = "mixed"
    mix = [(fam[f] / n_values, f) for f in fam if f == dom or fam[f] / n_values >= RARE_SHARE]
    if not mix:
        base_gen: dict = {"g": EMPTY}
    elif len(mix) == 1:
        base_gen = family_gens[mix[0][1]]
    else:
        base_gen = {"g": "mix", "of": [[round(w, 4), family_gens[f]] for w, f in sorted(mix, key=lambda x: -x[0])]}
    out.update(logical_type=logical, dominant_family=_FAMILY_NAME.get(dom), type_share=round(share, 4),
               base_gen=base_gen)

    # ---- distinct values / categories -------------------------------------------------------
    ds = acc.distinct_stats()
    out["distinct"] = ds
    if acc.vals is not None and dom == TXT and ds["n_distinct"] >= 1 and n_values >= 5 \
            and ds["n_distinct"] <= max(2, min(50, int(0.2 * n_values))):
        counts = sorted(acc.vals.values(), reverse=True)
        out["categorical"] = {"n_categories": len(counts),
                              "frequency_profile": [round(c / n_values, 4) for c in counts]}
        private["category_values"] = {v: c for v, c in sorted(acc.vals.items(), key=lambda kv: -kv[1])}
        n_rare_cat = sum(1 for c in counts if _rare(c, n_values))
        if n_rare_cat and len(counts) > 1:
            rows = []
            feats.add("category.rare_value", None, n_rare_cat, rows, {"g": "pool_rare"},
                      {"rare_categories": n_rare_cat})

    exceptions = []
    for (cls, dkey), f in feats.d.items():
        denom = acc.n if cls.split(".")[0] in ("missing", "xlsx") else max(1, n_values)
        exceptions.append({
            "class": cls, "detail": f["detail"], "count": f["count"],
            "share": round(f["count"] / denom, 6) if denom else 0.0,
            "common": f["count"] / denom >= RARE_SHARE if denom else False,
            "priority": PRIORITY[cls.split(".")[0]], "gen": f["gen"],
            "key": _detail_key(dkey),
            "_private": {"rows": f["rows"]},
        })
    exceptions.sort(key=lambda x: (x["priority"], x["class"], x["key"]))
    out["exceptions"] = exceptions
    out["_private"] = private
    return out


def _case_of(shape) -> str:
    if shape is None:
        return "unknown"
    classes = [item[0] for item in shape if item[0] in "AaCXx"]
    if not classes:
        return "none"
    if all(c in "AX" for c in classes):
        return "upper"
    if all(c in "ax" for c in classes):
        return "lower"
    if classes[0] == "C" or (classes[0] in "AX" and shape[[i[0] for i in shape].index(classes[0])][1] == 1):
        return "title"
    return "mixed"


def _detail_key(dkey) -> str:
    if dkey is None:
        return ""
    if isinstance(dkey, tuple):
        return shape_display(dkey)
    return str(dkey)


class TableAcc:
    def __init__(self, region: Region, fmt: str, markers: frozenset, date1904: bool, overflow_end: int | None):
        self.region = region
        self.csv = fmt == "csv"
        self.markers = markers
        self.date1904 = date1904
        self.overflow_end = overflow_end
        self.width = region.col_end - region.col_start
        self.cols: list[ColumnAcc] = [ColumnAcc(j, f"column_{j + 1}", markers, date1904) for j in range(self.width)]
        self.header_cells: list[str | None] | None = None
        self.preamble: list[list[dict]] = []
        self.n_rows = 0
        self.blank_inside = 0
        self.blank_rows: list[int] = []
        self.row_hashes = array("q")
        self.short: dict[int, list] = {}
        self.long: dict[tuple, list] = {}
        self.extra_classes: Counter = Counter()
        self.last_index = region.data_start - 1
        self.hidden_rows = 0

    def feed(self, row: Row) -> None:
        r = self.region
        idx = row.index
        if idx < r.data_start:
            if r.header_row is not None and idx == r.header_row:
                self.header_cells = [row.raw[i] if i < len(row.raw) else None for i in range(r.col_start, r.col_end)]
            else:
                self.preamble.append(_note_row(row, r.col_start, None))
            return
        if idx > self.last_index + 1:
            self.blank_inside += idx - self.last_index - 1
        self.last_index = idx
        raw = row.raw
        c0, c1 = r.col_start, r.col_end
        n = len(raw)
        cells = raw[c0:c1]
        end = self.overflow_end if self.overflow_end is not None else n
        extras = raw[c1:end] if n > c1 else []
        if not any(v is not None and v != "" and not v.isspace() for v in cells) and not any(
                v is not None and v != "" and not v.isspace() for v in extras):
            self.blank_inside += 1
            if len(self.blank_rows) < LOC_CAP:
                self.blank_rows.append(idx + 1)
            return
        self.n_rows += 1
        if row.hidden:
            self.hidden_rows += 1
        self.row_hashes.append(hash(tuple(cells)))
        if self.csv:
            if n < c1:
                ent = self.short.setdefault(c1 - max(n, c0), [0, []])
                ent[0] += 1
                if len(ent[1]) < LOC_CAP:
                    ent[1].append(idx + 1)
            elif extras and self.overflow_end is None:
                nonempty = any(v not in (None, "") for v in extras)
                ent = self.long.setdefault((len(extras), nonempty), [0, []])
                ent[0] += 1
                if len(ent[1]) < LOC_CAP:
                    ent[1].append(idx + 1)
                if nonempty:
                    for v in extras:
                        self.extra_classes[classify(v, TEXT, False, None, self.markers).family] += 1
        else:
            k = sum(1 for v in extras if v is not None and v != "" and not v.isspace())
            if k:
                ent = self.long.setdefault((k, True), [0, []])
                ent[0] += 1
                if len(ent[1]) < LOC_CAP:
                    ent[1].append(idx + 1)
        stypes, quoted, formats, formulas = row.stypes, row.quoted, row.formats, row.formulas
        cols = self.cols
        for j in range(self.width):
            i = c0 + j
            if i < n:
                cols[j].add(raw[i], stypes[i] if stypes is not None else TEXT,
                            bool(quoted) and i in quoted, formats.get(i) if formats else None, idx)
                if formulas and i in formulas:
                    cols[j].formulas += 1
            else:
                cols[j].add(None, TEXT, False, None, idx)

    def finalize(self, xlsx: bool) -> dict:
        r = self.region
        names = []
        header_feats = []
        if self.header_cells is not None:
            seen: Counter = Counter()
            for j, h in enumerate(self.header_cells):
                name = h if h is not None and h.strip() else None
                if name is None:
                    header_feats.append(("header.empty_name", j))
                    name = f"column_{j + 1}"
                elif name != name.strip():
                    header_feats.append(("header.padded_name", j))
                seen[name] += 1
                names.append(name)
            for j, nm in enumerate(names):
                if seen[nm] > 1:
                    header_feats.append(("header.duplicate_name", j))
        else:
            names = [f"column_{j + 1}" for j in range(self.width)]
        columns = []
        for j, acc in enumerate(self.cols):
            acc.name = names[j]
            col = finalize_column(acc, xlsx)
            col["id"] = f"c{j + 1}"
            columns.append(col)
        runs = _run_lengths(self.row_hashes)
        dup_groups = sum(1 for c in runs if c > 1)
        dup_extra = sum(c - 1 for c in runs if c > 1)
        row_ex = []

        def add(cls, key, count, rows, gen, detail):
            row_ex.append({"class": cls, "detail": detail, "count": count,
                           "share": round(count / max(1, self.n_rows), 6),
                           "common": count / max(1, self.n_rows) >= RARE_SHARE,
                           "priority": PRIORITY[cls.split(".")[0]], "gen": gen, "key": key,
                           "_private": {"rows": rows}})

        if dup_extra:
            add("row.duplicate", "", dup_extra, [], {"g": "duplicate_row"},
                {"duplicate_groups": dup_groups, "max_copies": max(runs)})
        if self.blank_inside:
            add("row.blank_inside_table", "", self.blank_inside, self.blank_rows, {"g": "blank_row"}, {})
        for delta, (c, rows) in sorted(self.short.items()):
            add("row.ragged_short", str(delta), c, rows, {"g": "ragged_short", "missing_fields": delta},
                {"missing_trailing_fields": delta})
        for (k, nonempty), (c, rows) in sorted(self.long.items()):
            add("row.ragged_long", f"{k}{'' if nonempty else ':empty'}", c, rows,
                {"g": "ragged_long", "extra_fields": k, "empty": not nonempty},
                {"extra_fields": k, "extra_fields_empty": not nonempty})
        for cls, j in header_feats:
            add(cls, f"c{j + 1}", 1, [], None, {"column": f"c{j + 1}"})
        return {
            "name": r.name, "sheet": r.sheet_name, "region": region_to_spec(r),
            "n_rows": self.n_rows, "n_columns": self.width, "header_present": self.header_cells is not None,
            "preamble": self.preamble, "hidden_rows": self.hidden_rows,
            "duplicate_rows": {"groups": dup_groups, "extra_rows": dup_extra},
            "columns": columns, "row_exceptions": row_ex,
        }


def _note_row(row: Row, c0: int, c1: int | None) -> list[dict]:
    """Shape-only description of an introductory or note row (never its text)."""
    out = []
    for i, v in enumerate(row.raw[c0:c1]):
        if v is None or v == "" or v.isspace():
            continue
        out.append({"col": i, "length": list(bucket(len(v.strip()))), "words": min(len(v.split()), 12),
                    "family": classify(v, row.stype(c0 + i), False, row.formats.get(c0 + i) if row.formats else None).family})
    return out


def _sensitivity_hint(col: dict) -> dict:
    name = col["name"].lower()
    kinds = (col.get("text") or {}).get("kinds", {})
    n_txt = sum(v["count"] for v in kinds.values()) or 1
    for kd in ("email", "phone", "ipv4", "uuid"):
        if kinds.get(kd, {}).get("count", 0) / n_txt >= 0.5:
            return {"class": "direct_identifier", "basis": f"values look like {kd}"}
    for cls, rx in _SENSITIVE_HINTS:
        if rx.search(name):
            return {"class": cls, "basis": "column name"}
    if col.get("key", {}).get("role") in ("unique", "reference", "repeating"):
        return {"class": "direct_identifier", "basis": "identifier-like key column"}
    if (col.get("text") or {}).get("structure") == "free" and col["logical_type"] == "text":
        return {"class": "free_text", "basis": "unstructured text"}
    return {"class": "unreviewed", "basis": "no indication found; needs human review"}


def _assign_keys(accs: list[TableAcc], tables: list[dict]) -> list[dict]:
    """Infer key roles and cross-table references. Proposals only; the contract asks for confirmation."""
    relationships = []
    uniques = []
    for acc, tab in zip(accs, tables):
        for j, col in enumerate(tab["columns"]):
            ds = col["distinct"]
            nv = col["n_values"]
            named = _id_named(col["name"])
            codeish = False
            if col["logical_type"] == "text" and col["text"]["structure"] in ("structured", "patterned"):
                top_kind = next(iter(col["text"]["kinds"]))
                codeish = top_kind in ("code", "alnum", "digits", "uuid") or (named and top_kind == "alpha")
            idlike = col["logical_type"] in ("integer", "digit_code") or codeish
            role, conf = "none", 0.0
            if nv >= 2 and idlike and "categorical" not in col:
                ratio = ds["n_distinct"] / nv
                if ratio == 1.0 and (named or j == 0 or col["logical_type"] != "integer" or nv >= 20):
                    role, conf = "unique", 0.9 if named else 0.6
                elif ratio >= 0.9 and ds["extra_occurrences"] and (named or j == 0):
                    role, conf = "unique", 0.6
                    col["exceptions"].append({
                        "class": "key.duplicate", "detail": {"repeated_values": ds["repeated_values"]},
                        "count": ds["extra_occurrences"], "share": round(ds["extra_occurrences"] / nv, 6),
                        "common": False, "priority": PRIORITY["key"], "gen": {"g": "duplicate_key"}, "key": "",
                        "_private": {"rows": []}})
                elif named and ratio < 0.9:
                    role, conf = "repeating", 0.7
            elif nv >= 2 and named and "categorical" in col and ds["extra_occurrences"]:
                role, conf = "repeating", 0.5
            col["key"] = {"role": role, "confidence": conf, "references": None}
            if role == "unique":
                uniques.append((acc, tab, j, col))
    for acc, tab in zip(accs, tables):
        for j, col in enumerate(tab["columns"]):
            if col["n_values"] < 2 or col["logical_type"] not in ("integer", "digit_code", "text"):
                continue
            if col["key"]["role"] == "unique" and len(tables) == 1:
                continue
            best = None
            for uacc, utab, uj, ucol in uniques:
                if utab is tab or ucol["logical_type"] != col["logical_type"]:
                    continue
                named = _id_named(col["name"]) or _share_token(col["name"], ucol["name"]) \
                    or _share_token(col["name"], utab["name"])
                if col["logical_type"] != "text" and not named:
                    continue
                if col["logical_type"] == "text" and col.get("text", {}).get("structure") == "free":
                    continue
                child = acc.cols[j].hash_counts()
                parent = uacc.cols[uj].hash_set()
                inside = sum(1 for h in child if h in parent)
                if len(child) < 2 or inside / len(child) < 0.8:
                    continue
                dangling_rows = sum(c for h, c in child.items() if h not in parent)
                cand = (inside / len(child), 1 if named else 0, utab["name"], ucol, len(child) - inside, dangling_rows)
                if best is None or cand[:2] > best[:2]:
                    best = cand
            if best is None or col["key"]["role"] == "unique" and best[0] < 1.0:
                continue
            containment, named, tname, ucol, dangling_vals, dangling_rows = best
            col["key"] = {"role": "reference", "confidence": round(0.5 + 0.3 * containment + 0.2 * named, 2),
                          "references": {"table": tname, "column": ucol["id"], "column_name": ucol["name"]}}
            col.pop("categorical", None)
            relationships.append({"from_table": tab["name"], "from_column": col["id"], "from_column_name": col["name"],
                                  "to_table": tname, "to_column": ucol["id"], "to_column_name": ucol["name"],
                                  "containment": round(containment, 4), "dangling_values": dangling_vals,
                                  "dangling_rows": dangling_rows})
            if dangling_rows:
                col["exceptions"].append({
                    "class": "key.dangling_reference", "detail": {"distinct_values": dangling_vals},
                    "count": dangling_rows, "share": round(dangling_rows / col["n_values"], 6), "common": False,
                    "priority": PRIORITY["key"], "gen": {"g": "dangling_reference"}, "key": "",
                    "_private": {"rows": []}})
    for tab in tables:
        for col in tab["columns"]:
            ds = col["distinct"]
            if col["key"]["role"] in ("repeating", "reference"):
                for label in ("1", "2", "3+"):
                    if ds["multiplicity"][label]:
                        col["exceptions"].append({
                            "class": "key.multiplicity", "detail": {"occurrences_per_value": label},
                            "count": ds["multiplicity"][label],
                            "share": round(ds["multiplicity"][label] / max(1, ds["n_distinct"]), 6),
                            "common": True, "priority": PRIORITY["key"],
                            "gen": {"g": "key_multiplicity", "times": label}, "key": label,
                            "_private": {"rows": []}})
            col["sensitivity_hint"] = _sensitivity_hint(col)
            col["exceptions"].sort(key=lambda x: (x["priority"], x["class"], x["key"]))
    return relationships


def _share_token(a: str, b: str) -> bool:
    ta = {t for t in re.split(r"[^a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", a).lower()) if len(t) > 2}
    tb = {t for t in re.split(r"[^a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", b).lower()) if len(t) > 2}
    ta -= {"id", "ids", "key", "code", "ref", "num", "number"}
    tb -= {"id", "ids", "key", "code", "ref", "num", "number"}
    return bool(ta & tb) or any(x.rstrip("s") == y.rstrip("s") for x in ta for y in tb)


def _file_exceptions(source) -> list[dict]:
    out = []

    def add(cls, count, detail, reproducible):
        out.append({"class": cls, "detail": detail, "count": count, "share": None, "common": False,
                    "priority": PRIORITY[cls.split(".")[0]], "gen": None, "key": "",
                    "reproduced": reproducible, "_private": {"rows": []}})

    info = source.info
    if source.format == "csv":
        enc = info["encoding"]
        if enc.get("undecodable_bytes"):
            add("file.undecodable_bytes", enc["undecodable_bytes"], {"encoding": enc["encoding"]}, False)
        if enc.get("nul_bytes"):
            add("file.nul_bytes", enc["nul_bytes"], {}, False)
        if enc.get("bom"):
            add("file.byte_order_mark", 1, {"bom": enc["bom"]}, True)
        if len(info.get("newlines") or {}) > 1:
            add("file.mixed_newlines", min(info["newlines"].values()), {"newlines": info["newlines"]}, False)
        if info.get("unterminated_quote"):
            add("file.unterminated_quote", info["unterminated_quote"], {}, False)
        if info.get("text_after_closing_quote"):
            add("file.text_after_closing_quote", info["text_after_closing_quote"], {}, False)
        if info.get("final_newline") is False:
            add("file.no_final_newline", 1, {}, True)
    else:
        inv = info["metadata_inventory"]
        totals = Counter()
        for s in source.sheets:
            totals.update({k: v for k, v in s.post.items() if isinstance(v, int)})
        for key, cls in (("merged_ranges", "workbook.merged_cells"), ("hidden_rows", "workbook.hidden_rows"),
                         ("hidden_columns", "workbook.hidden_columns"),
                         ("data_validations", "workbook.data_validations")):
            if totals.get(key):
                add(cls, totals[key], {}, False)
        if info["hidden_sheets"]:
            add("workbook.hidden_sheets", info["hidden_sheets"], {}, False)
        for key, cls in (("defined_names", "workbook.defined_names"), ("comment_parts", "workbook.comments"),
                         ("external_link_parts", "workbook.external_links"),
                         ("pivot_table_parts", "workbook.pivot_tables"), ("drawing_parts", "workbook.drawings"),
                         ("embedded_media_parts", "workbook.embedded_objects"),
                         ("custom_xml_parts", "workbook.custom_xml")):
            if inv.get(key):
                add(cls, inv[key], {}, False)
        for key, cls in (("has_macros", "workbook.macros"), ("has_data_connections", "workbook.data_connections"),
                         ("author_recorded", "workbook.author_metadata"),
                         ("has_custom_properties", "workbook.custom_properties")):
            if inv.get(key):
                add(cls, 1, {}, False)
    return out


def build_profile(path: str, recipe: ParseRecipe | None = None) -> dict:
    """Read ``path`` and return the private profile."""
    recipe = recipe or ParseRecipe()
    source = recipe.open(path)
    regions, detected = resolve_regions(recipe, source)
    markers = DEFAULT_MARKERS | frozenset(m.casefold() for m in recipe.extra_markers)
    date1904 = bool(source.info.get("date1904"))
    accs: list[TableAcc] = []
    notes: list[dict] = []
    for sh in source.sheets:
        regs = [r for r in regions if r.sheet == sh.index and r.include]
        if not regs:
            continue
        sheet_accs = []
        note_regs = []
        for r in regs:
            if r.kind != "table":
                note_regs.append((r, {"name": r.name, "sheet": r.sheet_name, "region": region_to_spec(r), "rows": []}))
                continue
            right = [o.col_start for o in regs if o is not r and o.col_start >= r.col_end
                     and o.top <= r.bottom and r.top <= o.bottom]
            sheet_accs.append(TableAcc(r, source.format, markers, date1904, min(right) if right else None))
        for row in source.rows(sh.index):
            idx = row.index
            for acc in sheet_accs:
                rg = acc.region
                if rg.top <= idx <= rg.bottom:
                    acc.feed(row)
            for r, note in note_regs:
                if r.top <= idx <= r.bottom:
                    note["rows"].append(_note_row(row, r.col_start, r.col_end))
        accs.extend(sheet_accs)
        notes.extend(n for _r, n in note_regs)
    xlsx = source.format == "xlsx"
    tables = [acc.finalize(xlsx) for acc in accs]
    relationships = _assign_keys(accs, tables)
    ambiguities = []
    for r in regions:
        if r.include and r.kind == "table" and r.confidence < 0.75:
            ambiguities.append({"scope": r.name, "message": "table boundaries or header detected with low "
                                "confidence: " + "; ".join(r.notes), "confidence": r.confidence})
    if source.format == "csv":
        for key, label in (("encoding", "text encoding"), ("delimiter", "field delimiter")):
            conf = source.info[key].get("confidence", 1.0)
            if conf < 0.75:
                ambiguities.append({"scope": "file", "message": f"{label} detected with low confidence",
                                    "confidence": conf})
    for tab in tables:
        for col in tab["columns"]:
            for msg in col.pop("ambiguities"):
                ambiguities.append({"scope": f"{tab['name']}.{col['id']}", "message": msg, "confidence": 0.5})
            if col["logical_type"] == "mixed":
                ambiguities.append({"scope": f"{tab['name']}.{col['id']}",
                                    "message": "no value type reaches 60 % of the column; treated as mixed",
                                    "confidence": col["type_share"]})
    profile = {
        "profile_version": PROFILE_VERSION, "tool_version": __version__, "view": "private",
        "source": dict(source.info),
        "sheets": [{"name": s.name, "state": s.state, **({"inventory": s.post} if s.post else {})} for s in source.sheets],
        "regions": [region_to_spec(r) for r in regions],
        "detected_candidates": [region_to_spec(r) for r in detected] if detected is not regions else None,
        "recipe": recipe.to_dict() | {"tables": [region_to_spec(r) for r in regions]},
        "tables": tables, "notes": notes, "relationships": relationships,
        "file_exceptions": _file_exceptions(source), "ambiguities": ambiguities,
    }
    _assign_ids(profile)
    return profile


def _assign_ids(profile: dict) -> None:
    for tab in profile["tables"]:
        for col in tab["columns"]:
            for ex in col["exceptions"]:
                ex["id"] = "/".join(x for x in (tab["name"], col["id"], ex["class"], ex["key"]) if x)
                ex["table"], ex["column"], ex["column_name"] = tab["name"], col["id"], col["name"]
        for ex in tab["row_exceptions"]:
            ex["id"] = "/".join(x for x in (tab["name"], ex["class"], ex["key"]) if x)
            ex["table"], ex["column"], ex["column_name"] = tab["name"], None, None
    for ex in profile["file_exceptions"]:
        ex["id"] = "file/" + ex["class"]
        ex["table"], ex["column"], ex["column_name"] = None, None, None


def iter_exceptions(profile: dict):
    """Yield every Exception Catalogue entry (file, table and column level)."""
    yield from profile["file_exceptions"]
    for tab in profile["tables"]:
        yield from tab["row_exceptions"]
        for col in tab["columns"]:
            yield from col["exceptions"]


# -- shareable view ------------------------------------------------------------------------------
def _strip_private(node):
    if isinstance(node, dict):
        return {k: _strip_private(v) for k, v in node.items() if k != "_private"}
    if isinstance(node, list):
        return [_strip_private(v) for v in node]
    return node


def _text_gen(col: dict, policy: PrivacyPolicy) -> dict:
    """Build the text generator of a column from its private layouts under ``policy``."""
    text = col["text"]
    priv = col.get("_private", {})
    n_txt = sum(v["count"] for v in text["kinds"].values()) or 1
    patterns: list = []
    top_kind, top = next(iter(text["kinds"].items()))
    semantic = top_kind in ("email", "url", "uuid", "ipv4", "phone") and top["count"] / n_txt >= 0.9
    if text["structure"] in ("structured", "patterned") and not semantic:
        general: Counter = Counter()
        exact_ok = []
        for shape, c in priv.get("exact_shapes", []):
            tshape = tuple(tuple(x) for x in shape)
            if text["structure"] == "structured" and c >= policy.shape_exact_min_count and not _rare(c, n_txt) \
                    and len(exact_ok) < 40:
                exact_ok.append((tshape, c))
            else:
                general[generalize_shape(tshape)] += c
        for tshape, c in exact_ok:
            patterns.append([c, {"g": "text_shape", "shape": [list(x) for x in tshape]}])
        for gshape, c in general.most_common(40):
            if c >= policy.shape_exact_min_count and not _rare(c, n_txt):
                patterns.append([c, {"g": "text_gshape", "shape": [list(x) for x in gshape]}])
    if not patterns:
        for kind, v in text["kinds"].items():
            if v["count"] / n_txt >= RARE_SHARE or len(text["kinds"]) == 1:
                patterns.append([v["count"], {"g": "text_kind", "kind": kind, "length": v["length"],
                                              "words": v["words"], "case": v.get("case", {})}])
    if not patterns:
        kind, v = next(iter(text["kinds"].items()))
        patterns.append([v["count"], {"g": "text_kind", "kind": kind, "length": v["length"], "words": v["words"],
                                      "case": v.get("case", {})}])
    total = sum(p[0] for p in patterns)
    gen = patterns[0][1] if len(patterns) == 1 else {"g": "mix", "of": [[round(c / total, 4), g] for c, g in patterns]}
    return gen


def _fill_text(gen: dict, text_gen: dict) -> dict:
    if gen.get("g") == "text":
        return text_gen
    if gen.get("g") == "mix":
        return {"g": "mix", "of": [[w, _fill_text(g, text_gen)] for w, g in gen["of"]]}
    return gen


def to_shareable(profile: dict, policy: PrivacyPolicy) -> dict:
    """Return the shareable view: no row numbers, no category values, rare layouts generalised."""
    out = copy.deepcopy(profile)
    k = policy.small_count_threshold
    for tab in out["tables"]:
        for col in tab["columns"]:
            _safe_formats(col)
            if "text" in col:
                tg = _text_gen(col, policy)
                col["base_gen"] = _fill_text(col["base_gen"], tg)
            if "categorical" in col:
                cat = col["categorical"]
                col["base_gen"] = {"g": "pool", "size": cat["n_categories"],
                                   "weights": cat["frequency_profile"][:200], "of": col["base_gen"]}
            for sect in ("date",):
                d = col.get(sect)
                if d and d.get("year_min") is not None and policy.year_rounding > 1:
                    r = policy.year_rounding
                    d["year_min"] = d["year_min"] - d["year_min"] % r
                    d["year_max"] = d["year_max"] + (-d["year_max"] % r)
            _round_years(col["base_gen"], policy.year_rounding)
            for ex in col["exceptions"]:
                if ex.get("gen"):
                    _round_years(ex["gen"], policy.year_rounding)
            if k:
                _mask_column(col, k)
        if k:
            for key in ("groups", "extra_rows"):
                tab["duplicate_rows"][key] = _mask(tab["duplicate_rows"][key], k)
    out = _strip_private(out)
    out["view"] = "shareable"
    out["policy"] = {"id": policy.id, "version": policy.version}
    for ex in iter_exceptions(out):
        c = ex["count"]
        if k and c is not None and c < k:
            ex["count_display"] = f"<{k}"
            ex["count"] = None
            ex["share"] = None
        else:
            ex["count_display"] = str(c)
    return out


def _safe_formats(col: dict) -> None:
    """Reduce every spreadsheet number format of a column to its layout codes (no literal text)."""
    hist: dict = {}
    for code, n in (col.get("number_formats") or {}).items():
        safe = safe_number_format(code) or "General"
        hist[safe] = hist.get(safe, 0) + n
    if "number_formats" in col:
        col["number_formats"] = dict(sorted(hist.items(), key=lambda kv: -kv[1]))

    def walk(node):
        if isinstance(node, dict):
            for key, v in node.items():
                if key == "number_format" and isinstance(v, str):
                    node[key] = safe_number_format(v)
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(col.get("base_gen"))
    for ex in col.get("exceptions", []):
        walk(ex.get("gen"))


def _mask(n, k: int):
    return f"<{k}" if isinstance(n, int) and not isinstance(n, bool) and 0 < n < k else n


def _mask_hist(d: dict, k: int) -> dict:
    return {key: _mask(v, k) for key, v in d.items()}


def _prune_gen(gen, k: int) -> None:
    """Drop histogram entries backed by fewer than ``k`` source values from a generator."""
    if not isinstance(gen, dict):
        return
    for key in ("int_digits", "dec_digits", "length", "words", "case"):
        h = gen.get(key)
        if isinstance(h, dict) and h:
            kept = {a: c for a, c in h.items() if c >= k}
            gen[key] = kept or {max(h, key=lambda a: h[a]): k}
    if gen.get("g") == "mix":
        for item in gen["of"]:
            _prune_gen(item[1], k)
    elif gen.get("g") == "pool":
        _prune_gen(gen.get("of"), k)


def _mask_column(col: dict, k: int) -> None:
    """Hide every count below ``k`` in a column's shareable statistics (policy small-count rule)."""
    _prune_gen(col["base_gen"], k)
    for key in ("missing", "markers", "families", "storage", "number_formats"):
        if isinstance(col.get(key), dict):
            col[key] = _mask_hist(col[key], k)
    for key in ("n_missing", "error_values", "formula_cells"):
        col[key] = _mask(col.get(key), k)
    num = col.get("number")
    if num:
        for key in ("formats", "int_digits", "dec_digits"):
            num[key] = _mask_hist(num[key], k)
        for key in ("negative", "zero", "leading_zero", "explicit_plus"):
            num[key] = _mask(num[key], k)
    date = col.get("date")
    if date:
        date["formats"] = _mask_hist(date["formats"], k)
        date["invalid"] = _mask(date["invalid"], k)
    boolean = col.get("boolean")
    if boolean:
        boolean["styles"] = _mask_hist(boolean["styles"], k)
        boolean["true"], boolean["false"] = _mask(boolean["true"], k), _mask(boolean["false"], k)
    text = col.get("text")
    if text:
        for v in text["kinds"].values():
            v["count"] = _mask(v["count"], k)
            for key in ("length", "words", "case"):
                if isinstance(v.get(key), dict):
                    v[key] = _mask_hist(v[key], k)
    dist = col.get("distinct")
    if dist:
        dist["multiplicity"] = _mask_hist(dist["multiplicity"], k)
        for key in ("repeated_values", "extra_occurrences"):
            dist[key] = _mask(dist[key], k)
    cat = col.get("categorical")
    if cat:
        floor = round(k / max(1, col["n_values"]), 4) if isinstance(col.get("n_values"), int) else 0.0
        cat["frequency_profile"] = [max(f, floor) for f in cat["frequency_profile"]]


def _round_years(gen: dict, r: int) -> None:
    if not isinstance(gen, dict):
        return
    if gen.get("g") == "date" and gen.get("year_min") is not None and r > 1:
        gen["year_min"] = gen["year_min"] - gen["year_min"] % r
        gen["year_max"] = gen["year_max"] + (-gen["year_max"] % r)
    for item in gen.get("of", []) if gen.get("g") in ("mix",) else []:
        _round_years(item[1], r)
    if gen.get("g") == "pool":
        _round_years(gen["of"], r)


__all__ = ["build_profile", "to_shareable", "iter_exceptions", "AMBIG", "QUOTED_EMPTY", "EMPTY_STRING"]
