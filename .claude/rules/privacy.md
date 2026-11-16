---
paths:
  - "src/anonimizer/privacy.py"
  - "src/anonimizer/policy.py"
  - "src/anonimizer/export.py"
  - "src/anonimizer/contract.py"
  - "src/anonimizer/profile.py"
  - "src/anonimizer/synth.py"
---

# Privacy-sensitive code

- The generator (`synth.py`) may import `patterns` only. No reader, no profile, no file or OS access.
- Anything that reaches the contract must come from `profile.to_shareable`. Put row numbers, exact layouts and values under a `_private` key so that stripping stays mechanical.
- A literal value may enter the contract only if it is on the marker allowlist, a boolean word, a spreadsheet error code, or approved by a named person through `contract.approve_categories`.
- Tier logic may only lower a tier. Never add a flag, environment variable or parameter that raises one.
- Exceptions and messages name rules, counts and positions. Never interpolate a cell value, a header from an error path, or a file name of the user's data.
- A new check needs a negative test (a planted problem it must catch) and a positive test, both marked `@pytest.mark.cnil("<row>")`, and the row in `docs/compliance/rtm.yaml`.
- Thresholds are ANON-policy choices. Do not present them as CNIL values, and add each new one to `PrivacyPolicy` with its rationale.
- Uniqueness and repeated keys among fictional rows are structure, not risk. Risk is closeness to a real record.
