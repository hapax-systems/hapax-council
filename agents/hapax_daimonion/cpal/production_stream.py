"""Production stream -- tier-composed, interruptible output.

Receives action decisions from the evaluator and produces signals
at the appropriate tier. Production is interruptible at tier boundaries:
if the operator resumes speaking, production yields immediately.

Stream 3 of 3 in the CPAL temporal architecture.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from agents.hapax_daimonion.cpal.types import CorrectionTier

log = logging.getLogger(__name__)

_DEFAULT_VISUAL_PATH = Path("/dev/shm/hapax-conversation/visual-signal.json")


def _emit_hardm_emphasis(state: str) -> None:
    """Publish the HARDM emphasis signal (task #160).

    Best-effort, fire-and-forget: any error is swallowed so the TTS
    production path never blocks on SHM write failures. Imported lazily
    to avoid the CPAL module pulling in the compositor package at
    import time (test environments without compositor extras still
    work).
    """
    try:
        from agents.studio_compositor.hardm_source import write_emphasis

        write_emphasis(state)
    except Exception:
        log.debug("hardm emphasis emit failed for %s", state, exc_info=True)
    try:
        from shared.director_observability import emit_hardm_emphasis_state

        emit_hardm_emphasis_state(state == "speaking")
    except Exception:
        log.debug("hardm emphasis metric emit failed", exc_info=True)


class ProductionStream:
    """Tier-composed output with interruption support."""

    def __init__(
        self,
        audio_output: object | None = None,
        shm_writer: object | None = None,
        on_speaking_changed: object | None = None,
    ) -> None:
        self._audio_output = audio_output
        self._shm_writer = shm_writer or self._default_shm_write
        self._on_speaking_changed = on_speaking_changed  # callback(bool) for buffer.set_speaking
        self._producing = False
        self._current_tier: CorrectionTier | None = None
        self._interrupted = False

    @property
    def is_producing(self) -> bool:
        return self._producing

    @property
    def current_tier(self) -> CorrectionTier | None:
        return self._current_tier

    @property
    def was_interrupted(self) -> bool:
        return self._interrupted

    def produce_t0(self, *, signal_type: str, intensity: float = 0.5) -> None:
        signal = {
            "type": signal_type,
            "intensity": intensity,
            "timestamp": time.time(),
        }
        self._shm_writer(signal)

    def produce_t1(
        self,
        *,
        pcm_data: bytes,
        destination_target: str | None = None,
        destination_role: str | None = None,
        source: str = "cpal_production_t1",
        text: str = "presynthesized_t1",
    ) -> None:
        """Produce a T1 presynthesised backchannel.

        Calls without a complete semantic route resolve private-or-drop and
        publish voice-output witness before playback. The output constructor
        default is never used as fallback.
        """
        self._producing = True
        self._current_tier = CorrectionTier.T1_PRESYNTHESIZED
        self._interrupted = False
        _emit_hardm_emphasis("speaking")
        try:
            if self._audio_output is not None:
                if self._on_speaking_changed:
                    self._on_speaking_changed(True)
                self._write_audio(
                    pcm_data,
                    destination_target=destination_target,
                    destination_role=destination_role,
                    source=source,
                    text=text,
                )
        finally:
            if self._on_speaking_changed:
                self._on_speaking_changed(False)
            if not self._interrupted:
                self._producing = False
                self._current_tier = None
            _emit_hardm_emphasis("quiescent")

    def produce_t2(
        self,
        *,
        text: str,
        pcm_data: bytes | None = None,
        destination_target: str | None = None,
        destination_role: str | None = None,
    ) -> None:
        """Produce T2 lightweight response (echo/rephrase, discourse marker).

        If pcm_data is provided, plays it directly. Otherwise logs the text
        (caller is responsible for synthesis).

        ``destination_target`` and ``destination_role`` behave identically to
        :meth:`produce_t1`.
        """
        self._producing = True
        self._current_tier = CorrectionTier.T2_LIGHTWEIGHT
        self._interrupted = False
        _emit_hardm_emphasis("speaking")
        try:
            if pcm_data is not None and self._audio_output is not None:
                self._write_audio(
                    pcm_data,
                    destination_target=destination_target,
                    destination_role=destination_role,
                    source="cpal_production_t2",
                    text=text,
                )
            log.info("T2 production: %s", text[:50])
        finally:
            if not self._interrupted:
                self._producing = False
                self._current_tier = None
            _emit_hardm_emphasis("quiescent")

    def _write_audio(
        self,
        pcm_data: bytes,
        *,
        destination_target: str | None,
        destination_role: str | None,
        source: str,
        text: str,
    ) -> None:
        """Dispatch PCM only after a complete semantic route exists.

        If the caller does not pass a route, this method resolves the default
        private-or-drop route and records the decision before playback. Partial
        route metadata is dropped; there is no default-sink fallback.
        """
        audio = self._audio_output
        if audio is None:
            return
        if destination_target is None and destination_role is None:
            resolved = _resolve_default_voice_route(source=source, text=text)
            if resolved is None:
                return
            destination_target, destination_role = resolved
        elif destination_target is None or destination_role is None:
            _record_incomplete_route_drop(
                source=source,
                text=text,
                destination_target=destination_target,
                destination_role=destination_role,
            )
            return
        try:
            audio.write(pcm_data, target=destination_target, media_role=destination_role)
        except TypeError:
            log.warning(
                "audio output does not accept semantic route kwargs; dropping routed audio "
                "instead of using an implicit output route",
                exc_info=True,
            )

    def mark_t3_start(self) -> None:
        self._producing = True
        self._current_tier = CorrectionTier.T3_FULL_FORMULATION
        self._interrupted = False
        _emit_hardm_emphasis("speaking")

    def mark_t3_end(self) -> None:
        self._producing = False
        self._current_tier = None
        _emit_hardm_emphasis("quiescent")

    def interrupt(self) -> None:
        if self._producing:
            log.info("Production interrupted at %s", self._current_tier)
            self._interrupted = True
        self._producing = False
        self._current_tier = None
        _emit_hardm_emphasis("quiescent")

    def yield_to_operator(self) -> None:
        self.interrupt()

    @staticmethod
    def _default_shm_write(signal: dict) -> None:
        try:
            path = _DEFAULT_VISUAL_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(signal), encoding="utf-8")
            tmp.rename(path)
        except Exception:
            pass


def _resolve_default_voice_route(*, source: str, text: str) -> tuple[str, str] | None:
    from agents.hapax_daimonion.cpal.destination_channel import resolve_playback_decision
    from agents.hapax_daimonion.voice_output_witness import (
        record_destination_decision,
        record_drop,
    )

    decision = resolve_playback_decision(None)
    target = decision.target
    role = decision.media_role
    record_destination_decision(
        source=source,
        destination=decision.destination.value,
        route_accepted=decision.allowed,
        reason=decision.reason_code,
        safety_gate=decision.safety_gate,
        target=target,
        media_role=role,
        text=text,
        terminal_state="pending" if decision.allowed else "inhibited",
    )
    if not decision.allowed:
        record_drop(
            reason=decision.reason_code,
            source=source,
            destination=decision.destination.value,
            target=target,
            media_role=role,
            text=text,
            terminal_state="inhibited",
        )
        return None
    if target is None or role is None:
        record_drop(
            reason="semantic_route_incomplete",
            source=source,
            destination=decision.destination.value,
            target=target,
            media_role=role,
            text=text,
            terminal_state="inhibited",
        )
        return None
    return target, role


def _record_incomplete_route_drop(
    *,
    source: str,
    text: str,
    destination_target: str | None,
    destination_role: str | None,
) -> None:
    from agents.hapax_daimonion.voice_output_witness import (
        record_destination_decision,
        record_drop,
    )

    safety_gate = {
        "context_default": "private_or_drop",
        "semantic_route": "incomplete",
    }
    record_destination_decision(
        source=source,
        destination="unknown",
        route_accepted=False,
        reason="semantic_route_incomplete",
        safety_gate=safety_gate,
        target=destination_target,
        media_role=destination_role,
        text=text,
        terminal_state="inhibited",
    )
    record_drop(
        reason="semantic_route_incomplete",
        source=source,
        destination="unknown",
        target=destination_target,
        media_role=destination_role,
        text=text,
        terminal_state="inhibited",
    )
