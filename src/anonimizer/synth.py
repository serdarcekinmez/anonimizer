"""Mode B generator: exception-driven synthetic test data from a Dataset Contract.

Information-flow rule (enforced by an architecture test): this module imports nothing that
can read source data. Its only inputs are the contract, the requested row counts and a seed.
Every value is built from pattern classes; no source value is available here to copy.
"""

from __future__ import annotations

import calendar
import hashlib
import math
import random
from typing import NamedTuple

from .patterns import BOOL_STYLES, bucket

GENERATOR_VERSION = 1
PACK_STEPS = (1, 2, 3, 4, 6, 8)
_CONS = "bcdfghjklmnprstvz"
_VOW = "aeiou"
_MON_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_MON_FULL = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]
_LOREM = ("lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore et "
          "dolore magna aliqua enim minim veniam quis nostrud exercitation ullamco laboris nisi aliquip commodo "
          "consequat").split()


class SynthError(ValueError):
    pass


class OutCell(NamedTuple):
    text: str | None  # None: the cell does not exist
    kind: str = "s"  # s text, n number, d date/time (ISO text), b boolean, e error, "" empty
    quoted: bool = False
    fmt: str | None = None


EMPTY_CELL = OutCell("", "")


class Rng:
    """Small deterministic generator. Only uses primitives that are stable across Python versions."""

    def __init__(self, *parts):
        digest = hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).digest()
        self._r = random.Random(int.from_bytes(digest[:16], "big"))

    def below(self, n: int) -> int:
        if n <= 1:
            return 0
        k = n.bit_length()
        while True:
            v = self._r.getrandbits(k)
            if v < n:
                return v

    def between(self, lo: int, hi: int) -> int:
        return lo + self.below(hi - lo + 1) if hi > lo else lo

    def unit(self) -> float:
        return self._r.getrandbits(53) / (1 << 53)

    def chance(self, p: float) -> bool:
        return p > 0 and self.unit() < p

    def choice(self, seq):
        return seq[self.below(len(seq))]

    def weighted(self, weights) -> int:
        total = sum(weights)
        if total <= 0:
            return self.below(len(weights))
        x = self.unit() * total
        acc = 0.0
        for i, w in enumerate(weights):
            acc += w
            if x < acc:
                return i
        return len(weights) - 1

    def shuffle(self, items: list) -> None:
        for i in range(len(items) - 1, 0, -1):
            j = self.below(i + 1)
            items[i], items[j] = items[j], items[i]


# -- primitive value builders ---------------------------------------------------------------------
def _digits(rng: Rng, n: int, first_nonzero: bool = True) -> str:
    if n <= 0:
        return ""
    s = [str(rng.below(10)) for _ in range(n)]
    if first_nonzero and s[0] == "0":
        s[0] = str(1 + rng.below(9))
    return "".join(s)


def _word(rng: Rng, n: int, case: str = "lower") -> str:
    start = rng.below(2)
    chars = [(_CONS if (i + start) % 2 == 0 else _VOW)[rng.below(len(_CONS if (i + start) % 2 == 0 else _VOW))]
             for i in range(max(0, n))]
    w = "".join(chars)
    if case == "upper":
        return w.upper()
    if case == "cap":
        return w[:1].upper() + w[1:]
    return w


def _hist_pick(hist, rng: Rng, default: int) -> int:
    if not hist:
        return default
    keys = sorted(hist, key=lambda k: int(k))
    return int(keys[rng.weighted([hist[k] or 1 for k in keys])])


def _group(ip: str, sep: str) -> str:
    out = []
    while len(ip) > 3:
        out.append(ip[-3:])
        ip = ip[:-3]
    out.append(ip)
    return sep.join(reversed(out))


def _shape_text(shape, rng: Rng) -> str:
    parts = []
    for item in shape:
        cls = item[0]
        n = item[1] if len(item) == 2 else rng.between(item[1], item[2])
        if cls == "A":
            parts.append(_word(rng, n, "upper"))
        elif cls == "a":
            parts.append(_word(rng, n))
        elif cls == "C":
            parts.append(_word(rng, max(2, n), "cap"))
        elif cls == "9":
            parts.append(_digits(rng, n, False))
        elif cls == "X":
            parts.append("".join(rng.choice("ÉÈÀÇÖÜÑ") for _ in range(n)))
        elif cls == "x":
            parts.append("".join(rng.choice("éèàçöüñ") for _ in range(n)))
        elif cls == "S":
            parts.append("".join(rng.choice("°§€") for _ in range(n)))
        else:
            parts.append(cls * n)
    return "".join(parts)


def _kind_text(g: dict, rng: Rng) -> str:
    text = _kind_text_raw(g, rng)
    cases = {k: v for k, v in (g.get("case") or {}).items() if k in ("lower", "upper", "title")}
    if cases and g.get("kind") in ("alpha", "words", "phrase", "sentence", "alnum", "code"):
        keys = sorted(cases)
        case = keys[rng.weighted([cases[k] for k in keys])]
        if case == "upper":
            return text.upper()
        if case == "title":
            return " ".join(w[:1].upper() + w[1:] for w in text.split(" "))
        return text.lower() if g.get("kind") in ("alpha", "words", "sentence") else text
    return text


def _kind_text_raw(g: dict, rng: Rng) -> str:
    kind = g.get("kind", "alpha")
    hi = _hist_pick(g.get("length"), rng, 8)
    lo = bucket(hi)[0]
    n = rng.between(lo, max(lo, hi))
    if kind == "email":
        return f"{_word(rng, rng.between(4, 7))}.{_word(rng, rng.between(4, 8))}@example.{rng.choice(['com', 'org', 'net'])}"
    if kind == "url":
        return f"https://www.example.{rng.choice(['com', 'org', 'net'])}/{_word(rng, rng.between(4, 9))}"
    if kind == "uuid":
        h = "".join(rng.choice("0123456789abcdef") for _ in range(32))
        return f"{h[:8]}-{h[8:12]}-4{h[13:16]}-a{h[17:20]}-{h[20:]}"
    if kind == "ipv4":
        return f"{rng.choice(['192.0.2', '198.51.100', '203.0.113'])}.{rng.between(1, 254)}"
    if kind == "phone":
        return f"+00 555 01{_digits(rng, 2, False)} {_digits(rng, 4, False)}"
    if kind == "digits":
        return _digits(rng, n, False)
    if kind == "alnum":
        k = max(1, n // 2)
        return _word(rng, k, "upper") + _digits(rng, max(1, n - k), False)
    if kind == "code":
        k = max(1, (n - 1) // 2)
        return _word(rng, k, "upper") + "-" + _digits(rng, max(1, n - k - 1), False)
    if kind == "symbols":
        return "".join(rng.choice("#*_~") for _ in range(n))
    if kind in ("words", "phrase", "sentence"):
        w = max(2, _hist_pick(g.get("words"), rng, 2 if kind != "sentence" else 5))
        avg = max(2, (n - (w - 1)) // w)
        words = [_word(rng, rng.between(max(2, avg - 2), avg + 2)) for _ in range(w)]
        words[0] = words[0].capitalize()
        text = " ".join(words)
        return text + (" " + _digits(rng, 2, False) if kind == "phrase" else "")
    return _word(rng, max(1, n))


class _Col:
    def __init__(self, spec: dict, xlsx: bool):
        self.spec = spec
        self.id = spec["id"]
        self.base = spec["base_gen"]
        self.xlsx = xlsx
        self.numeric_storage = xlsx and bool(spec.get("numeric_storage"))
        self.role = spec["key"]["role"]
        self.used: set[str] = set()
        self.pools: dict[int, list[OutCell]] = {}
        self.keypool: list[OutCell] = []
        self.parent_values: list[OutCell] | None = None
        self.reserved: set[str] = set()
        self.bump = 0
        self.values: list[OutCell] = []  # typical, non-missing values in generation order
        self.missing = [(m["rate"], m["gen"]) for m in spec.get("missing", []) if m.get("rate", 0) >= 0.01]


class _TableGen:
    def __init__(self, tab: dict, fmt: str, seed, parents: dict):
        self.tab = tab
        self.xlsx = fmt == "xlsx"
        self.rng = Rng("anonimizer", GENERATOR_VERSION, seed, tab["name"])
        self.cols = [_Col(c, self.xlsx) for c in tab["columns"] if c["keep"]]
        self.by_id = {c.id: c for c in self.cols}
        for c in self.cols:
            ref = c.spec["key"].get("references")
            if c.role == "reference" and ref:
                c.parent_values = parents.get((ref["table"], ref["column"]))

    # ---- value generation ---------------------------------------------------------------
    def value(self, g: dict, col: _Col, mods: dict | None = None) -> OutCell:
        rng = self.rng
        mods = mods or {}
        kind = g["g"]
        if kind == "base":
            m = {k: v for k, v in g.items() if k != "g"}
            return self.value(self._base_for(col.base, m), col, m)
        if kind == "mix":
            return self.value(g["of"][rng.weighted([w for w, _ in g["of"]])][1], col, mods)
        if kind == "pool":
            if any(k in mods for k in ("multiline", "non_ascii", "control", "pad")):
                return self.value(g["of"], col, mods)
            pool = self._pool(col, g)
            weights = list(g.get("weights") or [])
            weights = (weights + [min(weights or [1.0])] * len(pool))[: len(pool)]
            return pool[rng.weighted(weights)]
        if kind == "pool_rare":
            base = col.base
            if base.get("g") == "pool":
                return self._pool(col, base)[-1]
            if base.get("g") == "category" and base.get("other"):
                return self._pool(col, base["other"])[-1]
            return self.value(base, col, mods)
        if kind == "category":
            other = g.get("other")
            weights = list(g["weights"]) + ([other["weight"]] if other else [])
            i = rng.weighted(weights)
            if i < len(g["values"]):
                return self._finish(g["values"][i], "s", mods)
            pool = self._pool(col, other)
            return pool[rng.below(len(pool))]
        if kind == "number":
            return self._number(g, col, mods)
        if kind == "date":
            return self._date(g, col, mods)
        if kind == "bool":
            style, _, case = g["style"].partition(":")
            truth = rng.chance(g.get("p_true", 0.5))
            if style == "xlsx_bool":
                return OutCell("1" if truth else "0", "b") if self.xlsx else OutCell("TRUE" if truth else "FALSE")
            word = BOOL_STYLES[style][0 if truth else 1]
            word = word.upper() if case == "upper" else word.capitalize() if case == "title" else word
            return self._finish(word, "s", mods)
        if kind == "text_shape" or kind == "text_gshape":
            return self._finish(self._text_mods(_shape_text(g["shape"], rng), mods), "s", mods)
        if kind == "text_kind" or kind == "text":
            return self._finish(self._text_mods(_kind_text(g, rng), mods), "s", mods)
        if kind == "literal":
            return OutCell(g["value"])
        if kind == "error":
            return OutCell(g["code"], "e" if self.xlsx else "s")
        if kind == "formula_like":
            return OutCell("=1+1")
        if kind == "whitespace":
            return OutCell(" " * max(1, int(g.get("n", 1))))
        if kind == "quoted_empty":
            return OutCell("", "s", True)
        if kind == "empty_string":
            return OutCell("", "s")
        if kind == "absent":
            return OutCell(None, "")
        return EMPTY_CELL

    def _base_for(self, base: dict, mods: dict) -> dict:
        """Pick the component of the column's generator that the modifiers apply to."""
        numeric = any(k in mods for k in ("neg", "zero", "leading_zero", "plus", "int_digits", "dec_digits"))
        texty = any(k in mods for k in ("multiline", "non_ascii", "control"))
        g = base
        while g.get("g") in ("pool", "mix", "category"):
            if g["g"] == "pool":
                g = g["of"]
            elif g["g"] == "category":
                g = g["other"]["of"] if g.get("other") else {"g": "text_kind", "kind": "alpha", "length": {"8": 1}}
            else:
                want = [x for _w, x in g["of"] if (numeric and x.get("g") == "number")
                        or (texty and x.get("g", "").startswith("text"))]
                g = want[0] if want else g["of"][0][1]
        if numeric and g.get("g") != "number":
            return {"g": "number", "fmt": "int", "int_digits": {"3": 1}}
        if texty and not g.get("g", "").startswith("text"):
            return {"g": "text_kind", "kind": "words", "length": {"16": 1}, "words": {"2": 1}}
        return g

    def _pool(self, col: _Col, g: dict) -> list[OutCell]:
        key = id(g)
        pool = col.pools.get(key)
        if pool is None:
            pool, seen = [], set()
            size = max(1, min(int(g.get("size", 1)), 500))
            for _ in range(size):
                for _try in range(30):
                    v = self.value(g["of"], col)
                    if v.text not in seen:
                        break
                else:
                    v = v._replace(text=(v.text or "") + str(len(pool)), kind="s")
                seen.add(v.text)
                pool.append(v)
            col.pools[key] = pool
        return pool

    def _text_mods(self, text: str, mods: dict) -> str:
        if mods.get("multiline"):
            text = text.replace(" ", "\n", 1) if " " in text else text + "\n" + _word(self.rng, 4)
        if mods.get("non_ascii"):
            text = (text[:1] + "é" + text[2:]) if len(text) > 2 else text + "é"
        if mods.get("control") and not self.xlsx:
            text += "\x1f"
        return text

    def _finish(self, text: str, kind: str, mods: dict, fmt: str | None = None) -> OutCell:
        pad = mods.get("pad")
        if pad:
            text = (" " if pad in ("leading", "both") else "") + text + (" " if pad in ("trailing", "both") else "")
            return OutCell(text, "s")
        if mods.get("as_text"):
            return OutCell(text, "s")
        return OutCell(text, kind, False, fmt)

    def _number(self, g: dict, col: _Col, mods: dict) -> OutCell:
        rng = self.rng
        base, _, template = g.get("fmt", "int").partition("|")
        template = template or "{n}"
        idig = int(mods["int_digits"]) if "int_digits" in mods else _hist_pick(g.get("int_digits"), rng, 2)
        ddig = int(mods["dec_digits"]) if "dec_digits" in mods else _hist_pick(g.get("dec_digits"), rng, 0)
        idig = max(1, idig + col.bump) if col.role == "unique" else max(1, idig)
        if base.startswith("thou") or base == "comma_ambiguous":
            idig = max(idig, 4)
        if "dec" not in base and base != "sci":
            ddig = 0
        elif mods.get("_scenario") and ddig == 0 and "int_digits" not in mods:
            ddig = max((int(k) for k in (g.get("dec_digits") or {})), default=2) or 2
        lead = bool(g.get("leading_zeros"))
        zero = bool(mods.get("zero")) or (not mods.get("_scenario") and rng.chance(g.get("p_zero", 0.0)))
        if zero:
            ip, dp = "0", "0" * ddig
        else:
            ip = _digits(rng, idig, first_nonzero=not lead)
            dp = _digits(rng, ddig, False)
            if ddig and not dp.strip("0") and not ip.strip("0"):
                dp = dp[:-1] + "5"
            if mods.get("leading_zero"):
                ip = "0" + ip
        neg = bool(mods.get("neg")) or (not zero and not mods.get("_scenario") and rng.chance(g.get("p_neg", 0.0)))
        if base == "sci":
            body = f"{ip[:1]}.{_digits(rng, 2, False)}E+{rng.between(2, 12):02d}"
        else:
            sep = "," if base in ("thou_comma", "thou_comma_dec_dot", "comma_ambiguous") else \
                "." if base in ("thou_dot", "thou_dot_dec_comma") else " " if base.startswith("thou_space") else ""
            body = _group(ip, sep) if sep else ip
            if ddig:
                body += ("," if base.endswith("dec_comma") else ".") + dp
        plain = base in ("int", "dec_dot", "sci") and template == "{n}"
        if col.numeric_storage and plain and not mods.get("as_text") and not mods.get("pad") \
                and not mods.get("leading_zero") and not lead and not mods.get("plus"):
            return OutCell(("-" if neg else "") + body, "n", False, col.spec.get("number_format"))
        sign = "-" if neg and "(" not in template else "+" if mods.get("plus") else ""
        return self._finish(template.replace("{n}", sign + body), "s", mods)

    def _date(self, g: dict, col: _Col, mods: dict) -> OutCell:
        rng = self.rng
        fmt = g["fmt"]
        y0 = g.get("year_min") or 2015
        y1 = max(y0, g.get("year_max") or 2024)
        y, m = rng.between(y0, y1), rng.between(1, 12)
        d = rng.between(1, calendar.monthrange(y, m)[1])
        hh, mi, ss = rng.below(24), rng.below(60), rng.below(60)
        invalid = bool(g.get("invalid") or mods.get("invalid"))
        if fmt.startswith("excel_"):
            iso = f"{y:04d}-{m:02d}-{d:02d}"
            if fmt == "excel_datetime":
                iso += f"T{hh:02d}:{mi:02d}:{ss:02d}"
            elif fmt == "excel_time":
                iso = f"{hh:02d}:{mi:02d}:{ss:02d}"
            if self.xlsx and not mods.get("as_text") and not mods.get("pad"):
                return OutCell(iso, "d", False, g.get("number_format"))
            return self._finish(iso, "s", mods)
        first_x = True
        if invalid:
            m, d = rng.choice([(2, 30), (2, 31), (4, 31), (6, 31), (9, 31), (11, 31)])
            if fmt.startswith("X"):
                m = rng.between(13, 19)
        elif fmt.startswith("X"):
            d = rng.between(1, 12)
        elif fmt.startswith("M/D/") or (fmt.startswith("D/M/") and mods.get("_scenario")):
            d = rng.between(13, 28)
        pad = g.get("padding", "padded") != "unpadded" or fmt.startswith("Y-")
        out = []
        for ch in fmt:
            if ch == "Y":
                out.append(f"{y:04d}")
            elif ch == "y":
                out.append(f"{y % 100:02d}")
            elif ch == "M":
                out.append(f"{m:02d}" if pad else str(m))
            elif ch == "D":
                out.append(f"{d:02d}" if pad else str(d))
            elif ch == "X":
                v = d if first_x else m
                first_x = False
                out.append(f"{v:02d}" if pad else str(v))
            elif ch == "b" or ch == "e":
                out.append(_MON_ABBR[(m - 1) % 12])
            elif ch == "B":
                out.append(_MON_FULL[(m - 1) % 12])
            elif ch == "h":
                out.append(f"{hh:02d}")
            elif ch == "m":
                out.append(f"{mi:02d}")
            elif ch == "s":
                out.append(f"{ss:02d}")
            elif ch == "f":
                out.append(_digits(rng, 3, False))
            elif ch == "z":
                out.append("+01:00")
            else:
                out.append(ch)
        return self._finish("".join(out), "s", mods)

    # ---- typical cells --------------------------------------------------------------------
    def typical(self, col: _Col, allow_missing: bool = True) -> OutCell:
        rng = self.rng
        if allow_missing and col.missing:
            u = rng.unit()
            acc = 0.0
            for rate, gen in col.missing:
                acc += rate
                if u < acc:
                    return self.value(gen, col)
        if col.role == "reference" and col.parent_values:
            pool = [v for v in col.parent_values if v.text not in col.reserved] or col.parent_values
            v = rng.choice(pool)
        elif col.role == "repeating" and col.keypool:
            v = rng.choice(col.keypool)
        elif col.role == "unique":
            v = self.fresh(col)
        else:
            v = self.value(col.base, col)
        if v.kind != "" and v.text:
            col.values.append(v)
        return v

    def fresh(self, col: _Col, avoid: set | None = None) -> OutCell:
        """A value not used so far in this column (and not in ``avoid``)."""
        for attempt in range(200):
            v = self.value(col.base, col)
            if v.text and v.text not in col.used and not (avoid and v.text in avoid):
                col.used.add(v.text)
                return v
            if attempt % 25 == 24:
                col.bump += 1
        v = OutCell(f"{v.text or 'k'}{len(col.used) + 1}", "s")
        col.used.add(v.text)
        return v


# -- planning -------------------------------------------------------------------------------------
_ROW_LEVEL = {"duplicate_row", "blank_row", "ragged_short", "ragged_long"}


def _units(sc: dict) -> int:
    g = (sc.get("gen") or {}).get("g")
    if g == "key_multiplicity":
        return {"1": 1, "2": 2}.get(sc["gen"].get("times"), 3)
    return 1


def _pack(scenarios: list[dict], cap: float, max_per_row: float):
    """Greedy cover. Returns (rows, covered ids, uncovered scenarios, blank row count)."""
    rows: list[dict] = []  # {"slots": {col: scenario}, "row": scenario|None}
    covered, uncovered = [], []
    blanks = 0
    for sc in scenarios:
        g = sc["gen"]["g"]
        if g == "blank_row":
            blanks += 1
            covered.append(sc["id"])
            continue
        if g in _ROW_LEVEL:
            if len(rows) < cap:
                rows.append({"slots": {}, "row": sc})
                covered.append(sc["id"])
            else:
                uncovered.append(sc)
            continue
        need = _units(sc)
        col = sc["column"]
        chosen = []
        if max_per_row > 1:
            for r in rows:
                if len(chosen) == need:
                    break
                if r["row"] is None and col not in r["slots"] and 0 < len(r["slots"]) < max_per_row:
                    chosen.append(r)
        new = need - len(chosen)
        if len(rows) + new > cap:
            uncovered.append(sc)
            continue
        for _ in range(new):
            r = {"slots": {}, "row": None}
            rows.append(r)
            chosen.append(r)
        for i, r in enumerate(chosen):
            r["slots"][col] = (sc, i)
        covered.append(sc["id"])
    return rows, covered, uncovered, blanks


def plan_table(tab: dict, n_rows: int, packing: str = "auto") -> dict:
    kept = {c["id"] for c in tab["columns"] if c["keep"]}
    usable, skipped = [], []
    for sc in tab["scenarios"]:
        if not sc.get("enabled", True):
            skipped.append((sc, "disabled in the contract"))
        elif sc.get("column") is not None and sc["column"] not in kept:
            skipped.append((sc, "its column is dropped by the contract"))
        elif not sc.get("reproducible") or not sc.get("gen"):
            skipped.append((sc, sc.get("not_reproduced_reason") or "no generator exists for this class"))
        else:
            usable.append(sc)
    usable.sort(key=lambda s: (not s.get("pinned"), s["priority"], bool(s.get("common")), s["id"]))
    n_iso = len(_pack(usable, math.inf, 1)[0])
    n_packed = len(_pack(usable, math.inf, math.inf)[0])
    if packing == "isolate":
        steps = [1]
    elif packing == "packed":
        steps = [math.inf]
    elif packing == "auto":
        steps = list(PACK_STEPS) + [math.inf]
    else:
        raise SynthError("packing must be auto, isolate or packed")
    best = None
    reserve = math.ceil(0.2 * n_rows) if n_rows >= 5 else 0
    for cap in ([n_rows - reserve, n_rows] if packing == "auto" and reserve else [n_rows]):
        for m in steps:
            res = _pack(usable, cap, m)
            if not res[2]:
                best = (res, m)
                break
        if best:
            break
    if best is None:
        m = steps[-1]
        best = (_pack(usable, n_rows, m), m)
    (rows, covered, uncovered, blanks), m = best
    return {"rows": rows, "covered": covered, "uncovered": uncovered, "skipped": skipped, "blank_rows": blanks,
            "max_per_row": None if m == math.inf else m, "n_min_isolated": n_iso, "n_min_packed": n_packed,
            "usable": usable}


# -- generation ------------------------------------------------------------------------------------
def _table_order(tables: list[dict]) -> list[dict]:
    """Referenced tables first; reference cycles fall back to contract order."""
    by_name = {t["name"]: t for t in tables}
    done: list[dict] = []
    seen: set[str] = set()

    def visit(t, stack):
        if t["name"] in seen or t["name"] in stack:
            return
        stack.add(t["name"])
        for c in t["columns"]:
            ref = c["key"].get("references")
            if c["keep"] and c["key"]["role"] == "reference" and ref and ref["table"] in by_name:
                visit(by_name[ref["table"]], stack)
        stack.discard(t["name"])
        seen.add(t["name"])
        done.append(t)

    for t in tables:
        visit(t, set())
    return done


def resolve_row_counts(contract: dict, rows) -> dict[str, int]:
    tables = contract["tables"]
    if isinstance(rows, dict):
        base = rows.get("*")
    else:
        base, rows = rows, {}
    if base is not None and (not isinstance(base, int) or isinstance(base, bool)):
        raise SynthError("row counts must be integers between 1 and 5,000,000")
    out = {}
    largest = max((t["source_rows"] for t in tables), default=0)
    for t in tables:
        n = rows.get(t["name"])
        if n is None:
            if base is None:
                raise SynthError("a row count is required for every table")
            n = base if t["source_rows"] >= base or t["source_rows"] == largest else max(1, t["source_rows"])
        if not isinstance(n, int) or isinstance(n, bool) or n < 1 or n > 5_000_000:
            raise SynthError("row counts must be integers between 1 and 5,000,000")
        out[t["name"]] = n
    return out


def _note_rows(rows_spec: list, rng: Rng) -> list[list[tuple[int, str]]]:
    out = []
    for row in rows_spec:
        cells = []
        for c in row:
            lo, hi = c["length"]
            fam = c.get("family")
            if fam == "number":
                text = _digits(rng, max(1, min(hi, 6)))
            elif fam == "date":
                text = f"{rng.between(2015, 2024):04d}-{rng.between(1, 12):02d}-{rng.between(1, 28):02d}"
            else:
                words = [rng.choice(_LOREM) for _ in range(max(1, c.get("words", 1)))]
                text = " ".join(words).capitalize()
                target = rng.between(lo, hi)
                while len(text) < lo:
                    text += " " + rng.choice(_LOREM)
                text = text[:max(target, 1)].rstrip() or "Note"
            cells.append((c["col"], text))
        out.append(cells)
    return out


def generate(contract: dict, rows, seed: int | str = 0, packing: str = "auto") -> dict:
    """Generate the synthetic dataset, the Scenario Manifest and the coverage report."""
    fmt = contract["layout"]["format"]
    counts = resolve_row_counts(contract, rows)
    parents: dict = {}
    tables_out = {}
    manifest = []
    coverage_tables = []
    for tab in _table_order(contract["tables"]):
        tg = _TableGen(tab, fmt, seed, parents)
        n = counts[tab["name"]]
        plan = plan_table(tab, n, packing)
        res = _generate_table(tg, tab, n, plan)
        tables_out[tab["name"]] = res["table"]
        manifest.extend(res["manifest"])
        for c in tg.cols:
            if c.role in ("unique", "none", "repeating"):
                seen, vals = set(), []
                for v in c.values:
                    if v.text not in seen:
                        seen.add(v.text)
                        vals.append(v)
                parents[(tab["name"], c.id)] = vals
        unc = [{"id": s["id"], "class": s["class"], "column": s.get("column"), "description": s["description"],
                "reason": "row budget too small"} for s in plan["uncovered"]]
        unc += [{"id": s["id"], "class": s["class"], "column": s.get("column"), "description": s["description"],
                 "reason": why} for s, why in plan["skipped"]]
        unc += res["unsatisfied"]
        covered = [i for i in plan["covered"] if i not in {u["id"] for u in res["unsatisfied"]}]
        coverage_tables.append({
            "table": tab["name"], "requested_rows": n, "generated_data_rows": res["n_data"],
            "blank_rows": res["n_blank"], "scenarios_total": len(tab["scenarios"]),
            "scenarios_covered": len(covered), "covered": covered, "uncovered": unc,
            "max_scenarios_per_row": plan["max_per_row"], "n_min_isolated": plan["n_min_isolated"],
            "n_min_packed": plan["n_min_packed"],
            "full_coverage": not unc,
            "full_coverage_of_reproducible": not plan["uncovered"] and not res["unsatisfied"],
        })
    order = [t["name"] for t in contract["tables"]]
    rng = Rng("anonimizer", GENERATOR_VERSION, seed, "__notes__")
    notes = {n["name"]: _note_rows(n["rows"], rng) for n in contract.get("notes", [])}
    return {
        "format": fmt,
        "tables": {name: tables_out[name] for name in order},
        "notes": notes,
        "manifest": sorted(manifest, key=lambda e: (order.index(e["table"]), e["data_rows"][:1] or [0], e["scenario_id"])),
        "coverage": {
            "tables": sorted(coverage_tables, key=lambda c: order.index(c["table"])),
            "full_coverage": all(c["full_coverage"] for c in coverage_tables),
            "full_coverage_of_reproducible": all(c["full_coverage_of_reproducible"] for c in coverage_tables),
        },
        "params": {"generator_version": GENERATOR_VERSION, "seed": seed, "packing": packing, "rows": counts},
    }


def _generate_table(tg: _TableGen, tab: dict, n: int, plan: dict) -> dict:
    rng = tg.rng
    cols = tg.cols
    prows = plan["rows"]
    n_scn = len(prows)
    n_typ = max(0, n - n_scn)
    unsatisfied: list[dict] = []

    def fail(sc, why):
        unsatisfied.append({"id": sc["id"], "class": sc["class"], "column": sc.get("column"),
                            "description": sc["description"], "reason": why})

    # Key pools and reservations come first so that typical rows cannot disturb multiplicities.
    group_values: dict = {}
    for c in cols:
        if c.role == "repeating":
            ratio = c.spec["key"].get("distinct_ratio") or 0.5
            k = max(1, min(max(1, n_typ), round(ratio * max(1, n_typ))))
            c.keypool = [tg.fresh(c) for _ in range(k)]
    for r in prows:
        for cid, (sc, i) in r["slots"].items():
            if sc["gen"]["g"] != "key_multiplicity" or i != 0:
                continue
            c = tg.by_id[cid]
            if c.role == "reference" and c.parent_values:
                free = [v for v in c.parent_values if v.text not in c.reserved]
                if len(free) <= 1:
                    fail(sc, "the referenced table has too few generated key values to isolate this case")
                    continue
                v = rng.choice(free)
            else:
                v = tg.fresh(c, {x.text for x in c.keypool})
            c.reserved.add(v.text)
            group_values[sc["id"]] = v
    failed = {u["id"] for u in unsatisfied}

    data: list[dict] = []  # {"cells": [...], "extra": [...], "kind": "typical"|"scenario", "tags": [...], "after": row|None}
    for _ in range(n_typ):
        data.append({"cells": [tg.typical(c) for c in cols], "extra": [], "kind": "typical", "tags": [], "after": None})
    typical_rows = list(data)

    def _needs_source(r: dict) -> bool:
        if r["row"] is not None:
            return r["row"]["gen"]["g"] == "duplicate_row"
        return any(sc["gen"]["g"] == "duplicate_key" for sc, _i in r["slots"].values())

    # Rows that copy from another row are built last, so that a source row always exists.
    for r in sorted(prows, key=_needs_source):
        row = {"cells": None, "extra": [], "kind": "scenario", "tags": [], "after": None}
        rsc = r["row"]
        if rsc is not None:
            g = rsc["gen"]
            if g["g"] == "duplicate_row":
                src = rng.choice(typical_rows) if typical_rows else (rng.choice(data) if data else None)
                if src is None:
                    row["cells"] = [tg.typical(c, False) for c in cols]
                    fail(rsc, "no other row exists to duplicate")
                else:
                    row["cells"] = list(src["cells"])
                    row["extra"] = list(src["extra"])
                    row["after"] = src
                    row["tags"].append((rsc, None, {"copy_of": src}))
            else:
                row["cells"] = [tg.typical(c, False) for c in cols]
                if g["g"] == "ragged_short":
                    k = min(int(g.get("missing_fields", 1)), max(0, len(cols) - 1))
                    if k < 1:
                        fail(rsc, "the table has a single kept column")
                    else:
                        row["cells"] = row["cells"][: len(cols) - k]
                        row["tags"].append((rsc, None, {}))
                else:
                    k = max(1, min(int(g.get("extra_fields", 1)), 50))
                    row["extra"] = [EMPTY_CELL if g.get("empty") else OutCell(_word(rng, 4)) for _ in range(k)]
                    row["tags"].append((rsc, None, {}))
            data.append(row)
            continue
        cells = []
        for c in cols:
            slot = r["slots"].get(c.id)
            if slot is None:
                cells.append(tg.typical(c, False))
                continue
            sc, _i = slot
            g = sc["gen"]
            kind = g["g"]
            if sc["id"] in failed:
                cells.append(tg.typical(c, False))
                continue
            if kind == "key_multiplicity":
                cells.append(group_values[sc["id"]])
            elif kind == "duplicate_key":
                j = cols.index(c)
                src = [x for x in typical_rows if len(x["cells"]) > j and x["cells"][j].text] or \
                      [x for x in data if x["after"] is None and len(x["cells"]) > j and x["cells"][j].text
                       and x["cells"][j].kind != ""]
                if not src:
                    cells.append(tg.typical(c, False))
                    fail(sc, "no earlier key value exists to repeat")
                    continue
                orig = rng.choice(src)
                cells.append(orig["cells"][cols.index(c)])
                row["after"] = orig
            elif kind == "dangling_reference":
                cells.append(tg.fresh(c, {v.text for v in (c.parent_values or [])}))
            else:
                v = tg.value(g, c, {"_scenario": True} if kind in ("number", "date") else None)
                if c.role == "unique" and v.text:
                    c.used.add(v.text)
                cells.append(v)
            row["tags"].append((sc, c, {}))
        row["cells"] = cells
        data.append(row)

    # Order: shuffle, keep a typical first row when one exists, keep copies after their originals.
    rng.shuffle(data)
    if data and data[0]["kind"] != "typical":
        j = next((i for i, r in enumerate(data) if r["kind"] == "typical"), None)
        if j is not None:
            data[0], data[j] = data[j], data[0]
    pos = {id(r): i for i, r in enumerate(data)}
    for r in list(data):
        o = r["after"]
        if o is not None and pos[id(r)] < pos[id(o)]:
            i, j = pos[id(r)], pos[id(o)]
            data[i], data[j] = data[j], data[i]
            pos[id(r)], pos[id(o)] = j, i
    blank_after: list[int] = []
    for _ in range(plan["blank_rows"]):
        blank_after.append(rng.between(1, max(1, len(data) - 1)) if len(data) > 1 else len(data))
    blank_sc = [s for s in plan["usable"] if s["gen"]["g"] == "blank_row"]
    out_rows = []
    index_of = {}
    for i, r in enumerate(data):
        index_of[id(r)] = i + 1
    blanks_sorted = sorted(blank_after)
    manifest = []
    bi = 0
    for i, r in enumerate(data):
        out_rows.append({"kind": "data", "cells": r["cells"], "extra": r["extra"], "data_row": i + 1})
        while bi < len(blanks_sorted) and blanks_sorted[bi] == i + 1:
            out_rows.append({"kind": "blank", "cells": [], "extra": [], "data_row": None, "after_data_row": i + 1})
            sc = blank_sc[bi] if bi < len(blank_sc) else blank_sc[-1]
            manifest.append(_entry(tab, sc, None, [], note=f"blank row after data row {i + 1}", blank_after=i + 1))
            bi += 1
    groups: dict = {}
    for r in data:
        for sc, c, extra in r["tags"]:
            key = (sc["id"], c.id if c else None)
            e = groups.get(key)
            if e is None:
                e = groups[key] = _entry(tab, sc, c, [])
            e["data_rows"].append(index_of[id(r)])
            if "copy_of" in extra:
                e["note"] = f"copy of data row {index_of[id(extra['copy_of'])]}"
            if sc["gen"]["g"] == "duplicate_key" and r["after"] is not None:
                e["note"] = f"repeats the key of data row {index_of[id(r['after'])]}"
    for e in groups.values():
        e["data_rows"].sort()
        manifest.append(e)
    header = [c.spec["name"] for c in cols] if tab["header_present"] else None
    return {
        "table": {"name": tab["name"], "output_name": tab.get("output_name") or tab["name"], "sheet": tab["sheet"],
                  "header": header, "columns": [c.id for c in cols],
                  "preamble": _note_rows(tab.get("preamble") or [], rng), "rows": out_rows},
        "manifest": manifest, "unsatisfied": unsatisfied,
        "n_data": len(data), "n_blank": len(blanks_sorted),
    }


def _entry(tab: dict, sc: dict, col, data_rows: list, note: str | None = None, blank_after: int | None = None) -> dict:
    return {"scenario_id": sc["id"], "class": sc["class"], "description": sc["description"],
            "table": tab["name"], "column": col.id if col else None,
            "column_name": col.spec["name"] if col else None, "column_position": None,
            "data_rows": data_rows, "blank_after_data_row": blank_after, "note": note, "locations": []}
