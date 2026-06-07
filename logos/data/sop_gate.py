"""SOP-gate dependency projection for Logos infrastructure dashboards."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.sdlc_lifecycle import (
    TASK_FULFILLING_CLOSED_STATUSES,
    TASK_NON_FULFILLING_CLOSED_STATUSES,
    blocked_reason_from_frontmatter,
    blocked_witness_from_frontmatter,
    frontmatter_from_text,
)

CC_TASK_ROOT = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
SOP_TASK_ID = "appendix-podium-sop-baseline-proof-20260604"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SopDependency:
    task_id: str
    title: str | None
    status: str
    state: str
    stage: str | None
    assigned_to: str | None
    authority_case: str | None
    pr: str | None
    blocked_reason: str | None
    blocked_witness: str | None
    completed_at: str | None
    collection: str


@dataclass(frozen=True)
class SopGateSnapshot:
    schema_version: int
    generated_at: str
    task_id: str
    title: str | None
    status: str
    stage: str | None
    blocked_reason: str | None
    blocked_witness: str | None
    dependency_count: int
    closed_count: int
    blocked_count: int
    open_count: int
    missing_count: int
    non_fulfilling_count: int
    normal_dev_ready: bool
    dependencies: list[SopDependency] = field(default_factory=list)


@dataclass(frozen=True)
class _TaskNote:
    frontmatter: dict[str, Any]
    collection: str


def collect_sop_gate(
    *,
    root: Path | None = None,
    task_id: str = SOP_TASK_ID,
) -> SopGateSnapshot:
    """Render the SOP baseline dependency gate from cc-task frontmatter."""

    task_root = root or CC_TASK_ROOT
    index = _task_index(task_root)
    note = index.get(task_id)
    frontmatter = note.frontmatter if note is not None else {}
    dependency_ids = _string_list(frontmatter.get("depends_on"))
    dependencies = [_dependency(dep_id, index.get(dep_id)) for dep_id in dependency_ids]
    closed_count = sum(dep.state == "closed" for dep in dependencies)
    blocked_count = sum(dep.state == "blocked" for dep in dependencies)
    open_count = sum(dep.state == "open" for dep in dependencies)
    missing_count = sum(dep.state == "missing" for dep in dependencies)
    non_fulfilling_count = sum(dep.state == "non_fulfilling" for dep in dependencies)

    return SopGateSnapshot(
        schema_version=SCHEMA_VERSION,
        generated_at=_now_iso(),
        task_id=task_id,
        title=_optional_string(frontmatter.get("title")),
        status=str(frontmatter.get("status") or "missing"),
        stage=_optional_string(frontmatter.get("stage")),
        blocked_reason=blocked_reason_from_frontmatter(frontmatter),
        blocked_witness=blocked_witness_from_frontmatter(frontmatter),
        dependency_count=len(dependency_ids),
        closed_count=closed_count,
        blocked_count=blocked_count,
        open_count=open_count,
        missing_count=missing_count,
        non_fulfilling_count=non_fulfilling_count,
        normal_dev_ready=bool(dependency_ids)
        and closed_count == len(dependency_ids)
        and blocked_count == 0
        and open_count == 0
        and missing_count == 0
        and non_fulfilling_count == 0,
        dependencies=dependencies,
    )


def _task_index(root: Path) -> dict[str, _TaskNote]:
    notes: dict[str, _TaskNote] = {}
    for collection in ("closed", "active"):
        for path in sorted((root / collection).glob("*.md")):
            frontmatter = _read_frontmatter(path)
            if not frontmatter:
                continue
            task_id = _optional_string(frontmatter.get("task_id")) or path.stem
            notes[task_id] = _TaskNote(frontmatter=frontmatter, collection=collection)
    return notes


def _read_frontmatter(path: Path) -> dict[str, Any]:
    try:
        return frontmatter_from_text(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


def _dependency(task_id: str, note: _TaskNote | None) -> SopDependency:
    if note is None:
        return SopDependency(
            task_id=task_id,
            title=None,
            status="missing",
            state="missing",
            stage=None,
            assigned_to=None,
            authority_case=None,
            pr=None,
            blocked_reason=None,
            blocked_witness=None,
            completed_at=None,
            collection="missing",
        )

    frontmatter = note.frontmatter
    status = str(frontmatter.get("status") or "unknown")
    return SopDependency(
        task_id=task_id,
        title=_optional_string(frontmatter.get("title")),
        status=status,
        state=_dependency_state(status, note.collection),
        stage=_optional_string(frontmatter.get("stage")),
        assigned_to=_optional_string(frontmatter.get("assigned_to")),
        authority_case=_optional_string(frontmatter.get("authority_case")),
        pr=_optional_string(frontmatter.get("pr")),
        blocked_reason=blocked_reason_from_frontmatter(frontmatter),
        blocked_witness=blocked_witness_from_frontmatter(frontmatter),
        completed_at=_optional_string(frontmatter.get("completed_at")),
        collection=note.collection,
    )


def _dependency_state(status: str, collection: str) -> str:
    normalized = status.lower().strip()
    if normalized in TASK_FULFILLING_CLOSED_STATUSES:
        return "closed"
    if normalized in TASK_NON_FULFILLING_CLOSED_STATUSES:
        return "non_fulfilling"
    if collection == "closed":
        return "closed"
    if normalized == "blocked":
        return "blocked"
    return "open"


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "~"}:
        return None
    return text


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "SopDependency",
    "SopGateSnapshot",
    "collect_sop_gate",
]
