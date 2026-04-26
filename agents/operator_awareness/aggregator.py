"""Awareness state aggregator — pulls from sources with graceful degradation.

Each per-source helper is defensive: missing file / corrupt JSON /
unreachable backend returns the corresponding empty block rather
than raising. Goal: no aggregator failure can crash the runner; a
broken source produces an empty block that downstream surfaces dim
on (per the TTL semantics in ``state.py``).

This Phase-2 ship wires 3 concrete sources (refusals_recent,
health_system, stream) and leaves the remaining 5 sources as
default-empty blocks for Phase 3 follow-ups. Each source is
independently testable; the ``Aggregator.collect()`` orchestrator
composes them into a single ``AwarenessState`` per tick.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from prometheus_client import Counter

from agents.operator_awareness.sources.monetization import (
    collect_monetization_block,
)
from agents.operator_awareness.state import (
    AwarenessState,
    HealthBlock,
    RefusalEvent,
    StreamBlock,
)
from agents.payment_processors.event_log import DEFAULT_PAYMENT_LOG_PATH

log = logging.getLogger(__name__)

# Spec acceptance criterion: per-source failure counter so operators
# (Grafana, alerting) can see "the awareness daemon's stream source
# has been failing for the last 5 minutes" without scraping the
# daemon log. Each source helper increments under its own label on
# the degraded-graceful path (file missing / malformed / OSError).
aggregator_source_failures_total = Counter(
    "hapax_awareness_aggregator_source_failures_total",
    "Awareness aggregator per-source helper failures (graceful degradation events).",
    ["source"],
)

DEFAULT_REFUSALS_LOG = Path(
    os.environ.get(
        "HAPAX_REFUSALS_LOG_PATH",
        "/dev/shm/hapax-refusals/log.jsonl",
    )
)
DEFAULT_INFRA_SNAPSHOT = Path(
    os.environ.get(
        "HAPAX_INFRA_SNAPSHOT_PATH",
        str(Path.home() / "hapax-state/infra-snapshot.json"),
    )
)
DEFAULT_CHRONICLE_EVENTS = Path(
    os.environ.get(
        "HAPAX_CHRONICLE_EVENTS_PATH",
        "/dev/shm/hapax-chronicle/events.jsonl",
    )
)

# Bounded tail length for the refusals_recent block. Spec: 50 entries.
# Surfaces (waybar, sidebar, omg.lol fanout) display individuals; we
# cap to avoid unbounded JSON growth on a long-running daemon.
REFUSALS_TAIL_LIMIT = 50

# Stream block window for chronicle event count. Spec: 5min.
STREAM_EVENT_WINDOW_S = 300.0


def collect_refusals_recent(
    log_path: Path = DEFAULT_REFUSALS_LOG,
    *,
    limit: int = REFUSALS_TAIL_LIMIT,
) -> list[RefusalEvent]:
    """Tail the last ``limit`` valid RefusalEvents from the log.

    Reads the JSONL line-by-line and keeps the last ``limit`` valid
    events (a deque caps memory). Malformed lines are skipped at
    debug level. Missing file → empty list (the daemon hasn't
    written yet, or refusal-as-data is in pre-rollout state).
    """
    if not log_path.exists():
        # Pre-rollout state — not a failure; do not increment metric.
        return []
    tail: deque[RefusalEvent] = deque(maxlen=limit)
    try:
        with log_path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                text = raw.strip()
                if not text:
                    continue
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    log.debug("malformed refusal-log line skipped")
                    continue
                event = _parse_refusal(data)
                if event is not None:
                    tail.append(event)
    except OSError:
        log.warning("refusals log read failed at %s", log_path, exc_info=True)
        aggregator_source_failures_total.labels(source="refusals_recent").inc()
        return []
    return list(tail)


def _parse_refusal(data: object) -> RefusalEvent | None:
    if not isinstance(data, dict):
        return None
    try:
        ts_raw = data["timestamp"]
        surface = str(data["surface"])
        reason = str(data["reason"])
    except (KeyError, TypeError):
        return None
    timestamp = _parse_iso8601(ts_raw)
    if timestamp is None:
        return None
    slug = data.get("refused_artifact_slug")
    return RefusalEvent(
        timestamp=timestamp,
        surface=surface,
        reason=reason,
        refused_artifact_slug=str(slug) if slug else None,
    )


def _parse_iso8601(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def collect_health_block(
    snapshot_path: Path = DEFAULT_INFRA_SNAPSHOT,
) -> HealthBlock:
    """Build the HealthBlock from infra-snapshot.json (host-written).

    Schema (existing snapshot writer): ``{"systemd": {...},
    "docker": {...}, "disk": {...}, "gpu": {used_mb, total_mb}}``.
    Missing file or malformed JSON → empty block with overall_status
    "unknown" — surfaces dim until the snapshot becomes available.
    """
    if not snapshot_path.exists():
        # Pre-rollout — health collector not yet active; not a failure.
        return HealthBlock()
    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.debug("infra snapshot unreadable at %s", snapshot_path)
        aggregator_source_failures_total.labels(source="health_system").inc()
        return HealthBlock()
    if not isinstance(data, dict):
        aggregator_source_failures_total.labels(source="health_system").inc()
        return HealthBlock()
    failed_units = _safe_int(data.get("systemd", {}).get("failed_count"))
    docker_failed = _safe_int(data.get("docker", {}).get("failed_count"))
    disk_pct = _safe_float(data.get("disk", {}).get("pct_used"))
    gpu = data.get("gpu") or {}
    gpu_used = _safe_int(gpu.get("used_mb"))
    gpu_total = _safe_int(gpu.get("total_mb"))
    gpu_pct = (gpu_used / gpu_total * 100.0) if gpu_total > 0 else 0.0
    overall = _classify_health(failed_units, docker_failed, disk_pct, gpu_pct)
    return HealthBlock(
        overall_status=overall,
        failed_units=failed_units,
        docker_containers_failed=docker_failed,
        disk_pct_used=disk_pct,
        gpu_vram_pct_used=gpu_pct,
    )


def _classify_health(
    failed_units: int,
    docker_failed: int,
    disk_pct: float,
    gpu_pct: float,
) -> str:
    """Coarse 4-state classification from raw signals.

    Critical when systemd has failed units OR disk over 90%.
    Degraded when docker has any failed container OR disk over 80% OR
    GPU VRAM over 95%. Otherwise healthy. Unknown reserved for the
    missing-snapshot case (caller returns default block).
    """
    if failed_units > 0 or disk_pct >= 90.0:
        return "critical"
    if docker_failed > 0 or disk_pct >= 80.0 or gpu_pct >= 95.0:
        return "degraded"
    return "healthy"


def collect_stream_block(
    chronicle_path: Path = DEFAULT_CHRONICLE_EVENTS,
    *,
    window_s: float = STREAM_EVENT_WINDOW_S,
    now: float | None = None,
) -> StreamBlock:
    """Count chronicle events in the last ``window_s`` seconds.

    Live indicator semantic: any chronicle event in the window means
    the broadcast is live. Empty file or no events in window means
    the stream is offline. Missing chronicle path → live=False with
    zero events (chronicle daemon hasn't started, or stream is
    genuinely offline).
    """
    if not chronicle_path.exists():
        return StreamBlock()
    cutoff = (now if now is not None else time.time()) - window_s
    count = 0
    try:
        with chronicle_path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                text = raw.strip()
                if not text:
                    continue
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    continue
                ts = _safe_float(data.get("ts"))
                if ts >= cutoff:
                    count += 1
    except OSError:
        log.debug("chronicle read failed at %s", chronicle_path)
        aggregator_source_failures_total.labels(source="stream").inc()
        return StreamBlock()
    return StreamBlock(live=count > 0, chronicle_events_5min=count)


def _safe_int(value: object) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _safe_float(value: object) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


class Aggregator:
    """Compose per-source helpers into one ``AwarenessState`` per tick.

    Constructor parameters
    ----------------------
    refusals_log_path / infra_snapshot_path / chronicle_events_path:
        Source overrides; defaults read from env vars / spec paths.
    clock:
        ``() -> datetime`` for the state.timestamp field. Tests
        inject a fixed clock; production uses ``datetime.now(UTC)``.
    """

    def __init__(
        self,
        *,
        refusals_log_path: Path = DEFAULT_REFUSALS_LOG,
        infra_snapshot_path: Path = DEFAULT_INFRA_SNAPSHOT,
        chronicle_events_path: Path = DEFAULT_CHRONICLE_EVENTS,
        monetization_log_path: Path = DEFAULT_PAYMENT_LOG_PATH,
        clock=None,
    ) -> None:
        self._refusals_log_path = refusals_log_path
        self._infra_snapshot_path = infra_snapshot_path
        self._chronicle_events_path = chronicle_events_path
        self._monetization_log_path = monetization_log_path
        self._clock = clock or (lambda: datetime.now(UTC))

    def collect(self) -> AwarenessState:
        """Build one AwarenessState by pulling each source.

        Phase 2 wires 3 source helpers (refusals, health, stream)
        plus the Phase-money-rails monetization source. Remaining
        sub-blocks fall through to AwarenessState's default
        factories (empty-typed instances) — surfaces see
        dimmed/empty blocks for those categories until they're
        wired.
        """
        return AwarenessState(
            timestamp=self._clock(),
            refusals_recent=collect_refusals_recent(self._refusals_log_path),
            health_system=collect_health_block(self._infra_snapshot_path),
            stream=collect_stream_block(self._chronicle_events_path),
            monetization=collect_monetization_block(self._monetization_log_path),
        )


__all__ = [
    "DEFAULT_CHRONICLE_EVENTS",
    "DEFAULT_INFRA_SNAPSHOT",
    "DEFAULT_REFUSALS_LOG",
    "REFUSALS_TAIL_LIMIT",
    "STREAM_EVENT_WINDOW_S",
    "Aggregator",
    "aggregator_source_failures_total",
    "collect_health_block",
    "collect_refusals_recent",
    "collect_stream_block",
]
