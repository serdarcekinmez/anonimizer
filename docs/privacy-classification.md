# Output classification

Every output carries three things. None of them is a legal conclusion.

| Axis | Values | In this release |
|---|---|---|
| Transformation class | structure-only, masked, pseudonymized, generalised/randomised, synthetic | Only **synthetic** is produced |
| Assessment status | none, failed, passed (with policy id and version), expired | All four can occur |
| Release tier (derived) | `LOCAL_ONLY`, `RESTRICTED`, `EXTERNAL_CANDIDATE` | `EXTERNAL_CANDIDATE` is **unavailable** |

## What the words mean

| Term | Meaning here |
|---|---|
| Masking | Hiding part of a value. Not implemented. Would be personal data. |
| Pseudonymization | Replacing identifiers by stable substitutes. Not implemented. Remains personal data and could never exceed `RESTRICTED`. |
| Synthetic generation | Producing new values from pattern classes. What Mode B does. Synthetic does not mean anonymous. |
| Assessed anonymization | A controller's documented conclusion that the three criteria are met or the residual risk is negligible. The tool can supply evidence for it. It never states it. |

## Tiers

| Tier | Meaning | Conditions |
|---|---|---|
| `LOCAL_ONLY` | Keep on the machine that produced it | Default. Also the result when the assessment failed, was skipped or has expired, or when no person confirmed the Dataset Contract |
| `RESTRICTED` | May circulate inside the organisation that controls the source data, under its own rules. Not assessed as anonymous | Assessment passed under an explicit policy, and a named person confirmed keep decisions, sensitivity classes and key roles |
| `EXTERNAL_CANDIDATE` | Candidate for release outside the organisation, subject to the controller's own decision | Unavailable. The code path requires a policy that allows it, every criterion fully met and evaluable, and an attestation by the controller; it is then capped at `RESTRICTED` because no attack-based evaluation exists |

Rules enforced in code (`anonimizer.privacy.derive_tier`, `anonimizer.export.export_bundle`):

- The tier is derived, never chosen. A requested tier above the derived one is refused. There is no override flag.
- Every rule can only lower the tier.
- A record older than its review-by date counts as `LOCAL_ONLY` (`anonimizer check-record`).
- Raw data and the private profile are never part of an export bundle.

## Fictional keys

Identifiers that repeat inside a synthetic table, or that link two synthetic tables, are structure the tool creates on purpose so that joins and group-bys can be tested. They are not counted as a privacy risk. What is measured is whether a synthetic key value equals a *real* key value more often than chance explains.

## Who decides what

| Decision | Who |
|---|---|
| Software acceptance | Project owner |
| Keep, sensitivity class, quasi-identifiers, copying category values | The person running the tool, recorded by name in the contract |
| Release of a dataset | The data controller or the person they authorise. The developer of the tool never attests for a dataset |
