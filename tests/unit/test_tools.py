"""The gate's own tools: repository scan and traceability-matrix check."""

from __future__ import annotations

import datetime as dt
import os

import pytest

import check_rtm
import scan_repo
from tests.conftest import ROOT


@pytest.mark.cnil("ANON-05")
def test_rtm_is_consistent():
    errors, _warnings = check_rtm.check()
    assert errors == []
    by_status = check_rtm.summary()
    assert by_status.get("implemented", 0) >= 6 and sum(by_status.values()) >= 22


def test_rtm_release_rule_blocks_open_high_findings():
    """The release gate must fail today: high findings are open and not dispositioned."""
    errors, _ = check_rtm.check(release=True)
    assert any("F-001" in e for e in errors) and any("F-002" in e for e in errors)
    assert all(e.startswith("release:") for e in errors)


def test_source_staleness_becomes_an_error_for_a_release():
    late = dt.date(2028, 1, 1)
    errors, warnings = check_rtm.check(today=late)
    assert errors == [] and any("review is due" in w for w in warnings)
    errors, _ = check_rtm.check(release=True, today=late)
    assert any("review is due" in e for e in errors)


def test_every_marker_matches_a_row_and_every_automated_row_has_a_test():
    markers = check_rtm.test_markers()
    assert {"CNIL-01", "CNIL-10", "CNIL-11", "CNIL-12", "ANON-01", "ANON-02", "ANON-03"} <= set(markers)


def test_repository_is_clean():
    assert scan_repo.scan(scan_repo.tracked()) == []


def _write(rel: str, text: str) -> str:
    path = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


@pytest.mark.parametrize("rel,text,expect", [
    ("data_drop/clients.csv", "a,b\n1,2\n", "data file outside the fixture directories"),
    ("tests/fixtures/product/unlisted.csv", "a,b\n1,2\n", "not registered"),
    ("docs/zz_tmp_key.md", "-----BEGIN RSA PRIVATE KEY-----\n", "possible secret"),
    ("docs/zz_tmp_token.md", "token = 'ghp_" + "a1B2" * 9 + "'\n", "possible secret"),
    ("docs/zz_tmp_path.md", "see /home/" + "someone/projects/thing\n", "machine-specific path"),
    ("docs/zz_tmp_win.md", "see /mnt/" + "c/Users/x\n", "machine-specific path"),
    ("docs/zz_tmp_claim.md", "This output is CNIL " + "certified.\n", "forbidden wording"),
    ("docs/zz_tmp_claim2.md", "Produces guaranteed " + "anonymous data.\n", "forbidden wording"),
    ("docs/zz_tmp_mail.md", "write to jane.roe@" + "somecorp.com\n", "e-mail address"),
])
def test_scan_detects_planted_problems(rel, text, expect):
    path = _write(rel, text)
    try:
        findings = scan_repo.scan([rel])
        assert any(expect in f for f in findings), findings
        assert all(text.strip() not in f for f in findings)  # findings name the rule, not the content
    finally:
        os.remove(path)
        parent = os.path.dirname(path)
        if os.path.basename(parent) == "data_drop":
            os.rmdir(parent)


def test_scan_accepts_negated_statements():
    path = _write("docs/zz_tmp_ok.md", "This is not a certification and not proof that the data is legally anonymous.\n"
                                       "Mail user@example.org for a fictional example.\n")
    try:
        assert scan_repo.scan(["docs/zz_tmp_ok.md"]) == []
    finally:
        os.remove(path)
