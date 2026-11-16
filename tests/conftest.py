"""Shared fixtures. All data used by the tests is synthetic and built by scripts in tests/fixtures."""

from __future__ import annotations

import json
import os
import socket
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
PRODUCT = os.path.join(FIXTURES, "product")
PARSER = os.path.join(FIXTURES, "parser")
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, FIXTURES)

PRODUCT_FILES = ["customers_hidden.csv", "orders_multi.tsv", "inventory_mixed.xlsx"]


def pytest_addoption(parser):
    parser.addoption("--runslow", action="store_true", default=False, help="run large-file checks")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runslow"):
        return
    skip = pytest.mark.skip(reason="needs --runslow")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _no_outbound_network(monkeypatch):
    """Any connection to a non-loopback address fails the test."""
    real_connect = socket.socket.connect

    def guarded(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError("outbound network connection attempted during tests")
        return real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture(autouse=True)
def _private_register(tmp_path, monkeypatch):
    monkeypatch.setenv("ANONIMIZER_REGISTER", str(tmp_path / "register" / "release_register.jsonl"))


@pytest.fixture(scope="session")
def truths() -> dict:
    out = {}
    for name in PRODUCT_FILES:
        with open(os.path.join(PRODUCT, name + ".truth.json"), encoding="utf-8") as fh:
            out[name] = json.load(fh)
    return out


@pytest.fixture(scope="session")
def profiles() -> dict:
    from anonimizer.profile import build_profile

    return {name: build_profile(os.path.join(PRODUCT, name)) for name in PRODUCT_FILES}


def product_path(name: str) -> str:
    return os.path.join(PRODUCT, name)


def parser_path(name: str) -> str:
    return os.path.join(PARSER, name)


def confirm_all(contract: dict, name: str = "Test Reviewer") -> None:
    """Give every unreviewed column a class and confirm, as a reviewer would."""
    from anonimizer.contract import confirm_contract

    for t in contract["tables"]:
        for c in t["columns"]:
            if c["sensitivity"]["class"] == "unreviewed":
                c["sensitivity"]["class"] = "non_sensitive"
    confirm_contract(contract, name)


def read_bundle_texts(out_dir: str) -> dict[str, str]:
    """Every exported file as text (XLSX parts are unzipped)."""
    import zipfile

    texts = {}
    for name in sorted(os.listdir(out_dir)):
        path = os.path.join(out_dir, name)
        if name.endswith(".xlsx"):
            with zipfile.ZipFile(path) as z:
                for part in z.namelist():
                    texts[f"{name}!{part}"] = z.read(part).decode("utf-8", errors="replace")
        else:
            with open(path, "rb") as fh:
                raw = fh.read()
            for enc in ("utf-8", "cp1252"):
                try:
                    texts[name] = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
    return texts
