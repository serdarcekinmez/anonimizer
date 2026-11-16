#!/usr/bin/env python3
"""PreToolUse hook for Bash: scan staged files before a `git commit`.

Blocks (exit 2) when tools/scan_repo.py reports a finding. Any other command passes. This is a
convenience; pre-commit and CI run the same scan and are the enforcement.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

COMMIT = re.compile(r"(^|[;&|]\s*|\s)git(\s+-[cC]\s+\S+)*\s+commit(\s|$)")


def decide(payload: dict, root: str) -> tuple[int, str]:
    if payload.get("tool_name") != "Bash":
        return 0, ""
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not COMMIT.search(command):
        return 0, ""
    scan = os.path.join(root, "tools", "scan_repo.py")
    if not os.path.exists(scan):
        return 0, ""
    proc = subprocess.run([sys.executable, scan, "--staged"], capture_output=True, text=True, cwd=root)
    if proc.returncode == 0:
        return 0, ""
    lines = [line for line in proc.stdout.splitlines() if line.startswith("scan_repo:")][:20]
    return 2, "Commit blocked by the repository scan:\n" + "\n".join(lines) + "\nFix the findings or unstage the files."


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # not a hook payload; nothing to judge
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    code, message = decide(payload, root)
    if message:
        print(message, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
