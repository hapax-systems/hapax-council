"""logos/engine/reactive_rules.py — Reactive engine rules.

Phase 0 (deterministic):
- collector-refresh: refresh logos cache tier on profiles/ changes
- config-changed: log axiom registry reload on axioms/registry.yaml change
- sdlc-event-logged: notify + cache refresh on SDLC event append
- audio-archive-sidecar: log new audio archive sidecars

Phase 1 (local GPU):
- rag-source-landed: ingest new RAG source files via Ollama embeddings
- audio-clap-indexed: trigger RAG ingest after audio CLAP indexing

Phase 2 (cloud LLM):
- knowledge-maintenance: run maintenance after profiles/ changes settle (quiet window)
"""

from __future__ import annotations

import asyncio
import logging
import time

from logos.engine.models import Action, ChangeEvent
from logos.engine.rules import Rule
from shared.governance.carrier import CarrierRegistry
from shared.telemetry import hapax_event

_log = logging.getLogger(__name__)

# ── File-to-cache-tier mapping ───────────────────────────────────────────────

_FAST_REFRESH_FILES = {"health-history.jsonl"}
_SLOW_REFRESH_FILES = {"drift-report.json", "scout-report.json", "operator-profile.json"}


# ── Handlers (lazy imports to avoid circular deps) ──────────────────────────


async def _handle_collector_refresh(*, tier: str) -> str:
    """Refresh the appropriate logos cache tier."""
    from logos.api.cache import cache

    if tier == "fast":
        await cache.refresh_fast()
    else:
        await cache.refresh_slow()
    _log.info("Cache %s refresh triggered by file change", tier)
    return f"cache.refresh_{tier}"


async def _handle_config_changed(*, path: str) -> str:
    """Log axiom registry change. No explicit reload needed — loaders read fresh."""
    _log.info("Axiom config changed: %s (loaders will pick up on next call)", path)
    return "config-reloaded"


async def _handle_sdlc_event(*, path: str) -> str:
    """Send notification and refresh slow cache for SDLC events."""
    from logos._notify import send_notification
    from logos.api.cache import cache

    await asyncio.to_thread(
        send_notification,
        "SDLC Pipeline Event",
        "New event logged to sdlc-events.jsonl",
        priority="default",
        tags=["gear"],
    )
    await cache.refresh_slow()
    _log.info("SDLC event notification sent + slow cache refreshed")
    return "sdlc-notified"


# ── Rule definitions ────────────────────────────────────────────────────────


def _collector_refresh_filter(event: ChangeEvent) -> bool:
    """Match profiles/ file changes that need cache refresh."""
    return event.path.name in _FAST_REFRESH_FILES | _SLOW_REFRESH_FILES


def _collector_refresh_produce(event: ChangeEvent) -> list[Action]:
    """Produce cache refresh action for the correct tier."""
    filename = event.path.name
    if filename in _FAST_REFRESH_FILES:
        tier = "fast"
    else:
        tier = "slow"
    return [
        Action(
            name=f"collector-refresh-{tier}",
            handler=_handle_collector_refresh,
            args={"tier": tier},
            phase=0,
            priority=10,
        )
    ]


def _config_changed_filter(event: ChangeEvent) -> bool:
    """Match axioms/registry.yaml modifications."""
    return event.path.name == "registry.yaml" and "axioms" in event.path.parts


def _config_changed_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name="config-changed",
            handler=_handle_config_changed,
            args={"path": str(event.path)},
            phase=0,
            priority=5,
        )
    ]


def _sdlc_event_filter(event: ChangeEvent) -> bool:
    """Match sdlc-events.jsonl modifications."""
    return event.path.name == "sdlc-events.jsonl"


def _sdlc_event_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name="sdlc-event-logged",
            handler=_handle_sdlc_event,
            args={"path": str(event.path)},
            phase=0,
            priority=20,
        )
    ]


# ── Phase 1: Sync rules (local GPU) ─────────────────────────────────────


async def _handle_rag_ingest(*, path: str) -> str:
    """Ingest a new RAG source file. Runs in thread (sync function).

    NOTE: docling is installed in a separate venv (.venv-ingest) due to
    dependency conflicts with pydantic-ai.  The rag-ingest.service handles
    ingestion independently.  If docling is unavailable here, skip gracefully.
    """
    from pathlib import Path

    try:
        from agents.ingest import ingest_file
    except (ImportError, ModuleNotFoundError) as exc:
        _log.debug("Skipping reactive ingest (docling not in this venv): %s", exc)
        return f"skipped:{Path(path).name}"

    file_path = Path(path)
    success, error = await asyncio.to_thread(ingest_file, file_path)
    if success:
        _log.info("Ingested RAG source: %s", file_path.name)
        return f"ingested:{file_path.name}"
    else:
        _log.warning("Ingest failed for %s: %s", file_path.name, error)
        raise RuntimeError(f"Ingest failed: {error}")


def _rag_source_filter(event: ChangeEvent) -> bool:
    """Match new or updated files in RAG_SOURCES_DIR."""
    if event.event_type not in ("created", "modified"):
        return False
    return event.source_service is not None


def _rag_source_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name=f"rag-ingest:{event.path}",
            handler=_handle_rag_ingest,
            args={"path": str(event.path)},
            phase=1,
            priority=50,
        )
    ]


RAG_SOURCE_RULE = Rule(
    name="rag-source-landed",
    description="Ingest new RAG source files via local GPU embeddings",
    trigger_filter=_rag_source_filter,
    produce=_rag_source_produce,
    phase=1,
    cooldown_s=0,
)


# ── Phase 2: Knowledge rules (cloud LLM) ───────────────────────────────


class QuietWindowScheduler:
    """Accumulates events and fires a callback after a quiet period.

    Each new event resets the timer. The callback fires only after
    quiet_window_s seconds pass with no new events.
    """

    def __init__(self, quiet_window_s: float = 180) -> None:
        self._quiet_window_s = quiet_window_s
        self._dirty_paths: set[str] = set()
        self._last_event: float = 0.0
        self._scheduled_handle: asyncio.TimerHandle | None = None
        self._callback: asyncio.Future | None = None
        self._running = False

    @property
    def dirty(self) -> bool:
        return len(self._dirty_paths) > 0

    @property
    def dirty_paths(self) -> set[str]:
        return set(self._dirty_paths)

    def record(self, path: str, *, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Record a dirty path and reset the quiet window timer."""
        self._dirty_paths.add(path)
        self._last_event = time.monotonic()

        # Cancel any pending scheduled fire
        if self._scheduled_handle is not None:
            self._scheduled_handle.cancel()
            self._scheduled_handle = None

        # Schedule fire after quiet window
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # No running loop — can't schedule, stay dirty but don't fire
                return
        self._scheduled_handle = loop.call_later(self._quiet_window_s, self._mark_ready)

    def _mark_ready(self) -> None:
        """Called when quiet window expires."""
        self._scheduled_handle = None
        self._running = True

    def should_fire(self) -> bool:
        """Check if quiet window has elapsed and there's dirty state."""
        return bool(self._running and self._dirty_paths)

    def consume(self) -> set[str]:
        """Consume dirty paths, resetting state. Call after firing."""
        paths = set(self._dirty_paths)
        self._dirty_paths.clear()
        self._running = False
        return paths

    def cancel(self) -> None:
        """Cancel any pending timer."""
        if self._scheduled_handle is not None:
            self._scheduled_handle.cancel()
            self._scheduled_handle = None
        self._dirty_paths.clear()
        self._running = False


# Module-level scheduler instance shared between filter and handler
_knowledge_scheduler = QuietWindowScheduler(quiet_window_s=180)


def get_knowledge_scheduler() -> QuietWindowScheduler:
    """Expose scheduler for testing and engine integration."""
    return _knowledge_scheduler


async def _handle_knowledge_maintenance(*, ignore_fn=None) -> str:
    """Run knowledge maintenance after quiet window expires."""
    from agents.knowledge_maint import run_maintenance
    from logos._config import PROFILES_DIR

    # Self-trigger prevention for output files
    if ignore_fn is not None:
        ignore_fn(PROFILES_DIR / "knowledge-maint-report.json")

    paths = _knowledge_scheduler.consume()
    _log.info("Knowledge maintenance triggered by %d dirty paths", len(paths))

    report = await run_maintenance(dry_run=False)
    _log.info(
        "Knowledge maintenance complete: pruned=%d merged=%d",
        report.total_pruned,
        report.total_merged,
    )
    return f"maintenance:pruned={report.total_pruned},merged={report.total_merged}"


# Files that should trigger knowledge maintenance consideration
_KNOWLEDGE_TRIGGER_FILES = {
    "health-history.jsonl",
    "drift-report.json",
    "scout-report.json",
    "operator-profile.json",
    "knowledge-maint-report.json",  # own output — filtered by scheduler, not trigger
}


def _knowledge_maint_filter(event: ChangeEvent) -> bool:
    """Match profiles/ changes and manage quiet window.

    Always records events. Only returns True when quiet window has elapsed.
    """
    # Only profiles/ directory changes
    if "profiles" not in event.path.parts:
        return False
    # Skip our own output
    if event.path.name == "knowledge-maint-report.json":
        return False
    if event.path.name == "knowledge-maint-history.jsonl":
        return False

    # Record the event in the scheduler
    _knowledge_scheduler.record(str(event.path))

    # Only fire if quiet window has elapsed
    return _knowledge_scheduler.should_fire()


def _knowledge_maint_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name="knowledge-maintenance",
            handler=_handle_knowledge_maintenance,
            args={},
            phase=2,
            priority=80,
        )
    ]


KNOWLEDGE_MAINT_RULE = Rule(
    name="knowledge-maintenance",
    description="Run knowledge maintenance after profiles/ changes settle (180s quiet window)",
    trigger_filter=_knowledge_maint_filter,
    produce=_knowledge_maint_produce,
    phase=2,
    cooldown_s=600,
)


# ── Phase 0: Carrier fact intake (DD-26) ──────────────────────────────────

# Module-level carrier registry, shared across intake events.
# Principals are registered lazily on first carrier fact arrival.
_carrier_registry: CarrierRegistry | None = None
_DEFAULT_CARRIER_CAPACITY = 5


def get_carrier_registry() -> CarrierRegistry:
    """Get or create the module-level CarrierRegistry."""
    global _carrier_registry  # noqa: PLW0603
    if _carrier_registry is None:
        from shared.governance.carrier import CarrierRegistry as _CR

        _carrier_registry = _CR()
    return _carrier_registry


def set_carrier_registry(registry: CarrierRegistry) -> None:
    """Inject a CarrierRegistry for testing or external initialization."""
    global _carrier_registry  # noqa: PLW0603
    _carrier_registry = registry


async def _handle_carrier_intake(*, path: str, principal_id: str) -> str:
    """Process a carrier-flagged file with governor enforcement."""
    import asyncio
    from pathlib import Path as _Path

    from shared.governance.agent_governor import create_agent_governor
    from shared.governance.carrier_intake import intake_carrier_fact

    registry = get_carrier_registry()

    # Ensure principal is registered (lazy registration)
    if principal_id not in registry._capacities:
        registry.register(principal_id, _DEFAULT_CARRIER_CAPACITY)

    # Create governor for carrier-intake boundary (AMELI pattern)
    governor = create_agent_governor(
        "carrier-intake",
        axiom_bindings=[
            {"axiom_id": "interpersonal_transparency", "role": "enforcer"},
        ],
    )

    result = await asyncio.to_thread(
        intake_carrier_fact,
        _Path(path),
        principal_id,
        registry,
        governor=governor,
    )
    status = "accepted" if result.accepted else "rejected"
    return f"carrier:{status}:{result.source_domain}"


def _carrier_intake_filter(event: ChangeEvent) -> bool:
    """Match files with carrier: true in frontmatter."""
    if event.frontmatter is None:
        return False
    return bool(event.frontmatter.get("carrier"))


def _carrier_intake_produce(event: ChangeEvent) -> list[Action]:
    """Produce carrier intake action."""
    # Principal ID from frontmatter, or default to the source agent
    principal_id = "operator"
    if event.frontmatter:
        principal_id = event.frontmatter.get("carrier_principal", "operator")
    return [
        Action(
            name=f"carrier-intake:{event.path}",
            handler=_handle_carrier_intake,
            args={"path": str(event.path), "principal_id": str(principal_id)},
            phase=0,
            priority=30,
        )
    ]


CARRIER_INTAKE_RULE = Rule(
    name="carrier-intake",
    description="Process carrier-flagged files into CarrierRegistry (DD-26)",
    trigger_filter=_carrier_intake_filter,
    produce=_carrier_intake_produce,
    phase=0,
    cooldown_s=0,
)


# ── Phase 0/1: Audio archive & CLAP indexing rules ──────────────────────────


async def _handle_audio_archive_sidecar(*, path: str) -> str:
    """Log that a new audio archive sidecar was written."""
    _log.info("Audio archive sidecar created: %s", path)
    return f"audio-sidecar:{path}"


def _audio_archive_sidecar_filter(event: ChangeEvent) -> bool:
    """Match new .md sidecar files in the audio archive directory."""
    if event.event_type != "created":
        return False
    path_str = str(event.path)
    return "audio-recording/archive" in path_str and event.path.suffix == ".md"


def _audio_archive_sidecar_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name=f"audio-archive-sidecar:{event.path.name}",
            handler=_handle_audio_archive_sidecar,
            args={"path": str(event.path)},
            phase=0,
            priority=15,
        )
    ]


AUDIO_ARCHIVE_SIDECAR_RULE = Rule(
    name="audio-archive-sidecar",
    description="Log new audio archive sidecars (Phase 0, deterministic)",
    trigger_filter=_audio_archive_sidecar_filter,
    produce=_audio_archive_sidecar_produce,
    phase=0,
    cooldown_s=0,
)


async def _handle_audio_clap_indexed(*, path: str) -> str:
    """Trigger RAG ingest for CLAP-indexed audio RAG documents."""
    from pathlib import Path as _Path

    from agents.ingest import ingest_file

    file_path = _Path(path)
    success, error = await asyncio.to_thread(ingest_file, file_path)
    if success:
        _log.info("CLAP-indexed audio RAG ingested: %s", file_path.name)
        return f"clap-ingested:{file_path.name}"
    else:
        _log.warning("CLAP audio ingest failed for %s: %s", file_path.name, error)
        raise RuntimeError(f"CLAP audio ingest failed: {error}")


def _audio_clap_indexed_filter(event: ChangeEvent) -> bool:
    """Match new audio RAG documents (listening-*, sample-*, note-*, conv-*)."""
    if event.event_type != "created":
        return False
    path_str = str(event.path)
    if "rag-sources/audio" not in path_str:
        return False
    name = event.path.name
    return name.startswith(("listening-", "sample-", "note-", "conv-"))


def _audio_clap_indexed_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name=f"audio-clap-indexed:{event.path.name}",
            handler=_handle_audio_clap_indexed,
            args={"path": str(event.path)},
            phase=1,
            priority=55,
        )
    ]


AUDIO_CLAP_INDEXED_RULE = Rule(
    name="audio-clap-indexed",
    description="Ingest CLAP-indexed audio RAG documents via local GPU embeddings",
    trigger_filter=_audio_clap_indexed_filter,
    produce=_audio_clap_indexed_produce,
    phase=1,
    cooldown_s=0,
)


# ── Phase 2: Pattern consolidation (WS3 L3) ────────────────────────────────

_consolidation_scheduler = QuietWindowScheduler(quiet_window_s=300)


async def _handle_pattern_consolidation(*, ignore_fn=None) -> str:
    """Run WS3 L3 pattern consolidation after episodes accumulate."""
    from shared.correction_memory import CorrectionStore
    from shared.episodic_memory import EpisodeStore
    from shared.pattern_consolidation import PatternStore, run_consolidation

    _consolidation_scheduler.consume()

    episode_store = EpisodeStore()
    correction_store = CorrectionStore()
    pattern_store = PatternStore()
    pattern_store.ensure_collection()

    result = await run_consolidation(episode_store, correction_store, pattern_store)
    _log.info(
        "Pattern consolidation: %d new patterns, summary: %s",
        len(result.patterns),
        result.summary[:80],
    )
    return f"consolidation:patterns={len(result.patterns)}"


def _consolidation_filter(event: ChangeEvent) -> bool:
    """Trigger consolidation after perception state changes settle.

    Uses a 5-minute quiet window. Fires at most once per day (cooldown_s=86400).
    """
    if event.path.name != "perception-state.json":
        return False
    _consolidation_scheduler.record(str(event.path))
    return _consolidation_scheduler.should_fire()


def _consolidation_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name="pattern-consolidation",
            handler=_handle_pattern_consolidation,
            args={},
            phase=2,
            priority=90,
        )
    ]


PATTERN_CONSOLIDATION_RULE = Rule(
    name="pattern-consolidation",
    description="Run WS3 pattern consolidation after episodes accumulate (daily)",
    trigger_filter=_consolidation_filter,
    produce=_consolidation_produce,
    phase=2,
    cooldown_s=86400,  # once per day
)


# ── Phase 2: Correction synthesis (WS3 learning loop) ───────────────────────

_correction_synthesis_scheduler = QuietWindowScheduler(quiet_window_s=600)


async def _handle_correction_synthesis(*, ignore_fn=None) -> str:
    """Synthesize accumulated corrections into profile facts."""
    from shared.correction_synthesis import run_correction_synthesis

    _correction_synthesis_scheduler.consume()
    result = await run_correction_synthesis()
    _log.info("Correction synthesis: %s", result[:120])
    return f"correction-synthesis:{result[:80]}"


def _correction_synthesis_filter(event: ChangeEvent) -> bool:
    """Trigger correction synthesis after perception corrections accumulate.

    Uses a 10-minute quiet window. Fires at most once per day.
    """
    if event.path.name != "activity-correction.json":
        return False
    _correction_synthesis_scheduler.record(str(event.path))
    return _correction_synthesis_scheduler.should_fire()


def _correction_synthesis_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name="correction-synthesis",
            handler=_handle_correction_synthesis,
            args={},
            phase=2,
            priority=85,
        )
    ]


CORRECTION_SYNTHESIS_RULE = Rule(
    name="correction-synthesis",
    description="Synthesize operator corrections into profile facts (daily)",
    trigger_filter=_correction_synthesis_filter,
    produce=_correction_synthesis_produce,
    phase=2,
    cooldown_s=86400,  # once per day
)


# ── Phase 0: Voice/presence state reactive rules ─────────────────────────────

# Track previous presence state to detect transitions (not every tick)
# Lock protects all transition state to prevent filter/produce races
import threading

_transition_lock = threading.Lock()
_last_presence_state: str = ""
_last_consent_phase: str = "no_guest"


async def _handle_presence_transition(*, from_state: str, to_state: str) -> str:
    """React to Bayesian presence state transition."""
    _log.info("PRESENCE transition: %s → %s", from_state, to_state)

    if to_state == "AWAY":
        # Emit telemetry event for session analytics
        hapax_event(
            "presence",
            "operator_away",
            metadata={"from_state": from_state},
        )
    elif to_state == "PRESENT" and from_state == "AWAY":
        hapax_event(
            "presence",
            "operator_returned",
            metadata={"from_state": from_state},
        )

    return f"presence:{from_state}→{to_state}"


def _presence_transition_filter(event: ChangeEvent) -> bool:
    """Detect presence state transitions from perception-state.json updates."""
    if event.path.name != "perception-state.json":
        return False

    import json

    try:
        data = json.loads(event.path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False

    current = data.get("presence_state", "")
    with _transition_lock:
        return bool(current and current != _last_presence_state)


def _presence_transition_produce(event: ChangeEvent) -> list[Action]:
    global _last_presence_state

    import json

    try:
        data = json.loads(event.path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    current = data.get("presence_state", "")
    with _transition_lock:
        if current == _last_presence_state:
            return []  # lost race — another event already handled this transition
        from_state = _last_presence_state
        _last_presence_state = current

    return [
        Action(
            name=f"presence-transition:{from_state}→{current}",
            handler=_handle_presence_transition,
            args={"from_state": from_state, "to_state": current},
            phase=0,
            priority=10,
        )
    ]


PRESENCE_TRANSITION_RULE = Rule(
    name="presence-transition",
    description="React to Bayesian presence state transitions (PRESENT/UNCERTAIN/AWAY)",
    trigger_filter=_presence_transition_filter,
    produce=_presence_transition_produce,
    phase=0,
    cooldown_s=5,  # don't spam on rapid oscillation
)


async def _handle_consent_transition(*, from_phase: str, to_phase: str) -> str:
    """React to consent phase transitions."""
    _log.info("CONSENT transition: %s → %s", from_phase, to_phase)

    if to_phase == "consent_pending":
        from logos._notify import send_notification

        await asyncio.to_thread(
            send_notification,
            title="Guest Detected",
            message="Non-operator person detected. Consent flow initiated.",
            priority="high",
        )
    elif to_phase == "no_guest" and from_phase in ("consent_pending", "consent_refused"):
        from logos._notify import send_notification

        await asyncio.to_thread(
            send_notification,
            title="Guest Left",
            message=f"Guest departed ({from_phase}). Perception curtailment lifted.",
            priority="default",
        )

    hapax_event(
        "consent",
        f"phase_{to_phase}",
        metadata={"from_phase": from_phase, "to_phase": to_phase},
    )
    return f"consent:{from_phase}→{to_phase}"


def _consent_transition_filter(event: ChangeEvent) -> bool:
    """Detect consent phase transitions from perception-state.json updates."""
    if event.path.name != "perception-state.json":
        return False

    import json

    try:
        data = json.loads(event.path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False

    current = data.get("consent_phase", "no_guest")
    with _transition_lock:
        return current != _last_consent_phase


def _consent_transition_produce(event: ChangeEvent) -> list[Action]:
    global _last_consent_phase

    import json

    try:
        data = json.loads(event.path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    current = data.get("consent_phase", "no_guest")
    with _transition_lock:
        if current == _last_consent_phase:
            return []  # lost race — another event already handled this transition
        from_phase = _last_consent_phase
        _last_consent_phase = current

    return [
        Action(
            name=f"consent-transition:{from_phase}→{current}",
            handler=_handle_consent_transition,
            args={"from_phase": from_phase, "to_phase": current},
            phase=0,
            priority=5,  # high priority — consent is governance
        )
    ]


CONSENT_TRANSITION_RULE = Rule(
    name="consent-transition",
    description="React to consent phase transitions (guest detection, consent resolution)",
    trigger_filter=_consent_transition_filter,
    produce=_consent_transition_produce,
    phase=0,
    cooldown_s=5,
)


# ── Phase 0: Biometric state cascade (Distributed Nervous System) ────────


_BIOMETRIC_FILES = {"heartrate.json", "hrv.json", "activity.json", "eda.json"}
_last_stress_elevated: bool = False


async def _handle_biometric_state_change(*, path: str) -> str:
    """Update Stimmung biometric dimensions from watch state files.

    Reads current biometric data and writes a stress transition event
    to perception-state.json if stress state crosses a threshold.
    """
    from pathlib import Path as _Path

    from agents.hapax_daimonion.watch_signals import WATCH_STATE_DIR, is_stress_elevated

    global _last_stress_elevated
    stress_now = is_stress_elevated(WATCH_STATE_DIR)

    if stress_now != _last_stress_elevated:
        _log.info("Stress transition: %s → %s", _last_stress_elevated, stress_now)
        hapax_event(
            "biometric",
            "stress_transition",
            metadata={"from": _last_stress_elevated, "to": stress_now},
        )
        _last_stress_elevated = stress_now

    _log.debug("Biometric state change processed: %s", path)
    return f"biometric-update:{_Path(path).name}"


def _biometric_state_filter(event: ChangeEvent) -> bool:
    """Match watch biometric state file changes."""
    return event.path.name in _BIOMETRIC_FILES and "watch" in event.path.parts


def _biometric_state_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name=f"biometric-state:{event.path.name}",
            handler=_handle_biometric_state_change,
            args={"path": str(event.path)},
            phase=0,
            priority=15,
        )
    ]


BIOMETRIC_STATE_RULE = Rule(
    name="biometric-state-change",
    description="Update Stimmung biometric dimensions on watch state file changes",
    trigger_filter=_biometric_state_filter,
    produce=_biometric_state_produce,
    phase=0,
    cooldown_s=30,  # match watch flush interval
)


async def _handle_phone_health_summary(*, path: str) -> str:
    """Process daily phone health summary — update profiler bridge facts."""
    _log.info("Phone health summary received: %s", path)
    hapax_event(
        "biometric",
        "health_summary_received",
        metadata={"path": path},
    )
    return f"phone-health:{path}"


def _phone_health_filter(event: ChangeEvent) -> bool:
    """Match phone_health_summary.json updates."""
    return event.path.name == "phone_health_summary.json" and "watch" in event.path.parts


def _phone_health_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name="phone-health-summary",
            handler=_handle_phone_health_summary,
            args={"path": str(event.path)},
            phase=0,
            priority=20,
        )
    ]


PHONE_HEALTH_SUMMARY_RULE = Rule(
    name="phone-health-summary",
    description="Process daily phone health summary into profiler bridge facts",
    trigger_filter=_phone_health_filter,
    produce=_phone_health_produce,
    phase=0,
    cooldown_s=3600,  # daily data, no urgency
)


# ── Registration ────────────────────────────────────────────────────────────

ALL_RULES: list[Rule] = [
    Rule(
        name="collector-refresh",
        description="Refresh logos cache tier when profiles/ data changes",
        trigger_filter=_collector_refresh_filter,
        produce=_collector_refresh_produce,
        phase=0,
    ),
    Rule(
        name="config-changed",
        description="Log axiom registry reload on axioms/registry.yaml change",
        trigger_filter=_config_changed_filter,
        produce=_config_changed_produce,
        phase=0,
    ),
    Rule(
        name="sdlc-event-logged",
        description="Notify and refresh cache on SDLC pipeline event",
        trigger_filter=_sdlc_event_filter,
        produce=_sdlc_event_produce,
        phase=0,
        cooldown_s=30,
    ),
    RAG_SOURCE_RULE,
    AUDIO_ARCHIVE_SIDECAR_RULE,
    AUDIO_CLAP_INDEXED_RULE,
    CARRIER_INTAKE_RULE,
    KNOWLEDGE_MAINT_RULE,
    PATTERN_CONSOLIDATION_RULE,
    CORRECTION_SYNTHESIS_RULE,
    PRESENCE_TRANSITION_RULE,
    CONSENT_TRANSITION_RULE,
    BIOMETRIC_STATE_RULE,
    PHONE_HEALTH_SUMMARY_RULE,
]

# Backwards compat alias
INFRASTRUCTURE_RULES = ALL_RULES


def register_rules(registry) -> None:
    """Register all reactive rules on a RuleRegistry."""
    for rule in ALL_RULES:
        registry.register(rule)
    _log.info("Registered %d reactive rules", len(ALL_RULES))


# Backwards compat alias
register_infrastructure_rules = register_rules
