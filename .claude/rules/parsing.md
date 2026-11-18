---
paths:
  - "src/anonimizer/grid/**"
  - "src/anonimizer/regions.py"
  - "src/anonimizer/recipe.py"
  - "src/anonimizer/patterns.py"
---

# Reading and classifying

- Readers keep what the file stores: raw text, storage type, quoting, the kind of emptiness. No cleaning, no coercion, no silent drop.
- Classification happens in `patterns.classify`, never in a reader.
- Input files are untrusted: keep the zip limits, the DTD refusal, and never evaluate a formula or run a macro.
- Formula text is not retained anywhere.
- Every detection decision carries a confidence and a note the user can act on through the recipe.
- A parsing change needs a fixture in `tests/fixtures/parser/` and a hand-written expectation in `tests/golden/expected_parser.json`.
