from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cc-claim"
SESSION_ID = "0f9f9f9f-1111-2222-3333-444455556666"
DISPATCH_ARGS = (
    "--dispatch-message-id",
    "message-a",
    "--dispatch-binding-hash",
    "a" * 64,
    "--dispatch-platform",
    "codex",
    "--dispatch-mode",
    "headless",
    "--dispatch-profile",
    "full",
    "--dispatch-authority-case",
    "CASE-TEST-001",
    "--dispatch-idempotency-key",
    "dispatch-a",
)


def _task_root(home: Path) -> Path:
    root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (root / "active").mkdir(parents=True, exist_ok=True)
    (root / "closed").mkdir(parents=True, exist_ok=True)
    return root


def _write_task(
    home: Path,
    task_id: str,
    *,
    status: str = "offered",
    assigned_to: str = "unassigned",
    authority_case: str | None = "CASE-TEST-001",
    parent_spec: str | None = "/tmp/isap-test.md",
    depends_on: tuple[str, ...] = (),
    closed: bool = False,
) -> Path:
    path = _task_root(home) / ("closed" if closed else "active") / f"{task_id}.md"
    lines = [
        "---",
        "type: cc-task",
        f"task_id: {task_id}",
        f'title: "{task_id}"',
        f"status: {status}",
        f"assigned_to: {assigned_to}",
        "claimable: true",
        "kind: build",
    ]
    if authority_case is not None:
        lines.append(f"authority_case: {authority_case}")
    if parent_spec is not None:
        lines.append(f"parent_spec: {parent_spec}")
    if depends_on:
        lines.append("depends_on:")
        lines.extend(f"  - {item}" for item in depends_on)
    else:
        lines.append("depends_on: []")
    lines.extend(
        [
            "created_at: 2026-05-09T00:00:00Z",
            "updated_at: 2026-05-09T00:00:00Z",
            "claimed_at: null",
            "---",
            "",
            f"# {task_id}",
            "",
            "## Session log",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _run(
    home: Path,
    task_id: str,
    *,
    args: tuple[str, ...] = (),
    env_update: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        HOME=str(home),
        HAPAX_AGENT_ROLE="cx-test",
        HAPAX_SESSION_ID=SESSION_ID,
    )
    env.update(env_update or {})
    return subprocess.run(
        ["bash", str(SCRIPT), task_id, *args],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_claim_refuses_when_project_runtime_is_unprovisioned(tmp_path: Path) -> None:
    isolated = tmp_path / "isolated" / "scripts" / "cc-claim"
    isolated.parent.mkdir(parents=True)
    isolated.write_bytes(SCRIPT.read_bytes())
    isolated.chmod(0o755)
    result = subprocess.run(
        ["bash", str(isolated), "missing-task"],
        env={**os.environ, "HOME": str(tmp_path / "home"), "HAPAX_AGENT_ROLE": "cx-test"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 3
    assert "project_runtime_unprovisioned" in result.stderr


def test_claim_requires_complete_dispatch_before_any_mutation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "claim-target")
    before = note.read_bytes()
    result = _run(home, "claim-target")
    assert result.returncode == 2
    assert "requires the exact dispatch binding flags" in result.stderr
    assert note.read_bytes() == before
    assert not (home / ".cache" / "hapax").exists()


@pytest.mark.parametrize("ambient", [None, "0", "false", "garbage", ""])
def test_ambient_enforcement_values_cannot_restore_raw_publication(
    tmp_path: Path,
    ambient: str | None,
) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "claim-target")
    before = _tree_snapshot(home)
    env_update = {}
    if ambient is not None:
        env_update["HAPAX_CANON_ECHO_ENFORCEMENT"] = ambient
    result = _run(home, "claim-target", args=DISPATCH_ARGS, env_update=env_update)
    assert result.returncode == 8
    assert "unadmitted_claim_publication_forbidden" in result.stderr
    assert "prepared_intent=claim-publication-intent@sha256:" in result.stderr
    assert _tree_snapshot(home) == before
    assert "status: offered" in note.read_text(encoding="utf-8")


def test_force_is_retired_without_releasing_any_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "claim-target")
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    existing = cache / "cc-active-task-cx-test"
    existing.write_text("other-task\n", encoding="utf-8")
    before = _tree_snapshot(home)
    result = _run(home, "claim-target", args=("--force", *DISPATCH_ARGS))
    assert result.returncode == 2
    assert "--force is retired" in result.stderr
    assert _tree_snapshot(home) == before
    assert note.exists()


def test_expired_claim_requires_governed_release_and_is_not_reaped(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "claim-target")
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim = cache / f"cc-active-task-cx-test-{SESSION_ID}"
    claim.write_text("other-task\n", encoding="utf-8")
    os.utime(claim, (1, 1))
    before = _tree_snapshot(home)
    result = _run(home, "claim-target", args=DISPATCH_ARGS)
    assert result.returncode == 7
    assert "requires governed release" in result.stderr
    assert _tree_snapshot(home) == before


def test_partial_dispatch_vector_refuses_without_mutation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "claim-target")
    before = _tree_snapshot(home)
    result = _run(
        home,
        "claim-target",
        args=("--dispatch-message-id", "message-a"),
    )
    assert result.returncode == 1
    assert "all-or-none" in result.stderr
    assert _tree_snapshot(home) == before


def test_unkeyable_session_refuses_before_mutation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "claim-target")
    before = _tree_snapshot(home)
    result = _run(
        home,
        "claim-target",
        args=DISPATCH_ARGS,
        env_update={"HAPAX_SESSION_ID": "cx-test-12345"},
    )
    assert result.returncode == 2
    assert "claim-keyable non-PID session id" in result.stderr
    assert _tree_snapshot(home) == before


def test_preflight_dependency_refusal_remains_non_mutating(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "unfinished", status="in_progress", assigned_to="cx-peer")
    _write_task(home, "claim-target", depends_on=("unfinished",))
    before = _tree_snapshot(home)
    result = _run(home, "claim-target", args=DISPATCH_ARGS)
    assert result.returncode == 5
    assert "unmet dependencies" in result.stderr
    assert _tree_snapshot(home) == before


def test_preflight_authority_refusal_remains_non_mutating(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "claim-target", authority_case=None)
    before = _tree_snapshot(home)
    result = _run(home, "claim-target", args=DISPATCH_ARGS)
    assert result.returncode == 6
    assert "authority_case" in result.stderr
    assert _tree_snapshot(home) == before
