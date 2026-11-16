"""Property-based tests."""

from __future__ import annotations

import string

import pytest
from build_fixtures import csv_line
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from anonimizer.contract import build_contract
from anonimizer.grid import open_source
from anonimizer.patterns import NUM, V, classify, generalize_shape, shape_of
from anonimizer.policy import get_policy
from anonimizer.profile import build_profile, to_shareable
from anonimizer.synth import Rng, _shape_text, _TableGen, generate
from tests.conftest import product_path

FIELD = st.text(alphabet=string.ascii_letters + string.digits + ' ,;"\n\t.-', max_size=12)
SETTINGS = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])


@SETTINGS
@given(rows=st.lists(st.lists(FIELD, min_size=2, max_size=5), min_size=1, max_size=8),
       delim=st.sampled_from([",", ";", "\t", "|"]), data=st.data())
def test_csv_reader_returns_exactly_what_was_written(tmp_path, rows, delim, data):
    """Field text and the quoted-empty distinction survive any mix of quotes, delimiters and newlines."""
    for r in rows:
        assume(not r[0].startswith('"') or True)
    force = [data.draw(st.sets(st.integers(0, len(r) - 1), max_size=2)) for r in rows]
    path = tmp_path / "p.csv"
    text = "\n".join(csv_line(r, delim, f) for r, f in zip(rows, force)) + "\n"
    path.write_bytes(text.encode("utf-8"))
    got = list(open_source(str(path), delimiter=delim).rows())
    assert len(got) == len(rows)
    for row, expected, f in zip(got, rows, force):
        assert row.raw == expected
        for i in f:
            assert i in row.quoted
        for i, v in enumerate(expected):
            if v == "":
                assert row.cell(i).empty_kind == ("quoted_empty" if i in f else "empty")


@settings(max_examples=400, deadline=None)
@given(s=st.text(max_size=40))
def test_classify_is_total_and_deterministic(s):
    for stype in ("text", "number", "shared_string", "boolean", "error", "iso_date"):
        v = classify(s, stype, False, None)
        assert isinstance(v, V) and v == classify(s, stype, False, None)
    assert sum(n for _c, n in shape_of(s)) == len(s)


@settings(max_examples=300, deadline=None)
@given(s=st.text(alphabet=string.ascii_letters + string.digits + " -_/.#", min_size=1, max_size=30), seed=st.integers(0, 10**6))
def test_generated_text_has_the_requested_layout_and_never_the_source_letters(s, seed):
    shape = shape_of(s)
    out = _shape_text(shape, Rng("p", seed))
    assert shape_of(out) == shape and len(out) == len(s)
    g = generalize_shape(shape)
    out2 = _shape_text(g, Rng("p", seed))
    assert generalize_shape(shape_of(out2)) == g or len(g) != len(generalize_shape(shape_of(out2)))


@pytest.fixture(scope="module")
def customers_contract():
    pol = get_policy("internal-dev")
    return build_contract(to_shareable(build_profile(product_path("customers_hidden.csv")), pol), pol)


@SETTINGS
@given(n=st.integers(1, 90), seed=st.integers(0, 10**9), packing=st.sampled_from(["auto", "isolate", "packed"]))
def test_generation_invariants(customers_contract, n, seed, packing):
    ds = generate(customers_contract, n, seed=seed, packing=packing)
    cov = ds["coverage"]["tables"][0]
    data = [r for r in ds["tables"]["table_1"]["rows"] if r["kind"] == "data"]
    assert len(data) == n == cov["generated_data_rows"]
    assert len(cov["covered"]) + len(cov["uncovered"]) == cov["scenarios_total"]
    assert {m["scenario_id"] for m in ds["manifest"]} == set(cov["covered"])
    for m in ds["manifest"]:
        assert all(1 <= r <= n for r in m["data_rows"])
    need = cov["n_min_isolated"] if packing == "isolate" else cov["n_min_packed"]
    if n >= need + 1:
        assert cov["full_coverage_of_reproducible"]
    if cov["full_coverage"]:
        assert not cov["uncovered"]
    assert generate(customers_contract, n, seed=seed, packing=packing)["manifest"] == ds["manifest"]


NUMBER_FORMATS = ["int", "dec_dot", "dec_comma", "thou_comma_dec_dot", "thou_dot_dec_comma", "thou_space_dec_comma",
                  "sci", "int|{n}%", "dec_comma|{n} €", "dec_dot|${n}", "int|({n})"]


@settings(max_examples=300, deadline=None)
@given(fmt=st.sampled_from(NUMBER_FORMATS), idig=st.integers(1, 9), ddig=st.integers(1, 4), seed=st.integers(0, 10**6),
       neg=st.booleans())
def test_generated_numbers_read_back_in_the_same_format(fmt, idig, ddig, seed, neg):
    tab = {"name": "t", "columns": [{"id": "c1", "keep": True, "base_gen": {"g": "number", "fmt": fmt},
                                     "key": {"role": "none"}, "missing": []}]}
    tg = _TableGen(tab, "csv", seed, {})
    gen = {"g": "number", "fmt": fmt, "int_digits": {str(idig): 1}, "dec_digits": {str(ddig): 1}}
    cell = tg.value(gen, tg.cols[0], {"neg": True, "_scenario": True} if neg else {"_scenario": True})
    v = classify(cell.text)
    assert v.family == NUM
    base = fmt.split("|")[0]
    assert v.sub.split("|")[0] in (base, "comma_ambiguous") or (base.startswith("thou") and v.sub.split("|")[0].startswith(("thou", "comma")))
    assert v.sub.partition("|")[2] == fmt.partition("|")[2]


DATE_FORMATS = ["Y-M-D", "D/M/Y", "M/D/Y", "X/X/Y", "D.M.Y", "D-M-Y", "Y/M/D", "D-b-Y", "D B Y", "b D, Y",
                "Y-M-DTh:m:s", "Y-M-D h:m", "Y-M-DTh:m:sZ", "D/M/Y h:m", "h:m", "h:m:s"]


@settings(max_examples=300, deadline=None)
@given(fmt=st.sampled_from(DATE_FORMATS), seed=st.integers(0, 10**6), invalid=st.booleans())
def test_generated_dates_read_back_as_dates(fmt, seed, invalid):
    from anonimizer.patterns import DATE, INVALID

    tab = {"name": "t", "columns": [{"id": "c1", "keep": True, "base_gen": {"g": "date", "fmt": fmt},
                                     "key": {"role": "none"}, "missing": []}]}
    tg = _TableGen(tab, "csv", seed, {})
    time_only = fmt in ("h:m", "h:m:s")
    cell = tg.value({"g": "date", "fmt": fmt, "year_min": 1990, "year_max": 2030, "invalid": invalid and not time_only},
                    tg.cols[0], {"_scenario": True})
    v = classify(cell.text)
    assert v.family == DATE, cell.text
    if not time_only:
        assert bool(v.flags & INVALID) is invalid, cell.text
    if not invalid and not fmt.startswith("X"):
        got = v.sub.replace("e", "B" if "B" in fmt else "b") if not v.sub.startswith("excel") else v.sub
        assert got == fmt or (fmt.startswith("D/M/") and v.sub.startswith(("D/M/", "X/X/")))
