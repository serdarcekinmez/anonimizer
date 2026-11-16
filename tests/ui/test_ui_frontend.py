"""Runs the interface script against the real local server, in an embedded JavaScript engine.

This is not a browser test: layout and real DOM behaviour are not covered. It does prove that
the script parses, that every step's code path runs against real server answers, and that the
page shows what the engine returned.
"""

from __future__ import annotations

import json
import os
import threading

import pytest

from anonimizer.ui.server import make_server
from tests.conftest import product_path
from tests.ui.test_ui_server import Client

quickjs = pytest.importorskip("quickjs")
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(os.path.dirname(os.path.dirname(HERE)), "src", "anonimizer", "ui", "static")


def _run(ctx):
    for _ in range(100000):
        if not ctx.execute_pending_job():
            break


@pytest.fixture()
def page():
    server, token, session = make_server(0, quiet=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = Client(server.server_address[1], token)
    ctx = quickjs.Context()

    def py_fetch(path, method, body):
        if method == "GET":
            res, payload = client.request("GET", path)
        else:
            res, payload = client.request("POST", path, raw=None if body in (None, "null") else body.encode(),
                                          headers={"Content-Type": "application/json"})
        return json.dumps({"status": res.status, "body": json.loads(payload or b"{}")})

    ctx.add_callable("__py_fetch", py_fetch)
    with open(os.path.join(HERE, "dom_stub.js"), encoding="utf-8") as fh:
        ctx.eval(fh.read())
    with open(os.path.join(STATIC, "app.js"), encoding="utf-8") as fh:
        ctx.eval(fh.read())
    _run(ctx)
    try:
        yield ctx
    finally:
        server.shutdown()
        server.server_close()
        session.cleanup()


def _click(ctx, button):
    ctx.eval(f"__click({json.dumps(button)})")
    _run(ctx)


def test_script_drives_the_whole_workflow(page):
    ctx = page
    assert "not a certification" in ctx.eval("__text('statement')")
    ctx.eval(f"document.getElementById('path').value = {json.dumps(product_path('inventory_mixed.xlsx'))}")
    _click(ctx, "btn-open")
    assert ctx.eval("__text('msg')") == ""
    assert "XLSX" in ctx.eval("__text('file-facts')") and "1 hidden" in ctx.eval("__text('file-facts')")
    assert ctx.eval("__count('#regions [data-i]')") == 5 * 8  # five regions, eight editable fields each
    assert ctx.eval("document.getElementById('s-regions').hidden") is False
    # Profiling without a policy is refused on the page itself.
    _click(ctx, "btn-profile")
    assert "Choose a privacy policy" in ctx.eval("__text('msg')")
    # Rename a region, apply, choose a policy, profile.
    ctx.eval("document.querySelectorAll('#regions [data-i]').filter((n) => n.dataset.k === 'name')[1].value = 'stock'")
    _click(ctx, "btn-recipe")
    assert ctx.eval("__text('msg')") == ""
    ctx.eval("document.getElementById('policies').walk([]).filter((n) => n.name === 'policy')[0].checked = true")
    _click(ctx, "btn-profile")
    assert ctx.eval("__text('msg')") == ""
    report = ctx.eval("__text('report')")
    for expected in ("Exception Catalogue", "spreadsheet error value", "number stored as text", "stock", "Suppliers",
                     "reference value with no match"):
        assert expected in report
    contract = ctx.eval("__text('contract')")
    assert "unit_price" in contract and "Scenarios to generate" in contract
    assert "Not confirmed yet" in ctx.eval("__text('contract-state')")
    # Classify the unreviewed columns, confirm, generate.
    ctx.eval("document.querySelectorAll('#contract [data-c]').filter((n) => n.dataset.k === 'sensitivity' && n.value === 'unreviewed')"
             ".forEach((n) => { n.value = 'non_sensitive'; })")
    ctx.eval("document.getElementById('confirm-by').value = 'Front-end Tester'")
    _click(ctx, "btn-contract")
    assert ctx.eval("__text('msg')") == ""
    assert "Confirmed by Front-end Tester" in ctx.eval("__text('contract-state')")
    ctx.eval("document.getElementById('rows').value = '30'; document.getElementById('seed').value = '4';"
             "document.getElementById('packing').value = 'auto'")
    _click(ctx, "btn-generate")
    assert ctx.eval("__text('msg')") == ""
    result = ctx.eval("__text('result')")
    for expected in ("Release tier: RESTRICTED", "Scenario Manifest", "Scenario coverage", "Before / after",
                     "Preview of synthetic.xlsx", "singling out", "CLASSIFICATION.txt", "formulas are inventoried only"):
        assert expected in result
    for leaked in ("Quuxinator", "Fixture Author", "SKU-10000", "Widget blue"):
        assert leaked not in result and leaked not in report and leaked not in contract


def test_errors_are_shown_not_swallowed(page):
    ctx = page
    ctx.eval("document.getElementById('path').value = '/definitely/not/here.csv'")
    _click(ctx, "btn-open")
    assert "not an existing file" in ctx.eval("__text('msg')")
    assert ctx.eval("document.getElementById('msg').children[0].className") == "err"
