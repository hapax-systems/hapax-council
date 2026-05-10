from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts/audit-route-metadata-seed-candidates.py"
)


@pytest.fixture(scope="module")
def audit_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "audit_route_metadata_seed_candidates", SCRIPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["audit_route_metadata_seed_candidates"] = module
    spec.loader.exec_module(module)
    return module


def test_derived_task_and_request_candidates_are_read_only(
    tmp_path: Path, audit_module: ModuleType
) -> None:
    task_root = tmp_path / "hapax-cc-tasks"
    request_root = tmp_path / "hapax-requests"
    _write_task(
        task_root,
        "source-task",
        kind="implementation",
        risk_tier="T1",
        authority_case="CASE-001",
        parent_spec="/tmp/spec.md",
        tags=["governance"],
    )
    _write_request(
        request_root,
        "REQ-001",
        kind="planning",
        risk_tier="T1",
        authority_case="CASE-001",
        parent_plan="/tmp/plan.md",
    )
    before = _snapshot(tmp_path)

    report = audit_module.audit_route_metadata_seed_candidates(
        task_root,
        request_root=request_root,
        generated_at=datetime(2026, 5, 9, 22, 0, tzinfo=UTC),
    )

    assert _snapshot(tmp_path) == before
    payload = report.to_dict()
    assert payload["generated_at"] == "2026-05-09T22:00:00Z"
    assert payload["counts"]["task_notes"] == 1
    assert payload["counts"]["request_notes"] == 1
    assert payload["counts"]["derived"] == 2
    assert payload["counts"]["candidates"] == 2
    assert payload["counts"]["hazards"] == 0
    assert {candidate["source_type"] for candidate in payload["candidates"]} == {
        "cc_task",
        "hapax_request",
    }
    assert all(candidate["write_allowed"] is False for candidate in payload["candidates"])
    assert payload["candidates"][0]["proposed_metadata"]["route_metadata_schema"] == 1


def test_unknown_task_remains_hold_without_title_based_deterministic_ok(
    tmp_path: Path, audit_module: ModuleType
) -> None:
    task_root = tmp_path / "hapax-cc-tasks"
    request_root = tmp_path / "hapax-requests"
    _write_task(
        task_root,
        "unknown-jr-test-title",
        title="JR deterministic mechanical test",
        kind=None,
        risk_tier=None,
        authority_case=None,
        tags=[],
    )

    report = audit_module.audit_route_metadata_seed_candidates(
        task_root,
        request_root=request_root,
        generated_at=datetime(2026, 5, 9, 22, 0, tzinfo=UTC),
    ).to_dict()

    assert report["counts"]["hold"] == 1
    assert report["counts"]["candidates"] == 0
    assert report["hazards"][0]["route_status"] == "hold"
    assert set(report["hazards"][0]["missing_fields"]) == {"quality_floor", "mutation_surface"}


def test_malformed_frontmatter_is_reported_not_skipped(
    tmp_path: Path, audit_module: ModuleType
) -> None:
    task_root = tmp_path / "hapax-cc-tasks"
    request_root = tmp_path / "hapax-requests"
    active = task_root / "active"
    active.mkdir(parents=True)
    (active / "bad.md").write_text("---\ntype: [broken\n---\n# Bad\n", encoding="utf-8")

    report = audit_module.audit_route_metadata_seed_candidates(
        task_root,
        request_root=request_root,
        generated_at=datetime(2026, 5, 9, 22, 0, tzinfo=UTC),
    ).to_dict()

    assert report["counts"]["malformed_frontmatter"] == 1
    assert report["counts"]["hazards"] == 1
    assert report["hazards"][0]["hazard"] == "frontmatter"
    assert report["hazards"][0]["write_allowed"] is False


def test_malformed_explicit_route_metadata_is_hazard(
    tmp_path: Path, audit_module: ModuleType
) -> None:
    task_root = tmp_path / "hapax-cc-tasks"
    request_root = tmp_path / "hapax-requests"
    _write_task(
        task_root,
        "bad-route",
        route_metadata_schema=1,
        quality_floor="spark_is_fine",
        authority_level="authoritative",
        mutation_surface="source",
    )

    report = audit_module.audit_route_metadata_seed_candidates(
        task_root,
        request_root=request_root,
        generated_at=datetime(2026, 5, 9, 22, 0, tzinfo=UTC),
    ).to_dict()

    assert report["counts"]["malformed_route_metadata"] == 1
    assert report["hazards"][0]["hazard"] == "route_metadata_malformed"
    assert report["hazards"][0]["validation_errors"]


def test_cli_json_report_shape_is_stable(
    tmp_path: Path, audit_module: ModuleType, capsys: Any
) -> None:
    task_root = tmp_path / "hapax-cc-tasks"
    request_root = tmp_path / "hapax-requests"
    _write_task(
        task_root,
        "source-task",
        kind="implementation",
        risk_tier="T1",
        authority_case="CASE-001",
    )

    exit_code = audit_module.main(
        ["--task-root", str(task_root), "--requests-root", str(request_root), "--json"]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {
        "candidates",
        "counts",
        "generated_at",
        "hazards",
        "report_path",
        "source_roots",
    }
    assert payload["report_path"] is None
    assert payload["candidates"][0]["write_allowed"] is False


def _write_task(root: Path, task_id: str, **overrides: Any) -> Path:
    active = root / "active"
    active.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "type": "cc-task",
        "task_id": task_id,
        "title": task_id.replace("-", " ").title(),
        "status": "offered",
        "assigned_to": "unassigned",
        "priority": "p2",
        "wsjf": 1,
        "depends_on": [],
        "blocks": [],
        "branch": None,
        "pr": None,
        "created_at": "2026-05-09T00:00:00Z",
        "updated_at": "2026-05-09T00:00:00Z",
        "claimed_at": None,
        "completed_at": None,
        "tags": [],
    }
    _apply_overrides(frontmatter, overrides)
    path = active / f"{task_id}.md"
    _write_note(path, frontmatter)
    return path


def _write_request(root: Path, request_id: str, **overrides: Any) -> Path:
    active = root / "active"
    active.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "type": "hapax-request",
        "request_id": request_id,
        "title": request_id,
        "status": "captured",
        "tags": [],
    }
    _apply_overrides(frontmatter, overrides)
    path = active / f"{request_id}.md"
    _write_note(path, frontmatter)
    return path


def _apply_overrides(frontmatter: dict[str, Any], overrides: dict[str, Any]) -> None:
    for key, value in overrides.items():
        if value is None:
            frontmatter.pop(key, None)
        else:
            frontmatter[key] = value


def _write_note(path: Path, frontmatter: dict[str, Any]) -> None:
    body = yaml.safe_dump(frontmatter, sort_keys=False)
    path.write_text(f"---\n{body}---\n\n# {path.stem}\n", encoding="utf-8")


def _snapshot(root: Path) -> dict[Path, str]:
    return {
        path.relative_to(root): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*.md"))
    }
