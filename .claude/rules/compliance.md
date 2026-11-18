---
paths:
  - "docs/compliance/**"
---

# Compliance files

- `cnil/SOURCE.md` and `cnil/requirements.yaml` change only after a person has re-read the CNIL page and approved the change. Never paraphrase the source from memory; cite the requirement id.
- Quotes stay short. The page text is not stored in the repository.
- Every row of `rtm.yaml` says whether its basis is `CNIL-direct`, `CNIL-derived` or `ANON-policy`. Rows named `ANON-*` are project rules.
- `status: implemented` requires a test carrying the row's marker and an evidence path that exists. `partial` requires a note saying what is missing.
- `findings.yaml` entries are closed by a fix or dispositioned by the owner in `decisions/<id>.md`. A high DEFECT cannot be waived.
- Assessment reports under `assessments/` are immutable once committed.
- Run `tools/sbx python tools/check_rtm.py` after any edit here.
