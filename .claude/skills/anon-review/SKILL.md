---
name: anon-review
description: Run the three Anonimizer reviewers (cnil-observer, privacy-auditor, fidelity-reviewer) on the current change and merge their findings.
disable-model-invocation: true
---

# /anon-review

Run this in the main session.

1. Collect the changed files: `git diff --name-only main...HEAD`.
2. Start `privacy-auditor` and `fidelity-reviewer` on the change. Start `cnil-observer` (scope `change`) too if a changed file is under `src/anonimizer/{privacy,policy,export,contract,profile,synth}.py`, `docs/compliance/`, or a privacy document in `docs/`.
3. Merge the reports. Where two reviewers describe the same problem, keep one finding and note both sources. Every privacy finding must name a matrix row.
4. Show the merged list, most severe first, with the reviewers' own statements of what they did not review.
5. Append findings of severity high or above to `docs/compliance/findings.yaml` as `open`. Ask the user before recording medium and low ones.
6. Do not fix anything in the same step. Fixes are a separate, test-first change.
