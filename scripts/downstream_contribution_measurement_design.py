#!/usr/bin/env python3
"""Design downstream contribution measurement for Token Capital evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GENERATED_AT = "2026-05-13T00:00:00Z"
AUTHORITY_CASE = "REQ-20260513-token-capital-public-surface-regate-v2"
TASK_ID = "downstream-contribution-measurement-design"
DEFAULT_JSON = (
    REPO_ROOT / "docs/research/evidence/2026-05-13-downstream-contribution-measurement-design.json"
)
DEFAULT_MARKDOWN = (
    REPO_ROOT / "docs/research/evidence/2026-05-13-downstream-contribution-measurement-design.md"
)
DEFAULT_VAULT_MARKDOWN = (
    Path.home()
    / "Documents/Personal/20-projects/hapax-research/audit/"
    / "2026-05-13-downstream-contribution-measurement-design.md"
)
DEFAULT_FOLLOWUP_TASK = (
    Path.home()
    / "Documents/Personal/20-projects/hapax-cc-tasks/active/"
    / "downstream-contribution-ledger-v0-instrumentation.md"
)
PARENT_REQUEST = (
    Path.home()
    / "Documents/Personal/20-projects/hapax-requests/active/"
    / "REQ-20260513-token-capital-public-surface-regate-v2.md"
)


@dataclass(frozen=True)
class EvidenceArtifact:
    artifact_id: str
    title: str
    path: Path
    pr: int
    role: str


DEFAULT_EVIDENCE: tuple[EvidenceArtifact, ...] = (
    EvidenceArtifact(
        artifact_id="answer-faithfulness-ablation",
        title="RAG answer faithfulness and answer-metric ablation receipt",
        path=REPO_ROOT
        / "docs/research/2026-05-13-rag-answer-faithfulness-and-downstream-contribution-eval.md",
        pr=3212,
        role="shows existing downstream field is answer-metric ablation only",
    ),
    EvidenceArtifact(
        artifact_id="corpus-utilization-denominator",
        title="Token Capital corpus utilization denominator",
        path=REPO_ROOT / "docs/research/2026-05-13-token-capital-corpus-utilization-denominator.md",
        pr=3213,
        role="separates denominator, indexing, retrieval, answer context, and downstream use",
    ),
    EvidenceArtifact(
        artifact_id="claim-regate-v2",
        title="Token Capital claim re-gate v2",
        path=REPO_ROOT / "docs/research/evidence/2026-05-13-token-capital-claim-regate-v2.md",
        pr=3215,
        role="denies downstream contribution and economic claim upgrades",
    ),
    EvidenceArtifact(
        artifact_id="public-surface-scrutiny-gate-v2",
        title="Public surface scrutiny gate v2",
        path=REPO_ROOT / "docs/runbooks/public-surface-scrutiny-gate-v2.md",
        pr=3216,
        role="prevents unsupported public claim language",
    ),
    EvidenceArtifact(
        artifact_id="carrier-dynamics-separation",
        title="Carrier Dynamics formalization track",
        path=REPO_ROOT / "docs/research/2026-05-12-carrier-dynamics-formalization-track.md",
        pr=3158,
        role="keeps provenance and consent synergies separate from Token Capital proof",
    ),
)

METHODOLOGY_REFERENCES: tuple[dict[str, str], ...] = (
    {
        "reference_id": "w3c-prov-dm",
        "title": "W3C PROV-DM",
        "url": "https://www.w3.org/TR/prov-dm/",
        "role": (
            "Use entities, activities, agents, derivations, attribution, and primary "
            "source relations as the minimum provenance vocabulary."
        ),
    },
    {
        "reference_id": "rubin-1974-potential-outcomes",
        "title": "Rubin 1974 causal effects of treatments",
        "url": "https://www.ets.org/research/policy_research_reports/publications/article/1974/hrbx.html",
        "role": (
            "Treat contribution as a potential-outcome question: compare observed "
            "artifact outcome with a specified no-source-token counterfactual."
        ),
    },
    {
        "reference_id": "pearl-2009-causal-inference-overview",
        "title": "Pearl 2009 causal inference overview",
        "url": (
            "https://projecteuclid.org/journals/statistics-surveys/volume-3/"
            "issue-none/Causal-inference-in-statistics-An-overview/10.1214/09-SS057.full"
        ),
        "role": (
            "Keep causal assumptions explicit instead of inferring contribution from "
            "association, retrieval, or temporal proximity."
        ),
    },
    {
        "reference_id": "mackinlay-1997-event-studies",
        "title": "MacKinlay 1997 event studies in economics and finance",
        "url": "https://econpapers.repec.org/RePEc:aea:jeclit:v:35:y:1997:i:1:p:13-39",
        "role": (
            "Use predeclared event and estimation windows for any event-study-style "
            "diagnostic; do not treat a window alone as causal proof."
        ),
    },
    {
        "reference_id": "koh-liang-2017-influence-functions",
        "title": "Koh and Liang 2017 influence functions",
        "url": "https://proceedings.mlr.press/v70/koh17a.html",
        "role": (
            "Reserve influence-style attribution for future model-training influence "
            "questions; current RAG evidence should use replay/ablation first."
        ),
    },
)

METRIC_LAYERS: tuple[dict[str, Any], ...] = (
    {
        "layer_id": "retrieval_substrate",
        "question": "Can an approved source be indexed, retrieved, and placed in answer context?",
        "current_metrics": [
            "denominator_file_count",
            "indexed_file_count",
            "retrieved_file_count",
            "answer_context_file_count",
            "precision_at_k",
            "recall_at_k",
            "ndcg_at_k",
        ],
        "claim_status": "substrate_only_not_value",
    },
    {
        "layer_id": "answer_support",
        "question": "Does a generated or extractive answer faithfully support required claims?",
        "current_metrics": [
            "required_claim_recall",
            "supported_claim_rate",
            "faithfulness",
            "refusal_hit_rate",
            "forbidden_claim_hits",
        ],
        "claim_status": "answer_quality_not_downstream_value",
    },
    {
        "layer_id": "downstream_contribution",
        "question": "Did a source token change a later durable artifact or operator decision?",
        "current_metrics": [
            "eligible_contribution_event_count",
            "counterfactual_delta",
            "artifact_quality_delta",
            "gate_outcome_delta",
            "negative_event_count",
            "privacy_block_count",
        ],
        "claim_status": "not_measured_until_ledger_run",
    },
)

EVENT_CLASSES: tuple[dict[str, Any], ...] = (
    {
        "event_class_id": "artifact_derivation",
        "definition": (
            "A later durable artifact explicitly derives from a source token through "
            "citation, path reference, commit reference, or provenance edge."
        ),
        "eligible_artifacts": [
            "merged pull request",
            "source-controlled research receipt",
            "vault research mirror",
            "closed cc-task with closure evidence",
        ],
        "minimum_evidence": [
            "source_token_path_or_hash",
            "downstream_artifact_path_or_hash",
            "explicit derivation edge or citation",
            "operator or reviewer acceptance if the artifact is public-facing",
        ],
        "counterfactual": (
            "Replay the production step without the source token, or compare against a "
            "matched baseline artifact that had no access to the source token."
        ),
        "negative_results": [
            "explicit citation absent",
            "artifact not durable",
            "artifact exists but counterfactual delta is zero or unfavorable",
        ],
    },
    {
        "event_class_id": "operator_decision_support",
        "definition": (
            "An operator-approved decision record cites a source token and changes a "
            "choice, priority, acceptance, rejection, or scope boundary."
        ),
        "eligible_artifacts": [
            "operator-authored request update",
            "accepted PR review decision",
            "cc-task reprioritization record",
            "documented public-claim ceiling decision",
        ],
        "minimum_evidence": [
            "decision_record_path",
            "source_token_path_or_hash",
            "decision_before_or_available_alternative",
            "operator-visible acceptance or override state",
        ],
        "counterfactual": (
            "Compare with the documented pre-decision state, or run a blinded proposal "
            "generation pass without the source token and score the chosen difference."
        ),
        "negative_results": [
            "operator motive inferred without a decision record",
            "decision only temporally follows the source token",
            "decision lacks a documented alternative",
        ],
    },
    {
        "event_class_id": "quality_gate_unblock",
        "definition": (
            "A prior source token enables a deterministic gate, validator, or claim "
            "ceiling to pass or fail correctly on a later artifact."
        ),
        "eligible_artifacts": [
            "public-surface gate receipt",
            "claim re-gate receipt",
            "validation harness receipt",
            "CI or local deterministic gate output",
        ],
        "minimum_evidence": [
            "gate_command",
            "gate_input_receipt",
            "source_token_path_or_hash",
            "observed_gate_outcome",
            "leave_one_out_gate_outcome",
        ],
        "counterfactual": (
            "Run the same gate with the source token or receipt removed, masked, or "
            "replaced by the previous baseline receipt."
        ),
        "negative_results": [
            "gate outcome unchanged under leave-one-out",
            "gate is nondeterministic or has hidden dependencies",
            "gate pass relies on unsupported claim language",
        ],
    },
    {
        "event_class_id": "public_surface_revision",
        "definition": (
            "A source token causes public copy to become more accurate, bounded, or "
            "source-reconciled without upgrading unsupported Token Capital claims."
        ),
        "eligible_artifacts": [
            "weblog post source",
            "hapax.omg.lol landing page source",
            "publication draft",
            "source-of-truth reconciliation receipt",
        ],
        "minimum_evidence": [
            "before_copy_hash",
            "after_copy_hash",
            "source_token_path_or_hash",
            "public_surface_gate_result",
        ],
        "counterfactual": (
            "Compare against the pre-revision copy and the gate result that would have "
            "occurred without the source token's bound or citation."
        ),
        "negative_results": [
            "copy is unpublished and unreviewed",
            "copy passes only because denied claims were removed manually without provenance",
            "revision creates new unsupported claims",
        ],
    },
    {
        "event_class_id": "research_hypothesis_revision",
        "definition": (
            "A source token changes the status of a theory claim by strengthening, "
            "weakening, bounding, or falsifying it in a durable research artifact."
        ),
        "eligible_artifacts": [
            "research basis repair receipt",
            "audit follow-up",
            "claim class registry",
            "methodology note",
        ],
        "minimum_evidence": [
            "prior_claim_state",
            "new_claim_state",
            "source_token_path_or_hash",
            "reviewed rationale",
        ],
        "counterfactual": (
            "Compare against the previous claim state and require the revision rationale "
            "to identify why the source token changed the state."
        ),
        "negative_results": [
            "claim state changes without a cited evidence path",
            "revision imports Shapley-value or appreciation math without a measured utility",
            "revision conflates Carrier Dynamics or provenance with economic value",
        ],
    },
)

ELIGIBLE_DOWNSTREAM_ARTIFACTS: tuple[str, ...] = (
    "merged PRs and merge commits",
    "source-controlled research/evidence receipts",
    "vault mirrors with source-controlled canonical counterparts",
    "closed cc-tasks with closure evidence",
    "operator-authored request state changes",
    "public copy sources that pass the public-surface gate",
)

EXCLUDED_SIGNALS: tuple[str, ...] = (
    "raw retrieval hit",
    "answer-context exposure without a later artifact",
    "unpersisted chat output",
    "model-drafted text with no operator or reviewer acceptance",
    "temporal proximity without a derivation edge",
    "engagement, attention, or aesthetic preference without a measured artifact outcome",
    "private or consent-sensitive content that cannot be logged with approved labels",
)

ATTRIBUTION_WINDOWS: tuple[dict[str, Any], ...] = (
    {
        "window_id": "same_task_or_request",
        "duration": "from task claim to task closure, or from request update to next closure",
        "strength": "strong",
        "requirements": ["same authority_case", "explicit source reference"],
    },
    {
        "window_id": "default_short_window",
        "duration": "7 days after source token availability",
        "strength": "moderate",
        "requirements": ["explicit source reference", "no incompatible intervening source"],
    },
    {
        "window_id": "extended_bridge_window",
        "duration": "30 days maximum",
        "strength": "weak_without_bridge",
        "requirements": [
            "explicit bridge record",
            "unchanged claim target",
            "reviewer or operator acceptance",
        ],
    },
)

NEGATIVE_RESULT_STATUSES: tuple[dict[str, str], ...] = (
    {
        "status": "no_downstream_artifact",
        "meaning": "The source token was retrieved or read, but no durable later artifact exists.",
    },
    {
        "status": "no_attribution_edge",
        "meaning": "The later artifact has no explicit citation, derivation, or decision record.",
    },
    {
        "status": "counterfactual_no_effect",
        "meaning": "Leave-one-out or matched baseline comparison shows no useful delta.",
    },
    {
        "status": "negative_or_harmful_effect",
        "meaning": "The source token worsened claim accuracy, gate behavior, or artifact quality.",
    },
    {
        "status": "privacy_or_consent_blocked",
        "meaning": "The event cannot be logged without violating consent or disclosure limits.",
    },
    {
        "status": "answer_unfaithful",
        "meaning": "The downstream artifact relied on an answer that failed support or faithfulness checks.",
    },
)

PRIVACY_OPERATOR_CONSTRAINTS: tuple[str, ...] = (
    "No hidden operator surveillance: count explicit artifact and decision records, not inferred motive.",
    "No non-operator person data unless consent labels and redaction policy allow the record.",
    "Log hashes, paths, claim classes, and short bounded excerpts only when public-safe.",
    "Operator veto or override can block event logging without being treated as a negative motive.",
    "Consent revocation or missing labels produces a fail-closed privacy_or_consent_blocked event.",
)

MEASUREMENT_RECORD_SCHEMA: dict[str, Any] = {
    "required_fields": [
        "event_id",
        "event_class_id",
        "source_token_path",
        "source_token_sha256",
        "downstream_artifact_path",
        "downstream_artifact_sha256",
        "authority_case",
        "attribution_window_id",
        "provenance_edges",
        "counterfactual_method",
        "observed_outcome",
        "counterfactual_outcome",
        "delta",
        "negative_result_status",
        "privacy_label",
        "operator_acceptance_state",
        "claim_upgrade_allowed",
    ],
    "fail_closed_defaults": {
        "claim_upgrade_allowed": False,
        "negative_result_status": "no_attribution_edge",
        "privacy_label": "unknown",
    },
}

INSTRUMENTABLE_EVENT_STREAM: dict[str, Any] = {
    "status": "identified",
    "stream_id": "artifact_provenance_and_gate_receipts_v0",
    "description": (
        "A first ledger can be built from existing source-controlled receipts, PR metadata, "
        "closed cc-task closure evidence, public-surface gate outputs, and explicit path/hash "
        "references. This is an artifact stream, not operator activity surveillance."
    ),
    "inputs": [
        "docs/research/evidence/*.json",
        "docs/research/evidence/*.md",
        "docs/runbooks/public-surface-scrutiny-gate-v2.md",
        "$HOME/Documents/Personal/20-projects/hapax-cc-tasks/closed/*.md",
        "$HOME/Documents/Personal/20-projects/hapax-requests/active/*.md",
        "GitHub PR numbers and merge commits recorded in task closure evidence",
    ],
    "limits": [
        "Cannot infer downstream contribution from retrieval logs alone.",
        "Cannot infer operator motive without an explicit operator-visible decision record.",
        "Cannot upgrade public claims until a future ledger run and public gate permit it.",
    ],
}

FIRST_FOLLOWUP_TASK: dict[str, Any] = {
    "task_id": "downstream-contribution-ledger-v0-instrumentation",
    "title": "Implement downstream contribution ledger v0 instrumentation",
    "status": "offered",
    "priority": "p1",
    "wsjf": 16.0,
    "wsjf_formula": "BV 8, TC 6, RR/OE 8, size 1.4 -> WSJF 15.7, rounded to 16.0",
    "depends_on": [
        "downstream-contribution-measurement-design",
        "public-surface-scrutiny-gate-v2",
    ],
    "branch": "codex/downstream-contribution-ledger-v0",
    "acceptance": [
        "Ledger schema implements the measurement record fields and fail-closed defaults.",
        "Validator rejects records without artifact hashes, attribution edge, privacy label, "
        "counterfactual method, or negative-result status.",
        "Read-only ingest covers source receipts, closed cc-tasks, and public-surface gate "
        "receipts without scraping private content or inferring operator motive.",
        "A fixture run records at least one positive, one negative, and one privacy-blocked "
        "example using synthetic or existing public-safe fixtures.",
        "The ledger receipt states that no Token Capital claim upgrade is allowed until a "
        "future public claim gate explicitly permits it.",
    ],
}


def display_path(path: Path) -> str:
    path = path.expanduser()
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        pass
    home = Path.home()
    try:
        return "$HOME/" + str(path.resolve().relative_to(home))
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence_to_row(artifact: EvidenceArtifact) -> dict[str, Any]:
    exists = artifact.path.is_file()
    return {
        "artifact_id": artifact.artifact_id,
        "title": artifact.title,
        "path": display_path(artifact.path),
        "pr": artifact.pr,
        "role": artifact.role,
        "exists": exists,
        "sha256": sha256_file(artifact.path) if exists else None,
        "bytes": artifact.path.stat().st_size if exists else None,
    }


def claim_upgrade_allowed(report: Mapping[str, Any]) -> bool:
    predicates = report.get("gate_predicates", {})
    if not isinstance(predicates, Mapping):
        return False
    required = (
        "all_design_evidence_present",
        "instrumentable_event_stream_identified",
        "future_ledger_run_receipt_consumed",
        "future_public_claim_gate_permits_downstream_language",
        "eligible_positive_events_above_threshold",
        "privacy_and_operator_agency_passed",
        "answer_support_passed_when_generation_is_in_path",
    )
    return all(predicates.get(key) is True for key in required)


def build_design(
    evidence: Sequence[EvidenceArtifact] = DEFAULT_EVIDENCE,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or DEFAULT_GENERATED_AT
    evidence_rows = [evidence_to_row(artifact) for artifact in evidence]
    missing = [row["artifact_id"] for row in evidence_rows if not row["exists"]]
    report: dict[str, Any] = {
        "generated_at": generated_at,
        "generated_by": "scripts/downstream_contribution_measurement_design.py",
        "authority_case": AUTHORITY_CASE,
        "task_id": TASK_ID,
        "overall_decision": "measurement_design_only_no_claim_upgrade",
        "current_claim_ceiling": {
            "status": "downstream_contribution_not_measured",
            "allowed_summary": (
                "The project may say it has a design for measuring downstream contribution "
                "and a candidate artifact stream."
            ),
            "denied_summary": (
                "The project may not say downstream contribution, token appreciation, "
                "economic value, or compounding value has been demonstrated."
            ),
        },
        "evidence_artifacts": evidence_rows,
        "missing_evidence_artifacts": missing,
        "methodology_references": list(METHODOLOGY_REFERENCES),
        "metric_layers": list(METRIC_LAYERS),
        "candidate_source_requirements": [
            "Persisted text or code artifact in the approved denominator or evidence corpus.",
            "Stable path and SHA-256 hash at measurement time.",
            "Known authority class and claim ceiling.",
            "Consent/privacy label sufficient for the intended ledger visibility.",
            "Availability timestamp or merge/publication timestamp.",
        ],
        "contribution_event_classes": list(EVENT_CLASSES),
        "eligible_downstream_artifacts": list(ELIGIBLE_DOWNSTREAM_ARTIFACTS),
        "excluded_signals": list(EXCLUDED_SIGNALS),
        "attribution_windows": list(ATTRIBUTION_WINDOWS),
        "negative_result_statuses": list(NEGATIVE_RESULT_STATUSES),
        "privacy_operator_agency_constraints": list(PRIVACY_OPERATOR_CONSTRAINTS),
        "measurement_record_schema": MEASUREMENT_RECORD_SCHEMA,
        "instrumentable_event_stream": INSTRUMENTABLE_EVENT_STREAM,
        "first_followup_task": FIRST_FOLLOWUP_TASK,
        "gate_predicates": {
            "all_design_evidence_present": not missing,
            "instrumentable_event_stream_identified": True,
            "future_ledger_run_receipt_consumed": False,
            "future_public_claim_gate_permits_downstream_language": False,
            "eligible_positive_events_above_threshold": False,
            "privacy_and_operator_agency_passed": False,
            "answer_support_passed_when_generation_is_in_path": False,
            "claim_upgrade_allowed_now": False,
        },
    }
    report["gate_predicates"]["claim_upgrade_allowed_now"] = claim_upgrade_allowed(report)
    return report


def _markdown_list(items: Sequence[str]) -> list[str]:
    return [f"- {item}" for item in items]


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "---",
        'title: "Downstream Contribution Measurement Design"',
        "date: 2026-05-13",
        f"authority_case: {report['authority_case']}",
        "status: design_receipt",
        "mutation_surface: source_docs",
        "---",
        "",
        "# Downstream Contribution Measurement Design",
        "",
        f"Generated at: `{report['generated_at']}`",
        "",
        "## Decision",
        "",
        f"- Overall decision: `{report['overall_decision']}`",
        f"- Current ceiling: `{report['current_claim_ceiling']['status']}`",
        f"- Allowed summary: {report['current_claim_ceiling']['allowed_summary']}",
        f"- Denied summary: {report['current_claim_ceiling']['denied_summary']}",
        "",
        "## Evidence Artifacts",
        "",
        "| Artifact | PR | Role | Present | SHA-256 |",
        "|---|---:|---|---:|---|",
    ]
    for row in report["evidence_artifacts"]:
        sha = row["sha256"][:12] if row["sha256"] else "missing"
        lines.append(
            f"| `{row['path']}` | #{row['pr']} | {row['role']} | `{row['exists']}` | `{sha}` |"
        )

    lines.extend(
        [
            "",
            "## Methodological Basis",
            "",
            "| Reference | Role |",
            "|---|---|",
        ]
    )
    for reference in report["methodology_references"]:
        lines.append(f"| [{reference['title']}]({reference['url']}) | {reference['role']} |")

    lines.extend(
        [
            "",
            "## Metric Separation",
            "",
            "| Layer | Question | Claim status |",
            "|---|---|---|",
        ]
    )
    for layer in report["metric_layers"]:
        lines.append(f"| `{layer['layer_id']}` | {layer['question']} | `{layer['claim_status']}` |")

    lines.extend(
        [
            "",
            "## Candidate Source Requirements",
            "",
            *_markdown_list(report["candidate_source_requirements"]),
            "",
            "## Contribution Event Classes",
            "",
        ]
    )
    for event_class in report["contribution_event_classes"]:
        lines.extend(
            [
                f"### `{event_class['event_class_id']}`",
                "",
                event_class["definition"],
                "",
                "Minimum evidence:",
                *_markdown_list(event_class["minimum_evidence"]),
                "",
                f"Counterfactual: {event_class['counterfactual']}",
                "",
                "Negative results:",
                *_markdown_list(event_class["negative_results"]),
                "",
            ]
        )

    lines.extend(
        [
            "## Eligible Downstream Artifacts",
            "",
            *_markdown_list(report["eligible_downstream_artifacts"]),
            "",
            "## Excluded Signals",
            "",
            *_markdown_list(report["excluded_signals"]),
            "",
            "## Attribution Windows",
            "",
            "| Window | Duration | Strength | Requirements |",
            "|---|---|---|---|",
        ]
    )
    for window in report["attribution_windows"]:
        requirements = "; ".join(window["requirements"])
        lines.append(
            f"| `{window['window_id']}` | {window['duration']} | `{window['strength']}` | "
            f"{requirements} |"
        )

    lines.extend(
        [
            "",
            "## Negative Result Handling",
            "",
            "| Status | Meaning |",
            "|---|---|",
        ]
    )
    for status in report["negative_result_statuses"]:
        lines.append(f"| `{status['status']}` | {status['meaning']} |")

    lines.extend(
        [
            "",
            "## Privacy And Operator Agency",
            "",
            *_markdown_list(report["privacy_operator_agency_constraints"]),
            "",
            "## Measurement Record Schema",
            "",
            "Required fields:",
            *_markdown_list(report["measurement_record_schema"]["required_fields"]),
            "",
            "Fail-closed defaults:",
        ]
    )
    for key, value in report["measurement_record_schema"]["fail_closed_defaults"].items():
        lines.append(f"- `{key}`: `{value}`")

    stream = report["instrumentable_event_stream"]
    lines.extend(
        [
            "",
            "## Instrumentable Event Stream",
            "",
            f"- Status: `{stream['status']}`",
            f"- Stream id: `{stream['stream_id']}`",
            f"- Description: {stream['description']}",
            "",
            "Inputs:",
            *_markdown_list(stream["inputs"]),
            "",
            "Limits:",
            *_markdown_list(stream["limits"]),
            "",
            "## Gate Predicates",
            "",
        ]
    )
    for key, value in report["gate_predicates"].items():
        lines.append(f"- `{key}`: `{value}`")

    followup = report["first_followup_task"]
    lines.extend(
        [
            "",
            "## First Follow-Up Task",
            "",
            f"- Task id: `{followup['task_id']}`",
            f"- Title: {followup['title']}",
            f"- WSJF: `{followup['wsjf']}` ({followup['wsjf_formula']})",
            f"- Branch: `{followup['branch']}`",
            "",
            "Acceptance:",
            *_markdown_list(followup["acceptance"]),
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def render_followup_task(report: Mapping[str, Any]) -> str:
    task = report["first_followup_task"]
    acceptance = "\n".join(f"- [ ] {item}" for item in task["acceptance"])
    depends_on = "\n".join(f"  - {item}" for item in task["depends_on"])
    return f"""---
type: cc-task
task_id: {task["task_id"]}
title: "{task["title"]}"
status: {task["status"]}
assigned_to: unassigned
priority: {task["priority"]}
wsjf: {task["wsjf"]}
depends_on:
{depends_on}
blocks: []
branch: {task["branch"]}
pr: null
created_at: 2026-05-13T00:00:00Z
updated_at: 2026-05-13T00:00:00Z
claimed_at: null
completed_at: null
parent_plan: {PARENT_REQUEST}
parent_spec: {PARENT_REQUEST}
parent_request: {PARENT_REQUEST}
authority_case: {AUTHORITY_CASE}
quality_floor: frontier_review_required
mutation_surface: source_and_vault_docs
authority_level: support_non_authoritative
effort_class: standard
risk_tier: T2
platform_suitability: [codex, claude]
tags: [token-capital, downstream-contribution, ledger, provenance, measurement]
---

# Downstream Contribution Ledger V0 Instrumentation

## Intent

Implement the first fail-closed ledger for downstream contribution evidence.
The ledger measures durable artifact influence only; it cannot upgrade Token
Capital public claims without a later run receipt and public claim gate.

## Acceptance Criteria

{acceptance}

## WSJF

{task["wsjf_formula"]}.

## Session Log
"""


def write_design(
    report: Mapping[str, Any],
    *,
    json_path: Path,
    markdown_path: Path,
    vault_markdown_path: Path | None = None,
    followup_task_path: Path | None = None,
) -> tuple[Path, Path, Path | None, Path | None]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown = render_markdown(report)
    markdown_path.write_text(markdown, encoding="utf-8")
    if vault_markdown_path is not None:
        vault_markdown_path.parent.mkdir(parents=True, exist_ok=True)
        vault_markdown_path.write_text(markdown, encoding="utf-8")
    if followup_task_path is not None:
        followup_task_path.parent.mkdir(parents=True, exist_ok=True)
        followup_task_path.write_text(render_followup_task(report), encoding="utf-8")
    return json_path, markdown_path, vault_markdown_path, followup_task_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--vault-markdown", type=Path, default=DEFAULT_VAULT_MARKDOWN)
    parser.add_argument("--no-vault-markdown", action="store_true")
    parser.add_argument("--followup-task", type=Path, default=DEFAULT_FOLLOWUP_TASK)
    parser.add_argument("--no-followup-task", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_design()
    vault_markdown = None if args.no_vault_markdown else args.vault_markdown
    followup_task = None if args.no_followup_task else args.followup_task
    write_design(
        report,
        json_path=args.output,
        markdown_path=args.markdown,
        vault_markdown_path=vault_markdown,
        followup_task_path=followup_task,
    )
    if report["missing_evidence_artifacts"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
