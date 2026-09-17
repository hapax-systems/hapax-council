"""cc-task-gate × adoptability teeth (ADOPTABILITY-DETERMINATION-20260916 §7, A2).

Section 2b' of the hook judges Edit/Write/MultiEdit on cc-task rows that carry the
``garage-door`` tag through shared.adoptability_gate, before any claim or scope logic.
Same harness shape as test_cc_task_gate.py: pinned HOME, cleared identity env,
tool_input on stdin. Positive cases assert the *absence* of the teeth refusal (the
hook may still block downstream for want of a claim — that is another gate's word).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.impl.sh"
TEETH_MARK = "adoptability teeth refuse"
INSTALL_LINE = "curl -fsSL https://example.org/tool/install.sh | sh"

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


def _block() -> dict:
    return {
        "prior_art_receipt": "receipts/prior-art.yaml",
        "demand_receipt": "receipts/demand.yaml",
        "install_line": INSTALL_LINE,
        "platforms": ["linux"],
        "zero_config": True,
        "ttfv_seconds": 30,
        "replaces_nothing": True,
        "api": "cli",
        "licence": "Apache-2.0",
        "repo_open": "acme/tool",
        "release_notes": "https://github.com/acme/tool/releases",
        "compare_page": "https://example.org/compare",
        "operator_voice_post": "https://example.org/post",
    }


def _row_text(*, tags: list[str], stage: str = "S1_OFFERED", status: str = "offered") -> str:
    front = {
        "type": "cc-task",
        "task_id": "gd-hook",
        "title": "Fixture",
        "status": status,
        "assigned_to": "unassigned",
        "kind": "engineering",
        "authority_case": "CASE-TEST-001",
        "stage": stage,
        "tags": tags,
        "adoptability": _block(),
    }
    return "---\n" + yaml.safe_dump(front, sort_keys=False) + "---\n\n## Session log\n"


def _vault_row(home: Path, text: str | None) -> Path:
    active = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    active.mkdir(parents=True, exist_ok=True)
    note = active / "gd-hook-fixture.md"
    if text is not None:
        note.write_text(text)
    return note


def _write_receipts(home: Path) -> None:
    receipts = home / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    (receipts / "prior-art.yaml").write_text(
        yaml.safe_dump(
            {
                "search_shapes": [
                    {"shape": "github_code_search", "query": "a"},
                    {"shape": "package_registry", "query": "b"},
                ],
                "verdict": "UNBACKED",
            }
        )
    )
    (receipts / "demand.yaml").write_text(yaml.safe_dump({"asked_by": ["issue #12"]}))


def _run_hook(
    tool_input: dict, *, home: Path, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key in _IDENTITY_ENV:
        env.pop(key, None)
    env["HOME"] = str(home)
    env["CLAUDE_ROLE"] = "alpha"
    env["HAPAX_ADOPTABILITY_RECEIPT_ROOTS"] = str(home)
    env["HAPAX_METHODOLOGY_LEDGER"] = str(home / "ledger.jsonl")
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(HOOK)],
        input=json.dumps(tool_input),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )


def _edit(note: Path, old: str, new: str) -> dict:
    return {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(note), "old_string": old, "new_string": new},
    }


def test_hand_advancing_a_garage_door_row_without_receipts_is_blocked(tmp_path: Path) -> None:
    note = _vault_row(tmp_path, _row_text(tags=["cc-task", "garage-door"]))
    result = _run_hook(_edit(note, "stage: S1_OFFERED", "stage: S6_IMPLEMENTATION"), home=tmp_path)
    assert result.returncode == 2
    assert TEETH_MARK in result.stderr
    assert "stage_refused:prior_art_receipt_absent" in result.stderr
    assert "stage_refused:demand_receipt_absent" in result.stderr


def test_hand_claiming_a_garage_door_row_without_receipts_is_blocked(tmp_path: Path) -> None:
    note = _vault_row(tmp_path, _row_text(tags=["cc-task", "garage-door"]))
    result = _run_hook(_edit(note, "status: offered", "status: claimed"), home=tmp_path)
    assert result.returncode == 2
    assert TEETH_MARK in result.stderr


def test_removing_the_garage_door_tag_is_blocked(tmp_path: Path) -> None:
    note = _vault_row(tmp_path, _row_text(tags=["cc-task", "garage-door"]))
    result = _run_hook(_edit(note, "- garage-door\n", "- plain\n"), home=tmp_path)
    assert result.returncode == 2
    assert "stage_refused:garage_door_tag_removed" in result.stderr


def test_writing_a_new_garage_door_row_past_s1_is_blocked(tmp_path: Path) -> None:
    note = _vault_row(tmp_path, None)
    content = _row_text(
        tags=["cc-task", "garage-door"], stage="S6_IMPLEMENTATION", status="in_progress"
    )
    result = _run_hook(
        {"tool_name": "Write", "tool_input": {"file_path": str(note), "content": content}},
        home=tmp_path,
    )
    assert result.returncode == 2
    assert TEETH_MARK in result.stderr


def test_garage_door_row_with_receipts_passes_the_teeth(tmp_path: Path) -> None:
    _write_receipts(tmp_path)
    note = _vault_row(tmp_path, _row_text(tags=["cc-task", "garage-door"]))
    result = _run_hook(_edit(note, "stage: S1_OFFERED", "stage: S6_IMPLEMENTATION"), home=tmp_path)
    assert TEETH_MARK not in result.stderr
    assert "stage_refused" not in result.stderr


def test_editing_a_garage_door_row_inside_offered_passes_the_teeth(tmp_path: Path) -> None:
    note = _vault_row(tmp_path, _row_text(tags=["cc-task", "garage-door"]))
    result = _run_hook(_edit(note, "title: Fixture", "title: Fixture (reworded)"), home=tmp_path)
    assert TEETH_MARK not in result.stderr


def test_non_garage_door_rows_never_reach_the_predicate(tmp_path: Path) -> None:
    note = _vault_row(tmp_path, _row_text(tags=["cc-task", "garage-door-teeth"]))
    result = _run_hook(_edit(note, "stage: S1_OFFERED", "stage: S6_IMPLEMENTATION"), home=tmp_path)
    assert TEETH_MARK not in result.stderr
    assert "stage_refused" not in result.stderr


def test_the_gates_own_killswitch_covers_the_tooth(tmp_path: Path) -> None:
    # Review finding on PR 4676: a tooth placed ahead of the gate's ledgered bypass could not
    # be switched off in an incident. Section 3a now sits after section 3.
    note = _vault_row(tmp_path, _row_text(tags=["cc-task", "garage-door"]))
    result = _run_hook(
        _edit(note, "stage: S1_OFFERED", "stage: S6_IMPLEMENTATION"),
        home=tmp_path,
        extra_env={"HAPAX_CC_TASK_GATE_OFF": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert TEETH_MARK not in result.stderr
    assert "LEDGERED" in result.stderr


def test_the_teeth_killswitch_is_honoured_and_ledgered_through_the_hook(tmp_path: Path) -> None:
    note = _vault_row(tmp_path, _row_text(tags=["cc-task", "garage-door"]))
    result = _run_hook(
        _edit(note, "stage: S1_OFFERED", "stage: S6_IMPLEMENTATION"),
        home=tmp_path,
        extra_env={"HAPAX_ADOPTABILITY_TEETH_OFF": "1"},
    )
    assert TEETH_MARK not in result.stderr
    rows = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert any(
        row["kind"] == "adoptability_teeth_off_bypass" and row["surface"] == "hook-edit"
        for row in rows
    )
