#!/usr/bin/env python3
"""Read-only smoke check for the real cc-task vault shape."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.frontmatter import parse_frontmatter_with_diagnostics
from shared.route_metadata_schema import RouteMetadataStatus, assess_route_metadata

DEFAULT_VAULT_ROOT = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks"
DEFAULT_REQUESTS_ROOT = Path.home() / "Documents/Personal/20-projects/hapax-requests"

TASK_DIRS = ("active", "closed", "refused")

LIVE_TASK_FIELDS = (
    "type",
    "task_id",
    "title",
    "status",
    "assigned_to",
    "priority",
    "wsjf",
    "depends_on",
    "blocks",
    "branch",
    "pr",
    "created_at",
    "updated_at",
    "claimed_at",
    "completed_at",
    "tags",
)

REFUSED_TASK_FIELDS = LIVE_TASK_FIELDS + ("automation_status",)

ARCHIVED_TASK_FIELDS = (
    "task_id",
    "title",
    "status",
    "priority",
)

REQUIRED_TASK_FIELDS_BY_DIR = {
    "active": LIVE_TASK_FIELDS,
    "closed": ARCHIVED_TASK_FIELDS,
    "refused": REFUSED_TASK_FIELDS,
}

ACTIVE_STATUSES = {"offered", "claimed", "in_progress", "blocked", "pr_open"}
CLOSED_STATUSES = {"closed", "completed", "done", "superseded", "withdrawn"}
REFUSED_STATUSES = {"refused"}
TERMINAL_STATUSES = CLOSED_STATUSES | REFUSED_STATUSES

REQUIRED_DASHBOARDS = {
    "cc-active.md": (
        "dataview",
        'status = "in_progress"',
        "HYGIENE-AUTO-START",
        "HYGIENE-AUTO-END",
    ),
    "cc-blocked.md": ("dataview", 'status = "blocked"'),
    "cc-offered.md": ("dataview", 'status = "offered"'),
    "cc-readme.md": ("cc-task",),
    "cc-recent-closed.md": ("dataview", 'status = "done"'),
    "codex-session-health.md": ("type: codex-session-health",),
}


@dataclass(frozen=True)
class Finding:
    severity: Literal["error", "warning"]
    path: str
    check: str
    message: str


@dataclass(frozen=True)
class SmokeResult:
    ok: bool
    checked_files: int
    findings: list[Finding]


def check_vault_shape(
    vault_root: Path = DEFAULT_VAULT_ROOT,
    *,
    requests_root: Path | None = None,
    strict: bool = False,
) -> SmokeResult:
    """Validate task and dashboard shapes without mutating the vault."""
    root = vault_root.expanduser()
    request_root = _resolve_requests_root(root, requests_root)
    findings: list[Finding] = []
    seen_task_ids: dict[str, Path] = {}
    checked_files = 0

    if not root.is_dir():
        findings.append(
            Finding(
                severity="error",
                path=str(root),
                check="vault_root",
                message="vault root does not exist or is not a directory",
            )
        )
        return SmokeResult(ok=False, checked_files=0, findings=findings)

    for task_dir in TASK_DIRS:
        task_dir_path = root / task_dir
        if not task_dir_path.is_dir():
            findings.append(
                Finding(
                    severity="error",
                    path=_display_path(task_dir_path, root),
                    check="required_directory",
                    message="required task directory is missing",
                )
            )
            continue

        for note_path in sorted(task_dir_path.glob("*.md")):
            checked_files += 1
            frontmatter = _read_frontmatter(note_path, root, findings)
            if frontmatter is None:
                continue
            _check_task_note(root, note_path, task_dir, frontmatter, findings, seen_task_ids)

    checked_files += _check_active_requests(request_root, findings)
    checked_files += _check_dashboards(root, findings)
    ok = not any(
        finding.severity == "error" or (strict and finding.severity == "warning")
        for finding in findings
    )
    return SmokeResult(ok=ok, checked_files=checked_files, findings=findings)


def _check_task_note(
    root: Path,
    note_path: Path,
    task_dir: str,
    frontmatter: dict[str, Any],
    findings: list[Finding],
    seen_task_ids: dict[str, Path],
) -> None:
    display_path = _display_path(note_path, root)
    required_fields = REQUIRED_TASK_FIELDS_BY_DIR[task_dir]
    missing_fields = [field for field in required_fields if field not in frontmatter]
    for field in missing_fields:
        findings.append(
            Finding(
                severity="error",
                path=display_path,
                check="required_frontmatter",
                message=f"missing required frontmatter field: {field}",
            )
        )

    note_type = frontmatter.get("type")
    if task_dir in {"active", "refused"} and note_type != "cc-task":
        findings.append(
            Finding(
                severity="error",
                path=display_path,
                check="task_type",
                message="task frontmatter type must be cc-task",
            )
        )
    elif task_dir == "closed" and note_type not in (None, "cc-task"):
        findings.append(
            Finding(
                severity="error",
                path=display_path,
                check="task_type",
                message="closed task frontmatter type must be cc-task when present",
            )
        )

    task_id = _normalized_string(frontmatter.get("task_id"))
    if not task_id:
        findings.append(
            Finding(
                severity="error",
                path=display_path,
                check="task_id",
                message="task_id must be present and non-empty",
            )
        )
    elif previous_path := seen_task_ids.get(task_id):
        findings.append(
            Finding(
                severity="error",
                path=display_path,
                check="duplicate_task_id",
                message=f"duplicate task_id {task_id!r}; first seen at {_display_path(previous_path, root)}",
            )
        )
    else:
        seen_task_ids[task_id] = note_path

    _check_status_path_consistency(root, note_path, task_dir, frontmatter, findings)
    _check_collection_fields(root, note_path, frontmatter, findings)
    _check_route_metadata(
        root,
        note_path,
        frontmatter,
        findings,
        audit_missing=task_dir == "active",
    )


def _check_status_path_consistency(
    root: Path,
    note_path: Path,
    task_dir: str,
    frontmatter: dict[str, Any],
    findings: list[Finding],
) -> None:
    display_path = _display_path(note_path, root)
    status = _normalized_string(frontmatter.get("status"))

    if task_dir == "active":
        if status in TERMINAL_STATUSES:
            findings.append(
                Finding(
                    severity="warning",
                    path=display_path,
                    check="status_path_consistency",
                    message="active task has a terminal status and should be moved or reconciled",
                )
            )
            return
        if status not in ACTIVE_STATUSES:
            findings.append(
                Finding(
                    severity="error",
                    path=display_path,
                    check="status_path_consistency",
                    message=f"active task status must be one of {sorted(ACTIVE_STATUSES)}",
                )
            )
            return
        _check_active_status_fields(root, note_path, frontmatter, findings)
        return

    if task_dir == "closed":
        if status not in CLOSED_STATUSES:
            findings.append(
                Finding(
                    severity="error",
                    path=display_path,
                    check="status_path_consistency",
                    message=f"closed task status must be one of {sorted(CLOSED_STATUSES)}",
                )
            )
        return

    if task_dir == "refused":
        if status not in REFUSED_STATUSES:
            findings.append(
                Finding(
                    severity="error",
                    path=display_path,
                    check="status_path_consistency",
                    message="refused task status must be refused",
                )
            )
        automation_status = _normalized_string(frontmatter.get("automation_status"))
        if automation_status and automation_status != "REFUSED":
            findings.append(
                Finding(
                    severity="error",
                    path=display_path,
                    check="refused_automation_status",
                    message="refused task automation_status must be REFUSED when present",
                )
            )


def _check_active_status_fields(
    root: Path,
    note_path: Path,
    frontmatter: dict[str, Any],
    findings: list[Finding],
) -> None:
    display_path = _display_path(note_path, root)
    status = _normalized_string(frontmatter.get("status"))
    assigned_to = _normalized_string(frontmatter.get("assigned_to"))
    claimed_at = frontmatter.get("claimed_at")
    pr = _normalized_string(frontmatter.get("pr"))

    if status == "offered":
        if assigned_to and assigned_to != "unassigned":
            findings.append(
                Finding(
                    severity="error",
                    path=display_path,
                    check="offered_assignment",
                    message="offered tasks must be assigned_to: unassigned or null",
                )
            )
        if claimed_at not in (None, ""):
            findings.append(
                Finding(
                    severity="error",
                    path=display_path,
                    check="offered_claimed_at",
                    message="offered tasks must not have claimed_at set",
                )
            )

    if status in {"claimed", "in_progress", "pr_open"} and (
        not assigned_to or assigned_to == "unassigned"
    ):
        findings.append(
            Finding(
                severity="error",
                path=display_path,
                check="active_assignment",
                message=f"{status} tasks must have a concrete assignee",
            )
        )

    if status == "pr_open" and not pr:
        findings.append(
            Finding(
                severity="error",
                path=display_path,
                check="pr_open_pr",
                message="pr_open tasks must include a pr field value",
            )
        )


def _check_collection_fields(
    root: Path,
    note_path: Path,
    frontmatter: dict[str, Any],
    findings: list[Finding],
) -> None:
    display_path = _display_path(note_path, root)
    for field in ("depends_on", "blocks", "tags"):
        if (
            field in frontmatter
            and frontmatter[field] is not None
            and not isinstance(frontmatter[field], list)
        ):
            findings.append(
                Finding(
                    severity="error",
                    path=display_path,
                    check="collection_frontmatter",
                    message=f"{field} must be a YAML list when present",
                )
            )


def _check_route_metadata(
    root: Path,
    note_path: Path,
    frontmatter: dict[str, Any],
    findings: list[Finding],
    *,
    audit_missing: bool,
) -> None:
    display_path = _display_path(note_path, root)
    assessment = assess_route_metadata(frontmatter)

    if assessment.status == RouteMetadataStatus.EXPLICIT:
        return

    if assessment.status == RouteMetadataStatus.MALFORMED:
        errors = "; ".join(assessment.validation_errors) or "invalid route metadata"
        findings.append(
            Finding(
                severity="error",
                path=display_path,
                check="route_metadata_malformed",
                message=errors,
            )
        )
        return

    if not audit_missing:
        return

    if assessment.status == RouteMetadataStatus.DERIVED:
        metadata = assessment.metadata
        suffix = ""
        if metadata is not None:
            suffix = (
                f": quality_floor={metadata.quality_floor}, "
                f"mutation_surface={metadata.mutation_surface}"
            )
        findings.append(
            Finding(
                severity="warning",
                path=display_path,
                check="route_metadata_derived",
                message=f"route metadata was conservatively derived from existing fields{suffix}",
            )
        )
        return

    if assessment.status == RouteMetadataStatus.HOLD:
        reasons = ", ".join(assessment.hold_reasons) or "missing route metadata"
        findings.append(
            Finding(
                severity="warning",
                path=display_path,
                check="route_metadata_hold",
                message=f"route metadata hold: {reasons}",
            )
        )
        return


def _check_active_requests(requests_root: Path | None, findings: list[Finding]) -> int:
    if requests_root is None:
        return 0
    root = requests_root.expanduser()
    active_dir = root / "active"
    if not active_dir.is_dir():
        return 0

    checked_files = 0
    for request_path in sorted(active_dir.glob("*.md")):
        checked_files += 1
        frontmatter = _read_frontmatter(request_path, root, findings, note_label="request")
        if frontmatter is None:
            continue
        if frontmatter.get("type") != "hapax-request":
            continue
        status = _normalized_string(frontmatter.get("status"))
        _check_route_metadata(
            root,
            request_path,
            frontmatter,
            findings,
            audit_missing=status not in {"fulfilled", "rejected", "superseded"},
        )
    return checked_files


def _check_dashboards(root: Path, findings: list[Finding]) -> int:
    dashboard_dir = root / "_dashboard"
    if not dashboard_dir.is_dir():
        findings.append(
            Finding(
                severity="error",
                path=_display_path(dashboard_dir, root),
                check="required_directory",
                message="required dashboard directory is missing",
            )
        )
        return 0

    checked_files = 0
    for file_name, required_substrings in REQUIRED_DASHBOARDS.items():
        dashboard_path = dashboard_dir / file_name
        display_path = _display_path(dashboard_path, root)
        if not dashboard_path.is_file():
            findings.append(
                Finding(
                    severity="error",
                    path=display_path,
                    check="required_dashboard",
                    message="required dashboard note is missing",
                )
            )
            continue

        checked_files += 1
        try:
            text = dashboard_path.read_text(encoding="utf-8")
        except OSError as exc:
            findings.append(
                Finding(
                    severity="error",
                    path=display_path,
                    check="dashboard_read",
                    message=f"dashboard note could not be read: {exc}",
                )
            )
            continue

        for required_substring in required_substrings:
            if required_substring not in text:
                findings.append(
                    Finding(
                        severity="error",
                        path=display_path,
                        check="dashboard_shape",
                        message=f"missing expected dashboard marker: {required_substring}",
                    )
                )

    return checked_files


def _read_frontmatter(
    note_path: Path,
    root: Path,
    findings: list[Finding],
    *,
    note_label: str = "task",
) -> dict[str, Any] | None:
    display_path = _display_path(note_path, root)
    result = parse_frontmatter_with_diagnostics(note_path)

    if result.ok:
        return result.frontmatter

    if result.error_kind == "read_error":
        findings.append(
            Finding(
                severity="error",
                path=display_path,
                check=f"{note_label}_read",
                message=f"{note_label} note could not be read: {result.error_message}",
            )
        )
        return None

    if result.error_kind in {"missing_frontmatter", "missing_closing_marker"}:
        findings.append(
            Finding(
                severity="error",
                path=display_path,
                check="frontmatter",
                message=f"{note_label} note {result.error_message}",
            )
        )
        return None

    findings.append(
        Finding(
            severity="error",
            path=display_path,
            check="frontmatter_yaml",
            message=f"{note_label} frontmatter is invalid: {result.error_message}",
        )
    )
    return None


def _resolve_requests_root(vault_root: Path, requests_root: Path | None) -> Path | None:
    if requests_root is not None:
        return requests_root.expanduser()
    if vault_root == DEFAULT_VAULT_ROOT.expanduser():
        return DEFAULT_REQUESTS_ROOT
    sibling = vault_root.parent / "hapax-requests"
    return sibling if sibling.exists() else None


def _normalized_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _result_to_dict(result: SmokeResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "checked_files": result.checked_files,
        "findings": [asdict(finding) for finding in result.findings],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate cc-task vault shape without writing to the vault."
    )
    parser.add_argument(
        "--vault-root",
        type=Path,
        default=DEFAULT_VAULT_ROOT,
        help=f"cc-task vault root (default: {DEFAULT_VAULT_ROOT})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON diagnostics",
    )
    parser.add_argument(
        "--requests-root",
        type=Path,
        default=None,
        help="request intake root to include in route metadata audit",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail on warnings as well as errors",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = check_vault_shape(
        args.vault_root, requests_root=args.requests_root, strict=args.strict
    )

    if args.json:
        print(json.dumps(_result_to_dict(result), indent=2, sort_keys=True))
    else:
        warnings = [finding for finding in result.findings if finding.severity == "warning"]
        status = "ok" if result.ok else "failed"
        if result.ok and warnings:
            status = "ok with warnings"
        print(f"cc-task vault shape smoke {status}: checked {result.checked_files} files")
        for finding in result.findings:
            print(f"{finding.severity.upper()} {finding.path}: {finding.check}: {finding.message}")

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
