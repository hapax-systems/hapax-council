"""Tests for the SDLC frictionless foundational gate-loosening cluster.

Covers the four cc-task-gate.sh loosenings and the work-resolution-gate.sh
cognition exemption from CASE-SDLC-REFORM-001 (foundational cluster):

  1. FR-BASH-MUTATION-FALSE-POSITIVES — quoted payloads + piped read-only sed/grep
     no longer false-trigger the shell-source-scope guard; real in-place edits do.
  3. FR-STAGE-S6-TRAP — a blank stage on a fully-authorized task derives + stamps
     S6 and allows (covered in depth in test_authority_case_gate.py; a ledger check
     lives there).
  4. FR-AUTHORITY-FIELDS-FIRST-MUTATION-BLOCK — nullish route_metadata_schema
     defaults to 1 with a ledger line instead of blocking.
  5. FR-SCOPE-GATES-COGNITION — memory / vault / diagnostic scratch are allowed
     regardless of claim; the governance SSOT and repo docs are NOT.
  6. FR-WRG-PARKED-BRANCH-EDIT-BLOCK — cognition/docs/diagnostic edits are exempt
     from the parked-branch work-resolution block.

Every loosening must emit a ledger line (fail-open-WITH-ledger, never silent).
Invokes the real hooks via subprocess against synthetic fixtures with HOME pinned.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
GATE = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.sh"
WRG = REPO_ROOT / "hooks" / "scripts" / "work-resolution-gate.sh"

_ROLE_ENV_KEYS = (
    "HAPAX_AGENT_NAME",
    "HAPAX_AGENT_ROLE",
    "HAPAX_WORKTREE_ROLE",
    "CODEX_THREAD_NAME",
    "CODEX_ROLE",
    "CLAUDE_ROLE",
    "HAPAX_CC_TASK_GATE_OFF",
    "HAPAX_METHODOLOGY_EMERGENCY",
)


def _run_gate(
    tool_input: dict,
    *,
    home: Path,
    role: str | None = "alpha",
    role_env: str = "CLAUDE_ROLE",
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    for key in _ROLE_ENV_KEYS:
        env.pop(key, None)
    if role is not None:
        env[role_env] = role
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(GATE)],
        input=json.dumps(tool_input),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


def _write_claim(home: Path, role: str, task_id: str) -> None:
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"cc-active-task-{role}").write_text(task_id + "\n")


def _make_vault(
    home: Path,
    *,
    assigned: str = "alpha",
    task_id: str = "fr-001",
    scope: str = "/tmp/frtest-x.py",
    include_route_schema: bool = True,
    stage: str = "S6_IMPLEMENTATION",
    src_authorized: str = "true",
    runtime_authorized: str = "false",
) -> Path:
    vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    vault.mkdir(parents=True, exist_ok=True)
    note = vault / f"{task_id}-test.md"
    lines = [
        "---",
        "type: cc-task",
        f"task_id: {task_id}",
        "status: in_progress",
        f"assigned_to: {assigned}",
        f"parent_spec: {home / 'parent-spec.md'}",
        "authority_case: CASE-SDLC-REFORM-001",
    ]
    if include_route_schema:
        lines.append("route_metadata_schema: 1")
    if stage:
        lines.append(f"stage: {stage}")
    lines += [
        "implementation_authorized: true",
        f"source_mutation_authorized: {src_authorized}",
        "docs_mutation_authorized: true",
        f"runtime_mutation_authorized: {runtime_authorized}",
        "mutation_scope_refs:",
        f"  - {scope}",
        "created_at: 2026-05-29T00:00:00Z",
        "updated_at: 2026-05-29T00:00:00Z",
        "---",
        "",
        "# FR fixture",
        "",
        "## Session log",
        "",
    ]
    note.write_text("\n".join(lines))
    return note


def _ledger_kinds(home: Path) -> list[str]:
    ledger = home / ".cache" / "hapax" / "methodology-emergency-ledger.jsonl"
    if not ledger.exists():
        return []
    return [
        json.loads(line).get("kind", "") for line in ledger.read_text().splitlines() if line.strip()
    ]


# ── FR-BASH-MUTATION-FALSE-POSITIVES (change 1) ──────────────────────────


class TestBashMutationFalsePositives:
    def test_quoted_mutation_tokens_in_commit_message_not_scope_blocked(
        self, tmp_path: Path
    ) -> None:
        # `rm` / `mv` appear only inside the quoted commit message; CMD_STRIPPED
        # removes the quoted span before the source-scope check.
        _make_vault(tmp_path)
        _write_claim(tmp_path, "alpha", "fr-001")
        result = _run_gate(
            {
                "tool_name": "Bash",
                "tool_input": {"command": 'git commit -m "remove the rm and mv helpers"'},
            },
            home=tmp_path,
        )
        assert result.returncode == 0, f"stderr={result.stderr}"
        assert "cannot verify mutation_scope_refs" not in result.stderr

    def test_piped_read_only_sed_grep_not_scope_blocked(self, tmp_path: Path) -> None:
        # The `-iE` belongs to grep, across a pipe — the tightened sed pattern
        # must not borrow it. This is a read-only pipeline, not an in-place edit.
        _make_vault(tmp_path)
        _write_claim(tmp_path, "alpha", "fr-001")
        result = _run_gate(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "sed 's/x/y/' notes.txt | grep -iE pattern"},
            },
            home=tmp_path,
        )
        assert result.returncode == 0, f"stderr={result.stderr}"
        assert "cannot verify mutation_scope_refs" not in result.stderr

    def test_real_in_place_sed_still_blocked(self, tmp_path: Path) -> None:
        # A genuine `sed -i` source edit with no path stays blocked (preserved).
        _make_vault(tmp_path)
        _write_claim(tmp_path, "alpha", "fr-001")
        result = _run_gate(
            {"tool_name": "Bash", "tool_input": {"command": "sed -i 's/a/b/' /etc/hosts"}},
            home=tmp_path,
        )
        assert result.returncode == 2
        assert "cannot verify mutation_scope_refs" in result.stderr

    def test_systemctl_in_payload_not_scope_blocked(self, tmp_path: Path) -> None:
        # `systemctl` inside a quoted payload must not be treated as a source-scope
        # mutation. With runtime authorized, the command passes (the runtime gate,
        # not the scope gate, is the relevant one and is satisfied).
        _make_vault(tmp_path, runtime_authorized="true")
        _write_claim(tmp_path, "alpha", "fr-001")
        result = _run_gate(
            {
                "tool_name": "Bash",
                "tool_input": {"command": 'git commit -m "note: restart via systemctl later"'},
            },
            home=tmp_path,
        )
        assert "cannot verify mutation_scope_refs" not in result.stderr
        assert result.returncode == 0, f"stderr={result.stderr}"


# ── FR-AUTHORITY-FIELDS-FIRST-MUTATION-BLOCK (change 4) ──────────────────


class TestRouteSchemaDefault:
    def test_nullish_route_schema_defaults_and_logs(self, tmp_path: Path) -> None:
        scope = str(tmp_path / "work" / "x.py")
        _make_vault(tmp_path, include_route_schema=False, scope=scope)
        _write_claim(tmp_path, "alpha", "fr-001")
        result = _run_gate(
            {"tool_name": "Edit", "tool_input": {"file_path": scope}},
            home=tmp_path,
        )
        assert result.returncode == 0, f"stderr={result.stderr}"
        assert "route_metadata_schema" in result.stderr
        assert "route_schema_defaulted" in _ledger_kinds(tmp_path)


# ── FR-SCOPE-GATES-COGNITION (change 5) ──────────────────────────────────


class TestCognitionAllowlist:
    def test_memory_edit_allowed_without_claim(self, tmp_path: Path) -> None:
        target = tmp_path / ".claude" / "projects" / "-test" / "memory" / "fact.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        result = _run_gate(
            {"tool_name": "Write", "tool_input": {"file_path": str(target)}},
            home=tmp_path,
            role=None,
        )
        assert result.returncode == 0, f"stderr={result.stderr}"
        assert "cognition_allow" in _ledger_kinds(tmp_path)

    def test_vault_note_allowed_without_claim(self, tmp_path: Path) -> None:
        target = tmp_path / "Documents" / "Personal" / "00-daily" / "2026-05-29.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        result = _run_gate(
            {"tool_name": "Write", "tool_input": {"file_path": str(target)}},
            home=tmp_path,
            role=None,
        )
        assert result.returncode == 0, f"stderr={result.stderr}"
        assert "cognition_allow" in _ledger_kinds(tmp_path)

    def test_tmp_hapax_diagnostic_allowed_without_claim(self, tmp_path: Path) -> None:
        result = _run_gate(
            {"tool_name": "Write", "tool_input": {"file_path": "/tmp/hapax-diag-fr.txt"}},
            home=tmp_path,
            role=None,
        )
        assert result.returncode == 0, f"stderr={result.stderr}"

    def test_governance_ssot_is_not_cognition(self, tmp_path: Path) -> None:
        # An existing cc-task note must NOT be cognition-short-circuited: editing
        # it without a claim stays blocked by the bootstrap/claim path.
        note = (
            tmp_path
            / "Documents"
            / "Personal"
            / "20-projects"
            / "hapax-cc-tasks"
            / "active"
            / "ghost.md"
        )
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text("---\ntype: cc-task\nstatus: offered\n---\n# ghost\n")
        result = _run_gate(
            {"tool_name": "Write", "tool_input": {"file_path": str(note), "content": "x"}},
            home=tmp_path,
            role=None,
        )
        assert result.returncode == 2
        assert "cognition_allow" not in _ledger_kinds(tmp_path)

    def test_repo_docs_md_is_not_cognition(self, tmp_path: Path) -> None:
        # Repo docs/*.md keep the docs_mutation_authorized gate: with no claim the
        # edit is blocked (not silently allowed as cognition).
        target = tmp_path / "repo" / "docs" / "guide.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        result = _run_gate(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            home=tmp_path,
            role=None,
        )
        assert result.returncode == 2
        assert "cognition_allow" not in _ledger_kinds(tmp_path)


# ── FR-WRG-PARKED-BRANCH-EDIT-BLOCK (change 6) ───────────────────────────


def _run_wrg(file_path: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(WRG)],
        input=json.dumps({"tool_name": "Edit", "tool_input": {"file_path": file_path}}),
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=15,
    )


class TestWorkResolutionCognitionExempt:
    def test_markdown_exempt(self, tmp_path: Path) -> None:
        target = tmp_path / "notes.md"
        target.write_text("x")
        result = _run_wrg(str(target))
        assert result.returncode == 0
        assert result.stderr == ""

    def test_docs_path_exempt(self, tmp_path: Path) -> None:
        target = tmp_path / "docs" / "thing.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")
        result = _run_wrg(str(target))
        assert result.returncode == 0
