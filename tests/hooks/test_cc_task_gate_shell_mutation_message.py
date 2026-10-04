"""Defect 6 (amended) of vault-nfs-mount-boot-race-and-gate-fail-closed-20261003.

Shell source mutations (mv/cp/rm/mkdir/...) are refused BY DESIGN, without a scope
check — the gate does not extract target paths from command text, because that would
classify by spelling and treat free variables (~, $VAR, globs) as identifying, which
the 2026-09-20 operator ruling forbids. The fix is NOT to allow in-scope shell
mutations; it is to make the refusal MESSAGE actionable:

  - name the working path for file CONTENT (the Write/Edit tool, which IS scope-checked),
  - for rename/move/delete, say the gate cannot verify them and the act goes to the
    seat or to a row that authorizes it,
  - and NEVER suggest an alternative command spelling (e.g. an absolute path).

Self-contained per project conventions (no shared conftest).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_SRC = REPO_ROOT / "hooks" / "scripts"
_CLOSURE = (
    "cc-task-gate.impl.sh",
    "agent-role.sh",
    "escape-grant.sh",
    "cc-task-gate-bootstrap.py",
)
_IDENTITY_ENV = (
    "HAPAX_AGENT_ROLE",
    "HAPAX_AGENT_NAME",
    "HAPAX_WORKTREE_ROLE",
    "HAPAX_AGENT_SLOT",
    "HAPAX_SESSION_ID",
    "HAPAX_AGENT_INTERFACE",
    "CLAUDE_ROLE",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_ROLE",
    "CODEX_SESSION",
    "CODEX_SESSION_NAME",
    "CODEX_THREAD_ID",
    "CODEX_THREAD_NAME",
    "HAPAX_CC_TASK_GATE_OFF",
    "HAPAX_METHODOLOGY_EMERGENCY",
)


def _stage_gate(tmp_path: Path) -> Path:
    gate_dir = tmp_path / "gate"
    gate_dir.mkdir(parents=True, exist_ok=True)
    for name in _CLOSURE:
        shutil.copy2(HOOKS_SRC / name, gate_dir / name)
        (gate_dir / name).chmod(0o755)
    return gate_dir / "cc-task-gate.impl.sh"


def _run(
    gate_impl: Path, payload: dict, tmp_path: Path, *, role: str
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    for key in _IDENTITY_ENV:
        env.pop(key, None)
    env["HAPAX_AGENT_ROLE"] = role
    return subprocess.run(
        [str(gate_impl)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=15,
        check=False,
    )


def _setup_claimed(tmp_path: Path, *, role: str, task_id: str, scope: str) -> None:
    """A present, mounted vault (identity marker) with a claimed, source-authorized
    task whose mutation_scope_refs covers `scope`."""
    personal = tmp_path / "Documents" / "Personal"
    (personal / ".git").mkdir(parents=True, exist_ok=True)  # vault identity marker
    active = personal / "20-projects" / "hapax-cc-tasks" / "active"
    active.mkdir(parents=True, exist_ok=True)
    (active / f"{task_id}-t.md").write_text(
        "---\n"
        "type: cc-task\n"
        f"task_id: {task_id}\n"
        'title: "t"\n'
        "status: in_progress\n"
        f"assigned_to: {role}\n"
        f"parent_spec: {tmp_path / 'spec.md'}\n"
        "authority_case: CASE-TEST-001\n"
        "stage: S6_IMPLEMENTATION\n"
        "implementation_authorized: true\n"
        "source_mutation_authorized: true\n"
        "docs_mutation_authorized: true\n"
        "runtime_mutation_authorized: false\n"
        "route_metadata_schema: 1\n"
        "mutation_scope_refs:\n"
        f"  - {scope}\n"
        "created_at: 2026-06-01T00:00:00Z\n"
        "updated_at: 2026-06-01T00:00:00Z\n"
        "---\n\n# t\n\n## Session log\n"
    )
    cache = tmp_path / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"cc-active-task-{role}").write_text(task_id + "\n")


def _bash(cmd: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


def test_shell_mutation_refusal_names_write_edit_and_seat(tmp_path: Path):
    """The refusal MESSAGE guides to the Write/Edit tool for content and to the
    seat/an authorizing row for rename-move-delete, and suggests NO command spelling."""
    scope = str(tmp_path / "scope")
    _setup_claimed(tmp_path, role="delta", task_id="t6", scope=scope + "/")
    gate = _stage_gate(tmp_path)
    result = _run(gate, _bash(f"mv {scope}/a {scope}/b"), tmp_path, role="delta")
    assert result.returncode == 2, f"a shell mutation is refused by design; stderr={result.stderr}"
    low = result.stderr.lower()
    assert "write" in low and "edit" in low, (
        f"message must name the Write/Edit tool; stderr={result.stderr}"
    )
    assert "seat" in low and ("authorize" in low or "authorizes" in low), (
        f"message must route rename/move/delete to the seat or an authorizing row; stderr={result.stderr}"
    )
    # Never suggest an alternative command spelling / path form.
    assert "/usr/bin/" not in result.stderr, (
        f"must not suggest a command-spelling workaround; stderr={result.stderr}"
    )
    assert "absolute path" not in low, (
        f"must not suggest a path-spelling workaround; stderr={result.stderr}"
    )


def test_in_scope_mv_target_is_still_refused(tmp_path: Path):
    """Negative/narrowness: even when the mv target is INSIDE mutation_scope_refs, the
    shell mutation is still refused — the gate does not extract targets (no spelling
    classification). Mutation-verify by temporarily adding extraction: this goes red."""
    scope = str(tmp_path / "scope")
    _setup_claimed(tmp_path, role="delta", task_id="t6", scope=scope + "/")
    gate = _stage_gate(tmp_path)
    result = _run(gate, _bash(f"mv {scope}/in-scope-a {scope}/in-scope-b"), tmp_path, role="delta")
    assert result.returncode == 2, (
        f"an in-scope shell mv must STILL be refused (no target extraction); "
        f"rc={result.returncode} stderr={result.stderr}"
    )
