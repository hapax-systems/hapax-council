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

    def produce_t1(self, *, pcm_data: bytes, destination_target: str | None = None) -> None:
        """Produce a T1 presynthesised backchannel.

        ``destination_target`` (when supplied) overrides the audio
        output's default sink for this utterance only. CPAL passes the
        resolved sink name (``hapax-livestream`` / ``hapax-private``) from
        ``destination_channel.resolve_target`` so sidechat-origin
        acknowledgements land on the operator-private channel without
        disturbing the livestream subprocess. Passing ``None`` preserves
        legacy behavior — writes flow to the audio output's constructor
        default.
        """
        self._producing = True
        self._current_tier = CorrectionTier.T1_PRESYNTHESIZED
        self._interrupted = False
        _emit_hardm_emphasis("speaking")
        try:
            if self._audio_output is not None:
                if self._on_speaking_changed:
                    self._on_speaking_changed(True)
                self._write_audio(pcm_data, destination_target=destination_target)
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
    ) -> None:
        """Produce T2 lightweight response (echo/rephrase, discourse marker).

        If pcm_data is provided, plays it directly. Otherwise logs the text
        (caller is responsible for synthesis).

        ``destination_target`` behaves identically to :meth:`produce_t1`.
        """
        self._producing = True
        self._current_tier = CorrectionTier.T2_LIGHTWEIGHT
        self._interrupted = False
        _emit_hardm_emphasis("speaking")
        try:
            if pcm_data is not None and self._audio_output is not None:
                self._write_audio(pcm_data, destination_target=destination_target)
            log.info("T2 production: %s", text[:50])
        finally:
            if not self._interrupted:
                self._producing = False
                self._current_tier = None
            _emit_hardm_emphasis("quiescent")

    def _write_audio(self, pcm_data: bytes, *, destination_target: str | None) -> None:
        """Dispatch a PCM write to the audio output, honouring the per-call sink.

        The CPAL audio output is ``PwAudioOutput`` in production, which
        accepts ``target=`` as a keyword argument. Test doubles (MagicMock)
        also accept any kwargs without raising, so passing ``target`` is
        safe universally. If a caller wraps the audio output in a type
        that doesn't accept ``target``, we fall back to a positional call
        so legacy paths keep working.
        """
        audio = self._audio_output
        if audio is None:
            return
        if destination_target is None:
            audio.write(pcm_data)
            return
        try:
            audio.write(pcm_data, target=destination_target)
        except TypeError:
            log.debug(
                "audio output does not accept target=; falling back to default sink",
                exc_info=True,
            )
            audio.write(pcm_data)

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
