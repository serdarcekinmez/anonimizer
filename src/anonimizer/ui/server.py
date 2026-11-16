"""Loopback-only HTTP server for the Mode B workflow.

Hardening (architecture v0.4, correction F):
- binds 127.0.0.1 only, on a random free port unless one is given;
- a random per-session token is required (cookie set from the start URL);
- the Host header must name this loopback origin (DNS-rebinding guard);
- cross-origin requests are refused; there is no CORS header at all;
- a strict Content-Security-Policy; no external resource is ever referenced;
- nothing is logged except method, path and status. Request bodies are never logged.
"""

from __future__ import annotations

import atexit
import hmac
import json
import os
import re
import secrets
import shutil
import tempfile
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .. import NON_CERTIFICATION_STATEMENT, __version__
from .. import contract as contract_mod
from ..export import ExportRefused
from ..grid import GridError, open_source
from ..pipeline import apply_decisions, generate_and_export, inspect, profile_source
from ..policy import POLICIES, PolicyError, get_policy
from ..recipe import ParseRecipe, RecipeError, region_layout
from ..reports import summarize_profile
from ..synth import SynthError, generate

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MAX_JSON = 5 * 1024 * 1024
MAX_UPLOAD = 4 * 1024**3
COOKIE = "anonimizer_session"
LAYOUT_ROWS, LAYOUT_COLS, SAMPLE_ROWS = 8, 40, 6
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "form-action 'none'; frame-ancestors 'none'; base-uri 'none'")
KNOWN_ERRORS = (GridError, RecipeError, contract_mod.ContractError, PolicyError, SynthError, ExportRefused)
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8"}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class Session:
    """State of the single local user. Everything lives in a private temporary directory."""

    def __init__(self):
        self.workdir = tempfile.mkdtemp(prefix="anonimizer-ui-")
        os.chmod(self.workdir, 0o700)
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.path: str | None = None
        self.display_name: str | None = None
        self.recipe = ParseRecipe()
        self.detected: dict | None = None
        self.policy_id: str | None = None
        self.private: dict | None = None
        self.shareable: dict | None = None
        self.contract: dict | None = None
        self.result = None
        self.out_dir: str | None = None
        self.run_no = 0

    def cleanup(self) -> None:
        shutil.rmtree(self.workdir, ignore_errors=True)

    # -- steps --------------------------------------------------------------------------------
    def open_path(self, path: str) -> dict:
        if not isinstance(path, str) or not path.strip():
            raise ApiError(400, "a file path is required")
        real = os.path.realpath(os.path.expanduser(path.strip()))
        if not os.path.isfile(real):
            raise ApiError(400, "that path is not an existing file")
        self.reset()
        self.path, self.display_name = real, os.path.basename(real)
        return self.inspect()

    def inspect(self) -> dict:
        self._need_file()
        res = inspect(self.path, self.recipe)
        if self.detected is None:
            self.detected = res["recipe"]
        return {"file_name": self.display_name, "file": res["file"], "sheets": res["sheets"],
                "recipe": res["recipe"], "detected": self.detected}

    def set_recipe(self, body: dict) -> dict:
        self._need_file()
        if body.get("reset"):
            self.recipe = ParseRecipe()
            self.detected = None
        else:
            recipe = ParseRecipe.from_dict(body.get("recipe") or {})
            for t in recipe.tables or []:
                if isinstance(t, dict):
                    t["source"] = "user"
            inspect(self.path, recipe)  # validates against the file; raises with a reason
            self.recipe = recipe
        self.private = self.shareable = self.contract = self.result = None
        return self.inspect()

    def layout(self, body: dict) -> dict:
        """Kinds of the first cells of one region (text, number, date ...), never their values."""
        self._need_file()
        index = body.get("index")
        out = region_layout(self.path, self.recipe, index, LAYOUT_ROWS, LAYOUT_COLS)
        out["index"] = index
        return out

    def sample(self, _body: dict) -> dict:
        """A few synthetic rows per table, generated from the applied contract only. Nothing is exported."""
        if self.contract is None:
            raise ApiError(409, "profile the file first")
        contract = json.loads(json.dumps(self.contract))
        for tab in contract["tables"]:
            for sc in tab["scenarios"]:
                sc["enabled"] = False  # typical values only; the exceptions are listed per column
        try:
            out = generate(contract, {"*": SAMPLE_ROWS}, "preview")
        except SynthError:
            return {"tables": {}}
        tables = {}
        for name, tab in out["tables"].items():
            data = [r for r in tab["rows"] if r["kind"] == "data"][:SAMPLE_ROWS]
            tables[name] = {"columns": tab["columns"],
                            "rows": [["" if c.text is None else c.text[:60] for c in r["cells"]] for r in data]}
        return {"tables": tables}

    def profile(self, body: dict) -> dict:
        self._need_file()
        policy = get_policy(body.get("policy"))
        self.policy_id = policy.id
        self.private, self.shareable = profile_source(self.path, self.recipe, policy)
        self.contract = contract_mod.build_contract(self.shareable, policy)
        self.result = None
        return {"policy": policy.to_dict(), "report": summarize_profile(self.shareable, "source"),
                "contract": self._contract_view()}

    def decide(self, body: dict) -> dict:
        if self.shareable is None or self.private is None:
            raise ApiError(409, "profile the file first")
        policy = get_policy(self.policy_id)
        contract = contract_mod.build_contract(self.shareable, policy)
        cols = body.get("columns") or []
        scen = {s.get("id"): s for s in body.get("scenarios") or [] if isinstance(s, dict)}
        drop, sens, rename = [], [], []
        for c in cols:
            if not isinstance(c, dict):
                raise ApiError(400, "malformed column decision")
            t, cid = str(c.get("table")), str(c.get("id"))
            if c.get("keep") is False:
                drop.append((t, cid))
            if c.get("sensitivity"):
                sens.append((t, cid, str(c["sensitivity"])))
            if isinstance(c.get("name"), str) and c["name"] != contract_mod.find_column(contract, t, cid)["name"]:
                rename.append((t, cid, c["name"][:300]))
        keep_cat = [(str(c.get("table")), str(c.get("id"))) for c in cols if isinstance(c, dict) and c.get("literal_categories")]
        apply_decisions(contract, self.private, drop=drop, sensitivity=sens, keep_categories=keep_cat,
                        approved_by=body.get("approved_by"), rename=rename,
                        confirm_by=body.get("confirm_by") or None)
        for t in contract["tables"]:
            for s in t["scenarios"]:
                d = scen.get(s["id"])
                if d and s["reproducible"]:
                    s["enabled"] = bool(d.get("enabled", True))
                    s["pinned"] = bool(d.get("pinned", False))
        contract_mod.validate_contract(contract)
        self.contract = contract
        self.result = None
        return {"contract": self._contract_view()}

    def generate(self, body: dict) -> dict:
        if self.contract is None:
            raise ApiError(409, "profile the file first")
        self.result = None  # links of an earlier run stop working as soon as a new run is requested
        rows: dict = {"*": body.get("rows")}
        for name, n in (body.get("rows_for") or {}).items():
            if n not in (None, ""):
                rows[str(name)] = n
        self.run_no += 1
        out_dir = os.path.join(self.workdir, f"run{self.run_no}")
        try:
            result = generate_and_export(
                self.path, self.recipe, self.private, self.shareable, self.contract, rows=rows,
                seed=str(body.get("seed", "0")), packing=str(body.get("packing", "auto")), out_dir=out_dir,
                register_path=os.path.join(self.workdir, "release_register.jsonl"))
        except Exception:
            shutil.rmtree(out_dir, ignore_errors=True)
            raise
        self.result, self.out_dir = result, out_dir
        return {
            "assessment": result.assessment, "coverage": result.coverage, "manifest": result.manifest,
            "comparison": result.comparison, "generated_report": result.generated_report,
            "files": result.export["files"], "dataset_file": result.export["dataset_file"],
            "preview": self._preview(os.path.join(out_dir, result.export["dataset_file"])),
        }

    def save_bundle(self, body: dict) -> dict:
        if self.result is None or self.out_dir is None:
            raise ApiError(409, "generate a dataset first")
        target = body.get("directory")
        if not isinstance(target, str) or not target.strip():
            raise ApiError(400, "a target directory is required")
        target = os.path.realpath(os.path.expanduser(target.strip()))
        if os.path.exists(target) and (not os.path.isdir(target) or os.listdir(target)):
            raise ApiError(400, "the target must be a new or empty directory")
        os.makedirs(target, mode=0o700, exist_ok=True)
        for name in self.result.export["files"]:
            shutil.copyfile(os.path.join(self.out_dir, name), os.path.join(target, name))
            os.chmod(os.path.join(target, name), 0o600)
        return {"directory": target, "files": self.result.export["files"],
                "release_tier": self.result.assessment["release_tier"]}

    # -- helpers ------------------------------------------------------------------------------
    def _need_file(self) -> None:
        if not self.path:
            raise ApiError(409, "select a file first")

    def _contract_view(self) -> dict:
        categorical = {}
        for tab in (self.private or {}).get("tables", []):
            for col in tab["columns"]:
                categorical[(tab["name"], col["id"])] = "categorical" in col
        view = json.loads(json.dumps(self.contract))
        for tab in view["tables"]:
            for col in tab["columns"]:
                col["can_keep_literals"] = categorical.get((tab["name"], col["id"]), False)
        return view

    @staticmethod
    def _preview(path: str, max_rows: int = 40, max_cols: int = 30) -> list[dict]:
        src = open_source(path)
        out = []
        for sh in src.sheets:
            rows = []
            for row in src.rows(sh.index):
                if row.index >= max_rows:
                    break
                while len(rows) < row.index:
                    rows.append([])
                rows.append(["" if v is None else v[:120] for v in row.raw[:max_cols]])
            out.append({"sheet": sh.name, "rows": rows})
        return out


class Handler(BaseHTTPRequestHandler):
    server_version = "Anonimizer/" + __version__
    sys_version = ""
    session: Session
    token: str
    quiet = False

    # -- plumbing -----------------------------------------------------------------------------
    def log_message(self, fmt, *args):  # never log bodies or query strings
        if not self.quiet:
            path = urlsplit(self.path).path
            print(f"[ui] {self.command} {path} -> {args[1] if len(args) > 1 else ''}", flush=True)

    def _headers(self, status: int, ctype: str, length: int, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def _json(self, status: int, obj) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(data))
        self.wfile.write(data)

    def _origin_ok(self) -> bool:
        port = self.server.server_address[1]
        allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in allowed_hosts:
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {f"http://{h}" for h in allowed_hosts}:
            return False
        site = self.headers.get("Sec-Fetch-Site")
        return site in (None, "same-origin", "none")

    def _cookie_ok(self) -> bool:
        for part in (self.headers.get("Cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE and hmac.compare_digest(value.encode(), self.token.encode()):
                return True
        return False

    def _body_json(self) -> dict:
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            raise ApiError(415, "requests must be application/json")
        try:
            n = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            raise ApiError(400, "bad Content-Length") from None
        if n < 0 or n > MAX_JSON:
            raise ApiError(413, "request too large")
        try:
            obj = json.loads(self.rfile.read(n) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ApiError(400, "malformed JSON") from None
        if not isinstance(obj, dict):
            raise ApiError(400, "a JSON object is expected")
        return obj

    # -- routes -------------------------------------------------------------------------------
    def do_GET(self):  # noqa: N802
        if not self._origin_ok():
            return self._json(403, {"error": "request refused"})
        url = urlsplit(self.path)
        if url.path == "/":
            given = (parse_qs(url.query).get("token") or [""])[0]
            if given and hmac.compare_digest(given.encode(), self.token.encode()):
                # Move the token out of the address bar into an HttpOnly cookie.
                self._headers(303, "text/plain", 0, {
                    "Location": "/", "Set-Cookie": f"{COOKIE}={self.token}; HttpOnly; SameSite=Strict; Path=/"})
                return None
            if not self._cookie_ok():
                return self._json(403, {"error": "open the address printed in the terminal, including its token"})
            return self._static("index.html")
        if not self._cookie_ok():
            return self._json(403, {"error": "request refused"})
        if url.path.startswith("/static/"):
            return self._static(url.path[len("/static/"):])
        try:
            with self.session.lock:
                if url.path == "/api/meta":
                    return self._json(200, {"version": __version__, "statement": NON_CERTIFICATION_STATEMENT,
                                            "policies": [p.to_dict() for p in POLICIES.values()],
                                            "sensitivity_classes": list(contract_mod.SENSITIVITY_CLASSES),
                                            "file_name": self.session.display_name})
                if url.path.startswith("/api/download/"):
                    return self._download(url.path[len("/api/download/"):])
        except ApiError as exc:
            return self._json(exc.status, {"error": str(exc)})
        return self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if not self._origin_ok() or not self._cookie_ok():
            return self._json(403, {"error": "request refused"})
        url = urlsplit(self.path)
        s = self.session
        try:
            with s.lock:
                if url.path == "/api/upload":
                    return self._json(200, self._upload(url))
                body = self._body_json()
                routes = {"/api/open": lambda: s.open_path(body.get("path")), "/api/recipe": lambda: s.set_recipe(body),
                          "/api/profile": lambda: s.profile(body), "/api/contract": lambda: s.decide(body),
                          "/api/generate": lambda: s.generate(body), "/api/save": lambda: s.save_bundle(body),
                          "/api/layout": lambda: s.layout(body), "/api/sample": lambda: s.sample(body)}
                handler = routes.get(url.path)
                if handler is None:
                    return self._json(404, {"error": "not found"})
                return self._json(200, handler())
        except ApiError as exc:
            return self._json(exc.status, {"error": str(exc)})
        except KNOWN_ERRORS as exc:
            return self._json(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - the message may quote data, so it is withheld
            tb = traceback.extract_tb(exc.__traceback__)[-1]
            return self._json(500, {"error": f"internal error: {type(exc).__name__} at "
                                             f"{os.path.basename(tb.filename)}:{tb.lineno}"})

    def _static(self, name: str):
        if name not in ("index.html", "app.js", "app.css"):
            return self._json(404, {"error": "not found"})
        with open(os.path.join(STATIC, name), "rb") as fh:
            data = fh.read()
        self._headers(200, STATIC_TYPES[os.path.splitext(name)[1]], len(data))
        self.wfile.write(data)
        return None

    def _download(self, name: str):
        s = self.session
        if s.result is None or s.out_dir is None or name not in s.result.export["files"]:
            raise ApiError(404, "no such file in the current result")
        path = os.path.join(s.out_dir, name)
        size = os.path.getsize(path)
        self._headers(200, "application/octet-stream", size,
                      {"Content-Disposition": f'attachment; filename="{SAFE_NAME.sub("_", name)}"'})
        with open(path, "rb") as fh:
            shutil.copyfileobj(fh, self.wfile)
        return None

    def _upload(self, url) -> dict:
        s = self.session
        name = SAFE_NAME.sub("_", (parse_qs(url.query).get("name") or ["upload"])[0])[-120:] or "upload"
        try:
            n = int(self.headers.get("Content-Length") or "-1")
        except ValueError:
            raise ApiError(400, "bad Content-Length") from None
        if n < 0:
            raise ApiError(411, "Content-Length is required")
        if n > MAX_UPLOAD:
            raise ApiError(413, "file too large for upload; open it by path instead")
        updir = os.path.join(s.workdir, "input")
        shutil.rmtree(updir, ignore_errors=True)
        os.makedirs(updir, mode=0o700)
        path = os.path.join(updir, name)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            left = n
            while left > 0:
                chunk = self.rfile.read(min(1 << 20, left))
                if not chunk:
                    raise ApiError(400, "upload interrupted")
                fh.write(chunk)
                left -= len(chunk)
        s.reset()
        s.path, s.display_name = path, name
        return s.inspect()


def make_server(port: int = 0, quiet: bool = False) -> tuple[ThreadingHTTPServer, str, Session]:
    session = Session()
    token = secrets.token_urlsafe(32)
    handler = type("BoundHandler", (Handler,), {"session": session, "token": token, "quiet": quiet})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)  # loopback only, never 0.0.0.0
    server.daemon_threads = True
    return server, token, session


def serve(port: int = 0, open_browser: bool = True) -> int:
    server, token, session = make_server(port)
    atexit.register(session.cleanup)
    url = f"http://127.0.0.1:{server.server_address[1]}/?token={token}"
    print("Anonimizer local interface (loopback only, this session only):", flush=True)
    print(f"  {url}", flush=True)
    print("Press Ctrl+C to stop. Temporary files are removed on exit.", flush=True)
    if open_browser:
        try:
            import webbrowser

            webbrowser.open(url)
        except Exception:  # noqa: BLE001, S110 - a missing browser is not an error
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()
        session.cleanup()
    return 0
