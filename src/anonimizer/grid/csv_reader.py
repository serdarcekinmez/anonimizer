"""Streaming CSV/TSV reader that preserves quoting, emptiness kinds and encoding evidence."""

from __future__ import annotations

import codecs
import io
import os
import re
from collections import Counter
from collections.abc import Iterator

from .model import GridError, Row, SheetInfo

DELIMITERS = (",", ";", "\t", "|")
_NON_ASCII = re.compile(r"[^\x00-\x7f]")
_SURROGATE = re.compile(r"[\udc80-\udcff]")
_CHUNK = 1 << 20


def detect_encoding(path: str) -> dict:
    """Return encoding evidence. Scans the whole file so a single bad byte deep inside counts."""
    with open(path, "rb") as fh:
        head = fh.read(4)
        bom = None
        if head.startswith(codecs.BOM_UTF8):
            bom, enc = "utf-8-sig", "utf-8-sig"
        elif head.startswith(codecs.BOM_UTF32_LE) or head.startswith(codecs.BOM_UTF32_BE):
            bom, enc = "utf-32", "utf-32"
        elif head.startswith(codecs.BOM_UTF16_LE) or head.startswith(codecs.BOM_UTF16_BE):
            bom, enc = "utf-16", "utf-16"
        else:
            enc = "utf-8"
        fh.seek(0)
        invalid = 0
        non_ascii = 0
        nul = 0
        if enc in ("utf-8", "utf-8-sig"):
            dec = codecs.getincrementaldecoder("utf-8")(errors="surrogateescape")
            while True:
                chunk = fh.read(_CHUNK)
                if not chunk:
                    break
                nul += chunk.count(b"\x00")
                if chunk.isascii():
                    dec.decode(b"")
                    continue
                text = dec.decode(chunk)
                bad = len(_SURROGATE.findall(text))
                invalid += bad
                non_ascii += len(_NON_ASCII.findall(text)) - bad
            tail = dec.decode(b"", final=True)
            invalid += len(_SURROGATE.findall(tail))
    result = {"encoding": enc, "bom": bom, "undecodable_bytes": 0, "non_ascii_chars": non_ascii,
              "nul_bytes": nul, "confidence": 1.0 if bom else 0.95}
    if enc == "utf-8" and invalid:
        if non_ascii >= 10 * invalid:
            # Mostly valid UTF-8 with a few stray bytes: keep UTF-8 and flag the bytes.
            result.update(undecodable_bytes=invalid, confidence=0.7)
        else:
            result.update(encoding="cp1252", confidence=0.6)
    elif enc == "utf-8" and non_ascii == 0:
        result["confidence"] = 1.0  # pure ASCII
    return result


def _open_text(path: str, encoding: str) -> io.TextIOWrapper:
    # newline="" keeps the original terminators; surrogateescape keeps undecodable bytes.
    return open(path, encoding=encoding, errors="surrogateescape", newline="")


def sniff_delimiter(path: str, encoding: str, quotechar: str = '"', max_lines: int = 400) -> dict:
    counts: dict[str, Counter] = {d: Counter() for d in DELIMITERS}
    n = 0
    with _open_text(path, encoding) as fh:
        for line in fh:
            body = line.rstrip("\r\n")
            if not body.strip():
                continue
            if quotechar in body:  # drop quoted sections before counting
                body = re.sub(re.escape(quotechar) + r"(?:[^" + re.escape(quotechar) + r"]|"
                              + re.escape(quotechar) * 2 + r")*" + re.escape(quotechar) + "?", "", body)
            for d in DELIMITERS:
                counts[d][body.count(d)] += 1
            n += 1
            if n >= max_lines:
                break
    if n == 0:
        return {"delimiter": ",", "confidence": 0.3, "candidates": []}
    scored = []
    for rank, d in enumerate(DELIMITERS):
        nonzero = {c: k for c, k in counts[d].items() if c > 0}
        if not nonzero:
            continue
        mode, freq = max(nonzero.items(), key=lambda kv: (kv[1], kv[0]))
        covered = sum(nonzero.values()) / n
        scored.append((freq / n, covered, mode, -rank, d))
    if not scored:
        return {"delimiter": ",", "confidence": 0.5, "candidates": []}
    if path.lower().endswith((".tsv", ".tab")) and any(s[4] == "\t" for s in scored):
        best = next(s for s in scored if s[4] == "\t")
    else:
        best = max(scored)
    cands = [{"delimiter": s[4], "consistency": round(s[0], 3), "fields": s[2] + 1}
             for s in sorted(scored, reverse=True)]
    return {"delimiter": best[4], "confidence": round(min(1.0, 0.4 + 0.6 * best[0]), 2), "candidates": cands}


class CsvSource:
    format = "csv"

    def __init__(self, path: str, *, encoding: str | None = None, delimiter: str | None = None,
                 quotechar: str = '"'):
        if not os.path.isfile(path):
            raise GridError("input file does not exist or is not a regular file")
        self.path = path
        enc_info = detect_encoding(path)
        if encoding:
            try:
                codecs.lookup(encoding)
            except LookupError:
                raise GridError("unknown encoding requested in the parse recipe") from None
            enc_info.update(encoding=encoding, confidence=1.0, user_defined=True)
        self.encoding = enc_info["encoding"]
        self.quotechar = quotechar
        if delimiter:
            dl = {"delimiter": delimiter, "confidence": 1.0, "candidates": [], "user_defined": True}
        else:
            dl = sniff_delimiter(path, self.encoding, quotechar)
        self.delimiter = dl["delimiter"]
        self.info = {
            "format": "csv", "size_bytes": os.path.getsize(path), "encoding": enc_info,
            "delimiter": dl, "quotechar": quotechar,
            # filled after a full read:
            "newlines": {}, "records": None, "physical_lines": None,
            "unterminated_quote": 0, "text_after_closing_quote": 0, "multiline_records": 0,
            "final_newline": None,
        }
        self.sheets = [SheetInfo(0, "csv")]

    def rows(self, sheet: int = 0) -> Iterator[Row]:
        if sheet != 0:
            raise GridError("a CSV source has a single sheet")
        d, q = self.delimiter, self.quotechar
        newlines: Counter = Counter()
        stats = {"unterminated": 0, "stray": 0, "multiline": 0}
        lineno = 0
        index = 0
        last_term = ""
        with _open_text(self.path, self.encoding) as fh:
            first = True
            it = iter(fh)
            for line in it:
                lineno += 1
                start_line = lineno
                if first:
                    first = False
                    if line.startswith("﻿"):
                        line = line[1:]
                if line.endswith("\r\n"):
                    term = "\r\n"
                elif line.endswith("\n"):
                    term = "\n"
                elif line.endswith("\r"):
                    term = "\r"
                else:
                    term = ""
                last_term = term
                if term:
                    newlines[term] += 1
                if q not in line:
                    body = line[: len(line) - len(term)] if term else line
                    raw = body.split(d) if body else []
                    yield Row(index, raw, line=start_line)
                    index += 1
                    continue
                # Slow path: quoted fields, possibly spanning several physical lines.
                fields: list[str] = []
                quoted: set[int] = set()
                i = 0
                end = len(line) - len(term)
                extra_lines = 0
                while True:
                    if line.startswith(q, i) and i < end:
                        parts: list[str] = []
                        i += 1
                        closed = True
                        while True:
                            j = line.find(q, i)
                            if j < 0:
                                parts.append(line[i:])
                                nxt = next(it, None)
                                if nxt is None:
                                    closed = False
                                    stats["unterminated"] += 1
                                    i = end = len(line)
                                    break
                                lineno += 1
                                extra_lines += 1
                                line = nxt
                                if line.endswith("\r\n"):
                                    term = "\r\n"
                                elif line.endswith("\n"):
                                    term = "\n"
                                elif line.endswith("\r"):
                                    term = "\r"
                                else:
                                    term = ""
                                last_term = term
                                if term:
                                    newlines[term] += 1
                                end = len(line) - len(term)
                                i = 0
                                continue
                            if line.startswith(q, j + 1):
                                parts.append(line[i:j + 1])
                                i = j + 2
                                continue
                            parts.append(line[i:j])
                            i = j + 1
                            break
                        k = line.find(d, i) if closed else end
                        if k < 0 or k > end:
                            k = end
                        val = "".join(parts)
                        if closed and k > i:
                            val += line[i:k]
                            stats["stray"] += 1
                        quoted.add(len(fields))
                        fields.append(val)
                        i = k
                    else:
                        k = line.find(d, i)
                        if k < 0 or k > end:
                            k = end
                        fields.append(line[i:k])
                        i = k
                    if i < end and line.startswith(d, i):
                        i += len(d)
                        continue
                    break
                if extra_lines:
                    stats["multiline"] += 1
                yield Row(index, fields, line=start_line, quoted=frozenset(quoted))
                index += 1
        self.info.update(
            newlines={{"\r\n": "crlf", "\n": "lf", "\r": "cr"}[k]: v for k, v in newlines.items()},
            records=index, physical_lines=lineno, unterminated_quote=stats["unterminated"],
            text_after_closing_quote=stats["stray"], multiline_records=stats["multiline"],
            final_newline=bool(last_term) if lineno else None,
        )
