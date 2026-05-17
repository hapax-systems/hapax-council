"""Dynamic audio-router daemon — Phase B3 of evilpet-s4-dynamic-dual-processor-plan.

5 Hz arbiter loop. Each tick:

1. Assemble state from live SHM surfaces + hardware probes.
2. Run the three-layer policy (`policy.arbitrate`).
3. Resolve sticky-tier semantics (`sticky.StickyTracker.active_tier_at`).
4. Compare against the previously emitted intent; if changed, emit:
   - Evil Pet preset via `evil_pet_presets.recall_preset` (CC burst).
   - S-4 scene via `s4_midi.emit_program_change` (or CC fallback).
5. Sleep until the next 200 ms boundary.

The daemon ships under `systemd/units/hapax-audio-router.service`. It
runs always — when the S-4 is absent, the policy layer's `s4_absent`
clamp downgrades to single-engine routing automatically; the daemon
itself does not need to know about hardware presence beyond the probe
function it uses to populate `HardwareState`.

Spec: docs/superpowers/specs/2026-04-21-evilpet-s4-dynamic-dual-processor-design.md §6
Plan: docs/superpowers/plans/2026-04-21-evilpet-s4-dynamic-dual-processor-plan.md B3
"""

from __future__ import annotations

import json
import logging
import signal
import time
from pathlib import Path
from typing import Any

from agents.audio_router.policy import arbitrate
from agents.audio_router.state import (
    AudioRouterState,
    BroadcasterState,
    HardwareState,
    ProgrammeState,
    RoutingIntent,
    Stance,
    StimmungState,
)
from agents.audio_router.sticky import StickyTracker
from shared import s4_midi
from shared.evil_pet_presets import recall_preset

log = logging.getLogger(__name__)

# Spec §6 — 5 Hz tick = 200 ms period. Faster gives finer ramp
# resolution; slower reduces MIDI bus pressure. 5 Hz is the sweet spot
# per the research doc §7.4 cadence study.
TICK_HZ: float = 5.0
TICK_PERIOD_S: float = 1.0 / TICK_HZ

# Live state-surface paths (verified against running system 2026-04-21).
STIMMUNG_STATE_FILE: Path = Path("/dev/shm/hapax-stimmung/state.json")
EVIL_PET_STATE_FILE: Path = Path("/dev/shm/hapax-compositor/evil-pet-state.json")
VOICE_TIER_OVERRIDE_FILE: Path = Path("/dev/shm/hapax-compositor/voice-tier-override.json")
VOICE_STATE_FILE: Path = Path("/dev/shm/hapax-compositor/voice-state.json")

# Router observability surface. Every tick's (state, intent, timestamp)
# lands here so other components can see what the arbiter decided
# without needing MIDI bus introspection.
ROUTER_STATE_FILE: Path = Path("/dev/shm/hapax-audio-router/state.json")

# Stimmung file's `stance` field uses the same vocabulary as the router
# state — but a missing/malformed file falls back to NOMINAL so the
# router still emits a sensible default rather than blocking on
# perception.
_STANCE_FALLBACK: Stance = "NOMINAL"


def read_stimmung_state(path: Path | None = None) -> StimmungState:
    """Snapshot stimmung from the VLA writer's SHM file.

    Returns the model's defaults when the file is absent or malformed —
    upstream is best-effort, the router must keep emitting.

    ``path`` is late-bound to ``STIMMUNG_STATE_FILE`` so test patches of
    the module-level constant take effect (default-arg evaluation
    captures at definition time and would defeat patching).
    """
    if path is None:
        path = STIMMUNG_STATE_FILE
    try:
        if not path.exists():
            return StimmungState()
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.debug("stimmung read failed — using defaults", exc_info=True)
        return StimmungState()

    stance = data.get("stance") or _STANCE_FALLBACK
    if stance not in {"NOMINAL", "ENGAGED", "SEEKING", "ANT", "FORTRESS", "CONSTRAINED"}:
        stance = _STANCE_FALLBACK

    def _f(key: str, default: float = 0.5) -> float:
        try:
            value = float(data.get(key, default))
            return max(0.0, min(1.0, value))
        except (TypeError, ValueError):
            return default

    return StimmungState(
        stance=stance,
        energy=_f("energy"),
        coherence=_f("coherence"),
        focus=_f("focus"),
        intention_clarity=_f("intention_clarity"),
        presence=_f("presence"),
        exploration_deficit=_f("exploration_deficit", 0.0),
        timestamp=float(data.get("timestamp", 0.0) or 0.0),
    )


def read_voice_active(path: Path | None = None) -> bool:
    """Snapshot operator-VAD state from the daimonion publisher.

    Used to populate `BroadcasterState.operator_voice_active` and to
    drive the StickyTracker silence-window transitions. ``path`` is
    late-bound so module-level patches in tests take effect.
    """
    if path is None:
        path = VOICE_STATE_FILE
    try:
        if not path.exists():
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        return bool(data.get("operator_speech_active", False))
    except Exception:
        log.debug("voice-state read failed — assuming silence", exc_info=True)
        return False


def read_mode_d_active(path: Path | None = None) -> bool:
    """Snapshot Evil Pet Mode-D claimant from the on-demand state file.

    The vinyl_chain writes this when it claims the granular engine.
    Absence ⇒ no claim ⇒ False (router can route voice to T5+).
    Late-bound path for test compatibility.
    """
    if path is None:
        path = EVIL_PET_STATE_FILE
    try:
        if not path.exists():
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        return bool(data.get("mode_d_active", False))
    except Exception:
        log.debug("evil-pet-state read failed — assuming Mode-D inactive", exc_info=True)
        return False


def read_voice_tier_override(
    path: Path | None = None,
) -> tuple[int | None, bool]:
    """Snapshot the operator CLI override file (`hapax-voice-tier`).

    Returns (tier or None, sticky_flag). Both fall back to (None, False)
    when the file is absent — the operator hasn't issued an override.
    Late-bound path for test compatibility.
    """
    if path is None:
        path = VOICE_TIER_OVERRIDE_FILE
    try:
        if not path.exists():
            return None, False
        data = json.loads(path.read_text(encoding="utf-8"))
        tier = data.get("tier")
        sticky = bool(data.get("sticky", False))
        if tier is None:
            return None, sticky
        tier_int = int(tier)
        if not 0 <= tier_int <= 6:
            return None, sticky
        return tier_int, sticky
    except Exception:
        log.debug("voice-tier-override read failed — no override", exc_info=True)
        return None, False


def probe_hardware(
    *,
    evilpet_send_cc: Any | None = None,
    s4_reachable_fn: Any = s4_midi.is_s4_reachable,
) -> HardwareState:
    """Probe hardware presence for the safety-clamp layer.

    `evilpet_send_cc` is the live `MidiOutput` instance — its presence
    means MIDI hardware is open. `s4_reachable_fn` is the S-4 USB-MIDI
    enumeration check (overridable for tests).
    """
    return HardwareState(
        evilpet_midi_reachable=evilpet_send_cc is not None,
        s4_usb_enumerated=s4_reachable_fn(),
        l12_monitor_a_integrity=True,  # operator-set, rarely changes
    )


def assemble_state(
    *,
    programme: ProgrammeState | None = None,
    evilpet_send_cc: Any | None = None,
    s4_reachable_fn: Any = s4_midi.is_s4_reachable,
) -> AudioRouterState:
    """Build an `AudioRouterState` snapshot for one tick.

    `programme` defaults to the empty/no-op programme so the router
    runs even without ProgrammeManager wired in. Live programme
    integration is the next phase (B3 follow-on).
    """
    return AudioRouterState(
        stimmung=read_stimmung_state(),
        programme=programme or ProgrammeState(),
        broadcaster=BroadcasterState(
            operator_voice_active=read_voice_active(),
            mode_d_active=read_mode_d_active(),
        ),
        hardware=probe_hardware(
            evilpet_send_cc=evilpet_send_cc,
            s4_reachable_fn=s4_reachable_fn,
        ),
    )


def emit_intent_change(
    intent: RoutingIntent,
    previous: RoutingIntent | None,
    *,
    evilpet_midi: Any | None,
    s4_midi_port: Any | None,
    s4_program_for_scene_fn: Any | None = None,
) -> bool:
    """Emit the new intent's MIDI to both processors when it differs.

    Returns True iff at least one MIDI emission was attempted (tells
    the metric layer to count an "intent change" event).

    Idempotent: when `intent` matches `previous`, no MIDI is sent. This
    keeps the MIDI bus quiet during stable stimmung windows.
    """
    if previous is not None and _intents_equivalent(intent, previous):
        return False

    emitted = False

    if previous is None or intent.evilpet_preset != previous.evilpet_preset:
        if evilpet_midi is not None:
            try:
                count = recall_preset(intent.evilpet_preset, evilpet_midi)
                log.info("evil-pet preset recalled: %s (%d CCs)", intent.evilpet_preset, count)
                emitted = True
            except Exception:
                log.warning(
                    "evil-pet recall_preset failed: %s", intent.evilpet_preset, exc_info=True
                )
        else:
            log.debug("evil-pet MIDI absent — intent recall deferred")

    if previous is None or intent.s4_vocal_scene != previous.s4_vocal_scene:
        if (
            s4_midi_port is not None
            and intent.s4_vocal_scene is not None
            and s4_program_for_scene_fn is not None
        ):
            try:
                program = s4_program_for_scene_fn(intent.s4_vocal_scene)
                if program is not None:
                    ok = s4_midi.emit_program_change(s4_midi_port, program=program)
                    if ok:
                        log.info(
                            "s-4 vocal scene recalled: %s (program %d)",
                            intent.s4_vocal_scene,
                            program,
                        )
                        emitted = True
            except Exception:
                log.warning("s-4 scene emit failed: %s", intent.s4_vocal_scene, exc_info=True)

    return emitted


def _intents_equivalent(a: RoutingIntent, b: RoutingIntent) -> bool:
    """Two intents are equivalent for emission purposes when their
    MIDI-relevant fields match. Clamp / reroute reason metadata does
    not require re-emission."""
    return (
        a.evilpet_preset == b.evilpet_preset
        and a.s4_vocal_scene == b.s4_vocal_scene
        and a.s4_music_scene == b.s4_music_scene
        and a.tier == b.tier
    )


def write_router_state_snapshot(
    *,
    state: AudioRouterState,
    intent: RoutingIntent,
    now: float,
    path: Path | None = None,
) -> None:
    """Write the router's current (state, intent, timestamp) to SHM.

    Fail-closed: any error is logged and swallowed so a disk hiccup
    cannot take down the audio router daemon.

    ``path`` is late-bound to ``ROUTER_STATE_FILE`` so test patches of
    the module-level constant take effect.
    """
    if path is None:
        path = ROUTER_STATE_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "generated_at": now,
            "state": state.model_dump(mode="json"),
            "intent": intent.model_dump(mode="json"),
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(snapshot))
        tmp.replace(path)
    except Exception:
        log.debug("router state snapshot write failed", exc_info=True)


class DynamicRouter:
    """The 5 Hz arbiter daemon.

    Wires the policy layer to live SHM state + MIDI emission. Holds
    the `StickyTracker` instance and the previous-emitted-intent
    cache so emit_intent_change can no-op on stable windows.
    """

    def __init__(
        self,
        *,
        evilpet_midi: Any | None = None,
        s4_midi_port: Any | None = None,
        s4_program_for_scene_fn: Any | None = None,
        s4_reachable_fn: Any = s4_midi.is_s4_reachable,
        s4_reachable_probe_interval_s: float = 30.0,
        tick_period_s: float = TICK_PERIOD_S,
    ) -> None:
        self._evilpet_midi = evilpet_midi
        self._s4_midi_port = s4_midi_port
        self._s4_program_for_scene_fn = s4_program_for_scene_fn
        self._s4_reachable_fn = s4_reachable_fn
        self._s4_reachable_probe_interval_s = max(0.0, s4_reachable_probe_interval_s)
        self._last_s4_reachable_probe_monotonic: float | None = None
        self._last_s4_reachable: bool = s4_midi_port is not None
        self._tick_period_s = tick_period_s
        self._sticky = StickyTracker()
        self._last_intent: RoutingIntent | None = None
        self._last_voice_active: bool = False
        self._stop = False

    def stop(self) -> None:
        """Signal the run loop to exit on the next tick boundary."""
        self._stop = True

    def _s4_reachable(self, now: float) -> bool:
        """Return S-4 reachability without probing ALSA on every tick.

        ``mido.get_output_names()`` opens ALSA sequencer state under the
        hood on Linux. Calling it at the router's 5 Hz cadence can leave a
        trail of RtMidi clients and eventually make ``snd_seq_open`` fail.
        The router only needs a coarse hardware-presence signal for safety
        clamps, so the live daemon uses a slow cached probe while still
        allowing hot-plug detection after the interval elapses.
        """

        if self._s4_midi_port is not None:
            self._last_s4_reachable = True
            return True

        last = self._last_s4_reachable_probe_monotonic
        if (
            last is not None
            and self._s4_reachable_probe_interval_s > 0
            and now - last < self._s4_reachable_probe_interval_s
        ):
            return self._last_s4_reachable

        self._last_s4_reachable_probe_monotonic = now
        try:
            self._last_s4_reachable = bool(self._s4_reachable_fn())
        except Exception:
            log.debug("S-4 reachability probe failed", exc_info=True)
            self._last_s4_reachable = False

        try:
            from shared.s4_audio_witness import probe_and_publish

            probe_and_publish()
        except Exception:
            log.debug("S-4 audio witness publish failed", exc_info=True)

        return self._last_s4_reachable

    def tick(self, *, now: float | None = None) -> RoutingIntent:
        """One arbiter cycle. Returns the (possibly emitted) intent.

        Public for tests + cron-style callers that want a single
        decision without spawning the loop thread.
        """
        if now is None:
            now = time.monotonic()

        state = assemble_state(
            evilpet_send_cc=self._evilpet_midi,
            s4_reachable_fn=lambda: self._s4_reachable(now),
        )
        intent = arbitrate(state)

        # Sticky tracker: VAD transitions drive the silence window.
        voice_active = state.broadcaster.operator_voice_active
        if voice_active and not self._last_voice_active:
            self._sticky.on_tts_emission(intent.tier, now)
        elif not voice_active and self._last_voice_active:
            self._sticky.on_tts_silence_start(now)
        self._last_voice_active = voice_active

        # Operator override flows through the StickyTracker (CLI writes
        # the override file; we replay it into the tracker each tick so
        # the tracker stays the single source of truth).
        override_tier, override_sticky = read_voice_tier_override()
        if override_tier is not None and not self._sticky.is_operator_overridden():
            self._sticky.operator_override(override_tier, now, sticky=override_sticky)
        if override_tier is None and self._sticky.is_operator_overridden():
            self._sticky.operator_release(now)

        # Sticky-tier resolution: when the tracker holds a non-None tier,
        # it takes precedence over the policy result. The intent's other
        # fields (topology, scene) come from the policy as normal.
        sticky_tier = self._sticky.active_tier_at(now)
        if sticky_tier is not None and sticky_tier != intent.tier:
            from agents.audio_router.policy import _TIER_TO_PRESET

            intent = intent.model_copy(
                update={
                    "tier": sticky_tier,
                    "evilpet_preset": _TIER_TO_PRESET.get(sticky_tier, intent.evilpet_preset),
                }
            )

        emit_intent_change(
            intent,
            self._last_intent,
            evilpet_midi=self._evilpet_midi,
            s4_midi_port=self._s4_midi_port,
            s4_program_for_scene_fn=self._s4_program_for_scene_fn,
        )
        self._last_intent = intent

        # Observability: publish the full (state, intent) snapshot to SHM
        # so other components can read what the arbiter decided without
        # MIDI bus introspection. Uses wall-clock (time.time) rather than
        # the tick's monotonic ``now`` so downstream consumers can compute
        # staleness against their own clock.
        write_router_state_snapshot(state=state, intent=intent, now=time.time())

        return intent

    def run(self) -> None:
        """Block forever, ticking every `tick_period_s` seconds."""
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        signal.signal(signal.SIGINT, lambda *_: self.stop())
        log.info("audio-router daemon starting (tick=%.2fs)", self._tick_period_s)
        next_deadline = time.monotonic() + self._tick_period_s
        while not self._stop:
            tick_start = time.monotonic()
            try:
                self.tick(now=tick_start)
            except Exception:
                log.exception("router tick raised — continuing")
            now = time.monotonic()
            sleep_s = max(0.0, next_deadline - now)
            time.sleep(sleep_s)
            next_deadline += self._tick_period_s
            # If we fell behind by more than one tick, skip ahead so the
            # next deadline is in the future (avoids unbounded catch-up
            # bursts after a long pause / debugger break).
            if next_deadline < now:
                next_deadline = now + self._tick_period_s
        log.info("audio-router daemon stopped")


def _s4_program_lookup(scene_name: str) -> int | None:
    """Resolve scene name to S-4 program number from the scene library."""
    try:
        from shared.s4_scenes import get_program_number

        return get_program_number(scene_name)
    except Exception:
        log.debug("s4 program lookup failed for %s", scene_name, exc_info=True)
        return None


def main() -> int:
    """Entry point for `python -m agents.audio_router.dynamic_router`."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Open Evil Pet MIDI lane via the existing daimonion wrapper —
    # falls back to no-op when the port is missing (router still ticks
    # and policy layer's `evilpet_midi_unreachable` clamp engages).
    try:
        from agents.hapax_daimonion.midi_output import MidiOutput

        evilpet = MidiOutput("MIDI Dispatch")
    except Exception:
        log.warning("evil-pet MidiOutput init failed — router will run without it")
        evilpet = None

    s4_port = s4_midi.find_s4_midi_output()
    if s4_port is None:
        log.warning("S-4 MIDI port not found — router will downgrade to single-engine")

    router = DynamicRouter(
        evilpet_midi=evilpet,
        s4_midi_port=s4_port,
        s4_program_for_scene_fn=_s4_program_lookup,
    )
    try:
        router.run()
    finally:
        if evilpet is not None:
            close = getattr(evilpet, "close", None)
            if callable(close):
                close()
        s4_midi.close_output(s4_port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
