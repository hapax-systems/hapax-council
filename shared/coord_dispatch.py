"""Atomic coordination dispatch binding, MQ consumption, and launch replay."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from shared.coord_event_log import CoordEvent, CoordEventLog, CoordWriter, DuplicateEventError
from shared.relay_lifecycle import lane_is_retired, parse_relay_document
from shared.relay_mq import (
    COORDINATOR_ACCEPTED_DISPATCH_REASON_PREFIX,
    COORDINATOR_PREPARED_DISPATCH_REASON,
    ensure_schema,
)

TERMINAL_EVENT_TYPES = {
    "coord_dispatch.launch_succeeded",
    "coord_dispatch.launch_failed",
}
DISPATCH_PREPARATION_BINDING_SCHEMA = "hapax.coord-dispatch-preparation.v1"


class CoordDispatchError(RuntimeError):
    """Base error for coordination dispatch fusion failures."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


@dataclass(frozen=True)
class DispatchPreparationBinding:
    """Exact task/lane preimage carried by the coordinator MQ message."""

    task_id: str
    task_path: str
    task_sha256: str
    lane: str
    lane_session: str
    lane_generation: str
    lane_pid: int | None
    lane_pid_generation: str
    claim_projection_sha256: str
    relay_projection_sha256: str
    platform: str
    mode: str
    authority_case: str
    authority_item: str
    parent_spec: str

    def body(self) -> dict[str, object]:
        return {
            "authority_case": self.authority_case,
            "authority_item": self.authority_item,
            "claim_projection_sha256": self.claim_projection_sha256,
            "lane": self.lane,
            "lane_generation": self.lane_generation,
            "lane_pid": self.lane_pid,
            "lane_pid_generation": self.lane_pid_generation,
            "lane_session": self.lane_session,
            "may_authorize": False,
            "mode": self.mode,
            "parent_spec": self.parent_spec,
            "platform": self.platform,
            "relay_projection_sha256": self.relay_projection_sha256,
            "schema": DISPATCH_PREPARATION_BINDING_SCHEMA,
            "task_id": self.task_id,
            "task_path": self.task_path,
            "task_sha256": self.task_sha256,
        }

    @property
    def binding_hash(self) -> str:
        return hashlib.sha256(_canonical_json_bytes(self.body())).hexdigest()

    def to_record(self) -> dict[str, object]:
        return {**self.body(), "binding_hash": self.binding_hash}

    @classmethod
    def from_record(cls, value: object) -> DispatchPreparationBinding:
        if not isinstance(value, dict):
            raise CoordDispatchError("dispatch_preparation_binding_malformed")
        exact_keys = {
            "authority_case",
            "authority_item",
            "binding_hash",
            "claim_projection_sha256",
            "lane",
            "lane_generation",
            "lane_pid",
            "lane_pid_generation",
            "lane_session",
            "may_authorize",
            "mode",
            "parent_spec",
            "platform",
            "relay_projection_sha256",
            "schema",
            "task_id",
            "task_path",
            "task_sha256",
        }
        if (
            set(value) != exact_keys
            or value.get("schema") != DISPATCH_PREPARATION_BINDING_SCHEMA
            or value.get("may_authorize") is not False
            or not isinstance(value.get("lane_pid"), int | type(None))
        ):
            raise CoordDispatchError("dispatch_preparation_binding_malformed")
        binding = cls(
            task_id=str(value["task_id"]),
            task_path=str(value["task_path"]),
            task_sha256=str(value["task_sha256"]),
            lane=str(value["lane"]),
            lane_session=str(value["lane_session"]),
            lane_generation=str(value["lane_generation"]),
            lane_pid=value["lane_pid"],
            lane_pid_generation=str(value["lane_pid_generation"]),
            claim_projection_sha256=str(value["claim_projection_sha256"]),
            relay_projection_sha256=str(value["relay_projection_sha256"]),
            platform=str(value["platform"]),
            mode=str(value["mode"]),
            authority_case=str(value["authority_case"]),
            authority_item=str(value["authority_item"]),
            parent_spec=str(value["parent_spec"]),
        )
        required = (
            binding.task_id,
            binding.task_path,
            binding.lane,
            binding.platform,
            binding.mode,
            binding.authority_case,
        )
        if (
            any(not item.strip() for item in required)
            or re.fullmatch(r"[0-9a-f]{64}", binding.task_sha256) is None
            or re.fullmatch(r"[0-9a-f]{64}", binding.claim_projection_sha256) is None
            or re.fullmatch(r"[0-9a-f]{64}", binding.relay_projection_sha256) is None
            or value["binding_hash"] != binding.binding_hash
        ):
            raise CoordDispatchError("dispatch_preparation_binding_malformed")
        return binding


def dispatch_preparation_binding_from_payload(payload: object) -> DispatchPreparationBinding:
    if not isinstance(payload, str):
        raise CoordDispatchError("dispatch_preparation_payload_missing")

    def unique_pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        decoded: dict[str, object] = {}
        for key, value in values:
            if key in decoded:
                raise CoordDispatchError("dispatch_preparation_payload_duplicate_key")
            decoded[key] = value
        return decoded

    try:
        decoded = json.loads(payload, object_pairs_hook=unique_pairs)
    except CoordDispatchError:
        raise
    except json.JSONDecodeError as exc:
        raise CoordDispatchError("dispatch_preparation_payload_malformed") from exc
    if not isinstance(decoded, dict):
        raise CoordDispatchError("dispatch_preparation_payload_malformed")
    return DispatchPreparationBinding.from_record(decoded.get("dispatch_binding"))


def lane_ownership_projection_hashes(
    *,
    cache_dir: Path,
    relay_dir: Path,
    role: str,
    session: str,
) -> tuple[str, str]:
    """Hash ownership-relevant claim and relay projections for mutation recheck."""

    claim_records: list[dict[str, str]] = []
    try:
        legacy = cache_dir / f"cc-active-task-{role}"
        claim_paths = [legacy, *sorted(cache_dir.glob(f"cc-active-task-{role}-*"))]
        claim_paths = list(dict.fromkeys(path for path in claim_paths if path.exists()))
    except OSError as exc:
        raise CoordDispatchError("lane_claim_projection_unreadable") from exc
    for path in claim_paths:
        try:
            if not path.is_file() or path.is_symlink():
                raise OSError("claim projection is not a regular file")
            content = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise CoordDispatchError("lane_claim_projection_unreadable") from exc
        claim_records.append({"name": path.name, "task_id": content})

    relay_names = [
        f"{role}-status.yaml",
        f"{role}.yaml",
        f"status-{role}.yaml",
        f"peer-status-{role}.yaml",
    ]
    if session:
        relay_names.append(f"peer-status-{session}.yaml")
    freshest: Path | None = None
    freshest_key: tuple[float, str] | None = None
    for name in relay_names:
        path = relay_dir / name
        try:
            key = (path.stat().st_mtime, path.name)
        except OSError:
            continue
        if freshest_key is None or key > freshest_key:
            freshest = path
            freshest_key = key
    relay_record: dict[str, object] = {"name": None, "ownership": {}}
    if freshest is not None:
        try:
            relay = parse_relay_document(freshest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            raise CoordDispatchError("lane_relay_projection_unreadable") from exc
        ownership_keys = (
            "current_claim",
            "current_task",
            "currently_working_on",
            "relay_status",
            "role",
            "session_state",
            "session_status",
            "state",
            "status",
        )
        relay_record = {
            "name": freshest.name,
            "ownership": {key: relay.get(key) for key in ownership_keys if key in relay},
        }
    return (
        hashlib.sha256(_canonical_json_bytes(claim_records)).hexdigest(),
        hashlib.sha256(_canonical_json_bytes(relay_record)).hexdigest(),
    )


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
    binding_hash: str | None = None
    reactivate_retired: bool = False

    def __post_init__(self) -> None:
        for name in ("task_id", "lane", "platform", "mode", "profile", "authority_case"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if not self.message_id.strip():
            raise CoordDispatchError("strict_mq_message_id_required")
        if (
            self.binding_hash is not None
            and re.fullmatch(r"[0-9a-f]{64}", self.binding_hash) is None
        ):
            raise CoordDispatchError("dispatch_preparation_binding_hash_invalid")

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
    _refuse_inflight_idempotency_key(request, idempotency_key=key)

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
    )


def finalize_accepted_dispatch_on_pickup(
    request: DispatchLaunchRequest,
) -> DispatchLaunchResult:
    """Finalize a launch whose synchronous dispatcher timed out after live pickup.

    The coordinator may use this only after exact lane/claim pickup evidence. The
    MQ row must already be accepted by this request's idempotency key and the
    canonical event log must contain its launch-started event.
    """
    row = _load_and_validate_message(request, write=True)
    state = str(row["state"])
    reason = str(row["reason"] or "")
    if state == "accepted" and reason.startswith(COORDINATOR_ACCEPTED_DISPATCH_REASON_PREFIX):
        key = reason.removeprefix(COORDINATOR_ACCEPTED_DISPATCH_REASON_PREFIX)
    elif state == "processed":
        match = re.fullmatch(r"coord_dispatch_launch_processed:0:(.+)", reason)
        if match is None:
            raise CoordDispatchError("pickup_finalize_processed_identity_mismatch")
        key = match.group(1)
        replayed = _replay_terminal_result(request, idempotency_key=key, exact_route=False)
        if replayed is None:
            raise CoordDispatchError("pickup_finalize_terminal_event_missing")
        return replayed
    else:
        raise CoordDispatchError(f"pickup_finalize_requires_accepted:{state}")
    if not key:
        raise CoordDispatchError("pickup_finalize_acceptance_identity_mismatch")

    started = _find_event(request, _event_id(key, "started"))
    if (
        started is None
        or started.event_type != "coord_dispatch.launch_started"
        or started.payload.get("idempotency_key") != key
        or not _event_matches_request(started, request, exact_route=False)
    ):
        raise CoordDispatchError("pickup_finalize_started_event_missing")
    route_request = replace(
        request,
        platform=str(started.payload.get("platform", "")),
        mode=str(started.payload.get("mode", "")),
        profile=str(started.payload.get("profile", "")),
        idempotency_key=key,
    )
    if not all((route_request.platform, route_request.mode, route_request.profile)):
        raise CoordDispatchError("pickup_finalize_started_route_missing")

    _cleanup_dispatch_message(
        route_request,
        idempotency_key=key,
        state="processed",
        returncode=0,
    )
    event_id = _append_dispatch_event(
        route_request,
        idempotency_key=key,
        outcome="succeeded",
        returncode=0,
        completion_source="coordinator_verified_pickup_after_timeout",
    )
    return DispatchLaunchResult(
        launched=True,
        launch_returncode=0,
        replayed=False,
        reason="launch_succeeded_after_pickup",
        message_id=request.message_id,
        idempotency_key=key,
        event_id=event_id,
        cleanup_state="processed",
    )


def replay_terminal_result(
    request: DispatchLaunchRequest,
    *,
    idempotency_key: str,
) -> DispatchLaunchResult | None:
    """Replay a prior terminal launch result for ``idempotency_key``."""

    return _replay_terminal_result(request, idempotency_key=idempotency_key, exact_route=True)


def _replay_terminal_result(
    request: DispatchLaunchRequest,
    *,
    idempotency_key: str,
    exact_route: bool,
) -> DispatchLaunchResult | None:

    result = request.event_log.replay(fail_open=False)
    for event in reversed(result.events):
        if event.event_type not in TERMINAL_EVENT_TYPES:
            continue
        if event.payload.get("idempotency_key") != idempotency_key:
            continue
        if not _event_matches_request(event, request, exact_route=exact_route):
            raise CoordDispatchError("idempotency_key_request_identity_mismatch")
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
        )
    return None


def _refuse_inflight_idempotency_key(
    request: DispatchLaunchRequest,
    *,
    idempotency_key: str,
) -> None:
    event = _find_event(request, _event_id(idempotency_key, "started"))
    if event is None:
        return
    if not _event_matches_request(event, request, exact_route=True):
        raise CoordDispatchError("idempotency_key_request_identity_mismatch")
    raise CoordDispatchError("idempotency_key_in_flight")


def _accept_dispatch_message(request: DispatchLaunchRequest, *, idempotency_key: str) -> None:
    row = _load_and_validate_message(request, write=True)
    state = str(row["state"])
    reason = str(row["reason"] or "")
    if state == "processed":
        raise CoordDispatchError("mq_dispatch_already_processed_without_replay")
    if state == "accepted":
        raise CoordDispatchError("mq_dispatch_already_accepted_without_replay")
    coordinator_prepared = state == "deferred" and reason == COORDINATOR_PREPARED_DISPATCH_REASON
    if state in {"deferred", "escalated"} and not coordinator_prepared:
        raise CoordDispatchError(f"mq_dispatch_not_consumable:{state}")

    now = _now_iso()
    with sqlite3.connect(str(request.mq_db_path), timeout=5.0) as conn:
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            UPDATE recipients
            SET state = 'accepted',
                reason = :reason,
                updated_at = :now
            WHERE message_id = :message_id
              AND recipient = :recipient
              AND (
                  state IN ('offered', 'read')
                  OR (state = 'deferred' AND reason = :prepared_reason)
              )
            """,
            {
                "reason": f"{COORDINATOR_ACCEPTED_DISPATCH_REASON_PREFIX}{idempotency_key}",
                "prepared_reason": COORDINATOR_PREPARED_DISPATCH_REASON,
                "now": now,
                "message_id": request.message_id,
                "recipient": request.normalized_lane,
            },
        )
        if cursor.rowcount != 1:
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
              AND reason = :accepted_reason
            """,
            {
                "state": state,
                "reason": reason,
                "now": now,
                "message_id": request.message_id,
                "recipient": request.normalized_lane,
                "accepted_reason": (
                    f"{COORDINATOR_ACCEPTED_DISPATCH_REASON_PREFIX}{idempotency_key}"
                ),
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
                   m.sender,
                   m.message_type,
                   m.authority_case,
                   m.authority_item,
                   m.subject,
                   m.payload,
                   m.stale_after,
                   m.expires_at,
                   r.recipient,
                   r.state,
                   r.reason
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
    if subject != request.task_id:
        raise CoordDispatchError("mq_subject_task_mismatch")
    if authority_item not in expected_items:
        raise CoordDispatchError("mq_authority_item_mismatch")
    if request.binding_hash is not None:
        binding = dispatch_preparation_binding_from_payload(row["payload"])
        if binding.binding_hash != request.binding_hash:
            raise CoordDispatchError("dispatch_preparation_binding_hash_mismatch")
        if (
            binding.task_id != request.task_id
            or binding.lane.strip().lower().replace("_", "-") != request.normalized_lane
            or binding.authority_case != request.authority_case
            or binding.authority_item != (request.authority_item or request.task_id)
            or binding.parent_spec != (request.parent_spec or "")
        ):
            raise CoordDispatchError("dispatch_preparation_binding_identity_mismatch")

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
    completion_source: str | None = None,
) -> str:
    event_type = f"coord_dispatch.launch_{outcome}"
    event_id = _event_id(idempotency_key, outcome)
    payload = {
        "binding_hash": request.binding_hash,
        "idempotency_key": idempotency_key,
        "message_id": request.message_id,
        "platform": request.platform,
        "mode": request.mode,
        "profile": request.profile,
        "outcome": outcome,
        "returncode": returncode,
    }
    if completion_source:
        payload["completion_source"] = completion_source
    event = CoordEvent(
        event_id=event_id,
        timestamp=_now_z(),
        event_type=event_type,
        actor=request.normalized_lane,
        subject=request.task_id,
        authority_case=request.authority_case,
        parent_spec=request.parent_spec,
        payload=payload,
    )
    try:
        request.event_log.append(
            event,
            writer=CoordWriter.daemon("hapax-methodology-dispatch"),
            fail_open=False,
        )
    except DuplicateEventError:
        existing = _find_event(request, event_id)
        if existing is None or not _event_matches_request(
            existing,
            request,
            exact_route=True,
        ):
            raise CoordDispatchError("idempotency_key_request_identity_mismatch") from None
        if outcome == "started":
            raise CoordDispatchError("idempotency_key_in_flight") from None
    except Exception as exc:
        raise CoordDispatchError(
            f"coord_event_log_append_failed:{type(exc).__name__}:{exc}"
        ) from exc
    return event_id


def _find_event(request: DispatchLaunchRequest, event_id: str) -> CoordEvent | None:
    replay = request.event_log.replay(fail_open=False)
    return next((event for event in reversed(replay.events) if event.event_id == event_id), None)


def _event_matches_request(
    event: CoordEvent,
    request: DispatchLaunchRequest,
    *,
    exact_route: bool,
) -> bool:
    if (
        event.actor != request.normalized_lane
        or event.subject != request.task_id
        or event.authority_case != request.authority_case
        or event.parent_spec != request.parent_spec
        or event.payload.get("message_id") != request.message_id
        or event.payload.get("binding_hash") != request.binding_hash
    ):
        return False
    if not exact_route:
        return True
    return (
        event.payload.get("platform") == request.platform
        and event.payload.get("mode") == request.mode
        and event.payload.get("profile") == request.profile
    )


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
    "DispatchPreparationBinding",
    "DispatchLaunchRequest",
    "DispatchLaunchResult",
    "default_idempotency_key",
    "dispatch_preparation_binding_from_payload",
    "finalize_accepted_dispatch_on_pickup",
    "lane_ownership_projection_hashes",
    "replay_terminal_result",
    "run_atomic_dispatch_launch",
]
