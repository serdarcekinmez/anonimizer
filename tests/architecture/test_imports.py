"""Structural rules that the privacy argument rests on."""

from __future__ import annotations

import ast
import os

import pytest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src", "anonimizer")
NETWORK_MODULES = {"socket", "ssl", "http", "urllib", "ftplib", "smtplib", "poplib", "imaplib", "telnetlib",
                   "xmlrpc", "requests", "httpx", "aiohttp", "websockets", "asyncio", "socketserver", "webbrowser"}
AI_MODULES = {"anthropic", "openai", "transformers", "torch", "langchain", "ollama", "mistralai", "cohere"}
# Layer order: a module may import only from layers listed before it.
LAYERS = ["grid", "patterns", "policy", "regions", "recipe", "profile", "contract", "synth", "privacy", "export",
          "reports", "pipeline", "inspector", "cli", "ui"]
ALLOWED = {
    "grid": set(), "patterns": {"grid"}, "policy": set(), "regions": {"grid", "patterns"},
    "recipe": {"grid", "regions"}, "profile": {"grid", "patterns", "policy", "recipe", "regions"},
    "contract": {"patterns", "policy"}, "synth": {"patterns"},
    "privacy": {"patterns", "policy", "recipe", "synth"}, "export": {"policy", "synth"},
    "reports": {"contract", "profile"},
    "pipeline": {"contract", "export", "policy", "privacy", "profile", "recipe", "reports", "synth"},
    "cli": {"contract", "export", "grid", "policy", "recipe", "synth", "pipeline", "reports", "privacy", "ui"},
    "inspector": {"grid", "patterns", "recipe"},
    "ui": {"contract", "export", "grid", "policy", "recipe", "synth", "pipeline", "reports", "privacy", "profile",
           "inspector"},
}


def _modules():
    out = {}
    for base, _dirs, files in os.walk(SRC):
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(base, f)
                rel = os.path.relpath(path, SRC).replace(os.sep, "/")
                top = rel.split("/")[0].removesuffix(".py")
                with open(path, encoding="utf-8") as fh:
                    out[rel] = (top, ast.parse(fh.read(), filename=rel))
    return out


def _imports(tree):
    internal, external = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                external.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                name = (node.module or "").split(".")[0]
                if name:
                    internal.add(name)
                else:
                    internal.update(a.name for a in node.names)
            elif node.module:
                (internal if node.module.startswith("anonimizer") else external).add(
                    node.module.split(".")[1] if node.module.startswith("anonimizer.") else node.module.split(".")[0])
    return internal, external


MODULES = _modules()


def test_layering():
    for rel, (top, tree) in MODULES.items():
        if top in ("__init__", "__main__"):
            continue
        internal, _ = _imports(tree)
        internal = {i for i in internal if i in LAYERS and i != top}
        if rel.startswith("grid/"):
            internal -= {"model", "csv_reader", "xlsx_reader"}
        assert internal <= ALLOWED[top], f"{rel} imports {sorted(internal - ALLOWED[top])}"


@pytest.mark.cnil("ANON-01")
def test_generator_cannot_reach_source_data():
    """synth sees the contract only: no reader, no profile, no file or OS access."""
    _top, tree = MODULES["synth.py"]
    internal, external = _imports(tree)
    assert internal == {"patterns"}
    assert external <= {"__future__", "calendar", "hashlib", "math", "random", "typing"}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {"open", "exec", "eval", "__import__", "compile"}


def test_source_inspector_is_used_by_the_interface_only():
    """The module that returns original cells feeds the local page and nothing that can leave the machine."""
    for rel, (top, tree) in MODULES.items():
        internal, _external = _imports(tree)
        if top not in ("ui", "inspector"):
            assert "inspector" not in internal, f"{rel} imports the source inspector"
    _top, tree = MODULES["inspector.py"]
    internal, external = _imports(tree)
    assert internal <= {"grid", "model", "patterns", "recipe"} and external <= {"__future__", "datetime"}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {"open", "exec", "eval", "__import__", "compile", "print"}


def test_no_network_or_model_library_outside_the_ui():
    for rel, (top, tree) in MODULES.items():
        _internal, external = _imports(tree)
        assert not external & AI_MODULES, f"{rel} imports a model library"
        if top != "ui":
            assert not external & NETWORK_MODULES, f"{rel} imports {sorted(external & NETWORK_MODULES)}"


def test_only_declared_third_party_dependency():
    import sys

    std = set(sys.stdlib_module_names)
    for rel, (_top, tree) in MODULES.items():
        _internal, external = _imports(tree)
        assert external - std <= {"openpyxl"}, f"{rel}: {sorted(external - std)}"


def test_file_writing_is_confined():
    """Writes happen in export (datasets and documents), pipeline/cli (reports the user asked for) and ui."""
    writers = set()
    for _rel, (top, tree) in MODULES.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
                if name == "open" and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) \
                        and any(m in str(node.args[1].value) for m in "wax+"):
                    writers.add(top)
                on_os = isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in (
                    "os", "shutil", "tempfile")
                if on_os and name in ("fdopen", "makedirs", "mkdtemp", "remove", "rmdir", "rmtree", "replace",
                                      "rename", "open", "unlink", "mkdir"):
                    writers.add(top)
    assert writers <= {"export", "pipeline", "cli", "ui"}, writers


def test_no_print_or_logging_in_the_engine():
    """Engine modules stay silent, so no value can reach a console or a log from there."""
    for rel, (top, tree) in MODULES.items():
        if top in ("cli", "ui", "__main__"):
            continue
        _internal, external = _imports(tree)
        assert "logging" not in external, rel
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "print", f"print() in {rel}"
