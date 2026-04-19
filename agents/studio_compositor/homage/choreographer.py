"""Choreographer — reconciles pending HOMAGE transitions against concurrency.

HOMAGE spec §4.9. The single arbiter of "nothing plopped or pasted":
every ward transition goes through this module. Reads pending moves
from ``/dev/shm/hapax-compositor/homage-pending-transitions.json``,
applies the package's concurrency rules, emits the ordered plan via
``animation_engine.append_transitions`` (Phase 11+ consumes), and
publishes the 4-float shader coupling payload into
``/dev/shm/hapax-imagination/uniforms.json``.

Feature-flag: when ``HAPAX_HOMAGE_ACTIVE=0`` (default until Phase 12)
``reconcile()`` returns an empty plan and emits nothing — the legacy
paint-and-hold path stays in control.

Observability counters are emitted from
``shared/director_observability.py`` so the per-condition slicing
machinery already in place extends unchanged.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agents.studio_compositor.homage.substrate_source import (
    SUBSTRATE_SOURCE_REGISTRY,
    HomageSubstrateSource,
)
from shared.homage_coupling import (
    SHADER_READING_PATH,
    ShaderCouplingReading,
    hold_multiplier,
    read_shader_reading,
)
from shared.homage_package import HomagePackage, TransitionName

log = logging.getLogger(__name__)

_PENDING_TRANSITIONS: Path = Path("/dev/shm/hapax-compositor/homage-pending-transitions.json")
_UNIFORMS_JSON: Path = Path("/dev/shm/hapax-imagination/uniforms.json")
_SUBSTRATE_PACKAGE_FILE: Path = Path("/dev/shm/hapax-compositor/homage-substrate-package.json")


def _feature_flag_active() -> bool:
    value = os.environ.get("HAPAX_HOMAGE_ACTIVE", "").strip().lower()
    return value in ("1", "true", "yes", "on")


RejectionReason = Literal[
    "concurrency-limit",
    "malformed-entry",
    "unknown-transition",
    "feature-flag-off",
]


@dataclass(frozen=True, slots=True)
class PendingTransition:
    """One entry in the pending-transitions queue."""

    source_id: str
    transition: TransitionName
    enqueued_at: float


@dataclass(frozen=True, slots=True)
class PlannedTransition:
    """One entry in the choreographer's output plan."""

    source_id: str
    transition: TransitionName
    phase: Literal["entry", "exit", "modify"]
    start_at: float


@dataclass(frozen=True, slots=True)
class Rejection:
    """A pending transition the choreographer declined."""

    source_id: str
    transition: TransitionName
    reason: RejectionReason


@dataclass(frozen=True, slots=True)
class CoupledPayload:
    """The 4-float payload written into ``uniforms.custom[slot]``."""

    active_transition_energy: float
    palette_accent_hue_deg: float
    signature_artefact_intensity: float
    rotation_phase: float

    def to_floats(self) -> tuple[float, float, float, float]:
        return (
            self.active_transition_energy,
            self.palette_accent_hue_deg,
            self.signature_artefact_intensity,
            self.rotation_phase,
        )


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """Outcome of one reconcile() call."""

    planned: tuple[PlannedTransition, ...]
    rejections: tuple[Rejection, ...]
    coupled_payload: CoupledPayload


_ENTRY = frozenset(["zero-cut-in", "ticker-scroll-in", "join-message"])
_EXIT = frozenset(["zero-cut-out", "ticker-scroll-out", "part-message"])
_MODIFY = frozenset(["topic-change", "mode-change", "netsplit-burst"])


class Choreographer:
    """Per-tick reconciliation + emission.

    Construct once per compositor session; call ``reconcile()`` every
    tick. The class holds only per-tick state (the next expected
    netsplit-burst time); longer-lived state is in the SHM files.
    """

    def __init__(
        self,
        *,
        pending_file: Path = _PENDING_TRANSITIONS,
        uniforms_file: Path = _UNIFORMS_JSON,
        shader_reading_file: Path = SHADER_READING_PATH,
        substrate_package_file: Path = _SUBSTRATE_PACKAGE_FILE,
        source_registry: object | None = None,
    ) -> None:
        self._pending_file = pending_file
        self._uniforms_file = uniforms_file
        self._shader_reading_file = shader_reading_file
        self._substrate_package_file = substrate_package_file
        # Optional SourceRegistry handle (duck-typed). When provided, the
        # choreographer cross-checks registered backend instances against
        # ``HomageSubstrateSource`` so per-instance substrate declarations
        # are respected alongside the static SUBSTRATE_SOURCE_REGISTRY.
        self._source_registry = source_registry
        self._last_netsplit_burst_ts: float | None = None
        self._rotation_phase: float = 0.0
        self._last_package_broadcast: str | None = None

    # ── Phase 6: shader → ward reverse-path ─────────────────────────────

    def read_shader_coupling(self) -> ShaderCouplingReading | None:
        """Poll the Phase 6 shader feedback file.

        Returns ``None`` when the publisher has not written yet, the
        file is unreadable, or its contents are malformed. Callers must
        treat ``None`` as "default timer pacing" — never as an error.
        """
        return read_shader_reading(self._shader_reading_file)

    def hold_pacing_multiplier(self, *, now: float) -> float:
        """Current ward-hold pacing multiplier from shader feedback.

        ``> 1.0`` → extend holds (high shader energy, let GPU breathe).
        ``< 1.0`` → shorten holds (high drift, break feedback lock-in).
        ``1.0``  → neutral / default timer pacing.
        """
        reading = self.read_shader_coupling()
        return hold_multiplier(reading, now=now)

    # ── Public surface ──────────────────────────────────────────────────

    def reconcile(
        self,
        package: HomagePackage,
        *,
        now: float | None = None,
    ) -> ReconcileResult:
        """Read pending transitions, plan the tick, publish coupling."""
        clock = time.monotonic() if now is None else now

        if not _feature_flag_active():
            payload = CoupledPayload(0.0, 0.0, 0.0, 0.0)
            return ReconcileResult((), (), payload)

        pending = self._read_pending()
        # Consume: the choreographer owns these after read.
        self._clear_pending()

        # HOMAGE #124 — substrate filter. Sources flagged as always-on
        # (``HomageSubstrateSource``, e.g. Reverie) never enter the FSM
        # so we drop their pending entries before the entry/exit/modify
        # partition. Skipped entries are counter-emitted so any non-zero
        # rate surfaces in Grafana as a design violation.
        substrate_ids = self._resolve_substrate_ids()
        skipped_substrate = [p for p in pending if p.source_id in substrate_ids]
        pending = [p for p in pending if p.source_id not in substrate_ids]
        for p in skipped_substrate:
            self._emit_substrate_skip(p.source_id)

        # Package-palette broadcast to substrate sources. Always runs —
        # even on empty plans — so Reverie picks up hue shifts on every
        # package swap without needing a transition to be scheduled.
        self.broadcast_package_to_substrates(package, substrate_ids=substrate_ids)

        planned: list[PlannedTransition] = []
        rejections: list[Rejection] = []

        entries = [p for p in pending if p.transition in _ENTRY]
        exits = [p for p in pending if p.transition in _EXIT]
        modifies = [p for p in pending if p.transition in _MODIFY]
        unknown = [
            p
            for p in pending
            if p.transition not in _ENTRY
            and p.transition not in _EXIT
            and p.transition not in _MODIFY
        ]

        for p in unknown:
            rejections.append(Rejection(p.source_id, p.transition, "unknown-transition"))

        max_entries = package.transition_vocabulary.max_simultaneous_entries
        max_exits = package.transition_vocabulary.max_simultaneous_exits

        for i, p in enumerate(entries):
            if i < max_entries:
                planned.append(PlannedTransition(p.source_id, p.transition, "entry", clock))
            else:
                rejections.append(Rejection(p.source_id, p.transition, "concurrency-limit"))

        for i, p in enumerate(exits):
            if i < max_exits:
                planned.append(PlannedTransition(p.source_id, p.transition, "exit", clock))
            else:
                rejections.append(Rejection(p.source_id, p.transition, "concurrency-limit"))

        # Netsplit-burst gate: only one burst per ``netsplit_burst_min_interval_s``.
        for p in modifies:
            if p.transition == "netsplit-burst":
                last = self._last_netsplit_burst_ts
                min_interval = package.transition_vocabulary.netsplit_burst_min_interval_s
                if last is not None and (clock - last) < min_interval:
                    rejections.append(Rejection(p.source_id, p.transition, "concurrency-limit"))
                    continue
                self._last_netsplit_burst_ts = clock
            planned.append(PlannedTransition(p.source_id, p.transition, "modify", clock))

        # Metrics (spec §6) — best-effort, non-fatal.
        self._emit_metrics(package, planned, rejections)

        # Coupling payload (spec §4.6) — publish even on empty plan so
        # shader energy decays cleanly rather than sticking at its last
        # non-zero value.
        payload = self._compute_payload(package, planned, clock)
        self._publish_payload(package, payload)

        return ReconcileResult(tuple(planned), tuple(rejections), payload)

    # ── Internals ───────────────────────────────────────────────────────

    def _read_pending(self) -> list[PendingTransition]:
        try:
            if not self._pending_file.exists():
                return []
            data = json.loads(self._pending_file.read_text(encoding="utf-8"))
        except Exception:
            log.debug("homage-pending-transitions.json unreadable", exc_info=True)
            return []

        raw = data.get("transitions") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            return []

        out: list[PendingTransition] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            source_id = entry.get("source_id")
            transition = entry.get("transition")
            enqueued_at = entry.get("enqueued_at")
            if (
                isinstance(source_id, str)
                and source_id
                and isinstance(transition, str)
                and transition
                and isinstance(enqueued_at, (int, float))
            ):
                out.append(
                    PendingTransition(
                        source_id=source_id,
                        transition=transition,  # type: ignore[arg-type]
                        enqueued_at=float(enqueued_at),
                    )
                )
        return out

    def _clear_pending(self) -> None:
        try:
            if self._pending_file.exists():
                self._pending_file.unlink()
        except Exception:
            log.debug("failed to clear homage-pending-transitions", exc_info=True)

    def _compute_payload(
        self,
        package: HomagePackage,
        planned: list[PlannedTransition],
        now: float,
    ) -> CoupledPayload:
        """Build the 4-float payload for ``uniforms.custom[slot]``.

        Bands:
        - active_transition_energy: 1.0 while any plan entry is live;
          decays linearly to 0 over 0.5s after completion.
        - palette_accent_hue_deg: fixed per package (BitchX cyan ≈ 180°).
        - signature_artefact_intensity: 0 unless an artefact just
          rotated (publisher sets this via a separate SHM hint file
          in Phase 8).
        - rotation_phase: monotonically increasing [0, 1] clock with
          the package's steady cadence.
        """
        energy = 1.0 if planned else 0.0
        # mIRC 11 cyan maps to ~180°; other packages override.
        hue = 180.0 if package.name == "bitchx" else 0.0
        intensity = 0.0
        cadence = package.signature_conventions.rotation_cadence_s_steady
        if cadence > 0:
            self._rotation_phase = (now % cadence) / cadence
        return CoupledPayload(energy, hue, intensity, self._rotation_phase)

    def _publish_payload(self, package: HomagePackage, payload: CoupledPayload) -> None:
        """Merge the four coupling floats into ``uniforms.json``.

        Uses atomic tmp+rename. Non-destructive: reads existing uniform
        keys, updates only the ``signal.homage_custom_{i}`` slot entries
        for indices matching ``package.coupling_rules.custom_slot_index``.
        """
        try:
            self._uniforms_file.parent.mkdir(parents=True, exist_ok=True)
            current: dict[str, float] = {}
            if self._uniforms_file.exists():
                try:
                    current = json.loads(self._uniforms_file.read_text(encoding="utf-8"))
                    if not isinstance(current, dict):
                        current = {}
                except Exception:
                    current = {}
            slot = package.coupling_rules.custom_slot_index
            floats = payload.to_floats()
            for i, value in enumerate(floats):
                current[f"signal.homage_custom_{slot}_{i}"] = value
            tmp = self._uniforms_file.with_suffix(self._uniforms_file.suffix + ".tmp")
            tmp.write_text(json.dumps(current), encoding="utf-8")
            tmp.replace(self._uniforms_file)
        except Exception:
            log.debug("failed to publish homage coupling payload", exc_info=True)

    def _emit_metrics(
        self,
        package: HomagePackage,
        planned: list[PlannedTransition],
        rejections: list[Rejection],
    ) -> None:
        """Best-effort Prometheus metric emission. Non-fatal on failure."""
        try:
            from shared.director_observability import (
                emit_homage_choreographer_rejection,
                emit_homage_package_active,
                emit_homage_transition,
            )
        except Exception:
            return
        try:
            emit_homage_package_active(package.name)
            for plan in planned:
                emit_homage_transition(package.name, plan.transition)
            for rejection in rejections:
                emit_homage_choreographer_rejection(rejection.reason)
        except Exception:
            log.debug("homage metric emission failed", exc_info=True)

    # ── HOMAGE #124: substrate preservation ─────────────────────────────

    def _resolve_substrate_ids(self) -> frozenset[str]:
        """Return the set of source_ids currently flagged as substrate.

        Union of:
          * the static ``SUBSTRATE_SOURCE_REGISTRY`` (spec §4 table), and
          * any backend registered with ``self._source_registry`` that
            satisfies ``HomageSubstrateSource`` at runtime.

        The resolution is cheap and runs once per ``reconcile()`` call.
        """
        ids: set[str] = set(SUBSTRATE_SOURCE_REGISTRY)
        registry = self._source_registry
        if registry is None:
            return frozenset(ids)
        # Duck-typed: SourceRegistry exposes ``ids()`` and
        # ``_backends`` (Phase 11b). Fall back gracefully if not.
        backends = getattr(registry, "_backends", None)
        if not isinstance(backends, dict):
            return frozenset(ids)
        for source_id, backend in backends.items():
            try:
                # ``runtime_checkable`` Protocol isinstance only checks
                # attribute *presence*, not value. We additionally gate
                # on truthiness so only instances that explicitly set
                # ``is_substrate=True`` are classified as substrate.
                if isinstance(backend, HomageSubstrateSource) and bool(
                    getattr(backend, "is_substrate", False)
                ):
                    ids.add(source_id)
            except Exception:
                log.debug("substrate isinstance check failed for %s", source_id, exc_info=True)
        return frozenset(ids)

    def _emit_substrate_skip(self, source_id: str) -> None:
        """Non-fatal metric hook for substrate-filtered pending entries."""
        try:
            from shared.director_observability import (
                emit_homage_choreographer_substrate_skip,
            )
        except Exception:
            return
        try:
            emit_homage_choreographer_substrate_skip(source_id)
        except Exception:
            log.debug("homage substrate-skip metric emission failed", exc_info=True)

    def broadcast_package_to_substrates(
        self,
        package: HomagePackage,
        *,
        substrate_ids: frozenset[str] | None = None,
    ) -> None:
        """Broadcast palette-hint payload to substrate sources.

        Writes ``/dev/shm/hapax-compositor/homage-substrate-package.json``
        with the active package's name, resolved palette accent hue, and
        the list of substrate source_ids that should consume the hint.
        Reverie reads this file (or the mirrored ``custom[4]`` uniform
        slot) to tint its output without FSM gating.

        Idempotent under repeated calls with the same package — the file
        is only rewritten when the package name changes, so inotify
        watchers don't see spurious events on every reconcile tick.
        """
        if substrate_ids is None:
            substrate_ids = self._resolve_substrate_ids()
        if self._last_package_broadcast == package.name:
            # Same package as last call; atomic-refresh is unnecessary.
            # Still rewrite if the file was externally deleted so
            # downstream readers recover after /dev/shm wipes.
            if self._substrate_package_file.exists():
                return
        try:
            self._substrate_package_file.parent.mkdir(parents=True, exist_ok=True)
            hue = 180.0 if package.name == "bitchx" else 0.0
            payload = {
                "package": package.name,
                "palette_accent_hue_deg": hue,
                "custom_slot_index": package.coupling_rules.custom_slot_index,
                "substrate_source_ids": sorted(substrate_ids),
            }
            tmp = self._substrate_package_file.with_suffix(
                self._substrate_package_file.suffix + ".tmp"
            )
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(self._substrate_package_file)
            self._last_package_broadcast = package.name
        except Exception:
            log.debug("failed to broadcast homage substrate package", exc_info=True)


__all__ = [
    "Choreographer",
    "CoupledPayload",
    "PendingTransition",
    "PlannedTransition",
    "ReconcileResult",
    "Rejection",
    "RejectionReason",
]
