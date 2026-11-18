# Anonimizer

Local, offline tool. It reads a CSV or XLSX file, discovers its structure and data-quality anomalies, and generates a synthetic test dataset that reproduces those patterns without the source values. Mode B (synthetic test data) is implemented. Mode A is not implemented and must stay unavailable until a strategy is built and assessed. Mode C is a future extension.

## Non-negotiables

1. **Only synthetic data in this repository and in any session.** Never read, paste or commit real data. Every data file lives under `tests/fixtures/` and is listed in `tests/fixtures/MANIFEST.yaml`.
2. **Stay in this directory.** Do not read other projects, `/mnt`, or home-directory files outside `~/.claude` configuration.
3. **Run project code through the sandbox wrapper:** `tools/sbx <command>`. Outside a session sandbox it builds its own (home directory and `/mnt` hidden, no network; `SBX_NET=1 tools/sbx ...` is for installing packages only). Inside Claude Code's session sandbox it runs the command directly. If it exits with status 97, stop; do not run unsandboxed.
4. **No network, model or telemetry at runtime.** Only `anonimizer/ui` may open a socket, on 127.0.0.1.
5. **The generator never sees source data.** `anonimizer/synth.py` imports `patterns` only. Do not add imports there.
6. **No cell content in messages.** Errors, logs, reports and test output name rules, counts and positions, never values.
7. **Claims.** Never write that an output is anonymous, certified, or compliant. Use the fixed statement in `anonimizer.NON_CERTIFICATION_STATEMENT`. `tools/scan_repo.py` rejects the forbidden phrases.
8. **Tiers only go down.** No override flag for a release tier. `EXTERNAL_CANDIDATE` stays unavailable until attack-based evaluation exists.
9. **Git.** Work on the development branch. No force-push, no history rewrite, no merge into `main` without the owner. Commit with the repository's noreply address.

## Layer map (imports go left to right only)

`grid` → `patterns` → `regions` → `recipe` → `profile` → `contract` → `synth` → `privacy` → `export` → `reports` → `pipeline` → `cli`, `ui`

| Module | Role |
|---|---|
| `grid/` | Lossless streaming readers (CSV, XLSX). Nothing is coerced |
| `patterns.py` | Value classification into pattern classes |
| `regions.py`, `recipe.py` | Table detection with confidence; user-correctable ParseRecipe |
| `profile.py` | Full-scan profiler, Exception Catalogue, private and shareable views |
| `policy.py` | PrivacyPolicy profiles, tiers, release cap |
| `contract.py` | Dataset Contract v1, validation, human decisions |
| `synth.py` | Exception-driven generator, coverage planner, Scenario Manifest |
| `privacy.py` | Deterministic assessment per criterion, tier derivation |
| `export.py` | Writers and export gate; the only writer of datasets |
| `reports.py`, `pipeline.py`, `cli.py`, `ui/` | Reports, orchestration, interfaces |
| `inspector.py` | Local source inspector: original cells and exact counts for the local page. Imported by `ui` only; never by anything that feeds the contract, the generator, a report or an export |

`tests/architecture/test_imports.py` enforces the layering, the generator's isolation, the absence of network libraries and where files may be written.

## Commands

```
tools/sbx python tools/gate.py --fast      # lint, repository scan, matrix check, quick tests
tools/sbx python tools/gate.py --full      # everything; writes docs/evidence/gate-report-full.json
tools/sbx python tools/gate.py --release   # full + release rule on docs/compliance/findings.yaml
tools/sbx pytest tests/unit -q             # one test directory
tools/sbx python tools/demo.py             # product-value demonstration -> docs/evidence/
tools/sbx python tests/fixtures/build_fixtures.py   # rebuild fixtures and ground truth
tools/sbx anonimizer generate FILE --policy internal-dev -n 50 --out out/run1
```

A green gate means the listed controls behaved as specified on the listed fixtures. It is not a certification and not proof of legal anonymity. Do not report a check as passed unless it ran.

## Working rules

- Tests first for anything touching `privacy.py`, `export.py`, `policy.py`, `contract.py` or `profile.to_shareable`. Each privacy test carries `@pytest.mark.cnil("<row id>")`, and the row exists in `docs/compliance/rtm.yaml`.
- A new anomaly class needs: classifier or profiler support, a description in `contract.DESCRIPTIONS`, a generator, a planted fixture with ground truth, and a line in `docs/known-limitations.md` if it is partial.
- Ground truth is written by the fixture builder from what it plants. Never derive expected values from the detector's output.
- Changing seeded output changes users' reproducibility: update the pinned digest in `tests/determinism/` deliberately and say so in the commit.
- `docs/compliance/cnil/` and `docs/compliance/decisions/` change only with the owner's explicit approval.

## Where things are

| Topic | File |
|---|---|
| Approved architecture | `docs/architecture.md` |
| Decisions of the product build | `docs/adr/0002-product-build-decisions.md` |
| Status and continuation | `docs/status.md` |
| Threat model, classification, limits | `docs/threat-model.md`, `docs/privacy-classification.md`, `docs/privacy-limitations.md`, `docs/known-limitations.md` |
| CNIL reference, matrix, findings | `docs/compliance/` |
| Reviewers and their protocol | `.claude/agents/`, `.claude/skills/review-protocol/` |
