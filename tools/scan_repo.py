"""Repository scan: data files, secrets, machine paths, large files, forbidden claims.

Used by the gate, the commit hook, pre-commit and CI. Reads tracked and staged files only.
Exit status 1 when a finding exists. Findings never quote file contents beyond a rule name.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_EXT = (".csv", ".tsv", ".xlsx", ".xlsm", ".xls", ".xlsb", ".parquet", ".sqlite", ".db", ".json.gz", ".zip")
FIXTURE_DIRS = ("tests/fixtures/", "tests/corpus/", "tests/adversarial/")
MAX_BYTES = 1_000_000
SECRET_RULES = [
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("API key assignment", re.compile(r"(?i)\b(?:api[_-]?key|secret|passwd|password|token)\b\s*[:=]\s*['\"][A-Za-z0-9/+_\-]{20,}['\"]")),
    ("Anthropic or OpenAI key", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{24,}\b")),
]
PATH_RULES = [
    ("home directory path", re.compile(r"/home/(?!runner\b|user\b|<)[a-z_][a-z0-9_-]{2,}/")),
    ("Windows user path", re.compile(r"[A-Za-z]:\\\\?Users\\\\?[A-Za-z0-9._-]+")),
    ("mounted Windows drive", re.compile(r"/mnt/[a-z]/[A-Za-z]")),
]
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@(?!example\.(?:com|org|net)\b|users\.noreply\.github\.com\b|anthropic\.com\b)"
                   r"[A-Za-z0-9.-]+\.(?:com|org|net|fr|io|dev)\b")
# Wording the product must never use about its outputs (CNIL-03). Negations such as
# "not a certification" are fine; these patterns target positive claims only.
CLAIM_RULES = [
    ("certification claim", re.compile(r"(?i)\b(?:cnil|gdpr|rgpd)[- ](?:certified|compliant|approved)\b")),
    ("certification claim", re.compile(r"(?i)\bcertified (?:anonym|by the cnil)")),
    ("anonymity guarantee", re.compile(r"(?i)\b(?:guaranteed?|fully|truly|100 ?%) anonym")),
    ("anonymity guarantee", re.compile(r"(?i)\bguarantees? (?:legal )?anonymity\b")),
]
CLAIM_EXEMPT = ("tools/scan_repo.py", "tests/", "docs/compliance/cnil/", "docs/architecture.md")
TEXT_EXT = (".py", ".md", ".txt", ".toml", ".yaml", ".yml", ".json", ".js", ".html", ".css", ".cfg", ".ini", ".sh", "")


def _git(*args: str) -> list[str]:
    out = subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True, check=False)
    return [x for x in out.stdout.split("\0") if x] if out.returncode == 0 else []


def tracked(staged_only: bool = False) -> list[str]:
    if staged_only:
        return _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    files = set(_git("ls-files", "-z")) | set(_git("ls-files", "--others", "--exclude-standard", "-z"))
    return sorted(files)


def registered_fixtures() -> set[str]:
    path = os.path.join(ROOT, "tests", "fixtures", "MANIFEST.yaml")
    out: set[str] = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"\s*-?\s*path:\s*(\S+)", line)
                if m:
                    out.add(m.group(1))
    return out


def scan(files: list[str]) -> list[str]:
    findings: list[str] = []
    fixtures = registered_fixtures()
    for rel in files:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        low = rel.lower()
        size = os.path.getsize(path)
        if size > MAX_BYTES:
            findings.append(f"{rel}: file larger than {MAX_BYTES} bytes")
        if low.endswith(DATA_EXT):
            if not rel.startswith(FIXTURE_DIRS):
                findings.append(f"{rel}: data file outside the fixture directories")
            elif rel not in fixtures:
                findings.append(f"{rel}: fixture not registered in tests/fixtures/MANIFEST.yaml")
            continue
        if os.path.splitext(low)[1] not in TEXT_EXT or size > MAX_BYTES:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except (UnicodeDecodeError, OSError):
            continue
        for name, rx in SECRET_RULES:
            if rel != "tools/scan_repo.py" and not rel.startswith("tests/") and rx.search(text):
                findings.append(f"{rel}: possible secret ({name})")
        if rel != "tools/scan_repo.py" and not rel.startswith(("tests/unit/test_hooks", "tests/unit/test_tools")):
            for name, rx in PATH_RULES:
                for i, line in enumerate(text.splitlines(), start=1):
                    if rx.search(line):
                        findings.append(f"{rel}:{i}: machine-specific path ({name})")
                        break
            m = EMAIL.search(text)
            if m and not rel.startswith("tests/"):
                findings.append(f"{rel}: e-mail address that is not a reserved example address")
        if not rel.startswith(CLAIM_EXEMPT):
            for i, line in enumerate(text.splitlines(), start=1):
                for name, rx in CLAIM_RULES:
                    if rx.search(line):
                        findings.append(f"{rel}:{i}: forbidden wording ({name})")
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--staged", action="store_true", help="scan staged files only")
    args = ap.parse_args(argv)
    files = tracked(args.staged)
    findings = scan(files)
    for f in findings:
        print(f"scan_repo: {f}")
    print(f"scan_repo: {len(files)} file(s) scanned, {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
