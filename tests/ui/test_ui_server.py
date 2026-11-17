"""Local interface: loopback binding, token, Host and Origin checks, and the full Mode B flow."""

from __future__ import annotations

import http.client
import json
import os
import threading

import pytest

from anonimizer.ui.server import COOKIE, make_server
from tests.conftest import product_path, read_bundle_texts

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          "src", "anonimizer", "ui", "static")


class Client:
    def __init__(self, port: int, token: str | None):
        self.port, self.token = port, token

    def request(self, method, path, body=None, headers=None, raw=None, cookie=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        h = {"Host": f"127.0.0.1:{self.port}"}
        if cookie and self.token:
            h["Cookie"] = f"{COOKIE}={self.token}"
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        conn.request(method, path, body=data, headers=h)
        res = conn.getresponse()
        payload = res.read()
        conn.close()
        return res, payload

    def post(self, path, body):
        res, payload = self.request("POST", path, body)
        return res.status, json.loads(payload)


@pytest.fixture()
def ui():
    server, token, session = make_server(0, quiet=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield Client(server.server_address[1], token), server, session
    finally:
        server.shutdown()
        server.server_close()
        session.cleanup()


def test_binds_loopback_only(ui):
    _c, server, _s = ui
    assert server.server_address[0] == "127.0.0.1"


def test_token_is_required_and_moves_into_a_cookie(ui):
    c, _server, _s = ui
    res, _ = c.request("GET", "/", cookie=False)
    assert res.status == 403
    res, _ = c.request("GET", "/?token=wrong", cookie=False)
    assert res.status == 403
    res, _ = c.request("GET", f"/?token={c.token}", cookie=False)
    assert res.status == 303 and res.getheader("Location") == "/"
    cookie = res.getheader("Set-Cookie")
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    res, page = c.request("GET", "/")
    assert res.status == 200 and b"<title>Anonimizer</title>" in page
    for path in ("/api/meta", "/static/app.js"):
        assert c.request("GET", path, cookie=False)[0].status == 403
    assert c.request("POST", "/api/open", {"path": "x"}, cookie=False)[0].status == 403


def test_host_and_origin_checks(ui):
    c, _server, _s = ui
    assert c.request("GET", "/api/meta", headers={"Host": "evil.example"})[0].status == 403
    assert c.request("GET", "/api/meta", headers={"Host": f"127.0.0.1:{c.port + 1}"})[0].status == 403
    assert c.request("POST", "/api/open", {"path": "x"}, headers={"Origin": "http://evil.example"})[0].status == 403
    assert c.request("POST", "/api/open", {"path": "x"}, headers={"Sec-Fetch-Site": "cross-site"})[0].status == 403
    res, _ = c.request("POST", "/api/open", {"path": "/nonexistent"}, headers={"Origin": f"http://127.0.0.1:{c.port}"})
    assert res.status == 400
    res, _ = c.request("POST", "/api/open", raw=b"path=x", headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert res.status == 415


def test_security_headers_and_no_cors(ui):
    c, _server, _s = ui
    for path in ("/", "/static/app.js", "/static/app.css", "/api/meta"):
        res, body = c.request("GET", path)
        assert res.status == 200
        assert "default-src 'none'" in res.getheader("Content-Security-Policy")
        assert res.getheader("X-Content-Type-Options") == "nosniff" and res.getheader("Cache-Control") == "no-store"
        assert res.getheader("Access-Control-Allow-Origin") is None
    assert c.request("GET", "/static/../server.py")[0].status == 404
    assert c.request("GET", "/static/secret.txt")[0].status == 404


def test_page_references_no_external_resource():
    static = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          "src", "anonimizer", "ui", "static")
    for name in os.listdir(static):
        text = open(os.path.join(static, name), encoding="utf-8").read()
        assert "http://" not in text and "https://" not in text and "//cdn" not in text, name
        assert "innerHTML" not in text and "eval(" not in text and "document.write" not in text, name


def test_full_workflow(ui, tmp_path, truths):
    c, _server, session = ui
    status, data = c.post("/api/open", {"path": product_path("orders_multi.tsv")})
    assert status == 200 and [t["name"] for t in data["recipe"]["tables"]] == ["note_1", "table_1", "table_2", "note_2"]
    # Step 3 in the directive: correct a parsing selection.
    recipe = data["recipe"]
    recipe["tables"][2]["name"] = "clients"
    recipe["tables"][3]["include"] = False
    status, data = c.post("/api/recipe", {"recipe": recipe})
    assert status == 200 and data["recipe"]["tables"][2]["name"] == "clients"
    bad = json.loads(json.dumps(recipe))
    bad["tables"][1]["last_col"] = 0
    status, err = c.post("/api/recipe", {"recipe": bad})
    assert status == 400 and "positive integer" in err["error"]
    # A policy must be chosen.
    status, err = c.post("/api/profile", {})
    assert status == 400 and "explicitly" in err["error"]
    status, data = c.post("/api/profile", {"policy": "internal-dev"})
    assert status == 200
    classes = {e["class"] for e in data["report"]["exception_catalogue"]}
    assert {"type.text_in_number", "key.dangling_reference", "value.invalid_date", "row.blank_inside_table"} <= classes
    contract = data["contract"]
    assert [t["name"] for t in contract["tables"]] == ["table_1", "clients"]
    # Step 6: adjust the contract: classify everything, drop a column, copy an approved category, confirm.
    cols = []
    for t in contract["tables"]:
        for col in t["columns"]:
            d = {"table": t["name"], "id": col["id"], "keep": col["name"] != "comment",
                 "sensitivity": "non_sensitive" if col["sensitivity"]["class"] == "unreviewed" else col["sensitivity"]["class"]}
            if col["name"] == "channel":
                assert col["can_keep_literals"]
                d["literal_categories"] = True
            cols.append(d)
    status, err = c.post("/api/contract", {"columns": cols, "confirm_by": "UI Tester"})
    assert status == 400 and "approver" in err["error"]
    status, data = c.post("/api/contract", {"columns": cols, "confirm_by": "UI Tester", "approved_by": "Data Owner"})
    assert status == 200 and data["contract"]["review"]["confirmed_by"] == "UI Tester"
    status, err = c.post("/api/generate", {"rows": 0})
    assert status == 400
    status, res = c.post("/api/generate", {"rows": 45, "seed": "ui", "packing": "auto", "rows_for": {"clients": 20}})
    assert status == 200
    assert res["assessment"]["release_tier"] == "RESTRICTED" and res["assessment"]["assessment_status"] == "passed"
    cov = {t["table"]: t for t in res["coverage"]["tables"]}
    assert cov["table_1"]["generated_data_rows"] == 45 and cov["clients"]["generated_data_rows"] == 20
    assert any("dropped" in u["reason"] for u in cov["table_1"]["uncovered"])
    header = res["preview"][0]["rows"][3]
    assert header[:2] == ["order_no", "customer_ref"] and "comment" not in header
    channels = {r[5] for r in res["preview"][0]["rows"][4:30] if len(r) > 5}
    assert channels & {"web", "store", "phone"}
    assert res["manifest"] and res["comparison"]["tables"]
    # Nothing from the source leaks through any API answer.
    blob = json.dumps(res, ensure_ascii=False)
    for canary in truths["orders_multi.tsv"]["canaries"] + ["ORD-000001", "livraison", "Ventoux"]:
        assert canary not in blob
    # Step 9: export with classification.
    resp, payload = c.request("GET", "/api/download/CLASSIFICATION.txt")
    assert resp.status == 200 and b"RESTRICTED" in payload and "attachment" in resp.getheader("Content-Disposition")
    resp, payload = c.request("GET", "/api/download/synthetic.tsv")
    assert resp.status == 200 and payload.count(b"\r\n") > 60
    assert c.request("GET", "/api/download/..%2F..%2Fetc%2Fpasswd")[0].status == 404
    assert c.request("GET", "/api/download/source_profile.PRIVATE.json")[0].status == 404
    target = tmp_path / "bundle"
    status, saved = c.post("/api/save", {"directory": str(target)})
    assert status == 200 and saved["release_tier"] == "RESTRICTED"
    assert sorted(os.listdir(target)) == sorted(res["files"])
    status, err = c.post("/api/save", {"directory": str(target)})
    assert status == 400 and "empty" in err["error"]
    assert os.path.isdir(session.workdir)


def test_upload_and_internal_errors_hide_details(ui, monkeypatch):
    c, _server, session = ui
    data = open(product_path("customers_hidden.csv"), "rb").read()
    res, payload = c.request("POST", "/api/upload?name=..%2F..%2Fevil%20name.csv", raw=data)
    assert res.status == 200
    info = json.loads(payload)
    assert info["file_name"] == ".._.._evil_name.csv" and os.path.dirname(session.path).startswith(session.workdir)
    assert c.post("/api/generate", {"rows": 5})[0] == 409

    import anonimizer.ui.server as srv

    def boom(*a, **k):
        raise ValueError("bad value 'Wolfhaven77'")

    monkeypatch.setattr(srv, "build_profile", boom)
    status, err = c.post("/api/profile", {"policy": "internal-dev"})
    assert status == 500 and "Wolfhaven77" not in err["error"] and "ValueError" in err["error"]


def test_session_folder_is_removed(ui):
    _c, _server, session = ui
    workdir = session.workdir
    assert os.path.isdir(workdir) and oct(os.stat(workdir).st_mode & 0o777) == "0o700"
    session.cleanup()
    assert not os.path.exists(workdir)



SOURCE_ONLY = ["ORD-000001", "livraison", "Ventoux"]


def test_source_inspector_shows_original_cells_without_a_policy(ui, truths):
    c, _server, _session = ui
    assert c.post("/api/source", {"region": 0})[0] == 409  # no file yet
    status, opened = c.post("/api/open", {"path": product_path("orders_multi.tsv")})
    assert status == 200
    # The first table with its surroundings: three rows above it, the header, then the data. No policy was chosen.
    status, win = c.post("/api/source", {"region": 1})
    assert status == 200 and win["contains_source_values"] is True
    reg = next(r for r in win["regions"] if r["index"] == 1)
    assert (reg["header_row"], reg["first_data_row"], reg["first_col"], reg["last_col"]) == (4, 5, 1, 7)
    assert win["first_row"] == 1 and len(win["rows"]) == 50 and win["more_rows"] is True
    by_row = {r["row"]: r["cells"] for r in win["rows"]}
    assert by_row[4][:2] == ["order_no", "customer_ref"] and by_row[5][0] == "ORD-000001"
    # Paging is bounded whatever is asked for, and positions are checked.
    status, big = c.post("/api/source", {"sheet": 0, "row": 1, "rows": 100000, "cols": 100000})
    assert status == 200 and len(big["rows"]) == 200 and big["columns"] <= 60
    for bad in ({"region": 99}, {"region": "1"}, {"sheet": 5}, {"row": 0}, {"col": -3}, {"rows": 0}, {"row": 1.5}, {"region": True}):
        status, err = c.post("/api/source", bad)
        assert status == 400, bad
        assert "ORD-" not in err["error"]
    # A value planted deep in the file is reachable by going to its row; the end of the sheet is reported.
    planted = next(a for a in truths["orders_multi.tsv"]["anomalies"] if a["class"] == "type.text_in_number")
    deep_row = planted["rows"][0]  # the builder records the row of the file
    status, deep = c.post("/api/source", {"sheet": 0, "row": deep_row, "rows": 1})
    assert status == 200 and deep["rows"][0]["row"] == deep_row and "douze" in deep["rows"][0]["cells"]
    status, end = c.post("/api/source", {"sheet": 0, "row": 1350, "rows": 50})
    assert status == 200 and end["more_rows"] is False and 1 <= len(end["rows"]) < 50
    status, past = c.post("/api/source", {"sheet": 0, "row": 900000})
    assert status == 200 and past["rows"] == [] and past["more_rows"] is False
    # Exact counts, still without a policy, equal what the fixture builder planted.
    status, stats = c.post("/api/source/stats", {})
    assert status == 200
    table = {t["name"]: t for t in stats["tables"]}["table_1"]
    cols = {col["name"]: col for col in table["columns"]}
    assert table["rows"] == 1200 and len(cols) == 7
    assert cols["quantity"]["kinds"]["text"] == 1 and cols["quantity"]["missing"] == 1
    assert cols["comment"]["missing"] == 1117 and cols["order_no"]["distinct"] == 1200
    assert {v for v, _n in cols["channel"]["frequent_values"]} == {"web", "store", "phone"}
    assert c.post("/api/sample", {})[0] == 409  # counting is not an analysis under a policy: there is no contract


def test_what_the_inspector_shows_reaches_no_other_answer_and_no_export(ui, tmp_path, truths):
    c, _server, session = ui
    canaries = truths["orders_multi.tsv"]["canaries"] + SOURCE_ONLY
    answers = {}
    status, answers["open"] = c.post("/api/open", {"path": product_path("orders_multi.tsv")})
    # Look at everything first: the whole first table, the notes around it, the exact counts.
    seen = ""
    for row in range(1, 1400, 200):
        status, win = c.post("/api/source", {"sheet": 0, "row": row, "rows": 200})
        assert status == 200
        seen += json.dumps(win, ensure_ascii=False)
    seen += json.dumps(c.post("/api/source/stats", {})[1], ensure_ascii=False)
    assert all(canary in seen for canary in canaries)  # the inspector really shows the original values
    status, answers["recipe"] = c.post("/api/recipe", {"recipe": answers["open"]["recipe"]})
    c.post("/api/source/stats", {})
    status, answers["profile"] = c.post("/api/profile", {"policy": "internal-dev"})
    assert status == 200
    status, answers["sample"] = c.post("/api/sample", {})
    cols = [{"table": t["name"], "id": col["id"], "keep": True,
             "sensitivity": "non_sensitive" if col["sensitivity"]["class"] == "unreviewed" else col["sensitivity"]["class"]}
            for t in answers["profile"]["contract"]["tables"] for col in t["columns"]]
    status, answers["contract"] = c.post("/api/contract", {"columns": cols, "confirm_by": "UI Tester"})
    assert status == 200
    c.post("/api/source", {"region": 1})  # looking again between the steps changes nothing
    status, answers["generate"] = c.post("/api/generate", {"rows": 40, "seed": "inspect", "packing": "auto"})
    assert status == 200 and answers["generate"]["assessment"]["assessment_status"] == "passed"
    # Only the two inspector routes carry original values; every other answer is free of them.
    for name, answer in answers.items():
        blob = json.dumps(answer, ensure_ascii=False)
        for canary in canaries:
            assert canary not in blob, (name, "an answer outside the inspector carries a source value")
    # The bundle holds the intended artefacts and nothing of what was looked at.
    target = str(tmp_path / "bundle")
    status, saved = c.post("/api/save", {"directory": target})
    assert status == 200 and sorted(saved["files"]) == sorted(os.listdir(target)) == sorted(answers["generate"]["files"])
    for name, text in read_bundle_texts(target).items():
        for canary in canaries:
            assert canary not in text, name
    # Nothing was written next to the bundle either: the session folder holds runs and the register only.
    assert all(n.startswith("run") or n == "release_register.jsonl" for n in os.listdir(session.workdir))


def test_page_and_server_are_delivered_together(ui):
    c, server, _session = ui
    _resp, meta = c.request("GET", "/api/meta")
    with open(os.path.join(STATIC_DIR, "app.js"), encoding="utf-8") as fh:
        script = fh.read()
    assert f"const API = {json.loads(meta)['api']};" in script
    # The page is read when the server starts, so a running server never serves a newer page than its routes.
    assert server.RequestHandlerClass.static["app.js"] == script.encode("utf-8")


def test_column_names_endpoint_previews_without_changing_anything(ui):
    """ASTRA-05: the page asks the same naming layer as the command line for a preview."""
    c, _server, session = ui
    assert c.post("/api/open", {"path": product_path("customers_hidden.csv")})[0] == 200
    assert c.post("/api/profile", {"policy": "internal-dev"})[0] == 200
    cols = [{"id": "c1", "name": "a"}, {"id": "c2", "name": "b"}, {"id": "c3", "name": "c"}]
    status, data = c.post("/api/names", {"table": "table_1", "columns": cols, "selected": ["c1", "c3"],
                                         "mode": "sequence", "prefix": "f_"})
    assert status == 200 and [(p["id"], p["new"]) for p in data["plan"]] == [("c1", "f_Alpha"), ("c3", "f_Beta")]
    status, data = c.post("/api/names", {"table": "table_1", "columns": cols, "mode": "list", "names": ["x"]})
    assert status == 400 and "1 name(s) were given for 3 selected column(s)" in data["error"]
    status, data = c.post("/api/names", {"table": "table_1", "columns": cols, "mode": "list", "names": ["x", "y", "a"],
                                         "selected": ["c2", "c3"]})
    assert status == 400 and "2 selected column(s)" in data["error"]
    # Nothing was applied: the contract keeps its names until the decisions are applied.
    assert session.contract["tables"][0]["columns"][0]["name"] != "f_Alpha"


def test_leaving_out_every_column_is_refused_when_decisions_are_applied(ui):
    """ASTRA-06: the page hears it when it applies the decisions, in plain words."""
    c, _server, _session = ui
    assert c.post("/api/open", {"path": product_path("customers_hidden.csv")})[0] == 200
    status, data = c.post("/api/profile", {"policy": "internal-dev"})
    cols = [{"table": t["name"], "id": col["id"], "keep": False} for t in data["contract"]["tables"] for col in t["columns"]]
    status, err = c.post("/api/contract", {"columns": cols})
    assert status == 400 and "no column is kept" in err["error"]
