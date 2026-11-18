"""The product runs with networking removed entirely."""

from __future__ import annotations

import socket
import subprocess
import sys

import pytest

from anonimizer.pipeline import run
from tests.conftest import PRODUCT_FILES, product_path


@pytest.mark.parametrize("name", PRODUCT_FILES)
def test_full_run_with_sockets_disabled(name, tmp_path, monkeypatch):
    def no_socket(*a, **k):
        raise AssertionError("a socket was created during an offline run")

    monkeypatch.setattr(socket, "socket", no_socket)
    monkeypatch.setattr(socket, "create_connection", no_socket)
    monkeypatch.setattr(socket, "getaddrinfo", no_socket)
    res = run(product_path(name), policy_id="internal-dev", rows=40, seed=1, out_dir=str(tmp_path / "o"))
    assert res.assessment["assessment_status"] == "passed"


def test_engine_import_loads_no_network_client():
    code = ("import sys, anonimizer.pipeline, anonimizer.cli\n"
            "bad = sorted(m for m in ('urllib.request', 'http.client', 'requests', 'httpx', 'ssl', 'ftplib', 'smtplib')"
            " if m in sys.modules)\n"
            "print(','.join(bad))\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "", out.stdout


def test_cli_runs_in_a_subprocess_without_network(tmp_path):
    code = ("import socket, sys\n"
            "def no(*a, **k): raise RuntimeError('network')\n"
            "socket.socket = no\n"
            "from anonimizer.cli import main\n"
            "sys.exit(main(sys.argv[1:]))\n")
    out = subprocess.run([sys.executable, "-c", code, "generate", product_path("orders_multi.tsv"), "--policy",
                          "internal-dev", "-n", "25", "--out", str(tmp_path / "o")], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert (tmp_path / "o" / "synthetic.tsv").exists()
