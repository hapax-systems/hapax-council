from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from logos.data.sop_gate import collect_sop_gate


@pytest.fixture
async def client():
    from logos.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _write_task(
    root: Path,
    collection: str,
    task_id: str,
    *,
    status: str,
    title: str = "Task",
    depends_on: list[str] | None = None,
    extra: str = "",
) -> None:
    dep_lines = "depends_on: []"
    if depends_on:
        dep_lines = "depends_on:\n" + "\n".join(f"  - {dep}" for dep in depends_on)
    body = f"""---
type: cc-task
task_id: {task_id}
title: {title}
status: {status}
stage: S6_IMPLEMENTATION
assigned_to: cx-cyan
authority_case: CASE-SDLC-REFORM-001
pr: null
completed_at: null
{dep_lines}
{extra}
---

# {title}
"""
    (root / collection / f"{task_id}.md").write_text(body, encoding="utf-8")


def _task_root(tmp_path: Path) -> Path:
    root = tmp_path / "hapax-cc-tasks"
    (root / "active").mkdir(parents=True)
    (root / "closed").mkdir(parents=True)
    return root


def test_collect_sop_gate_classifies_all_dependency_states(tmp_path):
    root = _task_root(tmp_path)
    _write_task(
        root,
        "active",
        "appendix-podium-sop-baseline-proof-20260604",
        status="blocked",
        title="SOP baseline proof",
        depends_on=["dep-closed", "dep-blocked", "dep-open", "dep-missing", "dep-withdrawn"],
        extra='blocked_reason: "waiting_for_closure_valid_dependencies: dep-open"\n',
    )
    _write_task(
        root,
        "closed",
        "dep-closed",
        status="done",
        title="Closed dependency",
        extra="completed_at: 2026-06-06T12:00:00Z\n",
    )
    _write_task(
        root,
        "active",
        "dep-blocked",
        status="blocked",
        title="Blocked dependency",
        extra=(
            "blocked_reason: waiting_for_storage_identity\n"
            "blocked_witness: vault:host-storage-rollup\n"
        ),
    )
    _write_task(root, "active", "dep-open", status="pr_open", title="Open dependency")
    _write_task(root, "closed", "dep-withdrawn", status="withdrawn", title="Withdrawn")

    snapshot = collect_sop_gate(root=root)

    assert snapshot.dependency_count == 5
    assert snapshot.closed_count == 1
    assert snapshot.blocked_count == 1
    assert snapshot.open_count == 1
    assert snapshot.missing_count == 1
    assert snapshot.non_fulfilling_count == 1
    assert snapshot.normal_dev_ready is False
    assert [dep.task_id for dep in snapshot.dependencies] == [
        "dep-closed",
        "dep-blocked",
        "dep-open",
        "dep-missing",
        "dep-withdrawn",
    ]
    assert [dep.state for dep in snapshot.dependencies] == [
        "closed",
        "blocked",
        "open",
        "missing",
        "non_fulfilling",
    ]
    blocked = snapshot.dependencies[1]
    assert blocked.blocked_reason == "waiting_for_storage_identity"
    assert blocked.blocked_witness == "vault:host-storage-rollup"


async def test_sop_gate_route_redacts_host_terms_in_public_mode(client, tmp_path, monkeypatch):
    root = _task_root(tmp_path)
    _write_task(
        root,
        "active",
        "appendix-podium-sop-baseline-proof-20260604",
        status="blocked",
        title="appendix podium SOP baseline proof",
        depends_on=["appendix-proof"],
    )
    _write_task(root, "active", "appendix-proof", status="claimed", title="appendix proof")
    monkeypatch.setattr("logos.data.sop_gate.CC_TASK_ROOT", root)
    monkeypatch.setattr("logos.api.routes.data.is_publicly_visible", lambda: True)

    resp = await client.get("/api/infrastructure/sop-gate")

    assert resp.status_code == 200
    body = json.dumps(resp.json())
    assert "appendix" not in body
    assert "podium" not in body
    assert "[redacted-host]" in body
