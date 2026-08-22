"""Generated Constitutional Bill of Materials source and verifier.

The registry in this module is intentionally small and typed.  It is the
machine-readable inventory of procedural commitments that the kernel exposes
to an adopter; the JSON document is a generated projection, not a second
source of truth.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0.0"
ARTIFACT_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "constitutional-bill-of-materials.json"
)


@dataclass(frozen=True)
class Commitment:
    """One adopter-visible procedural commitment."""

    id: str
    commitment_class: str
    rule: str
    disposition: str
    source: str
    evidence_burden: str
    appeal_cost: str
    visibility: str
    amendment_path: str
    contestability: str
    recovery: str


# This is deliberately code, rather than prose copied into the generated BOM.
COMMITMENTS: list[Commitment] = [
    Commitment(
        "deny-wins",
        "decision_order",
        "Any deny veto blocks the decision.",
        "enforced",
        "agents/_governance.py:VetoChain",
        "all vetoes evaluated",
        "blocked action requires remediation",
        "decision result includes gate and reason",
        "change VetoChain semantics and tests",
        "reason is inspectable",
        "caller chooses a later retry or alternate path",
    ),
    Commitment(
        "unknown-fails-closed",
        "unknown_handling",
        "Unknown authority or required state blocks.",
        "enforced",
        "shared/policy_decision.py:FailMode.FAIL_CLOSED",
        "required field must be confirmed",
        "operator must supply or repair missing state",
        "required field is returned",
        "amend policy and version",
        "missing field is named",
        "no automatic unsafe fallback",
    ),
    Commitment(
        "evidence-thresholds",
        "evidence_burden",
        "Evidence floors and quality gates precede stronger claims or release.",
        "enforced",
        "config/review-lenses/registry.yaml; shared/route_metadata_schema.py",
        "frontier_review_required and receipt evidence",
        "additional review/receipt work",
        "findings and receipts are retained",
        "amend route metadata and gate tests",
        "independent review is required",
        "degraded routes remain blocked",
    ),
    Commitment(
        "appeal-is-explicit",
        "appeal_cost",
        "A block is not silently overridden; appeal requires an explicit governed path.",
        "enforced",
        "scripts/cc-task-gate.sh; shared/governance",
        "authority case and task evidence",
        "operator time and a new governed action",
        "block reason is visible",
        "amend the governing task/spec",
        "operator can contest with evidence",
        "preserve the blocked state until accepted",
    ),
    Commitment(
        "default-visibility",
        "visibility",
        "Decision reasons, receipts, and unknowns are observable rather than suppressed.",
        "enforced",
        "shared/policy_decision.py; shared/axiom_audit.py",
        "observable result fields",
        "inspection and remediation effort",
        "public claims remain scoped to evidence",
        "amend schema and publication gate",
        "audit findings are citable",
        "retain failed evidence for review",
    ),
    Commitment(
        "weight-defaults",
        "weights",
        "Axiom and route weights influence selection when no adopter profile replaces them.",
        "enforced",
        "axioms/registry.yaml; shared/axiom_registry.py",
        "declared weights are loaded",
        "profile selection or amendment effort",
        "weights are registry-visible",
        "operator-approved registry amendment",
        "weights can be inspected and challenged",
        "restore the prior versioned registry",
    ),
    Commitment(
        "amendment-path",
        "amendment",
        "Constitutional behavior changes through versioned source/spec amendments.",
        "enforced",
        "shared/policy_decision.py:POLICY_DECIDE_VERSION; cc-task contract",
        "task authority and tests",
        "review and release queue cost",
        "version stamps are emitted",
        "new governed task/spec and review",
        "change is diffable",
        "revert to a prior committed version",
    ),
    Commitment(
        "contestability",
        "contestability",
        "A decision exposes enough reason and required state for a challenge.",
        "enforced",
        "shared/policy_decision.py:Decision",
        "reason and required_field are mandatory outputs",
        "operator investigation cost",
        "reason/current value/remediation are visible",
        "amend Decision schema and consumers",
        "caller can dispute the stated gate",
        "hold action while disputed",
    ),
    Commitment(
        "recovery-is-bounded",
        "recovery",
        "Recovery attempts are bounded; exhaustion escalates instead of looping forever.",
        "enforced",
        "agents/studio_compositor/v4l2_stall_recovery.py",
        "fresh frame is required",
        "downtime or operator intervention",
        "recovery counters and escalation are observable",
        "amend recovery FSM and tests",
        "failure is escalated",
        "withhold the watchdog ping / restart the unit",
    ),
    Commitment(
        "unclassified-commitments",
        "unknown_class",
        "Commitments outside the classifier are emitted as unknown and counted.",
        "unknown",
        "shared/constitutional_bom.py:Commitment.disposition",
        "classification is incomplete",
        "classification review cost",
        "unknown appears in the BOM and report",
        "add a typed class and regeneration",
        "finding remains contestable",
        "do not infer a safe default; retain unknown",
    ),
]


REFERENCE_VALUES_PROFILE: dict[str, Any] = {
    "profile_id": "hapax-estate-reference",
    "label": "Explicit reference profile — example, not adopter default",
    "is_default": False,
    "weights": {
        "single_user": 100,
        "executive_function": 95,
        "corporate_boundary": 90,
        "interpersonal_transparency": 88,
        "management_governance": 85,
    },
}


def load_values_profile(profile_id: str | None = None) -> dict[str, Any] | None:
    """Load only an explicitly named profile; no substantive profile is defaulted."""
    if profile_id is None:
        return None
    if profile_id != REFERENCE_VALUES_PROFILE["profile_id"]:
        raise KeyError(profile_id)
    return json.loads(json.dumps(REFERENCE_VALUES_PROFILE))


def generate_bom(
    *, generated_on: str | None = None, commitments: list[Commitment] | None = None
) -> dict[str, Any]:
    """Generate the serializable BOM projection from the code registry."""
    rows = commitments if commitments is not None else COMMITMENTS
    unknowns = [row for row in rows if row.disposition == "unknown"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_on": generated_on or date.today().isoformat(),
        "source": "shared/constitutional_bom.py:COMMITMENTS",
        "commitments": [asdict(row) for row in rows],
        "unknown_count": len(unknowns),
        "unknown_disposition": "finding_and_review_required; never omitted",
        "reference_profile": load_values_profile("hapax-estate-reference"),
    }


def validate_completeness(artifact: dict[str, Any]) -> None:
    """Raise when any code commitment is absent or mismatched in the artifact."""
    artifact_rows = artifact.get("commitments")
    if not isinstance(artifact_rows, list):
        raise AssertionError("BOM has no commitments list")
    by_id = {row.get("id"): row for row in artifact_rows if isinstance(row, dict)}
    missing = [row.id for row in COMMITMENTS if row.id not in by_id]
    if missing:
        raise AssertionError(f"BOM is incomplete; missing code commitments: {missing}")
    if len(by_id) != len(COMMITMENTS):
        raise AssertionError("BOM contains commitments absent from code")
    for row in COMMITMENTS:
        if by_id[row.id] != asdict(row):
            raise AssertionError(f"BOM row differs from code commitment: {row.id}")
    if artifact.get("unknown_count") != sum(row.disposition == "unknown" for row in COMMITMENTS):
        raise AssertionError("BOM unknown_count differs from code")


__all__ = [
    "ARTIFACT_PATH",
    "COMMITMENTS",
    "REFERENCE_VALUES_PROFILE",
    "Commitment",
    "generate_bom",
    "load_values_profile",
    "validate_completeness",
]
