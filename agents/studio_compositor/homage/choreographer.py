"""Choreographer — reconciles pending HOMAGE transitions against concurrency.

HOMAGE spec §4.9. The single arbiter of "nothing plopped or pasted":
every ward transition goes through this module. Reads pending moves
from ``/dev/shm/hapax-compositor/homage-pending-transitions.json``,
applies the package's concurrency rules, emits the ordered plan via
``animation_engine.append_transitions`` (Phase 11+ consumes), and
publishes the 4-float shader coupling payload into
``/dev/shm/hapax-imagination/uniforms.json``.

Feature-flag: as of Phase 12 (task #120, 2026-04-18) the flag defaults
to ON. Setting ``HAPAX_HOMAGE_ACTIVE=0`` (or any falsy value: ``false``,
``no``, ``off``) short-circuits ``reconcile()`` back to the legacy
paint-and-hold path for emergency rollback.

Observability counters are emitted from
``shared/director_observability.py`` so the per-condition slicing
machinery already in place extends unchanged.
"""

from __future__ import annotations

import json
import logging
import os
import random
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
from shared.homage_package import (
    HomagePackage,
    SignatureArtefact,
    TransitionName,
)

log = logging.getLogger(__name__)

_PENDING_TRANSITIONS: Path = Path("/dev/shm/hapax-compositor/homage-pending-transitions.json")
_UNIFORMS_JSON: Path = Path("/dev/shm/hapax-imagination/uniforms.json")
_SUBSTRATE_PACKAGE_FILE: Path = Path("/dev/shm/hapax-compositor/homage-substrate-package.json")
# Phase 8 (task #114): structural director publish path. The
# choreographer reads ``homage_rotation_mode`` from this file every
# reconcile tick so the structural director (slow 90s cadence) can drive
# the rotation strategy without narrative-tick coupling. Missing, stale,
# or malformed file → default "sequential". Path matches
# ``structural_director.py::_STRUCTURAL_INTENT_PATH``.
_STRUCTURAL_INTENT_FILE: Path = Path("/dev/shm/hapax-structural/intent.json")
# Phase 7 (task #113): voice register file. Read by
# ``agents.hapax_daimonion.cpal.register_bridge`` before each TTS
# emission. Choreographer writes on every package swap — including the
# consent-safe variant swap, so the register stays stable even when the
# palette goes grey (BitchX consent-safe still declares TEXTMODE).
_VOICE_REGISTER_FILE: Path = Path("/dev/shm/hapax-compositor/homage-voice-register.json")
# Phase 12: the consent-live-egress guard writes this file when it flips
# the compositor into consent-safe layout. The choreographer reads it
# every reconcile tick and, when present, swaps the active package for
# its consent-safe variant (pure-grey palette, empty artefact corpus).
# Intentionally co-located with the other /dev/shm/hapax-compositor/
# state files so a single wipe restores the default layout.
_CONSENT_SAFE_FLAG_FILE: Path = Path("/dev/shm/hapax-compositor/consent-safe-active.json")
# Phase 12: signature artefact rotation cadence is tracked per-source
# so multiple choreographer instances can co-exist in tests without
# racing on the random selection. The intensity-boost window is short
# (one reconcile tick) — the Cairo sources do the actual rendering of
# the selected artefact text; the choreographer only chooses and
# announces.
_ARTEFACT_INTENSITY_ACTIVE: float = 1.0
_ARTEFACT_INTENSITY_IDLE: float = 0.0


def _feature_flag_active() -> bool:
    """Phase 12 default-ON. Unset env or any truthy value → active.

    Explicit disable requires ``HAPAX_HOMAGE_ACTIVE=0`` (or ``false``,
    ``no``, ``off``) — the rollback escape hatch. This inversion is
    load-bearing: operators who wipe env vars (or services that lose
    their environment) must still land in HOMAGE, not in paint-and-hold.
    """
    raw = os.environ.get("HAPAX_HOMAGE_ACTIVE")
    if raw is None:
        return True
    value = raw.strip().lower()
    if value == "":
        return True
    return value not in ("0", "false", "no", "off")


RejectionReason = Literal[
    "concurrency-limit",
    "malformed-entry",
    "unknown-transition",
    "feature-flag-off",
]


@dataclass(frozen=True, slots=True)
class PendingTransition:
    """One entry in the pending-transitions queue.

    Phase 8 (task #114): ``salience`` is an optional [0.0, 1.0] relevance
    score producers can attach. Defaults to ``0.0`` when absent so
    ``sequential`` / ``random`` rotation modes are unaffected.
    ``weighted_by_salience`` rotation mode sorts pending entries by this
    field descending before applying concurrency limits.
    """

    source_id: str
    transition: TransitionName
    enqueued_at: float
    salience: float = 0.0


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
        consent_safe_flag_file: Path = _CONSENT_SAFE_FLAG_FILE,
        voice_register_file: Path = _VOICE_REGISTER_FILE,
        structural_intent_file: Path = _STRUCTURAL_INTENT_FILE,
        source_registry: object | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._pending_file = pending_file
        self._uniforms_file = uniforms_file
        self._shader_reading_file = shader_reading_file
        self._substrate_package_file = substrate_package_file
        self._consent_safe_flag_file = consent_safe_flag_file
        self._voice_register_file = voice_register_file
        self._structural_intent_file = structural_intent_file
        # Optional SourceRegistry handle (duck-typed). When provided, the
        # choreographer cross-checks registered backend instances against
        # ``HomageSubstrateSource`` so per-instance substrate declarations
        # are respected alongside the static SUBSTRATE_SOURCE_REGISTRY.
        self._source_registry = source_registry
        self._last_netsplit_burst_ts: float | None = None
        self._rotation_phase: float = 0.0
        self._last_package_broadcast: str | None = None
        # Phase 12: signature-artefact rotation state.
        #   * ``_rng`` — injected for deterministic tests; defaults to
        #     system-random so production behaviour remains pseudo-random.
        #   * ``_last_rotation_cycle`` — integer index of the last
        #     rotation window an artefact was emitted for. We emit once
        #     per window to prevent artefact spam when ``reconcile()``
        #     runs faster than the configured rotation cadence.
        #   * ``_last_emitted_artefact`` — retained for observability /
        #     tests; Cairo consumers read ``homage-active-artefact.json``
        #     (published below) rather than touching the choreographer.
        self._rng: random.Random = rng if rng is not None else random.Random()
        self._last_rotation_cycle: int = -1
        self._last_emitted_artefact: SignatureArtefact | None = None

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
        """Read pending transitions, plan the tick, publish coupling.

        Phase 12 behaviour additions:
        - If the consent-safe flag file is present, swap ``package`` for
          its registered consent-safe variant before any reconciliation.
          When the flag clears, the next tick reverts to the caller's
          original package. The swap happens in one place so every
          downstream code path (substrate broadcast, coupling payload,
          artefact emission) inherits the restricted palette.
        - After concurrency reconciliation, roll the signature-artefact
          rotation. When the rotation cycle advances, select a random
          artefact from the package's corpus and publish the selection
          for Cairo consumers.
        """
        clock = time.monotonic() if now is None else now

        if not _feature_flag_active():
            payload = CoupledPayload(0.0, 0.0, 0.0, 0.0)
            return ReconcileResult((), (), payload)

        # Phase 12: consent-safe override. Rechecked every tick so that
        # the guard can flip in and out without restarting the
        # compositor. Explicit failure posture: if the resolver cannot
        # find the consent-safe variant, keep the caller-supplied
        # package — this matches the ``None``-fallback path downstream
        # wards already handle safely.
        if self._consent_safe_active():
            safe = self._resolve_consent_safe_package()
            if safe is not None:
                package = safe

        pending = self._read_pending()
        # Consume: the choreographer owns these after read.
        self._clear_pending()

        # Task #160 — HARDM communicative anchoring. When the weighted
        # salience bias exceeds the unskippable threshold and no HARDM
        # transition is already pending this tick, synthesize one at
        # the current bias salience so HARDM reliably locks into
        # rotation during voice / self-referential narrative / guest
        # consent / SEEKING stance. Best-effort: import errors and
        # evaluation failures silently fall through.
        pending = self._maybe_enqueue_hardm_anchor(package, pending, clock)

        # Phase 8 (task #114): fetch the structural director's rotation
        # mode so the FSM-advancing slice can be gated (paused) or
        # re-ordered (weighted_by_salience) without the structural
        # director owning any choreographer state. ``sequential`` is the
        # default when the intent file is missing/malformed/old.
        rotation_mode = self._read_rotation_mode()

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

        # Phase 7 (task #113): voice-register broadcast to CPAL. Runs
        # every tick — the consumer's staleness check refuses a file
        # older than 2s, so silence from here means "choreographer died,
        # fall back to DEFAULT_REGISTER". Rewriting is cheap.
        self._broadcast_voice_register(package, now=clock)

        planned: list[PlannedTransition] = []
        rejections: list[Rejection] = []

        # Phase 8: ``paused`` rotation mode. Drop every pending transition
        # this tick — no planned moves, no rejections (the rejection set
        # is reserved for the concurrency / feature-flag axes). Substrate
        # broadcast + coupling payload still publish below so Reverie
        # keeps its palette and shader energy decays cleanly.
        if rotation_mode == "paused":
            payload = self._compute_payload(package, planned, clock)
            self._publish_payload(package, payload)
            self._emit_metrics(package, planned, rejections)
            return ReconcileResult(tuple(planned), tuple(rejections), payload)

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

        # Phase 8: ``weighted_by_salience`` sorts entries/exits (highest
        # salience first) before the concurrency slice so the most-
        # salient wards win under contention. ``random`` and
        # ``sequential`` leave order as-is — producers fix the queue
        # order, the concurrency slice does the rest.
        if rotation_mode == "weighted_by_salience":
            entries = sorted(entries, key=lambda p: p.salience, reverse=True)
            exits = sorted(exits, key=lambda p: p.salience, reverse=True)

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
                raw_salience = entry.get("salience", 0.0)
                if isinstance(raw_salience, (int, float)):
                    salience = max(0.0, min(1.0, float(raw_salience)))
                else:
                    salience = 0.0
                out.append(
                    PendingTransition(
                        source_id=source_id,
                        transition=transition,  # type: ignore[arg-type]
                        enqueued_at=float(enqueued_at),
                        salience=salience,
                    )
                )
        return out

    def _clear_pending(self) -> None:
        try:
            if self._pending_file.exists():
                self._pending_file.unlink()
        except Exception:
            log.debug("failed to clear homage-pending-transitions", exc_info=True)

    # ── Task #160: HARDM communicative-anchoring anchor ───────────────

    def _maybe_enqueue_hardm_anchor(
        self,
        package: HomagePackage,
        pending: list[PendingTransition],
        now: float,
    ) -> list[PendingTransition]:
        """Synthesize a HARDM entry when bias > unskippable threshold.

        The synthetic entry joins the pending list at the current salience
        score. It is skipped (not re-synthesized) when a HARDM entry is
        already present this tick, so real recruitments retain priority.
        Evaluation cost is small (four SHM reads, bounded scan); failure
        falls open to the unmodified pending list.
        """
        try:
            from agents.studio_compositor.hardm_source import (
                UNSKIPPABLE_BIAS,
                current_salience_bias,
            )
        except Exception:
            log.debug("hardm_source import failed; skipping anchor", exc_info=True)
            return pending
        try:
            bias = current_salience_bias()
        except Exception:
            log.debug("current_salience_bias raised; skipping anchor", exc_info=True)
            return pending
        if bias <= UNSKIPPABLE_BIAS:
            return pending
        # Dedupe: a real producer entry this tick wins.
        for entry in pending:
            if entry.source_id == "hardm_dot_matrix":
                return pending
        transition = package.transition_vocabulary.default_entry
        synthetic = PendingTransition(
            source_id="hardm_dot_matrix",
            transition=transition,
            enqueued_at=now,
            salience=bias,
        )
        return [*pending, synthetic]

    # ── Phase 8: structural-director rotation-mode readback ────────────

    def _read_rotation_mode(
        self,
    ) -> Literal["sequential", "random", "weighted_by_salience", "paused"]:
        """Read ``homage_rotation_mode`` from the structural intent file.

        Fails open to ``"sequential"`` in every non-happy-path case:
        missing file, unreadable bytes, malformed JSON, non-dict payload,
        missing field, or unknown mode value. The choreographer never
        crashes because the structural director crashed.
        """
        try:
            if not self._structural_intent_file.exists():
                return "sequential"
            raw = self._structural_intent_file.read_text(encoding="utf-8")
        except Exception:
            log.debug("structural-intent read failed", exc_info=True)
            return "sequential"
        try:
            data = json.loads(raw)
        except Exception:
            log.debug("structural-intent json decode failed", exc_info=True)
            return "sequential"
        if not isinstance(data, dict):
            return "sequential"
        mode = data.get("homage_rotation_mode", "sequential")
        if mode in ("sequential", "random", "weighted_by_salience", "paused"):
            return mode  # type: ignore[return-value]
        return "sequential"

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
        - palette_accent_hue_deg: fixed per package (BitchX cyan ≈ 180°;
          consent-safe variant → 0° since every accent collapses to
          muted grey).
        - signature_artefact_intensity: 1.0 on the reconcile tick that
          just rolled into a new rotation cycle and successfully chose
          an artefact from the package's corpus. 0 otherwise.
        - rotation_phase: monotonically increasing [0, 1] clock with
          the package's steady cadence.
        """
        energy = 1.0 if planned else 0.0
        # mIRC 11 cyan maps to ~180°; consent-safe + other packages 0°.
        hue = 180.0 if package.name == "bitchx" else 0.0
        cadence = package.signature_conventions.rotation_cadence_s_steady
        if cadence > 0:
            self._rotation_phase = (now % cadence) / cadence
            cycle = int(now // cadence)
        else:
            cycle = self._last_rotation_cycle

        emitted = self._maybe_emit_signature_artefact(package, cycle=cycle)
        intensity = _ARTEFACT_INTENSITY_ACTIVE if emitted else _ARTEFACT_INTENSITY_IDLE

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

    # ── Phase 12: consent-safe + signature artefact emission ────────────

    def _consent_safe_active(self) -> bool:
        """Return True when the consent-safe flag file is present.

        The consent-live-egress guard writes this file (atomic tmp+rename)
        when it flips the compositor into compose-safe layout. Missing
        file or unreadable contents both resolve to False — fail-open
        here means the grey variant only engages on an explicit signal,
        not on every I/O hiccup. The HOMAGE feature flag still gates
        everything above this call.
        """
        try:
            return self._consent_safe_flag_file.exists()
        except Exception:
            log.debug("consent-safe flag existence check raised", exc_info=True)
            return False

    def _resolve_consent_safe_package(self) -> HomagePackage | None:
        """Look up the registered consent-safe variant.

        Deferred import to avoid the choreographer importing its own
        package during ``agents.studio_compositor.homage`` bootstrap.
        """
        try:
            from agents.studio_compositor.homage import get_consent_safe_package

            return get_consent_safe_package()
        except Exception:
            log.debug("consent-safe package lookup failed", exc_info=True)
            return None

    def _maybe_emit_signature_artefact(
        self,
        package: HomagePackage,
        *,
        cycle: int,
    ) -> SignatureArtefact | None:
        """Roll artefact selection once per rotation cycle.

        Returns the selected artefact (and publishes it) when the cycle
        index advances, else ``None``. An empty corpus (e.g., the
        consent-safe variant) is a no-op — we still bump the cycle
        counter so the next tick won't re-roll, but emit nothing.
        """
        if cycle == self._last_rotation_cycle:
            return None
        self._last_rotation_cycle = cycle

        corpus = package.signature_artefacts
        if not corpus:
            # Consent-safe / empty-corpus packages: intentional silence.
            self._last_emitted_artefact = None
            return None

        try:
            weights = [max(0.0, float(a.weight)) for a in corpus]
            if sum(weights) <= 0:
                chosen = self._rng.choice(corpus)
            else:
                chosen = self._rng.choices(corpus, weights=weights, k=1)[0]
        except Exception:
            log.debug("artefact selection raised", exc_info=True)
            return None

        self._last_emitted_artefact = chosen
        self._publish_active_artefact(package, chosen)
        self._emit_artefact_metric(package, chosen)
        return chosen

    def _publish_active_artefact(
        self,
        package: HomagePackage,
        artefact: SignatureArtefact,
    ) -> None:
        """Write the selected artefact to SHM for Cairo consumers.

        Atomic tmp+rename. Lives under ``/dev/shm/hapax-compositor/``
        alongside other HOMAGE state. Cairo sources poll this file;
        they do not subscribe to the choreographer directly.
        """
        try:
            target = self._substrate_package_file.parent
            target.mkdir(parents=True, exist_ok=True)
            out = target / "homage-active-artefact.json"
            payload = {
                "package": package.name,
                "content": artefact.content,
                "form": artefact.form,
                "author_tag": artefact.author_tag,
                "weight": artefact.weight,
            }
            tmp = out.with_suffix(out.suffix + ".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(out)
        except Exception:
            log.debug("failed to publish active artefact", exc_info=True)

    def _emit_artefact_metric(
        self,
        package: HomagePackage,
        artefact: SignatureArtefact,
    ) -> None:
        """Increment the Prometheus artefact counter. Best-effort."""
        try:
            from shared.director_observability import emit_homage_signature_artefact
        except Exception:
            return
        try:
            emit_homage_signature_artefact(package.name, artefact.form)
        except Exception:
            log.debug("homage signature artefact metric failed", exc_info=True)

    # ── Phase 11b: substrate-source palette broadcast ───────────────────

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

    # ── Phase 7: voice-register publish ─────────────────────────────────

    def _broadcast_voice_register(self, package: HomagePackage, *, now: float) -> None:
        """Write the active package's voice register to SHM for CPAL.

        Atomic tmp+rename. Co-located with other HOMAGE compositor state
        so a single ``/dev/shm/hapax-compositor/`` wipe resets both sides
        of the wire at once. Best-effort: a failure here is non-fatal —
        CPAL's bridge falls back to the default register when the file
        is missing or stale.

        Payload:
          * ``register``: enum value (``announcing`` / ``conversing`` /
            ``textmode``).
          * ``package``: source package name for observability / replay.
          * ``updated_at``: monotonic clock captured by the caller. The
            bridge uses wall-clock mtime for staleness because monotonic
            clocks aren't comparable across processes, so this is
            diagnostic only.
        """
        try:
            target = self._voice_register_file.parent
            target.mkdir(parents=True, exist_ok=True)
            payload = {
                "register": package.voice_register_default.value,
                "package": package.name,
                "updated_at": now,
            }
            tmp = self._voice_register_file.with_suffix(self._voice_register_file.suffix + ".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(self._voice_register_file)
        except Exception:
            log.debug("failed to publish voice register", exc_info=True)


__all__ = [
    "Choreographer",
    "CoupledPayload",
    "PendingTransition",
    "PlannedTransition",
    "ReconcileResult",
    "Rejection",
    "RejectionReason",
]
