# Product status

Version 0.1.0, built on 2026-11-16 under the owner's product build directive. This page says what exists, how far each part goes, what was actually run, and what to do next. It replaces `phase-0-status.md` as the current status.

**This is a working first increment, not a release.** It has had no independent review; the fixtures, the detector and the tests share one author. `tools/gate.py --release` fails by design because three high findings await the owner's decision.

## What works

A Mode B run, from the command line or the local interface: read a CSV, TSV or XLSX file, detect and correct tables, profile every cell, build the Exception Catalogue, propose a Dataset Contract, generate a chosen number of synthetic rows with explicit exception scenarios and fictional keys, write the Scenario Manifest, coverage report, before and after reports and comparison, assess the output against the source, and export a labelled bundle.

## Modules

| Module | State | Notes |
|---|---|---|
| `grid` (CSV, XLSX readers) | Implemented | Streaming; quoting, emptiness kinds, storage types, number formats, formula presence; zip and DTD guards. No `.xls`/`.xlsb` |
| `regions`, `recipe` | Implemented | Blank-row and blank-column separation, intro rows, header guess with confidence, merge of a table split by blank rows, user-defined boundaries. Limits in `known-limitations.md` |
| `patterns` | Implemented | Missing kinds, markers, numbers in 12 notations, dates in 16 layouts with validity, booleans, text kinds and layouts |
| `profile` | Implemented | Full scan, Exception Catalogue, key roles, references between tables of one file, private and shareable views |
| `policy` | Implemented | `internal-dev`, `external-strict`; no default; release cap |
| `contract` | Implemented | Contract v1, validation, category approval, confirmation |
| `synth` | Implemented | Generators per pattern class, coverage planner (auto, isolate, packed), manifest, key and reference behaviour |
| `privacy` | Partial | Closest-record, row equality, identifier overlap against control samples, quasi-identifier replication, report scan, tier derivation. No attack-based evaluation |
| `export` | Implemented | CSV and XLSX writers, layout reproduction, export gate, release register |
| `reports` | Implemented | Source and generated summaries, comparison, Markdown report |
| `pipeline`, `cli` | Implemented | `inspect`, `profile`, `contract`, `generate`, `check-record`, `policies`, `ui` |
| `ui` | Implemented, lightly verified | Loopback server and one page. Server tested; script run in an embedded JavaScript engine, not in a browser |
| `skeleton` | Not built | Decision F9: no skeleton export |
| `transform` (Mode A) | Not built | The command only states that it is unavailable |
| Mode C | Not started | No specification written |
| `mcp_server` | Not built | Optional in the architecture |

## Phases of the approved architecture

| Phase | State | What is missing |
|---|---|---|
| 0 Workshop and compliance baseline | Partial | Hook logging experiment; `prompt_guard`, `session_check`, `format_file`, `stop_gate` hooks; several skills; WP216 ingestion; attack-library licence check; a `cnil-observer` run; live verification of the session sandbox and of the hooks; pyright |
| 1 Grid, regions, recipe, skeleton | Mostly done | Corpus of 25 irregular files (22 fixtures exist: 3 with ground truth, 19 parser goldens); skeleton; reviewer runs |
| 2 Profile and policy | Done for Mode B | Composite keys; value-based numeric outliers |
| 3 Contract | Done with a recorded deviation | See ADR 0002 items 5 and 6, finding F-003 |
| 4 Mode B release | Partial | Attack-based evaluation; `cnil-observer` release assessment; `gate.py --release` green |
| 5 Interface | Done in substance | Real-browser test |
| 6 Mode A | Not started | Everything |
| 7 Mode C specification | Not started | Everything |

## What was run, and the results

All commands ran inside the bubblewrap wrapper (`tools/sbx`) on 2026-11-16.

| Check | Result |
|---|---|
| Test suite, Python 3.12.16 | 294 passed, 1 skipped (the opt-in large-file check) |
| Test suite, Python 3.10.12 | 294 passed, 1 skipped |
| Seeded output identical on 3.10 and 3.12 | Yes (pinned digest test) |
| Lint (`ruff check src tests tools .claude`) | Clean |
| Repository scan | 0 findings |
| Traceability matrix check | 0 errors: 6 rows implemented, 12 partial, 3 planned, 1 not applicable |
| `gate.py --full` | See `docs/evidence/gate-report-full.json` |
| `gate.py --release` | **Fails by design**: findings F-001, F-002, F-003 are high and not dispositioned |
| Detection against ground truth | 27/27, 20/20 and 25/25 planted classes found with exact counts on the three fixtures |
| Product-value demonstration | Planted classes present in Anonimizer's output: 26/27, 20/20, 24/25. In the plain mock generator's output: 1, 1, 0. See `docs/evidence/product-value-demo.md` |
| Large file (`pytest --runslow tests/bench`) | Passed. 2,000,000 rows x 10 columns (186 MB CSV): full run in 74.6 s, peak memory 257 MB; the single text value planted at row 1,950,002 of the numeric column was found; 31/31 scenarios covered; assessment passed |
| Session sandbox of Claude Code | Not active during the build; see `environment.md` |
| Push to GitHub | See the delivery report of the build session; this environment has no GitHub credentials |

Tests by area: readers and classifier, recipes and regions, profiler, contract, generator and planner, golden parser fixtures (19 files), ground truth (3 fixtures), generated-data checks, canary and leak tests, privacy assessment (negative and positive), determinism, offline operation, architecture rules, properties (hypothesis), command line, interface server and script, gate tools, hooks.

Not run: any reviewer agent; any real-browser test; mutation testing; the tools on a file that was not written by this project.

## Open findings

`docs/compliance/findings.yaml`: F-001 no attack-based evaluation (high), F-002 WP216 not ingested (high), F-003 columns kept by default (high, owner decision), F-004 names copied without enforced review, F-005 no observer assessment, F-006 exact small counts under `internal-dev`, F-007 interface not exercised in a browser.

## Continue from here, in this order

1. **Owner decisions.** Disposition F-001, F-002 and F-003 in `docs/compliance/decisions/`, and accept or change ADR 0002.
2. **Independent review.** Run `/anon-review` and `/anon-cnil release` (or the planned external review). Treat the fixtures' agreement with the detector as the weakest evidence in the repository.
3. **Try it on files the project did not write** (still synthetic or public): the detection limits in `known-limitations.md` are the ones known so far.
4. **Browser pass of the interface**, then a browser-driven test.
5. **Verify the session sandbox and hooks** in a new Claude Code session with the probes in `environment.md`.
6. **Attack-based evaluation** on synthetic source populations, as a development dependency after a licence check. Only then reconsider `RELEASE_TIER_CAP`.
7. **Header and name review** as an explicit contract decision (F-004).
8. **Detection depth:** composite keys, value-based numeric outliers, cross-column rules as optional scenarios, located duplicate rows, footers.
9. **Mode A**, one strategy at a time, each with its negative and positive tests, starting with the assessment code it shares with Mode B.
10. **Mode C specification**, reviewed for inference risk before any build.
