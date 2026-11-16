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
| Claude Code's own shell sandbox active | **Not active in the build session.** A probe write outside the workspace succeeded and `/mnt` was listable | Project settings now enable it (`.claude/settings.json`); it takes effect in the next session. Verify with the probes below |
| Project code runs isolated | Met, by another route | Every install, test and tool run of the build went through `tools/sbx` (bubblewrap): read-only filesystem except the repository, home directory and `/mnt` replaced by empty directories, no network unless `SBX_NET=1` |
| Wrapper fails closed | Met | `tools/sbx` exits with status 97 if bubblewrap is missing; `tools/gate.py` refuses to run outside it |
| Read tool cannot read `/mnt` or sibling projects | Configured, untested in a live session | `permissions.deny` rules and the `guard_paths` hook (unit-tested against the documented hook input) |
| No data-like files in the workspace except registered fixtures | Met | `tools/scan_repo.py`, run by the gate |
| Bypass mode disabled | Configured, untested in a live session | `permissions.disableBypassPermissionsMode` |
| Real data kept away from the workspace | Met by instruction | Owner rule |

## Probes to run in a new session

```
touch ~/.anonimizer_probe && echo "NOT sandboxed" || echo "write outside the workspace denied"
ls /mnt/c >/dev/null 2>&1 && echo "NOT sandboxed" || echo "/mnt hidden"
tools/sbx bash -c 'ls /mnt | wc -l; ls ~ | wc -l'      # both 0 inside the wrapper
```

If the first two print "NOT sandboxed", the session sandbox is not active. Use `tools/sbx` for everything and check `/sandbox` in Claude Code.

## Consequence of the session sandbox for copies to Windows

With the sandbox on, shell commands cannot write under `/mnt`. Copying the repository to a Windows folder then has to be done from Windows (for example `git pull` in the Windows clone) or by the owner in a plain terminal.
