# ADR 0001: Claude Code assumptions the workshop relies on

- Status: accepted for Phase 0
- Date: 2026-11-12
- Checked against: official docs at `code.claude.com/docs/en/` (hooks, sub-agents, skills, env-vars, sandboxing, permissions, settings, settings-reference, memory, commands), Claude Code 2.1.322

Several pages are long and were partly read through extracted summaries. Rows marked "summary" rest on that and should be re-checked the first time the behaviour matters.

## Resolved

| Topic | Finding | Consequence for the design |
|---|---|---|
| Name collisions | `/verify` and `/run` are bundled skills. No `anon-*` name, `/gate`, `/feature`, `/adr`, `/phase` or `/domain-review` is on the commands page. A project skill with a bundled or built-in name replaces it (not its aliases). | Keep the `anon-` prefix. |
| Subagent nesting | Subagents can spawn subagents by default, three layers below the main conversation. `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` (default 3, `1` disables, v2.1.217+) can be set under `env` in settings. Omitting `Agent` from `tools` stops one subagent from spawning. (summary) | Set depth to `1` in project settings and omit `Agent` from every custom agent. |
| Subagent tools | `tools` is an allowlist; if omitted, every subagent-available tool is inherited, including MCP tools. | Every custom agent declares `tools` explicitly. |
| Subagent `memory` | Enables Read, Write and Edit automatically. (summary) | Not used for reviewers. |
| Subagent `permissionMode` | Honoured only conditionally; the parent's mode wins in several cases. | Nothing depends on it. |
| Subagent `skills` | Full skill content is injected at startup. A skill with `disable-model-invocation: true` cannot be preloaded. | `review-protocol` must not set `disable-model-invocation`. |
| Hook blocking | `PreToolUse`: exit 2, or `hookSpecificOutput.permissionDecision` = `deny`. `UserPromptSubmit`: exit 2 or `decision: block`. `Stop`: exit 2 or `decision: block`, `stop_hook_active` input field, cap of 8 consecutive continuations. `SessionStart`: cannot block; adds context. | Matches the design. `stop_gate` must read `stop_hook_active`. |
| Hook `if` | One permission rule, tool events only, best-effort. | `guard_commit` is a convenience; pre-commit and CI are the enforcement. |
| Hook config | `hooks` → event → `[{matcher, hooks: [{type: "command", command}]}]`; `${CLAUDE_PROJECT_DIR}` available. | As designed. |
| Sandbox prerequisites | Linux and WSL2 need `bubblewrap` and `socat`. | Blocker recorded in `docs/environment.md`. |
| Sandbox keys | `sandbox.enabled`, `sandbox.failIfUnavailable`, `sandbox.autoAllowBashIfSandboxed`, `sandbox.allowUnsandboxedCommands`, `sandbox.excludedCommands`, `sandbox.filesystem.{allowWrite,denyWrite,denyRead,allowRead}`, `sandbox.network.{allowedDomains,deniedDomains,strictAllowlist}`. On Linux only a trailing `/**` wildcard works for write lists. | Use `denyRead: ["~/", "/mnt"]` with `allowRead: ["."]`, `allowUnsandboxedCommands: false`, `strictAllowlist: true`. |
| Sandbox scope | Covers shell commands only. Read, Edit, Write, WebFetch, hooks and MCP servers run outside it. `Read` deny rules are merged into `denyRead`. | Read-tool boundary needs permission rules and `guard_paths`. |
| Permission paths | `//path` absolute, `~/path` home, `/path` relative to the settings file's project, `path` relative to cwd. Order: deny, ask, allow. `!` carve-outs cannot reopen a directory denied as a whole. | Deny `Read(//mnt/**)`; do not deny a parent of the workspace. |
| Mode keys | `permissions.disableBypassPermissionsMode: "disable"`; `permissions.defaultMode`. | As designed. |
| WebFetch rules | `WebFetch(domain:example.com)`; `*.example.com` does not match the apex. | Allow `cnil.fr`, `www.cnil.fr`, `code.claude.com`. |
| Rules files | `.claude/rules/*.md` with `paths:` list frontmatter; without `paths` they load at launch. | As designed. |
| Skill fields | `disable-model-invocation`, `user-invocable`, `context: fork`, `agent`, `allowed-tools`, `paths`, `hooks`, `argument-hint` exist. (summary) | As designed. |

## Unresolved, with fallback

| Topic | State | Fallback in force |
|---|---|---|
| `agent_id` / `agent_type` on `PreToolUse` | Documented as common fields identifying a subagent, but the page is inconsistent about which events carry them. | No access-control decision uses them. |
| Preloading a `user-invocable: false` skill into a subagent | Not stated. | If preload fails, `review-protocol` becomes a normal skill and reviewers read it from the repository. |
| Rules and `CLAUDE.md` inside subagents | Not stated on the memory page. | Reviewers get their rules through `review-protocol` and explicit file reads. |
| Whether hook edits apply to a running session | Summary says a file watcher picks them up. | Restart the session after changing hooks. |

## Not done

The planned local experiment (a temporary logging hook capturing real `PreToolUse` input from the main session and a subagent) was not run. It needs a separate Claude Code session. Hook tests in step 7 will use inputs built from the documented schema until it is run.
