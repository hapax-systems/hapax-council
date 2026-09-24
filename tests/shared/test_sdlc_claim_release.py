"""Governed release of another holder's claim lease (the half of a governed rebind).

A release checks the incumbent's exact current projection under the installed role lock
and then the task-note lock, requires a typed witness checked at the point of use, archives
every byte it removes, and is idempotent under crash and retry. The successor then claims
through the unchanged admitted publication.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

import shared.sdlc_claim as sdlc_claim
from shared.sdlc_claim import ClaimPublicationError, release_claim_lease
from shared.sdlc_task_store import ClaimDispatchBinding, write_claim_dispatch_binding

TASK = "held-task"
ROLE = "cx-walled"
SESSION = "6fe9afe8-84e2-4093-a09d-6ce5e387eddb"
OTHER_SESSION = "0a0a0a0a-1111-4222-8333-444455556666"
EPOCH = 1790224731
NOW = datetime(2026, 9, 24, 20, 0, tzinfo=UTC)


def _note(status: str = "claimed", assigned_to: str = ROLE, task_id: str = TASK) -> str:
    return (
        "---\n"
        "type: cc-task\n"
        f"task_id: {task_id}\n"
        f'title: "{task_id}"\n'
        f"status: {status}\n"
        f"assigned_to: {assigned_to}\n"
        "claimable: true\n"
        "claimed_at: 2026-09-24T04:38:52Z\n"
        "updated_at: 2026-09-24T07:16:36Z\n"
        "---\n\n"
        f"# {task_id}\n\n"
        "## Session log\n"
        f"- 2026-09-24T04:38:52Z {assigned_to} claimed (cc-claim)\n"
    )


class Fixture:
    def __init__(self, tmp_path: Path) -> None:
        self.vault = tmp_path / "vault"
        self.cache = tmp_path / "cache"
        self.transactions = tmp_path / "transactions"
        self.receipts = tmp_path / "receipts"
        self.locks = tmp_path / "locks"
        for state in ("active", "closed", "refused"):
            (self.vault / state).mkdir(parents=True)
        self.cache.mkdir()
        self.note = self.vault / "active" / f"{TASK}.md"

    def write_note(self, text: str, state: str = "active") -> Path:
        path = self.vault / state / f"{TASK}.md"
        path.write_text(text, encoding="utf-8")
        self.note = path
        return path

    def lease(
        self,
        *,
        role: str = ROLE,
        session: str | None = SESSION,
        task_id: str = TASK,
        epoch: int = EPOCH,
        families: tuple[str, ...] = ("active", "epoch", "dispatch"),
    ) -> None:
        keys = [role] + ([f"{role}-{session}"] if session else [])
        for key in keys:
            if "active" in families:
                (self.cache / f"cc-active-task-{key}").write_text(f"{task_id}\n")
            if "epoch" in families:
                (self.cache / f"cc-claim-epoch-{key}").write_text(f"{epoch} {task_id}\n")
            if "dispatch" in families and session:
                write_claim_dispatch_binding(
                    self.cache,
                    key,
                    ClaimDispatchBinding.create(
                        task_id=task_id,
                        lane=role,
                        session_id=session,
                        claim_epoch=epoch,
                        dispatch_message_id=f"dispatch-{task_id}",
                        platform="codex",
                        mode="headless",
                        profile="ultra",
                        authority_case="CASE-TEST-001",
                        binding_hash="a" * 64,
                    ),
                )

    def cache_bytes(self) -> dict[str, bytes]:
        return {path.name: path.read_bytes() for path in sorted(self.cache.iterdir())}

    def release(self, witness: str, **kwargs):
        options = {
            "vault_root": self.vault,
            "cache_dir": self.cache,
            "transaction_root": self.transactions,
            "receipt_root": self.receipts,
            "lock_root": self.locks,
            "task_id": TASK,
            "witness_kind": witness,
            "releaser_role": "dev4",
            "releaser_session_id": "91af13c0-6a47-4f93-a5ef-9c14a8cb5954",
            "now": NOW,
        }
        options.update(kwargs)
        return release_claim_lease(**options)


@pytest.fixture(autouse=True)
def _isolated_note_locks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The note lock's default root derives from HAPAX_COORD_DIR; never touch the real one.
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))


def _snapshot(root: Path) -> dict[str, bytes]:
    # Lock files are exclusion infrastructure, created on first use; everything else is state.
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.relative_to(root).parts[0] not in {"locks", "coord"}
    }


def _wall(evidence: dict[str, object] | None = None, error: ClaimPublicationError | None = None):
    calls = []

    def verifier(incumbent, now):
        calls.append((incumbent, now))
        if error is not None:
            raise error
        return evidence or {"kind": "test-wall", "earliest_at": "2026-09-24T17:38:50Z"}

    verifier.calls = calls
    return verifier


# --- refusals without effect --------------------------------------------------------------


@pytest.mark.parametrize("witness", ["absent_pid", "age", "silence", "", "force"])
def test_unknown_witness_kind_refuses_without_effect(tmp_path: Path, witness: str) -> None:
    fixture = Fixture(tmp_path)
    fixture.write_note(_note())
    fixture.lease()
    before = _snapshot(tmp_path)
    with pytest.raises(ClaimPublicationError) as raised:
        fixture.release(witness)
    assert raised.value.reason_code == "claim_release_witness_unknown"
    assert _snapshot(tmp_path) == before


def test_self_yield_from_another_session_refuses_without_effect(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    fixture.write_note(_note())
    fixture.lease()
    before = _snapshot(tmp_path)
    with pytest.raises(ClaimPublicationError) as raised:
        fixture.release("self_yield", releaser_role=ROLE, releaser_session_id=OTHER_SESSION)
    assert raised.value.reason_code == "claim_release_witness_rejected"
    assert _snapshot(tmp_path) == before


def test_self_yield_by_another_role_refuses_without_effect(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    fixture.write_note(_note())
    fixture.lease()
    before = _snapshot(tmp_path)
    with pytest.raises(ClaimPublicationError) as raised:
        fixture.release("self_yield", releaser_role="dev4", releaser_session_id=SESSION)
    assert raised.value.reason_code == "claim_release_witness_rejected"
    assert _snapshot(tmp_path) == before


def test_note_not_assigned_to_a_holder_refuses(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    fixture.write_note(_note(status="offered", assigned_to="unassigned"))
    before = _snapshot(tmp_path)
    with pytest.raises(ClaimPublicationError) as raised:
        fixture.release("provider_wall", provider_wall_verifier=_wall())
    assert raised.value.reason_code == "claim_release_no_incumbent"
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("status", ["blocked", "offered", "parked"])
def test_unsupported_status_refuses(tmp_path: Path, status: str) -> None:
    fixture = Fixture(tmp_path)
    fixture.write_note(_note(status=status))
    fixture.lease()
    before = _snapshot(tmp_path)
    with pytest.raises(ClaimPublicationError) as raised:
        fixture.release("provider_wall", provider_wall_verifier=_wall())
    assert raised.value.reason_code == "claim_release_status_unsupported"
    assert _snapshot(tmp_path) == before


def test_two_incumbent_sessions_refuse_as_ambiguous(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    fixture.write_note(_note())
    fixture.lease()
    fixture.lease(session=OTHER_SESSION)
    before = _snapshot(tmp_path)
    with pytest.raises(ClaimPublicationError) as raised:
        fixture.release("provider_wall", provider_wall_verifier=_wall())
    assert raised.value.reason_code == "claim_release_incumbent_ambiguous"
    assert _snapshot(tmp_path) == before


def test_symlinked_sidecar_refuses_without_effect(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    fixture.write_note(_note())
    fixture.lease()
    target = tmp_path / "elsewhere"
    target.write_text(f"{TASK}\n")
    marker = fixture.cache / f"cc-active-task-{ROLE}-{SESSION}"
    marker.unlink()
    marker.symlink_to(target)
    before = _snapshot(tmp_path)
    with pytest.raises(ClaimPublicationError) as raised:
        fixture.release("provider_wall", provider_wall_verifier=_wall())
    assert raised.value.reason_code == "claim_release_sidecar_unsafe"
    assert _snapshot(tmp_path) == before
    assert marker.is_symlink()


def test_provider_wall_without_verifier_is_typed_unavailable(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    fixture.write_note(_note())
    fixture.lease()
    before = _snapshot(tmp_path)
    with pytest.raises(ClaimPublicationError) as raised:
        fixture.release("provider_wall")
    assert raised.value.reason_code == "claim_release_witness_verifier_unavailable"
    assert _snapshot(tmp_path) == before


def test_provider_wall_verifier_refusal_propagates_without_effect(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    fixture.write_note(_note())
    fixture.lease()
    before = _snapshot(tmp_path)
    refusal = ClaimPublicationError(
        "claim_release_wall_not_newer_than_last_turn", "wait for a newer provider wall"
    )
    with pytest.raises(ClaimPublicationError) as raised:
        fixture.release("provider_wall", provider_wall_verifier=_wall(error=refusal))
    assert raised.value.reason_code == "claim_release_wall_not_newer_than_last_turn"
    assert _snapshot(tmp_path) == before


def test_provider_wall_verifier_sees_the_exact_incumbent(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    fixture.write_note(_note())
    fixture.lease()
    verifier = _wall()
    fixture.release("provider_wall", provider_wall_verifier=verifier)
    ((incumbent, now),) = verifier.calls
    assert (incumbent.task_id, incumbent.role, incumbent.session_id, incumbent.claim_epoch) == (
        TASK,
        ROLE,
        SESSION,
        EPOCH,
    )
    assert now == NOW


def test_terminal_task_witness_refuses_an_active_task(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    fixture.write_note(_note())
    fixture.lease()
    before = _snapshot(tmp_path)
    with pytest.raises(ClaimPublicationError) as raised:
        fixture.release("terminal_task")
    assert raised.value.reason_code == "claim_release_witness_rejected"
    assert _snapshot(tmp_path) == before


def test_pending_publication_journal_blocks_release(tmp_path: Path, monkeypatch) -> None:
    fixture = Fixture(tmp_path)
    fixture.write_note(_note())
    fixture.lease()

    class _Hold:
        disposition = "hold"
        publication_id = "claim-pub-" + "b" * 64

    monkeypatch.setattr(sdlc_claim, "inspect_claim_publications", lambda **_: (_Hold(),))
    before = _snapshot(tmp_path)
    with pytest.raises(ClaimPublicationError) as raised:
        fixture.release("provider_wall", provider_wall_verifier=_wall())
    assert raised.value.reason_code == "claim_release_pending_publication"
    assert "claim-pub-" + "b" * 64 in (raised.value.detail or "")
    assert "--recover-claim-publications" in raised.value.repair_action
    assert _snapshot(tmp_path) == before


def test_release_waits_for_the_incumbent_role_lock(tmp_path: Path, monkeypatch) -> None:
    fixture = Fixture(tmp_path)
    fixture.write_note(_note())
    fixture.lease()
    monkeypatch.setattr(sdlc_claim, "_CLAIM_PUBLICATION_LOCK_TIMEOUT_SECONDS", 0.2)
    holding, done = threading.Event(), threading.Event()

    def incumbent_publishing() -> None:
        with sdlc_claim.claim_role_exclusion(ROLE, lock_root=fixture.locks):
            holding.set()
            done.wait(timeout=10)

    thread = threading.Thread(target=incumbent_publishing)
    thread.start()
    try:
        assert holding.wait(timeout=5)
        before = _snapshot(tmp_path)
        with pytest.raises(ClaimPublicationError):
            fixture.release("provider_wall", provider_wall_verifier=_wall())
        assert _snapshot(tmp_path) == before
    finally:
        done.set()
        thread.join(timeout=10)


# --- applied releases ----------------------------------------------------------------------


def test_provider_wall_release_archives_every_byte_and_reoffers(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    note_before = fixture.write_note(_note()).read_bytes()
    fixture.lease()
    # A foreign claim of the same role (another task) is retained untouched.
    (fixture.cache / "cc-claim-epoch-cx-walled-0b0b0b0b-1111-4222-8333-444455556666").write_text(
        "123 other-task\n"
    )
    # A prefix-neighbour role is never read as this role.
    (fixture.cache / "cc-active-task-cx-walled-extra").write_text(f"{TASK}\n")
    cache_before = fixture.cache_bytes()

    result = fixture.release("provider_wall", provider_wall_verifier=_wall())

    assert result.state == "applied"
    assert (result.incumbent_role, result.incumbent_session_id) == (ROLE, SESSION)
    removed = {name for name in cache_before if name not in fixture.cache_bytes()}
    assert removed == {
        f"cc-active-task-{ROLE}",
        f"cc-active-task-{ROLE}-{SESSION}",
        f"cc-claim-epoch-{ROLE}",
        f"cc-claim-epoch-{ROLE}-{SESSION}",
        f"cc-claim-dispatch-{ROLE}.json",
        f"cc-claim-dispatch-{ROLE}-{SESSION}.json",
    }
    assert set(result.archived) == removed
    for name in removed:
        assert (result.archive_dir / "sidecars" / name).read_bytes() == cache_before[name]
    assert (result.archive_dir / "note.before").read_bytes() == note_before
    text = fixture.note.read_text(encoding="utf-8")
    assert "status: offered" in text and "assigned_to: unassigned" in text
    assert f"governed release of {ROLE}" in text and result.release_id in text
    receipt = json.loads((result.archive_dir / "release.json").read_text(encoding="utf-8"))
    assert receipt["state"] == "applied"
    assert receipt["witness"]["kind"] == "provider_wall"
    assert receipt["note"]["before_sha256"] == hashlib.sha256(note_before).hexdigest()
    assert receipt["note"]["after_sha256"] == hashlib.sha256(fixture.note.read_bytes()).hexdigest()
    assert {item["name"]: item["sha256"] for item in receipt["sidecars"]} == {
        name: hashlib.sha256(cache_before[name]).hexdigest() for name in removed
    }


def test_ready_state_release_requires_a_successor_and_keeps_status(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    fixture.write_note(_note(status="pr_open"))
    fixture.lease()
    before = _snapshot(tmp_path)
    with pytest.raises(ClaimPublicationError) as raised:
        fixture.release("provider_wall", provider_wall_verifier=_wall())
    assert raised.value.reason_code == "claim_release_successor_required"
    assert _snapshot(tmp_path) == before

    result = fixture.release("provider_wall", provider_wall_verifier=_wall(), successor_role="dev4")
    text = fixture.note.read_text(encoding="utf-8")
    assert "status: pr_open" in text and "assigned_to: dev4" in text
    assert result.assigned_to_after == "dev4"


def test_self_yield_by_the_owning_session_releases(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    fixture.write_note(_note())
    fixture.lease()
    result = fixture.release("self_yield", releaser_role=ROLE, releaser_session_id=SESSION)
    assert result.state == "applied"
    assert not list(fixture.cache.glob(f"cc-*-{ROLE}*"))


def test_terminal_task_archives_epoch_only_residue_and_keeps_the_closed_note(
    tmp_path: Path,
) -> None:
    fixture = Fixture(tmp_path)
    closed = fixture.write_note(_note(status="done"), state="closed")
    note_before = closed.read_bytes()
    fixture.lease(families=("epoch",))
    result = fixture.release("terminal_task")
    assert closed.read_bytes() == note_before
    assert set(result.archived) == {f"cc-claim-epoch-{ROLE}", f"cc-claim-epoch-{ROLE}-{SESSION}"}
    assert not list(fixture.cache.glob("cc-claim-epoch-*"))


def test_operator_release_requires_an_exact_recorded_authorization(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    fixture.write_note(_note())
    fixture.lease()
    authority = fixture.vault / "authority.md"
    authority.write_text(
        "---\n"
        "kind: claim-release-authorization\n"
        f"task_id: {TASK}\n"
        "incumbent_role: someone-else\n"
        f"incumbent_session_id: {SESSION}\n"
        "authorized_by: operator\n"
        "authority: test dispatch\n"
        "---\n",
        encoding="utf-8",
    )
    before = _snapshot(tmp_path)
    with pytest.raises(ClaimPublicationError) as raised:
        fixture.release("operator_release", authority_ref=authority)
    assert raised.value.reason_code == "claim_release_authority_mismatch"
    assert _snapshot(tmp_path) == before

    authority.write_text(authority.read_text().replace("someone-else", ROLE), encoding="utf-8")
    result = fixture.release("operator_release", authority_ref=authority)
    receipt = json.loads((result.archive_dir / "release.json").read_text(encoding="utf-8"))
    assert (
        receipt["witness"]["evidence"]["authority_sha256"]
        == hashlib.sha256(authority.read_bytes()).hexdigest()
    )


def test_second_release_after_apply_refuses_without_effect(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    fixture.write_note(_note())
    fixture.lease()
    fixture.release("provider_wall", provider_wall_verifier=_wall())
    before = _snapshot(tmp_path)
    with pytest.raises(ClaimPublicationError) as raised:
        fixture.release("provider_wall", provider_wall_verifier=_wall())
    assert raised.value.reason_code == "claim_release_no_incumbent"
    assert _snapshot(tmp_path) == before


# --- crash and retry -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "boundary",
    [
        "intent_recorded",
        "sidecar_archived:0",
        "sidecar_archived:3",
        "sidecars_done",
        "note_written",
    ],
)
def test_crash_at_any_boundary_resumes_the_same_release(tmp_path: Path, boundary: str) -> None:
    fixture = Fixture(tmp_path)
    note_before = fixture.write_note(_note()).read_bytes()
    fixture.lease()
    cache_before = fixture.cache_bytes()

    def crash(point: str) -> None:
        if point == boundary:
            raise RuntimeError(f"simulated crash at {point}")

    with pytest.raises(RuntimeError):
        fixture.release("provider_wall", provider_wall_verifier=_wall(), _fault_hook=crash)
    # A retry (even with a witness that would now refuse) completes the started release
    # rather than leaving half state or starting a second one.
    refusal = ClaimPublicationError("claim_release_wall_lifted", "the wall has lifted")
    result = fixture.release("provider_wall", provider_wall_verifier=_wall(error=refusal))
    assert result.state == "resumed"
    archives = list((fixture.vault / "_lineage" / TASK).glob("governed-release-*"))
    assert archives == [result.archive_dir]
    for name in result.archived:
        assert (result.archive_dir / "sidecars" / name).read_bytes() == cache_before[name]
        assert not (fixture.cache / name).exists()
    assert (result.archive_dir / "note.before").read_bytes() == note_before
    assert "status: offered" in fixture.note.read_text(encoding="utf-8")
    receipt = json.loads((result.archive_dir / "release.json").read_text(encoding="utf-8"))
    assert receipt["state"] == "applied"


def test_pending_intent_whose_state_moved_on_refuses(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    fixture.write_note(_note())
    fixture.lease()

    def crash(point: str) -> None:
        if point == "sidecar_archived:0":
            raise RuntimeError("simulated crash")

    with pytest.raises(RuntimeError):
        fixture.release("provider_wall", provider_wall_verifier=_wall(), _fault_hook=crash)
    # Someone rewrote a not-yet-archived sidecar after the crash.
    remaining = sorted(fixture.cache.glob(f"cc-claim-epoch-{ROLE}*"))
    remaining[-1].write_text(f"{EPOCH + 1} {TASK}\n")
    before = _snapshot(tmp_path)
    with pytest.raises(ClaimPublicationError) as raised:
        fixture.release("provider_wall", provider_wall_verifier=_wall())
    assert raised.value.reason_code == "claim_release_pending_intent_conflict"
    assert _snapshot(tmp_path) == before
