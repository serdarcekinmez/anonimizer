#!/usr/bin/env python3
"""PreToolUse hook for Read, Edit and Write: keep file access inside the workspace boundary.

Blocks (exit 2):
- any path under /mnt (Windows drives);
- any path under a home directory that is outside this project, except Claude Code's own
  configuration directory;
- data files (CSV, XLSX and similar) outside the registered fixture directories and `out/`.

The shell is not covered here; the sandbox and tools/sbx cover it.
"""

from __future__ import annotations

import json
import os
import sys

DATA_EXT = (".csv", ".tsv", ".xlsx", ".xlsm", ".xls", ".xlsb", ".parquet", ".sqlite", ".db")
DATA_DIRS = ("tests/fixtures", "tests/corpus", "tests/adversarial", "out", ".tools")


def decide(payload: dict, root: str, home: str) -> tuple[int, str]:
    if payload.get("tool_name") not in ("Read", "Edit", "Write", "NotebookEdit"):
        return 0, ""
    raw = (payload.get("tool_input") or {}).get("file_path") or (payload.get("tool_input") or {}).get("notebook_path")
    if not raw or not isinstance(raw, str):
        return 0, ""
    base = payload.get("cwd") or root
    path = os.path.realpath(raw if os.path.isabs(raw) else os.path.join(base, raw))
    root = os.path.realpath(root)
    home = os.path.realpath(home)
    inside = path == root or path.startswith(root + os.sep)
    if path == "/mnt" or path.startswith("/mnt/"):
        return 2, "Blocked: paths under /mnt are outside the Anonimizer workspace boundary."
    if not inside:
        under_home = path == home or path.startswith(home + os.sep) or path.startswith("/home/") or path.startswith("/root")
        claude_cfg = path.startswith(os.path.join(home, ".claude") + os.sep)
        if under_home and not claude_cfg:
            return 2, "Blocked: this path is in a home directory outside the Anonimizer project."
        return 0, ""
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    if rel.lower().endswith(DATA_EXT) and not rel.startswith(tuple(d + "/" for d in DATA_DIRS)):
        return 2, ("Blocked: data files are only allowed under tests/fixtures, tests/corpus, tests/adversarial or out/. "
                   "Only synthetic data may be in this workspace.")
    return 0, ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    code, message = decide(payload, root, os.path.expanduser("~"))
    if message:
        print(message, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
