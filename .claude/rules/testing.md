---
paths:
  - "tests/**"
---

# Tests

- Synthetic data only, produced by a builder script in `tests/fixtures/`. Register every data file in `tests/fixtures/MANIFEST.yaml`.
- Ground truth comes from the builder, not from the detector's output.
- Assert on behaviour a user depends on. Do not add tests to raise a count.
- Canary tests read every exported file, including workbook parts.
- Tests must pass with networking removed; `conftest.py` fails any non-loopback connection.
- Large-file checks carry `@pytest.mark.slow` and run with `--runslow`.
- Report real results. If a check did not run, say so.
