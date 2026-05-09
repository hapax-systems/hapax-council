#!/usr/bin/env python3
"""Read-only audit for route metadata seed candidates.

The audit classifies active cc-task and request notes using the canonical
frontmatter parser and route metadata assessment API. It never writes to the
vault unless explicitly asked to persist a copy of the JSON report under state.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.frontmatter import parse_frontmatter_with_diagnostics
from shared.route_metadata_schema import (
    RouteMetadataAssessment,
    RouteMetadataStatus,
    assess_route_metadata,
)

DEFAULT_TASK_ROOT = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks"
DEFAULT_REQUEST_ROOT = Path.home() / "Documents/Personal/20-projects/hapax-requests"
DEFAULT_STATE_DIR = Path.home() / ".local/state/hapax/route-metadata-seed-audit"

SourceType = Literal["cc_task", "hapax_request"]
HazardKind = Literal["frontmatter", "route_metadata_hold", "route_metadata_malformed"]


@dataclass(frozen=True)
class SourceRoots:
    task_root: str
    task_active_root: str
    request_root: str
    request_active_root: str


@dataclass
class AuditCounts:
    task_notes: int = 0
    request_notes: int = 0
    audited_notes: int = 0
    explicit: int = 0
    derived: int = 0
    hold: int = 0
    malformed_route_metadata: int = 0
    malformed_frontmatter: int = 0
    candidates: int = 0
    hazards: int = 0


@dataclass(frozen=True)
class SeedCandidate:
    source_type: SourceType
    path: str
    id: str
    title: str | None
    route_status: Literal["derived"]
    write_allowed: bool
    derived_fields: list[str]
    proposed_metadata: dict[str, Any]


@dataclass(frozen=True)
class AuditHazard:
    source_type: SourceType
    path: str
    id: str | None
    title: str | None
    hazard: HazardKind
    route_status: Literal["hold", "malformed"] | None
    write_allowed: bool
    reasons: list[str]
    missing_fields: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AuditReport:
    generated_at: str
    source_roots: SourceRoots
    counts: AuditCounts
    candidates: list[SeedCandidate]
    hazards: list[AuditHazard]
    report_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def audit_route_metadata_seed_candidates(
    task_root: Path = DEFAULT_TASK_ROOT,
    *,
    request_root: Path = DEFAULT_REQUEST_ROOT,
    generated_at: datetime | None = None,
) -> AuditReport:
    """Classify active notes that can or cannot receive route metadata seeds."""
    task_root = task_root.expanduser()
    request_root = request_root.expanduser()
    task_active_root = task_root / "active"
    request_active_root = request_root / "active"
    timestamp = _iso_utc(generated_at or datetime.now(UTC))
    counts = AuditCounts()
    candidates: list[SeedCandidate] = []
    hazards: list[AuditHazard] = []

    for note_path in _iter_markdown(task_active_root):
        counts.task_notes += 1
        _audit_note(
            note_path,
            source_root=task_root,
            source_type="cc_task",
            expected_type="cc-task",
            id_field="task_id",
            counts=counts,
            candidates=candidates,
            hazards=hazards,
        )

    for note_path in _iter_markdown(request_active_root):
        counts.request_notes += 1
        _audit_note(
            note_path,
            source_root=request_root,
            source_type="hapax_request",
            expected_type="hapax-request",
            id_field="request_id",
            counts=counts,
            candidates=candidates,
            hazards=hazards,
        )

    counts.candidates = len(candidates)
    counts.hazards = len(hazards)
    return AuditReport(
        generated_at=timestamp,
        source_roots=SourceRoots(
            task_root=str(task_root),
            task_active_root=str(task_active_root),
            request_root=str(request_root),
            request_active_root=str(request_active_root),
        ),
        counts=counts,
        candidates=candidates,
        hazards=hazards,
    )


def _audit_note(
    note_path: Path,
    *,
    source_root: Path,
    source_type: SourceType,
    expected_type: str,
    id_field: str,
    counts: AuditCounts,
    candidates: list[SeedCandidate],
    hazards: list[AuditHazard],
) -> None:
    display_path = _display_path(note_path, source_root)
    result = parse_frontmatter_with_diagnostics(note_path)
    if not result.ok:
        counts.malformed_frontmatter += 1
        hazards.append(
            AuditHazard(
                source_type=source_type,
                path=display_path,
                id=None,
                title=None,
                hazard="frontmatter",
                route_status=None,
                write_allowed=False,
                reasons=[result.error_kind or "frontmatter_error"],
                validation_errors=[result.error_message or "frontmatter parse failed"],
            )
        )
        return

    frontmatter = result.frontmatter or {}
    counts.audited_notes += 1
    note_id = _note_id(frontmatter, id_field, note_path)
    title = _optional_string(frontmatter.get("title"))

    if frontmatter.get("type") != expected_type:
        counts.hold += 1
        hazards.append(
            AuditHazard(
                source_type=source_type,
                path=display_path,
                id=note_id,
                title=title,
                hazard="route_metadata_hold",
                route_status="hold",
                write_allowed=False,
                reasons=[f"unexpected_type:{frontmatter.get('type')!s}"],
            )
        )
        return

    assessment = assess_route_metadata(frontmatter)
    _record_assessment(
        assessment,
        source_type=source_type,
        path=display_path,
        note_id=note_id,
        title=title,
        counts=counts,
        candidates=candidates,
        hazards=hazards,
    )


def _record_assessment(
    assessment: RouteMetadataAssessment,
    *,
    source_type: SourceType,
    path: str,
    note_id: str,
    title: str | None,
    counts: AuditCounts,
    candidates: list[SeedCandidate],
    hazards: list[AuditHazard],
) -> None:
    if assessment.status == RouteMetadataStatus.EXPLICIT:
        counts.explicit += 1
        return

    if assessment.status == RouteMetadataStatus.DERIVED:
        counts.derived += 1
        metadata = assessment.metadata
        candidates.append(
            SeedCandidate(
                source_type=source_type,
                path=path,
                id=note_id,
                title=title,
                route_status="derived",
                write_allowed=False,
                derived_fields=list(assessment.derived_fields),
                proposed_metadata=metadata.model_dump(mode="json") if metadata is not None else {},
            )
        )
        return

    if assessment.status == RouteMetadataStatus.HOLD:
        counts.hold += 1
        hazards.append(
            AuditHazard(
                source_type=source_type,
                path=path,
                id=note_id,
                title=title,
                hazard="route_metadata_hold",
                route_status="hold",
                write_allowed=False,
                reasons=list(assessment.hold_reasons),
                missing_fields=list(assessment.missing_fields),
            )
        )
        return

    counts.malformed_route_metadata += 1
    hazards.append(
        AuditHazard(
            source_type=source_type,
            path=path,
            id=note_id,
            title=title,
            hazard="route_metadata_malformed",
            route_status="malformed",
            write_allowed=False,
            reasons=["invalid_route_metadata"],
            missing_fields=list(assessment.missing_fields),
            validation_errors=list(assessment.validation_errors),
        )
    )


def _iter_markdown(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(root.glob("*.md"))


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _note_id(frontmatter: dict[str, Any], id_field: str, path: Path) -> str:
    value = _optional_string(frontmatter.get(id_field))
    return value or path.stem


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _write_state_report(report: AuditReport, state_dir: Path) -> AuditReport:
    state_dir = state_dir.expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    safe_timestamp = report.generated_at.replace(":", "").replace("-", "")
    report_path = state_dir / f"route-metadata-seed-audit-{safe_timestamp}.json"
    persisted = AuditReport(
        generated_at=report.generated_at,
        source_roots=report.source_roots,
        counts=report.counts,
        candidates=report.candidates,
        hazards=report.hazards,
        report_path=str(report_path),
    )
    report_path.write_text(_json_dumps(persisted.to_dict()) + "\n", encoding="utf-8")
    return persisted


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def _print_text_report(report: AuditReport) -> None:
    counts = report.counts
    print(f"route metadata seed audit generated_at={report.generated_at}")
    print(f"task_active_root={report.source_roots.task_active_root}")
    print(f"request_active_root={report.source_roots.request_active_root}")
    print(
        "counts "
        f"task_notes={counts.task_notes} request_notes={counts.request_notes} "
        f"explicit={counts.explicit} derived={counts.derived} hold={counts.hold} "
        f"malformed_frontmatter={counts.malformed_frontmatter} "
        f"malformed_route_metadata={counts.malformed_route_metadata} "
        f"candidates={counts.candidates} hazards={counts.hazards}"
    )
    for candidate in report.candidates:
        print(
            "CANDIDATE "
            f"{candidate.source_type} {candidate.path} id={candidate.id} "
            f"write_allowed={str(candidate.write_allowed).lower()}"
        )
    for hazard in report.hazards:
        reasons = ",".join(hazard.reasons) if hazard.reasons else "none"
        print(
            "HAZARD "
            f"{hazard.source_type} {hazard.path} id={hazard.id or 'unknown'} "
            f"hazard={hazard.hazard} reasons={reasons}"
        )
    if report.report_path:
        print(f"report_path={report.report_path}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Classify active route metadata seed candidates without writing notes."
    )
    parser.add_argument(
        "--task-root",
        type=Path,
        default=DEFAULT_TASK_ROOT,
        help=f"cc-task vault root (default: {DEFAULT_TASK_ROOT})",
    )
    parser.add_argument(
        "--requests-root",
        type=Path,
        default=DEFAULT_REQUEST_ROOT,
        help=f"request intake root (default: {DEFAULT_REQUEST_ROOT})",
    )
    parser.add_argument("--json", action="store_true", help="emit a stable JSON report")
    parser.add_argument(
        "--persist",
        action="store_true",
        help="also persist the JSON report under --state-dir",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=DEFAULT_STATE_DIR,
        help=f"state directory for --persist (default: {DEFAULT_STATE_DIR})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = audit_route_metadata_seed_candidates(
        args.task_root,
        request_root=args.requests_root,
    )
    if args.persist:
        report = _write_state_report(report, args.state_dir)

    if args.json:
        print(_json_dumps(report.to_dict()))
    else:
        _print_text_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
