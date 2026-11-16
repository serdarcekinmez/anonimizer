"""Canary tests: planted source values must not appear in anything the tool exports or prints."""

from __future__ import annotations

import json
import os
import stat

import pytest

from anonimizer.cli import main
from anonimizer.pipeline import run
from tests.conftest import PRODUCT_FILES, confirm_all, product_path, read_bundle_texts

# Source values that would be damaging to see in an output. Canaries come from the truth files;
# the others are ordinary source values of identifier-like columns.
EXTRA_SOURCE_VALUES = {
    "customers_hidden.csv": ["Prefers contact by email", "100001", "Asked for a paper invoice"],
    "orders_multi.tsv": ["ORD-000001", "livraison différée", "C-0001", "Ventoux", "région Ouest", "comptabilité"],
    "inventory_mixed.xlsx": ["SKU-10000", "Widget blue", "Inventory snapshot", "Fixture Author", "D4*E4", "StockRange",
                             "Checked by the fixture builder"],
}
FORBIDDEN_CLAIMS = ["certified", "cnil compliant", "cnil-compliant", "guaranteed anonymous", "fully anonymous",
                    "gdpr compliant", "anonymized data", "anonymised data"]


def _canaries(name, truths):
    return [c for c in truths[name]["canaries"] if len(c) >= 5] + EXTRA_SOURCE_VALUES[name]


@pytest.mark.cnil("ANON-01")
@pytest.mark.cnil("ANON-03")
@pytest.mark.parametrize("policy", ["internal-dev", "external-strict"])
@pytest.mark.parametrize("name", PRODUCT_FILES)
def test_no_source_value_in_any_exported_file(name, policy, truths, tmp_path):
    out = str(tmp_path / "out")
    res = run(product_path(name), policy_id=policy, rows=80, seed=5, out_dir=out)
    texts = read_bundle_texts(out)
    assert len(texts) >= 12
    for canary in _canaries(name, truths):
        for fname, text in texts.items():
            assert canary not in text, f"{canary!r} leaked into {fname}"
    assert res.assessment["criteria"]["source_leakage"]["status"] == "passed"


@pytest.mark.cnil("ANON-03")
@pytest.mark.parametrize("name", PRODUCT_FILES)
def test_cli_output_and_errors_carry_no_source_value(name, truths, tmp_path, capsys):
    path = product_path(name)
    assert main(["inspect", path, "--recipe-out", str(tmp_path / "r.json")]) == 0
    assert main(["profile", path, "--policy", "internal-dev", "--out", str(tmp_path / "p")]) == 0
    assert main(["contract", path, "--policy", "internal-dev", "-o", str(tmp_path / "c.json")]) == 0
    assert main(["generate", path, "--policy", "internal-dev", "-n", "40", "--out", str(tmp_path / "g")]) == 0
    # A failing run: a contract that is not valid JSON, then a refused tier.
    (tmp_path / "bad.json").write_text("{")
    assert main(["generate", path, "--policy", "internal-dev", "-n", "5", "--out", str(tmp_path / "g2"),
                 "--contract", str(tmp_path / "bad.json")]) == 2
    assert main(["generate", path, "--policy", "internal-dev", "-n", "5", "--out", str(tmp_path / "g3"),
                 "--tier", "RESTRICTED"]) == 4
    captured = capsys.readouterr()
    printed = captured.out + captured.err
    for extra in ("r.json", "c.json", os.path.join("p", "source_report.json")):
        printed += (tmp_path / extra).read_text(encoding="utf-8")
    for canary in _canaries(name, truths):
        assert canary not in printed


@pytest.mark.cnil("ANON-03")
def test_unexpected_errors_do_not_print_their_message(tmp_path, capsys, monkeypatch):
    import anonimizer.pipeline as pipeline

    def boom(*a, **k):
        raise ValueError("invalid literal for int() with base 10: 'Wolfhaven77'")

    monkeypatch.setattr(pipeline, "run", boom)
    code = main(["generate", product_path("customers_hidden.csv"), "--policy", "internal-dev", "-n", "5",
                 "--out", str(tmp_path / "o")])
    err = capsys.readouterr().err
    assert code == 70 and "Wolfhaven77" not in err and "ValueError" in err


@pytest.mark.cnil("ANON-03")
def test_private_profile_is_kept_apart_and_owner_only(tmp_path, truths):
    out, priv = str(tmp_path / "out"), str(tmp_path / "private")
    res = run(product_path("customers_hidden.csv"), policy_id="internal-dev", rows=30, seed=1, out_dir=out,
              private_dir=priv)
    assert not any("PRIVATE" in f for f in os.listdir(out))
    ppath = res.private_files[0]
    assert os.path.dirname(ppath) == priv
    assert stat.S_IMODE(os.stat(ppath).st_mode) == 0o600
    private = json.load(open(ppath, encoding="utf-8"))
    assert private["view"] == "private" and "_private" in json.dumps(private)
    for f in os.listdir(out):
        assert stat.S_IMODE(os.stat(os.path.join(out, f)).st_mode) == 0o600


@pytest.mark.cnil("CNIL-03")
@pytest.mark.parametrize("name", PRODUCT_FILES)
def test_no_certification_or_anonymity_claim_in_outputs(name, tmp_path):
    from anonimizer.contract import build_contract
    from anonimizer.pipeline import profile_source
    from anonimizer.policy import get_policy
    from anonimizer.recipe import ParseRecipe

    pol = get_policy("internal-dev")
    private, share = profile_source(product_path(name), ParseRecipe(), pol)
    contract = build_contract(share, pol)
    confirm_all(contract)
    out = str(tmp_path / "out")
    res = run(product_path(name), policy_id="internal-dev", rows=40, seed=5, out_dir=out, contract=contract)
    assert res.assessment["release_tier"] == "RESTRICTED"
    texts = read_bundle_texts(out)
    for fname, text in texts.items():
        low = text.lower()
        for claim in FORBIDDEN_CLAIMS:
            assert claim not in low, f"{claim!r} in {fname}"
    for fname in ("report.md", "CLASSIFICATION.txt", "assessment_record.json", "release_label.json"):
        assert "not a certification" in texts[fname]
        assert "not proof that the data is legally anonymous" in texts[fname]
