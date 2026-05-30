"""Tests for scripts/cc-task-repair (FR-MALFORMED-TASK-UNREPAIRABLE, cluster 5).

cc-task-repair backfills ONLY governance scaffolding into a malformed cc-task
note (offered OR claimed/in_progress), and is diff-gated: it never overwrites an
existing non-scaffolding value and never flips a no-go boolean to ``true``.

Invokes the script via subprocess against synthetic vault fixtures under
``tmp_path`` (HOME override) so the operator's real vault is never touched.
Per project convention, no shared conftest fixtures — each test builds its own
vault + note.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "cc-task-repair"

# A no-go boolean set every well-formed task must carry (least-privilege false).
NOGO_BOOLEANS = (
    "implementation_authorized",
    "source_mutation_authorized",
    "docs_mutation_authorized",
    "runtime_mutation_authorized",
    "release_authorized",
    "public_current",
)


def _make_note(
    tmp_path: Path,
    *,
    task_id: str,
    status: str = "offered",
    assigned_to: str = "unassigned",
    extra_frontmatter: str = "",
    body: str = "\n# Fixture\n\nSome body text.\n",
    include_session_log: bool = False,
) -> tuple[Path, Path]:
    """Build a *malformed* cc-task note (missing scaffolding) under a fixture vault.

    Returns ``(vault_root, note_path)``. The note carries the required authority
    scalars but deliberately omits the no-go booleans, route_metadata_schema,
    stage, the present-empty lists, and (by default) the ``## Session log``.
    """
    vault_root = tmp_path / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    note_dir = vault_root / "active"
    note_dir.mkdir(parents=True, exist_ok=True)
    note = note_dir / f"{task_id}-fixture.md"
    session_log = (
        "\n## Session log\n\n- 2026-05-29T00:00:00Z fixture\n" if include_session_log else ""
    )
    note.write_text(
        f"""---
type: cc-task
task_id: {task_id}
title: "Malformed fixture"
priority: p2
wsjf: 5.0
status: {status}
assigned_to: {assigned_to}
parent_spec: ~/projects/hapax-council/docs/specs/some.md
authority_case: CASE-TEST-001
quality_floor: standard
mutation_surface: source
authority_level: authoritative
created_at: 2026-05-29T00:00:00Z
updated_at: 2026-05-29T00:00:00Z
{extra_frontmatter}---
{body}{session_log}"""
    )
    return vault_root, note


def _run_repair(
    *args: str,
    home: Path,
    role: str = "eta",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["CLAUDE_ROLE"] = role
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["python3", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


def test_scaffolds_malformed_offered_note(tmp_path: Path) -> None:
    _vault, note = _make_note(tmp_path, task_id="repair-offered-001", status="offered")
    result = _run_repair("repair-offered-001", home=tmp_path)
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    text = note.read_text(encoding="utf-8")
    # Every no-go boolean is backfilled to the least-privilege false.
    for field in NOGO_BOOLEANS:
        assert f"{field}: false" in text, f"{field} not scaffolded to false:\n{text}"
    # Route schema, stage, present-empty lists, and a Session log heading.
    assert "route_metadata_schema: 1" in text
    assert "stage: S6_IMPLEMENTATION" in text
    assert "mutation_scope_refs:" in text
    assert "depends_on:" in text
    assert "blocks:" in text
    assert "## Session log" in text
    # The authority root is untouched.
    assert "authority_case: CASE-TEST-001" in text
    assert 'title: "Malformed fixture"' in text


def test_repair_writes_ledger_line(tmp_path: Path) -> None:
    _vault, _note = _make_note(tmp_path, task_id="repair-ledger-001", status="offered")
    result = _run_repair("repair-ledger-001", home=tmp_path)
    assert result.returncode == 0, result.stderr
    ledger = tmp_path / ".cache" / "hapax" / "cc-task-gate-bootstrap-ledger.jsonl"
    assert ledger.exists(), "repair must append to the bootstrap ledger"
    records = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
    assert any(r.get("kind") == "task_repair" for r in records), records


def test_scaffolds_malformed_in_progress_note(tmp_path: Path) -> None:
    _vault, note = _make_note(
        tmp_path, task_id="repair-inprog-001", status="in_progress", assigned_to="eta"
    )
    result = _run_repair("repair-inprog-001", home=tmp_path)
    assert result.returncode == 0, result.stderr
    text = note.read_text(encoding="utf-8")
    for field in NOGO_BOOLEANS:
        assert f"{field}: false" in text
    assert "status: in_progress" in text  # status is not a scaffolding field — untouched


def test_refuses_non_scaffolding_field_via_set(tmp_path: Path) -> None:
    _vault, note = _make_note(tmp_path, task_id="repair-refuse-title", status="offered")
    before = note.read_text(encoding="utf-8")
    result = _run_repair("repair-refuse-title", "--set", "title=Hijacked", home=tmp_path)
    assert result.returncode == 2, f"expected REFUSED: out={result.stdout!r} err={result.stderr!r}"
    assert "scaffolding" in result.stderr.lower()
    assert note.read_text(encoding="utf-8") == before  # byte-identical — nothing written


def test_refuses_flipping_nogo_boolean_true(tmp_path: Path) -> None:
    _vault, note = _make_note(tmp_path, task_id="repair-refuse-bool", status="offered")
    before = note.read_text(encoding="utf-8")
    result = _run_repair(
        "repair-refuse-bool", "--set", "implementation_authorized=true", home=tmp_path
    )
    assert result.returncode == 2, f"expected REFUSED: out={result.stdout!r} err={result.stderr!r}"
    assert "true" in result.stderr.lower()
    text = note.read_text(encoding="utf-8")
    assert text == before
    assert "implementation_authorized: true" not in text  # the escalation never lands


def test_never_overwrites_existing_authorized_true(tmp_path: Path) -> None:
    _vault, note = _make_note(
        tmp_path,
        task_id="repair-keep-true",
        status="in_progress",
        assigned_to="eta",
        extra_frontmatter="release_authorized: true\n",
    )
    result = _run_repair("repair-keep-true", home=tmp_path)
    assert result.returncode == 0, result.stderr
    text = note.read_text(encoding="utf-8")
    assert "release_authorized: true" in text  # present value untouched
    assert "release_authorized: false" not in text  # never flipped
    assert "implementation_authorized: false" in text  # the absent ones still backfilled


def test_idempotent_second_run_is_noop(tmp_path: Path) -> None:
    _vault, note = _make_note(tmp_path, task_id="repair-idem-001", status="offered")
    first = _run_repair("repair-idem-001", home=tmp_path)
    assert first.returncode == 0, first.stderr
    after_first = note.read_text(encoding="utf-8")
    second = _run_repair("repair-idem-001", home=tmp_path)
    assert second.returncode == 0, second.stderr
    assert note.read_text(encoding="utf-8") == after_first  # no churn on re-run
    assert "already well-formed" in second.stderr


def test_set_backfills_absent_scaffolding_value(tmp_path: Path) -> None:
    _vault, note = _make_note(tmp_path, task_id="repair-set-stage", status="offered")
    result = _run_repair("repair-set-stage", "--set", "stage=S5_PLANNING", home=tmp_path)
    assert result.returncode == 0, result.stderr
    text = note.read_text(encoding="utf-8")
    assert "stage: S5_PLANNING" in text  # --set overrides the default for an absent key
    assert "stage: S6_IMPLEMENTATION" not in text


def test_reports_residual_non_scaffolding_gap(tmp_path: Path) -> None:
    vault_root = tmp_path / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    note_dir = vault_root / "active"
    note_dir.mkdir(parents=True, exist_ok=True)
    note = note_dir / "repair-residual-001-fixture.md"
    # Missing a NON-scaffolding required field (authority_case): repair scaffolds
    # what it can but reports the residual gap rather than claiming full repair.
    note.write_text(
        """---
type: cc-task
task_id: repair-residual-001
title: "Missing authority"
priority: p2
wsjf: 5.0
status: offered
assigned_to: unassigned
parent_spec: ~/projects/x.md
quality_floor: standard
mutation_surface: source
authority_level: authoritative
created_at: 2026-05-29T00:00:00Z
updated_at: 2026-05-29T00:00:00Z
---

# Missing authority
"""
    )
    result = _run_repair("repair-residual-001", home=tmp_path)
    assert result.returncode == 1, f"expected RESIDUAL: out={result.stdout!r} err={result.stderr!r}"
    assert "authority_case" in result.stderr
    assert "implementation_authorized: false" in note.read_text(encoding="utf-8")
