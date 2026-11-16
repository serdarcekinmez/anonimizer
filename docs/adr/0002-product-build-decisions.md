# ADR 0002: Decisions taken during the Mode B product build

- Status: taken by the implementer under the owner's product build directive of 2026-11-16; open to owner review
- Date: 2026-11-16
- Supersedes: the Phase 0 "no application code" rule and the one-step-one-commit plan in `architecture.md`

The owner asked for a working Mode B product in one session and authorised ordinary engineering decisions within the approved architecture. This record lists every place where the build departs from, narrows or completes architecture v0.4 / v0.4.1.

## Decisions

| # | Topic | Decision | Reason | Architecture reference |
|---|---|---|---|---|
| 1 | Isolation | Project code runs through `tools/sbx`, a bubblewrap wrapper: read-only filesystem except the repository, home directory and `/mnt` hidden, no network unless `SBX_NET=1`. It refuses to run without bubblewrap | `bubblewrap` and `socat` are installed, but Claude Code's own sandbox was not enabled in the build session. The wrapper gives the same boundary, verified by probe, without bypassing anything | v0.4.1 item 8; `environment.md` |
| 2 | XLSX reading | Thin streaming reader over the sheet XML (standard library). openpyxl is used to write outputs and as an independent oracle in tests | openpyxl read-only mode does not expose the stored number text, and gives formula text or cached value but not both in one pass. The reader keeps stored text, storage type, number format and formula *presence* only | F5; v0.4.1 item 5 (custom reading only for a field no library delivers) |
| 3 | Formula text | Never retained, not even in the private profile | Smaller leak surface than "kept in the private layer" | B1 grid table |
| 4 | Grid sketch | Region detection streams the file once and keeps per-block column counts and the first 30 rows of each block in memory; there is no on-disk sketch | Simpler; memory stays bounded by block count, not row count | B1 "on-disk grid sketch" |
| 5 | Contract confirmation | Generation is allowed without a confirmed contract. The output is then `LOCAL_ONLY`. `RESTRICTED` needs a named person's confirmation, which is refused while a kept column is unreviewed | "A user may still work with appropriately labeled local-only outputs" (directive section 5). Blocking generation would make the first run impossible | Phase 3 acceptance; CNIL-04, CNIL-06. Finding F-003 |
| 6 | Columns kept by default | Columns are proposed as kept, not dropped | A test dataset that silently loses columns defeats schema fidelity. The fail-closed element is the tier, not the column | CNIL-06 row. Finding F-003 |
| 7 | Top tier | `EXTERNAL_CANDIDATE` is unavailable: a constant caps every derived tier at `RESTRICTED`, and the export gate refuses the tier outright | v0.4.1 item 6 makes attack-based evaluation a condition of the Phase 4 release. It is not implemented | D2; v0.4.1 item 6. Finding F-001 |
| 8 | Skeleton | Not built | F9 recommended no export; nothing else needed it | B, `skeleton/` |
| 9 | Mode A | Not built. `anonimizer transform` exists only to say so | "Leave that strategy explicitly unavailable rather than offering an unsafe approximation" | Phase 6 |
| 10 | Interface stack | Standard-library `http.server` with a single static page (no framework, no build step, no external resource) | Fewest moving parts; no telemetry by construction; every header under our control | Correction F; Phase 5 |
| 11 | Interface test | The page's script is executed in tests by QuickJS with a small test DOM against the real server | No browser automation is available in the sandbox. This is not a browser test. Finding F-007 | Phase 5 acceptance |
| 12 | Python version | Code runs on 3.10 and later; developed and tested on 3.12.16, seeded output verified identical on 3.10.12 | The owner's system Python is 3.10; independent verification should not need a toolchain install | Phase 0 step 4 |
| 13 | Seeded randomness | Own small generator over `getrandbits`, seeded from SHA-256 of (seed, table name) | `random.shuffle`, `choice` and `sample` are not guaranteed stable across Python versions | Phase 4 "byte-identical for same seed" |
| 14 | Row counts for several tables | The largest table gets the requested count; smaller tables keep their source size unless a count is given for them | A five-row lookup table should not become fifty rows | Not specified |
| 15 | Packing | `auto`: one scenario per row if the request allows it while leaving 20 % ordinary rows; otherwise pack step by step; otherwise cover by priority and report the rest | A row with several anomalies can hide all but the first from the application under test | Correction C (the architecture defaulted to packing, with `--isolate` as an option) |
| 16 | Private and shareable profiles | One profile with `_private` keys; `to_shareable` strips them and generalises under the policy. The contract can only be built from the shareable view | Mechanical, testable separation | Phase 2 |
| 17 | Value-coincidence handling | Coincident values are measured and reported; no value is redrawn because it matched the source | Redrawing would make the output depend on the source beyond the contract | v0.4.1 item 2 |
| 18 | Type checker | pyright was not set up | Time. ruff and the test suite are the static and dynamic checks | Phase 0 step 4 |
| 19 | CNIL source record | The page was fetched once on 2026-11-16 to record its normalised hash and section titles; the text is not stored | F2 | Phase 0 step 10 |
| 20 | Development MCP servers, agent teams | None used | As approved | A1 |

## Not done from Phase 0

Temporary logging-hook experiment (ADR 0001); `prompt_guard`, `session_check`, `format_file` and `stop_gate` hooks; `/anon-feature`, `/anon-adr`, `/anon-fixture`, `/anon-phase`, `/anon-cnil-refresh` skills (the refresh is a script, `tools/cnil_source.py`); WP216 ingestion; attack-library licence check; any `cnil-observer` run.

## Consequences

`python tools/gate.py --release` fails by design until the owner dispositions findings F-001, F-002 and F-003. The software is a working increment, not a release.
