"""PrivacyPolicy: versioned, explicitly selected per run. There is no implicit default.

Passing a policy is necessary for a release tier and never sufficient for a legal conclusion.
The thresholds are this project's own choices (requirement basis ANON-policy), not CNIL values.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

LOCAL_ONLY = "LOCAL_ONLY"
RESTRICTED = "RESTRICTED"
EXTERNAL_CANDIDATE = "EXTERNAL_CANDIDATE"
TIER_ORDER = {LOCAL_ONLY: 0, RESTRICTED: 1, EXTERNAL_CANDIDATE: 2}

# This release has no attack-based evaluation (architecture v0.4.1 item 6). Until it exists,
# no output can reach EXTERNAL_CANDIDATE, whatever the policy and whoever attests.
RELEASE_TIER_CAP = RESTRICTED
RELEASE_TIER_CAP_REASON = (
    "attack-based evaluation (singling-out, linkability and inference attacks against a held-out "
    "baseline) is not implemented in this release, so the EXTERNAL_CANDIDATE tier is unavailable"
)


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class PrivacyPolicy:
    id: str
    version: str
    description: str
    # A text layout is reproduced exactly only if at least this many source values share it;
    # rarer layouts are reproduced with bucketed run lengths.
    shape_exact_min_count: int
    # Counts below this value are masked ("<k") in shareable reports. 0 disables masking.
    small_count_threshold: int
    # A literal category value may be approved for copying only above both limits.
    category_min_count: int
    category_min_share: float
    # Date ranges are widened outward to a multiple of this many years.
    year_rounding: int
    # Closest-record check: a synthetic row may not equal a source row on more than this share
    # of its informative cells (rows with fewer informative cells than the minimum are skipped).
    max_row_similarity: float
    min_informative_cells: int
    # Extra identifier-value overlaps tolerated beyond what chance explains.
    identifier_overlap_slack: int
    max_tier: str
    review_interval_days: int
    attacker_assumptions: tuple[str, ...] = field(default_factory=tuple)
    rationale: str = ""
    limits: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["attacker_assumptions"] = list(self.attacker_assumptions)
        return d


_COMMON_LIMITS = (
    "Thresholds are necessary conditions chosen by this project, not sufficient ones. Equal-value and "
    "closest-record checks do not address background knowledge or attacks that combine releases."
)

POLICIES = {
    "internal-dev": PrivacyPolicy(
        id="internal-dev", version="1.0",
        description="Synthetic test data used inside the organisation that controls the source data.",
        shape_exact_min_count=5, small_count_threshold=0, category_min_count=10, category_min_share=0.0,
        year_rounding=1, max_row_similarity=0.999, min_informative_cells=3, identifier_overlap_slack=0,
        max_tier=RESTRICTED, review_interval_days=180,
        attacker_assumptions=(
            "Recipients are staff or contractors already bound by the controller's confidentiality rules.",
            "Recipients may know some source records and may hold the source file's column names.",
            "Recipients do not attempt systematic re-identification.",
        ),
        rationale="Favours structural fidelity for developers; accepts exact counts in reports.",
        limits=_COMMON_LIMITS,
    ),
    "external-strict": PrivacyPolicy(
        id="external-strict", version="1.0",
        description="Stricter generalisation, intended for a later external-candidate assessment.",
        shape_exact_min_count=20, small_count_threshold=10, category_min_count=50, category_min_share=0.01,
        year_rounding=5, max_row_similarity=0.75, min_informative_cells=3, identifier_overlap_slack=0,
        max_tier=EXTERNAL_CANDIDATE, review_interval_days=90,
        attacker_assumptions=(
            "Recipients may be anyone; the output may be combined with public registers.",
            "Recipients may know that a given person is in the source data.",
            "Recipients may hold another release produced from the same source.",
        ),
        rationale="Rare layouts and small counts are generalised or masked before anything is derived.",
        limits=_COMMON_LIMITS + " In this release the tier is capped at RESTRICTED regardless of this policy.",
    ),
}


def get_policy(policy_id: str | None) -> PrivacyPolicy:
    if not policy_id:
        raise PolicyError("a privacy policy must be selected explicitly: " + ", ".join(sorted(POLICIES)))
    try:
        return POLICIES[policy_id]
    except KeyError:
        raise PolicyError("unknown privacy policy; available: " + ", ".join(sorted(POLICIES))) from None


def min_tier(*tiers: str) -> str:
    return min(tiers, key=lambda t: TIER_ORDER[t])
