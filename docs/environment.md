# Development environment

Survey of 2026-11-12, updated 2026-11-16. Machine-specific paths and names are left out because this repository is public.

## Observed on 2026-11-16

| Item | Value |
|---|---|
| OS | Ubuntu 22.04 on WSL2 |
| Workspace | Inside the distribution's own filesystem (not under `/mnt`) |
| Claude Code | 2.1.325 (VS Code extension) |
| System Python | 3.10.12 |
| Project Python | 3.12.16, installed by `uv` into `.tools/` inside the repository (ignored by git) |
| `bubblewrap` | 0.6.1, installed |
| `socat` | 1.7.4.1, installed |
| `uv`, `ruff`, `pytest`, `hypothesis` | Installed into the project environment (`.tools/`, `.venv/`) |
| `gh` | Not installed |
| GitHub credentials for git | None in this environment; pushes fail at the credential prompt |
| Node.js or a headless browser usable from the sandbox | None; the interface script is run by QuickJS in tests |

## Isolation conditions

| Condition | Status on 2026-11-16 | How |
|---|---|---|
| Sandbox dependencies present | Met | `bubblewrap` and `socat` are installed |
| Claude Code's own shell sandbox active | **Active since `.claude/settings.json` was written at the end of the build session.** Before that it was off: a probe write outside the workspace had succeeded and `/mnt` was listable | Observed afterwards in the same session: the home directory is read-only, a shell command that names `/mnt` is refused by the deny rule, network goes through the filtering proxy, and the full gate passes inside it |
| Project code runs isolated | Met | Outside a session sandbox, `tools/sbx` builds its own bubblewrap sandbox: read-only filesystem except the repository, home directory and `/mnt` replaced by empty directories, no network unless `SBX_NET=1`. The whole build ran this way. Inside the session sandbox bubblewrap cannot nest, so `tools/sbx` checks that it is in a user namespace with a read-only home directory and then runs the command directly |
| Wrapper fails closed | Met | `tools/sbx` exits with status 97 if neither mode applies; `tools/gate.py` refuses to run outside it |
| Read tool cannot read `/mnt` or sibling projects | Configured, untested in a live session | `permissions.deny` rules and the `guard_paths` hook (unit-tested against the documented hook input) |
| No data-like files in the workspace except registered fixtures | Met | `tools/scan_repo.py`, run by the gate |
| Bypass mode disabled | Configured, untested in a live session | `permissions.disableBypassPermissionsMode` |
| Real data kept away from the workspace | Met by instruction | Owner rule |

## Checks to run in a new session

```
tools/sbx python -c "print('wrapper ok')"       # must print; exit status 97 means no isolation was found
tools/sbx python tools/gate.py --fast
```

In Claude Code, `/sandbox` shows whether the session sandbox is on. To switch it off, remove the `sandbox` block from `.claude/settings.json`; `tools/sbx` then goes back to its own bubblewrap sandbox.

Not verified: that the `Read` deny rules and the `guard_paths` hook block the Read tool in a live session (the hook is unit-tested against the documented input format only).

## Consequence of the session sandbox for copies to Windows

With the sandbox on, shell commands can neither read nor write under `/mnt`. Copying the repository to a Windows folder then has to be done from Windows (for example `git pull` in the Windows clone) or by the owner in a plain terminal.
