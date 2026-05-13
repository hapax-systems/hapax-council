#!/usr/bin/env python3
"""Build the v0 downstream contribution ledger for Token Capital evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GENERATED_AT = "2026-05-13T00:00:00Z"
AUTHORITY_CASE = "REQ-20260513-token-capital-public-surface-regate-v2"
TASK_ID = "downstream-contribution-ledger-v0-instrumentation"
DEFAULT_DESIGN_JSON = (
    REPO_ROOT / "docs/research/evidence/2026-05-13-downstream-contribution-measurement-design.json"
)
DEFAULT_JSON = (
    REPO_ROOT / "docs/research/evidence/2026-05-13-downstream-contribution-ledger-v0.json"
)
DEFAULT_MARKDOWN = DEFAULT_JSON.with_suffix(".md")
DEFAULT_VAULT_MARKDOWN = (
    Path.home()
    / "Documents/Personal/20-projects/hapax-research/audit/"
    / "2026-05-13-downstream-contribution-ledger-v0.md"
)
DEFAULT_VAULT_ROOT = Path.home() / "Documents/Personal/20-projects"

NON_NEGATIVE_STATUS = "not_negative"
VALID_PRIVACY_LABELS = frozenset(
    {
        "public",
        "internal_path_hash_only",
        "redacted_public_safe",
        "privacy_or_consent_blocked",
    }
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class IngestedArtifact:
    artifact_id: str
    kind: str
    path: str
    exists: bool
    sha256: str | None
    bytes: int | None = None
    status: str | None = None
    pr: str | int | None = None

    def to_report(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "path": self.path,
            "exists": self.exists,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "status": self.status,
            "pr": self.pr,
        }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def display_path(path: Path, *, repo_root: Path = REPO_ROOT) -> str:
    path = path.expanduser()
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        pass
    home = Path.home()
    try:
        return "~/" + str(path.resolve().relative_to(home))
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return payload


def _frontmatter_value(text: str, key: str) -> str | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    pattern = re.compile(rf"^{re.escape(key)}:\s*(.*?)\s*$", re.MULTILINE)
    match = pattern.search(text[3:end])
    if not match:
        return None
    value = match.group(1).strip()
    return value.strip("\"'") if value else None


def _artifact_from_path(path: Path, *, kind: str, repo_root: Path) -> IngestedArtifact:
    exists = path.is_file()
    return IngestedArtifact(
        artifact_id=path.stem,
        kind=kind,
        path=display_path(path, repo_root=repo_root),
        exists=exists,
        sha256=sha256_file(path) if exists else None,
        bytes=path.stat().st_size if exists else None,
    )


def collect_source_receipts(repo_root: Path = REPO_ROOT) -> list[dict[str, Any]]:
    evidence_root = repo_root / "docs/research/evidence"
    self_receipt_names = {
        "2026-05-13-downstream-contribution-ledger-v0.json",
        "2026-05-13-downstream-contribution-ledger-v0.md",
    }
    paths = [
        path
        for path in sorted(evidence_root.glob("*.json")) + sorted(evidence_root.glob("*.md"))
        if path.name not in self_receipt_names
    ]
    return [
        _artifact_from_path(path, kind="source_receipt", repo_root=repo_root).to_report()
        for path in paths
    ]


def collect_public_surface_gate_receipts(repo_root: Path = REPO_ROOT) -> list[dict[str, Any]]:
    paths = (
        repo_root / "docs/runbooks/public-surface-scrutiny-gate-v2.md",
        repo_root
        / "docs/research/evidence/2026-05-13-public-surface-source-of-truth-reconciliation.json",
        repo_root
        / "docs/research/evidence/2026-05-13-public-surface-source-of-truth-reconciliation.md",
        repo_root / "docs/research/evidence/2026-05-13-token-capital-claim-regate-v2.json",
    )
    return [
        _artifact_from_path(
            path, kind="public_surface_gate_receipt", repo_root=repo_root
        ).to_report()
        for path in paths
    ]


def collect_closed_cc_tasks(vault_root: Path = DEFAULT_VAULT_ROOT) -> dict[str, Any]:
    closed_root = vault_root / "hapax-cc-tasks/closed"
    if not closed_root.is_dir():
        return {
            "count": 0,
            "status_counts": {},
            "tasks_with_pr": 0,
            "aggregate_sha256": sha256_text(""),
            "emitted_metadata": [
                "count",
                "status_counts",
                "tasks_with_pr",
                "aggregate_sha256",
            ],
        }
    status_counts: Counter[str] = Counter()
    tasks_with_pr = 0
    digest_parts: list[str] = []
    for path in sorted(closed_root.glob("*.md")):
        exists = path.is_file()
        text = path.read_text(encoding="utf-8") if exists else ""
        status = _frontmatter_value(text, "status") or "unknown"
        pr = _frontmatter_value(text, "pr")
        file_hash = sha256_file(path) if exists else ""
        status_counts[status] += 1
        if pr and pr != "null":
            tasks_with_pr += 1
        digest_parts.append(f"{status}:{bool(pr and pr != 'null')}:{file_hash}")
    aggregate = sha256_text("\n".join(digest_parts))
    return {
        "count": len(digest_parts),
        "status_counts": dict(sorted(status_counts.items())),
        "tasks_with_pr": tasks_with_pr,
        "aggregate_sha256": aggregate,
        "emitted_metadata": [
            "count",
            "status_counts",
            "tasks_with_pr",
            "aggregate_sha256",
        ],
        "privacy_note": (
            "Closed cc-task paths, titles, bodies, and task identifiers are not emitted "
            "in the source-controlled ledger receipt."
        ),
    }


def build_input_inventory(
    *,
    repo_root: Path = REPO_ROOT,
    vault_root: Path = DEFAULT_VAULT_ROOT,
) -> dict[str, Any]:
    source_receipts = collect_source_receipts(repo_root)
    closed_tasks = collect_closed_cc_tasks(vault_root)
    public_gate_receipts = collect_public_surface_gate_receipts(repo_root)
    return {
        "source_receipts": source_receipts,
        "closed_cc_tasks": closed_tasks,
        "public_surface_gate_receipts": public_gate_receipts,
        "privacy_note": (
            "Source and public-gate receipts emit path/hash metadata. Closed cc-tasks emit "
            "aggregate counts and an aggregate digest only. No inventory path emits private "
            "excerpts or infers operator motive."
        ),
        "counts": {
            "source_receipts": len(source_receipts),
            "closed_cc_tasks": closed_tasks["count"],
            "public_surface_gate_receipts": len(public_gate_receipts),
        },
    }


def _file_hash_or_redacted(path: str, *, repo_root: Path) -> str:
    if path.startswith("redacted://"):
        return sha256_text(path)
    candidate = repo_root / path
    if candidate.is_file():
        return sha256_file(candidate)
    return sha256_text(path)


def default_records(repo_root: Path = REPO_ROOT) -> list[dict[str, Any]]:
    claim_regate = "docs/research/evidence/2026-05-13-token-capital-claim-regate-v2.json"
    public_gate = "docs/runbooks/public-surface-scrutiny-gate-v2.md"
    answer_eval = (
        "docs/research/2026-05-13-rag-answer-faithfulness-and-downstream-contribution-eval.md"
    )
    measurement_design = (
        "docs/research/evidence/2026-05-13-downstream-contribution-measurement-design.json"
    )
    return [
        {
            "event_id": "fixture-positive-quality-gate-unblock-claim-regate-to-public-gate",
            "event_class_id": "quality_gate_unblock",
            "source_token_path": claim_regate,
            "source_token_sha256": _file_hash_or_redacted(claim_regate, repo_root=repo_root),
            "downstream_artifact_path": public_gate,
            "downstream_artifact_sha256": _file_hash_or_redacted(public_gate, repo_root=repo_root),
            "authority_case": AUTHORITY_CASE,
            "attribution_window_id": "same_task_or_request",
            "provenance_edges": [
                {
                    "type": "used",
                    "source": claim_regate,
                    "target": public_gate,
                    "evidence": "public-surface gate consumes the claim ceiling and denied patterns",
                }
            ],
            "counterfactual_method": (
                "leave-one-out: remove the claim-regate receipt and the public gate has no "
                "machine-readable denied Token Capital claim classes to consume"
            ),
            "observed_outcome": "Public-surface gate v2 can fail denied Token Capital overclaim language.",
            "counterfactual_outcome": "Gate remains fail-closed without a consumed claim ceiling.",
            "delta": {
                "direction": "positive",
                "metric": "public_claim_gate_enforcement",
                "observed": "denied claim patterns available",
                "counterfactual": "no consumable denied-pattern receipt",
            },
            "negative_result_status": NON_NEGATIVE_STATUS,
            "privacy_label": "public",
            "operator_acceptance_state": "merged_pr_and_source_receipt",
            "claim_upgrade_allowed": False,
            "result_valence": "positive",
            "fixture_record": True,
        },
        {
            "event_id": "fixture-negative-answer-faithfulness-blocks-downstream-claim",
            "event_class_id": "research_hypothesis_revision",
            "source_token_path": answer_eval,
            "source_token_sha256": _file_hash_or_redacted(answer_eval, repo_root=repo_root),
            "downstream_artifact_path": claim_regate,
            "downstream_artifact_sha256": _file_hash_or_redacted(claim_regate, repo_root=repo_root),
            "authority_case": AUTHORITY_CASE,
            "attribution_window_id": "same_task_or_request",
            "provenance_edges": [
                {
                    "type": "wasInformedBy",
                    "source": answer_eval,
                    "target": claim_regate,
                    "evidence": "claim re-gate denies answer-faithfulness and downstream contribution upgrades",
                }
            ],
            "counterfactual_method": (
                "compare claim ceiling before and after the answer-faithfulness receipt; "
                "the observed local generator path does not support downstream-value language"
            ),
            "observed_outcome": "Answer-faithfulness and downstream-contribution claims remain denied.",
            "counterfactual_outcome": "Without the receipt, the claim gate would lack answer-level evidence.",
            "delta": {
                "direction": "negative",
                "metric": "claim_upgrade_support",
                "observed": "answer_unfaithful",
                "counterfactual": "unmeasured",
            },
            "negative_result_status": "answer_unfaithful",
            "privacy_label": "public",
            "operator_acceptance_state": "merged_pr_and_source_receipt",
            "claim_upgrade_allowed": False,
            "result_valence": "negative",
            "fixture_record": True,
        },
        {
            "event_id": "fixture-privacy-blocked-operator-decision-record",
            "event_class_id": "operator_decision_support",
            "source_token_path": "redacted://operator-private-decision-record",
            "source_token_sha256": _file_hash_or_redacted(
                "redacted://operator-private-decision-record", repo_root=repo_root
            ),
            "downstream_artifact_path": measurement_design,
            "downstream_artifact_sha256": _file_hash_or_redacted(
                measurement_design, repo_root=repo_root
            ),
            "authority_case": AUTHORITY_CASE,
            "attribution_window_id": "same_task_or_request",
            "provenance_edges": [
                {
                    "type": "privacyBlocked",
                    "source": "redacted://operator-private-decision-record",
                    "target": measurement_design,
                    "evidence": "operator-private decision content is not logged by the ledger",
                }
            ],
            "counterfactual_method": (
                "privacy fail-closed: do not inspect or infer motive from private operator state"
            ),
            "observed_outcome": "Event is retained only as a privacy-blocked count.",
            "counterfactual_outcome": "Logging private content would violate the measurement-design boundary.",
            "delta": {
                "direction": "blocked",
                "metric": "privacy_and_operator_agency",
                "observed": "privacy_or_consent_blocked",
                "counterfactual": "unsafe_private_logging",
            },
            "negative_result_status": "privacy_or_consent_blocked",
            "privacy_label": "privacy_or_consent_blocked",
            "operator_acceptance_state": "veto_or_missing_public_label_respected",
            "claim_upgrade_allowed": False,
            "result_valence": "privacy_blocked",
            "fixture_record": True,
        },
    ]


def measurement_required_fields(design: Mapping[str, Any]) -> tuple[str, ...]:
    schema = design.get("measurement_record_schema", {})
    if not isinstance(schema, Mapping):
        return ()
    fields = schema.get("required_fields", ())
    if not isinstance(fields, Sequence) or isinstance(fields, str):
        return ()
    return tuple(str(field) for field in fields)


def negative_statuses(design: Mapping[str, Any]) -> set[str]:
    statuses = {NON_NEGATIVE_STATUS}
    for item in design.get("negative_result_statuses", []):
        if isinstance(item, Mapping) and item.get("status"):
            statuses.add(str(item["status"]))
    return statuses


def normalize_record(record: Mapping[str, Any], design: Mapping[str, Any]) -> dict[str, Any]:
    schema = design.get("measurement_record_schema", {})
    defaults = schema.get("fail_closed_defaults", {}) if isinstance(schema, Mapping) else {}
    normalized = dict(record)
    if isinstance(defaults, Mapping):
        for key, value in defaults.items():
            normalized.setdefault(str(key), value)
    normalized.setdefault("claim_upgrade_allowed", False)
    return normalized


def validate_record(record: Mapping[str, Any], design: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    required = measurement_required_fields(design)
    for field in required:
        if field not in record:
            errors.append(f"missing_required_field:{field}")

    for field in ("source_token_sha256", "downstream_artifact_sha256"):
        value = record.get(field)
        if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
            errors.append(f"invalid_sha256:{field}")

    edges = record.get("provenance_edges")
    if not isinstance(edges, list) or not edges:
        errors.append("missing_attribution_edge:provenance_edges")

    counterfactual = record.get("counterfactual_method")
    if not isinstance(counterfactual, str) or not counterfactual.strip():
        errors.append("missing_counterfactual_method")

    negative_status = record.get("negative_result_status")
    if not isinstance(negative_status, str) or not negative_status.strip():
        errors.append("missing_negative_result_status")
    elif negative_status not in negative_statuses(design):
        errors.append(f"unknown_negative_result_status:{negative_status}")

    privacy_label = record.get("privacy_label")
    if not isinstance(privacy_label, str) or not privacy_label.strip():
        errors.append("missing_privacy_label")
    elif privacy_label not in VALID_PRIVACY_LABELS:
        errors.append(f"unsupported_privacy_label:{privacy_label}")

    if record.get("claim_upgrade_allowed") is not False:
        errors.append("claim_upgrade_must_fail_closed")

    return errors


def validate_records(
    records: Sequence[Mapping[str, Any]], design: Mapping[str, Any]
) -> list[dict[str, Any]]:
    validations: list[dict[str, Any]] = []
    for record in records:
        event_id = str(record.get("event_id", "unknown"))
        errors = validate_record(record, design)
        validations.append({"event_id": event_id, "ok": not errors, "errors": errors})
    return validations


def fixture_valence_counts(records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = Counter(str(record.get("result_valence", "unknown")) for record in records)
    return {key: counts.get(key, 0) for key in ("positive", "negative", "privacy_blocked")}


def claim_upgrade_allowed(report: Mapping[str, Any]) -> bool:
    predicates = report.get("gate_predicates", {})
    if not isinstance(predicates, Mapping):
        return False
    required = (
        "all_records_valid",
        "read_only_ingest_completed",
        "fixture_run_contains_required_valences",
        "eligible_positive_events_above_threshold",
        "privacy_and_operator_agency_passed",
        "answer_support_passed_when_generation_is_in_path",
        "future_public_claim_gate_permits_downstream_language",
    )
    return all(predicates.get(key) is True for key in required)


def build_report(
    *,
    design_path: Path = DEFAULT_DESIGN_JSON,
    repo_root: Path = REPO_ROOT,
    vault_root: Path = DEFAULT_VAULT_ROOT,
    records: Sequence[Mapping[str, Any]] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or DEFAULT_GENERATED_AT
    design = read_json(design_path)
    normalized_records = [
        normalize_record(record, design) for record in (records or default_records(repo_root))
    ]
    validations = validate_records(normalized_records, design)
    valence_counts = fixture_valence_counts(normalized_records)
    fixture_ok = all(valence_counts[key] >= 1 for key in valence_counts)
    report: dict[str, Any] = {
        "generated_at": generated_at,
        "generated_by": "scripts/downstream_contribution_ledger_v0.py",
        "authority_case": AUTHORITY_CASE,
        "task_id": TASK_ID,
        "overall_decision": "ledger_v0_instrumented_no_claim_upgrade",
        "current_claim_ceiling": {
            "status": "fixture_ledger_only_no_downstream_claim_upgrade",
            "allowed_summary": (
                "The project may say a downstream contribution ledger schema and fixture "
                "run exist for durable artifact influence records."
            ),
            "denied_summary": (
                "The project may not present this fixture ledger as evidence for Token "
                "Capital downstream contribution, appreciation, recursive economic "
                "effects, or economic value."
            ),
        },
        "design_receipt": {
            "path": display_path(design_path, repo_root=repo_root),
            "sha256": sha256_file(design_path) if design_path.is_file() else None,
            "overall_decision": design.get("overall_decision"),
            "claim_upgrade_allowed_now": design.get("gate_predicates", {}).get(
                "claim_upgrade_allowed_now"
            )
            if isinstance(design.get("gate_predicates"), Mapping)
            else None,
        },
        "measurement_record_schema": design.get("measurement_record_schema"),
        "records": normalized_records,
        "validations": validations,
        "input_inventory": build_input_inventory(repo_root=repo_root, vault_root=vault_root),
        "summary": {
            "record_count": len(normalized_records),
            "valid_record_count": sum(1 for validation in validations if validation["ok"]),
            "invalid_record_count": sum(1 for validation in validations if not validation["ok"]),
            "fixture_valence_counts": valence_counts,
            "records_are_fixture_or_synthetic": all(
                record.get("fixture_record") is True for record in normalized_records
            ),
        },
        "gate_predicates": {
            "all_records_valid": all(validation["ok"] for validation in validations),
            "read_only_ingest_completed": True,
            "fixture_run_contains_required_valences": fixture_ok,
            "future_ledger_run_receipt_consumed": True,
            "eligible_positive_events_above_threshold": False,
            "privacy_and_operator_agency_passed": True,
            "answer_support_passed_when_generation_is_in_path": False,
            "future_public_claim_gate_permits_downstream_language": False,
            "claim_upgrade_allowed_now": False,
        },
        "claim_upgrade_note": (
            "No Token Capital claim upgrade is allowed until a future public claim gate "
            "explicitly permits downstream-contribution language after non-fixture ledger "
            "evidence exceeds its threshold."
        ),
    }
    report["gate_predicates"]["claim_upgrade_allowed_now"] = claim_upgrade_allowed(report)
    return report


def _markdown_list(items: Sequence[str]) -> list[str]:
    return [f"- {item}" for item in items]


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "---",
        'title: "Downstream Contribution Ledger V0"',
        "date: 2026-05-13",
        f"authority_case: {report['authority_case']}",
        "status: receipt",
        "mutation_surface: source_docs",
        "---",
        "",
        "# Downstream Contribution Ledger V0",
        "",
        f"Generated at: `{report['generated_at']}`",
        "",
        "## Decision",
        "",
        f"- Overall decision: `{report['overall_decision']}`",
        f"- Current ceiling: `{report['current_claim_ceiling']['status']}`",
        f"- Allowed summary: {report['current_claim_ceiling']['allowed_summary']}",
        f"- Denied summary: {report['current_claim_ceiling']['denied_summary']}",
        f"- Claim upgrade note: {report['claim_upgrade_note']}",
        "",
        "## Design Receipt",
        "",
        f"- Path: `{report['design_receipt']['path']}`",
        f"- SHA-256: `{str(report['design_receipt']['sha256'])[:12]}`",
        f"- Decision: `{report['design_receipt']['overall_decision']}`",
        "",
        "## Input Inventory",
        "",
        f"- Source receipts: `{report['input_inventory']['counts']['source_receipts']}`",
        f"- Closed cc-tasks: `{report['input_inventory']['counts']['closed_cc_tasks']}`",
        "- Public-surface gate receipts: "
        f"`{report['input_inventory']['counts']['public_surface_gate_receipts']}`",
        f"- Privacy note: {report['input_inventory']['privacy_note']}",
        "",
        "## Records",
        "",
        "| Event | Class | Valence | Negative status | Privacy label | Valid |",
        "|---|---|---|---|---|---:|",
    ]
    validations = {item["event_id"]: item for item in report["validations"]}
    for record in report["records"]:
        event_id = record["event_id"]
        valid = validations.get(event_id, {}).get("ok", False)
        lines.append(
            f"| `{event_id}` | `{record['event_class_id']}` | "
            f"`{record.get('result_valence')}` | `{record['negative_result_status']}` | "
            f"`{record['privacy_label']}` | `{valid}` |"
        )

    lines.extend(
        [
            "",
            "## Fixture Valence Counts",
            "",
        ]
    )
    for key, value in report["summary"]["fixture_valence_counts"].items():
        lines.append(f"- `{key}`: `{value}`")

    lines.extend(
        [
            "",
            "## Gate Predicates",
            "",
        ]
    )
    for key, value in report["gate_predicates"].items():
        lines.append(f"- `{key}`: `{value}`")

    lines.extend(
        [
            "",
            "## Validation",
            "",
        ]
    )
    for validation in report["validations"]:
        if validation["ok"]:
            lines.append(f"- `{validation['event_id']}`: valid")
        else:
            errors = ", ".join(validation["errors"])
            lines.append(f"- `{validation['event_id']}`: invalid - {errors}")

    return "\n".join(lines).rstrip() + "\n"


def write_report(
    report: Mapping[str, Any],
    *,
    json_path: Path,
    markdown_path: Path,
    vault_markdown_path: Path | None = None,
) -> tuple[Path, Path, Path | None]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown = render_markdown(report)
    markdown_path.write_text(markdown, encoding="utf-8")
    if vault_markdown_path is not None:
        vault_markdown_path.parent.mkdir(parents=True, exist_ok=True)
        vault_markdown_path.write_text(markdown, encoding="utf-8")
    return json_path, markdown_path, vault_markdown_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", type=Path, default=DEFAULT_DESIGN_JSON)
    parser.add_argument("--output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--vault-markdown", type=Path, default=DEFAULT_VAULT_MARKDOWN)
    parser.add_argument("--no-vault-markdown", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_report(design_path=args.design)
    vault_markdown = None if args.no_vault_markdown else args.vault_markdown
    write_report(
        report,
        json_path=args.output,
        markdown_path=args.markdown,
        vault_markdown_path=vault_markdown,
    )
    if report["summary"]["invalid_record_count"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
