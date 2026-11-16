# Phase 0 status

Superseded on 2026-11-16 by [status.md](status.md). Kept for the history of the plan.

On 2026-11-16 the owner replaced the Phase 0-only authorization with a product build directive: implement Mode B end to end in one session, keeping the approved architecture and its security constraints. The steps below show where each Phase 0 item stands after that build.

| # | Step | Status |
|---|---|---|
| 1 | Read-only environment survey | Done, updated: [environment.md](environment.md) |
| 2 | Claude Code assumptions | Done except the hook logging experiment: [adr/0001-claude-code-assumptions.md](adr/0001-claude-code-assumptions.md). Settings keys re-checked against the published settings schema on 2026-11-16 |
| 3 | Repository, branch, `.gitignore`, README | Done |
| 4 | Python project, package, ruff, pytest, import rules | Done. pyright not set up |
| 5 | `tools/scan_repo.py`, `tools/gate.py` with tests | Done |
| 6 | `CLAUDE.md`, `.claude/settings.json`, rules | Done. Rules: privacy, compliance, parsing, testing. Settings untested in a live session |
| 7 | Hooks with tests | Partial: `guard_paths`, `guard_commit`. Not written: `session_check`, `prompt_guard`, `format_file`, `stop_gate` |
| 8 | pre-commit and `ci.yml` | Written. CI has not run (nothing was pushed from this environment) |
| 9 | Documents | Threat model, classification, limitations, ADR 0002. One ADR covers the build's decisions instead of one per F-item |
| 10 | Compliance baseline | Source record with hash, requirements, matrix, findings register, `check_rtm.py`. WP216 not ingested; no attack-library licence check |
| 11 | Reviewers and skills | `review-protocol`, `cnil-observer`, `privacy-auditor`, `fidelity-reviewer`, `/anon-gate`, `/anon-cnil`, `/anon-review`. Not written: `corpus-builder`, `/anon-feature`, `/anon-adr`, `/anon-fixture`, `/anon-phase`, `/anon-cnil-refresh` (a script, `tools/cnil_source.py`, does the refresh) |
| 12 | Acceptance drills and sign-off | Not done. No reviewer has run; the owner has not signed off |

## The blocker of 2026-11-12

`bubblewrap` and `socat` are installed now. Claude Code's own sandbox was still not active in the build session, so project code ran through `tools/sbx`, a bubblewrap wrapper that fails closed. See [environment.md](environment.md) and ADR 0002 item 1.
