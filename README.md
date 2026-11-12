# Anonimizer

A local-first Python application that turns CSV and Excel files into safer datasets for development and testing. It runs fully offline: no cloud service and no language model at runtime.

**Status: Phase 0 (workshop and compliance baseline). There is no application code yet.**

## What it will do

- **Mode B, synthetic dataset (first priority):** learn a file's structure and its exceptional values (blanks, `N/A`, zeros, duplicates, invalid entries), then generate a fictional dataset with the row count you choose.
- **Mode A, full dataset conversion:** pseudonymize, generalise or suppress values in a large dataset, or replace it with synthetic data.
- **Mode C, machine learning:** deferred; specification only.

Every run produces before/after quality reports and an assessment record.

## What it does not claim

Anonimizer supports a data controller's own assessment. It does not certify anonymization, and a passing test suite is not proof of legal anonymity. Pseudonymized output is still personal data and is labelled as such.

## Where to read

| Document | Content |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Approved architecture v0.4 with the v0.4.1 corrections |
| [docs/phase-0-status.md](docs/phase-0-status.md) | Phase 0 plan, progress and open blockers |
| [docs/environment.md](docs/environment.md) | Development environment survey and isolation conditions |
| [docs/adr/](docs/adr/) | Architecture decision records |

## Development rules

- Only synthetic test data is allowed in this repository.
- Work happens on phase branches and reaches `main` through pull requests approved by the project owner.
