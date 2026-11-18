# What the privacy checks show and what they do not

A green gate or a "passed" assessment means the listed controls behaved as specified on the listed files. It is not a certification and not proof of legal anonymity.

| Check | What it shows | What it does not show |
|---|---|---|
| Import rule (generator cannot read source data) | No code path carries a source value into the generator | That the contract itself is harmless: it holds names, formats, rates and approved literals |
| Canary tests | Planted tokens are absent from every exported file, console output and error message on the test fixtures | Absence of other source values on other files |
| Runtime report scan | No source cell of five characters or more appears as a string or token in the exported documents of this run | Values shorter than five characters, numbers, values split across tokens, or values equal to a word of the tool's own vocabulary |
| Whole-row equality | No synthetic row equals a source row | Partial matches |
| Closest-record similarity | No synthetic row matches a source row on more than the policy's share of its informative cells | Rows with fewer than three informative cells are skipped; cells whose value is frequent in the output are not counted |
| Identifier overlap versus chance | Synthetic identifiers do not coincide with real ones more often than in control datasets generated from the same contract with other seeds | In a dense value space (short integer keys) coincidence is expected and passes; such a key equals a real key by accident. The comparison uses 2 to 30 control samples; in a value space where a coincidence is rare but possible, a single chance match can fail the check (run again with another seed) |
| Quasi-identifier replication | No synthetic row reproduces a combination that is unique in the source, on the columns a person designated | Nothing if no quasi-identifier was designated; combinations of other columns |
| Inference | Columns are generated independently, so the output carries no relationship between attributes of a record | No inference attack is run; per-column distributions are disclosed |
| Small-count masking | Under `external-strict`, counts below 10 are shown as "<10" and generator histograms below 10 are pruned | Under `internal-dev` exact counts are shown |
| Category approval limits | A category value is copied only above the policy's count and share limits and on a named person's approval | That the value is harmless. A frequent value can still be sensitive |
| Tier rules | The label on a bundle never exceeds what the assessment allows | That the label is the right legal qualification |
| Wording lint | No positive certification or guarantee claim in the repository or in outputs | Misleading wording that avoids the listed phrases |
| Traceability matrix check | Every requirement has a row, every automated row has a test, evidence exists | That the tests are adequate for the requirement |

## Not implemented

- Attack-based evaluation (singling-out, linkability and inference attacks against a held-out baseline).
- Equivalence-class measures (k-anonymity, l-diversity, t-closeness). They belong to Mode A, which is not implemented.
- Differential privacy.
- Cross-release analysis.
- Ingestion of WP216.
- A `cnil-observer` assessment of this release.

## The fixtures

Every privacy test runs on synthetic files written by this project. Passing them shows that each check reacts to the problem planted for it. It says little about data whose risks nobody thought to plant.
