"""Terminal work evidence is more than an applied publication or an absent marker."""

from pathlib import Path

import pytest

from shared import sdlc_claim as claim
from tests.scripts.test_cc_claim import _SESSION_ID
from tests.scripts.test_cc_close_role_exclusion import owned as original_owner
from tests.scripts.test_cc_close_session_lease import _run_close


@pytest.fixture
def owned(tmp_path, monkeypatch):
    return original_owner.__wrapped__(tmp_path, monkeypatch)


def _identity(home, install):
    roots = install.receipt.roots
    applied = claim.resolve_applied_claim_publication(
        vault_root=Path(roots.claim_vault_root),
        cache_dir=Path(roots.claim_cache_dir),
        role="cx-test",
        session_id=_SESSION_ID,
        task_id="original-task",
        transaction_root=Path(roots.claim_transaction_root),
        receipt_root=Path(roots.claim_receipt_root),
        lock_root=Path(roots.claim_lock_root),
    )
    return applied.intent.claim_epoch, applied.receipt.publication_id


def _observe(install, identity, **changes):
    roots = install.receipt.roots
    args = dict(
        vault_root=Path(roots.claim_vault_root),
        cache_dir=Path(roots.claim_cache_dir),
        transaction_root=Path(roots.claim_transaction_root),
        receipt_root=Path(roots.claim_receipt_root),
        lock_root=Path(roots.claim_lock_root),
        role="cx-test",
        session_id=_SESSION_ID,
        task_id="original-task",
        claim_epoch=identity[0],
        publication_id=identity[1],
    )
    args.update(changes)
    with claim.claim_role_exclusion("cx-test", lock_root=Path(roots.claim_lock_root)) as held:
        return claim.observe_terminal_claim(exclusion=held, **args)


def _closed(owned):
    home, note, install = owned
    identity = _identity(home, install)
    result = _run_close(home, "original-task", role="cx-closer", session_id="other-session")
    assert result.returncode == 0, result.stdout + result.stderr
    return home, note.parent.parent / "closed" / note.name, install, identity


def test_real_normal_close_produces_terminal_evidence(owned):
    _, _, install, identity = _closed(owned)
    observed = _observe(install, identity)
    assert isinstance(observed, claim.TerminalClaimEvidence), observed
    assert observed.may_authorize is False
    assert observed.publication_id == identity[1]
    assert observed.receipt.receipt_hash
    assert observed.snapshot.sha256
    assert observed.release is None


def test_applied_journal_on_active_task_is_not_terminal(owned):
    home, _, install = owned
    identity = _identity(home, install)
    observed = _observe(install, identity)
    assert isinstance(observed, claim.TerminalClaimHold)


@pytest.mark.parametrize(
    "change",
    [
        "session",
        "epoch",
        "publication",
        "active-twin",
        "active-twin-same-owner",
        "duplicate",
        "missing-epoch",
        "changed-epoch",
        "new-marker",
        "receipt",
        "unknown-owner",
        "undecodable-owner",
        "sidecar-mode",
        "sidecar-symlink",
        "sidecar-hardlink",
    ],
)
def test_terminal_evidence_holds_on_ambiguous_or_changed_identity(owned, change):
    home, note, install, identity = _closed(owned)
    args = {}
    cache = home / ".cache/hapax"
    if change == "session":
        args["session_id"] = "different-session"
    elif change == "epoch":
        args["claim_epoch"] = identity[0] + 1
    elif change == "publication":
        args["publication_id"] = "claim-pub-" + "0" * 64
    elif change in {"active-twin", "active-twin-same-owner"}:
        twin = note.read_bytes()
        if change == "active-twin":
            twin = twin.replace(b"assigned_to: cx-test", b"assigned_to: cx-other")
        (note.parent.parent / "active" / note.name).write_bytes(twin)
    elif change == "duplicate":
        note.with_name("original-task-duplicate.md").write_bytes(note.read_bytes())
    elif change == "missing-epoch":
        (cache / "cc-claim-epoch-cx-test").unlink()
    elif change == "changed-epoch":
        (cache / "cc-claim-epoch-cx-test").write_text("1 original-task\n")
    elif change == "new-marker":
        (cache / "cc-active-task-cx-test").write_text("successor\n")
    elif change == "receipt":
        next(Path(install.receipt.roots.claim_receipt_root).glob("*.json")).unlink()
    elif change in {"unknown-owner", "undecodable-owner"}:
        other = note.parent.parent / "active" / "new-owner.md"
        other.write_bytes(
            b"\xff"
            if change == "undecodable-owner"
            else b"---\ntask_id: new-owner\nstatus: claimed\nassigned_to: cx-test\n---\n"
        )
    elif change.startswith("sidecar-"):
        import os

        sidecar = cache / "cc-claim-epoch-cx-test"
        if change == "sidecar-mode":
            sidecar.chmod(0o600)
        else:
            original = cache / "preserved-epoch"
            sidecar.rename(original)
            if change == "sidecar-symlink":
                sidecar.symlink_to(original)
            else:
                os.link(original, sidecar)
    observed = _observe(install, identity, **args)
    assert isinstance(observed, claim.TerminalClaimHold), observed


@pytest.mark.parametrize(
    "changed", ["readme-bytes", "readme-mode", "archive-bytes", "archive-mode", "staging-bytes"]
)
def test_governed_release_retains_terminal_evidence(owned, changed):
    _, _, install, identity = _closed(owned)
    roots = install.receipt.roots
    released = claim.release_claim_residue(
        vault_root=Path(roots.claim_vault_root),
        cache_dir=Path(roots.claim_cache_dir),
        role="cx-test",
        task_id="original-task",
        observed_at="20261003T010101Z",
        transaction_root=Path(roots.claim_transaction_root),
        lock_root=Path(roots.claim_lock_root),
    )
    observed = _observe(install, identity)
    assert isinstance(observed, claim.TerminalClaimEvidence), observed
    assert observed.release.archive_path == released.archive_dir
    target = released.archive_dir / (
        "README.md" if changed.startswith("readme") else "cc-claim-epoch-cx-test"
    )
    if changed == "staging-bytes":
        target = (
            Path(roots.claim_cache_dir)
            / "claim-residue-release/original-task/20261003T010101Z-cx-test/cc-claim-epoch-cx-test"
        )
    if changed.endswith("mode"):
        target.chmod(0o600)
    else:
        target.write_bytes(target.read_bytes().replace(b"\n", b"\r\n"))
    assert isinstance(_observe(install, identity), claim.TerminalClaimHold)


def test_lapsed_release_of_active_task_is_not_terminal(owned):
    home, _, install = owned
    identity = _identity(home, install)
    roots = install.receipt.roots
    for path in Path(roots.claim_cache_dir).glob("cc-active-task-*"):
        path.unlink()
    claim.release_claim_residue(
        vault_root=Path(roots.claim_vault_root),
        cache_dir=Path(roots.claim_cache_dir),
        role="cx-test",
        task_id="original-task",
        observed_at="20261003T020202Z",
        transaction_root=Path(roots.claim_transaction_root),
        lock_root=Path(roots.claim_lock_root),
    )
    assert isinstance(_observe(install, identity), claim.TerminalClaimHold)


def test_terminal_snapshot_churn_holds_without_writes(owned, monkeypatch):
    _, note, install, identity = _closed(owned)
    before = note.read_bytes()

    def raced(self):
        raise claim.ReadOnlySnapshotError(
            "fs_snapshot_file_changed", "retry observation", "fixture"
        )

    monkeypatch.setattr(claim.ReadOnlyFsSnapshot, "seal", raced)
    observed = _observe(install, identity)
    assert isinstance(observed, claim.TerminalClaimHold)
    assert observed.reason_code == "fs_snapshot_file_changed"
    assert note.read_bytes() == before
