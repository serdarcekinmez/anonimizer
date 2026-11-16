# Threat model

Scope: Mode B (synthetic test data) as implemented in version 0.1.0. Mode A is not implemented.

This is the project's own model. It is not derived from a CNIL text beyond the three criteria named on the CNIL page (singling out, linkability, inference); thresholds and attacker assumptions are ANON-policy choices.

## What is protected

- The values of the source file, and through them the people or organisations they describe.
- Facts about small groups in the source (for example "exactly one row has this pattern").

## Who is trusted

| Party | Trust |
|---|---|
| The person running the tool | Trusted with the source file. They already hold it. |
| The machine | Trusted. The tool adds no network path and no telemetry. |
| Recipients of a `RESTRICTED` output | Bound by the controller's internal rules; may know some source records and the column names. Not trusted to receive source values. |
| Anyone else | Not trusted. No tier in this release is meant for them. |
| Input files | Untrusted. A CSV or workbook may be malformed or hostile. |
| A browser tab on the same machine | Untrusted for the local interface. |

## Assets that leave the engine, and what they can disclose

| Asset | Contains | Residual disclosure |
|---|---|---|
| Synthetic dataset | Generated values; column, sheet and table names; allowlisted markers; approved category values | Names copied from the source; per-column formats, digit counts, year range, missing-value rates; chance equality with real values in dense value spaces |
| Scenario Manifest, coverage report | Positions in the generated file, exception classes | That a class of anomaly exists in the source |
| Shareable reports | Counts per class, types, formats, detection confidence | Exact small counts under `internal-dev`; masked below 10 under `external-strict` |
| Dataset Contract | Pattern classes, rates, generator specifications | Same as the reports |
| Assessment record | Metrics, policy, statements | Number of coincident values, never the values |
| Private profile | Source row numbers, exact layouts, category values | Private by design; written only to a directory the user names, mode 0600 |

## Attacks considered and the control for each

| # | Attack | Control | Where it is tested |
|---|---|---|---|
| T1 | Read a source value straight from the synthetic file | The generator's only inputs are the contract, row counts and a seed (import rule); literal values must be on the marker allowlist or approved by a named person | `tests/architecture`, `tests/leak` |
| T2 | Find a synthetic row that is a copy or near copy of a source row | Closest-source-row check on informative cells; whole-row equality count | `tests/privacy` (planted copies must fail) |
| T3 | Link a synthetic identifier to a real one | Identifier overlap compared with the overlap of independent control datasets generated from the same contract | `tests/privacy` |
| T4 | Recognise a person by a combination of quasi-identifiers that is unique in the source | Replication check on designated quasi-identifier columns | `tests/privacy` |
| T5 | Infer an attribute from another attribute of the same synthetic row | Columns are generated independently, so a row carries no cross-attribute relationship from the source | By construction; no attack run |
| T6 | Read source values from reports, manifest, contract, logs or error messages | Shareable profile; messages without cell contents; runtime scan of every exported document for source values | `tests/leak`, `tests/privacy` |
| T7 | Recover data from workbook metadata, formulas, comments, hidden sheets | Fresh-file export from generated cells only; formula text is never retained | `tests/product`, `tests/unit` |
| T8 | Learn about one person from an exact small count | Count masking and generator pruning under `external-strict` | `tests/unit`, `tests/privacy` |
| T9 | Hostile input file (zip bomb, XML entity tricks, macros, formula injection) | Size and ratio limits; DTDs refused; macros never run; formulas never evaluated | `tests/unit/test_grid.py` |
| T10 | Another website drives the local interface (CSRF, DNS rebinding) | Loopback bind, session token in an HttpOnly SameSite=Strict cookie, Host and Origin checks, no CORS, strict CSP | `tests/ui` |
| T11 | A higher release label than the assessment allows | Tier derivation that only lowers; export gate without override; top tier unavailable | `tests/privacy` |

## Attacks not addressed

- An attacker who combines the output with other data about the same people. No attack-based evaluation is run (finding F-001).
- An attacker who holds another output generated from the same source. No cross-release analysis exists.
- Meaning carried by column, sheet or table names. They are copied; a person must review them (finding F-004).
- Statistical disclosure through per-column distributions. The output keeps formats and coarse shapes, and the reports describe them.
- A compromised machine or a malicious local user.
- CSV formula injection in the *output*: a source cell that starts like a formula is reproduced as a synthetic formula-like cell (`=1+1`) on purpose, as a test scenario. Open generated CSV files in a spreadsheet with that in mind.

## Review

Review by 2027-05-15, or earlier when a release tier, a policy threshold or the CNIL reference changes.
