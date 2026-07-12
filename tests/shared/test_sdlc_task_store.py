from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.coord_dispatch import (
    CoordDispatchError,
    dispatch_preparation_binding_from_payload,
)
from shared.sdlc_task_store import (
    ClaimDispatchBinding,
    TaskStoreError,
    load_claim_dispatch_binding,
    resolve_task_note,
    write_claim_dispatch_binding,
)


def _note(path: Path, task_id: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntask_id: {task_id}\nstatus: offered\nassigned_to: unassigned\n---\n",
        encoding="utf-8",
    )
    return path


def test_exact_task_note_precedes_prefix_sibling(tmp_path: Path) -> None:
    exact = _note(tmp_path / "active" / "task-1.md", "task-1")
    _note(tmp_path / "active" / "task-1-followup.md", "task-1-followup")

    assert resolve_task_note(tmp_path, "task-1").path == exact.resolve()


def test_broken_exact_symlink_refuses_suffix_fallback(tmp_path: Path) -> None:
    exact = tmp_path / "active" / "task-1.md"
    exact.parent.mkdir(parents=True)
    exact.symlink_to(tmp_path / "missing.md")
    _note(tmp_path / "active" / "task-1-work.md", "task-1")

    with pytest.raises(TaskStoreError, match="task_note_path_unsafe"):
        resolve_task_note(tmp_path, "task-1")


def test_suffix_resolution_skips_other_declared_identity(tmp_path: Path) -> None:
    _note(tmp_path / "active" / "task-1-followup.md", "task-1-followup")
    selected = _note(tmp_path / "active" / "task-1-work.md", "task-1")

    assert resolve_task_note(tmp_path, "task-1").path == selected.resolve()


def test_suffix_resolution_rejects_multiple_matching_notes(tmp_path: Path) -> None:
    _note(tmp_path / "active" / "task-1-one.md", "task-1")
    _note(tmp_path / "active" / "task-1-two.md", "task-1")

    with pytest.raises(TaskStoreError, match="task_note_identity_ambiguous"):
        resolve_task_note(tmp_path, "task-1")


def test_claim_dispatch_binding_rejects_tampered_receipt(tmp_path: Path) -> None:
    binding = ClaimDispatchBinding.create(
        task_id="task-1",
        lane="cx-red",
        session_id="session-1",
        claim_epoch=123,
        dispatch_message_id="message-1",
        platform="codex",
        mode="headless",
        profile="full",
        authority_case="CASE-1",
        binding_hash="a" * 64,
        coord_dispatch_idempotency_key="key-1",
    )
    path = write_claim_dispatch_binding(tmp_path, "cx-red", binding)
    record = json.loads(path.read_text(encoding="ascii"))
    record["task_id"] = "task-2"
    path.write_text(json.dumps(record), encoding="ascii")

    with pytest.raises(TaskStoreError, match="receipt_hash_mismatch"):
        load_claim_dispatch_binding(path)


def test_dispatch_preparation_payload_rejects_duplicate_keys() -> None:
    payload = '{"dispatch_binding":{},"dispatch_binding":{}}'

    with pytest.raises(CoordDispatchError, match="payload_duplicate_key"):
        dispatch_preparation_binding_from_payload(payload)
