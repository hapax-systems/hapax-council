"""Integration witnesses for the charter machinery.

Two production wirings are exercised end-to-end against synthetic vaults:

- ``scripts/cc-claim`` charter_keep: a unit claimed while its charter holds
  the lease is recorded under the charter, the parent's publication receipt
  is actually resolved, and an absent parent lease holds instead of falling
  through to minting a fresh claim.
- ``hooks/scripts/cc-task-gate.impl.sh`` obligation reporter: an edit inside
  a charter's scope is allowed, the recorded units (charter-units-*.jsonl)
  are consulted, and only an edit no unit covers is written down as a breach.

The library-level contracts live in tests/shared/test_charter_claim.py; these
tests pin the wiring, not the functions.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cc-claim"
GATE = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.impl.sh"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.gate0b_claim_publication_install import (  # noqa: E402
    default_claim_publication_roots,
    install_claim_publication_composition,
)

_SESSION_ID = "1a2b3c4d-1111-2222-3333-444455556666"
_ROLE = "cx-charter-test"

_AMBIENT_IDENTITY_ENV = (
    "HAPAX_AGENT_NAME",
    "CODEX_THREAD_NAME",
    "CODEX_SESSION_NAME",
    "CODEX_SESSION",
    "CODEX_ROLE",
    "CLAUDE_ROLE",
    "CLAUDE_CODE_SESSION_ID",
    "HAPAX_SESSION_ID",
    "HAPAX_GATE0B_CLAIM_PUBLICATION_OFF",
    "HAPAX_CLAIM_DISPATCH_MESSAGE_ID",
    "HAPAX_CLAIM_DISPATCH_BINDING_HASH",
    "HAPAX_CLAIM_DISPATCH_PLATFORM",
    "HAPAX_CLAIM_DISPATCH_MODE",
    "HAPAX_CLAIM_DISPATCH_PROFILE",
    "HAPAX_CLAIM_DISPATCH_AUTHORITY_CASE",
    "HAPAX_CLAIM_DISPATCH_IDEMPOTENCY_KEY",
)


def _task_root(home: Path) -> Path:
    root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (root / "active").mkdir(parents=True, exist_ok=True)
    (root / "closed").mkdir(parents=True, exist_ok=True)
    return root


def _write_note(
    home: Path,
    task_id: str,
    *,
    extra_frontmatter: list[str] | None = None,
    status: str = "offered",
) -> Path:
    root = _task_root(home)
    path = root / "active" / f"{task_id}.md"
    lines = [
        "---",
        "type: cc-task",
        f"task_id: {task_id}",
        f'title: "{task_id}"',
        f"status: {status}",
        "assigned_to: unassigned",
        "claimable: true",
        "kind: implementation",
        "authority_case: CASE-TEST-001",
        "parent_spec: /tmp/charter-parent-spec.md",
        "quality_floor: frontier_required",
        "mutation_surface: source",
        "authority_level: authoritative",
        "route_metadata_schema: 1",
        "depends_on: []",
        "created_at: 2026-09-22T00:00:00Z",
        "updated_at: 2026-09-22T00:00:00Z",
    ]
    lines.extend(extra_frontmatter or [])
    lines.extend(["claimed_at: null", "---", "", f"# {task_id}", "", "## Session log", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _install_gate0b(home: Path) -> None:
    install_claim_publication_composition(
        roots=default_claim_publication_roots(home=home),
        installed_at=datetime(2026, 9, 22, 0, 0, tzinfo=UTC),
        install_task_ref="charter-breach-reporter-publication-validation-20260922-test",
    )


def _claim(
    home: Path,
    task_id: str,
    *,
    extra_env: dict[str, str] | None = None,
    install_gate0b: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for leaked in _AMBIENT_IDENTITY_ENV:
        env.pop(leaked, None)
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = _ROLE
    env["HAPAX_AGENT_NAME"] = _ROLE
    env["HAPAX_SESSION_ID"] = _SESSION_ID
    env.update(
        {
            "HAPAX_CLAIM_DISPATCH_MESSAGE_ID": f"dispatch-{task_id}",
            "HAPAX_CLAIM_DISPATCH_BINDING_HASH": "a" * 64,
            "HAPAX_CLAIM_DISPATCH_PLATFORM": "codex",
            "HAPAX_CLAIM_DISPATCH_MODE": "headless",
            "HAPAX_CLAIM_DISPATCH_PROFILE": "ultra",
            "HAPAX_CLAIM_DISPATCH_AUTHORITY_CASE": "CASE-TEST-001",
            "HAPAX_CLAIM_DISPATCH_IDEMPOTENCY_KEY": f"coord-{task_id}",
        }
    )
    if extra_env:
        env.update(extra_env)
    if install_gate0b:
        _install_gate0b(home)
    return subprocess.run(
        ["bash", str(SCRIPT), task_id],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )


def _publications(home: Path) -> list[str]:
    root = Path(default_claim_publication_roots(home=home).claim_transaction_root)
    if not root.exists():
        return []
    return sorted(path.name for path in root.iterdir() if path.is_dir())


def _write_charter(home: Path, task_id: str = "charter-x") -> Path:
    return _write_note(
        home,
        task_id,
        extra_frontmatter=[
            "claim_form: charter",
            "charter_scope:",
            "  - shared/cx/",
        ],
    )


def _write_unit(home: Path, task_id: str, refs: list[str], parent: str = "charter-x") -> Path:
    return _write_note(
        home,
        task_id,
        extra_frontmatter=[
            f"parent_charter: {parent}",
            "mutation_scope_refs:",
            *[f"  - {ref}" for ref in refs],
        ],
    )


def test_charter_unit_claim_records_unit_and_keeps_lease(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_charter(home)
    charter = _claim(home, "charter-x")
    assert charter.returncode == 0, charter.stderr
    assert len(_publications(home)) == 1
    # The charter sidecar exists from the mint itself, not only once a unit
    # is recorded under the charter.
    mint_sidecar = home / ".cache" / "hapax" / f"cc-active-charter-{_ROLE}-{_SESSION_ID}"
    assert mint_sidecar.read_text(encoding="utf-8") == "charter-x\n"

    _write_unit(home, "unit-a", ["shared/cx/unit-a.py"])
    unit = _claim(home, "unit-a", install_gate0b=False)

    assert unit.returncode == 0, unit.stderr
    assert "recorded 'unit-a' under charter 'charter-x'" in unit.stdout
    cache = home / ".cache" / "hapax"
    ledger = cache / f"charter-units-{_ROLE}-{_SESSION_ID}.jsonl"
    assert ledger.exists()
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows == [
        {
            "schema": "hapax.charter-unit.v1",
            "charter_id": "charter-x",
            "unit_id": "unit-a",
            "recorded_at": rows[0]["recorded_at"],
        }
    ]
    sidecar = cache / f"cc-active-charter-{_ROLE}-{_SESSION_ID}"
    assert sidecar.read_text(encoding="utf-8") == "charter-x\n"
    # The lease stays with the charter: no new claim sidecars, no new publication.
    assert (cache / f"cc-active-task-{_ROLE}").read_text(encoding="utf-8") == "charter-x\n"
    assert len(_publications(home)) == 1
    unit_note = (
        home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active" / "unit-a.md"
    )
    assert "claimed_at: 2026-" in unit_note.read_text(encoding="utf-8")


def test_charter_unit_claim_holds_when_parent_publication_unresolvable(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_charter(home)
    charter = _claim(home, "charter-x")
    assert charter.returncode == 0, charter.stderr

    # The sidecars stay live, but the publication journal is gone: the
    # receipt check must actually resolve, not just be named.
    transaction_root = Path(default_claim_publication_roots(home=home).claim_transaction_root)
    for entry in transaction_root.iterdir():
        if entry.is_dir():
            for child in entry.iterdir():
                child.unlink()
            entry.rmdir()

    _write_unit(home, "unit-a", ["shared/cx/unit-a.py"])
    unit = _claim(home, "unit-a", install_gate0b=False)

    assert unit.returncode == 8
    assert "no coherent applied claim publication" in unit.stderr
    assert _publications(home) == []


def test_charter_unit_claim_holds_with_incomplete_parent_lease_and_mints_nothing(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    _write_charter(home)
    charter = _claim(home, "charter-x")
    assert charter.returncode == 0, charter.stderr
    cache = home / ".cache" / "hapax"
    for key in (_ROLE, f"{_ROLE}-{_SESSION_ID}"):
        (cache / f"cc-claim-epoch-{key}").unlink(missing_ok=True)
        (cache / f"cc-claim-dispatch-{key}.json").unlink(missing_ok=True)

    # The active-task sidecar keeps the loop's charter grant alive, but a
    # leftover active-task file is not a complete lease: the unit holds.
    _write_unit(home, "unit-a", ["shared/cx/unit-a.py"])
    unit = _claim(home, "unit-a", install_gate0b=False)

    assert unit.returncode == 8
    assert "does not have a complete lease" in unit.stderr
    assert len(_publications(home)) == 1


def test_unit_claim_holds_when_charter_has_no_live_lease_sidecars_for_this_role(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    _write_charter(home)
    charter = _claim(home, "charter-x")
    assert charter.returncode == 0, charter.stderr
    cache = home / ".cache" / "hapax"
    # The role-keyed lease legs are archived away; only the minting session's
    # own files remain. A unit claimed from a different session discovers the
    # charter (the bash lease scan reads any session's active-task file) but
    # holds: none of THIS role's lease sidecars belongs to the charter.
    (cache / f"cc-active-task-{_ROLE}").unlink()
    (cache / f"cc-claim-epoch-{_ROLE}").unlink()
    (cache / f"cc-claim-dispatch-{_ROLE}.json").unlink(missing_ok=True)

    _write_unit(home, "unit-a", ["shared/cx/unit-a.py"])
    unit = _claim(home, "unit-a", extra_env={"HAPAX_SESSION_ID": "session-b"}, install_gate0b=False)

    assert unit.returncode == 8
    assert "has no live lease sidecars" in unit.stderr
    assert len(_publications(home)) == 1


def test_inherited_charter_keep_env_does_not_force_the_charter_branch(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    _write_unit(home, "unit-a", ["shared/cx/unit-a.py"])

    # A stale HAPAX_CHARTER_KEEP_TASK inherited from the caller's environment
    # must not reach the charter branch: it is unset before the lease scan,
    # so the claim proceeds as an ordinary claim instead of holding.
    unit = _claim(home, "unit-a", extra_env={"HAPAX_CHARTER_KEEP_TASK": "charter-x"})

    assert unit.returncode == 0, unit.stderr
    cache = home / ".cache" / "hapax"
    assert not (cache / f"charter-units-{_ROLE}-{_SESSION_ID}.jsonl").exists()
    # An ordinary (non-charter) claim writes no charter sidecar.
    assert not (cache / f"cc-active-charter-{_ROLE}-{_SESSION_ID}").exists()
    assert len(_publications(home)) == 1


def test_unit_outside_charter_scope_is_blocked_with_next_action(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_charter(home)
    charter = _claim(home, "charter-x")
    assert charter.returncode == 0, charter.stderr

    _write_unit(home, "unit-b", ["shared/outside/unit-b.py"])
    blocked = _claim(home, "unit-b", install_gate0b=False)

    assert blocked.returncode == 7
    assert "The unit was not recorded." in blocked.stderr
    assert "Next action:" in blocked.stderr
    assert "parent_charter" in blocked.stderr


def _gate_home(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "gate-home"
    vault_root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (vault_root / "active").mkdir(parents=True, exist_ok=True)
    note = vault_root / "active" / "charter-x-gate.md"
    note.write_text(
        "---\n"
        "type: cc-task\n"
        "task_id: charter-x\n"
        'title: "charter-x"\n'
        "status: in_progress\n"
        "assigned_to: alpha\n"
        "authority_case: CASE-TEST-001\n"
        f"parent_spec: {tmp_path / 'parent-spec.md'}\n"
        "stage: S6_IMPLEMENTATION\n"
        "implementation_authorized: true\n"
        "source_mutation_authorized: true\n"
        "docs_mutation_authorized: true\n"
        "runtime_mutation_authorized: false\n"
        "route_metadata_schema: 1\n"
        "mutation_scope_refs:\n"
        "  - /tmp/precise-area/\n"
        "claim_form: charter\n"
        "charter_scope:\n"
        "  - charter-gate-area/\n"
        "---\n"
        "\n"
        "# charter-x\n"
        "\n"
        "## Session log\n",
        encoding="utf-8",
    )
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "cc-active-task-alpha").write_text("charter-x\n", encoding="utf-8")
    return home, note


def _run_gate(
    home: Path, target: Path, *, cwd: Path | None = None, path: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key in (
        "HAPAX_AGENT_ROLE",
        "HAPAX_AGENT_NAME",
        "HAPAX_SESSION_ID",
        "CLAUDE_ROLE",
        "CLAUDE_CODE_SESSION_ID",
        "HAPAX_CC_TASK_GATE_OFF",
        "HAPAX_METHODOLOGY_EMERGENCY",
    ):
        env.pop(key, None)
    env["HOME"] = str(home)
    env["CLAUDE_ROLE"] = "alpha"
    if path:
        env["PATH"] = path
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": str(target)},
    }
    return subprocess.run(
        [str(GATE)],
        input=json.dumps(payload),
        env=env,
        cwd=str(cwd or REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )


def test_gate_reports_charter_breach_when_no_unit_covers_the_edit(tmp_path: Path) -> None:
    home, _ = _gate_home(tmp_path)
    target = REPO_ROOT / "charter-gate-area" / "x.py"

    result = _run_gate(home, target)

    assert result.returncode == 0, result.stderr
    report = home / ".cache" / "hapax" / "charter-obligation-charter-x.jsonl"
    assert report.exists()
    rows = [json.loads(line) for line in report.read_text(encoding="utf-8").splitlines()]
    assert [row["breaches"] for row in rows] == [["charter-gate-area/x.py"]]
    assert rows[0]["schema"] == "hapax.charter-obligation-report.v1"


def test_gate_resolves_the_reporter_from_a_repo_without_shared(tmp_path: Path) -> None:
    home, note = _gate_home(tmp_path)
    note.write_text(
        note.read_text(encoding="utf-8").replace("  - charter-gate-area/\n", "  - src/\n"),
        encoding="utf-8",
    )
    foreign = tmp_path / "other-repo"
    target = foreign / "src" / "x.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(foreign)], check=True, timeout=30)

    # The edit target's repository carries no shared/ tree and the gate is
    # invoked from that repository with the system interpreter (the
    # canonical-deployed shape, no venv editable install): the reporter must
    # import from the canonical council source root, not block the edit.
    result = _run_gate(home, target, cwd=foreign, path="/usr/bin:/bin")

    assert result.returncode == 0, result.stderr
    report = home / ".cache" / "hapax" / "charter-obligation-charter-x.jsonl"
    assert report.exists()
    rows = [json.loads(line) for line in report.read_text(encoding="utf-8").splitlines()]
    assert [row["breaches"] for row in rows] == [["src/x.py"]]


def test_gate_records_no_breach_when_a_unit_covers_the_edit(tmp_path: Path) -> None:
    home, _ = _gate_home(tmp_path)
    cache = home / ".cache" / "hapax"
    (cache / "charter-units-alpha-session.jsonl").write_text(
        json.dumps(
            {
                "schema": "hapax.charter-unit.v1",
                "charter_id": "charter-x",
                "unit_id": "unit-gate",
                "recorded_at": "2026-09-22T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    unit_note = (
        home
        / "Documents"
        / "Personal"
        / "20-projects"
        / "hapax-cc-tasks"
        / "active"
        / "unit-gate-cover.md"
    )
    unit_note.write_text(
        "---\n"
        "type: cc-task\n"
        "task_id: unit-gate\n"
        "parent_charter: charter-x\n"
        "mutation_scope_refs:\n"
        "  - charter-gate-area/\n"
        "---\n"
        "# unit-gate\n",
        encoding="utf-8",
    )
    target = REPO_ROOT / "charter-gate-area" / "x.py"

    result = _run_gate(home, target)

    assert result.returncode == 0, result.stderr
    assert not (cache / "charter-obligation-charter-x.jsonl").exists()


def test_gate_blocks_fail_closed_when_the_obligation_report_cannot_be_written(
    tmp_path: Path,
) -> None:
    home, _ = _gate_home(tmp_path)
    cache = home / ".cache" / "hapax"
    # A directory squatting on the report path makes the report write raise
    # OSError: the reporter must exit 3 and the gate must block the edit
    # rather than let an unrecorded breach pass.
    (cache / "charter-obligation-charter-x.jsonl").mkdir(parents=True, exist_ok=True)
    target = REPO_ROOT / "charter-gate-area" / "x.py"

    result = _run_gate(home, target)

    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "charter check did not finish" in combined
