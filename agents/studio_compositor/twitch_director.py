"""TwitchDirector — deterministic sub-5s compositional modulations.

Phase 5 of the volitional-director epic (PR #1017, spec §3.4).

Under the grounding-exhaustive axiom, the twitch layer is *deterministic
code outsourced by a grounding move* — the narrative director (`DirectorLoop`)
declares a stance and a perceptual field; the twitch layer's rules
modulate small compositional parameters within that stance's frame. It
does NOT make independent grounding decisions; it implements the
narrative director's grounded declarations at a faster cadence.

Rules (all deterministic, no LLM):
- MIDI transport PLAYING + beat_position increment → album-overlay alpha pulse.
- desk_activity == "drumming" (high desk_energy) → `fx.family.audio-reactive` bias.
- detected_action == "away" for >30s → `overlay.dim.all-chrome`.
- ir_hand_zone == "turntable" → album-overlay alpha pulse.
- stream_health.dropped_frames_pct > 0.05 → `overlay.dim.all-chrome` + diagnostic flash.

Stance-gated (read from /dev/shm/hapax-director/narrative-state.json):
- CAUTIOUS or CRITICAL stance → disabled (no twitch emissions).
- SEEKING stance → rate 3s.
- NOMINAL stance (default) → rate 4s.

Emissions go via `agents.studio_compositor.compositional_consumer.dispatch`
against `CompositionalImpingement` equivalents — same code path as
narrative director's impingements. No separate pipeline.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from agents.studio_compositor.compositional_consumer import (
    RecruitmentRecord,
    dispatch,
    recent_recruitment_age_s,
)
from shared.perceptual_field import build_perceptual_field
from shared.stimmung import Stance

log = logging.getLogger(__name__)

_NARRATIVE_STATE = Path("/dev/shm/hapax-director/narrative-state.json")

# Cadence by stance. Per sim-1 audit (2026-04-18), CAUTIOUS was the
# majority stance, and the prior design disabled twitch there → the
# livestream had minute-long stretches with no meta-structural movement.
# Operator directive: "no 'do nothing interesting' tick is acceptable."
# Non-nominal stances now run twitch at a slower cadence (never None),
# preserving the original intent that compositional pressure should be
# low when the system is stressed, without falling to zero.
_STANCE_CADENCE: dict[str, float | None] = {
    Stance.NOMINAL.value: 4.0,
    Stance.SEEKING.value: 3.0,
    Stance.CAUTIOUS.value: 10.0,
    Stance.DEGRADED.value: 20.0,
    Stance.CRITICAL.value: 30.0,
}

# Debounce: minimum interval between identical emissions per family.
# Prevents a sustained signal from spamming the pipeline.
_MIN_DWELL_S: dict[str, float] = {
    "overlay.foreground.album": 2.0,
    "overlay.dim.all-chrome": 5.0,
    "preset.bias.audio-reactive": 15.0,
}


def _read_narrative_state() -> dict:
    """Return narrative-state JSON as a dict, or {} on any failure.

    Validates the JSON root is a mapping. The TwitchDirector loop calls
    ``ns.get(\"stance\")`` (line 130) and
    ``_read_narrative_state().get(\"condition_id\")`` (line 293) directly
    on the returned value; a writer producing valid JSON whose root is
    null, a list, a string, or a number previously raised AttributeError
    out of the twitch loop, killing the 3-4s compositional cadence.
    Same corruption-class as #2627, #2631, #2632 (already merged).
    """
    try:
        if _NARRATIVE_STATE.exists():
            data = json.loads(_NARRATIVE_STATE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            log.debug(
                "narrative-state root is %s, expected mapping",
                type(data).__name__,
            )
    except Exception:
        log.debug("narrative-state read failed", exc_info=True)
    return {}


_SIGNIFICANT_MAGNITUDE = 0.35  # signals above this count toward "pressure"
_PRESSURE_FORCE_THRESHOLD = 6  # N active signals → force a compositional move
_IDLE_VARIATION_CADENCE_S = 12.0  # gentle overlay emphasis when nothing else fires
_CHAT_RECENT_PATH = Path("/dev/shm/hapax-chat/recent.jsonl")


class TwitchDirector:
    """Run deterministic compositional modulations on a short cadence."""

    def __init__(self, *, sleep_fn=time.sleep):
        self._sleep = sleep_fn
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_beat: float | None = None
        self._away_since: float | None = None
        self._last_hand_zone: str | None = None
        self._last_idle_emission: float = 0.0
        self._last_chat_count: int = 0
        from agents.studio_compositor.color_resonance import ColorResonance

        self._color_resonance = ColorResonance()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="twitch-director", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            try:
                cadence = self._cadence_or_none()
                if cadence is None:
                    # Stance-gated off — idle until stance changes.
                    self._sleep(5.0)
                    continue
                self.tick_once()
                self._sleep(cadence)
            except Exception:  # pragma: no cover — defensive
                log.warning("twitch tick crashed", exc_info=True)
                self._sleep(4.0)

    def _cadence_or_none(self) -> float | None:
        ns = _read_narrative_state()
        stance = str(ns.get("stance") or Stance.NOMINAL.value).lower()
        return _STANCE_CADENCE.get(stance, 4.0)

    def tick_once(self) -> list[str]:
        """Run one twitch tick; return the list of capability-names dispatched."""
        field = build_perceptual_field()
        dispatched: list[str] = []

        # Phase F2 — color-resonance publisher. Smooth the album cover's
        # color temperature into /dev/shm/hapax-compositor/color-resonance.json
        # so chrome readers can tint toward warmth when the record is
        # warm-toned and cool when it's cool-toned.
        try:
            from agents.studio_compositor.color_resonance import publish

            publish(self._color_resonance.tick())
        except Exception:
            log.debug("color resonance publish failed", exc_info=True)

        # MIDI-sync album pulse.
        # #127 SPLATTRIBUTION: gate on derived ``vinyl_playing`` (transport
        # PLAYING AND beat_position_rate > 0) so a stale transport_state
        # with a silently-stopped clock source doesn't emit album pulses
        # against silence.
        if field.vinyl_playing:
            beat = field.audio.midi.beat_position
            if beat is not None and beat != self._last_beat:
                self._last_beat = beat
                if self._emit_if_cool("overlay.foreground.album"):
                    dispatched.append("overlay.foreground.album")

        # Turntable hand-zone → album pulse
        if field.ir.ir_hand_zone == "turntable":
            if self._emit_if_cool("overlay.foreground.album"):
                dispatched.append("overlay.foreground.album")

        # Drumming with high energy → audio-reactive bias
        desk_activity = field.audio.contact_mic.desk_activity
        desk_energy = field.audio.contact_mic.desk_energy or 0.0
        if desk_activity == "drumming" and desk_energy > 0.25:
            if self._emit_if_cool("preset.bias.audio-reactive", family="fx.family.audio-reactive"):
                dispatched.append("fx.family.audio-reactive")

        # Away for >30s → dim chrome
        if field.visual.detected_action == "away":
            if self._away_since is None:
                self._away_since = time.time()
            elif time.time() - self._away_since > 30.0:
                if self._emit_if_cool("overlay.dim.all-chrome"):
                    dispatched.append("overlay.dim.all-chrome")
        else:
            self._away_since = None

        # Stream degraded → dim chrome + visibility on the issue
        dropped = field.stream_health.dropped_frames_pct
        if dropped is not None and dropped > 0.05:
            if self._emit_if_cool("overlay.dim.all-chrome"):
                dispatched.append("overlay.dim.all-chrome")

        # Epic 2 Phase E — hand-zone cycling: emit a camera.hero-biased
        # preset move once per hand-zone change. Overhead hand-zone is
        # the authoritative grounding signal for what the operator is
        # physically doing.
        hand_zone = field.ir.ir_hand_zone
        if hand_zone and hand_zone != self._last_hand_zone:
            self._last_hand_zone = hand_zone
            if self._emit_if_cool(
                f"preset.bias.hand-zone-{hand_zone}",
                family="fx.family.audio-reactive",
            ):
                dispatched.append(f"fx.family.audio-reactive(zone:{hand_zone})")

        # Epic 2 Phase E — chat-arrival pulse: on new chat message,
        # foreground the captions overlay regardless of other state so
        # viewers feel their messages land.
        try:
            if _CHAT_RECENT_PATH.exists():
                lines = _CHAT_RECENT_PATH.read_text(encoding="utf-8").strip().splitlines()
                count = len(lines)
                if count > self._last_chat_count:
                    self._last_chat_count = count
                    if self._emit_if_cool(
                        "overlay.foreground.captions",
                        family="overlay.foreground.captions",
                    ):
                        dispatched.append("overlay.foreground.captions(chat)")
        except Exception:
            log.debug("chat-recent pulse failed", exc_info=True)

        # Epic 2 Phase E — pressure forcing: if many signals are active
        # simultaneously, force a compositional impingement so the
        # narrative director doesn't stall the stream visually.
        active = self._count_active_signals(field)
        if active >= _PRESSURE_FORCE_THRESHOLD:
            if self._emit_if_cool(
                "preset.bias.pressure-discharge",
                family="fx.family.audio-reactive",
            ):
                dispatched.append("fx.family.audio-reactive(pressure)")

        # Epic 2 Phase E — idle variation: if nothing else fired, emit a
        # gentle overlay emphasis every ~12s so the surface never looks
        # static. Not random: alternates foreground/dim targets.
        now = time.time()
        if not dispatched and now - self._last_idle_emission > _IDLE_VARIATION_CADENCE_S:
            self._last_idle_emission = now
            target = "overlay.foreground.grounding-ticker"
            if self._emit_if_cool(target, family=target):
                dispatched.append(target)

        return dispatched

    def _count_active_signals(self, field) -> int:
        active = 0
        try:
            audio = field.audio.contact_mic.desk_energy or 0.0
            if audio >= _SIGNIFICANT_MAGNITUDE:
                active += 1
            # #127 SPLATTRIBUTION: pressure counter also tracks real
            # playback, not just a transport flag that may be stale.
            if field.vinyl_playing:
                active += 1
            if field.ir.ir_hand_zone not in (None, ""):
                active += 1
            if field.ir.ir_hand_activity and field.ir.ir_hand_activity >= _SIGNIFICANT_MAGNITUDE:
                active += 1
            if field.chat.recent_message_count > 0:
                active += 1
            if field.album.confidence and field.album.confidence >= 0.5:
                active += 1
            if field.visual.detected_action and field.visual.detected_action != "idle":
                active += 1
            if field.presence.state == "PRESENT":
                active += 1
        except Exception:
            log.debug("pressure signal count failed", exc_info=True)
        return active

    def _emit_if_cool(self, signature: str, *, family: str | None = None) -> bool:
        """Dispatch if the family's minimum-dwell has elapsed.

        `signature` is the debounce key. `family` is the capability name
        to dispatch (defaults to `signature` for overlay.* cases where
        they're identical).
        """
        min_dwell = _MIN_DWELL_S.get(signature, 1.0)
        if signature == "preset.bias.audio-reactive":
            family_for_dispatch = family or "fx.family.audio-reactive"
            age = recent_recruitment_age_s("preset.bias")
        else:
            family_for_dispatch = family or signature
            # Overlay emphasis shares one family cooldown bucket
            age = recent_recruitment_age_s("overlay.emphasis")
        if age is not None and age < min_dwell:
            return False
        rec = RecruitmentRecord(name=family_for_dispatch, ttl_s=8.0, score=0.5)
        dispatch(rec)
        # Record Prometheus metric (best-effort)
        try:
            from shared.director_observability import emit_twitch_move

            # Derive the intent-family bucket name for the metric label.
            fam = "preset.bias" if signature.startswith("preset.bias") else "overlay.emphasis"
            cond = _read_narrative_state().get("condition_id") or "none"
            emit_twitch_move(intent_family=fam, condition_id=cond)
        except Exception:
            log.debug("twitch observability emit failed", exc_info=True)
        return True


__all__ = ["TwitchDirector"]
