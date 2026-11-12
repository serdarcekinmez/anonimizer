# Development environment survey

Phase 0, step 1. Read-only survey taken 2026-11-12, re-checked the same day. Re-run after any environment change. Machine-specific paths and names are left out because this repository is public.

## Observed

| Item | Value |
|---|---|
| OS | Ubuntu 22.04.5 LTS on WSL2, systemd enabled |
| Workspace | `~/projects/anonimizer`, ext4 inside the distribution (not under `/mnt`) |
| Claude Code | 2.1.322 |
| Python | 3.10.12 (system). The project targets 3.12+, to be provided by `uv` |
| git | 2.34.1 |
| Present | `rg`, `git`, `python3` |
| Missing | `bwrap` (bubblewrap), `socat`, `uv`, `ruff`, `pre-commit`, `gh` |
| sudo | Requires a password; cannot be used non-interactively |
| Windows drives | Mounted under `/mnt` (9p); WSL interop enabled |
| `/etc/wsl.conf` | Only `[boot] systemd=true`; automount and interop at defaults |
| Other projects | Sibling project directories exist in the same home directory. They are out of scope and are not read |
| Data-like files nearby | Present in a sibling project (contents not opened) |
| User-level Claude Code settings | Exist; contents not inspected |

## Isolation conditions

| Condition | Status | What is needed |
|---|---|---|
| Sandbox available | **Not met** | `bubblewrap` and `socat` are not installed. Owner runs `sudo apt-get install bubblewrap socat` |
| Sandbox fails closed | Not yet configurable | `sandbox.enabled` and `sandbox.failIfUnavailable` in project settings, after the packages exist |
| Sandboxed commands cannot read `/mnt` or other home content | Not met | `sandbox.filesystem.denyRead` / `allowRead` in project settings |
| Read tool cannot read `/mnt` or sibling projects | Not met | `Read` deny rules plus the `guard_paths` hook |
| No data-like files in the workspace | Met | Workspace holds documentation only |
| Bypass mode disabled | Not met | `permissions.disableBypassPermissionsMode: "disable"` |
| Real data kept away from the workspace | Met by instruction | Owner rule: only synthetic data in the workspace; other projects are not accessed |

Until the first condition is met, shell commands run unsandboxed and the boundary rests on working rules only. Phase 0 steps that install tools or run project code are on hold for that reason (see `phase-0-status.md`).
