from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts/check-cc-task-vault-shape.py"


@pytest.fixture(scope="module")
def vault_shape_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_cc_task_vault_shape", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_cc_task_vault_shape"] = module
    spec.loader.exec_module(module)
    return module


def test_valid_vault_shape_passes(tmp_path: Path, vault_shape_module: ModuleType) -> None:
    root = _write_valid_vault(tmp_path)

    result = vault_shape_module.check_vault_shape(root)

    assert result.ok is True
    assert result.findings == []


def test_duplicate_task_ids_fail(tmp_path: Path, vault_shape_module: ModuleType) -> None:
    root = _write_valid_vault(tmp_path)
    _write_task(root, "closed", "active-task", status="done", completed_at="2026-05-01T01:00:00Z")

    result = vault_shape_module.check_vault_shape(root)

    assert result.ok is False
    assert _checks(result) == {"duplicate_task_id"}


def test_missing_required_frontmatter_field_fails(
    tmp_path: Path,
    vault_shape_module: ModuleType,
) -> None:
    root = _write_valid_vault(tmp_path)
    _write_task(
        root,
        "active",
        "missing-priority",
        status="offered",
        assigned_to="unassigned",
        claimed_at=None,
        omit_fields=("priority",),
    )

    result = vault_shape_module.check_vault_shape(root)

    assert result.ok is False
    assert "required_frontmatter" in _checks(result)


def test_active_terminal_status_warns_by_default(
    tmp_path: Path,
    vault_shape_module: ModuleType,
) -> None:
    root = _write_valid_vault(tmp_path)
    _write_task(root, "active", "terminal-in-active", status="done")

    result = vault_shape_module.check_vault_shape(root)

    assert result.ok is True
    assert "status_path_consistency" in _checks(result, severity="warning")


def test_strict_mode_fails_on_warnings(tmp_path: Path, vault_shape_module: ModuleType) -> None:
    root = _write_valid_vault(tmp_path)
    _write_task(root, "active", "terminal-in-active", status="done")

    result = vault_shape_module.check_vault_shape(root, strict=True)

    assert result.ok is False
    assert "status_path_consistency" in _checks(result, severity="warning")


def test_refused_status_shape_fails(tmp_path: Path, vault_shape_module: ModuleType) -> None:
    root = _write_valid_vault(tmp_path)
    _write_task(root, "refused", "bad-refusal", status="refused", automation_status="DONE")

    result = vault_shape_module.check_vault_shape(root)

    assert result.ok is False
    assert "refused_automation_status" in _checks(result)


def test_missing_dashboard_marker_fails(tmp_path: Path, vault_shape_module: ModuleType) -> None:
    root = _write_valid_vault(tmp_path)
    (root / "_dashboard/cc-offered.md").write_text("# Offered\n", encoding="utf-8")

    result = vault_shape_module.check_vault_shape(root)

    assert result.ok is False
    assert "dashboard_shape" in _checks(result)


def test_check_is_read_only(tmp_path: Path, vault_shape_module: ModuleType) -> None:
    root = _write_valid_vault(tmp_path)
    before = _snapshot(root)

    result = vault_shape_module.check_vault_shape(root)

    assert result.ok is True
    assert _snapshot(root) == before


def test_route_metadata_missing_quality_floor_warns_without_writing(
    tmp_path: Path, vault_shape_module: ModuleType
) -> None:
    root = _write_valid_vault(tmp_path)
    _write_task(
        root,
        "active",
        "missing-route-metadata",
        status="offered",
        assigned_to="unassigned",
        claimed_at=None,
        route_metadata=False,
    )
    before = _snapshot(root)

    result = vault_shape_module.check_vault_shape(root)

    assert result.ok is True
    assert "route_metadata_hold" in _checks(result, severity="warning")
    assert _snapshot(root) == before


def test_malformed_route_metadata_fails(tmp_path: Path, vault_shape_module: ModuleType) -> None:
    root = _write_valid_vault(tmp_path)
    _write_task(
        root,
        "active",
        "bad-route-metadata",
        route_metadata={
            "quality_floor": "frontier_review_required",
            "authority_level": "authoritative",
            "mutation_surface": "vault_docs",
        },
    )

    result = vault_shape_module.check_vault_shape(root)

    assert result.ok is False
    assert "route_metadata_malformed" in _checks(result)


def test_request_route_metadata_audit_is_read_only(
    tmp_path: Path, vault_shape_module: ModuleType
) -> None:
    root = _write_valid_vault(tmp_path / "hapax-cc-tasks")
    requests_root = tmp_path / "hapax-requests"
    (requests_root / "active").mkdir(parents=True)
    request_path = requests_root / "active" / "REQ-001.md"
    request_path.write_text(
        "\n".join(
            [
                "---",
                "type: hapax-request",
                "request_id: REQ-001",
                "title: Needs route metadata",
                "status: captured",
                "---",
                "",
            ]
        ),
        encoding="utf-8",
    )
    before = _snapshot(requests_root)

    result = vault_shape_module.check_vault_shape(root, requests_root=requests_root)

    assert result.ok is True
    assert "route_metadata_hold" in _checks(result, severity="warning")
    assert _snapshot(requests_root) == before


def test_cli_json_reports_failures(
    tmp_path: Path, vault_shape_module: ModuleType, capsys: Any
) -> None:
    root = _write_valid_vault(tmp_path)
    _write_task(root, "closed", "offered-in-closed", status="offered")

    exit_code = vault_shape_module.main(["--vault-root", str(root), "--json"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert '"ok": false' in captured.out
    assert "status_path_consistency" in captured.out


def _write_valid_vault(root: Path) -> Path:
    for directory in ("active", "closed", "refused", "_dashboard"):
        (root / directory).mkdir(parents=True)

    _write_task(root, "active", "active-task", status="in_progress", assigned_to="cx-gold")
    _write_task(
        root,
        "active",
        "offered-task",
        status="offered",
        assigned_to="unassigned",
        claimed_at=None,
    )
    _write_task(root, "closed", "closed-task", status="done", completed_at="2026-05-01T01:00:00Z")
    _write_task(
        root,
        "refused",
        "refused-task",
        status="refused",
        automation_status="REFUSED",
    )
    _write_dashboards(root)
    return root


def _write_task(root: Path, directory: str, task_id: str, **overrides: Any) -> None:
    omit_fields = set(overrides.pop("omit_fields", ()))
    route_metadata = overrides.pop("route_metadata", True)
    frontmatter = {
        "type": "cc-task",
        "task_id": task_id,
        "title": task_id.replace("-", " ").title(),
        "status": overrides.pop("status", "in_progress"),
        "assigned_to": overrides.pop("assigned_to", "cx-gold"),
        "priority": overrides.pop("priority", "p3"),
        "wsjf": overrides.pop("wsjf", 1),
        "depends_on": overrides.pop("depends_on", []),
        "blocks": overrides.pop("blocks", []),
        "branch": overrides.pop("branch", f"codex/{task_id}"),
        "pr": overrides.pop("pr", None),
        "created_at": overrides.pop("created_at", "2026-05-01T00:00:00Z"),
        "updated_at": overrides.pop("updated_at", "2026-05-01T00:00:00Z"),
        "claimed_at": overrides.pop("claimed_at", "2026-05-01T00:00:00Z"),
        "completed_at": overrides.pop("completed_at", None),
        "tags": overrides.pop("tags", ["coordination"]),
        **overrides,
    }
    if route_metadata:
        metadata = {
            "route_metadata_schema": 1,
            "quality_floor": "deterministic_ok",
            "authority_level": "authoritative",
            "mutation_surface": "source",
            "mutation_scope_refs": ["test:isap"],
        }
        if isinstance(route_metadata, dict):
            metadata.update(route_metadata)
        frontmatter.update(metadata)
    for field in omit_fields:
        frontmatter.pop(field, None)
    body = yaml.safe_dump(frontmatter, sort_keys=False)
    (root / directory / f"{task_id}.md").write_text(
        f"---\n{body}---\n\n# {task_id}\n", encoding="utf-8"
    )


def _write_dashboards(root: Path) -> None:
    dashboards = {
        "cc-active.md": '# Active\n```dataview\nstatus = "in_progress"\n```\n<!-- HYGIENE-AUTO-START -->\n<!-- HYGIENE-AUTO-END -->\n',
        "cc-blocked.md": '# Blocked\n```dataview\nstatus = "blocked"\n```\n',
        "cc-offered.md": '# Offered\n```dataview\nstatus = "offered"\n```\n',
        "cc-readme.md": "# README\ncc-task\n",
        "cc-recent-closed.md": '# Closed\n```dataview\nstatus = "done"\n```\n',
        "codex-session-health.md": "---\ntype: codex-session-health\n---\n# Health\n",
    }
    for file_name, text in dashboards.items():
        (root / "_dashboard" / file_name).write_text(text, encoding="utf-8")


def _checks(result: Any, *, severity: str = "error") -> set[str]:
    return {finding.check for finding in result.findings if finding.severity == severity}


def _snapshot(root: Path) -> dict[Path, str]:
    return {
        path.relative_to(root): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*.md"))
    }
