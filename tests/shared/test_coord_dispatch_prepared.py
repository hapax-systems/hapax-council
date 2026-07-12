from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Literal
from unittest.mock import Mock, patch

import pytest

from shared.coord_dispatch import (
    CoordDispatchError,
    DispatchLaunchRequest,
    DispatchPreparationBinding,
    _accept_dispatch_message,
    _append_dispatch_event,
    _cleanup_dispatch_message,
    finalize_accepted_dispatch_on_pickup,
    run_atomic_dispatch_launch,
)
from shared.coord_event_log import CoordEventLog
from shared.relay_mq import (
    COORDINATOR_PREPARED_DISPATCH_REASON,
    abort_coordinator_prepared_dispatch,
    ack_message,
    send_message,
)
from shared.relay_mq_envelope import Envelope, compute_payload_hash

_DEFAULT_BINDING_HASH = object()


def _binding() -> DispatchPreparationBinding:
    return DispatchPreparationBinding(
        task_id="task-1",
        task_path="/tmp/task-1.md",
        task_sha256="1" * 64,
        lane="cx-test",
        lane_session="cx-test-session",
        lane_generation="generation-1",
        lane_pid=123,
        lane_pid_generation="pid-generation-1",
        claim_projection_sha256="2" * 64,
        relay_projection_sha256="3" * 64,
        platform="codex",
        mode="headless",
        authority_case="CASE-P0-TEST",
        authority_item="task-1",
        parent_spec="/tmp/spec.md",
        parent_spec_sha256=hashlib.sha256(b"parent spec").hexdigest(),
    )


def _binding_for(
    *,
    task_id: str = "task-1",
    authority_item: str = "task-1",
) -> DispatchPreparationBinding:
    return replace(_binding(), task_id=task_id, authority_item=authority_item)


def _binding_payload(binding: DispatchPreparationBinding) -> str:
    return json.dumps(
        {"dispatch_binding": binding.to_record()},
        separators=(",", ":"),
        sort_keys=True,
    )


def _request(
    db_path: Path,
    message_id: str,
    *,
    event_log: CoordEventLog | Mock | None = None,
    task_id: str = "task-1",
    authority_item: str = "task-1",
    platform: str = "codex",
    mode: str = "headless",
    profile: str = "full",
    idempotency_key: str | None = None,
    binding_hash: object = _DEFAULT_BINDING_HASH,
    prepared_platform: str | None = None,
    prepared_mode: str | None = None,
) -> DispatchLaunchRequest:
    if binding_hash is _DEFAULT_BINDING_HASH:
        resolved_binding_hash: str | None = _binding_for(
            task_id=task_id,
            authority_item=authority_item,
        ).binding_hash
    elif isinstance(binding_hash, str) or binding_hash is None:
        resolved_binding_hash = binding_hash
    else:
        raise TypeError("binding_hash must be a string or None")
    return DispatchLaunchRequest(
        task_id=task_id,
        lane="cx-test",
        platform=platform,
        mode=mode,
        profile=profile,
        authority_case="CASE-P0-TEST",
        authority_item=authority_item,
        parent_spec="/tmp/spec.md",
        message_id=message_id,
        mq_db_path=db_path,
        event_log=event_log or Mock(),
        idempotency_key=idempotency_key,
        binding_hash=resolved_binding_hash,
        prepared_platform=prepared_platform,
        prepared_mode=prepared_mode,
    )


def _deferred_dispatch(
    db_path: Path,
    reason: str,
    *,
    task_id: str = "task-1",
    authority_item: str = "task-1",
    sender: str = "hapax-coordinator",
    payload: str | None = None,
) -> str:
    if payload is None:
        payload = _binding_payload(
            _binding_for(task_id=task_id, authority_item=authority_item),
        )
    envelope = Envelope(
        sender=sender,
        message_type="dispatch",
        priority=0,
        subject=task_id,
        authority_case="CASE-P0-TEST",
        authority_item=authority_item,
        recipients_spec="cx-test",
        payload=payload,
    )
    return send_message(
        db_path,
        envelope,
        initial_recipient_state="deferred",
        initial_reason=reason,
    )


def test_preparation_binding_binds_and_validates_parent_spec_sha256() -> None:
    binding = _binding()
    record = binding.to_record()

    assert record["parent_spec_sha256"] == hashlib.sha256(b"parent spec").hexdigest()
    assert DispatchPreparationBinding.from_record(record) == binding
    assert replace(binding, parent_spec_sha256="a" * 64).binding_hash != binding.binding_hash

    uppercase = replace(binding, parent_spec_sha256="A" * 64)
    with pytest.raises(CoordDispatchError, match="dispatch_preparation_binding_malformed"):
        DispatchPreparationBinding.from_record(uppercase.to_record())


@pytest.mark.parametrize("binding_hash", [None, _binding().binding_hash])
def test_lower_layer_launch_rejects_unbound_or_empty_preparation(
    tmp_path: Path,
    binding_hash: str | None,
) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(
        db_path,
        COORDINATOR_PREPARED_DISPATCH_REASON,
        payload="{}",
    )
    event_log = CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )
    request = _request(
        db_path,
        message_id,
        event_log=event_log,
        binding_hash=binding_hash,
    )
    launcher = Mock(return_value=0)

    with pytest.raises(
        CoordDispatchError,
        match="dispatch_preparation_binding_(hash_required|malformed)",
    ):
        run_atomic_dispatch_launch(request, launcher)

    launcher.assert_not_called()
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT state, reason FROM recipients WHERE message_id = ?",
            (message_id,),
        ).fetchone() == ("deferred", COORDINATOR_PREPARED_DISPATCH_REASON)


def test_atomic_launch_rejects_tampered_payload_with_recomputed_inner_hash(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "messages.db"
    binding = _binding()
    payload = json.dumps(
        {"dispatch_binding": binding.to_record()},
        separators=(",", ":"),
        sort_keys=True,
    )
    envelope = Envelope(
        sender="hapax-coordinator",
        message_type="dispatch",
        priority=0,
        subject=binding.task_id,
        authority_case=binding.authority_case,
        authority_item=binding.authority_item,
        recipients_spec=binding.lane,
        payload=payload,
    )
    message_id = send_message(
        db_path,
        envelope,
        initial_recipient_state="deferred",
        initial_reason=COORDINATOR_PREPARED_DISPATCH_REASON,
    )
    tampered_binding = replace(binding, lane_session="recomputed-tampered-session")
    tampered_payload = json.dumps(
        {"dispatch_binding": tampered_binding.to_record()},
        separators=(",", ":"),
        sort_keys=True,
    )
    with sqlite3.connect(db_path) as conn:
        persisted_hash = conn.execute(
            "SELECT payload_hash FROM messages WHERE message_id = ?",
            (message_id,),
        ).fetchone()[0]
        conn.execute(
            "UPDATE messages SET payload = ? WHERE message_id = ?",
            (tampered_payload, message_id),
        )
        conn.commit()

    event_log = CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )
    request = _request(
        db_path,
        message_id,
        event_log=event_log,
        binding_hash=tampered_binding.binding_hash,
    )
    launcher = Mock(return_value=0)

    with pytest.raises(CoordDispatchError, match="mq_payload_hash_mismatch"):
        run_atomic_dispatch_launch(request, launcher)

    launcher.assert_not_called()
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT payload_hash FROM messages WHERE message_id = ?",
            (message_id,),
        ).fetchone() == (persisted_hash,)
        assert conn.execute(
            "SELECT state, reason FROM recipients WHERE message_id = ?",
            (message_id,),
        ).fetchone() == ("deferred", COORDINATOR_PREPARED_DISPATCH_REASON)


def test_atomic_dispatch_accepts_exact_coordinator_prepared_row(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    request = _request(db_path, message_id)

    _accept_dispatch_message(request, idempotency_key="dispatch-key")

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT state, reason FROM recipients WHERE message_id = ?",
            (message_id,),
        ).fetchone() == ("accepted", "coord_dispatch_accepted:dispatch-key")

    with pytest.raises(
        CoordDispatchError,
        match="mq_dispatch_already_accepted_without_replay",
    ):
        _accept_dispatch_message(request, idempotency_key="dispatch-key")


def test_atomic_launch_records_prepared_and_recomposed_route_identity(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    event_log = CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )
    request = _request(
        db_path,
        message_id,
        event_log=event_log,
        platform="claude",
        prepared_platform="codex",
        prepared_mode="headless",
    )

    result = run_atomic_dispatch_launch(request, Mock(return_value=0))

    assert result.launched is True
    events = event_log.replay().events
    assert [event.payload["prepared_platform"] for event in events] == ["codex", "codex"]
    assert [event.payload["platform"] for event in events] == ["claude", "claude"]


def test_recomposed_route_without_explicit_prepared_identity_is_refused(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    event_log = CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )
    request = _request(
        db_path,
        message_id,
        event_log=event_log,
        platform="claude",
    )
    launcher = Mock(return_value=0)

    with pytest.raises(CoordDispatchError, match="binding_identity_mismatch"):
        run_atomic_dispatch_launch(request, launcher)

    launcher.assert_not_called()


def test_accepted_message_mutation_requires_binding_hash(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    request = _request(db_path, message_id, binding_hash=None)

    with pytest.raises(CoordDispatchError, match="dispatch_preparation_binding_hash_required"):
        _accept_dispatch_message(request, idempotency_key="dispatch-key")

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT state, reason FROM recipients WHERE message_id = ?",
            (message_id,),
        ).fetchone() == ("deferred", COORDINATOR_PREPARED_DISPATCH_REASON)


def test_event_append_requires_exact_accepted_row(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    event_log = CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )
    request = _request(db_path, message_id, event_log=event_log)
    key = request.effective_idempotency_key
    _accept_dispatch_message(request, idempotency_key=key)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE recipients SET state = 'deferred', reason = 'foreign-transition' "
            "WHERE message_id = ?",
            (message_id,),
        )
        conn.commit()

    with pytest.raises(CoordDispatchError, match="event_requires_exact_acceptance"):
        _append_dispatch_event(
            request,
            idempotency_key=key,
            outcome="started",
            returncode=None,
        )

    assert event_log.replay().events == ()


def test_terminal_event_requires_exact_started_event(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    event_log = CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )
    request = _request(db_path, message_id, event_log=event_log)
    key = request.effective_idempotency_key
    _accept_dispatch_message(request, idempotency_key=key)

    with pytest.raises(CoordDispatchError, match="terminal_event_requires_exact_started_event"):
        _append_dispatch_event(
            request,
            idempotency_key=key,
            outcome="succeeded",
            returncode=0,
        )

    assert event_log.replay().events == ()


def test_atomic_dispatch_rejects_non_coordinator_sender(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(
        db_path,
        COORDINATOR_PREPARED_DISPATCH_REASON,
        sender="operator-dispatcher",
    )

    with pytest.raises(CoordDispatchError, match="mq_sender_mismatch"):
        _accept_dispatch_message(
            _request(db_path, message_id),
            idempotency_key="dispatch-key",
        )


def test_atomic_dispatch_always_verifies_outer_payload_hash(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE messages SET payload = ? WHERE message_id = ?",
            ('{"tampered":true}', message_id),
        )
        conn.commit()

    with pytest.raises(CoordDispatchError, match="mq_payload_hash_mismatch"):
        _accept_dispatch_message(
            _request(db_path, message_id),
            idempotency_key="dispatch-key",
        )


def test_atomic_dispatch_compare_and_swap_rejects_stale_offered_reader(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    request = _request(db_path, message_id)
    _accept_dispatch_message(request, idempotency_key="first")
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        stale_row = dict(
            conn.execute(
                """
                SELECT m.sender, m.message_type, m.authority_case, m.authority_item,
                       m.subject, m.payload, m.payload_hash, m.stale_after, m.expires_at,
                       r.state, r.reason
                FROM messages m
                JOIN recipients r ON r.message_id = m.message_id
                WHERE m.message_id = ? AND r.recipient = ?
                """,
                (message_id, "cx-test"),
            ).fetchone()
        )
    stale_row["state"] = "offered"
    stale_row["reason"] = None

    with (
        patch(
            "shared.coord_dispatch._load_and_validate_message",
            return_value=stale_row,
        ),
        pytest.raises(CoordDispatchError, match="mq_dispatch_consume_race"),
    ):
        _accept_dispatch_message(request, idempotency_key="second")


def test_atomic_dispatch_compare_and_swap_binds_validated_message_preimage(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    request = _request(db_path, message_id)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        validated_row = dict(
            conn.execute(
                """
                SELECT m.sender, m.message_type, m.authority_case, m.authority_item,
                       m.subject, m.payload, m.payload_hash, m.stale_after, m.expires_at,
                       r.state, r.reason
                FROM messages m
                JOIN recipients r ON r.message_id = m.message_id
                WHERE m.message_id = ? AND r.recipient = ?
                """,
                (message_id, "cx-test"),
            ).fetchone()
        )
        replacement_payload = '{"replacement":true}'
        conn.execute(
            "UPDATE messages SET payload = ?, payload_hash = ? WHERE message_id = ?",
            (replacement_payload, compute_payload_hash(replacement_payload), message_id),
        )
        conn.commit()

    with (
        patch(
            "shared.coord_dispatch._load_and_validate_message",
            return_value=validated_row,
        ),
        pytest.raises(CoordDispatchError, match="mq_dispatch_consume_race"),
    ):
        _accept_dispatch_message(request, idempotency_key="dispatch-key")


def test_atomic_dispatch_rejects_unrelated_deferred_row(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, "operator_deferred")

    with pytest.raises(CoordDispatchError, match="mq_dispatch_not_consumable:deferred"):
        _accept_dispatch_message(_request(db_path, message_id), idempotency_key="dispatch-key")

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT state, reason FROM recipients WHERE message_id = ?",
            (message_id,),
        ).fetchone() == ("deferred", "operator_deferred")


def test_atomic_dispatch_rejects_shared_authority_item_for_different_task(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(
        db_path,
        COORDINATOR_PREPARED_DISPATCH_REASON,
        task_id="task-a",
        authority_item="shared-item",
    )
    request = _request(
        db_path,
        message_id,
        task_id="task-b",
        authority_item="shared-item",
    )

    with pytest.raises(CoordDispatchError, match="mq_subject_task_mismatch"):
        _accept_dispatch_message(request, idempotency_key=request.effective_idempotency_key)


def test_generic_ack_cannot_accept_coordinator_prepared_row(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)

    assert ack_message(db_path, message_id, "cx-test", "accepted") is False

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT state, reason FROM recipients WHERE message_id = ?",
            (message_id,),
        ).fetchone() == ("deferred", COORDINATOR_PREPARED_DISPATCH_REASON)


def test_abort_does_not_treat_an_accepted_row_as_revoked(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(
        db_path,
        "operator_deferred",
        sender="operator-dispatcher",
    )
    assert ack_message(db_path, message_id, "cx-test", "accepted") is True

    assert (
        abort_coordinator_prepared_dispatch(db_path, message_id, "cx-test", "ownership_changed")
        is False
    )


def test_generic_ack_cannot_resurrect_aborted_preparation(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    assert abort_coordinator_prepared_dispatch(
        db_path,
        message_id,
        "cx-test",
        "ownership_changed",
    )

    assert ack_message(db_path, message_id, "cx-test", "accepted") is False
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT state, reason FROM recipients WHERE message_id = ?",
            (message_id,),
        ).fetchone() == (
            "deferred",
            "coordinator_prepare_aborted:ownership_changed",
        )


def test_generic_ack_cannot_reassign_coordinator_accepted_row(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    request = _request(db_path, message_id)
    _accept_dispatch_message(request, idempotency_key="owned-key")

    assert ack_message(db_path, message_id, "cx-test", "deferred", "generic retry") is False
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT state, reason FROM recipients WHERE message_id = ?",
            (message_id,),
        ).fetchone() == ("accepted", "coord_dispatch_accepted:owned-key")


def test_cleanup_requires_exact_acceptance_owner_key(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    request = _request(db_path, message_id)
    _accept_dispatch_message(request, idempotency_key="owned-key")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE recipients SET reason = ? WHERE message_id = ?",
            ("coord_dispatch_accepted:replacement-key", message_id),
        )
        conn.commit()

    with pytest.raises(CoordDispatchError, match="mq_dispatch_cleanup_race"):
        _cleanup_dispatch_message(
            request,
            idempotency_key="owned-key",
            state="processed",
            returncode=0,
        )


def test_inflight_idempotency_key_cannot_launch_second_message(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    first_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    second_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    event_log = CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )
    first = _request(db_path, first_id, event_log=event_log, idempotency_key="shared-key")
    second = _request(db_path, second_id, event_log=event_log, idempotency_key="shared-key")
    _accept_dispatch_message(first, idempotency_key="shared-key")
    _append_dispatch_event(
        first,
        idempotency_key="shared-key",
        outcome="started",
        returncode=None,
    )
    launcher = Mock(return_value=0)

    with pytest.raises(CoordDispatchError, match="idempotency_key_request_identity_mismatch"):
        run_atomic_dispatch_launch(second, launcher)

    launcher.assert_not_called()
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT state FROM recipients WHERE message_id = ?",
            (second_id,),
        ).fetchone() == ("deferred",)


def test_idempotency_replay_refuses_when_canonical_ledger_is_unreadable(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    event_log = Mock()
    event_log.replay.side_effect = OSError("canonical ledger unavailable")
    launcher = Mock(return_value=0)

    with pytest.raises(OSError, match="canonical ledger unavailable"):
        run_atomic_dispatch_launch(
            _request(db_path, message_id, event_log=event_log),
            launcher,
        )

    launcher.assert_not_called()
    event_log.replay.assert_called_once_with(fail_open=False)


@pytest.mark.parametrize("returncode", [0, 42])
def test_terminal_event_append_failure_after_launch_leaves_mq_accepted(
    tmp_path: Path,
    returncode: int,
) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    event_log = CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )
    request = _request(db_path, message_id, event_log=event_log)
    launcher = Mock(return_value=returncode)
    append = event_log.append

    def fail_terminal_append(event: object, **kwargs: object) -> object:
        if getattr(event, "event_type", "") in {
            "coord_dispatch.launch_succeeded",
            "coord_dispatch.launch_failed",
        }:
            raise OSError("terminal ledger unavailable")
        return append(event, **kwargs)  # type: ignore[arg-type]

    with (
        patch.object(event_log, "append", side_effect=fail_terminal_append),
        pytest.raises(CoordDispatchError, match="coord_event_log_append_failed:OSError"),
    ):
        run_atomic_dispatch_launch(request, launcher)

    launcher.assert_called_once_with()
    key = request.effective_idempotency_key
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT state, reason FROM recipients WHERE message_id = ?",
            (message_id,),
        ).fetchone() == ("accepted", f"coord_dispatch_accepted:{key}")
    assert [event.event_type for event in event_log.replay().events] == [
        "coord_dispatch.launch_started"
    ]


@pytest.mark.parametrize(
    ("outcome", "returncode", "cleanup_state", "launched"),
    [
        ("succeeded", 0, "processed", True),
        ("failed", 42, "deferred", False),
    ],
)
def test_terminal_event_present_reconciles_accepted_row_without_relaunch(
    tmp_path: Path,
    outcome: Literal["succeeded", "failed"],
    returncode: int,
    cleanup_state: Literal["processed", "deferred"],
    launched: bool,
) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    event_log = CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )
    request = _request(db_path, message_id, event_log=event_log)
    key = request.effective_idempotency_key
    _accept_dispatch_message(request, idempotency_key=key)
    _append_dispatch_event(request, idempotency_key=key, outcome="started", returncode=None)
    terminal_event_id = _append_dispatch_event(
        request,
        idempotency_key=key,
        outcome=outcome,
        returncode=returncode,
    )
    launcher = Mock(return_value=0)

    result = run_atomic_dispatch_launch(request, launcher)

    launcher.assert_not_called()
    assert result.replayed is True
    assert result.launched is launched
    assert result.event_id == terminal_event_id
    assert result.cleanup_state == cleanup_state
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT state, reason FROM recipients WHERE message_id = ?",
            (message_id,),
        ).fetchone() == (
            cleanup_state,
            f"coord_dispatch_launch_{cleanup_state}:{returncode}:{key}",
        )


def test_duplicate_terminal_replay_is_exact_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    event_log = CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )
    request = _request(db_path, message_id, event_log=event_log)
    key = request.effective_idempotency_key
    _accept_dispatch_message(request, idempotency_key=key)
    _append_dispatch_event(request, idempotency_key=key, outcome="started", returncode=None)
    _append_dispatch_event(
        request,
        idempotency_key=key,
        outcome="succeeded",
        returncode=0,
    )
    launcher = Mock(return_value=0)
    first = run_atomic_dispatch_launch(request, launcher)
    with sqlite3.connect(db_path) as conn:
        first_row = conn.execute(
            "SELECT state, reason, updated_at FROM recipients WHERE message_id = ?",
            (message_id,),
        ).fetchone()

    second = run_atomic_dispatch_launch(request, launcher)

    launcher.assert_not_called()
    assert first.replayed is True
    assert second == first
    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute(
                "SELECT state, reason, updated_at FROM recipients WHERE message_id = ?",
                (message_id,),
            ).fetchone()
            == first_row
        )


def test_terminal_replay_rejects_mismatched_mq_cleanup_reason(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    event_log = CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )
    request = _request(db_path, message_id, event_log=event_log)
    key = request.effective_idempotency_key
    _accept_dispatch_message(request, idempotency_key=key)
    _append_dispatch_event(request, idempotency_key=key, outcome="started", returncode=None)
    _append_dispatch_event(
        request,
        idempotency_key=key,
        outcome="succeeded",
        returncode=0,
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE recipients SET state = 'processed', reason = ? WHERE message_id = ?",
            (f"coord_dispatch_launch_processed:1:{key}", message_id),
        )
        conn.commit()
    launcher = Mock(return_value=0)

    with pytest.raises(CoordDispatchError, match="mq_dispatch_cleanup_race"):
        run_atomic_dispatch_launch(request, launcher)

    launcher.assert_not_called()
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT state, reason FROM recipients WHERE message_id = ?",
            (message_id,),
        ).fetchone() == ("processed", f"coord_dispatch_launch_processed:1:{key}")


def test_terminal_replay_rejects_conflicting_exact_events(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    event_log = CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )
    request = _request(db_path, message_id, event_log=event_log)
    key = request.effective_idempotency_key
    _accept_dispatch_message(request, idempotency_key=key)
    _append_dispatch_event(request, idempotency_key=key, outcome="started", returncode=None)
    _append_dispatch_event(
        request,
        idempotency_key=key,
        outcome="succeeded",
        returncode=0,
    )
    _append_dispatch_event(
        request,
        idempotency_key=key,
        outcome="failed",
        returncode=42,
    )
    launcher = Mock(return_value=0)

    with pytest.raises(CoordDispatchError, match="idempotency_key_terminal_event_conflict"):
        run_atomic_dispatch_launch(request, launcher)

    launcher.assert_not_called()
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT state, reason FROM recipients WHERE message_id = ?",
            (message_id,),
        ).fetchone() == ("accepted", f"coord_dispatch_accepted:{key}")


def test_pickup_finalizer_uses_actual_recomposed_route_identity(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    event_log = CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )
    coordinator_request = _request(db_path, message_id, event_log=event_log, profile="full")
    selected_request = _request(db_path, message_id, event_log=event_log, profile="spark")
    selected_key = selected_request.effective_idempotency_key
    _accept_dispatch_message(selected_request, idempotency_key=selected_key)
    _append_dispatch_event(
        selected_request,
        idempotency_key=selected_key,
        outcome="started",
        returncode=None,
    )

    result = finalize_accepted_dispatch_on_pickup(coordinator_request)

    assert result.idempotency_key == selected_key
    events = event_log.replay().events
    assert events[-1].payload["profile"] == "spark"
    assert events[-1].event_type == "coord_dispatch.launch_succeeded"


def test_pickup_finalizer_uses_cross_platform_recomposed_route_identity(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    event_log = CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )
    coordinator_request = _request(db_path, message_id, event_log=event_log)
    selected_request = _request(
        db_path,
        message_id,
        event_log=event_log,
        platform="claude",
        prepared_platform="codex",
        prepared_mode="headless",
    )
    selected_key = selected_request.effective_idempotency_key
    _accept_dispatch_message(selected_request, idempotency_key=selected_key)
    _append_dispatch_event(
        selected_request,
        idempotency_key=selected_key,
        outcome="started",
        returncode=None,
    )

    result = finalize_accepted_dispatch_on_pickup(coordinator_request)

    assert result.idempotency_key == selected_key
    events = event_log.replay().events
    assert events[-1].payload["prepared_platform"] == "codex"
    assert events[-1].payload["platform"] == "claude"
    assert events[-1].event_type == "coord_dispatch.launch_succeeded"


def test_pickup_finalizer_requires_binding_hash(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    event_log = CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )
    request = _request(db_path, message_id, event_log=event_log)
    key = request.effective_idempotency_key
    _accept_dispatch_message(request, idempotency_key=key)
    _append_dispatch_event(request, idempotency_key=key, outcome="started", returncode=None)

    with pytest.raises(CoordDispatchError, match="dispatch_preparation_binding_hash_required"):
        finalize_accepted_dispatch_on_pickup(replace(request, binding_hash=None))

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT state, reason FROM recipients WHERE message_id = ?",
            (message_id,),
        ).fetchone() == ("accepted", f"coord_dispatch_accepted:{key}")


def test_pickup_terminal_append_failure_leaves_mq_accepted(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    event_log = CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )
    request = _request(db_path, message_id, event_log=event_log)
    key = request.effective_idempotency_key
    _accept_dispatch_message(request, idempotency_key=key)
    _append_dispatch_event(request, idempotency_key=key, outcome="started", returncode=None)
    append = event_log.append

    def fail_terminal_append(event: object, **kwargs: object) -> object:
        if getattr(event, "event_type", "") == "coord_dispatch.launch_succeeded":
            raise OSError("terminal ledger unavailable")
        return append(event, **kwargs)  # type: ignore[arg-type]

    with (
        patch.object(event_log, "append", side_effect=fail_terminal_append),
        pytest.raises(CoordDispatchError, match="coord_event_log_append_failed:OSError"),
    ):
        finalize_accepted_dispatch_on_pickup(request)

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT state, reason FROM recipients WHERE message_id = ?",
            (message_id,),
        ).fetchone() == ("accepted", f"coord_dispatch_accepted:{key}")
    assert [event.event_type for event in event_log.replay().events] == [
        "coord_dispatch.launch_started"
    ]


def test_pickup_finalizer_closes_accepted_row_and_terminal_event(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    event_log = CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )
    request = _request(db_path, message_id, event_log=event_log)
    key = request.effective_idempotency_key
    _accept_dispatch_message(request, idempotency_key=key)
    _append_dispatch_event(
        request,
        idempotency_key=key,
        outcome="started",
        returncode=None,
    )

    result = finalize_accepted_dispatch_on_pickup(request)

    assert result.launched is True
    assert result.cleanup_state == "processed"
    assert result.reason == "launch_succeeded_after_pickup"
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT state, reason FROM recipients WHERE message_id = ?",
            (message_id,),
        ).fetchone() == (
            "processed",
            f"coord_dispatch_launch_processed:0:{key}",
        )
    events = event_log.replay().events
    event_types = [event.event_type for event in events]
    assert event_types == [
        "coord_dispatch.launch_started",
        "coord_dispatch.launch_succeeded",
    ]
    assert events[-1].payload["completion_source"] == ("coordinator_verified_pickup_after_timeout")

    replayed = finalize_accepted_dispatch_on_pickup(request)
    assert replayed.replayed is True
    assert replayed.launched is True


def test_pickup_finalizer_requires_started_event(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    event_log = CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )
    request = _request(db_path, message_id, event_log=event_log)
    _accept_dispatch_message(request, idempotency_key=request.effective_idempotency_key)

    with pytest.raises(CoordDispatchError, match="pickup_finalize_started_event_missing"):
        finalize_accepted_dispatch_on_pickup(request)
