"""Value classification: the distinctions the product promises to keep apart."""

from __future__ import annotations

import pytest

from anonimizer.patterns import (
    AMBIG,
    BOOLEAN,
    DATE,
    FORMULA_LIKE,
    INVALID,
    LEADZERO,
    MISSING,
    MULTILINE,
    NEG,
    NONASCII,
    NUM,
    PAD_LEAD,
    PAD_TRAIL,
    TXT,
    ZERO,
    classify,
    generalize_shape,
    shape_display,
    shape_of,
)


@pytest.mark.parametrize("raw,quoted,sub", [
    (None, False, "absent"), ("", False, "empty"), ("", True, "quoted_empty"), ("   ", False, "whitespace"),
    ("\t", False, "whitespace"), ("N/A", False, "marker:N/A"), ("nan", False, "marker:nan"),
    ("NULL", False, "marker:NULL"), ("-", False, "marker:-"), ("#DIV/0!", False, "marker:#DIV/0!"),
])
def test_missing_kinds(raw, quoted, sub):
    v = classify(raw, "text", quoted)
    assert v.family == MISSING and v.sub == sub


def test_zero_is_a_number_not_a_missing_value():
    for raw in ("0", "0.00", "0,0", "-0"):
        v = classify(raw)
        assert v.family == NUM and v.flags & ZERO
    assert not classify("10").flags & ZERO and not classify("0.5").flags & ZERO


@pytest.mark.parametrize("raw,sub", [
    ("12", "int"), ("3.14", "dec_dot"), ("12,5", "dec_comma"), ("1,234.56", "thou_comma_dec_dot"),
    ("1.234,56", "thou_dot_dec_comma"), ("1 234,5", "thou_space_dec_comma"), ("1,234", "comma_ambiguous"),
    ("1e5", "sci"), ("45%", "int|{n}%"), ("12,50 €", "dec_comma|{n} €"), ("$5.00", "dec_dot|${n}"),
    ("(123)", "int|({n})"), ("1.234.567", "thou_dot"),
])
def test_number_formats(raw, sub):
    v = classify(raw)
    assert v.family == NUM and v.sub == sub


def test_number_flags():
    assert classify("-3.5").flags & NEG and classify("(12)").flags & NEG
    assert classify("007").flags & LEADZERO and not classify("0.7").flags & LEADZERO
    v = classify("  12 ")
    assert v.family == NUM and v.flags & PAD_LEAD and v.flags & PAD_TRAIL


@pytest.mark.parametrize("raw,sub,invalid", [
    ("2024-01-05", "Y-M-D", False), ("2024-02-30", "Y-M-D", True), ("2021-13-01", "Y-M-D", True),
    ("13/01/2024", "D/M/Y", False), ("01/13/2024", "M/D/Y", False), ("13/13/2024", "X/X/Y", True),
    ("31.12.2023", "D.M.Y", False), ("31.02.2023", "D.M.Y", True), ("12-Jan-2024", "D-b-Y", False),
    ("Jan 5, 2024", "b D, Y", False), ("2024-01-05T10:22:01Z", "Y-M-DTh:m:sZ", False), ("12:30", "h:m", False),
    ("29/02/2023", "D/M/Y", True), ("29/02/2024", "D/M/Y", False),
])
def test_dates(raw, sub, invalid):
    v = classify(raw)
    assert v.family == DATE and v.sub == sub and bool(v.flags & INVALID) is invalid


def test_ambiguous_day_month_is_flagged_not_guessed():
    v = classify("05/01/2024")
    assert v.sub == "X/X/Y" and v.flags & AMBIG


def test_things_that_are_not_dates_or_numbers():
    assert classify("1.2.3").family == TXT and classify("10.5.21").family == TXT
    assert classify("12 pts").family == TXT and classify("abc").family == TXT
    assert classify("pending review").sub == "words"


def test_booleans_and_text_kinds():
    assert classify("TRUE").sub == "true_false:upper" and classify("oui").family == BOOLEAN
    assert classify("jo@example.org").sub == "email" and classify("AB-1234").sub == "code"
    assert classify("+33 6 12 34 56 78").sub == "phone" and not classify("+33 6 12 34 56 78").flags & FORMULA_LIKE
    assert classify("=SUM(A1)").flags & FORMULA_LIKE
    assert classify("Zoë").flags & NONASCII and classify("a\nb").flags & MULTILINE


def test_xlsx_storage_types_drive_classification():
    assert classify("45296", "number", number_format="yyyy-mm-dd").family == DATE
    assert classify("45296", "number", number_format="yyyy-mm-dd").a == 2024
    assert classify("45296", "number").family == NUM
    assert classify("1", "boolean").family == BOOLEAN
    assert classify("#N/A", "error").family == "error"
    assert classify("15", "shared_string").family == NUM  # number stored as text keeps its storage type
    v = classify("97.01000000000001", "number")
    assert v.family == NUM and v.b == 2  # binary float artefact is not counted as 14 decimals


def test_extra_markers_from_the_recipe():
    assert classify("sans objet").family == TXT
    assert classify("sans objet", markers=frozenset({"sans objet"})).family == MISSING


def test_shapes_never_contain_letters_or_digits_of_the_value():
    s = "Wolfhaven77-QX"
    shape = shape_of(s)
    assert sum(n for _c, n in shape) == len(s)
    shown = shape_display(shape) + shape_display(generalize_shape(shape))
    assert "Wolf" not in shown and "77" not in shown and "QX" not in shown
    assert generalize_shape(shape_of("Pending"))[0][0] == "C"
