# Phase 0 status

Phase 0 builds the development workshop and the compliance baseline. No application code is written in this phase. Only Phase 0 is authorized; later phases and any merge into `main` need the project owner's approval.

Last updated: 2026-11-12.

## Steps

| # | Step | Status | Output |
|---|---|---|---|
| 1 | Read-only environment survey | Done; one isolation condition failed | [environment.md](environment.md) |
| 2 | Read the official Claude Code documentation and record the assumptions the workshop relies on | Done, except the hook logging experiment | [adr/0001-claude-code-assumptions.md](adr/0001-claude-code-assumptions.md) |
| 3 | Repository: init, connect to GitHub, branch, `.gitignore`, README | Done | This branch |
| 4 | Python skeleton: project file, package, ruff, pyright, pytest, import rules | **On hold** | — |
| 5 | `tools/scan_repo.py`, `tools/gate.py` with tests | On hold | — |
| 6 | `CLAUDE.md`, `.claude/settings.json`, rules `privacy.md`, `compliance.md` | On hold | — |
| 7 | Phase 0 hooks with tests | On hold | — |
| 8 | pre-commit and `ci.yml` | On hold | — |
| 9 | Documents: requirements, threat model, classification, limitations, ADRs for decisions F1–F12 | On hold | Architecture already published: [architecture.md](architecture.md) |
| 10 | Compliance baseline: CNIL source record, requirements, traceability matrix, findings register, `check_rtm.py` | On hold | — |
| 11 | `review-protocol`, `cnil-observer`, `/anon-cnil`, `/anon-cnil-refresh`, `/anon-feature`, `/anon-gate`, `/anon-adr` | On hold | — |
| 12 | Acceptance drills and Phase 0 report for owner sign-off | On hold | — |

## Open blocker

The approved plan makes the existing WSL2 environment acceptable only with a verified, fail-closed shell sandbox. The sandbox needs the `bubblewrap` and `socat` packages. Both are missing, and installing them needs the owner's password:

```
sudo apt-get install bubblewrap socat
```

Until then, steps 4–12 stay on hold. They install tools and run project code, and the owner's instruction is not to bypass the isolation requirement.

## Not done in step 2

The planned experiment (a temporary logging hook capturing real hook input from the main session and from a subagent) needs a separate Claude Code session. Hook tests in step 7 will use inputs built from the documented schema until it is run.

## Changes to the approved plan since approval

| Date | Change | Source |
|---|---|---|
| 2026-11-12 | Commits and pushes of verified, non-sensitive work to GitHub are authorized on the `phase-0-foundation` branch, with a pull request against `main`. This replaces "no push without confirmation" in [architecture.md](architecture.md). Merging still needs owner approval. | Owner instruction |
| 2026-11-12 | The workspace is the only directory used for the project. Other projects on the machine are not explored or read. Claude Code's own configuration may be read for verification. | Owner instruction |

## Evidence

No tests exist yet, so there are no test results to publish. Evidence for steps 1–3 is the two survey documents and this branch's history.
