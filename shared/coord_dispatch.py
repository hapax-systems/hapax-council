"""Atomic coordination dispatch binding, MQ consumption, and launch replay."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from shared.coord_event_log import CoordEvent, CoordEventLog, CoordWriter, DuplicateEventError
from shared.relay_lifecycle import lane_is_retired
from shared.relay_mq import ensure_schema

TERMINAL_EVENT_TYPES = {
    "coord_dispatch.launch_succeeded",
    "coord_dispatch.launch_failed",
}
OPERATOR_ATTESTATION_RULING = "RULING-REINS-OPERATOR-ATTESTATION-20260701"


class CoordDispatchError(RuntimeError):
    """Base error for coordination dispatch fusion failures."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def expected_operator_attestation_ref(
    *,
    origin_surface: str,
    task_id: str,
    lane: str,
    ruling: str = OPERATOR_ATTESTATION_RULING,
) -> str:
    """Return the Crow-chat operator attestation ref bound to origin, task, lane, and ruling."""

    origin = origin_surface.strip()
    payload = {
        "origin_surface": origin,
        "task_id": task_id.strip(),
        "lane": lane.strip(),
        "ruling": ruling.strip(),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:32]
    return f"operator-attestation:reins:{origin}:{digest}"


@dataclass(frozen=True)
class DispatchLaunchRequest:
    """Inputs needed to bind a strict MQ dispatch message to one launch."""

    task_id: str
    lane: str
    platform: str
    mode: str
    profile: str
    authority_case: str
    parent_spec: str | None
    message_id: str
    mq_db_path: Path
    event_log: CoordEventLog
    idempotency_key: str | None = None
    authority_item: str | None = None
    reactivate_retired: bool = False
    origin_surface: str | None = None
    operator_attestation_ref: str | None = None
    require_crow_chat_attestation: bool = False

    def __post_init__(self) -> None:
        for name in ("task_id", "lane", "platform", "mode", "profile", "authority_case"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if not self.message_id.strip():
            raise CoordDispatchError("strict_mq_message_id_required")
        origin_surface = (self.origin_surface or "").strip()
        attestation_ref = (self.operator_attestation_ref or "").strip()
        if self.require_crow_chat_attestation and origin_surface != "crow_chat":
            raise CoordDispatchError("crow_chat_origin_required_for_dispatch")
        if origin_surface == "crow_chat" and not attestation_ref:
            raise CoordDispatchError("operator_attestation_ref_required_for_crow_chat")
        if origin_surface == "crow_chat":
            expected = expected_operator_attestation_ref(
                origin_surface=origin_surface,
                task_id=self.task_id,
                lane=self.lane,
            )
            if attestation_ref != expected:
                raise CoordDispatchError("operator_attestation_ref_task_lane_mismatch")
        if attestation_ref and not origin_surface:
            raise CoordDispatchError("operator_attestation_ref_without_origin_surface")

    @property
    def normalized_lane(self) -> str:
        return self.lane.strip().lower().replace("_", "-")

    @property
    def effective_idempotency_key(self) -> str:
        if self.idempotency_key and self.idempotency_key.strip():
            return self.idempotency_key.strip()
        return default_idempotency_key(
            task_id=self.task_id,
            lane=self.normalized_lane,
            platform=self.platform,
            mode=self.mode,
            profile=self.profile,
            message_id=self.message_id,
        )


@dataclass(frozen=True)
class DispatchLaunchResult:
    """Outcome of the atomic dispatch launch operation."""

    launched: bool
    launch_returncode: int
    replayed: bool
    reason: str
    message_id: str
    idempotency_key: str
    event_id: str | None = None
    cleanup_state: Literal["processed", "deferred"] | None = None
    origin_surface: str | None = None
    operator_attestation_ref: str | None = None
    crow_chat_attestation_required: bool = False


def default_idempotency_key(
    *,
    task_id: str,
    lane: str,
    platform: str,
    mode: str,
    profile: str,
    message_id: str,
) -> str:
    """Return the stable default idempotency key for one dispatch launch."""

    return ":".join(
        [
            "coord-dispatch-v1",
            message_id,
            lane,
            task_id,
            platform,
            mode,
            profile,
        ]
    )


def run_atomic_dispatch_launch(
    request: DispatchLaunchRequest,
    launch: Callable[[], int],
) -> DispatchLaunchResult:
    """Bind, consume, launch, and record one dispatch as a single operation.

    The external launcher cannot participate in SQLite transactions, so this
    function makes the side effect idempotent: terminal coordination events are
    replayed before any MQ mutation; nonzero launcher exits return the MQ row to
    an explicit deferred cleanup state.
    """

    key = request.effective_idempotency_key
    replayed = replay_terminal_result(request, idempotency_key=key)
    if replayed is not None:
        return replayed

    _accept_dispatch_message(request, idempotency_key=key)
    try:
        # Derived lane-liveness eligibility gate (the retired-axis of the 3-axis
        # predicate at this chokepoint): refuse to launch a retired lane unless
        # the caller supplied the sanctioned reactivation signal
        # (reactivate_retired, threaded from methodology-dispatch's
        # allow_codex_governed_relay_reactivation). Raised before the "started"
        # event is appended, so no launch_started is recorded; the except returns
        # the MQ row to deferred (accepted -> deferred) and the error propagates.
        # See shared/relay_lifecycle + design-of-record
        # non-boutique-codex-auth-and-lane-liveness-design-2026-07-03.md.
        if lane_is_retired(request.lane) and not request.reactivate_retired:
            raise CoordDispatchError(
                "lane_retired: inspect the lane relay in HAPAX_RELAY_DIR, resume the lane, "
                "or use the sanctioned P0-drain reactivation path"
            )
        _append_dispatch_event(request, idempotency_key=key, outcome="started", returncode=None)
    except CoordDispatchError:
        _cleanup_dispatch_message(request, idempotency_key=key, state="deferred", returncode=71)
        raise

    try:
        returncode = int(launch())
    except BaseException:
        _cleanup_dispatch_message(request, idempotency_key=key, state="deferred", returncode=70)
        _append_dispatch_event(request, idempotency_key=key, outcome="failed", returncode=70)
        raise

    if returncode == 0:
        cleanup_state: Literal["processed", "deferred"] = "processed"
        outcome = "succeeded"
        launched = True
    else:
        cleanup_state = "deferred"
        outcome = "failed"
        launched = False

    _cleanup_dispatch_message(
        request,
        idempotency_key=key,
        state=cleanup_state,
        returncode=returncode,
    )
    event_id = _append_dispatch_event(
        request,
        idempotency_key=key,
        outcome=outcome,
        returncode=returncode,
    )
    return DispatchLaunchResult(
        launched=launched,
        launch_returncode=returncode,
        replayed=False,
        reason=f"launch_{outcome}",
        message_id=request.message_id,
        idempotency_key=key,
        event_id=event_id,
        cleanup_state=cleanup_state,
        origin_surface=request.origin_surface,
        operator_attestation_ref=request.operator_attestation_ref,
        crow_chat_attestation_required=request.require_crow_chat_attestation,
    )


def replay_terminal_result(
    request: DispatchLaunchRequest,
    *,
    idempotency_key: str,
) -> DispatchLaunchResult | None:
    """Replay a prior terminal launch result for ``idempotency_key``."""

    result = request.event_log.replay(fail_open=True)
    for event in reversed(result.events):
        if event.event_type not in TERMINAL_EVENT_TYPES:
            continue
        if event.payload.get("idempotency_key") != idempotency_key:
            continue
        event_message_id = str(event.payload.get("message_id", ""))
        if event_message_id != request.message_id:
            raise CoordDispatchError("idempotency_key_message_id_mismatch")
        returncode = int(event.payload.get("returncode", 0))
        outcome = str(event.payload.get("outcome", ""))
        cleanup_state = "processed" if outcome == "succeeded" else "deferred"
        return DispatchLaunchResult(
            launched=outcome == "succeeded",
            launch_returncode=returncode,
            replayed=True,
            reason=f"replayed_{outcome}",
            message_id=request.message_id,
            idempotency_key=idempotency_key,
            event_id=event.event_id,
            cleanup_state=cleanup_state,
            origin_surface=request.origin_surface,
            operator_attestation_ref=request.operator_attestation_ref,
            crow_chat_attestation_required=request.require_crow_chat_attestation,
        )
    return None


def _accept_dispatch_message(request: DispatchLaunchRequest, *, idempotency_key: str) -> None:
    row = _load_and_validate_message(request, write=True)
    state = str(row["state"])
    if state == "processed":
        raise CoordDispatchError("mq_dispatch_already_processed_without_replay")
    if state in {"deferred", "escalated"}:
        raise CoordDispatchError(f"mq_dispatch_not_consumable:{state}")

    now = _now_iso()
    with sqlite3.connect(str(request.mq_db_path), timeout=5.0) as conn:
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE recipients
            SET state = 'accepted',
                reason = :reason,
                updated_at = :now
            WHERE message_id = :message_id
              AND recipient = :recipient
              AND state IN ('offered', 'read', 'accepted')
            """,
            {
                "reason": f"coord_dispatch_accepted:{idempotency_key}",
                "now": now,
                "message_id": request.message_id,
                "recipient": request.normalized_lane,
            },
        )
        if conn.total_changes != 1:
            conn.rollback()
            raise CoordDispatchError("mq_dispatch_consume_race")
        conn.commit()


def _cleanup_dispatch_message(
    request: DispatchLaunchRequest,
    *,
    idempotency_key: str,
    state: Literal["processed", "deferred"],
    returncode: int,
) -> None:
    now = _now_iso()
    reason = f"coord_dispatch_launch_{state}:{returncode}:{idempotency_key}"
    with sqlite3.connect(str(request.mq_db_path), timeout=5.0) as conn:
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            UPDATE recipients
            SET state = :state,
                reason = :reason,
                updated_at = :now
            WHERE message_id = :message_id
              AND recipient = :recipient
              AND state = 'accepted'
            """,
            {
                "state": state,
                "reason": reason,
                "now": now,
                "message_id": request.message_id,
                "recipient": request.normalized_lane,
            },
        )
        if cursor.rowcount != 1:
            conn.rollback()
            raise CoordDispatchError("mq_dispatch_cleanup_race")
        conn.commit()


def _load_and_validate_message(
    request: DispatchLaunchRequest,
    *,
    write: bool,
) -> sqlite3.Row:
    if not request.mq_db_path.exists():
        raise CoordDispatchError("durable_mq_database_missing")
    ensure_schema(request.mq_db_path)
    mode = "" if write else "?mode=ro"
    uri = f"file:{request.mq_db_path}{mode}" if mode else str(request.mq_db_path)
    with sqlite3.connect(uri, uri=bool(mode), timeout=5.0) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        if not write:
            conn.execute("PRAGMA query_only = ON")
        row = conn.execute(
            """
            SELECT m.message_id,
                   m.message_type,
                   m.authority_case,
                   m.authority_item,
                   m.subject,
                   m.stale_after,
                   m.expires_at,
                   r.recipient,
                   r.state
            FROM messages m
            JOIN recipients r ON r.message_id = m.message_id
            WHERE m.message_id = :message_id
              AND r.recipient = :recipient
            """,
            {
                "message_id": request.message_id,
                "recipient": request.normalized_lane,
            },
        ).fetchone()
    if row is None:
        raise CoordDispatchError("strict_mq_message_id_mismatch")
    _validate_message_row(request, row)
    return row


def _validate_message_row(request: DispatchLaunchRequest, row: sqlite3.Row) -> None:
    if row["message_type"] != "dispatch":
        raise CoordDispatchError("mq_message_type_mismatch")
    if row["authority_case"] != request.authority_case:
        raise CoordDispatchError("mq_authority_case_mismatch")
    expected_items = {request.task_id}
    if request.authority_item:
        expected_items.add(request.authority_item)
    authority_item = row["authority_item"]
    subject = row["subject"]
    if authority_item not in expected_items and subject != request.task_id:
        raise CoordDispatchError("mq_authority_item_mismatch")

    now = datetime.now(UTC)
    expires_at = _parse_datetime(row["expires_at"])
    stale_after = _parse_datetime(row["stale_after"])
    if expires_at is None or stale_after is None:
        raise CoordDispatchError("durable_mq_freshness_unknown")
    if expires_at < now:
        raise CoordDispatchError("durable_mq_dispatch_expired")
    if stale_after < now:
        raise CoordDispatchError("durable_mq_dispatch_stale")


def _append_dispatch_event(
    request: DispatchLaunchRequest,
    *,
    idempotency_key: str,
    outcome: Literal["started", "succeeded", "failed"],
    returncode: int | None,
) -> str:
    event_type = f"coord_dispatch.launch_{outcome}"
    event_id = _event_id(idempotency_key, outcome)
    event = CoordEvent(
        event_id=event_id,
        timestamp=_now_z(),
        event_type=event_type,
        actor=request.normalized_lane,
        subject=request.task_id,
        authority_case=request.authority_case,
        parent_spec=request.parent_spec,
        payload={
            "idempotency_key": idempotency_key,
            "message_id": request.message_id,
            "platform": request.platform,
            "mode": request.mode,
            "profile": request.profile,
            "outcome": outcome,
            "returncode": returncode,
            "origin_surface": request.origin_surface,
            "operator_attestation_ref": request.operator_attestation_ref,
            "crow_chat_attestation_required": request.require_crow_chat_attestation,
        },
    )
    try:
        request.event_log.append(
            event,
            writer=CoordWriter.daemon("hapax-methodology-dispatch"),
            fail_open=True,
        )
    except DuplicateEventError:
        pass
    except Exception as exc:
        raise CoordDispatchError(
            f"coord_event_log_append_failed:{type(exc).__name__}:{exc}"
        ) from exc
    return event_id


def _event_id(idempotency_key: str, outcome: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:32]
    return f"coord-dispatch-{digest}-{outcome}"


def _parse_datetime(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _now_z() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "CoordDispatchError",
    "DispatchLaunchRequest",
    "DispatchLaunchResult",
    "default_idempotency_key",
    "replay_terminal_result",
    "run_atomic_dispatch_launch",
]
