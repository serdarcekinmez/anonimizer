"""Claude Code hooks: inputs are built from the documented PreToolUse schema (not from a recorded session)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys

import pytest

from tests.conftest import ROOT

HOOKS = os.path.join(ROOT, ".claude", "hooks")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HOOKS, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


guard_paths = _load("guard_paths")
guard_commit = _load("guard_commit")
HOME = "/home/someone"
PROJECT = "/home/someone/projects/anonimizer"


@pytest.mark.parametrize("tool,path,blocked", [
    ("Read", "/mnt/c/Users/x/data.xlsx", True),
    ("Read", "/mnt", True),
    ("Write", "/mnt/d/out.csv", True),
    ("Read", "/home/someone/projects/Other/app.py", True),
    ("Read", "/home/someone/.ssh/id_rsa", True),
    ("Edit", "/home/another/file.txt", True),
    ("Read", "/home/someone/.claude/settings.json", False),
    ("Read", PROJECT + "/src/anonimizer/cli.py", False),
    ("Read", "src/anonimizer/cli.py", False),
    ("Read", PROJECT + "/tests/fixtures/product/customers_hidden.csv", False),
    ("Read", PROJECT + "/out/run1/synthetic.csv", False),
    ("Read", PROJECT + "/clients.xlsx", True),
    ("Write", PROJECT + "/docs/real_export.csv", True),
    ("Read", PROJECT + "/../Other/secret.txt", True),
    ("Read", "/tmp/scratch/notes.md", False),
    ("Read", "/usr/lib/python3/os.py", False),
    ("Bash", "/mnt/c/x", False),
])
def test_guard_paths(tool, path, blocked):
    payload = {"tool_name": tool, "tool_input": {"file_path": path}, "cwd": PROJECT}
    code, message = guard_paths.decide(payload, PROJECT, HOME)
    assert (code == 2) is blocked, message
    if blocked:
        assert message.startswith("Blocked")


def test_guard_paths_ignores_malformed_input():
    out = subprocess.run([sys.executable, os.path.join(HOOKS, "guard_paths.py")], input="not json", capture_output=True, text=True)
    assert out.returncode == 0
    assert guard_paths.decide({"tool_name": "Read", "tool_input": {}}, PROJECT, HOME)[0] == 0


@pytest.mark.parametrize("command,is_commit", [
    ("git commit -m 'x'", True), ("git add -A && git commit -q -m x", True), ("git -c user.name=x commit -m y", True),
    ("git status", False), ("git log --oneline", False), ("echo git commit", True), ("git commit-tree abc", False),
    ("pytest", False),
])
def test_guard_commit_only_reacts_to_commits(command, is_commit):
    assert bool(guard_commit.COMMIT.search(command)) is is_commit


def test_guard_commit_passes_on_a_clean_tree_and_other_tools():
    assert guard_commit.decide({"tool_name": "Read", "tool_input": {"file_path": "x"}}, ROOT) == (0, "")
    assert guard_commit.decide({"tool_name": "Bash", "tool_input": {"command": "ls"}}, ROOT) == (0, "")
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git status"}})
    out = subprocess.run([sys.executable, os.path.join(HOOKS, "guard_commit.py")], input=payload, capture_output=True, text=True)
    assert out.returncode == 0


def test_guard_commit_blocks_when_the_scan_finds_something(tmp_path):
    """A throwaway repository with a staged data file outside the fixture directories."""
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    with open(os.path.join(ROOT, "tools", "scan_repo.py"), encoding="utf-8") as fh:
        (repo / "tools" / "scan_repo.py").write_text(fh.read(), encoding="utf-8")
    (repo / "clients.csv").write_text("a,b\n1,2\n")
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    for cmd in (["git", "init", "-q"], ["git", "add", "clients.csv"]):
        subprocess.run(cmd, cwd=repo, check=True, env=env, capture_output=True)
    code, message = guard_commit.decide({"tool_name": "Bash", "tool_input": {"command": "git commit -m data"}}, str(repo))
    assert code == 2 and "data file outside the fixture directories" in message
