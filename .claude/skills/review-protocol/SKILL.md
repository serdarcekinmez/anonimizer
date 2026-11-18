---
name: review-protocol
description: Finding schema, severity scale and evidence rule shared by the Anonimizer reviewers (cnil-observer, privacy-auditor, fidelity-reviewer). Preloaded into those agents.
user-invocable: false
---

# Review protocol

You review; you do not edit. Report findings in this form, most severe first.

```
id:        <reviewer>-<n>
category:  DEFECT | RISK | EVIDENCE-GAP | JUDGMENT | SOURCE-DRIFT
severity:  blocker | high | medium | low
rtm_row:   <row id from docs/compliance/rtm.yaml, or "none">
where:     <file>:<line>
claim:     one sentence stating what is wrong
evidence:  what you read that shows it (quote code or text, never data values)
remedy:    the smallest change that would resolve it
```

Rules:

1. Cite a file and line for every finding. No finding from memory or from general knowledge of regulations.
2. Key every privacy finding to a matrix row. If no row fits, say so; a missing row is itself a finding.
3. Categories: DEFECT is a wrong or missing control or automatable test. RISK is a residual privacy risk. EVIDENCE-GAP is a claim without a supporting artifact. JUDGMENT needs a human decision. SOURCE-DRIFT is a changed or stale reference.
4. Severity: blocker stops any release; high stops a release unless the owner signs a disposition (a high DEFECT cannot be waived); medium and low are tracked.
5. Say what you did not review.
6. Do not restate the design. Do not praise. If you found nothing in an area you examined, write "examined, no finding".
7. Never include source data values, even from fixtures marked as canaries.
8. A passing test suite is not evidence of anonymity. Do not write that an output is anonymous, certified or compliant.
