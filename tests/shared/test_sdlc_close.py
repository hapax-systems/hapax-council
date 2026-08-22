from __future__ import annotations

import gc
import hashlib
import json
import os
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
    ledger = tmp_path / "artifact-ledger.yaml"
    ledger.write_text(
        "- artifact_id: fixture-unrelated\n"
        "  class: receipt\n"
        "  disposition: receipt_only\n"
        "  task_id: other-task\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HAPAX_ARTIFACT_LEDGER_PATH", str(ledger))
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
        False,
        None,
    )

    assert len(evidence) == 4
    assert len(calls) == 3
    assert any("cc-task-closure-check.py" in part for command, _env in calls for part in command)
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


def _gate0b_journal(home: Path, *, digest: str = "a" * 64) -> Path:
    from shared.gate0b_claim_publication_install import default_claim_publication_roots

    root = Path(default_claim_publication_roots(home=home).claim_transaction_root)
    journal = root / f"claim-pub-{digest}"
    journal.mkdir(parents=True)
    journal.chmod(0o700)
    (journal / "manifest.json").write_bytes(b"{}\n")
    (journal / "manifest.json").chmod(0o600)
    return root


class _LifecycleComplete:
    scope_complete = True
    reason_codes: tuple[str, ...] = ()


def _probe_close_observation_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    home = tmp_path / "home"
    cache = tmp_path / "cache"
    vault = tmp_path / "vault"
    monkeypatch.setenv("HOME", str(home))
    recorded: dict[str, object] = {}

    def inspect_spy(**kwargs: object) -> tuple[object, ...]:
        recorded["inspect"] = kwargs
        return ()

    def resolve_spy(**kwargs: object) -> object:
        recorded["resolve"] = kwargs
        raise sdlc_claim.ClaimPublicationError("probe_resolve", "probe", "probe")

    monkeypatch.setattr(
        sdlc_close, "inspect_lifecycle_transactions", lambda **_: _LifecycleComplete()
    )
    monkeypatch.setattr(sdlc_close, "inspect_claim_publications", inspect_spy)
    monkeypatch.setattr(sdlc_close, "resolve_applied_claim_publication", resolve_spy)
    with pytest.raises(TerminalCloseError) as raised:
        close_task(
            "task-observe-root",
            actor="alpha",
            session_id="session-observe",
            vault_root=vault,
            cache_dir=cache,
        )
    recorded["reason"] = raised.value.reason_code
    recorded["cache"] = cache
    recorded["home"] = home
    return recorded


def test_close_task_observes_gate0b_journal_root_when_admitted_journal_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HAPAX_GATE0B_CLAIM_PUBLICATION_OFF", raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    gate0b = _gate0b_journal(home)
    recorded = _probe_close_observation_roots(tmp_path, monkeypatch)
    inspect_kwargs = recorded["inspect"]
    resolve_kwargs = recorded["resolve"]
    assert recorded["reason"] == "probe_resolve"
    assert inspect_kwargs["transaction_root"] == gate0b
    assert resolve_kwargs["transaction_root"] == gate0b
    assert inspect_kwargs["cache_dir"] == recorded["cache"]


def test_close_task_observes_cache_journal_root_when_gate0b_has_no_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HAPAX_GATE0B_CLAIM_PUBLICATION_OFF", raising=False)
    recorded = _probe_close_observation_roots(tmp_path, monkeypatch)
    cache = recorded["cache"]
    inspect_kwargs = recorded["inspect"]
    resolve_kwargs = recorded["resolve"]
    assert recorded["reason"] == "probe_resolve"
    assert inspect_kwargs["transaction_root"] == cache / "claim-publications"
    assert resolve_kwargs["transaction_root"] == cache / "claim-publications"


def test_close_task_killswitch_observes_cache_journal_root_even_with_gate0b_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HAPAX_GATE0B_CLAIM_PUBLICATION_OFF", "1")
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    _gate0b_journal(home, digest="c" * 64)
    recorded = _probe_close_observation_roots(tmp_path, monkeypatch)
    cache = recorded["cache"]
    inspect_kwargs = recorded["inspect"]
    resolve_kwargs = recorded["resolve"]
    assert inspect_kwargs["transaction_root"] == cache / "claim-publications"
    assert resolve_kwargs["transaction_root"] == cache / "claim-publications"
    assert recorded["reason"] in {"probe_resolve", "task_note_not_found"}


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


def test_terminal_close_creates_missing_closed_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    _inject_trusted_echo_projection(fixture, monkeypatch)
    closed_dir = fixture.vault / "closed"
    for child in closed_dir.iterdir():
        child.unlink()
    closed_dir.rmdir()

    result = _close(fixture)

    assert result.applied_event_id.endswith(".applied")
    assert (fixture.vault / "closed" / fixture.note.name).is_file()


def test_terminal_close_applies_when_lifecycle_effects_are_default_deny(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    _inject_trusted_echo_projection(fixture, monkeypatch)
    monkeypatch.setattr(coord_projection, "_LIFECYCLE_EFFECT_ACTIVATION", False)

    result = _close(fixture)

    assert result.applied_event_id.endswith(".applied")
    assert (fixture.vault / "closed" / fixture.note.name).is_file()


def test_retroactive_done_gate_skips_paperwork_and_child_checkers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch, acceptance_receipt=False)
    snapshot = resolve_task_note(fixture.vault, fixture.task_id, state="active")
    calls: list[list[str]] = []

    def fake_run(command, *, env, **_kwargs):
        calls.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(sdlc_close.subprocess, "run", fake_run)

    evidence = sdlc_close._default_done_gate_runner(
        snapshot,
        "done",
        "4483",
        True,
        None,
    )

    assert [(item.gate, item.outcome) for item in evidence] == [
        ("acceptance-criteria", "skipped_retroactive"),
        ("acceptance-receipt", "skipped_retroactive"),
        ("artifact-disposition", "skipped_retroactive"),
        ("pr-merge", "pass"),
    ]
    assert evidence[0].command == ("cc-close", "--retroactive", "--pr", "4483")
    assert evidence[0].reason_code == "rec_1_retroactive_merge_is_evidence"
    assert evidence[0].authority_ref == ""
    assert len(calls) == 1
    assert calls[0][-3:] == [str(snapshot.path), "--pr", "4483"]
    assert all("artifact-disposition" not in part for cmd in calls for part in cmd)


def test_missing_relay_directory_is_named_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    _inject_trusted_echo_projection(fixture, monkeypatch)
    relay_dir = fixture.cache / "relay"
    for path in relay_dir.iterdir():
        path.unlink()
    relay_dir.rmdir()

    with pytest.raises(TerminalCloseError) as raised:
        _close(fixture)

    assert raised.value.reason_code == "terminal_close_relay_directory_missing"
    assert fixture.note.is_file()


def test_non_retroactive_honors_acceptance_receipt_gate_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch, acceptance_receipt=False)
    snapshot = resolve_task_note(fixture.vault, fixture.task_id, state="active")
    monkeypatch.setenv("HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF", "1")
    monkeypatch.setattr(
        sdlc_close.subprocess,
        "run",
        lambda command, *, env, **_kwargs: subprocess.CompletedProcess(
            command, 0, stdout="", stderr=""
        ),
    )

    evidence = sdlc_close._default_done_gate_runner(
        snapshot,
        "done",
        "4483",
        False,
        None,
    )

    assert evidence[0].gate == "task-close-internal"
    assert evidence[0].outcome == "pass"


def test_retroactive_done_gate_refuses_without_merged_pr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch, acceptance_receipt=False)
    snapshot = resolve_task_note(fixture.vault, fixture.task_id, state="active")

    with pytest.raises(TerminalCloseError) as raised:
        sdlc_close._default_done_gate_runner(
            snapshot,
            "done",
            "",
            True,
            None,
        )

    assert raised.value.reason_code == "terminal_close_done_gate_refused"
    assert raised.value.detail == "retroactive_merge_evidence_missing"


def test_retroactive_done_gate_refuses_when_merge_checker_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch, acceptance_receipt=False)
    snapshot = resolve_task_note(fixture.vault, fixture.task_id, state="active")

    def fake_run(command, *, env, **_kwargs):
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="PR is OPEN")

    monkeypatch.setattr(sdlc_close.subprocess, "run", fake_run)

    with pytest.raises(TerminalCloseError) as raised:
        sdlc_close._default_done_gate_runner(
            snapshot,
            "done",
            "4483",
            True,
            None,
        )

    assert raised.value.reason_code == "terminal_close_pr-merge_refused"
    assert "PR is OPEN" in (raised.value.detail or "")


def test_debt_reason_is_forwarded_to_disposition_checker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    snapshot = resolve_task_note(fixture.vault, fixture.task_id, state="active")
    calls: list[list[str]] = []

    def fake_run(command, *, env, **_kwargs):
        calls.append(list(command))
        target = Path(command[3])
        if command[-2:] == ["--debt", "service outage"]:
            target.write_bytes(target.read_bytes() + b"\n# debt-applied\n")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(sdlc_close.subprocess, "run", fake_run)

    sdlc_close._default_done_gate_runner(
        snapshot,
        "done",
        "4483",
        False,
        "service outage",
    )

    disposition = [cmd for cmd in calls if any("artifact-disposition" in part for part in cmd)]
    assert len(disposition) == 1
    assert disposition[0][-2:] == ["--debt", "service outage"]
    assert disposition[0][3] != str(snapshot.path)
    assert b"debt-applied" not in snapshot.path.read_bytes()
    cookie = snapshot.path.with_name(f".{snapshot.path.name}.close-invocation.{os.getpid()}")
    assert cookie.is_file()
    invocation = cookie.read_text(encoding="utf-8").strip()
    after = snapshot.path.with_name(
        f".{snapshot.path.name}.close-after.{snapshot.sha256[:12]}.{invocation}"
    )
    assert after.is_file()
    assert b"debt-applied" in after.read_bytes()


def test_disposition_debt_is_copied_back_to_the_live_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    ledger = Path(os.environ["HAPAX_ARTIFACT_LEDGER_PATH"])
    ledger.write_text(
        "- artifact_id: fixture-unrelated\n"
        "  class: receipt\n"
        "  disposition: receipt_only\n"
        "  task_id: other-task\n"
        "- artifact_id: close-receipt\n"
        "  class: receipt\n"
        "  disposition: produced\n"
        "  task_id: task-close\n",
        encoding="utf-8",
    )
    snapshot = resolve_task_note(fixture.vault, fixture.task_id, state="active")
    real_run = subprocess.run

    def fake_run(command, *, env, **kwargs):
        if any("cc-task-artifact-disposition-check.py" in part for part in command):
            return real_run(command, env=env, **kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(sdlc_close.subprocess, "run", fake_run)

    sdlc_close._default_done_gate_runner(snapshot, "done", "4483", False, None)

    live = yaml.safe_load(ledger.read_text(encoding="utf-8"))
    close_rows = [row for row in live if row.get("task_id") == "task-close"]
    assert len(close_rows) == 1
    assert close_rows[0].get("debt") is not None
    leftovers = list(snapshot.path.parent.glob("*.ledger.yaml"))
    assert leftovers == []


def test_disposition_gate_off_isolates_missing_global_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    monkeypatch.delenv("HAPAX_ARTIFACT_LEDGER_PATH", raising=False)
    monkeypatch.setenv("HAPAX_ARTIFACT_DISPOSITION_GATE_OFF", "1")
    snapshot = resolve_task_note(fixture.vault, fixture.task_id, state="active")
    captured: list[dict[str, str]] = []

    def fake_run(command, *, env, **_kwargs):
        captured.append(dict(env))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(sdlc_close.subprocess, "run", fake_run)

    sdlc_close._default_done_gate_runner(snapshot, "done", "4483", False, None)

    default = Path.home() / ".cache" / "hapax" / "document-pipeline" / "artifact-ledger.yaml"
    assert captured
    for environment in captured:
        isolated = environment.get("HAPAX_ARTIFACT_LEDGER_PATH", "")
        assert isolated
        assert isolated != str(default)
        assert isolated.endswith(".ledger.yaml")
    assert not default.exists()


def test_expired_claim_admission_is_refused() -> None:
    class _Expired:
        valid_until = "2020-01-01T00:00:00Z"

    with pytest.raises(TerminalCloseError) as raised:
        sdlc_close._require_current_claim_admission(_Expired())

    assert raised.value.reason_code == "terminal_close_claim_admission_expired"


def test_current_claim_admission_is_accepted() -> None:
    class _Current:
        valid_until = "2099-01-01T00:00:00Z"

    sdlc_close._require_current_claim_admission(_Current())


def test_retroactive_strips_only_merge_gate_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch, acceptance_receipt=False)
    snapshot = resolve_task_note(fixture.vault, fixture.task_id, state="active")
    monkeypatch.setenv("HAPAX_PR_MERGE_GATE_OFF", "1")
    monkeypatch.setenv("HAPAX_ARTIFACT_DISPOSITION_GATE_OFF", "1")
    captured: list[dict[str, str]] = []

    def fake_run(command, *, env, **_kwargs):
        captured.append(dict(env))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(sdlc_close.subprocess, "run", fake_run)

    sdlc_close._default_done_gate_runner(snapshot, "done", "4483", True, None)

    assert captured
    assert "HAPAX_PR_MERGE_GATE_OFF" not in captured[0]
    assert captured[0].get("HAPAX_ARTIFACT_DISPOSITION_GATE_OFF") == "1"


def test_disposition_fail_open_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    snapshot = resolve_task_note(fixture.vault, fixture.task_id, state="active")

    def fake_run(command, *, env, **_kwargs):
        stderr = ""
        if any("artifact-disposition" in part for part in command):
            stderr = "warning: artifact ledger malformed (YAML parse error), failing open"
        return subprocess.CompletedProcess(command, 0, stdout="", stderr=stderr)

    monkeypatch.setattr(sdlc_close.subprocess, "run", fake_run)

    with pytest.raises(TerminalCloseError) as raised:
        sdlc_close._default_done_gate_runner(snapshot, "done", "4483", False, None)

    assert raised.value.reason_code == "terminal_close_artifact_disposition_refused"


def test_non_retroactive_preserves_disposition_bypass_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    snapshot = resolve_task_note(fixture.vault, fixture.task_id, state="active")
    monkeypatch.setenv("HAPAX_ARTIFACT_DISPOSITION_GATE_OFF", "1")
    monkeypatch.setenv("HAPAX_PR_MERGE_GATE_OFF", "1")
    captured: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(command, *, env, **_kwargs):
        captured.append((list(command), dict(env)))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(sdlc_close.subprocess, "run", fake_run)

    evidence = sdlc_close._default_done_gate_runner(snapshot, "done", "4483", False, None)

    assert captured
    for _command, environment in captured:
        assert environment.get("HAPAX_ARTIFACT_DISPOSITION_GATE_OFF") == "1"
        assert environment.get("HAPAX_PR_MERGE_GATE_OFF") == "1"
    assert any(
        item.gate == "artifact-disposition" and item.outcome == "not_applicable"
        for item in evidence
    )


def test_non_retroactive_done_gate_still_requires_acceptance_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch, acceptance_receipt=False)
    snapshot = resolve_task_note(fixture.vault, fixture.task_id, state="active")

    with pytest.raises(TerminalCloseError) as raised:
        sdlc_close._default_done_gate_runner(
            snapshot,
            "done",
            "4483",
            False,
            None,
        )

    assert raised.value.reason_code == "terminal_close_done_gate_refused"
    assert "missing_acceptance_receipt" in (raised.value.detail or "")


def test_retroactive_close_skips_premerge_paperwork_gates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch, acceptance_receipt=False)
    _inject_trusted_echo_projection(fixture, monkeypatch)
    monkeypatch.setattr(
        sdlc_close.subprocess,
        "run",
        lambda command, *, env, **_kwargs: subprocess.CompletedProcess(
            command, 0, stdout="", stderr=""
        ),
    )

    result = close_task(
        fixture.task_id,
        final_status="done",
        actor="watcher",
        session_id="",
        pr="4483",
        retroactive=True,
        vault_root=fixture.vault,
        cache_dir=fixture.cache,
        relay_db=fixture.relay_db,
        dispatch_ledger=fixture.dispatch_ledger,
        event_log=fixture.event_log,
    )

    assert result.applied_event_id.endswith(".applied")
    assert (fixture.vault / "closed" / fixture.note.name).is_file()


def test_retroactive_watcher_binds_owning_claim_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    _inject_trusted_echo_projection(fixture, monkeypatch)
    monkeypatch.setattr(
        sdlc_close.subprocess,
        "run",
        lambda command, *, env, **_kwargs: subprocess.CompletedProcess(
            command, 0, stdout="", stderr=""
        ),
    )

    result = close_task(
        fixture.task_id,
        final_status="done",
        actor="watcher",
        session_id="",
        pr="4483",
        retroactive=True,
        vault_root=fixture.vault,
        cache_dir=fixture.cache,
        relay_db=fixture.relay_db,
        dispatch_ledger=fixture.dispatch_ledger,
        event_log=fixture.event_log,
    )

    assert result.applied_event_id.endswith(".applied")
    assert (fixture.vault / "closed" / fixture.note.name).is_file()


def test_publication_owned_echo_receipt_is_not_an_mq_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from shared.coord_projection import _echo_receipt_ref_matches

    assert _echo_receipt_ref_matches("echo-absent:claim-pub-ab", "echo-absent:claim-pub-ab")
    assert not _echo_receipt_ref_matches("mq:echo-absent:claim-pub-ab", "echo-absent:claim-pub-ab")
    assert _echo_receipt_ref_matches("mq:real-echo", "real-echo")


def test_killswitch_env_does_not_bypass_pre_gate0_echo_stub(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("HAPAX_GATE0B_CLAIM_PUBLICATION_OFF", "1")
    monkeypatch.setattr(
        sdlc_close,
        "resolve_claim_bound_canon_position",
        _REAL_CLAIM_POSITION_RESOLVER,
    )

    with pytest.raises(TerminalCloseError) as raised:
        _close(fixture)

    assert raised.value.reason_code == "canon_pre_gate0_claim_migration_required"
    assert "recover-claim-publications" in raised.value.repair_action
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
def test_non_done_close_is_not_wedged_by_an_unsatisfiable_receipt_demand(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    final_status: str,
) -> None:
    """A disposition close must not fail on a receipt that cannot be produced.

    This previously asserted ``terminal_close_operator_disposition_receipt_required``.
    That refusal demanded a governed override receipt with no representation
    anywhere in the tree, so a withdrawn or superseded task could not reach
    terminal closure by ANY route. It is removed from this landing; the strictness
    returns only once the override contract exists with its own review.

    The close may still fail here on ordinary grounds — this pins only that the
    unsatisfiable demand is not the reason.
    """
    fixture = _fixture(tmp_path, monkeypatch, acceptance_receipt=False)

    try:
        _close(fixture, final_status=final_status)
    except TerminalCloseError as exc:
        assert exc.reason_code != "terminal_close_operator_disposition_receipt_required"


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


def test_debt_close_is_not_wedged_and_touches_no_state(tmp_path: Path) -> None:
    """A debt-bearing close fails on satisfiable grounds, and mutates nothing.

    This previously asserted ``terminal_close_debt_override_requires_receipt`` —
    a demand for a governed override receipt that no mechanism could produce, so
    a debt-bearing task was permanently nonterminal. Removed from this landing.

    The close still fails (no vault fixture here), which is the point: it fails
    on something an operator can fix. The no-mutation assertion is the part worth
    keeping — a refused close must leave the tree untouched.
    """
    with pytest.raises(TerminalCloseError) as raised:
        close_task(
            "task-close",
            actor="alpha",
            session_id="session-test",
            debt_reason="skip the gate",
            vault_root=tmp_path / "vault",
            cache_dir=tmp_path / "cache",
        )
    assert raised.value.reason_code != "terminal_close_debt_override_requires_receipt"
    assert not list(tmp_path.rglob("*"))


# ---------------------------------------------------------------------------
# Gate-0A dormancy declarations must expire on their own
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALLOWLIST = _REPO_ROOT / "config" / "new-module-allowlist.json"

# Only the entries THIS landing added. shared.sdlc_close left the dormant set
# when slice-2 re-landed cc-close onto it. methodology_dispatch_carrier is still
# Gate-0A dormant. Pre-existing allowlist rows are not this PR's to police.
_GATE0A_DORMANT_MODULES = ("shared.methodology_dispatch_carrier",)
_SOURCE_DIRS = ("shared", "scripts", "agents", "hooks")


def _imports_module(path: Path, module: str) -> bool:
    """True if ``path`` imports ``module`` — parsed, not grepped.

    A substring search would count the module's name inside a comment, a
    docstring, or the allowlist-explaining prose that motivated these tests, and
    would then report a consumer that does not exist.
    """
    import ast

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name == module or a.name.startswith(module + ".") for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == module or node.module.startswith(module + ".")):
                return True
    return False


def _consumers(module: str) -> list[str]:
    own = _REPO_ROOT / (module.replace(".", "/") + ".py")
    found = []
    for directory in _SOURCE_DIRS:
        for path in (_REPO_ROOT / directory).rglob("*.py"):
            if path == own or "test" in path.name:
                continue
            if _imports_module(path, module):
                found.append(str(path.relative_to(_REPO_ROOT)))
    return sorted(found)


@pytest.mark.parametrize("module", _GATE0A_DORMANT_MODULES)
def test_allowlisted_module_is_still_dormant(module: str) -> None:
    """The dormancy declaration deletes itself once Gate 0B wires a consumer.

    Landing a module with no committer is honest at Gate 0A and dishonest the
    moment a consumer appears — but nothing forces anyone to notice the
    transition, so "dormant" can quietly become "permanently exempt from the
    consumer gate". This makes the transition loud, so the exit predicate for
    the dormancy is a command rather than a promise.
    """
    consumers = _consumers(module)
    assert not consumers, (
        f"{module} now has non-test consumers: {consumers}. It is no longer a "
        f"dormant Gate-0A seam, so remove it from {_ALLOWLIST.name} and let the "
        "new-module-consumer gate cover it normally."
    )


@pytest.mark.parametrize("module", _GATE0A_DORMANT_MODULES)
def test_dormant_module_is_actually_declared(module: str) -> None:
    """Guards the inverse: a declaration dropped while the module stays dormant.

    Without this, deleting an allowlist entry breaks CI's consumer gate on some
    later unrelated PR, far away from the edit that caused it.
    """
    entries = json.loads(_ALLOWLIST.read_text(encoding="utf-8"))
    assert module in entries, (
        f"{module} has no consumer yet is missing from {_ALLOWLIST.name}; the "
        "new-module-consumer gate will fail. Either wire a consumer or restore "
        "the declaration."
    )


def test_the_dormant_set_is_not_empty() -> None:
    """An empty tuple would make both parametrized suites vacuously pass."""
    assert _GATE0A_DORMANT_MODULES
