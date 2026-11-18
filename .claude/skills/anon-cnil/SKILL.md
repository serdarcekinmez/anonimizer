---
name: anon-cnil
description: Run the cnil-observer on a scope (architecture, tests, change, release) and record its report. Use for privacy-tagged decisions, before a phase or release acceptance, and after changes under privacy paths.
argument-hint: architecture | tests | change | release
disable-model-invocation: true
---

# /anon-cnil <scope>

Run this in the main session; the observer cannot start other agents.

1. Run `tools/sbx python tools/check_rtm.py`. If it fails, stop and report: the observer needs a consistent matrix.
2. Start the `cnil-observer` agent with the scope and, for `change`, the list of changed files (`git diff --name-only main...HEAD`).
3. Write its report unchanged to `docs/compliance/assessments/<YYYY-MM-DD>-<scope>.md`, headed by: date, commit, scope, source hash from `SOURCE.md`, version of `requirements.yaml`, and what the observer said it did not review.
4. Append each finding to `docs/compliance/findings.yaml` with status `open`. Do not disposition anything; that is the owner's decision.
5. Tell the user the number of findings by severity and which ones block a release.

The observer's opinion is not a gate. The gate reads the register after the owner has dispositioned it.
