"""Cooperative role exclusion stays held through the consumer's dependent action."""

from __future__ import annotations

import multiprocessing as mp
import os
from dataclasses import replace
from pathlib import Path

import pytest

from shared import sdlc_claim as claim
from shared.task_note_lock import projected_path_lock
from tests.shared.test_sdlc_claim import _active_admission_fixture, _fixture


@pytest.fixture(autouse=True)
def isolated_binding(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))


def _publish(fixture, admission, ready, applied):
    ready.set()
    claim._apply_admitted_claim_publication_transaction(
        fixture.intent,
        admission.consumption,
        transaction_root=fixture.transactions,
        receipt_root=fixture.cache / "receipts",
        lock_root=fixture.locks,
        now=admission.checked_at,
    )
    applied.set()


@pytest.mark.parametrize("task_id", ["first-task", "other-task"])
def test_admitted_publisher_waits_until_dependent_action_finishes(tmp_path, task_id):
    fixture = _fixture(tmp_path, task_id=task_id)
    fixture = replace(fixture, locks=tmp_path / "installed-nondefault" / "role-locks")
    admission = _active_admission_fixture(tmp_path, fixture)
    context = mp.get_context("spawn")
    ready, applied = context.Event(), context.Event()
    child = context.Process(target=_publish, args=(fixture, admission, ready, applied))
    with claim.claim_role_exclusion(fixture.intent.role, lock_root=fixture.locks) as exclusion:
        exclusion.require_held(role=fixture.intent.role, lock_root=fixture.locks)
        child.start()
        try:
            assert ready.wait(10), "publisher did not reach the publication entry point"
            assert not applied.wait(0.4), "publication crossed a held role exclusion"
            # This write is the dependent fake action, inside the same exclusion span.
            (tmp_path / "fake-action").write_text("acted before successor publication\n")
            assert not list(fixture.cache.glob("cc-active-task-*"))
        finally:
            if not ready.is_set():
                child.terminate()
                child.join(5)
    child.join(15)
    try:
        assert child.exitcode == 0
        assert applied.is_set()
    finally:
        if child.is_alive():
            child.terminate()
            child.join(5)


@pytest.mark.parametrize("inner_role", ["cx-owner", "cx-other"])
def test_nested_role_exclusion_refuses_before_creating_another_lock(tmp_path, inner_role):
    root = tmp_path / "locks"
    with claim.claim_role_exclusion("cx-owner", lock_root=root):
        before = set(root.iterdir())
        with pytest.raises(claim.ClaimPublicationError, match="claim_role_exclusion_nested"):
            with claim.claim_role_exclusion(inner_role, lock_root=root):
                pytest.fail("nested exclusion entered")
        assert set(root.iterdir()) == before


def test_projected_lock_cannot_invert_role_order(tmp_path):
    root = tmp_path / "role-locks"
    with projected_path_lock("task", (tmp_path / "task.md",), root=tmp_path / "notes"):
        with pytest.raises(claim.ClaimPublicationError, match="lock_order_inversion"):
            with claim.claim_role_exclusion("cx-owner", lock_root=root):
                pytest.fail("inverted exclusion entered")
    assert not root.exists()


def test_handle_refuses_wrong_role_root_and_released_use(tmp_path):
    root = tmp_path / "locks"
    with claim.claim_role_exclusion("cx-owner", lock_root=root) as handle:
        handle.require_held(role="cx-owner", lock_root=root)
        for role, other_root in [("cx-other", root), ("cx-owner", tmp_path / "other")]:
            with pytest.raises(claim.ClaimPublicationError, match="claim_role_exclusion_not_held"):
                handle.require_held(role=role, lock_root=other_root)
    with pytest.raises(claim.ClaimPublicationError, match="claim_role_exclusion_not_held"):
        handle.require_held(role="cx-owner", lock_root=root)


def test_exception_releases_exclusion(tmp_path, monkeypatch):
    monkeypatch.setattr(claim, "_CLAIM_PUBLICATION_LOCK_TIMEOUT_SECONDS", 0.1)
    with pytest.raises(RuntimeError, match="fake action failed"):
        with claim.claim_role_exclusion("cx-owner", lock_root=tmp_path / "locks"):
            raise RuntimeError("fake action failed")
    with claim.claim_role_exclusion("cx-owner", lock_root=tmp_path / "locks") as handle:
        handle.require_held(role="cx-owner", lock_root=tmp_path / "locks")


def _timeout(root, result):
    claim._CLAIM_PUBLICATION_LOCK_TIMEOUT_SECONDS = 0.1
    try:
        with claim.claim_role_exclusion("cx-owner", lock_root=Path(root)):
            result.put("entered")
    except claim.ClaimPublicationError as exc:
        result.put(exc.reason_code)


def test_contention_is_bounded_and_fork_does_not_inherit_handle(tmp_path):
    context = mp.get_context("fork")
    result = context.Queue()
    root = tmp_path / "locks"
    with claim.claim_role_exclusion("cx-owner", lock_root=root):
        child = context.Process(target=_timeout, args=(str(root), result))
        child.start()
        child.join(5)
        assert child.exitcode == 0
        assert result.get(timeout=1) == "claim_publication_lock_unavailable"


@pytest.mark.parametrize("shape", ["symlink", "hardlink", "directory"])
def test_unsafe_role_lock_refuses(tmp_path, shape):
    root = tmp_path / "locks"
    root.mkdir(mode=0o700)
    name = root / (claim._claim_publication_role_lock_digest("cx-owner") + ".lock")
    target = tmp_path / "target"
    target.write_text("")
    target.chmod(0o600)
    if shape == "symlink":
        name.symlink_to(target)
    elif shape == "hardlink":
        os.link(target, name)
    else:
        name.mkdir()
    with pytest.raises(claim.ClaimPublicationError):
        with claim.claim_role_exclusion("cx-owner", lock_root=root):
            pytest.fail("unsafe lock entered")


def test_public_exclusion_requires_explicit_root(tmp_path):
    with pytest.raises(claim.ClaimPublicationError, match="claim_role_exclusion_root_required"):
        with claim.claim_role_exclusion("cx-owner", lock_root=None):
            pytest.fail("implicit root entered")


def test_raw_writer_is_outside_the_cooperative_boundary(tmp_path):
    """Keep the raw-writer counterexample: exclusion is not filesystem authorization."""
    with claim.claim_role_exclusion("cx-owner", lock_root=tmp_path / "locks"):
        note = tmp_path / "raw-note.md"
        note.write_text("assigned_to: cx-owner\nstatus: claimed\n")
        assert note.exists()
