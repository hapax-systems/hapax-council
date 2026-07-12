from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from shared.coord_dispatch import (
    CoordDispatchError,
    DispatchLaunchRequest,
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
from shared.relay_mq_envelope import Envelope


def _request(
    db_path: Path,
    message_id: str,
    *,
    event_log: CoordEventLog | Mock | None = None,
    task_id: str = "task-1",
    authority_item: str = "task-1",
    profile: str = "full",
    idempotency_key: str | None = None,
) -> DispatchLaunchRequest:
    return DispatchLaunchRequest(
        task_id=task_id,
        lane="cx-test",
        platform="codex",
        mode="headless",
        profile=profile,
        authority_case="CASE-P0-TEST",
        authority_item=authority_item,
        parent_spec="/tmp/spec.md",
        message_id=message_id,
        mq_db_path=db_path,
        event_log=event_log or Mock(),
        idempotency_key=idempotency_key,
    )


def _deferred_dispatch(
    db_path: Path,
    reason: str,
    *,
    task_id: str = "task-1",
    authority_item: str = "task-1",
) -> str:
    envelope = Envelope(
        sender="hapax-coordinator",
        message_type="dispatch",
        priority=0,
        subject=task_id,
        authority_case="CASE-P0-TEST",
        authority_item=authority_item,
        recipients_spec="cx-test",
        payload="{}",
    )
    return send_message(
        db_path,
        envelope,
        initial_recipient_state="deferred",
        initial_reason=reason,
    )


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


def test_atomic_dispatch_compare_and_swap_rejects_stale_offered_reader(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    message_id = _deferred_dispatch(db_path, COORDINATOR_PREPARED_DISPATCH_REASON)
    request = _request(db_path, message_id)
    _accept_dispatch_message(request, idempotency_key="first")

    with (
        patch(
            "shared.coord_dispatch._load_and_validate_message",
            return_value={"state": "offered", "reason": None},
        ),
        pytest.raises(CoordDispatchError, match="mq_dispatch_consume_race"),
    ):
        _accept_dispatch_message(request, idempotency_key="second")


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
    message_id = _deferred_dispatch(db_path, "operator_deferred")
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
