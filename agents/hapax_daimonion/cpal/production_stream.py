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


class ProductionStream:
    """Tier-composed output with interruption support."""

    def __init__(
        self,
        audio_output: object | None = None,
        shm_writer: object | None = None,
    ) -> None:
        self._audio_output = audio_output
        self._shm_writer = shm_writer or self._default_shm_write
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

    def produce_t1(self, *, pcm_data: bytes) -> None:
        self._producing = True
        self._current_tier = CorrectionTier.T1_PRESYNTHESIZED
        self._interrupted = False
        try:
            if self._audio_output is not None:
                self._audio_output.write(pcm_data)
        finally:
            if not self._interrupted:
                self._producing = False
                self._current_tier = None

    def produce_t2(self, *, text: str, pcm_data: bytes | None = None) -> None:
        """Produce T2 lightweight response (echo/rephrase, discourse marker).

        If pcm_data is provided, plays it directly. Otherwise logs the text
        (caller is responsible for synthesis).
        """
        self._producing = True
        self._current_tier = CorrectionTier.T2_LIGHTWEIGHT
        self._interrupted = False
        try:
            if pcm_data is not None and self._audio_output is not None:
                self._audio_output.write(pcm_data)
            log.info("T2 production: %s", text[:50])
        finally:
            if not self._interrupted:
                self._producing = False
                self._current_tier = None

    def mark_t3_start(self) -> None:
        self._producing = True
        self._current_tier = CorrectionTier.T3_FULL_FORMULATION
        self._interrupted = False

    def mark_t3_end(self) -> None:
        self._producing = False
        self._current_tier = None

    def interrupt(self) -> None:
        if self._producing:
            log.info("Production interrupted at %s", self._current_tier)
            self._interrupted = True
        self._producing = False
        self._current_tier = None

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
