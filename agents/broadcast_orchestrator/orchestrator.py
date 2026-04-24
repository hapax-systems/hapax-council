"""Broadcast boundary orchestration state machine.

State diagram (spec §5)::

    INACTIVE → ACTIVE → ROTATING_NEW → ROTATING_OLD → ACTIVE
                  ↑                                       │
                  └────── ERROR ◀── failure path ◀───────┘

ACTIVE polls every tick. When elapsed >= rotation interval, the
rotation runs through INSERT → BIND → TRANSITION_TESTING →
TRANSITION_LIVE → TRANSITION_OLD_COMPLETE → UPDATE_METADATA. Any
step's failure stays in ROTATING_NEW (or _OLD) and retries next tick.

Past 12h with no successful rotation, the outgoing VOD is dropped by
YouTube — this is logged + ntfy'd (CRITICAL) but the orchestrator
keeps trying so the next rotation still lands.
"""

from __future__ import annotations

import enum
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from . import api
from .events import emit
from .metadata_seed import SeedMetadata, compose

log = logging.getLogger(__name__)

ROTATION_S = int(os.environ.get("HAPAX_BROADCAST_ROTATION_S", "39600"))
PRIVACY_STATUS = os.environ.get("HAPAX_BROADCAST_PRIVACY_STATUS", "public")
STREAM_ID_ENV = os.environ.get("HAPAX_BROADCAST_STREAM_ID", "").strip() or None
VOD_LOSS_THRESHOLD_S = 12 * 3600
RETRY_LIMIT = 3


class State(enum.Enum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    ROTATING_NEW = "rotating_new"
    ROTATING_OLD = "rotating_old"
    ERROR = "error"


@dataclass
class _Tracking:
    state: State = State.INACTIVE
    active_broadcast_id: str | None = None
    active_started_ts: float | None = None
    incoming_broadcast_id: str | None = None
    incoming_seed: SeedMetadata | None = None
    rotation_attempt: int = 0
    rotation_started_ts: float | None = None
    last_rotation_ts: float | None = None
    segment_counter: int = 0
    cached_stream_id: str | None = STREAM_ID_ENV
    vod_loss_alerted_for: set[str] = field(default_factory=set)


try:
    from prometheus_client import Counter, Gauge, Histogram

    ROTATIONS_TOTAL = Counter(
        "hapax_broadcast_rotations_total",
        "Broadcast rotations attempted, broken down by outcome.",
        ["result"],
    )
    ACTIVE_ELAPSED = Gauge(
        "hapax_broadcast_active_broadcast_elapsed_s",
        "Seconds since the active broadcast started.",
    )
    ROTATION_DURATION = Histogram(
        "hapax_broadcast_rotation_duration_s",
        "End-to-end rotation duration in seconds.",
    )
    VOD_LOST = Counter(
        "hapax_broadcast_vod_lost_total",
        "Outgoing broadcasts whose VOD passed the 12h archive cap before completion.",
    )
    ORCH_STATE = Gauge(
        "hapax_broadcast_orchestrator_state",
        "Current state encoded as enum value index.",
    )

    def _record_rotation(result: str) -> None:
        ROTATIONS_TOTAL.labels(result=result).inc()

    def _record_state(state: State) -> None:
        ORCH_STATE.set(list(State).index(state))

    def _record_active_elapsed(secs: float) -> None:
        ACTIVE_ELAPSED.set(secs)

    def _record_rotation_duration(secs: float) -> None:
        ROTATION_DURATION.observe(secs)

    def _record_vod_lost() -> None:
        VOD_LOST.inc()
except ImportError:

    def _record_rotation(result: str) -> None:
        pass

    def _record_state(state: State) -> None:
        pass

    def _record_active_elapsed(secs: float) -> None:
        pass

    def _record_rotation_duration(secs: float) -> None:
        pass

    def _record_vod_lost() -> None:
        pass


def _ntfy(priority: str, message: str) -> None:
    """Send ntfy alert via :func:`shared.notify.send_notification` if available."""
    try:
        from shared.notify import send_notification

        send_notification(message, priority=priority, topic="hapax-broadcast")
    except Exception:
        log.exception("ntfy failed: %s", message)


class Orchestrator:
    """Drive the broadcast rotation FSM. One tick per ``run_once`` call."""

    def __init__(
        self,
        client: Any,
        rotation_s: int = ROTATION_S,
        privacy_status: str = PRIVACY_STATUS,
        retry_limit: int = RETRY_LIMIT,
        time_fn: Any = time.time,
    ) -> None:
        self._client = client
        self._rotation_s = rotation_s
        self._privacy_status = privacy_status
        self._retry_limit = retry_limit
        self._time = time_fn
        self._tracking = _Tracking()
        _record_state(self._tracking.state)

    @property
    def state(self) -> State:
        return self._tracking.state

    @property
    def tracking(self) -> _Tracking:
        return self._tracking

    def _set_state(self, state: State) -> None:
        if state != self._tracking.state:
            log.info("state %s → %s", self._tracking.state.value, state.value)
        self._tracking.state = state
        _record_state(state)

    def run_once(self) -> None:
        """Execute one orchestrator tick."""
        if not self._client.enabled:
            log.debug("client disabled (no creds); skipping tick")
            return
        if self._tracking.state == State.INACTIVE:
            self._discover()
        if self._tracking.state == State.ACTIVE:
            self._tick_active()
        if self._tracking.state == State.ROTATING_NEW:
            self._continue_rotation_new()
        if self._tracking.state == State.ROTATING_OLD:
            self._continue_rotation_old()

    def _discover(self) -> None:
        active = api.list_active_broadcasts(self._client)
        if not active:
            log.info("no active broadcast — staying INACTIVE")
            return
        chosen = active[0]
        self._tracking.active_broadcast_id = chosen.get("id")
        snippet = chosen.get("snippet", {})
        actual_start = snippet.get("actualStartTime") or snippet.get("scheduledStartTime")
        parsed = _parse_iso8601(actual_start) if actual_start else None
        self._tracking.active_started_ts = parsed if parsed is not None else self._time()
        if not self._tracking.cached_stream_id:
            self._tracking.cached_stream_id = api.discover_stream_id(self._client)
        self._set_state(State.ACTIVE)
        log.info(
            "discovered active broadcast id=%s started=%s stream_id=%s",
            self._tracking.active_broadcast_id,
            actual_start,
            self._tracking.cached_stream_id,
        )

    def _elapsed(self) -> float:
        if self._tracking.active_started_ts is None:
            return 0.0
        return max(0.0, self._time() - self._tracking.active_started_ts)

    def _tick_active(self) -> None:
        elapsed = self._elapsed()
        _record_active_elapsed(elapsed)
        if elapsed < self._rotation_s:
            return
        if not self._tracking.cached_stream_id:
            log.error(
                "rotation due but stream_id unknown; set HAPAX_BROADCAST_STREAM_ID "
                "or wait for liveStreams.list discovery"
            )
            _ntfy(
                "high",
                "broadcast orchestrator: rotation due but stream_id unavailable",
            )
            return
        log.info("elapsed %.0fs >= %ds — beginning rotation", elapsed, self._rotation_s)
        self._tracking.rotation_started_ts = self._time()
        self._tracking.rotation_attempt = 0
        self._tracking.segment_counter += 1
        self._tracking.incoming_seed = compose(segment_index=self._tracking.segment_counter)
        self._set_state(State.ROTATING_NEW)
        self._continue_rotation_new()

    def _continue_rotation_new(self) -> None:
        if self._tracking.incoming_broadcast_id is None:
            inserted = api.insert_broadcast(
                self._client,
                seed=self._tracking.incoming_seed,
                privacy_status=self._privacy_status,
                scheduled_start_iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
            if inserted is None or "id" not in inserted:
                self._fail_rotation_step("insert")
                return
            self._tracking.incoming_broadcast_id = inserted["id"]
            log.info("rotation: inserted incoming id=%s", inserted["id"])

        bound = api.bind_broadcast(
            self._client,
            broadcast_id=self._tracking.incoming_broadcast_id,
            stream_id=self._tracking.cached_stream_id,
        )
        if bound is None:
            self._fail_rotation_step("bind")
            return

        if not _transition_to(self._client, self._tracking.incoming_broadcast_id, "testing"):
            self._fail_rotation_step("transition_testing")
            return
        if not _transition_to(self._client, self._tracking.incoming_broadcast_id, "live"):
            self._fail_rotation_step("transition_live")
            return

        log.info("rotation: incoming live id=%s", self._tracking.incoming_broadcast_id)
        self._set_state(State.ROTATING_OLD)
        self._continue_rotation_old()

    def _continue_rotation_old(self) -> None:
        outgoing_id = self._tracking.active_broadcast_id
        if outgoing_id is None:
            log.warning("no outgoing broadcast id; skipping completion")
            self._finalize_rotation()
            return
        if not _transition_to(self._client, outgoing_id, "complete"):
            self._fail_rotation_step("transition_complete")
            self._maybe_alert_vod_lost(outgoing_id)
            return
        log.info("rotation: outgoing complete id=%s", outgoing_id)
        if self._tracking.incoming_seed is not None and self._tracking.incoming_broadcast_id:
            api.update_video_metadata(
                self._client,
                broadcast_id=self._tracking.incoming_broadcast_id,
                seed=self._tracking.incoming_seed,
            )
        self._finalize_rotation()

    def _finalize_rotation(self) -> None:
        outgoing_id = self._tracking.active_broadcast_id
        incoming_id = self._tracking.incoming_broadcast_id
        seed = self._tracking.incoming_seed
        duration_s = self._time() - (self._tracking.rotation_started_ts or self._time())
        emit(
            "broadcast_rotated",
            outgoing_broadcast_id=outgoing_id,
            outgoing_vod_url=api.vod_url(outgoing_id) if outgoing_id else None,
            incoming_broadcast_id=incoming_id,
            incoming_broadcast_url=api.vod_url(incoming_id) if incoming_id else None,
            elapsed_s=int(self._elapsed()),
            seed_title=seed.title if seed else None,
            seed_description_digest=_digest(seed.description) if seed else None,
        )
        _record_rotation_duration(duration_s)
        _record_rotation("ok")
        self._tracking.active_broadcast_id = incoming_id
        self._tracking.active_started_ts = self._time()
        self._tracking.last_rotation_ts = self._time()
        self._tracking.incoming_broadcast_id = None
        self._tracking.incoming_seed = None
        self._tracking.rotation_started_ts = None
        self._tracking.rotation_attempt = 0
        self._set_state(State.ACTIVE)
        log.info("rotation complete: new active=%s (duration %.1fs)", incoming_id, duration_s)

    def _fail_rotation_step(self, step: str) -> None:
        self._tracking.rotation_attempt += 1
        _record_rotation(f"failed_{step}")
        if self._tracking.rotation_attempt >= self._retry_limit:
            log.error(
                "rotation step %s failed %d× — staying in %s, will retry next tick",
                step,
                self._tracking.rotation_attempt,
                self._tracking.state.value,
            )
            _ntfy(
                "high",
                f"broadcast rotation step {step} failed {self._tracking.rotation_attempt}× "
                "— next tick retries",
            )
            self._tracking.rotation_attempt = 0

    def _maybe_alert_vod_lost(self, outgoing_id: str) -> None:
        if outgoing_id in self._tracking.vod_loss_alerted_for:
            return
        if self._elapsed() < VOD_LOSS_THRESHOLD_S:
            return
        log.error("VOD likely lost: outgoing %s past 12h archive cap", outgoing_id)
        _record_vod_lost()
        _ntfy(
            "max",
            f"broadcast VOD lost: id={outgoing_id} past 12h cap before rotation completed",
        )
        self._tracking.vod_loss_alerted_for.add(outgoing_id)


def _transition_to(client: Any, broadcast_id: str, status: str) -> bool:
    resp = api.transition_broadcast(client, broadcast_id=broadcast_id, status=status)
    if resp is None:
        return False
    actual = resp.get("status", {}).get("lifeCycleStatus")
    return actual == status or actual is None


def _parse_iso8601(value: str) -> float | None:
    """Parse an ISO-8601 timestamp into epoch seconds; ``None`` if malformed.

    YouTube returns clean ISO-8601, but defensive parsing avoids a tick
    crash if the API ever shifts a format detail.
    """
    import datetime as dt

    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return dt.datetime.fromisoformat(value).timestamp()
    except (ValueError, TypeError):
        log.warning("failed to parse broadcast start timestamp %r", value)
        return None


def _digest(text: str) -> str:
    """Stable short hex digest of `text`. blake2b is deterministic across
    Python processes (unlike ``hash()``), so consumers can compare digests
    across orchestrator restarts.
    """
    import hashlib

    return hashlib.blake2b(text.encode("utf-8"), digest_size=8).hexdigest()
