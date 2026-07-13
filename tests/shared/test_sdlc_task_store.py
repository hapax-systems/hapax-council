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
    assert_claim_slot_available,
    assert_close_slot_owned,
    load_claim_dispatch_binding,
    resolve_task_note,
)
from tests.shared.sdlc_task_store_support import write_claim_dispatch_binding_fixture


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
    path = write_claim_dispatch_binding_fixture(tmp_path, "cx-red", binding)
    record = json.loads(path.read_text(encoding="ascii"))
    record["task_id"] = "task-2"
    path.write_text(json.dumps(record), encoding="ascii")

    with pytest.raises(TaskStoreError, match="receipt_hash_mismatch"):
        load_claim_dispatch_binding(path)


def test_dispatch_preparation_payload_rejects_duplicate_keys() -> None:
    payload = '{"dispatch_binding":{},"dispatch_binding":{}}'

    with pytest.raises(CoordDispatchError, match="payload_duplicate_key"):
        dispatch_preparation_binding_from_payload(payload)


def test_claim_slot_refuses_expired_different_task_without_mutation(tmp_path: Path) -> None:
    claim = tmp_path / "cc-active-task-cx-red-old-session"
    epoch = tmp_path / "cc-claim-epoch-cx-red-old-session"
    claim.write_text("old-task\n", encoding="utf-8")
    epoch.write_text("1 old-task\n", encoding="utf-8")
    before = (claim.read_bytes(), epoch.read_bytes())

    with pytest.raises(TaskStoreError, match="claim_slot_occupied"):
        assert_claim_slot_available(
            cache_dir=tmp_path,
            role="cx-red",
            session_id="new-session",
            task_id="new-task",
        )

    assert (claim.read_bytes(), epoch.read_bytes()) == before


def test_claim_slot_refuses_legacy_only_same_task_for_new_session(tmp_path: Path) -> None:
    (tmp_path / "cc-active-task-cx-red").write_text("task-1\n", encoding="utf-8")
    (tmp_path / "cc-claim-epoch-cx-red").write_text("1 task-1\n", encoding="utf-8")

    with pytest.raises(TaskStoreError, match="claim_same_task_session_unproven"):
        assert_claim_slot_available(
            cache_dir=tmp_path,
            role="cx-red",
            session_id="new-session",
            task_id="task-1",
        )


def test_close_slot_refuses_legacy_only_claim_for_present_session(tmp_path: Path) -> None:
    (tmp_path / "cc-active-task-cx-red").write_text("task-1\n", encoding="utf-8")
    (tmp_path / "cc-claim-epoch-cx-red").write_text("1 task-1\n", encoding="utf-8")

    with pytest.raises(TaskStoreError, match="close_exact_session_projection_absent"):
        assert_close_slot_owned(
            cache_dir=tmp_path,
            role="cx-red",
            session_id="session-1",
            task_id="task-1",
        )


def test_close_slot_refuses_dispatch_binding_from_other_session(tmp_path: Path) -> None:
    binding = ClaimDispatchBinding.create(
        task_id="task-1",
        lane="cx-red",
        session_id="old-session",
        claim_epoch=1,
        dispatch_message_id="message-1",
        platform="codex",
        mode="headless",
        profile="full",
        authority_case="CASE-1",
        binding_hash="a" * 64,
        coord_dispatch_idempotency_key="key-1",
    )
    for key in ("cx-red", "cx-red-old-session"):
        (tmp_path / f"cc-active-task-{key}").write_text("task-1\n", encoding="utf-8")
        (tmp_path / f"cc-claim-epoch-{key}").write_text("1 task-1\n", encoding="utf-8")
        write_claim_dispatch_binding_fixture(tmp_path, key, binding)

    with pytest.raises(TaskStoreError, match="close_slot_owned_by_other_session"):
        assert_close_slot_owned(
            cache_dir=tmp_path,
            role="cx-red",
            session_id="new-session",
            task_id="task-1",
        )


def test_close_slot_requires_complete_role_and_session_binding_projection(
    tmp_path: Path,
) -> None:
    binding = ClaimDispatchBinding.create(
        task_id="task-1",
        lane="cx-red",
        session_id="session-1",
        claim_epoch=1,
        dispatch_message_id="message-1",
        platform="codex",
        mode="headless",
        profile="full",
        authority_case="CASE-1",
        binding_hash="a" * 64,
        coord_dispatch_idempotency_key="key-1",
    )
    for key in ("cx-red", "cx-red-session-1"):
        (tmp_path / f"cc-active-task-{key}").write_text("task-1\n", encoding="utf-8")
        (tmp_path / f"cc-claim-epoch-{key}").write_text("1 task-1\n", encoding="utf-8")
    write_claim_dispatch_binding_fixture(tmp_path, "cx-red", binding)

    with pytest.raises(
        TaskStoreError,
        match="close_dispatch_binding_projection_incomplete",
    ):
        assert_close_slot_owned(
            cache_dir=tmp_path,
            role="cx-red",
            session_id="session-1",
            task_id="task-1",
        )


def test_close_slot_refuses_torn_role_and_session_claim_epochs(tmp_path: Path) -> None:
    for key, epoch in (("cx-red", 1), ("cx-red-session-1", 2)):
        (tmp_path / f"cc-active-task-{key}").write_text("task-1\n", encoding="utf-8")
        (tmp_path / f"cc-claim-epoch-{key}").write_text(f"{epoch} task-1\n", encoding="utf-8")

    with pytest.raises(TaskStoreError, match="close_slot_projection_epoch_mismatch"):
        assert_close_slot_owned(
            cache_dir=tmp_path,
            role="cx-red",
            session_id="session-1",
            task_id="task-1",
        )


def test_close_slot_refuses_binding_epoch_that_disagrees_with_claim(tmp_path: Path) -> None:
    binding = ClaimDispatchBinding.create(
        task_id="task-1",
        lane="cx-red",
        session_id="session-1",
        claim_epoch=2,
        dispatch_message_id="message-1",
        platform="codex",
        mode="headless",
        profile="full",
        authority_case="CASE-1",
        binding_hash="a" * 64,
        coord_dispatch_idempotency_key="key-1",
    )
    for key in ("cx-red", "cx-red-session-1"):
        (tmp_path / f"cc-active-task-{key}").write_text("task-1\n", encoding="utf-8")
        (tmp_path / f"cc-claim-epoch-{key}").write_text("1 task-1\n", encoding="utf-8")
        write_claim_dispatch_binding_fixture(tmp_path, key, binding)

    with pytest.raises(TaskStoreError, match="close_dispatch_binding_epoch_mismatch"):
        assert_close_slot_owned(
            cache_dir=tmp_path,
            role="cx-red",
            session_id="session-1",
            task_id="task-1",
        )
