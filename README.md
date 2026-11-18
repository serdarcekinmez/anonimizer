# Anonimizer

Anonimizer reads a CSV or Excel file that may be confidential, discovers its real structure and its data-quality anomalies, and generates a small synthetic test dataset that reproduces those patterns without the original values. It runs on your machine, offline, with no cloud service and no language model.

It is not a generic mock-data generator. A mock generator produces clean rows for a schema you describe. Anonimizer finds what you did not know was in the file (the one text value in a numeric column at row 1,950,002, the three dates written the other way round, the order that points at no customer) and puts each of those cases into the test data, with a manifest saying where.

**Status: version 0.1.0, a working first increment of Mode B. Not reviewed independently. Not production-ready.** See [docs/status.md](docs/status.md).

## What it does today

| Step | What you get |
|---|---|
| Read | CSV, TSV, XLSX. Delimiter, encoding and tables are detected; several tables per file or sheet, introductory rows, blank rows, ragged rows, Excel cell types, errors and formula presence are kept as evidence. Nothing is cleaned |
| Correct | A parse recipe (JSON, or the interface) lets you fix table boundaries and headers when detection is unsure |
| Profile | Every cell is classified. The Exception Catalogue counts empty cells, quoted empties, whitespace, `N/A`-style markers, zeros, text in numeric columns, invalid dates, format deviations, duplicates, key behaviour, dangling references, rare layouts |
| Contract | A Dataset Contract proposes, per column, type, format, sensitivity class and key role. You decide what to keep and classify |
| Generate | The row count you ask for, with one explicit scenario per catalogued exception where space allows, fictional keys that repeat and reference each other as in the source, and a seed for exact reproduction |
| Report | Scenario Manifest, coverage report (including what did not fit), before and after quality reports, comparison, privacy assessment record, classification label |

Mode A (converting a full dataset) is not implemented and is not offered. Mode C (machine-learning datasets) is a future extension.

## What it does not claim

Synthetic does not mean anonymous. Anonimizer supports a data controller's own assessment and does not replace it. It certifies nothing, and a passing test suite is not proof of legal anonymity. Outputs are labelled `LOCAL_ONLY` by default and at most `RESTRICTED` (for use inside the organisation that controls the source data). No output of this version is cleared for release outside that organisation. Read [docs/privacy-limitations.md](docs/privacy-limitations.md) before sharing anything.

## Install

Python 3.10 or later. One runtime dependency (openpyxl).

```
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Use

Command line:

```
anonimizer inspect  data.csv --recipe-out recipe.json        # detected tables; edit recipe.json if needed
anonimizer profile  data.csv --policy internal-dev           # Exception Catalogue on the console
anonimizer generate data.csv --policy internal-dev -n 50 --seed 1 --out out/run1
```

`out/run1` then holds `synthetic.csv` (or `.tsv`, `.xlsx`), `scenario_manifest.json` and `.csv`, `coverage_report.json`, `source_report.json`, `generated_report.json`, `comparison.json`, `report.md`, `contract.json`, `recipe.json`, `assessment_record.json`, `release_label.json` and `CLASSIFICATION.txt`.

A policy must be named; there is no default. `anonimizer policies` lists them.

To reach `RESTRICTED`, a person has to classify every kept column and confirm the contract:

```
anonimizer contract data.csv --policy internal-dev -o contract.json     # then review contract.json
anonimizer generate data.csv --policy internal-dev -n 50 --out out/run2 \
    --sensitivity table_1.balance=non_sensitive --drop table_1.notes \
    --keep-categories table_1.status --approved-by "Name" --confirm-contract "Name"
```

Local interface (loopback only, random port, session token):

```
anonimizer ui
```

Open the address it prints. The page walks through file, tables, policy, report, contract, generation, result and export.

On Windows with the project inside WSL, a double-click launcher can be generated for the machine:

```
python3 tools/launch_wsl.py --write-launcher     # writes Start-Anonimizer.cmd (not tracked: it names the local distribution and path)
```

The launcher starts the interface through `tools/sbx` and allows one instance at a time. A second start shows the address of the running instance. If that instance's session file is missing, the launcher waits ten seconds, checks that the lock holder really is an Anonimizer launcher of this checkout, and asks before stopping it and starting a new one; it never deletes a held lock and never stops a process it cannot identify. After an update of the code, close the running instance and start it again.

More options: `anonimizer generate --help`. Exit status: 0 success, 2 input error, 3 full coverage required and not reached, 4 release tier refused.

## Verify it yourself

```
python tests/fixtures/build_fixtures.py        # rebuild the three fixtures and their ground truth
python -m pytest -q                            # the test suite
python -m pytest -q --runslow tests/bench      # 2 million rows (several minutes, about 300 MB of temporary files)
python tools/demo.py                           # detection versus ground truth, and versus a plain mock generator
python tools/gate.py --full                    # lint, repository scan, traceability check, tests
```

On the development machine these run inside a sandbox: prefix them with `tools/sbx` (see [CLAUDE.md](CLAUDE.md)). `tools/gate.py` refuses to run outside it unless `ANONIMIZER_CI=1` is set.

The demonstration's last result is in [docs/evidence/product-value-demo.md](docs/evidence/product-value-demo.md).

## Documents

| Document | Content |
|---|---|
| [docs/status.md](docs/status.md) | What works, what is partial, test results, what to do next |
| [docs/known-limitations.md](docs/known-limitations.md) | Formats, detection, generation and interface limits |
| [docs/privacy-classification.md](docs/privacy-classification.md) | Transformation classes, assessment status, release tiers |
| [docs/privacy-limitations.md](docs/privacy-limitations.md) | What each privacy check shows and does not show |
| [docs/threat-model.md](docs/threat-model.md) | Attacks considered and not considered |
| [docs/compliance/](docs/compliance/) | CNIL source record, requirements, traceability matrix, findings register |
| [docs/architecture.md](docs/architecture.md) | Approved architecture v0.4 with the v0.4.1 corrections |
| [docs/adr/](docs/adr/) | Decision records, including the departures made during the build |
| [docs/evidence/](docs/evidence/) | Demonstration and gate reports |

## Development rules

- Only synthetic data in this repository. Every data file is a registered fixture.
- Work happens on a development branch and reaches `main` through a pull request approved by the project owner.
