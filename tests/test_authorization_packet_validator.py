"""Tests for hooks/scripts/authorization-packet-validator.sh (FR-PACKET-VALIDATOR-TEMPLATE-GAP).

The validator must stop hard-blocking a release command merely because a no-go
field is *absent*. All five no-go fields default to ``false`` at the PRESENCE
check only (a ledger line is emitted), so:
  - absent docs_mutation_authorized / public_current no longer wall a push, and
  - absent implementation_authorized still blocks — but on the defaulted VALUE
    (not authorized), never "solely on absence".

Invokes the shell hook via subprocess against synthetic vault fixtures under
``tmp_path`` (HOME override). No shared conftest — each test builds its own note.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "authorization-packet-validator.sh"

# A well-formed authorization packet, minus whatever a test omits.
_BASE_FIELDS = {
    "type": "cc-task",
    "task_id": "pkt-001",
    "title": '"Packet fixture"',
    "status": "in_progress",
    "assigned_to": "beta",
    "authority_case": "CASE-TEST-001",
    "parent_spec": "~/projects/hapax-council/docs/specs/x.md",
    "stage": "S6_IMPLEMENTATION",
    "implementation_authorized": "true",
    "source_mutation_authorized": "true",
    "docs_mutation_authorized": "true",
    "runtime_mutation_authorized": "false",
    "release_authorized": "false",
    "public_current": "false",
}


def _make_note(tmp_path: Path, *, task_id: str = "pkt-001", omit: tuple[str, ...] = ()) -> Path:
    vault = tmp_path / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    vault.mkdir(parents=True, exist_ok=True)
    fields = {k: v for k, v in _BASE_FIELDS.items() if k not in omit}
    fields["task_id"] = task_id
    front = "\n".join(f"{k}: {v}" for k, v in fields.items())
    note = vault / f"{task_id}-fixture.md"
    note.write_text(f"---\n{front}\n---\n\n# Packet fixture\n\n## Session log\n")
    return note


def _write_claim(tmp_path: Path, role: str, task_id: str) -> None:
    cache = tmp_path / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"cc-active-task-{role}").write_text(task_id + "\n")


def _run(command: str, *, tmp_path: Path, role: str = "beta") -> subprocess.CompletedProcess:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "t"}
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["CLAUDE_ROLE"] = role
    env.pop("HAPAX_AGENT_ROLE", None)
    env.pop("CODEX_ROLE", None)
    env.pop("HAPAX_METHODOLOGY_EMERGENCY", None)
    return subprocess.run(
        [str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


def _ledger_records(tmp_path: Path) -> list[dict]:
    ledger = tmp_path / ".cache" / "hapax" / "methodology-emergency-ledger.jsonl"
    if not ledger.exists():
        return []
    return [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]


def test_absent_docs_and_public_no_longer_block_push(tmp_path: Path) -> None:
    _make_note(tmp_path, omit=("docs_mutation_authorized", "public_current"))
    _write_claim(tmp_path, "beta", "pkt-001")
    result = _run("git push -u origin HEAD", tmp_path=tmp_path)
    assert result.returncode == 0, f"absent docs/public must not block push: {result.stderr}"


def test_default_emits_ledger_line(tmp_path: Path) -> None:
    _make_note(tmp_path, omit=("docs_mutation_authorized", "public_current"))
    _write_claim(tmp_path, "beta", "pkt-001")
    result = _run("git push -u origin HEAD", tmp_path=tmp_path)
    assert result.returncode == 0, result.stderr
    records = _ledger_records(tmp_path)
    defaulted = [r for r in records if r.get("kind") == "nogo_field_defaulted"]
    assert defaulted, f"expected a nogo_field_defaulted ledger line; got {records}"
    joined = json.dumps(defaulted)
    assert "docs_mutation_authorized" in joined
    assert "public_current" in joined


def test_absent_impl_blocks_on_value_not_presence(tmp_path: Path) -> None:
    # implementation_authorized absent -> defaults false -> blocks, but as a
    # value decision ("not authorized"), never the old "missing required" wall.
    _make_note(
        tmp_path,
        omit=("implementation_authorized", "docs_mutation_authorized", "public_current"),
    )
    _write_claim(tmp_path, "beta", "pkt-001")
    result = _run("git push -u origin HEAD", tmp_path=tmp_path)
    assert result.returncode == 2, f"absent impl must still fail closed: {result.stdout}"
    assert "implementation_authorized" in result.stderr
    assert "missing required no-go fields" not in result.stderr


def test_fully_present_valid_packet_passes_without_ledger(tmp_path: Path) -> None:
    _make_note(tmp_path)  # all fields present
    _write_claim(tmp_path, "beta", "pkt-001")
    result = _run("git push -u origin HEAD", tmp_path=tmp_path)
    assert result.returncode == 0, result.stderr
    assert not [r for r in _ledger_records(tmp_path) if r.get("kind") == "nogo_field_defaulted"]


def test_merge_still_requires_release_authorized(tmp_path: Path) -> None:
    # The default-false touches only the PRESENCE check; the merge VALUE gate is
    # untouched, so a merge with release_authorized:false is still refused.
    _make_note(tmp_path)
    _write_claim(tmp_path, "beta", "pkt-001")
    result = _run("gh pr merge 123 --squash", tmp_path=tmp_path)
    assert result.returncode == 2, f"merge without release auth must block: {result.stdout}"
    assert "release" in result.stderr.lower()
