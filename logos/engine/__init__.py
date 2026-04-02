"""logos/engine — Reactive engine orchestrator.

Watches filesystem for changes, evaluates rules, executes actions in phases.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from logos._config import AI_AGENTS_DIR, PROFILES_DIR, RAG_SOURCES_DIR
from logos._stimmung import Stance
from logos._telemetry import hapax_event, hapax_interaction
from logos._working_mode import WorkingMode, get_working_mode
from logos.engine.executor import PhasedExecutor
from logos.engine.models import ActionPlan as ActionPlan
from logos.engine.models import ChangeEvent
from logos.engine.rules import RuleRegistry, evaluate_rules
from shared.chronicle import ChronicleEvent, current_otel_ids
from shared.chronicle import record as chronicle_record

if TYPE_CHECKING:
    from logos.engine.watcher import DirectoryWatcher

# ── Persistent Event Counters (WS2) ─────────────────────────────────────────


def _load_counters(path: Path) -> dict[str, int]:
    """Load persistent event pattern counters."""
    import json

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_counters(counters: dict[str, int], path: Path) -> None:
    """Save persistent event pattern counters atomically."""
    import json

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(counters, indent=2), encoding="utf-8")
        tmp.rename(path)
    except OSError:
        _log.debug("Failed to save engine counters", exc_info=True)


def _event_pattern_key(event_type: str, doc_type: str | None, rules: list[str]) -> str:
    """Build a hashable key for an event pattern."""
    rules_str = "+".join(sorted(rules)) if rules else "none"
    return f"{event_type}|{doc_type or 'unknown'}|{rules_str}"


_log = logging.getLogger(__name__)


def _env_int(key: str, default: int) -> int:
    val = os.environ.get(key)
    if val is not None:
        try:
            return int(val)
        except ValueError:
            pass
    return default


def _env_float(key: str, default: float) -> float:
    val = os.environ.get(key)
    if val is not None:
        try:
            return float(val)
        except ValueError:
            pass
    return default


@dataclass
class _HistoryEntry:
    """Record of a processed event for status queries."""

    timestamp: datetime
    event_path: str
    event_type: str
    doc_type: str | None
    rules_matched: list[str]
    actions: list[str]
    errors: list[str]


class _AuditLog:
    """Append-only JSONL audit trail for engine events.

    Survives process restarts. Daily rotation, 30-day retention.
    Complements the in-memory ring buffer (100 entries) with
    persistent long-term history.
    """

    def __init__(self, base_dir: Path, retention_days: int = 30) -> None:
        self._base_dir = base_dir
        self._retention_days = retention_days
        self._current_date: str = ""
        self._file = None

    def write(self, entry: _HistoryEntry) -> None:
        """Append a history entry to the JSONL audit log."""
        import json

        try:
            f = self._get_file()
            record = {
                "ts": entry.timestamp.isoformat(),
                "event_path": entry.event_path,
                "event_type": entry.event_type,
                "doc_type": entry.doc_type,
                "rules_matched": entry.rules_matched,
                "actions": entry.actions,
                "errors": entry.errors,
            }
            f.write(json.dumps(record, default=str) + "\n")
            f.flush()
        except Exception:
            _log.warning("Failed to write audit log", exc_info=True)

    def cleanup(self) -> None:
        """Remove audit files older than retention_days."""
        import datetime as dt

        cutoff = dt.date.today() - dt.timedelta(days=self._retention_days)
        for path in self._base_dir.glob("engine-audit-*.jsonl"):
            try:
                date_str = path.stem.replace("engine-audit-", "")
                file_date = dt.date.fromisoformat(date_str)
                if file_date < cutoff:
                    path.unlink()
                    _log.debug("Cleaned up old audit log: %s", path.name)
            except (ValueError, OSError):
                pass

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def _get_file(self):
        import datetime as dt

        today = dt.date.today().isoformat()
        if today != self._current_date:
            if self._file is not None:
                self._file.close()
            self._base_dir.mkdir(parents=True, exist_ok=True)
            path = self._base_dir / f"engine-audit-{today}.jsonl"
            self._file = open(path, "a", encoding="utf-8")  # noqa: SIM115
            self._current_date = today
        return self._file


class ReactiveEngine:
    """Orchestrator wiring watcher, rules, executor, and delivery."""

    def __init__(
        self,
        data_dir: Path | None = None,
        watch_paths: list[Path] | None = None,
        debounce_ms: int | None = None,
        gpu_concurrency: int | None = None,
        cloud_concurrency: int | None = None,
        action_timeout_s: float | None = None,
        quiet_window_s: float | None = None,
        cooldown_default_s: float | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._event_bus = event_bus
        mode = get_working_mode()
        default_debounce = 1500 if mode == WorkingMode.RESEARCH else 500

        self._data_dir = data_dir or PROFILES_DIR
        self._debounce_ms = debounce_ms or _env_int("ENGINE_DEBOUNCE_MS", default_debounce)
        self._gpu_concurrency = gpu_concurrency or _env_int("ENGINE_GPU_CONCURRENCY", 1)
        self._cloud_concurrency = cloud_concurrency or _env_int("ENGINE_CLOUD_CONCURRENCY", 2)
        self._action_timeout_s = action_timeout_s or _env_float("ENGINE_ACTION_TIMEOUT_S", 120)
        self._quiet_window_s = quiet_window_s or _env_float("ENGINE_QUIET_WINDOW_S", 180)
        self._cooldown_default_s = cooldown_default_s or _env_float("ENGINE_COOLDOWN_S", 600)

        # Voice state directory for presence/consent reactive rules
        _voice_state_dir = Path.home() / ".cache" / "hapax-daimonion"

        # Watch biometric state directory for biometric cascade rules
        _watch_state_dir = Path.home() / "hapax-state" / "watch"

        self._watch_paths = watch_paths or [
            PROFILES_DIR,
            RAG_SOURCES_DIR,
            AI_AGENTS_DIR / "axioms",
            _voice_state_dir,
            _watch_state_dir,
        ]

        self._registry = RuleRegistry()
        self._executor = PhasedExecutor(
            gpu_concurrency=self._gpu_concurrency,
            cloud_concurrency=self._cloud_concurrency,
            action_timeout_s=self._action_timeout_s,
        )
        self._watcher: DirectoryWatcher | None = None
        self._paused = False
        self._running = False
        self._start_time: float | None = None

        # Impingement cascade integration
        from logos._affordance import CapabilityRecord
        from logos._affordance_pipeline import AffordancePipeline
        from logos.engine.converter import convert as _convert
        from logos.engine.rule_capability import RuleCapability, generate_rule_description

        self._convert_event = _convert
        self._rule_capability_class = RuleCapability
        self._generate_rule_description = generate_rule_description
        self._affordance_pipeline = AffordancePipeline()
        self._cascade_initialized = False
        self._rule_capability_record_class = CapabilityRecord

        # Counters
        self._events_processed = 0
        self._rules_evaluated = 0
        self._actions_executed = 0
        self._error_count = 0

        # History ring buffer (fast API queries) + persistent audit log
        self._history: deque[_HistoryEntry] = deque(maxlen=100)
        self._audit_log = _AuditLog(
            base_dir=self._data_dir / "engine-audit",
            retention_days=30,
        )
        self._audit_log.cleanup()  # prune old files on startup

        # Persistent event pattern counters (WS2 novelty detection)
        self._counters_path = self._data_dir / "engine-counters.json"
        self._pattern_counters: dict[str, int] = _load_counters(self._counters_path)
        self._counter_save_interval = 50  # save every N events
        self._events_since_save = 0

        # WS4: time-windowed frequency tracker (distribution shift detection)
        from logos._frequency_window import FrequencyWindow

        self._frequency_window = FrequencyWindow(window_s=3600.0)  # 1 hour window

    @staticmethod
    def _agent_from_path(path: str) -> str:
        from pathlib import PurePosixPath

        for p in PurePosixPath(path).parts:
            if p.startswith("hapax-"):
                return p.removeprefix("hapax-")
        return "unknown"

    @property
    def registry(self) -> RuleRegistry:
        """Expose rule registry for external registration."""
        return self._registry

    @property
    def status(self) -> dict[str, object]:
        """Current engine status."""
        uptime = time.monotonic() - self._start_time if self._start_time else 0
        return {
            "running": self._running,
            "paused": self._paused,
            "uptime_s": round(uptime, 1),
            "events_processed": self._events_processed,
            "rules_evaluated": self._rules_evaluated,
            "actions_executed": self._actions_executed,
            "errors": self._error_count,
            "unique_patterns": len(self._pattern_counters),
            "novelty_score": self.novelty_score,
            "shift_score": self.shift_score,
            "window_events": self._frequency_window.total_in_window,
        }

    @property
    def novelty_score(self) -> float:
        """Fraction of recent events that are novel (seen <= 2 times).

        0.0 = all patterns are well-known. 1.0 = all patterns are novel.
        Used by stimmung collector for processing_throughput dimension.
        """
        if not self._history:
            return 0.0
        recent = list(self._history)[-20:]  # last 20 events
        novel = 0
        for entry in recent:
            key = _event_pattern_key(
                "modified",  # history doesn't store event_type, approximate
                entry.doc_type,
                entry.rules_matched,
            )
            count = self._pattern_counters.get(key, 0)
            if count <= 2:
                novel += 1
        return round(novel / len(recent), 2)

    @property
    def shift_score(self) -> float:
        """Distribution shift between recent (1h) and historical event patterns.

        0.0 = recent patterns match long-term baseline.
        1.0 = recent patterns are maximally different from baseline.
        High values signal regime change (new activity, new data sources, etc.).
        """
        return self._frequency_window.shift_score(self._pattern_counters)

    @property
    def history(self) -> list[_HistoryEntry]:
        """Recent event history (newest first)."""
        return list(reversed(self._history))

    async def start(self) -> None:
        """Start the watcher and begin processing events."""
        if self._running:
            _log.warning("Engine already running")
            return

        from logos.engine.watcher import DirectoryWatcher

        loop = asyncio.get_running_loop()
        self._watcher = DirectoryWatcher(
            watch_paths=self._watch_paths,
            callback=self._handle_change,
            debounce_ms=self._debounce_ms,
            loop=loop,
            data_dir=self._data_dir,
        )
        await self._watcher.start()
        self._running = True
        self._start_time = time.monotonic()
        _log.info(
            "Reactive engine started (debounce=%dms, gpu=%d, cloud=%d)",
            self._debounce_ms,
            self._gpu_concurrency,
            self._cloud_concurrency,
        )

    async def stop(self) -> None:
        """Stop the watcher and clean up."""
        if not self._running:
            return

        if self._watcher is not None:
            await self._watcher.stop()
            self._watcher = None

        self._running = False
        _save_counters(self._pattern_counters, self._counters_path)
        self._audit_log.close()
        _log.info("Reactive engine stopped")

    def pause(self) -> None:
        """Pause rule evaluation (events still debounced but not processed)."""
        self._paused = True
        _log.info("Engine paused")

    def resume(self) -> None:
        """Resume rule evaluation."""
        self._paused = False
        _log.info("Engine resumed")

    def ignore_fn(self, path: Path) -> None:
        """Register a path as own-write (passthrough to watcher)."""
        if self._watcher is not None:
            self._watcher.ignore_fn(path)

    def _read_stimmung_stance(self) -> str:
        """Read current stimmung stance from /dev/shm. Returns 'nominal' on error or stale data."""
        import json

        stimmung_path = Path("/dev/shm/hapax-stimmung/state.json")
        try:
            data = json.loads(stimmung_path.read_text(encoding="utf-8"))
            ts = data.get("timestamp", 0)
            if ts > 0 and (time.time() - ts) > 300:
                return "nominal"
            return data.get("overall_stance", "nominal")
        except (OSError, json.JSONDecodeError):
            return "nominal"

    def _read_presence_state(self) -> str:
        """Read current Bayesian presence state. Returns 'PRESENT' on error (fail-open)."""
        import json

        state_path = Path.home() / ".cache" / "hapax-daimonion" / "perception-state.json"
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            return data.get("presence_state", "PRESENT") or "PRESENT"
        except (OSError, json.JSONDecodeError):
            return "PRESENT"

    async def _handle_change(self, event: ChangeEvent) -> None:
        """Core event handler: evaluate rules → execute plan → log results.

        WS2: stimmung-modulated processing. When system is degraded/critical,
        skip non-critical GPU/LLM actions (phase 1+2) to conserve resources.
        Phase 0 (deterministic) always runs.
        """
        if self._paused:
            _log.debug("Paused, ignoring event: %s", event.path)
            return

        self._events_processed += 1

        _log.info(
            "Event: %s %s (doc_type=%s)",
            event.event_type,
            event.path,
            event.doc_type,
        )

        from logos._telemetry import hapax_score, hapax_span, hapax_trace

        with hapax_trace(
            "engine",
            "event",
            metadata={
                "path": str(event.path),
                "event_type": event.event_type,
                "doc_type": event.doc_type or "",
            },
        ) as _engine_trace:
            # Evaluate rules (legacy path — rules still work unchanged)
            with hapax_span(
                "engine", "evaluate_rules", metadata={"rule_count": len(self._registry)}
            ):
                plan = evaluate_rules(event, self._registry)
            self._rules_evaluated += len(self._registry)

            # Chronicle: record rule matches
            if plan.actions:
                _tid, _sid = current_otel_ids()
                chronicle_record(
                    ChronicleEvent(
                        ts=time.time(),
                        trace_id=_tid,
                        span_id=_sid,
                        parent_span_id=None,
                        source="engine",
                        event_type="rule.matched",
                        payload={
                            "rules": [a.name for a in plan.actions],
                            "event_path": str(event.path),
                            "doc_type": event.doc_type or "",
                        },
                    )
                )

            # Affordance pipeline: convert event and select capabilities
            try:
                if not self._cascade_initialized:
                    for rule in self._registry:
                        desc = self._generate_rule_description(rule)
                        self._affordance_pipeline.index_capability(
                            self._rule_capability_record_class(
                                name=rule.name,
                                description=desc,
                                daemon="logos_engine",
                            )
                        )
                    self._cascade_initialized = True
                    _log.info(
                        "Affordance pipeline: %d rule capabilities indexed", len(self._registry)
                    )

                impingement = self._convert_event(event)
                # Inject OTel trace context for chronicle causal chains
                if impingement is not None:
                    _tid, _sid = current_otel_ids()
                    from shared.impingement import Impingement

                    impingement = Impingement(
                        id=impingement.id,
                        timestamp=impingement.timestamp,
                        source=impingement.source,
                        type=impingement.type,
                        strength=impingement.strength,
                        content=impingement.content,
                        context=impingement.context,
                        interrupt_token=impingement.interrupt_token,
                        parent_id=impingement.parent_id,
                        trace_id=_tid,
                        span_id=_sid,
                        embedding=impingement.embedding,
                    )
                candidates = self._affordance_pipeline.select(impingement)
                if candidates:
                    _log.debug(
                        "Affordance selection: %d candidates for %s",
                        len(candidates),
                        event.path.name,
                    )
            except Exception:
                _log.debug("Affordance selection failed (non-fatal)", exc_info=True)

            if not plan.actions:
                _log.debug("No rules matched for %s", event.path)
                return

            # Phase gating: skip expensive phases (1+2) when system is stressed
            # or operator is away (no reason to burn GPU/cloud when nobody's here)
            skip_expensive = False
            skip_reason = ""

            stance = self._read_stimmung_stance()
            if stance in (Stance.DEGRADED, Stance.CRITICAL):
                skip_expensive = True
                skip_reason = f"stimmung:{stance}"

            presence = self._read_presence_state()
            if presence == "AWAY":
                skip_expensive = True
                skip_reason = skip_reason or f"presence:{presence}"

            if skip_expensive:
                original_count = len(plan.actions)
                plan.actions = [a for a in plan.actions if a.phase == 0]
                skipped = original_count - len(plan.actions)
                if skipped > 0:
                    _log.info(
                        "Phase gating (%s): skipped %d non-critical action(s)",
                        skip_reason,
                        skipped,
                    )
                    hapax_interaction(
                        "stimmung",
                        "engine",
                        "phase_gating",
                        metadata={
                            "reason": skip_reason,
                            "stance": stance,
                            "presence": presence,
                            "skipped_actions": skipped,
                        },
                    )
                if not plan.actions:
                    return

            # Inject ignore_fn into handlers that accept it (phase-2 self-trigger prevention)
            import inspect

            for action in plan.actions:
                sig = inspect.signature(action.handler)
                if "ignore_fn" in sig.parameters and "ignore_fn" not in action.args:
                    action.args["ignore_fn"] = self.ignore_fn

            _log.info(
                "Matched %d action(s): %s",
                len(plan.actions),
                [a.name for a in plan.actions],
            )

            # Execute
            with hapax_span(
                "engine",
                "execute",
                metadata={
                    "action_count": len(plan.actions),
                    "actions": [a.name for a in plan.actions],
                },
            ):
                await self._executor.execute(plan)
            self._actions_executed += len(plan.results)
            self._error_count += len(plan.errors)

            # Chronicle: record action executions
            _tid, _sid = current_otel_ids()
            for action_name in plan.results:
                chronicle_record(
                    ChronicleEvent(
                        ts=time.time(),
                        trace_id=_tid,
                        span_id=_sid,
                        parent_span_id=None,
                        source="engine",
                        event_type="action.executed",
                        payload={
                            "action_name": action_name,
                            "event_path": str(event.path),
                        },
                    )
                )

            if self._event_bus:
                for action_name in plan.results:
                    from logos.event_bus import FlowEvent

                    self._event_bus.emit(
                        FlowEvent(
                            kind="engine.action",
                            source=self._agent_from_path(str(event.path)),
                            target=action_name,
                            label=action_name,
                            trace_id=_tid,
                            span_id=_sid,
                        )
                    )

            # Score the engine trace
            hapax_score(_engine_trace, "actions_completed", float(len(plan.results)))
            hapax_score(_engine_trace, "actions_errored", float(len(plan.errors)))

        if plan.errors:
            _log.warning("Action errors: %s", plan.errors)

        # Record history (ring buffer + persistent audit)
        matched_rules = [a.name for a in plan.actions]
        entry = _HistoryEntry(
            timestamp=event.timestamp,
            event_path=str(event.path),
            event_type=event.event_type,
            doc_type=event.doc_type,
            rules_matched=matched_rules,
            actions=list(plan.results.keys()),
            errors=list(plan.errors.keys()),
        )
        self._history.append(entry)
        self._audit_log.write(entry)

        # WS2/WS4: track event pattern for novelty + distribution shift detection
        pattern_key = _event_pattern_key(event.event_type, event.doc_type, matched_rules)
        prev_count = self._pattern_counters.get(pattern_key, 0)
        self._pattern_counters[pattern_key] = prev_count + 1
        self._frequency_window.record(pattern_key)

        # Flag novel patterns (first or second occurrence)
        if prev_count == 0:
            _log.info("NOVEL event pattern (first occurrence): %s", pattern_key)
            hapax_event(
                "prediction",
                "novel_pattern",
                metadata={"pattern": pattern_key, "occurrence": 1},
                level="WARNING",
            )
        elif prev_count == 1:
            _log.info("Rare event pattern (second occurrence): %s", pattern_key)

        # WS4: check for distribution shift (every 10 events)
        if self._events_processed % 10 == 0:
            shift = self.shift_score
            if shift > 0.5:
                _log.warning(
                    "Distribution shift detected (score=%.3f, window=%d events)",
                    shift,
                    self._frequency_window.total_in_window,
                )
                hapax_event(
                    "prediction",
                    "distribution_shift",
                    metadata={"shift_score": shift},
                    level="WARNING",
                )

        # Periodic save
        self._events_since_save += 1
        if self._events_since_save >= self._counter_save_interval:
            _save_counters(self._pattern_counters, self._counters_path)
            self._events_since_save = 0
