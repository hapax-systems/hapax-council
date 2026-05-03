"""shared/micromove_cycle.py — 8-slot micromove cycle substrate (cc-task u4 Phase 0).

Audit underutilization U4: the compositor declared an 8-slot micromove
cycle (zoom-in / pan-left / blur / etc.) that has been dormant. Audit
U4 wants the consumer wired so the cycle actually advances on tick.

This Phase 0 ships the **substrate**: the 8 canonical micromove slots,
a deterministic cycle that advances on each ``tick()`` call, and the
per-slot ``MicromoveAction`` descriptor downstream consumers will read
to fire the visible parameter change. Phase 1 wires the actual
consumers (compositor camera-tile transform, shader uniform deltas,
Prometheus counter) + the livestream evidence sample.

The 8 slots span a complete spatial+temporal+tonal regime so the
cycle visibly shifts every N ticks without repeating semantics:

  slot 0: zoom-in       — tighten the visual field on its center
  slot 1: zoom-out      — relax the visual field outward
  slot 2: pan-left      — drift attention left
  slot 3: pan-right     — drift attention right
  slot 4: blur          — soften focus
  slot 5: sharpen       — crispen edges
  slot 6: warm-tint     — palette tilt warm
  slot 7: cool-tint     — palette tilt cool

The cycle is **stateful** but **process-local** by default. A
production deployment can persist the slot index in
``/dev/shm/hapax-compositor/micromove-cycle.json`` so a compositor
restart resumes mid-cycle (Phase 1 wiring decision).

Phase 1 (separate cc-tasks):
  * ``u4-micromove-consumer-wiring`` — connect ``MicromoveCycle.tick()``
    to the compositor's main loop tick path; each slot's hint applied
    to a real visible parameter (compositor tile transform, shader
    uniform target, palette bias)
  * ``u4-prometheus-counter`` — wire
    ``hapax_micromove_advance_total{slot=...}`` increment in the
    consumer
  * ``u4-livestream-evidence`` — operator-side 60s screenshot grid
    showing visible motion shifts every N ticks
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Literal

MicromoveAxis = Literal["spatial", "tonal", "focal"]


@dataclass(frozen=True)
class MicromoveAction:
    """Per-slot action descriptor consumers interpret at their own scale.

    Phase 0 carries the slot's name + axis + description + a free-form
    ``hint`` dict. Hint keys mirror the conventions used in
    ``shared/director_semantic_verbs.py`` so consumers wired for both
    can share interpretation logic (``shader_uniform_target``,
    ``compositor_transform``, ``palette_bias``).
    """

    slot: int
    name: str
    axis: MicromoveAxis
    description: str
    hint: dict[str, object] = field(default_factory=dict)


MICROMOVE_SLOTS: tuple[MicromoveAction, ...] = (
    MicromoveAction(
        slot=0,
        name="zoom-in",
        axis="spatial",
        description="Tighten the visual field on its center — invite intimate attention",
        hint={
            "compositor_transform": {"scale": 1.08, "anchor": "center"},
            "duration_ticks": 4,
        },
    ),
    MicromoveAction(
        slot=1,
        name="zoom-out",
        axis="spatial",
        description="Relax the visual field outward — restore wide perspective",
        hint={
            "compositor_transform": {"scale": 0.92, "anchor": "center"},
            "duration_ticks": 4,
        },
    ),
    MicromoveAction(
        slot=2,
        name="pan-left",
        axis="spatial",
        description="Drift attention leftward across the frame",
        hint={
            "compositor_transform": {"translate_x": -0.06, "translate_y": 0.0},
            "duration_ticks": 4,
        },
    ),
    MicromoveAction(
        slot=3,
        name="pan-right",
        axis="spatial",
        description="Drift attention rightward across the frame",
        hint={
            "compositor_transform": {"translate_x": +0.06, "translate_y": 0.0},
            "duration_ticks": 4,
        },
    ),
    MicromoveAction(
        slot=4,
        name="blur",
        axis="focal",
        description="Soften focus — render the field as remembered, not seen",
        hint={
            "shader_uniform_target": {"diffusion": "+0.15"},
            "duration_ticks": 5,
        },
    ),
    MicromoveAction(
        slot=5,
        name="sharpen",
        axis="focal",
        description="Crispen edges — render the field as just-noticed",
        hint={
            "shader_uniform_target": {"coherence": "+0.20"},
            "duration_ticks": 5,
        },
    ),
    MicromoveAction(
        slot=6,
        name="warm-tint",
        axis="tonal",
        description="Tilt palette warm — Gruvbox-direction pulse",
        hint={
            "palette_bias": "warm",
            "duration_ticks": 6,
        },
    ),
    MicromoveAction(
        slot=7,
        name="cool-tint",
        axis="tonal",
        description="Tilt palette cool — Solarized-direction pulse",
        hint={
            "palette_bias": "cool",
            "duration_ticks": 6,
        },
    ),
)

CYCLE_LENGTH = len(MICROMOVE_SLOTS)


@dataclass
class MicromoveCycle:
    """Stateful 8-slot cycle that advances on each ``tick()`` call.

    Process-local by default. A deployment that wants restart-survivability
    can persist the slot index across restarts (Phase 1 wiring decision).

    Thread-safe: tick / current_slot / current_action are all guarded by
    an internal lock so a director-loop tick + a metrics scrape can't
    race on the slot index.
    """

    _slot_index: int = 0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def current_slot(self) -> int:
        with self._lock:
            return self._slot_index

    def current_action(self) -> MicromoveAction:
        with self._lock:
            return MICROMOVE_SLOTS[self._slot_index]

    def tick(self) -> MicromoveAction:
        """Advance to the next slot and return the new current action."""
        with self._lock:
            self._slot_index = (self._slot_index + 1) % CYCLE_LENGTH
            return MICROMOVE_SLOTS[self._slot_index]

    def reset(self) -> None:
        with self._lock:
            self._slot_index = 0


def slot_by_name(name: str) -> MicromoveAction | None:
    """Look up a slot by its short name (zoom-in, pan-left, etc.)."""
    for action in MICROMOVE_SLOTS:
        if action.name == name:
            return action
    return None
