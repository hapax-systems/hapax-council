from __future__ import annotations

import gc
import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

import shared.coord_projection as coord_projection
import shared.sdlc_claim as sdlc_claim
import shared.sdlc_close as sdlc_close
from shared.coord_event_log import CoordEvent, CoordEventLog, CoordWriter
from shared.coord_projection import (
    LifecycleTransitionError,
    recover_lifecycle_transactions,
)
from shared.relay_lifecycle import parse_relay_document, relay_values_are_retired
from shared.relay_mq import (
    CanonEchoReconciliation,
    CanonPositionEcho,
    ExpectedCanonEcho,
    ack_message,
    assess_canon_echo,
    build_canon_echo_envelope,
    consume_messages,
    load_dispatch_echo_expectation,
    parse_canon_echo,
    send_message,
)
from shared.relay_mq_envelope import Envelope
from shared.sdlc_claim import (
    ClaimPublicationIntent,
    inspect_claim_publications,
)
from shared.sdlc_close import CloseGateEvidence, TerminalCloseError, close_task
from shared.sdlc_task_store import (
    ClaimDispatchBinding,
    resolve_task_note,
)
from shared.session_context_canon import build_canon_bundle

_REAL_CLAIM_POSITION_RESOLVER = sdlc_close.resolve_claim_bound_canon_position
_REAL_ECHO_RECONCILER = sdlc_close.reconcile_canon_echo


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _write_private_history(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_bytes(payload)
    path.chmod(0o600)


def _materialize_legacy_claim_history(
    intent: ClaimPublicationIntent,
    cache: Path,
) -> None:
    """Create exact historical bytes for close compatibility without an effect API."""

    projections = sdlc_claim._projections(intent)
    publication_id = sdlc_claim.claim_publication_id(intent)
    for projection in projections:
        if projection.after is None:
            projection.path.unlink(missing_ok=True)
            continue
        projection.path.parent.mkdir(parents=True, exist_ok=True)
        projection.path.write_bytes(projection.after)
        assert projection.after_mode is not None
        projection.path.chmod(projection.after_mode)
    transaction_root = sdlc_claim._manifest_root(None, cache)
    transaction_root.mkdir(parents=True, exist_ok=True)
    transaction_root.chmod(0o700)
    transaction = transaction_root / publication_id
    transaction.mkdir()
    transaction.chmod(0o700)
    for index, projection in enumerate(projections):
        for label, content in (("before", projection.before), ("after", projection.after)):
            if content is not None:
                _write_private_history(transaction / f"{index:04d}.{label}", content)
    manifest = {
        **sdlc_claim._static_manifest(intent, projections, publication_id),
        "reason_code": None,
        "state": "applied",
    }
    _write_private_history(transaction / "manifest.json", _canonical_bytes(manifest) + b"\n")
    receipt = sdlc_claim.claim_publication_receipt_path(cache, intent.binding)
    _write_private_history(
        receipt,
        _canonical_bytes(sdlc_claim._receipt_record(intent, projections, publication_id)) + b"\n",
    )


@dataclass(frozen=True)
class CloseFixture:
    task_id: str
    lane: str
    session_id: str
    authority_case: str
    vault: Path
    cache: Path
    note: Path
    receipt: Path
    relay: Path
    relay_db: Path
    dispatch_ledger: Path
    event_log: CoordEventLog
    echo_message_id: str
    expected: ExpectedCanonEcho
    projected_echo: CanonPositionEcho


def _dispatch_record(
    source_message_id: str,
    *,
    task_id: str,
    lane: str,
    authority_case: str,
) -> dict[str, object]:
    bundle = build_canon_bundle()
    image = next(
        item for item in bundle.images if item.stage_token == "S10" and item.level.value == "pi0"
    )
    canon = {
        "canon_hash": bundle.canon_hash,
        "canon_version": bundle.canon_version,
        "image_hash": image.image_hash,
        "level": image.level.value,
        "payload_sha256": hashlib.sha256(image.rendered_payload.encode()).hexdigest(),
        "stage_token": "S10",
    }
    position_body = {
        "authority_case": authority_case,
        "declared_task_constraint_digest": "c" * 64,
        "effective_constraint_state": "unresolved_scope_chain",
        "lane": lane,
        "legal_successors": ["S11"],
        "stage_token": "S10",
        "task_id": task_id,
    }
    position_hash = _hash(position_body)
    position = {
        **position_body,
        "position_hash": position_hash,
        "position_ref": f"dispatch-position@sha256:{position_hash}",
    }
    binding_body = {
        "advisory_carriage": True,
        "canon": canon,
        "may_authorize": False,
        "position": position,
        "receipt_is_admission": False,
        "schema": "hapax.dispatch-canon-binding.v1",
    }
    binding_hash = _hash(binding_body)
    binding = {
        **binding_body,
        "binding_hash": binding_hash,
        "binding_ref": f"dispatch-canon-binding@sha256:{binding_hash}",
    }
    return {
        "event": "methodology_dispatch",
        "ok": True,
        "launched": True,
        "launch_returncode": 0,
        "launch_eligible": True,
        "durable_mq_dispatch_bound": True,
        "durable_mq_message_id": source_message_id,
        "may_authorize": False,
        "receipt_is_admission": False,
        "canon_binding": binding,
        "canon_binding_hash": binding_hash,
        "canon_binding_ref": binding["binding_ref"],
        "dispatch_position_hash": position_hash,
        "dispatch_position_ref": position["position_ref"],
    }


def _fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    echo_sender: str = "alpha",
    echo_session: str = "session-test",
    acceptance_receipt: bool = True,
    note_mode: int = 0o644,
) -> CloseFixture:
    task_id = "task-close"
    lane = "alpha"
    session_id = "session-test"
    authority_case = "CASE-CLOSE-001"
    vault = tmp_path / "vault"
    active = vault / "active"
    (vault / "closed").mkdir(parents=True)
    active.mkdir()
    cache = tmp_path / "cache"
    (cache / "relay").mkdir(parents=True)
    coord = tmp_path / "coord"
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HAPAX_COORD_DIR", str(coord))
    monkeypatch.setattr(coord_projection, "_LIFECYCLE_EFFECT_ACTIVATION", True)
    # Projection tests exercise the future admitted close effect. A separate
    # test proves the real ingress refuses legacy claim publications.
    monkeypatch.setattr(sdlc_close, "inspect_claim_publications", lambda **_kwargs: ())
    for key in (
        "HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF",
        "HAPAX_ARTIFACT_DISPOSITION_GATE_OFF",
        "HAPAX_CC_TASK_CLOSURE_GATE_OFF",
        "HAPAX_PR_MERGE_GATE_OFF",
    ):
        monkeypatch.delenv(key, raising=False)
    note = active / f"{task_id}.md"
    note.write_text(
        f"""---
type: cc-task
task_id: {task_id}
title: Close fixture
status: offered
assigned_to: unassigned
authority_case: {authority_case}
parent_spec: /tmp/close-parent-spec.md
stage: S10
quality_floor: frontier_review_required
claimed_at: 2020-01-01T00:00:00Z
claimable: true
completed_at:
updated_at: 2026-07-11T00:00:00Z
pr:
implementation_authorized: true
source_mutation_authorized: true
docs_mutation_authorized: false
runtime_mutation_authorized: false
vault_mutation_authorized: true
release_authorized: false
public_current: false
axiom_mutation_authorized: false
---

# Close fixture

## Acceptance criteria
- [x] exact close position

## Session log
""",
        encoding="utf-8",
    )
    note.chmod(note_mode)
    receipt = active / f"{task_id}.acceptance.yaml"
    if acceptance_receipt:
        receipt.write_text(
            yaml.safe_dump(
                {
                    "acceptor": "operator",
                    "verdict": "accepted",
                    "timestamp": "2026-07-11T15:00:00Z",
                    "artifact": "task:close-fixture",
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    relay = cache / "relay" / f"{lane}.yaml"
    relay.write_text(
        f"role: {lane}\nsession_id: {session_id}\nstatus: active\n"
        f"current_claim: {task_id}\nworktree: /tmp/worktree\n",
        encoding="utf-8",
    )
    relay_db = cache / "relay" / "messages.db"
    source_message_id = "dispatch-close-source"
    send_message(
        relay_db,
        Envelope(
            message_id=source_message_id,
            sender="hapax-coordinator",
            message_type="dispatch",
            priority=0,
            subject=task_id,
            authority_case=authority_case,
            authority_item=task_id,
            recipients_spec=lane,
            payload=json.dumps({"task_id": task_id}),
        ),
    )
    consume_messages(relay_db, lane)
    ack_message(relay_db, source_message_id, lane, "accepted")
    ack_message(relay_db, source_message_id, lane, "processed")
    dispatch_ledger = tmp_path / "methodology-dispatch.jsonl"
    dispatch_record = _dispatch_record(
        source_message_id,
        task_id=task_id,
        lane=lane,
        authority_case=authority_case,
    )
    dispatch_ledger.write_text(json.dumps(dispatch_record, sort_keys=True) + "\n", encoding="utf-8")
    expected = load_dispatch_echo_expectation(
        dispatch_ledger,
        source_message_id=source_message_id,
        task_id=task_id,
        lane=lane,
    )
    # These projection/atomicity tests exercise the future admitted close body.
    # The real ingress remains fail-closed until legacy claims are migrated to
    # applied ownership plus authenticated outcome replay.
    monkeypatch.setattr(
        sdlc_close,
        "resolve_claim_bound_canon_position",
        lambda *_args, **_kwargs: expected,
    )
    epoch = 123
    idempotency_key = "coord-dispatch-close-fixture"
    binding = ClaimDispatchBinding.create(
        task_id=task_id,
        lane=lane,
        session_id=session_id,
        claim_epoch=epoch,
        dispatch_message_id=source_message_id,
        platform="codex",
        mode="visible",
        profile="default",
        authority_case=authority_case,
        binding_hash=expected.binding_hash,
        coord_dispatch_idempotency_key=idempotency_key,
    )
    task_snapshot = resolve_task_note(vault, task_id, state="active")
    claim_text = task_snapshot.content.decode("utf-8")
    claim_text = claim_text.replace("status: offered", "status: claimed", 1)
    claim_text = claim_text.replace("assigned_to: unassigned", f"assigned_to: {lane}", 1)
    claim_intent = ClaimPublicationIntent.create(
        task=task_snapshot,
        cache_dir=cache,
        note_after=claim_text.encode("utf-8"),
        binding=binding,
    )
    _materialize_legacy_claim_history(claim_intent, cache)
    note.write_text(
        note.read_text(encoding="utf-8").replace("status: claimed", "status: in_progress", 1),
        encoding="utf-8",
    )
    event_log = CoordEventLog(
        db_path=coord / "ledger.db",
        jsonl_path=coord / "ledger.jsonl",
        spool_dir=coord / "spool",
    )
    event_log.append(
        CoordEvent(
            event_id="dispatch-close-launch-succeeded",
            timestamp=datetime.now(UTC).isoformat(),
            event_type="coord_dispatch.launch_succeeded",
            actor=lane,
            subject=task_id,
            authority_case=authority_case,
            payload={
                "idempotency_key": idempotency_key,
                "message_id": source_message_id,
                "mode": "visible",
                "outcome": "succeeded",
                "platform": "codex",
                "profile": "default",
                "returncode": 0,
            },
        ),
        writer=CoordWriter.daemon("test-dispatch"),
    )
    echo = build_canon_echo_envelope(
        expected,
        sender=echo_sender,
        session_id=echo_session,
        observed_at=datetime.now(UTC),
    )
    projected_echo = parse_canon_echo(echo)
    send_message(relay_db, echo)
    return CloseFixture(
        task_id=task_id,
        lane=lane,
        session_id=session_id,
        authority_case=authority_case,
        vault=vault,
        cache=cache,
        note=note,
        receipt=receipt,
        relay=relay,
        relay_db=relay_db,
        dispatch_ledger=dispatch_ledger,
        event_log=event_log,
        echo_message_id=echo.message_id,
        expected=expected,
        projected_echo=projected_echo,
    )


def _close(fixture: CloseFixture, *, final_status: str = "done"):
    return close_task(
        fixture.task_id,
        final_status=final_status,
        actor=fixture.lane,
        session_id=fixture.session_id,
        vault_root=fixture.vault,
        cache_dir=fixture.cache,
        relay_db=fixture.relay_db,
        dispatch_ledger=fixture.dispatch_ledger,
        event_log=fixture.event_log,
    )


def _inject_trusted_echo_projection(
    fixture: CloseFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reconcile(
        db_path: Path,
        expected: ExpectedCanonEcho,
        *,
        rendered_payload: str,
        now: datetime,
        expected_sender: str | None = None,
        expected_session_id: str | None = None,
    ) -> CanonEchoReconciliation:
        assert db_path == fixture.relay_db
        assert expected == fixture.expected
        assert (
            hashlib.sha256(rendered_payload.encode()).hexdigest() == expected.canon_payload_sha256
        )
        assessment = assess_canon_echo(
            expected,
            fixture.projected_echo,
            now=now,
            expected_sender=expected_sender,
            expected_session_id=expected_session_id,
        )
        assert assessment.status == "matched"
        return CanonEchoReconciliation(
            "grounded",
            "canon_echo_matched",
            echo_message_id=assessment.message_id,
        )

    def require(
        db_path: Path,
        expected: ExpectedCanonEcho,
        *,
        echo_message_id: str,
        now: datetime,
        expected_sender: str | None = None,
        expected_session_id: str | None = None,
    ) -> CanonPositionEcho:
        assert db_path == fixture.relay_db
        assert expected == fixture.expected
        assert echo_message_id == fixture.projected_echo.envelope.message_id
        assessment = assess_canon_echo(
            expected,
            fixture.projected_echo,
            now=now,
            expected_sender=expected_sender,
            expected_session_id=expected_session_id,
        )
        assert assessment.status == "matched"
        return fixture.projected_echo

    monkeypatch.setattr(sdlc_close, "reconcile_canon_echo", reconcile)
    monkeypatch.setattr(sdlc_close, "require_matching_canon_echo", require)


def test_done_gate_children_use_isolated_project_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    snapshot = resolve_task_note(fixture.vault, fixture.task_id, state="active")
    monkeypatch.setenv("PYTHONPATH", "/tmp/ambient-pythonpath")
    monkeypatch.setenv("PYTHONHOME", "/tmp/ambient-pythonhome")
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(command, *, env, **_kwargs):
        calls.append((list(command), dict(env)))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(sdlc_close.subprocess, "run", fake_run)

    evidence = sdlc_close._default_done_gate_runner(
        snapshot,
        "done",
        "4483",
        True,
        None,
    )

    assert len(evidence) == 3
    assert len(calls) == 2
    for command, environment in calls:
        assert command[:2] == [sdlc_close.sys.executable, "-I"]
        assert "PYTHONPATH" not in environment
        assert "PYTHONHOME" not in environment


def test_done_close_projects_every_terminal_surface_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    _inject_trusted_echo_projection(fixture, monkeypatch)

    result = _close(fixture)

    closed_note = fixture.vault / "closed" / fixture.note.name
    closed_receipt = fixture.vault / "closed" / fixture.receipt.name
    assert result.applied_event_id.endswith(".applied")
    assert not fixture.note.exists()
    assert not fixture.receipt.exists()
    assert "stage: S11" in closed_note.read_text(encoding="utf-8")
    assert closed_receipt.is_file()
    for key in (fixture.lane, f"{fixture.lane}-{fixture.session_id}"):
        assert not (fixture.cache / f"cc-active-task-{key}").exists()
        assert not (fixture.cache / f"cc-claim-epoch-{key}").exists()
        assert not (fixture.cache / f"cc-claim-dispatch-{key}.json").exists()
    relay = parse_relay_document(fixture.relay.read_text(encoding="utf-8"))
    assert relay["status"] == "idle"
    assert relay["current_claim"] is None
    assert relay["worktree"] == "/tmp/worktree"
    assert not relay_values_are_retired([str(relay["status"])])
    admission_receipts = list(
        fixture.event_log.db_path.parent.glob("terminal-close-admission-*.json")
    )
    assert len(admission_receipts) == 1
    admission = json.loads(admission_receipts[0].read_text(encoding="ascii"))
    assert admission["schema"] == "hapax.terminal-close-admission.v2"
    assert admission["task_id"] == fixture.task_id
    assert admission["gate_evidence"]
    proof = admission["claim_publication_proof"]
    assert [item["kind"] for item in proof] == ["receipt", "manifest"]
    assert all(item["mode"] == 0o600 for item in proof)
    assert all(Path(item["path"]).read_bytes() for item in proof)
    assert all(
        hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest() == item["sha256"]
        for item in proof
    )
    assert [event.event_type for event in fixture.event_log.replay().events][-2:] == [
        "sdlc.transition_prepared",
        "sdlc.transition_applied",
    ]


def test_terminal_close_real_ingress_holds_legacy_claim_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        sdlc_close,
        "inspect_claim_publications",
        inspect_claim_publications,
    )

    with pytest.raises(TerminalCloseError) as raised:
        _close(fixture)

    assert raised.value.reason_code == "terminal_close_claim_inspection_hold"
    assert "legacy_claim_publication_consumption_required" in str(raised.value)


def test_terminal_close_real_ingress_holds_pre_gate0_claim_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        sdlc_close,
        "resolve_claim_bound_canon_position",
        _REAL_CLAIM_POSITION_RESOLVER,
    )

    with pytest.raises(TerminalCloseError) as raised:
        _close(fixture)

    assert raised.value.reason_code == "canon_pre_gate0_claim_migration_required"
    assert fixture.note.is_file()
    assert not (fixture.vault / "closed" / fixture.note.name).exists()


def test_terminal_close_recovers_complete_postimage_after_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    _inject_trusted_echo_projection(fixture, monkeypatch)
    original = sdlc_close._execute_terminal_close_transition

    def crash_before_applied(**kwargs: object):
        def fail(phase: str, _index: int | None) -> None:
            if phase == "before_applied":
                raise SystemExit("simulated process death")

        return original(**kwargs, failure_hook=fail)  # type: ignore[arg-type]

    monkeypatch.setattr(sdlc_close, "_execute_terminal_close_transition", crash_before_applied)
    with pytest.raises(SystemExit, match="simulated process death"):
        _close(fixture)

    assert not fixture.note.exists()
    results = recover_lifecycle_transactions(event_log=fixture.event_log, task_id=fixture.task_id)
    assert any(item.state == "applied" for item in results)
    assert (fixture.vault / "closed" / fixture.note.name).is_file()
    assert [event.event_type for event in fixture.event_log.replay().events][-2:] == [
        "sdlc.transition_prepared",
        "sdlc.transition_applied",
    ]


def test_terminal_close_refuses_racing_destination_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    _inject_trusted_echo_projection(fixture, monkeypatch)
    destination = fixture.vault / "closed" / fixture.note.name
    original = sdlc_close._execute_terminal_close_transition

    def create_destination_before_cas(**kwargs: object):
        destination.write_bytes(b"third-party\n")
        return original(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        sdlc_close,
        "_execute_terminal_close_transition",
        create_destination_before_cas,
    )

    with pytest.raises(LifecycleTransitionError, match="transition_precondition_changed"):
        _close(fixture)

    assert destination.read_bytes() == b"third-party\n"
    assert fixture.note.is_file()


def test_terminal_close_updates_every_matching_relay_alias_and_preserves_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch, note_mode=0o640)
    _inject_trusted_echo_projection(fixture, monkeypatch)
    fixture.receipt.chmod(0o600)
    alias = fixture.cache / "relay" / f"{fixture.lane}-status.yaml"
    alias.write_bytes(fixture.relay.read_bytes())

    _close(fixture)

    for relay_path in (fixture.relay, alias):
        relay = parse_relay_document(relay_path.read_text(encoding="utf-8"))
        assert relay["status"] == "idle"
        assert relay["current_claim"] is None
    assert (fixture.vault / "closed" / fixture.note.name).stat().st_mode & 0o777 == 0o640
    assert (fixture.vault / "closed" / fixture.receipt.name).stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("final_status", ["withdrawn", "superseded"])
def test_non_done_close_requires_operator_disposition_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    final_status: str,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch, acceptance_receipt=False)

    with pytest.raises(
        TerminalCloseError,
        match="terminal_close_operator_disposition_receipt_required",
    ):
        _close(fixture, final_status=final_status)

    assert fixture.note.is_file()
    assert not list(fixture.event_log.db_path.parent.glob("terminal-close-admission-*.json"))


def test_terminal_close_live_relay_requires_projection_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch, echo_session="copied-session")
    gc.collect()
    relay_before = {
        path.name: path.read_bytes() for path in fixture.relay_db.parent.iterdir() if path.is_file()
    }
    note_before = fixture.note.read_bytes()
    events_before = fixture.event_log.replay().events

    with pytest.raises(TerminalCloseError) as raised:
        _close(fixture)

    assert raised.value.reason_code == "canon_echo_projection_required"
    assert fixture.note.read_bytes() == note_before
    assert {
        path.name: path.read_bytes() for path in fixture.relay_db.parent.iterdir() if path.is_file()
    } == relay_before
    assert fixture.event_log.replay().events == events_before
    assert not (fixture.vault / "closed" / fixture.note.name).exists()
    assert not list(fixture.event_log.db_path.parent.glob("terminal-close-admission-*.json"))


def test_terminal_close_refuses_non_claimed_task_or_wrong_relay_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    fixture.note.write_text(
        fixture.note.read_text(encoding="utf-8").replace(
            "status: in_progress",
            "status: offered",
        ),
        encoding="utf-8",
    )
    with pytest.raises(TerminalCloseError, match="terminal_close_task_identity_mismatch"):
        _close(fixture)

    fixture = _fixture(tmp_path / "wrong-relay", monkeypatch)
    fixture.relay.write_text(
        fixture.relay.read_text(encoding="utf-8").replace(
            f"session_id: {fixture.session_id}",
            "session_id: different-session",
        ),
        encoding="utf-8",
    )
    with pytest.raises(TerminalCloseError, match="terminal_close_relay_claim_mismatch"):
        _close(fixture)


def test_receipt_changed_by_gate_is_refused_before_echo_or_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)

    def racing_gate(*_args: object, **_kwargs: object) -> tuple[CloseGateEvidence, ...]:
        fixture.receipt.write_text("verdict: rejected\n", encoding="utf-8")
        return (
            CloseGateEvidence(
                gate="test-race",
                outcome="pass",
                task_id=fixture.task_id,
                note_sha256=hashlib.sha256(fixture.note.read_bytes()).hexdigest(),
                authority_case=fixture.authority_case,
                final_status="done",
                observed_at=datetime.now(UTC).isoformat(),
            ),
        )

    monkeypatch.setattr("shared.sdlc_close._default_done_gate_runner", racing_gate)

    with pytest.raises(TerminalCloseError, match="terminal_close_preflight_receipt_drift"):
        _close(fixture)

    assert fixture.note.is_file()
    assert not (fixture.vault / "closed" / fixture.note.name).exists()


def test_raw_debt_override_refuses_without_touching_state(tmp_path: Path) -> None:
    with pytest.raises(TerminalCloseError, match="terminal_close_debt_override_requires_receipt"):
        close_task(
            "task-close",
            actor="alpha",
            session_id="session-test",
            debt_reason="skip the gate",
            vault_root=tmp_path / "vault",
            cache_dir=tmp_path / "cache",
        )
    assert not list(tmp_path.rglob("*"))
