"""Same contract and seed: identical bytes. Different seed: different data, same guarantees."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

import pytest

from anonimizer.contract import build_contract
from anonimizer.export import render_dataset
from anonimizer.pipeline import run
from anonimizer.policy import get_policy
from anonimizer.profile import build_profile, to_shareable
from anonimizer.synth import Rng, generate
from tests.conftest import PRODUCT_FILES, product_path


def _bytes(name, seed, rows=50):
    pol = get_policy("internal-dev")
    contract = build_contract(to_shareable(build_profile(product_path(name)), pol), pol)
    ds = generate(contract, rows, seed=seed)
    data, _ext, _recipe = render_dataset(contract, ds)
    return data, json.dumps(ds["manifest"], sort_keys=True), json.dumps(contract, sort_keys=True)


@pytest.mark.parametrize("name", PRODUCT_FILES)
def test_same_seed_gives_identical_bytes(name):
    a, b = _bytes(name, 7), _bytes(name, 7)
    assert a[0] == b[0] and a[1] == b[1] and a[2] == b[2]


@pytest.mark.parametrize("name", PRODUCT_FILES)
def test_different_seed_gives_different_data(name):
    assert _bytes(name, 7)[0] != _bytes(name, 8)[0]


def test_seed_may_be_text():
    assert _bytes("customers_hidden.csv", "release-2026-11")[0] == _bytes("customers_hidden.csv", "release-2026-11")[0]


def test_output_does_not_depend_on_hash_randomisation(tmp_path):
    """Profiling uses Python's salted string hashes internally; the result must not depend on the salt."""
    code = (
        "import hashlib, json, sys\n"
        "from anonimizer.pipeline import run\n"
        "r = run(sys.argv[1], policy_id='internal-dev', rows=40, seed=3, out_dir=sys.argv[2])\n"
        "d = open(sys.argv[2] + '/' + r.export['dataset_file'], 'rb').read()\n"
        "print(hashlib.sha256(d).hexdigest(), hashlib.sha256(json.dumps(r.contract, sort_keys=True).encode()).hexdigest())\n"
    )
    digests = set()
    for i, salt in enumerate(("0", "1", "4242")):
        env = dict(os.environ, PYTHONHASHSEED=salt)
        for name in ("orders_multi.tsv", "inventory_mixed.xlsx"):
            out = subprocess.run([sys.executable, "-c", code, product_path(name), str(tmp_path / f"{i}{name}")],
                                 capture_output=True, text=True, env=env, check=True)
            digests.add((name, out.stdout.strip()))
    assert len(digests) == 2


def test_rng_is_stable_across_python_versions():
    """Pinned values: a change here would silently change every user's seeded output."""
    r = Rng("anonimizer", 1, 0, "table_1")
    assert [r.below(1000) for _ in range(5)] == [r2 for r2 in _PINNED]
    assert hashlib.sha256(_bytes("customers_hidden.csv", 0, 25)[0]).hexdigest() == _PINNED_SHA


def test_full_run_is_repeatable(tmp_path):
    a = run(product_path("inventory_mixed.xlsx"), policy_id="internal-dev", rows=30, seed=5, out_dir=str(tmp_path / "a"))
    b = run(product_path("inventory_mixed.xlsx"), policy_id="internal-dev", rows=30, seed=5, out_dir=str(tmp_path / "b"))
    for f in ("synthetic.xlsx", "scenario_manifest.json", "coverage_report.json", "contract.json", "comparison.json",
              "source_report.json", "generated_report.json", "recipe.json", "report.md", "scenario_manifest.csv"):
        assert (tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes(), f
    assert a.assessment["record_id"] == b.assessment["record_id"]


_PINNED = [381, 171, 337, 208, 555]
_PINNED_SHA = "4a5ea055c5afb70ccb68e8ca7f13eb4a19ba8e3a0ae2972e747e7be3a9535d98"
