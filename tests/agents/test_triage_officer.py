from __future__ import annotations

import json
from pathlib import Path

import yaml

from agents.triage_officer.core import (
    TaskTriageAnnotation,
    apply_annotation,
    iter_candidates,
    run_triage_pass,
)
from shared.frontmatter import parse_frontmatter
from shared.route_metadata_schema import RouteMetadataStatus, assess_route_metadata


def test_iter_candidates_targets_deterministic_fallback_not_operator_override(
    tmp_path: Path,
) -> None:
    root = tmp_path / "tasks"
    _write_task(root, "fallback", annotation_source="deterministic_fallback")
    _write_task(root, "operator", annotation_source="operator_override")
    _write_task(root, "missing", annotation_source=None)

    candidates = iter_candidates(task_root=root)

    assert [candidate.task_id for candidate in candidates] == ["fallback"]


def test_apply_annotation_writes_frontier_provenance_and_route_metadata(tmp_path: Path) -> None:
    root = tmp_path / "tasks"
    path = _write_task(root, "fallback", annotation_source="deterministic_fallback")

    apply_annotation(path, _annotation(), model_name="balanced")

    frontmatter, _body = parse_frontmatter(path)
    assert frontmatter["annotation_source"] == "frontier_triage"
    assert frontmatter["annotation_model"] == "balanced"
    assert frontmatter["quality_floor"] == "frontier_required"
    assert frontmatter["mutation_surface"] == "source"
    assert frontmatter["platform_suitability"] == ["codex", "claude"]
    assert frontmatter["branch"] is None
    assert frontmatter["pr"] is None
    assert frontmatter["claimed_at"] is None
    assert frontmatter["completed_at"] is None
    assessment = assess_route_metadata(frontmatter)
    assert assessment.status == RouteMetadataStatus.EXPLICIT
    assert assessment.metadata is not None


def test_run_triage_pass_updates_bounded_candidates_and_writes_state(tmp_path: Path) -> None:
    root = tmp_path / "tasks"
    state = tmp_path / "state" / "officer-state.json"
    _write_task(root, "one", annotation_source="deterministic_fallback")
    _write_task(root, "two", annotation_source="deterministic_fallback")

    run = run_triage_pass(
        task_root=root,
        state_path=state,
        model_name="balanced",
        write=True,
        limit=1,
        agent_factory=lambda _model: _FakeAgent(),
    )

    assert run.updated == 1
    assert run.candidates == 2
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["updated"] == 1
    first, _body = parse_frontmatter(root / "active" / "one.md")
    second, _body = parse_frontmatter(root / "active" / "two.md")
    assert first["annotation_source"] == "frontier_triage"
    assert second["annotation_source"] == "deterministic_fallback"


class _RunResult:
    output = None

    def __init__(self, annotation: TaskTriageAnnotation) -> None:
        self.output = annotation


class _FakeAgent:
    def run_sync(self, prompt: str) -> _RunResult:
        assert "Hapax frontier triage officer" in prompt
        return _RunResult(_annotation())


def _annotation() -> TaskTriageAnnotation:
    return TaskTriageAnnotation(
        quality_floor="frontier_required",
        mutation_surface="source",
        authority_level="authoritative",
        effort_class="high",
        platform_suitability=["codex", "claude"],
        annotation_confidence=0.91,
        reasoning="Source mutation with routing impact needs frontier-grade annotation.",
    )


def _write_task(root: Path, task_id: str, *, annotation_source: str | None) -> Path:
    active = root / "active"
    active.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "type": "cc-task",
        "task_id": task_id,
        "title": task_id.title(),
        "status": "offered",
        "assigned_to": "unassigned",
        "wsjf": 1.0,
        "quality_floor": "deterministic_ok",
        "mutation_surface": "none",
        "authority_level": "support_non_authoritative",
        "effort_class": "standard",
        "platform_suitability": ["any"],
    }
    if annotation_source is not None:
        frontmatter["annotation_source"] = annotation_source
        frontmatter["annotation_model"] = "deterministic"
    path = active / f"{task_id}.md"
    path.write_text(
        f"---\n{yaml.safe_dump(frontmatter, sort_keys=False)}---\n\nBody.\n",
        encoding="utf-8",
    )
    return path
