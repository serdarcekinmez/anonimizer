"""Runs the interface script against the real local server, in an embedded JavaScript engine.

This is not a browser test: layout and real DOM behaviour are not covered. It does prove that
the script parses, that every step's code path runs against real server answers, and that the
page shows what the engine returned.
"""

from __future__ import annotations

import json
import os
import re
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
    # Five regions: use, name and kind on each card; five row and column numbers in the technical details.
    assert ctx.eval("__count('#region-cards [data-i]')") == 5 * 3 and ctx.eval("__count('#regions [data-i]')") == 5 * 5
    assert ctx.eval("document.getElementById('s-regions').hidden") is False
    # Profiling without a policy is refused on the page itself.
    _click(ctx, "btn-profile")
    assert "Choose a privacy policy" in ctx.eval("__text('msg')")
    # Rename a region, apply, choose a policy, profile.
    ctx.eval("document.querySelectorAll('#region-cards [data-i]').filter((n) => n.dataset.k === 'name')[1].value = 'stock'")
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


def _hidden(ctx, node_id):
    return ctx.eval(f"document.getElementById({json.dumps(node_id)}).hidden")


def test_unapplied_form_changes_are_never_used_silently(page):
    ctx = page
    ctx.eval(f"document.getElementById('path').value = {json.dumps(product_path('customers_hidden.csv'))}")
    _click(ctx, "btn-open")
    ctx.eval("document.getElementById('policies').walk([]).filter((n) => n.name === 'policy')[0].checked = true")
    _click(ctx, "btn-profile")
    ctx.eval("document.getElementById('rows').value = '20'; document.getElementById('seed').value = '1';"
             "document.getElementById('packing').value = 'auto'")
    _click(ctx, "btn-generate")
    assert ctx.eval("__text('msg')") == "" and _hidden(ctx, "s-result") is False
    assert "Done: synthetic.csv was generated" in ctx.eval("__text('result')")
    # A changed generation setting withdraws the result that no longer matches it.
    ctx.eval("__fire('gen-settings', 'input')")
    assert _hidden(ctx, "s-result") is True and ctx.eval("__text('result')") == ""
    assert "withdrawn" in ctx.eval("__text('msg')")
    _click(ctx, "btn-generate")
    assert _hidden(ctx, "s-result") is False
    # An edited contract form blocks generation until it is applied.
    ctx.eval("__fire('contract', 'change')")
    assert _hidden(ctx, "s-result") is True and "Unapplied changes" in ctx.eval("__text('contract-state')")
    _click(ctx, "btn-generate")
    assert "unapplied changes" in ctx.eval("__text('msg')") and _hidden(ctx, "s-result") is True
    _click(ctx, "btn-contract")
    assert "Unapplied changes" not in ctx.eval("__text('contract-state')")
    _click(ctx, "btn-generate")
    assert ctx.eval("__text('msg')") == "" and _hidden(ctx, "s-result") is False
    # Edited table settings withdraw every later step and block profiling until applied.
    ctx.eval("__fire('s-regions', 'input')")
    for section in ("s-report", "s-contract", "s-generate", "s-result"):
        assert _hidden(ctx, section) is True
    assert "Unapplied changes" in ctx.eval("__text('recipe-state')")
    _click(ctx, "btn-profile")
    assert "not applied" in ctx.eval("__text('msg')") and _hidden(ctx, "s-contract") is True
    _click(ctx, "btn-recipe")
    assert ctx.eval("__text('recipe-state')") == ""
    _click(ctx, "btn-profile")
    assert ctx.eval("__text('msg')") == "" and _hidden(ctx, "s-generate") is False
    # A changed policy withdraws the profile made under the previous one.
    ctx.eval("__fire('policies', 'change')")
    assert _hidden(ctx, "s-generate") is True and "analyse the file again" in ctx.eval("__text('msg')")


def test_first_screen_summary_layout_and_column_workspace(page, truths):
    ctx = page
    ctx.eval(f"document.getElementById('path').value = {json.dumps(product_path('orders_multi.tsv'))}")
    _click(ctx, "btn-open")
    assert ctx.eval("__text('msg')") == ""
    glance = ctx.eval("__text('glance')")
    # The summary states counts from the detection and says that nothing is confirmed or analysed yet.
    assert "4 region(s) found: 2 read as table(s), 2 read as note(s)" in glance
    assert "You have not confirmed any region yet" in glance and "have not been analysed yet" in glance
    assert "detected automatically" in ctx.eval("__text('region-cards')")
    # The layout of the first table is shown as cell kinds only.
    layout = ctx.eval("__text('layout')")
    assert "Layout of table_1" in layout and "header" in layout and "number" in layout and "date" in layout
    assert "values of your file are not sent to this page" in layout
    # Pressing the confirm button is what turns detections into confirmed regions; nothing is left out by it.
    _click(ctx, "btn-recipe")
    glance = ctx.eval("__text('glance')")
    assert "4 of 4 region(s) were confirmed or set by you" in glance and "left out" not in glance
    assert "confirmed by you" in ctx.eval("__text('region-cards')")
    ctx.eval("document.getElementById('policies').walk([]).filter((n) => n.name === 'policy')[0].checked = true")
    _click(ctx, "btn-profile")
    assert ctx.eval("__text('msg')") == ""
    glance = ctx.eval("__text('glance')")
    assert "Table table_1: 1200 rows, 7 columns" in glance and "kind(s) of exception were found" in glance
    assert "1 key reference(s) between tables" in glance
    assert "Rules that link several columns of one row are not detected and not preserved" in glance
    # The grid shows the columns of the selected table with synthetic sample rows; one column panel is open.
    sheet = ctx.eval("__text('sheet')")
    assert "order_no" in sheet and "amount_eur" in sheet and "synthetic examples" in sheet
    assert ctx.eval("__count('#sheet [data-c]')") == 0  # the grid holds no form control of its own
    assert ctx.eval("Object.values(state.panels).filter((p) => !p.hidden).length") == 1
    ctx.eval("selectColumn('table_1', 'c4')")
    assert ctx.eval("state.panels['table_1\\u0000c4'].hidden") is False
    assert "Column quantity of table_1" in ctx.eval("state.panels['table_1\\u0000c4'].textContent")
    # Bulk renaming only fills the name fields in; it must be applied like any other edit.
    ctx.eval("document.getElementById('bulk-style').value = 'upper'; document.getElementById('bulk-prefix').value = 'x_'")
    _click(ctx, "btn-bulk")
    assert "7 output name(s) of table_1 were filled in" in ctx.eval("__text('msg')")
    sheet = ctx.eval("__text('sheet')")
    assert "x_ORDER_NO" in sheet and "Press \"Apply decisions\" to see sample rows" in sheet
    assert "Unapplied changes" in ctx.eval("__text('contract-state')")
    _click(ctx, "btn-generate")
    assert "unapplied changes" in ctx.eval("__text('msg')") and _hidden(ctx, "s-result") is True
    # One column renamed by hand on top of the bulk change, then applied.
    ctx.eval("state.fields['table_1\\u0000c4'].name.value = 'qty'")
    _click(ctx, "btn-contract")
    assert ctx.eval("__text('msg')") == ""
    sheet = ctx.eval("__text('sheet')")
    assert "qty" in sheet and "x_AMOUNT_EUR" in sheet and "synthetic examples" in sheet
    ctx.eval("document.getElementById('rows').value = '25'; document.getElementById('seed').value = '2';"
             "document.getElementById('packing').value = 'auto'")
    _click(ctx, "btn-generate")
    assert ctx.eval("__text('msg')") == ""
    result = ctx.eval("__text('result')")
    assert "Done: synthetic.tsv was generated" in result and "Download synthetic.tsv" in result
    assert "x_ORDER_NO" in result and "qty" in result  # the output preview carries the applied names
    everything = " ".join(ctx.eval(f"__text('{i}')") for i in ("glance", "layout", "sheet", "contract", "report", "result"))
    for canary in truths["orders_multi.tsv"]["canaries"] + ["ORD-000001", "livraison", "Ventoux"]:
        assert canary not in everything


def test_every_element_the_script_looks_up_exists_in_the_page():
    # The test DOM creates elements on demand, so a misspelt id would pass there and fail in a browser.
    with open(os.path.join(STATIC, "app.js"), encoding="utf-8") as fh:
        script = fh.read()
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    declared = re.findall(r'\bid="([\w-]+)"', html)
    assert len(declared) == len(set(declared))
    looked_up = set(re.findall(r'\$\("([\w-]+)"\)', script)) | set(re.findall(r'(?:show|flag|onEdit)\("([\w-]+)"', script))
    looked_up |= set(re.findall(r'"(s-[\w-]+)"', script))
    created_by_the_script = {"save-dir"}
    assert looked_up - created_by_the_script <= set(declared), sorted(looked_up - set(declared))
    assert set(re.findall(r'\bfor="([\w-]+)"', html)) <= set(declared)
    assert set(re.findall(r'href="#([\w-]+)"', html)) <= set(declared)
    # Every class the script assigns has a rule, or is one of the two purely descriptive ones.
    with open(os.path.join(STATIC, "app.css"), encoding="utf-8") as fh:
        css = fh.read()
    for cls in ("card", "sel", "low", "out", "panel", "tab", "colbtn", "dropped", "rowhead", "sheet", "corner", "btn", "k-text",
                "k-number", "k-date", "k-bool", "k-missing", "k-empty", "k-error", "link", "bulk", "big", "cards", "preview"):
        assert "." + cls in css, cls
