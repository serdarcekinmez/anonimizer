# Anonimizer — Technical Architecture v0.4 (CNIL observer, privacy verification, final review)

## Context

v0.3 defined the product pipeline and the Claude Code workshop. v0.4 adds a CNIL-grounded compliance observer, turns CNIL's guidance into a traceability matrix wired into the existing gate, and corrects seven v0.3 weaknesses (Mode A limited to HMAC, lossy grid, coverage policy, "safe" skeleton, fixed threshold 10, over-strict network rule, `/verify` collision). This document is architecture only. Nothing has been created, installed or executed.

**What was verified in this session**

| Item | Result |
|---|---|
| CNIL source | Fetched in full from `https://www.cnil.fr/fr/technologies/lanonymisation-de-donnees-personnelles` (HTTP 200, dated 19 mai 2020, no update date). Section D quotes and paraphrases come from that fetch. |
| Referenced texts | G29/WP29 Avis 05/2014 (WP216) and CRPA art. L312-1-2 are listed by the page but were **not read**. Nothing here relies on their content. |
| Environment | cwd `~/projects/anonimizer`, ext4 inside WSL2 (kernel 6.18 microsoft-standard-WSL2), Claude Code 2.1.322. Directory is **empty and not a git repository**; no project `.claude/`. A user-level `~/.claude/settings.json` exists (not inspected). |
| Not verified | Ubuntu release, whether the Bash sandbox is active or its dependencies installed, VS Code extension version, contents of user settings. |
| Session continuity | This session does hold the v0.2/v0.3 conversation, but those turns ran in a different checkout (a git repo on an empty branch). Phase 0 must reconcile: clone `serdarcekinmez/anonimizer` into this path or `git init` and add the remote. |
| Claude Code docs | `code.claude.com` checked through search summaries of official pages, not full page reads. Unverified points are listed in section C6. |

---

## A. Architecture decision summary

### A1. Retained from v0.3

- Linear pipeline `grid → regions → recipe → profile → contract → {synth | transform} → privacy → export`, with import direction enforced.
- Mode B first; Mode A scalable by construction (streaming `grid` and `profile`); Mode C specification only.
- Dataset Contract v1 without formulas or business rules; key role (`unique`, `repeating`, `reference`) kept and user-confirmed.
- Exception Catalogue and scenario manifest.
- One deterministic gate script called by hooks, skills, pre-commit and CI.
- Layered development data boundary; real data never enters the Claude Code workspace.
- No development MCP servers, no agent teams, no `/loop`, no Workflow tool.
- Comprehensive UI in Phase 5.

### A2. Changed

| # | v0.3 | v0.4 | Reason |
|---|---|---|---|
| 1 | Label `ASSESSED-ANONYMIZED`; skeleton and synthetic shareable after checks | Three-axis classification (transformation class, assessment status, release tier). Top tier is `EXTERNAL_CANDIDATE`, never "anonymous". Human sign-off required. | CNIL places the demonstration on the controller; a tool cannot assert the legal conclusion. |
| 2 | Mode A = HMAC pseudonymization (+ optional k check) | Three Mode A strategies: pseudonymize, generalise/suppress/randomise with per-criterion assessment, synthetic at scale. Each has a tier cap. | Correction A. |
| 3 | `Cell(raw_text, origin)` | Lossless cell record with storage type, stored value, number format, formula presence, empty-kind, quoting and encoding flags; typed view is a separate, reversible layer. | Correction B. |
| 4 | "Reports uncovered patterns and required N" | Explicit coverage policy with priority classes, packing, `N_min`, and a coverage report. | Correction C. |
| 5 | Skeleton = `STRUCTURE-ONLY`, shareable | Skeleton is `LOCAL_ONLY` by default; export needs its own assessment. | Correction D. |
| 6 | Default category threshold 10 | Versioned `PrivacyPolicy` profiles; no implicit default; thresholds documented as necessary, not sufficient. | Correction E. |
| 7 | "No network calls" | No outbound or non-loopback traffic; loopback allowed only in `ui/`, hardened. | Correction F. |
| 8 | Skills `/verify`, `/feature`, … | All custom skills prefixed `anon-`. `/verify` is a bundled Claude Code skill (builds and runs the app); a same-named project skill would replace it. | Correction G. |
| 9 | privacy-auditor introduced in P2 | Introduced in P1 | Skeleton, logging and exceptions already exist in P1. |
| 10 | Privacy checks start in P4 | Compliance baseline (reference, RTM, observer, policy draft) in P0; checks grow per phase. | Tests must be designed against the requirements, not retrofitted. |

### A3. New components

| Component | Kind | Purpose |
|---|---|---|
| `cnil-observer` | Custom subagent (= the requested `observorAgent`) | Reviews methodology, traceability, evidence and claims against the CNIL reference. |
| `review-protocol` | Custom skill, preloaded into the three reviewers, not user-invocable | One finding schema, severity scale and evidence-citation rule shared by all reviewers. |
| `/anon-cnil` | Custom skill | Runs the observer for a scope (`architecture`, `tests`, `change`, `release`) and persists its report. |
| `/anon-cnil-refresh` | Custom skill | Re-fetches the CNIL page, compares the normalised hash, prepares a diff for human review. |
| `docs/compliance/` | Versioned reference | Source record, requirement interpretation, RTM, findings register, assessments, decisions. |
| `tools/check_rtm.py` | Custom script, called by the gate | Deterministic RTM integrity, staleness and release checks. |
| `source-watch.yml` | CI scheduled job (optional, P4) | Deterministic monthly hash check of the CNIL page; opens an issue on change. |
| `policy/` | Product module | `PrivacyPolicy` schema and shipped profiles. |
| Adversarial fixture families | Test data | Synthetic files that plant each CNIL risk. |

### A4. Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Merge the observer into privacy-auditor | Different inputs (policy, RTM, evidence versus code paths), different failure modes, and a merged checklist dilutes both. |
| Give the observer WebFetch or Write | A reviewer that can fetch and rewrite its own reference is not source-traceable. Fetching is a separate human-triggered step. |
| Subagent `memory:` for the reference | Documented to enable Read/Write/Edit automatically, which breaks read-only; memory is also not reviewable in pull requests. |
| Observer verdict as a gate | Model opinion is non-deterministic. The gate reads the human-dispositioned findings register instead. |
| LLM or observer logic at runtime | Violates the offline requirement and is not reproducible. |
| `/goal` on privacy checks | Optimising until privacy tests pass invites threshold gaming. |
| MCP server for CNIL or legal sources | A vendored, hashed file does the job with no added attack surface. |
| One universal anonymity metric | Contradicts the three-criteria structure and the residual-risk assessment. |

---

## B. Annotated architecture tree

Legend: **B** built-in · **C** custom · **R** required · **O** optional · **P#** phase introduced. "→" lists dependencies.

```
~/projects/anonimizer/                      (WSL2 ext4; never under /mnt)
│
├── CLAUDE.md                               C·R·P0  ≤200 lines: non-negotiables, layer map, gate command,
│                                                   claim-wording rule, pointer to docs/compliance
├── .claude/
│   ├── settings.json                       C·R·P0  permissions, sandbox, hook wiring (see C5)
│   ├── settings.local.json                 C·O     personal, gitignored
│   ├── rules/                              C·R     path-scoped (`paths:` frontmatter)
│   │   ├── privacy.md                      P0      src/**/{privacy,policy,export,skeleton,transform,synth}
│   │   ├── parsing.md                      P1      src/**/{grid,regions,recipe}
│   │   ├── testing.md                      P1      tests/**
│   │   └── compliance.md                   P0      docs/compliance/**: edit protocol, no paraphrase without source ref
│   ├── hooks/                              C
│   │   ├── session_check.py                R·P0    SessionStart: WSL2, cwd not /mnt, git repo, sandbox, CLI version
│   │   ├── prompt_guard.py                 R·P0    UserPromptSubmit: blocks pasted tabular data
│   │   ├── guard_paths.py                  R·P0    PreToolUse Read|Edit|Write|Bash: workspace and fixture boundary;
│   │   │                                           restricts corpus-builder writes by `agent_type`
│   │   ├── guard_commit.py                 R·P0    PreToolUse `if: Bash(git commit *)` → tools/scan_repo.py
│   │   ├── format_file.py                  R·P0    PostToolUse Edit|Write → ruff
│   │   └── stop_gate.py                    R·P1    Stop → tools/gate.py --fast
│   ├── skills/                             C
│   │   ├── anon-feature/                   R·P0    spec → acceptance tests → plan → test-first build (user-invoked)
│   │   ├── anon-gate/                      R·P0    runs tools/gate.py --full, summarises evidence
│   │   ├── anon-fixture/                   R·P1    synthetic fixture + ground truth + manifest entry → corpus-builder
│   │   ├── anon-review/                    R·P1    runs reviewers in parallel, merges, updates findings register
│   │   ├── anon-cnil/                      R·P0    runs cnil-observer for a scope, writes assessment record
│   │   ├── anon-cnil-refresh/              R·P0    re-fetch CNIL source, hash compare, diff for human review
│   │   ├── anon-phase/                     R·P1    phase acceptance report incl. RTM status and open findings
│   │   ├── anon-adr/                       O·P0    records an ADR; flags privacy-tagged ADRs for /anon-cnil
│   │   └── review-protocol/                R·P0    preloaded into reviewers; finding schema; not user-invocable
│   └── agents/                             C
│       ├── cnil-observer.md                R·P0    Read, Grep, Glob. Methodology, traceability, claims
│       ├── privacy-auditor.md              R·P1    Read, Grep, Glob. Concrete leak paths in code and outputs
│       ├── fidelity-reviewer.md            R·P1    Read, Grep, Glob, Bash(test runner). Loss, exceptions, determinism
│       └── corpus-builder.md               R·P1    Read, Write, Edit, Bash. Writes only tests/fixtures, tests/corpus
│
├── docs/
│   ├── requirements.md  architecture.md  threat-model.md                R·P0
│   ├── privacy-classification.md           R·P0    three-axis policy (D2)
│   ├── adr/                                R·P0
│   └── compliance/                         R·P0
│       ├── cnil/SOURCE.md                          URL, title, date, retrieval date, method, normalised SHA-256,
│       │                                           section list, referenced texts and their ingestion status
│       ├── cnil/requirements.yaml                  CNIL-01..16: section, short quote, interpretation, applicability
│       ├── rtm.yaml                                requirement → risk → component → control → tests → evidence → status
│       ├── findings.yaml                           register: id, category, severity, RTM row, status, disposition
│       ├── assessments/YYYY-MM-DD-<scope>.md       observer reports (immutable once committed)
│       └── decisions/                              signed human dispositions and release sign-offs
│
├── tools/                                  C
│   ├── gate.py                             R·P0    --fast | --full | --release; single entry point
│   ├── check_rtm.py                        R·P0    called by gate.py; RTM integrity, staleness, release rule
│   ├── scan_repo.py                        R·P0    unregistered data files, large files, secrets, forbidden claims
│   ├── parser_eval.py                      R·P1    region detection score vs corpus
│   └── bench.py                            R·P6    memory and throughput
│
├── .github/workflows/
│   ├── ci.yml                              C·R·P0  gate.py --full on push and PR; uploads evidence artifacts
│   └── source-watch.yml                    C·O·P4  monthly normalised-hash check of the CNIL page
├── .pre-commit-config.yaml                 C·R·P0  scan_repo.py for human commits
├── .mcp.json                               —       absent. No development MCP servers
│
├── src/anonimizer/                         C       product; offline; no Claude dependency
│   ├── grid/        R·P1  lossless streaming cell reader (CSV, XLSX) + on-disk grid sketch
│   ├── regions/     R·P1  table detection on the sketch → candidates with confidence        → grid
│   ├── recipe/      R·P1  ParseRecipe + typed view (reversible interpretation)              → grid, regions
│   ├── skeleton/    R·P1  shape-only diagnostic artifact, LOCAL_ONLY by default             → grid
│   ├── profile/     R·P2  private profile, Exception Catalogue, shareable profile           → recipe, policy
│   ├── policy/      R·P2  PrivacyPolicy schema, shipped profiles, attacker assumptions
│   ├── contract/    R·P3  Dataset Contract v1 (+ sensitivity, quasi-identifier, key role)   → profile
│   ├── synth/       R·P4  Mode B exception-driven generator, coverage planner               → contract
│   ├── privacy/     R·P4  per-criterion deterministic assessment, AssessmentRecord          → policy
│   ├── export/      R·P4  sole writer; enforces tier caps; scrubs metadata                  → privacy
│   ├── pipeline/    R·P4  mode orchestration                                                → all above
│   ├── cli/         R·P1  thin layer                                                        → pipeline
│   ├── ui/          R·P5  local interface, loopback only                                    → pipeline
│   ├── transform/   R·P6  Mode A strategies A1–A3                                           → contract, policy
│   └── mcp_server/  O·P8  serves only EXTERNAL_CANDIDATE datasets, local                    → export
│
└── tests/
    ├── fixtures/ + MANIFEST.yaml           R·P0  synthetic only, each file registered
    ├── corpus/                             R·P1  irregular files + ground truth
    ├── adversarial/                        R·P1+ planted-risk families (D4)
    └── unit/ property/ leak/ privacy/ determinism/ architecture/ offline/ bench/
```

**Built-in capabilities used:** plan mode (`/plan`), `/code-review` (alias `/review`), `/security-review`, `/rewind`, `/goal` (parser score and Mode A memory only), Bash sandbox, permission rules, Explore and Plan subagents, worktrees (optional).

### B1. Product corrections in detail

**Grid (correction B).** One record per cell; nothing is coerced at ingestion.

| Field | Content |
|---|---|
| Position | sheet, row, column, merged-range membership, hidden row/column flag |
| `raw_text` | CSV: decoded field exactly as written. XLSX: the stored XML value as text (no float round-trip) |
| `storage_type` | CSV: `text`. XLSX: number, shared string, inline string, boolean, error, date-typed, formula, blank |
| `number_format` | XLSX format code; workbook date system (1900/1904) at sheet level |
| `formula_present`, `formula_text`, cached value | Formula text stays in the private layer and is never exported |
| `empty_kind` | absent cell, present-but-empty, empty string, quoted-empty (`""` in CSV), whitespace-only |
| `error_code` | `#N/A`, `#DIV/0!` and similar |
| Encoding flags | undecodable bytes (byte offset kept), BOM, NUL, mixed newlines |

- Missing-marker literals (`N/A`, `NaN`, `-`, `null`) stay as text; classification happens in `profile`, driven by the recipe.
- The typed view is computed from raw cells plus recipe and can always be recomputed.
- Bounded memory: both readers stream rows. A first pass writes a compact on-disk **grid sketch** (per-cell coarse class code). Region detection runs on the sketch; extraction then streams each region.
- Workbook metadata (author, comments, defined names, hidden sheets, external links, validation lists) is inventoried in the private profile as a leak source and never copied to outputs.
- Input files are untrusted: zip-bomb limits, no external entity resolution, no macro execution.

**Mode B coverage policy (correction C).**

1. Scenarios come from the Exception Catalogue and key behaviour: missing-kind classes per column, invalid-format classes, duplicate rows, duplicate keys, repeat multiplicity (1, 2, many), dangling references, boundary numerics (zero, negative, bucketed extremes), rare pattern classes.
2. Priority classes order the scenarios; the user can pin or drop scenarios.
3. The planner packs compatible scenarios from different columns into one row (greedy cover). `--isolate` gives each scenario its own otherwise-clean row.
4. It computes `N_min_packed` and `N_min_isolated`.
5. If requested N is too small: generate by priority, write `coverage_report` listing every unrepresented scenario and the N needed, and exit non-zero when `--require-full-coverage` is set.
6. Literal values are copied only from a marker allowlist (built-in list plus user-approved additions). Anything else is reproduced as a pattern class with a synthetic stand-in.

**Mode A strategies (correction A).**

| Strategy | Operations | Transformation class | Tier cap |
|---|---|---|---|
| A1 Pseudonymize | Keyed HMAC on identifiers, per-release key | pseudonymized | `RESTRICTED` always |
| A2 De-identify | Drop direct identifiers; generalise quasi-identifiers through user-chosen hierarchies; top/bottom coding; rare-category merge; local suppression of residual small classes; optional noise or within-class swapping | generalised/randomised | `EXTERNAL_CANDIDATE` only if all three criteria pass under the selected policy and a human signs |
| A3 Synthetic at scale | Mode B generator from the shareable profile | synthetic | Same condition as A2 |

- A2 is two-pass: pass 1 counts quasi-identifier combinations with on-disk aggregation, pass 2 applies suppression. It uses fixed hierarchy levels and measures the result; it does not search for an optimal generalisation.
- If the policy cannot be met, the tool says so and emits nothing at the higher tier.
- Stated limitations: equivalence-class size does not address homogeneity or background knowledge; diversity measures do not address skewed distributions; sparse high-dimensional data may not be anonymisable with useful utility. Differential privacy is a future extension.

**Skeleton (correction D).** Default `LOCAL_ONLY`. Optional export requires length bucketing, header masking, rare-shape suppression, row-count rounding, metadata scrub, a skeleton-specific assessment, and user review. Recommendation for v1: no skeleton export at all (decision F9).

**PrivacyPolicy (correction E).** A versioned object selected explicitly per run. Parameters:
- Minimum equivalence-class size over confirmed quasi-identifiers.
- Maximum sensitive-attribute confidence within a class.
- Rare-category rule as count and fraction, with per-column sensitivity overrides.
- Numeric bound generalisation and outlier handling.
- Free-text handling.
- Minimum distance between a synthetic row and its closest source row.
- Skeleton bucketing.
- Attacker assumptions and listed external data sources.
- Review-by date.

Shipped profiles (`external-strict`, `internal-dev`) document their rationale and limits. Passing a profile is necessary for a tier, never sufficient for a legal conclusion.

**Runtime network (correction F).** Core modules may not import network client libraries (import rule). `ui/` may bind `127.0.0.1` only, on a random port with a per-session token, Host-header check and no wildcard CORS. Tests run with a socket guard that permits loopback only in `ui` tests.

---

## C. Agent and workflow design

### C1. Reviewer boundaries

| Agent | Question it answers | Inputs | Does not do |
|---|---|---|---|
| cnil-observer | Is each anonymity-related claim justified, traceable to the source, and backed by adequate tests and evidence? | `docs/compliance/**`, classification policy, threat model, ADRs, policy profiles, privacy test code and gate evidence | Hunt leak paths in code; judge parsing correctness; edit anything |
| privacy-auditor | Where can original data escape in this implementation? | `src/**`, export and logging code, generated outputs of synthetic fixtures | Interpret CNIL; decide tiers |
| fidelity-reviewer | Is anything lost, conflated or non-reproducible? | `grid`, `regions`, `recipe`, `profile`, `synth` code and tests | Any privacy judgment |

They stay separate agents, share the `review-protocol` skill, and are coordinated by `/anon-review`. Overlap is resolved by keying every privacy finding to an RTM row: the auditor reports "control X is broken here", the observer reports "row Y has no control, weak tests or an unsupported claim".

### C2. `cnil-observer` specification

| Aspect | Design |
|---|---|
| Location | `.claude/agents/cnil-observer.md` |
| Tools | `Read`, `Grep`, `Glob` only. Strictly read-only; no Bash, WebFetch, Write, MCP |
| Preloaded skill | `review-protocol` |
| Reference access | Reads `docs/compliance/cnil/SOURCE.md` and `requirements.yaml` at the start of every run. It must cite requirement IDs and may not rely on recalled CNIL or GDPR content. If the source hash in `SOURCE.md` is flagged stale, it reports `SOURCE-DRIFT` first. |
| Persistence | Everything it needs is in the repository, so any session or checkout reproduces the same context. No conversational or agent memory. |
| Output | Structured findings returned to the caller. `/anon-cnil` writes `assessments/YYYY-MM-DD-<scope>.md` (source hash, requirement-file version, commit, scope, findings) and appends to `findings.yaml`. |
| Finding categories | `DEFECT` (a control or automatable test is wrong or missing), `RISK` (residual privacy risk), `EVIDENCE-GAP` (claim without supporting artifact), `JUDGMENT` (needs a human decision), `SOURCE-DRIFT` |
| Severity | blocker, high, medium, low; each finding names the RTM row, the file and line of evidence, and the proposed remedy |
| Fixed checks | Pseudonymized or stably keyed output never treated as anonymous; the three criteria assessed separately; residual-risk reasoning present where a criterion is not fully met; no single-threshold reduction; review-by dates present; wording never claims certification |

### C3. Workflow

| Stage | Mechanism | Observer role |
|---|---|---|
| Session start | `session_check` | — |
| Architecture or ADR change | `/anon-adr`, then `/anon-cnil architecture` for privacy-tagged ADRs | Reviews design against requirements; updates expected RTM rows |
| Feature planning | `/anon-feature` in plan mode | For privacy-relevant features, `/anon-cnil tests` reviews the proposed tests against the RTM before code is written |
| Implementation | Edits under `guard_paths`, `format_file`; `stop_gate` runs `gate.py --fast` | — |
| Verification | `/anon-gate` → `gate.py --full` (includes `check_rtm.py`) | — (deterministic) |
| Review | `/code-review`, `/security-review` on sensitive modules, `/anon-review` | Runs in parallel with the other two reviewers when the diff touches privacy paths or `docs/compliance` |
| Commit and CI | `guard_commit`, pre-commit, `ci.yml` | — |
| Phase or release acceptance | `/anon-phase` → `/anon-cnil release` → `gate.py --release` | Full-scope assessment; report attached to the phase report |
| Source upkeep | `/anon-cnil-refresh` each release and at least quarterly; `source-watch.yml` | Re-assesses affected rows after a human accepts a source change |

`/anon-review` and `/anon-cnil` run in the main session context, because subagents cannot start other subagents *(verify)*.

### C4. Release rule

`gate.py --release` fails when any of these holds:
- An open finding of severity blocker or high has no disposition.
- A `DEFECT` of severity high or above is open. It cannot be waived; the fix is to repair the control or withdraw the claim or tier.
- A `RISK`, `EVIDENCE-GAP` or `JUDGMENT` of high severity lacks a signed entry in `docs/compliance/decisions/`.
- `SOURCE.md` is older than the policy's review interval or flagged as drifted.
- An RTM row marked `auto` has no passing test.

The gate reads the register and test results. It never reads a model verdict.

### C5. Settings intent (exact keys to confirm in Phase 0)

- Sandbox on, fail if unavailable; sandbox read denial for `/mnt/**` and home credential directories; network limited to package registries.
- Read deny for data extensions outside `tests/{fixtures,corpus,adversarial}`.
- `ask` on `Edit(docs/compliance/cnil/**)` and `Edit(docs/compliance/decisions/**)`; the reference changes only with explicit human approval.
- `WebFetch` allowed for `cnil.fr` and `code.claude.com` only.
- Bypass mode disabled. Auto mode only for sandboxed `/goal` runs.

### C6. Claude Code assumptions still to verify in Phase 0

| Assumption | Status |
|---|---|
| `/verify`, `/run`, `/debug`, `/batch` are bundled skills; a same-named project skill replaces a bundled one | Search-confirmed |
| `/plan` enters plan mode; `/review` is an alias of `/code-review` | Search-confirmed |
| Subagent `skills:` preloads full skill content; `tools:` is an allowlist | Search-confirmed |
| Subagent `memory:` enables Read/Write/Edit | Search-confirmed |
| Hook `if` field with permission-rule syntax, tool events only, best-effort | Search-confirmed |
| `WebFetch(domain:…)` rule syntax | Search-confirmed |
| `user-invocable: false` on a skill; preloading requires the skill not to set `disable-model-invocation` | Second half confirmed; field name unverified |
| Subagent `permissionMode` honoured | Docs conflict; not relied on |
| Path-scoped rules load inside subagents | Unverified; reviewers therefore get rules through `review-protocol` |
| No `anon-*` name collides with a built-in | Check `/help` in the installed version |
| Exact sandbox setting key names | Unverified |

---

## D. Privacy verification architecture

### D1. Principles

- Runtime enforcement is the deterministic `privacy/` engine plus the `export/` gate. Development-time agents review; they enforce nothing at runtime.
- A green gate means "the listed controls behaved as specified on the listed fixtures". It is not CNIL certification and not proof of legal anonymity. That sentence appears in every phase report and assessment record.
- All development tests use synthetic adversarial fixtures.

### D2. Output classification

| Axis | Values |
|---|---|
| Transformation class | structure-only, masked, pseudonymized, generalised/randomised, synthetic |
| Assessment status | none, failed, passed (policy id and version), expired |
| Release tier (derived) | `LOCAL_ONLY`, `RESTRICTED`, `EXTERNAL_CANDIDATE` |

Rules:
- Raw data and private profiles are never exported.
- Pseudonymized and masked outputs cap at `RESTRICTED` and are labelled as personal data.
- `EXTERNAL_CANDIDATE` requires all three criteria evaluated and passing under an explicit policy, plus a recorded human attestation.
- A criterion that is "not evaluable" (for example no quasi-identifiers confirmed) blocks `EXTERNAL_CANDIDATE`.
- Tier can only go down along a pipeline path, never up (property-tested).

Every output carries an **AssessmentRecord**: tool version, policy id and version, attacker assumptions, confirmed quasi-identifiers and sensitive attributes, per-criterion metrics and result, residual-risk statements, limitations, date, review-by date.

### D3. CNIL Requirements Traceability Matrix

Kind: **A** automated, **H** human review, **A+H** both. Initial status of all rows: `planned`.

| ID | CNIL source (section) | Interpretation for Anonimizer | Component | Control | Test or procedure | Kind | Evidence |
|---|---|---|---|---|---|---|---|
| CNIL-01 | Qu'est-ce que l'anonymisation: identification practically impossible, by any means, "de manière irréversible" | No retained mapping, key or seed may allow reversal of an external-tier output | transform, synth, export | Per-release keys destroyed or kept outside outputs; no source row indices or seeds in outputs | `privacy/test_no_reversal_material`; canary suite | A | Gate log |
| CNIL-02 | Same section: "ne doit pas être confondue avec la pseudonymisation"; pseudonymised data keep "un caractère personnel"; reversible | Stable identifiers are personal data regardless of other transformations | privacy, export | Tier cap on pseudonymized and masked classes; detector for stable 1:1 identifier mappings | `test_tier_caps` (property); `adv-pseudonym` must be classified pseudonymized | A | Gate log |
| CNIL-03 | Pourquoi anonymiser: data protection law "ne s'applique plus" once anonymised | The claim has legal weight, so wording is controlled | export, docs, ui | Forbidden-claim lint ("certified", "CNIL compliant", "guaranteed anonymous"); fixed disclaimer in records | `scan_repo` claim check; observer wording review | A+H | Scan log, assessment |
| CNIL-04 | Comment anonymiser, step 1: identify information to keep by relevance | Utility needs are declared before transformation | contract | Per-column keep/drop decision required | `test_contract_requires_keep_decision` | A | Gate log |
| CNIL-05 | Step 2: remove direct identifiers and rare values (centenarian example) | Direct identifiers never pass through; rare values and outliers handled by policy | profile, policy, synth, transform | Sensitivity class per column; rare-category and outlier rules | `adv-unique` (centenarian), `adv-rare-combo`: planted values absent from outputs and shareable profile | A | Gate log |
| CNIL-06 | Step 3: distinguish important from secondary information; delete what is useless | Minimisation by default | contract, export | Columns without a keep decision are dropped | `test_unconfirmed_columns_dropped` | A | Gate log |
| CNIL-07 | Step 4: define ideal and acceptable "finesse" per item | Granularity is an explicit, recorded choice | policy, contract | Generalisation level per quasi-identifier stored in the record | `test_record_contains_granularity`; observer checks rationale | A+H | AssessmentRecord |
| CNIL-08 | Randomisation: less precise attributes while keeping overall distribution; protects against inference | Randomisation controls must exist where inference risk is flagged, with utility impact reported | transform, synth | Noise or swapping options; before/after distribution comparison in the quality report | `test_randomisation_changes_records`; utility delta within stated bound | A | Quality report |
| CNIL-09 | Généralisation: change of scale; prevents individualisation, limits correlation | Generalisation hierarchies for dates, locations, numerics | transform | Hierarchy library; class-size measurement after generalisation | `test_generalisation_raises_min_class_size` on `adv-unique` | A | Gate log |
| CNIL-10 | Vérifier l'efficacité: individualisation (CV base example) | No record isolable on confirmed quasi-identifiers or on small column subsets | privacy | Class-size distribution; uniqueness rate; sampled subset-uniqueness search; for synthetic: exact-match and closest-source-record distance, replication of source-unique combinations | `adv-unique`, `adv-rare-combo`, `adv-small-n`: check must **fail** the planted file and pass after transformation | A+H | AssessmentRecord |
| CNIL-11 | Corrélation (address map example) | Records must not be linkable across releases, tables beyond declared need, or to listed external sources | privacy, transform, threat-model | Per-release keys; verbatim-value check on identifier-like columns; exact quasi-identifier combination check against a synthetic "external register" | `adv-linkable` (two tables plus external register): join rate must be zero or below policy; cross-release pseudonym test | A+H | AssessmentRecord, threat model |
| CNIL-12 | Inférence, "quasi-certitude" (tax survey example) | No sensitive attribute deducible with near certainty for a group or individual | privacy | Max sensitive-value confidence per class; group-homogeneity scan; for synthetic: check that conditional structure is not preserved unless assessed | `adv-homogeneous` (all men 20–25 share one value): check must fail the planted file | A+H | AssessmentRecord |
| CNIL-13 | Se prémunir: "évaluation approfondie" that risk by means "raisonnablement susceptibles d'être utilisés" is negligible | Where a criterion is not fully met, a written residual-risk assessment and attacker model are mandatory | privacy, docs | Record requires residual-risk statement and attacker assumptions when any criterion is partial; blocks top tier otherwise | `test_partial_criterion_requires_residual_statement`; observer reviews adequacy | A+H | AssessmentRecord, decision file |
| CNIL-14 | Same section: techniques evolve; "veille régulière" on means and data sources | Assessments expire; the reference and threat model are re-reviewed | policy, compliance docs | Review-by date in every record; expired status; source staleness check | `test_expired_assessment_downgrades_tier`; `check_rtm` staleness; `/anon-cnil-refresh` | A+H | Gate log, SOURCE.md history |
| CNIL-15 | Same section: a published "anonymous" dataset containing personal data may be a "violation de données"; withdraw promptly | Users need to identify and recall what was released | export, docs | Local release register (what, when, tier, record id); incident procedure in documentation | `test_release_register_written`; observer reviews procedure | A+H | Release register |
| CNIL-16 | Whole page addresses the "responsable de traitement" | The tool supports the controller's assessment and never substitutes for it | export, ui, docs | Human attestation required for top tier; disclaimer | `test_external_candidate_requires_attestation` | A+H | Decision file |
| REF-WP216 | Les textes de référence: Avis 05/2014 | Technique-level detail lives here; not yet ingested | compliance docs | Ingest with the same provenance procedure in P0, then extend rows 08–13 | Observer reports `EVIDENCE-GAP` until ingested | H | SOURCE.md |

Cross-cutting rows (linked to CNIL-01, -05, -10):

| ID | Risk | Control | Test | Kind |
|---|---|---|---|---|
| X-01 | Residual source values in synthetic output | Value-level non-membership for identifier and free-text columns; marker allowlist | Canary suite; `adv-canary` | A |
| X-02 | Sensitive free text or unexpected values in numeric or categorical columns | Pattern-class reproduction only | `adv-freetext-in-numeric`: planted string absent everywhere | A |
| X-03 | Leaks through reports, headers, logs, exceptions, metadata | Shareable profile; header review; message templates without values; fresh-file export | `adv-header-leak`, `adv-metadata`, `adv-formula`; canary scan of logs and exception text | A+H (header meaning is human) |
| X-04 | Skeleton shape disclosure | Local-only default; bucketing | `adv-skeleton-shape`: unique length pattern not recoverable | A+H |
| X-05 | Regression from later code changes | Privacy tests in `gate.py --full`; RTM-impact rule; expected-outcome snapshots for adversarial fixtures | `check_rtm`: a change under privacy paths must touch `rtm.yaml` or add a no-impact note | A |

### D4. Test strategy

| Layer | Content | Trigger |
|---|---|---|
| Negative tests | Each adversarial family carries a planted risk; the relevant check must detect it. This tests the checks themselves. | Full gate |
| Positive tests | After the configured transformation the same file passes, and utility deltas stay within stated bounds | Full gate |
| Property tests | Tier monotonicity; cap rules; planted-unique generators | Fast and full gate |
| Canary tests | Unique tokens absent from outputs, logs, reports, exceptions, metadata | Full gate |
| Snapshot tests | AssessmentRecord for each adversarial fixture matches the committed expectation | Full gate |
| RTM checks | `check_rtm.py`: every requirement has a control; every `A` row maps to existing tests carrying a `cnil("ID")` marker; no orphan markers; no "satisfied" without evidence | Fast (schema) and full gate |
| Mutation testing on `privacy/` and `export/` | Confirms tests kill seeded faults | Optional, manual, from P4 |
| Attack-based evaluation (singling-out, linkability, inference attacks on synthetic output) | Independent of our own metrics | Optional, P6; library choice open (F8) |

Adversarial families: `adv-unique`, `adv-rare-combo`, `adv-homogeneous`, `adv-linkable`, `adv-pseudonym`, `adv-freetext-in-numeric`, `adv-header-leak`, `adv-metadata`, `adv-formula`, `adv-skeleton-shape`, `adv-small-n`, `adv-canary`. Four reproduce the CNIL page's own examples (centenarian, CV base, address map, tax survey).

### D5. Automated versus human

| Automatically testable | Requires human review |
|---|---|
| Tier caps and monotonicity | Which columns are quasi-identifiers or sensitive |
| Class sizes, uniqueness, attribute confidence under a given policy | Whether the attacker model and external sources are realistic |
| Absence of planted values, canaries, metadata | Whether "negligible" residual risk is justified |
| Presence and expiry of assessment fields | Whether header names or layout are themselves sensitive |
| RTM integrity and source staleness | Whether a source change alters requirements |
| Forbidden wording | Final release attestation |

### D6. Evidence and failure handling

- Evidence per release: gate log, RTM snapshot, adversarial AssessmentRecords, observer assessment, findings register state, signed decision file. CI stores them as artifacts.
- Runtime failure: a failed or non-evaluable check lowers the tier and is written into the record; the export gate refuses a higher tier. There is no override flag for `EXTERNAL_CANDIDATE`.
- Development failure: gate failure blocks at stop, commit and CI. Observer findings follow the release rule in C4.

---

## E. Revised development phases

| Phase | Depends on | Deliverables | Acceptance criteria |
|---|---|---|---|
| 0 Workshop and compliance baseline | — | Git repo reconciled; environment verified; settings, sandbox, P0 hooks; `gate.py`, `scan_repo.py`, `check_rtm.py`; CI; threat model; classification policy; CNIL `SOURCE.md`, `requirements.yaml`, RTM with all rows `planned`; WP216 ingested or flagged; `cnil-observer`, `review-protocol`, `/anon-cnil`, `/anon-cnil-refresh` | Planted data file blocked on read and commit; subprocess read of `/mnt` fails; `check_rtm` green on schema; C6 list resolved; observer architecture assessment committed with no undispositioned high finding |
| 1 Grid, regions, recipe, skeleton | 0 | Lossless readers, sketch, detection, recipes, local-only skeleton, corpus ≥ 25 files, first adversarial families (`metadata`, `formula`, `header-leak`, `skeleton-shape`); privacy-auditor, fidelity-reviewer, corpus-builder; `stop_gate` | Cell accounting holds on all corpus files; every `empty_kind` and storage type round-trips; formula presence detected on all formula fixtures; memory flat on a generated 2M-row CSV; every detection miss flagged; no source text in skeleton, logs or exceptions |
| 2 Profile and policy | 1 | Private and shareable profiles, Exception Catalogue, `PrivacyPolicy` schema and two profiles | Catalogue counts exact against ground truth; shareable profile passes `adv-unique` and `adv-rare-combo`; no run proceeds without an explicit policy; RTM rows 05, X-03 `implemented` |
| 3 Contract | 2 | Contract v1 with sensitivity, quasi-identifier and key-role confirmation | Round-trip; generation blocked while any column lacks a keep decision or sensitivity class; rows 04, 06, 07 `implemented` |
| 4 Mode B release | 3 | Generator, coverage planner, privacy engine for synthetic outputs, AssessmentRecord, export gate, release register | Requested N honoured; coverage report lists every unrepresented scenario; byte-identical for same seed; all negative and positive privacy tests pass; rows 01–03, 10–16, X-01, X-02 `implemented`; offline suite green; `/anon-cnil release` done; `gate.py --release` green |
| 5 UI | 4 | Local interface on loopback | No logic in `ui`; binds loopback only; token and Host checks tested; every action yields a recipe, contract or policy change |
| 6 Mode A | 2, 3, 4 | Strategies A1–A3, hierarchies, two-pass suppression, bench | 2M rows under a fixed memory ceiling; identical output for any chunk size; A1 never above `RESTRICTED`; A2 negative and positive tests pass; rows 08, 09 `implemented`; observer release assessment |
| 7 Mode C specification | 4 | Specification reviewed by the observer for inference risk | Approved before any build |
| 8 Optional | 4 | Packaging, local MCP server, `source-watch.yml` | MCP server serves only `EXTERNAL_CANDIDATE` outputs |

Numeric thresholds here (corpus size, row counts) are proposals to confirm.

**Observer timing.** The reference, RTM skeleton and observer arrive in Phase 0, because its first input is this architecture and the classification policy. Supporting tests arrive with the module they cover (P1 metadata and skeleton, P2 rare values, P4 the three criteria for synthetic output, P6 the same for transformed output). The observer runs at every phase end and on every privacy-tagged ADR.

---

## F. Open technical decisions

| # | Decision | Recommendation | Alternative | Reason |
|---|---|---|---|---|
| 1 | Development isolation inside WSL2 | Dedicated dev distribution with Windows drive automount and interop disabled; real data never in that distribution | Current distribution, relying on sandbox read denial for `/mnt` | Removes the path to Windows files instead of blocking it |
| 2 | How the CNIL text is stored | Commit `SOURCE.md` with normalised hash, section list and short quotes; keep the full snapshot uncommitted until CNIL's reuse licence is confirmed | Commit the full snapshot | Repository is public; licence terms not verified |
| 3 | Secondary references | Ingest WP216 in Phase 0; add newer EDPB material to a watch list only | CNIL page alone | The page delegates technique detail to WP216 |
| 4 | Skill naming | `anon-` prefix | Unprefixed names checked once | Survives future built-in additions |
| 5 | XLSX reading | Thin streaming reader over the sheet XML for raw fidelity | General spreadsheet library in read-only mode | Libraries convert types and lose stored text; needs a spike in P1 |
| 6 | Engine for quasi-identifier counting at scale | Decide by benchmark in P6 between a streaming dataframe engine and an embedded SQL engine with disk spill | Fix it now | No measurement yet |
| 7 | Mode B when N is too small | Generate, report, non-zero exit only with `--require-full-coverage` | Refuse by default | Small N is a legitimate request; the report prevents silent gaps |
| 8 | Attack-based evaluation library | Evaluate an open-source attack framework in P6 as a development-only dependency after licence review | Own metrics only | Independent evidence strengthens CNIL-13 |
| 9 | Skeleton export in v1 | Local-only, no export | Assessed export | Shape disclosure is hard to bound; diagnostics rarely need export |
| 10 | Default policy | No default; user picks a profile | Conservative default | Avoids an implied universal threshold |
| 11 | Legacy `.xls` and `.xlsb` | Out of scope for v1 | Support `.xls` | Separate binary format and reader |
| 12 | Who signs release decisions | Project owner, recorded in `decisions/` | Second reviewer as well | Single-owner project today |

## v0.4.1 corrections (supersede C1–C3 nesting and hook statements, F1, F5, F8, F12)

1. **RTM basis.** Every row carries requirement basis (`CNIL-direct`, `CNIL-derived`, `ANON-policy`), CNIL strength (definition, advice, criterion, required-if), and control basis. CNIL-04..07 are advice; 08–09 are descriptions; metrics for 10–12 are our choice; X-rows renamed ANON-01..05. `check_rtm.py` enforces the fields; the observer flags ANON-policy presented as CNIL.
2. **Synthetic vs real-derived.** Uniqueness and cross-table keys among fictional rows are structure metrics, not risks. Synthetic risk = match or closeness to a real row, replication of source-unique combinations, key values derived from source keys, and attack success against real records. Primary Mode B argument is information flow: `synth` consumes only Contract + shareable profile (import rule + test).
3. **Nesting and hook identity.** Docs (via search) say subagents can nest by default (about three layers; `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`, 1 disables). Custom agents omit `Agent`; nesting disabled project-wide after verification. `agent_id`/`agent_type` in PreToolUse are unverified for the CLI: no guarantee depends on them. corpus-builder boundary = common path rules + `scan_repo`/CI path check + diff review.
4. **Limitations.** `docs/privacy-limitations.md` states what canaries, exact-row match, closest-record distance, k, attribute confidence, rare-category rules, attack evaluation, wording lint and RTM checks do and do not show. Every record and report carries the non-certification statement.
5. **XLSX.** Library first (openpyxl read-only; python-calamine second). Phase 1 fidelity matrix decides; custom XML reading only for a field no library delivers.
6. **Attack evaluation.** Required for the Phase 4 release: singling-out, linkability, inference attacks vs a held-out baseline, code independent of `privacy/`, on synthetic source populations. Anonymeter is the candidate pending licence check in Phase 0.
7. **Authorization.** Software acceptance: project owner. Dataset release: the data controller or their authorized decision-maker, recorded as declared name, role, date in the AssessmentRecord and release register. The developer never attests for a dataset.
8. **Environment.** Existing WSL2 environment, conditional on verified sandbox (fail-closed), `/mnt` and credential read denial, no data files in workspace, bypass disabled. Dedicated distribution is a hardening option.

### Phase 0 implementation plan (one commit per step; stop on failure; no push without confirmation)

1. Read-only environment survey → `docs/environment.md`.
2. Full read of official docs + temporary logging hook experiment → ADR 0001 resolving every C6 row.
3. Repository: clone or init, branch, `.gitignore`, README.
4. Python skeleton: project file, package, ruff, pyright, pytest, import rules.
5. `tools/scan_repo.py`, `tools/gate.py` with tests.
6. `CLAUDE.md`, `.claude/settings.json`, rules `privacy.md`, `compliance.md`.
7. P0 hooks with tests fed by recorded input from step 2.
8. pre-commit and `ci.yml`.
9. Documents: requirements, architecture, threat model, classification, limitations, ADRs for F1–F12.
10. Compliance baseline: `SOURCE.md`, `requirements.yaml`, `rtm.yaml`, `findings.yaml`, `check_rtm.py`; WP216 ingest; attack-library licence check.
11. `review-protocol`, `cnil-observer`, `/anon-cnil`, `/anon-cnil-refresh`, `/anon-feature`, `/anon-gate`, `/anon-adr`.
12. Acceptance drills and Phase 0 report for owner sign-off.

If step 1 or 2 fails its check, stop and report before step 3.

## Verification of this proposal and next step

- Independent review of this document, then owner decisions on F1–F12.
- On approval, only Phase 0 starts. Its first actions are read-only checks: `/help` for name collisions, sandbox status, settings reference for key names, Ubuntu release.
- End-to-end proof of the workshop is the Phase 0 acceptance row: planted-file block, sandbox denial, green `check_rtm`, committed observer assessment.

## Sources

- CNIL, "L'anonymisation de données personnelles", 19 mai 2020: https://www.cnil.fr/fr/technologies/lanonymisation-de-donnees-personnelles
- Claude Code docs (via search): https://code.claude.com/docs/en/commands · https://code.claude.com/docs/en/skills · https://code.claude.com/docs/en/sub-agents · https://code.claude.com/docs/en/hooks · https://code.claude.com/docs/en/permissions · https://code.claude.com/docs/en/sandboxing · https://code.claude.com/docs/en/memory · https://code.claude.com/docs/en/goal · https://code.claude.com/docs/en/tools-reference
