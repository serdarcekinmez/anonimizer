"""Value pattern classification. Pure functions, no I/O, no state.

``classify`` turns one raw cell into a pattern class ``V``. The class never contains the
value itself, with one exception: literal missing-value markers from the allowlist (``N/A``,
``null`` ...) and boolean words, which form a closed, public vocabulary.
"""

from __future__ import annotations

import calendar
import datetime as _dt
import re
from itertools import groupby
from typing import NamedTuple

from .grid.model import ABSENT, BOOL, EMPTY, EMPTY_STRING, ERROR, ISODATE, NUMBER, QUOTED_EMPTY, WHITESPACE

# Families
MISSING, ERR, NUM, DATE, BOOLEAN, TXT = "missing", "error", "number", "date", "bool", "text"

# Flags
PAD_LEAD, PAD_TRAIL, NEG, ZERO, LEADZERO, PLUS = 1, 2, 4, 8, 16, 32
INVALID, AMBIG, MULTILINE, NONASCII, CONTROL, FORMULA_LIKE, UNPADDED = 64, 128, 256, 512, 1024, 2048, 4096
PADDED = PAD_LEAD | PAD_TRAIL

FLAG_NAMES = {
    PAD_LEAD: "leading_whitespace", PAD_TRAIL: "trailing_whitespace", NEG: "negative", ZERO: "zero",
    LEADZERO: "leading_zero", PLUS: "explicit_plus", INVALID: "invalid", AMBIG: "ambiguous",
    MULTILINE: "multiline", NONASCII: "non_ascii", CONTROL: "control_chars", FORMULA_LIKE: "formula_like",
    UNPADDED: "unpadded",
}

# Built-in missing-marker allowlist (compared case-insensitively on the stripped value).
DEFAULT_MARKERS = frozenset({
    "n/a", "na", "n.a.", "n.a", "#n/a", "nan", "null", "none", "nil", "-", "--", "---", "?", "??", "???",
    "missing", "unknown", "undefined", "tbd", "tba", "(blank)", "blank", "(null)", "<null>", "<na>",
    "#null!", "#value!", "#div/0!", "#ref!", "#name?", "#num!", "n.d.", "nd", ".", "..", "...", "\\n",
    "not available", "not applicable", "inconnu", "néant", "s.o.", "nc", "n.c.", "n/c",
})
ERROR_CODES = frozenset({"#N/A", "#NULL!", "#VALUE!", "#DIV/0!", "#REF!", "#NAME?", "#NUM!", "#GETTING_DATA",
                         "#SPILL!", "#CALC!"})
BOOL_WORDS = {
    "true": ("true_false", 1), "false": ("true_false", 0), "yes": ("yes_no", 1), "no": ("yes_no", 0),
    "y": ("y_n", 1), "n": ("y_n", 0), "oui": ("oui_non", 1), "non": ("oui_non", 0),
}
BOOL_STYLES = {"true_false": ("true", "false"), "yes_no": ("yes", "no"), "y_n": ("y", "n"),
               "oui_non": ("oui", "non"), "xlsx_bool": ("1", "0")}

MONTHS = {}
for _i, _names in enumerate([
    ("jan", "january", "janv", "janvier"), ("feb", "february", "fév", "févr", "février", "fev", "fevrier"),
    ("mar", "march", "mars"), ("apr", "april", "avr", "avril"), ("may", "mai"), ("jun", "june", "juin"),
    ("jul", "july", "juil", "juillet"), ("aug", "august", "août", "aout"),
    ("sep", "sept", "september", "septembre"), ("oct", "october", "octobre"),
    ("nov", "november", "novembre"), ("dec", "december", "déc", "décembre", "decembre"),
], start=1):
    for _n in _names:
        MONTHS[_n] = _i


class V(NamedTuple):
    family: str
    sub: str  # format / kind / marker literal / error code
    flags: int = 0
    a: int = 0  # number: integer digits; date: year; text: length; bool: truth value
    b: int = 0  # number: decimal digits; text: word count


_CUR = "€$£¥₺"
_ISO_CUR = re.compile(r"^(.*\d)\s?(EUR|USD|GBP|CHF|TRY|JPY|CAD|AUD)$")
_UNSIGNED = re.compile(
    r"(?P<int>\d+)"
    r"|(?P<sci>(?:\d+\.?\d*|\.\d+)[eE][+-]?\d+)"
    r"|(?P<thou_comma_dec_dot>\d{1,3}(?:,\d{3})+\.\d+)"
    r"|(?P<thou_dot_dec_comma>\d{1,3}(?:\.\d{3})+,\d+)"
    r"|(?P<thou_comma>\d{1,3}(?:,\d{3}){2,})"
    r"|(?P<thou_dot>\d{1,3}(?:\.\d{3}){2,})"
    r"|(?P<comma_ambiguous>\d{1,3},\d{3})"
    r"|(?P<dec_comma>\d+,\d+)"
    r"|(?P<dec_dot>\d+\.\d*|\.\d+)"
    r"|(?P<thou_space_dec_comma>\d{1,3}(?:[   ]\d{3})+,\d+)"
    r"|(?P<thou_space_dec_dot>\d{1,3}(?:[   ]\d{3})+\.\d+)"
    r"|(?P<thou_space>\d{1,3}(?:[   ]\d{3})+)"
)
_DEC_SEP = {"dec_comma": ",", "dec_dot": ".", "thou_comma_dec_dot": ".", "thou_dot_dec_comma": ",",
            "thou_space_dec_comma": ",", "thou_space_dec_dot": ".", "comma_ambiguous": None}
_NUM_START = frozenset("0123456789+-.(" + _CUR)


def _number(s: str) -> V | None:
    if s[0] not in _NUM_START:
        return None
    core, template, flags = s, "{n}", 0
    if core.endswith("%"):
        inner = core[:-1]
        template = "{n} %" if inner.endswith(" ") else "{n}%"
        core = inner.rstrip()
    if len(core) > 2 and core[0] == "(" and core[-1] == ")":
        core, flags, template = core[1:-1], flags | NEG, template.replace("{n}", "({n})")
    if not core:
        return None
    if core[0] in "+-":
        flags |= NEG if core[0] == "-" else PLUS
        core = core[1:]
    if not core:
        return None
    if core[0] in _CUR:
        sym, rest = core[0], core[1:]
        sp = " " if rest.startswith(" ") else ""
        template, core = template.replace("{n}", sym + sp + "{n}"), rest.lstrip()
        if core[:1] in ("-", "+"):
            flags |= NEG if core[0] == "-" else PLUS
            core = core[1:]
    elif core[-1] in _CUR:
        sym, rest = core[-1], core[:-1]
        sp = " " if rest.endswith(" ") else ""
        template, core = template.replace("{n}", "{n}" + sp + sym), rest.rstrip()
    else:
        m = _ISO_CUR.match(core)
        if m:
            sp = " " if core[len(m.group(1))] == " " else ""
            template, core = template.replace("{n}", "{n}" + sp + m.group(2)), m.group(1)
    m = _UNSIGNED.fullmatch(core)
    if not m:
        return None
    sub = m.lastgroup or "int"
    if sub == "int":
        idig, ddig = len(core), 0
        if idig > 1 and core[0] == "0":
            flags |= LEADZERO
    elif sub == "sci":
        idig, ddig = 1, 0
    elif sub == "comma_ambiguous":
        idig, ddig = len(core) - 1, 0
    else:
        sep = _DEC_SEP.get(sub)
        if sep:
            ip, _, dp = core.rpartition(sep)
            idig, ddig = sum(ch.isdigit() for ch in ip), len(dp)
        else:
            idig, ddig = sum(ch.isdigit() for ch in core), 0
    if not core.strip("0.,eE+-   ") or (sub == "sci" and not core.lower().split("e")[0].strip("0.")):
        flags |= ZERO
        flags &= ~LEADZERO if core.strip("0") else flags
    if template != "{n}":
        sub = sub + "|" + template
    return V(NUM, sub, flags, idig, ddig)


_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:([T ])(\d{2}):(\d{2})(?::(\d{2})(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?")
_SEP3 = re.compile(r"(\d{1,4})([/.\-])(\d{1,2})\2(\d{1,4})(?: (\d{1,2}):(\d{2})(?::(\d{2}))?)?")
_DMONY = re.compile(r"(\d{1,2})([ \-])([^\W\d_]{3,9})\.?\2(\d{2}|\d{4})")
_MONDY = re.compile(r"([^\W\d_]{3,9})\.? (\d{1,2}),? (\d{4})")
_TIME = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?")


def _valid(y: int, m: int, d: int) -> bool:
    if not 1 <= m <= 12 or d < 1 or y < 1:
        return False
    return d <= calendar.monthrange(y if y <= 9999 else 2000, m)[1]


def _full_year(y: str) -> int:
    v = int(y)
    return v if len(y) > 2 else (2000 + v if v < 70 else 1900 + v)


_ABBREVIATIONS = frozenset({"sept", "janv", "févr", "fév", "fev", "avr", "juil", "déc"})


def _month_token(name: str) -> str:
    """b: abbreviated, B: full, e: either (May is its own abbreviation); resolved per column."""
    low = name.lower()
    if low in ("may", "mai"):
        return "e"
    return "b" if len(low) <= 3 or low in _ABBREVIATIONS else "B"


def _date(s: str) -> V | None:
    c0 = s[0]
    if c0.isdigit():
        m = _ISO.fullmatch(s)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            flags = 0 if _valid(y, mo, d) else INVALID
            sub = "Y-M-D"
            if m.group(4):
                hh, mi, ss = int(m.group(5)), int(m.group(6)), int(m.group(7) or 0)
                if hh > 23 or mi > 59 or ss > 59:
                    flags |= INVALID
                sub += m.group(4) + "h:m" + (":s" if m.group(7) else "") + (".f" if m.group(8) else "")
                if m.group(9):
                    sub += "Z" if m.group(9) == "Z" else "z"
            return V(DATE, sub, flags, y)
        m = _SEP3.fullmatch(s)
        if m:
            p1, sep, p2, p3 = m.group(1), m.group(2), m.group(3), m.group(4)
            flags = 0
            if len(p1) == 4:  # Y sep M sep D
                if len(p3) > 2:
                    return None
                y, mo, d = int(p1), int(p2), int(p3)
                sub = f"Y{sep}M{sep}D"
                parts = (p2, p3)
            elif len(p1) <= 2 and len(p3) in (2, 4):
                a, bb = int(p1), int(p2)
                y = _full_year(p3)
                ytok = "Y" if len(p3) == 4 else "y"
                parts = (p1, p2)
                if a > 12 and bb > 12 or a == 0 or bb == 0:
                    flags |= INVALID
                    sub, mo, d = f"X{sep}X{sep}{ytok}", 0, 0
                elif a > 12:
                    sub, d, mo = f"D{sep}M{sep}{ytok}", a, bb
                elif bb > 12 and sep == "/":
                    sub, mo, d = f"M{sep}D{sep}{ytok}", a, bb
                elif sep == "/":
                    sub, d, mo, flags = f"X{sep}X{sep}{ytok}", a, bb, flags | AMBIG
                else:  # dotted and dashed day-first notations
                    sub, d, mo = f"D{sep}M{sep}{ytok}", a, bb
                if sep == "." and len(p3) == 2 and not m.group(5):
                    # 12.05.21 is more often a version or a number than a date; require evidence
                    return None
            else:
                return None
            if not flags & INVALID and not _valid(y, mo, d):
                flags |= INVALID
            if any(len(p) == 1 for p in parts):
                flags |= UNPADDED
            elif any(p[0] == "0" for p in parts):
                flags |= LEADZERO
            if m.group(5):
                if int(m.group(5)) > 23 or int(m.group(6)) > 59 or int(m.group(7) or 0) > 59:
                    flags |= INVALID
                sub += " h:m" + (":s" if m.group(7) else "")
            return V(DATE, sub, flags, y)
        m = _DMONY.fullmatch(s)
        if m:
            mo = MONTHS.get(m.group(3).lower())
            if mo is None:
                return None
            y = _full_year(m.group(4))
            tok = _month_token(m.group(3))
            sub = f"D{m.group(2)}{tok}{m.group(2)}{'Y' if len(m.group(4)) == 4 else 'y'}"
            return V(DATE, sub, 0 if _valid(y, mo, int(m.group(1))) else INVALID, y)
        m = _TIME.fullmatch(s)
        if m:
            bad = int(m.group(1)) > 23 or int(m.group(2)) > 59 or int(m.group(3) or 0) > 59
            return V(DATE, "h:m" + (":s" if m.group(3) else ""), INVALID if bad else 0, 0)
        return None
    if c0.isalpha():
        m = _MONDY.fullmatch(s)
        if m:
            mo = MONTHS.get(m.group(1).lower())
            if mo is None:
                return None
            y = int(m.group(3))
            tok = _month_token(m.group(1))
            return V(DATE, f"{tok} D, Y" if "," in s else f"{tok} D Y",
                     0 if _valid(y, mo, int(m.group(2))) else INVALID, y)
    return None


_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^\W\d_]{2,}")
_URL = re.compile(r"(?:(?:https?|ftp)://|www\.)\S+", re.I)
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_IPV4 = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}")
_PHONE = re.compile(r"\+?[\d\s().\-/]{7,24}")
_WORDISH = re.compile(r"[^\W\d_]+(?:['’.\-][^\W\d_]+)*\.?,?")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def text_kind(s: str) -> tuple[str, int]:
    """Coarse kind of a text value and its word count."""
    if "@" in s and _EMAIL.fullmatch(s):
        return "email", 1
    if _URL.fullmatch(s):
        return "url", 1
    if len(s) == 36 and _UUID.fullmatch(s):
        return "uuid", 1
    words = s.split()
    n = len(words)
    if n <= 1:
        if s.isalpha():
            return "alpha", 1
        if s.isalnum():
            return ("digits" if s.isdigit() else "alnum"), 1
        if _IPV4.fullmatch(s):
            return "ipv4", 1
        if _PHONE.fullmatch(s) and sum(c.isdigit() for c in s) >= 7:
            return "phone", 1
        if any(c.isalnum() for c in s):
            return "code", 1
        return "symbols", 1
    if _PHONE.fullmatch(s) and sum(c.isdigit() for c in s) >= 7:
        return "phone", n
    if all(_WORDISH.fullmatch(w) for w in words):
        return ("words" if n <= 3 else "sentence"), n
    return ("phrase" if n <= 3 else "sentence"), n


def _text(s: str, raw: str, flags: int) -> V:
    kind, n = text_kind(s)
    if "\n" in raw or "\r" in raw:
        flags |= MULTILINE
    if not s.isascii():
        flags |= NONASCII
    if _CTRL.search(raw):
        flags |= CONTROL
    if s[0] in "=@" or (s[0] in "+-" and kind != "phone" and any(c.isalpha() for c in s)):
        flags |= FORMULA_LIKE
    return V(TXT, kind, flags, len(s), n)


_EXCEL_EPOCH = _dt.date(1899, 12, 30)


def excel_serial_to_date(serial: float, date1904: bool = False) -> _dt.date | None:
    try:
        days = int(serial)
        if date1904:
            days += 1462
        if days < 1 or days > 2958465:
            return None
        return _EXCEL_EPOCH + _dt.timedelta(days=days)
    except (OverflowError, ValueError):
        return None


# -- spreadsheet number formats ----------------------------------------------------------------
# A number format can hold literal text: quoted strings, backslash-escaped characters, and
# bracketed currency or locale tags. That text is part of the source file. Only layout codes
# (digit placeholders, separators, date and time codes) may travel to a contract or an output.
_FMT_PART = re.compile(r'"[^"]*"?|\\.|_.|\*.|\[[^\]]*\]?|.', re.S)
_FMT_ELAPSED = re.compile(r"\[(?:h+|m+|s+)\]$", re.I)
_FMT_WORDS = ("general", "am/pm", "a/p")
_FMT_CHARS = frozenset("0#?,.%Ee+-/: ()$@yYmMdDhHsS;")
_FMT_ESCAPED_OK = frozenset(" -/:().,+$")
_FMT_CANONICAL = {"date": "yyyy-mm-dd", "time": "hh:mm:ss", "datetime": "yyyy-mm-dd hh:mm:ss"}


def safe_number_format(code: str | None) -> str | None:
    """Return the layout part of a spreadsheet number format; literal text is removed.

    Kept: digit placeholders, thousands and decimal separators, percent, exponent, fraction,
    date and time codes, elapsed-time brackets, General, AM/PM and section separators. Removed:
    quoted text, escaped letters, padding and repeat characters, colour, condition, currency
    and locale brackets. A date format stays a date format. ``None`` means "no format".
    """
    if code is None:
        return None
    from .grid.xlsx_reader import date_format_kind, is_date_format

    s = str(code)
    out: list[str] = []
    i = 0
    while i < len(s):
        low = s[i:i + 8].lower()
        word = next((w for w in _FMT_WORDS if low.startswith(w)), None)
        if word:
            out.append(s[i:i + len(word)])
            i += len(word)
            continue
        tok = _FMT_PART.match(s, i).group()
        i += len(tok)
        if len(tok) == 1:
            if tok in _FMT_CHARS:
                out.append(tok)
        elif tok[0] == "\\" and tok[1] in _FMT_ESCAPED_OK:
            out.append(tok)
        elif _FMT_ELAPSED.match(tok):
            out.append(tok)
    sections = "".join(out).split(";")
    while sections and not sections[-1].strip():
        sections.pop()
    result = ";".join(sections)
    if not result.strip(" ;,.-+/:()$\\"):
        result = ""
    if is_date_format(s) and not is_date_format(result):
        return _FMT_CANONICAL[date_format_kind(s)]
    if result and is_date_format(result) and not is_date_format(s):
        return None
    return result or None


def format_literals(code: str | None) -> list[str]:
    """The literal text parts of a number format (quoted, escaped runs, currency tags)."""
    if not code:
        return []
    out: list[str] = []
    run = ""
    for m in _FMT_PART.finditer(str(code)):
        tok = m.group()
        if tok.startswith("\\") and len(tok) == 2:
            run += tok[1]
            continue
        if run:
            out.append(run)
            run = ""
        if tok.startswith('"'):
            body = tok[1:-1] if tok.endswith('"') and len(tok) > 1 else tok[1:]
            if body.strip():
                out.append(body)
        elif tok.startswith("[$"):
            body = tok[2:].rstrip("]").split("-", 1)[0]
            if body.strip():
                out.append(body)
    if run:
        out.append(run)
    return out


def classify(raw: str | None, stype: str = "text", quoted: bool = False, number_format: str | None = None,
             markers: frozenset = DEFAULT_MARKERS, date1904: bool = False) -> V:
    if raw is None:
        return V(MISSING, ABSENT)
    if raw == "":
        if quoted:
            return V(MISSING, QUOTED_EMPTY)
        return V(MISSING, EMPTY_STRING if stype in ("shared_string", "inline_string", "formula_string") else EMPTY)
    if stype == ERROR:
        return V(ERR, raw)
    if stype == BOOL:
        return V(BOOLEAN, "xlsx_bool", 0, 1 if raw.strip() in ("1", "true", "TRUE") else 0)
    s = raw.strip()
    if not s or not s.strip("   "):
        return V(MISSING, WHITESPACE, 0, len(raw))
    flags = 0
    if s is not raw and len(s) != len(raw):
        if raw[0] != s[0]:
            flags |= PAD_LEAD
        if raw[-1] != s[-1]:
            flags |= PAD_TRAIL
    if stype == NUMBER:
        if number_format is not None:
            from .grid.xlsx_reader import date_format_kind, is_date_format
            if is_date_format(number_format):
                kind = date_format_kind(number_format)
                try:
                    serial = float(s)
                except ValueError:
                    return V(DATE, "excel_" + kind, INVALID)
                if kind == "time":
                    return V(DATE, "excel_time", 0 if 0 <= serial < 1.0000001 or serial >= 0 else INVALID)
                d = excel_serial_to_date(serial, date1904)
                return V(DATE, "excel_" + kind, 0 if d else INVALID, d.year if d else 0)
        if len(s) >= 15:
            # Stored doubles often carry binary artefacts (97.01000000000001); count the digits of
            # the shortest text that reads back as the same number. The raw text itself is kept.
            try:
                s = repr(float(s))
                if s.endswith(".0"):
                    s = s[:-2]
            except ValueError:
                pass
        v = _number(s)
        return v if v is not None else V(TXT, "other", flags, len(s), 1)
    if stype == ISODATE:
        v = _date(s)
        return v if v is not None else V(DATE, "Y-M-D", INVALID)
    low = s.casefold()
    if low in markers:
        return V(MISSING, "marker:" + s, flags)
    if s in ERROR_CODES:
        return V(MISSING, "marker:" + s, flags)
    b = BOOL_WORDS.get(low)
    if b is not None:
        case = "lower" if s.islower() else "upper" if s.isupper() else "title"
        return V(BOOLEAN, f"{b[0]}:{case}", flags, b[1])
    v = _number(s)
    if v is not None:
        return v._replace(flags=v.flags | flags) if flags else v
    v = _date(s)
    if v is not None:
        return v._replace(flags=v.flags | flags) if flags else v
    return _text(s, raw, flags)


# -- shapes -----------------------------------------------------------------------------------
_ASCII_CLASS = {i: "S" for i in range(128)}
for _c in range(ord("A"), ord("Z") + 1):
    _ASCII_CLASS[_c] = "A"
for _c in range(ord("a"), ord("z") + 1):
    _ASCII_CLASS[_c] = "a"
for _c in range(ord("0"), ord("9") + 1):
    _ASCII_CLASS[_c] = "9"
for _ch in " !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~":
    _ASCII_CLASS[ord(_ch)] = _ch
for _ch in "\t\n\r":
    _ASCII_CLASS[ord(_ch)] = " "
CLASS_CHARS = "Aa9XxSC"


def _cls(ch: str) -> str:
    if ch.isalpha():
        return "X" if ch.isupper() else "x"
    if ch.isdigit():
        return "9"
    if ch.isspace():
        return " "
    return "S"


def shape_of(s: str) -> tuple:
    """Run-length encoded character-class shape, e.g. ``AB-1234`` -> (('A',2),('-',1),('9',4))."""
    if s.isascii():
        classes = s.translate(_ASCII_CLASS)
    else:
        classes = "".join(_ASCII_CLASS[ord(c)] if c < "\x80" else _cls(c) for c in s)
    return tuple((k, len(list(g))) for k, g in groupby(classes))


_BUCKETS = (1, 2, 4, 8, 16, 32, 64, 128)


def bucket(n: int) -> tuple[int, int]:
    lo = 1
    for hi in _BUCKETS:
        if n <= hi:
            return lo, hi
        lo = hi + 1
    return lo, max(n, lo)


def generalize_shape(shape: tuple) -> tuple:
    """Bucket run lengths so that a rare value's exact layout is not carried over.

    A capital followed by lowercase letters becomes one capitalised-word class ``C``.
    """
    out = []
    i = 0
    n_items = len(shape)
    while i < n_items:
        cls, n = shape[i]
        if cls == "A" and n == 1 and i + 1 < n_items and shape[i + 1][0] == "a":
            lo, hi = bucket(shape[i + 1][1] + 1)
            out.append(("C", lo, hi))
            i += 2
            continue
        lo, hi = bucket(n)
        if cls in CLASS_CHARS:
            out.append((cls, lo, hi))
        else:
            out.append((cls, n, n) if n <= 2 else (cls, lo, hi))
        i += 1
    return tuple(out)


def shape_display(shape: tuple, limit: int = 48) -> str:
    """Human-readable rendering of a shape. Contains no source characters except punctuation."""
    total = sum(item[1] if len(item) == 2 else item[2] for item in shape)
    parts = []
    for item in shape:
        if len(item) == 2:
            cls, n = item
            parts.append(cls * n if total <= limit else (f"{cls}{{{n}}}" if n > 1 else cls))
        else:
            cls, lo, hi = item
            parts.append(cls if lo == hi == 1 else f"{cls}{{{lo}-{hi}}}" if lo != hi else f"{cls}{{{lo}}}")
    return "".join(parts)
