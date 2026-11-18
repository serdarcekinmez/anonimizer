"""Single quality gate, used by people, hooks, pre-commit and CI.

    python tools/gate.py --fast      lint, repository scan, matrix check, quick tests
    python tools/gate.py --full      the same with the whole test suite; writes docs/evidence/gate-report.*
    python tools/gate.py --release   --full plus the release rule on the findings register

On a development machine the gate re-runs itself inside the bubblewrap sandbox (tools/sbx) and
refuses to run if that is impossible. CI sets ANONIMIZER_CI=1 because its runners are disposable.

A green gate means the listed controls behaved as specified on the listed fixtures. It is not
a certification and not proof of legal anonymity.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATEMENT = ("A green gate means the listed controls behaved as specified on the listed fixtures. It is not a "
             "certification and not proof of legal anonymity.")
FAST_TESTS = ["tests/unit", "tests/golden", "tests/architecture"]


def _sandbox_or_exit(argv: list[str]) -> None:
    if os.environ.get("ANONIMIZER_SBX") == "1" or os.environ.get("ANONIMIZER_CI") == "1":
        return
    sbx = os.path.join(ROOT, "tools", "sbx")
    try:
        os.execv(sbx, [sbx, sys.executable if ".venv" in sys.executable else "python", os.path.abspath(__file__), *argv])
    except OSError:
        print("gate: the sandbox wrapper could not be started; refusing to run unsandboxed", file=sys.stderr)
        sys.exit(97)


def _run(name: str, cmd: list[str]) -> dict:
    start = time.time()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-12:]
    tail = [re.sub(re.escape(ROOT), ".", line) for line in tail]
    return {"step": name, "command": " ".join(cmd[1:] if cmd[0] == sys.executable else cmd), "exit": proc.returncode,
            "seconds": round(time.time() - start, 1), "tail": tail}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    mode = "release" if "--release" in argv else "full" if "--full" in argv else "fast"
    _sandbox_or_exit(argv)
    py = sys.executable
    steps = [
        _run("lint", [py, "-m", "ruff", "check", "src", "tests", "tools", ".claude"]),
        _run("repository scan", [py, "tools/scan_repo.py"]),
        _run("traceability matrix", [py, "tools/check_rtm.py"] + (["--release"] if mode == "release" else [])),
    ]
    tests = [py, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rN"]
    tests += FAST_TESTS if mode == "fast" else ["tests"]
    steps.append(_run("tests", tests))
    counts = None
    for line in reversed(steps[-1]["tail"]):
        m = re.search(r"(\d+) passed", line)
        if m:
            counts = {"passed": int(m.group(1))}
            for key in ("failed", "skipped", "error", "errors"):
                k = re.search(rf"(\d+) {key}", line)
                if k:
                    counts[key] = int(k.group(1))
            break
    ok = all(s["exit"] == 0 for s in steps)
    for s in steps:
        print(f"gate: {'ok  ' if s['exit'] == 0 else 'FAIL'} {s['step']} ({s['seconds']} s)")
        if s["exit"] != 0:
            for line in s["tail"]:
                print(f"      {line}")
    print(f"gate: {mode} gate {'passed' if ok else 'FAILED'}" + (f"; tests: {counts}" if counts else ""))
    print(f"gate: {STATEMENT}")
    if mode in ("full", "release"):
        out = os.path.join(ROOT, "docs", "evidence")
        os.makedirs(out, exist_ok=True)
        commit = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", ROOT, "status", "--porcelain"], capture_output=True, text=True).stdout.strip())
        report = {"mode": mode, "passed": ok, "date": dt.date.today().isoformat(), "commit": commit,
                  "uncommitted_changes": dirty, "python": sys.version.split()[0], "sandboxed": os.environ.get("ANONIMIZER_SBX") == "1",
                  "tests": counts, "steps": steps, "statement": STATEMENT}
        with open(os.path.join(out, f"gate-report-{mode}.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
            fh.write("\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
