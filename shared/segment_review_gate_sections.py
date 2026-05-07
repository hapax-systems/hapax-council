"""Projection helpers for migrating segment review gates.

The current one-segment review gate is intentionally unchanged: every failing
automated criterion still blocks release. This module only projects those
criteria into the migration vocabulary so later patches can demote rubric/craft
readouts without accidentally weakening authority gates.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

GateSection = Literal[
    "hard_authority_gate",
    "structural_readout",
    "advisory_excellence_report",
]

HARD_AUTHORITY_GATE = "hard_authority_gate"
STRUCTURAL_READOUT = "structural_readout"
ADVISORY_EXCELLENCE_REPORT = "advisory_excellence_report"
SECTION_NAMES: tuple[GateSection, ...] = (
    HARD_AUTHORITY_GATE,
    STRUCTURAL_READOUT,
    ADVISORY_EXCELLENCE_REPORT,
)

CRITERION_SECTION: dict[str, GateSection] = {
    "artifact.exactly_one_manifest_accepted": HARD_AUTHORITY_GATE,
    "artifact.raw_loader_separation": HARD_AUTHORITY_GATE,
    "artifact.command_r_model": HARD_AUTHORITY_GATE,
    "artifact.no_validator_rewrite_phase": HARD_AUTHORITY_GATE,
    "artifact.prior_only_authority": HARD_AUTHORITY_GATE,
    "artifact.hash_receipt": HARD_AUTHORITY_GATE,
    "artifact.source_provenance_receipt": HARD_AUTHORITY_GATE,
    "artifact.prior_source_binding": HARD_AUTHORITY_GATE,
    "artifact.segment_prep_contract": HARD_AUTHORITY_GATE,
    "artifact.prepared_script_contract_binding": HARD_AUTHORITY_GATE,
    "live_event.report_freshness": HARD_AUTHORITY_GATE,
    "layout.hard_contract_replay": HARD_AUTHORITY_GATE,
    "script.no_framework_vocabulary_leakage": HARD_AUTHORITY_GATE,
    "script.source_consequence_bound": HARD_AUTHORITY_GATE,
    "actionability.supported": HARD_AUTHORITY_GATE,
    "actionability.claim_layout_binding": HARD_AUTHORITY_GATE,
    "actionability.receipt_freshness": HARD_AUTHORITY_GATE,
    "layout.responsible_proposal_only": HARD_AUTHORITY_GATE,
    "layout.intent_receipt_freshness": HARD_AUTHORITY_GATE,
    "layout.evidence_refs_are_content_refs": HARD_AUTHORITY_GATE,
    "layout.no_prepared_authority": HARD_AUTHORITY_GATE,
    "layout.no_static_camera_spoken_laundering": HARD_AUTHORITY_GATE,
    "live_event.good_or_better": STRUCTURAL_READOUT,
    "script.shape": STRUCTURAL_READOUT,
    "actionability.visible_or_doable_counterpart": STRUCTURAL_READOUT,
    "script.quality_floor": ADVISORY_EXCELLENCE_REPORT,
    "script.ideal_livestream_bit": ADVISORY_EXCELLENCE_REPORT,
    "script.source_fidelity": ADVISORY_EXCELLENCE_REPORT,
}

KNOWN_CURRENT_REVIEW_CRITERIA: tuple[str, ...] = tuple(CRITERION_SECTION)


def project_review_gate_sections(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Return a non-authoritative section projection for a review receipt.

    Unknown criteria default to the hard-authority section so newly added gates
    cannot silently become advisory during the migration.
    """

    automated_gate = receipt.get("automated_gate")
    raw_criteria = automated_gate.get("criteria") if isinstance(automated_gate, Mapping) else []
    criteria = _criteria(raw_criteria)
    sections = {name: _empty_section(name) for name in SECTION_NAMES}
    unknown: list[str] = []

    for item in criteria:
        name = item["name"]
        section_name = CRITERION_SECTION.get(name, HARD_AUTHORITY_GATE)
        if name not in CRITERION_SECTION:
            unknown.append(name)
        sections[section_name]["criteria"].append(item)
        if not item["passed"]:
            sections[section_name]["failed"].append(name)

    for section in sections.values():
        section["passed"] = not section["failed"]
        section["criterion_count"] = len(section["criteria"])

    current_failed = [item["name"] for item in criteria if not item["passed"]]
    advisory_or_structural_failed = [
        name
        for section_name in (STRUCTURAL_READOUT, ADVISORY_EXCELLENCE_REPORT)
        for name in sections[section_name]["failed"]
    ]
    return {
        "review_gate_section_projection_version": 1,
        **sections,
        "migration_guard": {
            "projection_only": True,
            "current_release_gate_unchanged": True,
            "unknown_criteria_default_to_hard_authority": True,
            "current_automated_gate_passed": bool(
                automated_gate.get("passed") if isinstance(automated_gate, Mapping) else False
            ),
            "current_failed_criteria": current_failed,
            "advisory_or_structural_failures_still_block_current_release": (
                advisory_or_structural_failed
            ),
            "unknown_criteria": unknown,
        },
    }


def _criteria(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        out.append({**dict(item), "name": name, "passed": item.get("passed") is True})
    return out


def _empty_section(name: GateSection) -> dict[str, Any]:
    return {
        "name": name,
        "passed": True,
        "criterion_count": 0,
        "criteria": [],
        "failed": [],
    }


__all__ = [
    "ADVISORY_EXCELLENCE_REPORT",
    "CRITERION_SECTION",
    "HARD_AUTHORITY_GATE",
    "KNOWN_CURRENT_REVIEW_CRITERIA",
    "STRUCTURAL_READOUT",
    "project_review_gate_sections",
]
