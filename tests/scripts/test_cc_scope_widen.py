"""Tests for scripts/cc-scope-widen — the sanctioned mutation_scope_refs editor."""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

# cc-scope-widen is an extensionless executable, so spec_from_file_location can't
# infer a loader from the suffix — bind SourceFileLoader explicitly.
_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "cc-scope-widen"
_loader = SourceFileLoader("cc_scope_widen", str(_SCRIPT))
_spec = importlib.util.spec_from_loader("cc_scope_widen", _loader)
assert _spec is not None
cc_scope_widen = importlib.util.module_from_spec(_spec)
_loader.exec_module(cc_scope_widen)


_NOTE_TEMPLATE = """\
---
type: cc-task
task_id: {task_id}
title: "demo"
status: in_progress
assigned_to: zeta
wsjf: 30
authority_case: CASE-SDLC-REFORM-001
parent_spec: ~/spec.md
stage: S6_IMPLEMENTATION
updated_at: 2026-05-31T00:00:00Z
tags:
  - cc-task
  - reform
mutation_scope_refs:
  - shared/coord_event_log.py
  - scripts/
  - tests/
---

# demo

body line
"""


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, task_id: str) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    active = vault / "active"
    active.mkdir(parents=True)
    note = active / f"{task_id}.md"
    note.write_text(_NOTE_TEMPLATE.format(task_id=task_id), encoding="utf-8")

    repo = tmp_path / "repo"
    (repo / "shared").mkdir(parents=True)
    (repo / "agents" / "coordinator").mkdir(parents=True)
    (repo / "shared" / "coord_projection.py").write_text("", encoding="utf-8")
    (repo / "agents" / "coordinator" / "core.py").write_text("", encoding="utf-8")

    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setattr(cc_scope_widen, "VAULT", vault)
    monkeypatch.setattr(cc_scope_widen, "REPO_ROOT", repo)
    monkeypatch.setattr(cc_scope_widen, "LEDGER", ledger)
    return note, ledger


def _scope_block(note_text: str) -> list[str]:
    """Return the mutation_scope_refs list items as they appear in the frontmatter."""
    lines = note_text.splitlines()
    start = lines.index("mutation_scope_refs:")
    items: list[str] = []
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
        else:
            break
    return items


def test_widen_appends_only_requested_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    note, _ = _setup(tmp_path, monkeypatch, "demo-task")

    rc = cc_scope_widen.widen(
        "demo-task",
        ["shared/coord_projection.py", "agents/coordinator/core.py"],
    )

    assert rc == cc_scope_widen.OK
    items = _scope_block(note.read_text(encoding="utf-8"))
    assert items == [
        "shared/coord_event_log.py",
        "scripts/",
        "tests/",
        "shared/coord_projection.py",
        "agents/coordinator/core.py",
    ]
    # The bug guard: scalar frontmatter keys never leak into the list.
    assert "wsjf" not in items and "30" not in items


def test_widen_preserves_frontmatter_scalars_and_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    note, _ = _setup(tmp_path, monkeypatch, "demo-task")

    cc_scope_widen.widen("demo-task", ["shared/coord_projection.py"])

    text = note.read_text(encoding="utf-8")
    assert "\nwsjf: 30\n" in text
    assert "\nstatus: in_progress\n" in text
    assert text.count("mutation_scope_refs:") == 1
    assert text.count("\n---\n") == 1  # exactly one frontmatter close
    assert "# demo" in text and "body line" in text
    assert "\nupdated_at: 2026-05-31T00:00:00Z\n" not in text  # refreshed


def test_widen_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note, _ = _setup(tmp_path, monkeypatch, "demo-task")

    cc_scope_widen.widen("demo-task", ["shared/coord_projection.py"])
    first = _scope_block(note.read_text(encoding="utf-8"))
    rc = cc_scope_widen.widen("demo-task", ["shared/coord_projection.py"])
    second = _scope_block(note.read_text(encoding="utf-8"))

    assert rc == cc_scope_widen.OK
    assert second.count("shared/coord_projection.py") == 1
    assert first == second


def test_widen_refuses_path_with_absent_parent_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    note, _ = _setup(tmp_path, monkeypatch, "demo-task")
    before = note.read_text(encoding="utf-8")

    rc = cc_scope_widen.widen("demo-task", ["nonexistent_dir/foo.py"])

    assert rc == cc_scope_widen.REFUSED
    assert note.read_text(encoding="utf-8") == before  # unchanged on refusal


def test_widen_allows_new_file_in_existing_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    note, _ = _setup(tmp_path, monkeypatch, "demo-task")

    # shared/ exists; the file is new (about to be created) — allowed.
    rc = cc_scope_widen.widen("demo-task", ["shared/brand_new_module.py"])

    assert rc == cc_scope_widen.OK
    assert "shared/brand_new_module.py" in _scope_block(note.read_text(encoding="utf-8"))


def test_widen_removes_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note, _ = _setup(tmp_path, monkeypatch, "demo-task")

    rc = cc_scope_widen.widen("demo-task", [], removals=["scripts/"])

    assert rc == cc_scope_widen.OK
    assert "scripts/" not in _scope_block(note.read_text(encoding="utf-8"))


def test_widen_ledgers_the_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, ledger = _setup(tmp_path, monkeypatch, "demo-task")

    cc_scope_widen.widen("demo-task", ["shared/coord_projection.py"])

    assert ledger.exists()
    body = ledger.read_text(encoding="utf-8")
    assert "scope_widen" in body and "shared/coord_projection.py" in body


# M112 / M108a: the gate resolves a relative scope ref against the personal vault root
# as well as the repo, but cc-scope-widen checked surfaces under the repo only, so every
# vault path was refused and a lane could not lawfully widen onto a row it had drafted.


def _with_personal_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    personal = tmp_path / "Personal"
    rows = personal / "20-projects" / "hapax-cc-tasks" / "active"
    rows.mkdir(parents=True)
    (rows / "drafted-row.md").write_text("---\ntask_id: drafted-row\n---\n", encoding="utf-8")
    monkeypatch.setattr(cc_scope_widen, "PERSONAL_VAULT_ROOT", personal)
    return personal


def test_widen_refuses_paths_that_escape_both_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    note, _ = _setup(tmp_path, monkeypatch, "demo-task")
    _with_personal_vault(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("x", encoding="utf-8")
    before = note.read_text(encoding="utf-8")

    for item in ("../outside/secret.txt", "../outside/", str(outside / "secret.txt")):
        assert cc_scope_widen.widen("demo-task", [item]) == cc_scope_widen.REFUSED, item

    assert note.read_text(encoding="utf-8") == before


def test_widen_refuses_a_vault_typo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note, _ = _setup(tmp_path, monkeypatch, "demo-task")
    _with_personal_vault(tmp_path, monkeypatch)
    before = note.read_text(encoding="utf-8")

    rc = cc_scope_widen.widen("demo-task", ["20-projects/hapax-cc-taks/active/drafted-row.md"])

    assert rc == cc_scope_widen.REFUSED
    assert note.read_text(encoding="utf-8") == before


def test_widen_accepts_a_vault_row_relative_or_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    note, _ = _setup(tmp_path, monkeypatch, "demo-task")
    personal = _with_personal_vault(tmp_path, monkeypatch)
    relative = "20-projects/hapax-cc-tasks/active/drafted-row.md"
    absolute = str(personal / relative)

    assert cc_scope_widen.widen("demo-task", [relative]) == cc_scope_widen.OK
    assert cc_scope_widen.widen("demo-task", [absolute]) == cc_scope_widen.OK

    scope = _scope_block(note.read_text(encoding="utf-8"))
    assert relative in scope
    assert absolute in scope
