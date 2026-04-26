"""Awareness state aggregator — pulls from sources with graceful degradation.

Each per-source helper is defensive: missing file / corrupt JSON /
unreachable backend returns the corresponding empty block rather
than raising. Goal: no aggregator failure can crash the runner; a
broken source produces an empty block that downstream surfaces dim
on (per the TTL semantics in ``state.py``).

Wired sources: refusals_recent, health_system, stream, monetization,
daimonion_voice (stimmung), time_sprint (sprint), hardware_fleet
(pi-noir per-Pi heartbeats), publishing_pipeline (publish/ inbox +
draft + published mtime). Remaining default-empty blocks
(marketing_outreach, research_dispatches, music_soundcloud,
cross_account, governance, content_programmes) wait on producer-side
substrate to land before the helpers can do better than the typed
default. Each source is independently testable; the
``Aggregator.collect()`` orchestrator composes them into a single
``AwarenessState`` per tick.
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
    DaimonionBlock,
    FleetBlock,
    HealthBlock,
    PublishingBlock,
    RefusalEvent,
    SprintBlock,
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
DEFAULT_STIMMUNG_PATH = Path(
    os.environ.get(
        "HAPAX_STIMMUNG_STATE_PATH",
        "/dev/shm/hapax-stimmung/state.json",
    )
)
DEFAULT_SPRINT_PATH = Path(
    os.environ.get(
        "HAPAX_SPRINT_STATE_PATH",
        "/dev/shm/hapax-sprint/state.json",
    )
)
DEFAULT_FLEET_DIR = Path(
    os.environ.get(
        "HAPAX_PI_NOIR_DIR",
        str(Path.home() / "hapax-state/pi-noir"),
    )
)
DEFAULT_PUBLISH_DIR = Path(
    os.environ.get(
        "HAPAX_PUBLISH_DIR",
        str(Path.home() / "hapax-state/publish"),
    )
)

# Bounded tail length for the refusals_recent block. Spec: 50 entries.
# Surfaces (waybar, sidebar, omg.lol fanout) display individuals; we
# cap to avoid unbounded JSON growth on a long-running daemon.
REFUSALS_TAIL_LIMIT = 50

# Stream block window for chronicle event count. Spec: 5min.
STREAM_EVENT_WINDOW_S = 300.0

# Pi NoIR heartbeat freshness window. Per IR perception design, the
# edge daemons POST every ~3s; 120s gives 40 ticks of margin before
# we mark a Pi offline (handles brief WiFi blips without flapping).
FLEET_FRESHNESS_S = 120.0

# Publishing pipeline 24h count window.
PUBLISH_COUNT_WINDOW_S = 86400.0


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


def collect_daimonion_block(
    state_path: Path = DEFAULT_STIMMUNG_PATH,
) -> DaimonionBlock:
    """Read the stimmung state file and project ``overall_stance``.

    The stimmung daemon publishes a flat JSON object with an
    ``overall_stance`` string (e.g. ``"cautious"`` / ``"engaged"``).
    Missing file is the pre-rollout case (stimmung daemon not yet
    started) — return defaults without incrementing the failure
    metric. Malformed payload is a real source failure.
    """
    if not state_path.exists():
        return DaimonionBlock()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.debug("stimmung state unreadable at %s", state_path)
        aggregator_source_failures_total.labels(source="daimonion_voice").inc()
        return DaimonionBlock()
    if not isinstance(data, dict):
        aggregator_source_failures_total.labels(source="daimonion_voice").inc()
        return DaimonionBlock()
    raw_stance = data.get("overall_stance")
    stance = str(raw_stance) if raw_stance else "unknown"
    return DaimonionBlock(stance=stance)


def collect_sprint_block(
    state_path: Path = DEFAULT_SPRINT_PATH,
) -> SprintBlock:
    """Read the sprint tracker state and map to ``SprintBlock``.

    The obsidian-hapax sprint tracker writes a flat JSON object with
    ``current_sprint``, ``current_day``, ``measures_completed``,
    ``measures_blocked``. Coerce sprint id to string (the tracker
    writes ints). Missing file is pre-rollout; do not raise the
    failure metric.
    """
    if not state_path.exists():
        return SprintBlock()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.debug("sprint state unreadable at %s", state_path)
        aggregator_source_failures_total.labels(source="time_sprint").inc()
        return SprintBlock()
    if not isinstance(data, dict):
        aggregator_source_failures_total.labels(source="time_sprint").inc()
        return SprintBlock()
    sprint_raw = data.get("current_sprint")
    sprint_id = "" if sprint_raw is None else str(sprint_raw)
    return SprintBlock(
        sprint_id=sprint_id,
        sprint_day=_safe_int(data.get("current_day")),
        completed_measures=_safe_int(data.get("measures_completed")),
        blocked_measures=_safe_int(data.get("measures_blocked")),
    )


def collect_fleet_block(
    pi_noir_dir: Path = DEFAULT_FLEET_DIR,
    *,
    now: float | None = None,
    freshness_s: float = FLEET_FRESHNESS_S,
) -> FleetBlock:
    """Count Pi NoIR edge daemons + classify online by mtime.

    Each Pi (desk / room / overhead) writes its IR state JSON to
    ``~/hapax-state/pi-noir/{role}.json`` on every successful POST.
    ``*-cadence.json`` siblings hold per-Pi cadence config and are
    not heartbeats — exclude from the count. Total = number of role
    files; online = count where stat().st_mtime is within
    ``freshness_s`` seconds of wall clock. Missing dir is
    pre-rollout (no Pis configured yet).
    """
    if not pi_noir_dir.exists() or not pi_noir_dir.is_dir():
        return FleetBlock()
    try:
        candidates = [p for p in pi_noir_dir.glob("*.json") if not p.stem.endswith("-cadence")]
    except OSError:
        log.debug("pi-noir dir unreadable at %s", pi_noir_dir)
        aggregator_source_failures_total.labels(source="hardware_fleet").inc()
        return FleetBlock()
    cutoff = (now if now is not None else time.time()) - freshness_s
    pi_count_online = sum(1 for p in candidates if _safe_mtime(p) >= cutoff)
    return FleetBlock(
        pi_count_total=len(candidates),
        pi_count_online=pi_count_online,
    )


def collect_publishing_block(
    publish_dir: Path = DEFAULT_PUBLISH_DIR,
    *,
    now: float | None = None,
    window_s: float = PUBLISH_COUNT_WINDOW_S,
) -> PublishingBlock:
    """Compose publishing-pipeline counters from the publish/ tree.

    Publication-bus persistence layout: ``inbox/`` queued items,
    ``draft/`` in-flight, ``published/`` completed. Counts are file
    counts (one item per file). ``published_24h`` filters by mtime;
    ``last_publish_at`` is the max mtime in published/. Missing tree
    is pre-rollout — bus configured but no items queued/published.
    """
    if not publish_dir.exists() or not publish_dir.is_dir():
        return PublishingBlock()
    inbox_count = _count_dir_files(publish_dir / "inbox")
    in_flight_count = _count_dir_files(publish_dir / "draft")
    published_dir = publish_dir / "published"
    if not published_dir.exists() or not published_dir.is_dir():
        return PublishingBlock(
            inbox_count=inbox_count,
            in_flight_count=in_flight_count,
        )
    cutoff_24h = (now if now is not None else time.time()) - window_s
    published_24h = 0
    last_mtime = 0.0
    try:
        for entry in published_dir.iterdir():
            if not entry.is_file():
                continue
            mtime = _safe_mtime(entry)
            if mtime >= cutoff_24h:
                published_24h += 1
            if mtime > last_mtime:
                last_mtime = mtime
    except OSError:
        log.debug("publish/published dir unreadable at %s", published_dir)
        aggregator_source_failures_total.labels(source="publishing_pipeline").inc()
        return PublishingBlock(
            inbox_count=inbox_count,
            in_flight_count=in_flight_count,
        )
    last_publish_at: datetime | None = None
    if last_mtime > 0:
        last_publish_at = datetime.fromtimestamp(last_mtime, tz=UTC)
    return PublishingBlock(
        inbox_count=inbox_count,
        in_flight_count=in_flight_count,
        published_24h=published_24h,
        last_publish_at=last_publish_at,
    )


def _count_dir_files(directory: Path) -> int:
    """Count regular files in ``directory``; missing dir → 0."""
    if not directory.exists() or not directory.is_dir():
        return 0
    try:
        return sum(1 for entry in directory.iterdir() if entry.is_file())
    except OSError:
        return 0


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


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
        stimmung_state_path: Path = DEFAULT_STIMMUNG_PATH,
        sprint_state_path: Path = DEFAULT_SPRINT_PATH,
        pi_noir_dir: Path = DEFAULT_FLEET_DIR,
        publish_dir: Path = DEFAULT_PUBLISH_DIR,
        clock=None,
    ) -> None:
        self._refusals_log_path = refusals_log_path
        self._infra_snapshot_path = infra_snapshot_path
        self._chronicle_events_path = chronicle_events_path
        self._monetization_log_path = monetization_log_path
        self._stimmung_state_path = stimmung_state_path
        self._sprint_state_path = sprint_state_path
        self._pi_noir_dir = pi_noir_dir
        self._publish_dir = publish_dir
        self._clock = clock or (lambda: datetime.now(UTC))

    def collect(self) -> AwarenessState:
        """Build one AwarenessState by pulling each wired source.

        Wires 8 source helpers: refusals_recent, health_system,
        stream, monetization, daimonion_voice (stimmung overall
        stance), time_sprint (obsidian sprint tracker),
        hardware_fleet (pi-noir per-Pi heartbeats), publishing
        (publish/ inbox/draft/published mtime). Remaining sub-blocks
        (marketing_outreach, research_dispatches, music_soundcloud,
        cross_account, governance, content_programmes) fall through
        to default-empty until producer-side substrate ships.
        """
        return AwarenessState(
            timestamp=self._clock(),
            refusals_recent=collect_refusals_recent(self._refusals_log_path),
            health_system=collect_health_block(self._infra_snapshot_path),
            stream=collect_stream_block(self._chronicle_events_path),
            monetization=collect_monetization_block(self._monetization_log_path),
            daimonion_voice=collect_daimonion_block(self._stimmung_state_path),
            time_sprint=collect_sprint_block(self._sprint_state_path),
            hardware_fleet=collect_fleet_block(self._pi_noir_dir),
            publishing_pipeline=collect_publishing_block(self._publish_dir),
        )


__all__ = [
    "DEFAULT_CHRONICLE_EVENTS",
    "DEFAULT_FLEET_DIR",
    "DEFAULT_INFRA_SNAPSHOT",
    "DEFAULT_PUBLISH_DIR",
    "DEFAULT_REFUSALS_LOG",
    "DEFAULT_SPRINT_PATH",
    "DEFAULT_STIMMUNG_PATH",
    "FLEET_FRESHNESS_S",
    "PUBLISH_COUNT_WINDOW_S",
    "REFUSALS_TAIL_LIMIT",
    "STREAM_EVENT_WINDOW_S",
    "Aggregator",
    "aggregator_source_failures_total",
    "collect_daimonion_block",
    "collect_fleet_block",
    "collect_health_block",
    "collect_publishing_block",
    "collect_refusals_recent",
    "collect_sprint_block",
    "collect_stream_block",
]
