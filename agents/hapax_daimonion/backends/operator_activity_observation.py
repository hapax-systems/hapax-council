"""Perception-state → OperatorActivityEngine signal adapter.

Phase 6a-i.B partial wire-in for the activity-claim engine that #1375
shipped as engine math + signal contract without a live consumer.

Activity signals live in the daimonion-side ``perception-state.json``
(written by ``agents.hapax_daimonion._perception_state_writer``):

- ``keyboard_active``: bool, derived from evdev raw HID input
- ``desk_activity``: enum, contact-mic DSP gesture classifier
  (``idle`` / ``typing`` / ``tapping`` / ``drumming`` / ``active``)
- ``active_window_class``: str, current Hyprland-focused window class
- ``desktop_active``: bool, separate Hyprland focus-event flag
- ``desk_energy``: float, contact-mic RMS energy

This adapter exposes a ``operator_activity_observation`` builder that
takes any ``_PerceptionStateSource`` and returns a single-tick
observation dict for ``OperatorActivityEngine.contribute()``.

Wired so far (live perception-state.json signals):
- Part 1 (#1389): ``keyboard_active``
- Part 2 (#1391): ``desk_active``
- Part 3 (#1410): ``desktop_focus_changed_recent``

Scaffolded (this PR — accessors return ``None`` until upstream
publishers exist):
- Part 4: ``midi_clock_active``. Source data lives in
  ``MidiClockBackend`` (in-process daimonion state). Cross-process
  publication to ``/dev/shm/hapax-daimonion/midi-clock.json`` lands
  in a follow-up PR.
- Part 5: ``watch_movement``. Source data flows through
  ``hapax-watch-receiver`` HTTP endpoint to a per-tick state file;
  bridge accessor needs a thin reader for that file.

The all-None scaffolding pattern matches alpha's ``LogosStimmungBridge``
for the mood-arousal cluster (#1392 + follow-ups) — keeps the protocol
surface stable so downstream consumers can rely on the dict shape,
while signal contribution lights up incrementally as upstream
publishers ship.

Reference doc: ``docs/superpowers/research/2026-04-23-bayesian-claims-research.md``
§Phase 6a + the OperatorActivityEngine module docstring.
"""

from __future__ import annotations

from typing import Protocol


class _PerceptionStateSource(Protocol):
    """Anything exposing the activity signal accessors.

    The bridge in ``logos/api/app.py`` (``LogosPerceptionStateBridge``)
    matches this protocol; tests use a stub object with the same shape.
    Returning ``None`` from any accessor signals "perception state
    unavailable for this signal" — the Bayesian engine then skips that
    signal for the tick (no contribution rather than negative evidence;
    positional ``None`` semantics are documented in
    ``shared/claim.py::ClaimEngine.tick``).
    """

    def keyboard_active(self) -> bool | None: ...
    def desk_active(self) -> bool | None: ...
    def desktop_focus_changed_recent(self) -> bool | None: ...
    def midi_clock_active(self) -> bool | None: ...
    def watch_movement(self) -> bool | None: ...


def operator_activity_observation(
    source: _PerceptionStateSource,
) -> dict[str, bool | None]:
    """Build a single-tick observation dict for OperatorActivityEngine.

    Emits all 5 activity signals. Three are wired to the
    perception-state.json bridge; two are scaffolded with the bridge
    returning ``None`` until upstream cross-process publishers land.
    Each signal's contract is registered in
    ``shared/lr_registry.yaml::operator_activity_signals``:

    - ``keyboard_active``: WIRED. Bidirectional, idle keyboard → real
      negative evidence (no recent keystrokes in the perception window).
    - ``desk_active``: WIRED. Bidirectional, idle contact mic → mild
      negative evidence (LR weights 0.75/0.10 — operator may be reading
      without typing or tapping, but sustained silence is informative).
    - ``desktop_focus_changed_recent``: WIRED. Bidirectional, focus
      change in the perception window → positive evidence of active
      engagement (LR weights 0.65/0.15 — workspace switching is a
      strong cue but not exhaustive of activity).
    - ``midi_clock_active``: SCAFFOLDED. Bridge returns None until
      ``MidiClockBackend`` publishes BPM to a cross-process state file
      (follow-up PR).
    - ``watch_movement``: SCAFFOLDED. Bridge returns None until the
      ``hapax-watch-receiver`` per-tick state file reader lands
      (follow-up PR).

    Designed for callers like::

        from agents.hapax_daimonion.operator_activity_engine import OperatorActivityEngine
        from agents.hapax_daimonion.backends.operator_activity_observation import (
            operator_activity_observation,
        )

        engine = OperatorActivityEngine()
        engine.contribute(operator_activity_observation(perception_bridge))
    """
    return {
        "keyboard_active": source.keyboard_active(),
        "desk_active": source.desk_active(),
        "desktop_focus_changed_recent": source.desktop_focus_changed_recent(),
        "midi_clock_active": source.midi_clock_active(),
        "watch_movement": source.watch_movement(),
    }


__all__ = ["operator_activity_observation"]
