---
name: anon-gate
description: Run the Anonimizer quality gate and summarise the evidence. Use when asked to verify the project, before a commit of substance, or before reporting work as done.
---

# /anon-gate

1. Run `tools/sbx python tools/gate.py --full` (or `--fast` if the user asked for a quick check, `--release` for a release decision).
2. Report each step with its real result: lint, repository scan, traceability matrix, tests (passed, failed, skipped).
3. For a failure, show the failing lines from the gate output and name the file to look at. Do not retry in a loop and do not weaken a test or a threshold to make the gate pass.
4. If the gate could not run (sandbox wrapper unavailable, missing environment), say exactly that. Do not report it as passed.
5. End with the fixed sentence: a green gate means the listed controls behaved as specified on the listed fixtures; it is not a certification and not proof of legal anonymity.

`--release` is expected to fail while high findings in `docs/compliance/findings.yaml` have no disposition. That is a decision for the owner, not something to fix by editing the register.
