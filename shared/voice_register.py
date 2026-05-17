"""VoiceRegister — CPAL-readable tonal mode for the daimonion.

HOMAGE spec §4.8. The persona document already frames voice as register
selection ("Adaptation is register selection, not personality"); this
module formalises the mechanism so a HomagePackage can set it, and CPAL
can read it, without either side having to re-litigate the abstraction.

Three values cover the spread:

- ``ANNOUNCING`` — broadcast register; no turn closes. Default under
  ``stream_mode == public_research``.
- ``CONVERSING`` — turn-taking with repair and grounding. Default when
  the operator is in active conversation.
- ``TEXTMODE`` — clipped, IRC-style, bridge-short delivery. Set by the
  BitchX package and any other homage whose grammar is textmode-lineage.

Reader + writer live in ``agents.hapax_daimonion.voice_register_reader``
(Phase 7 of the HOMAGE epic); this module holds only the enum so every
side of the wire agrees on the vocabulary without importing daimonion.

Spec: ``docs/superpowers/specs/2026-04-18-homage-framework-design.md``.
"""

from __future__ import annotations

from enum import StrEnum


class VoiceRegister(StrEnum):
    """Tonal mode read by CPAL prompt construction + TTS pacing."""

    ANNOUNCING = "announcing"
    CONVERSING = "conversing"
    TEXTMODE = "textmode"
    AMBIENT = "ambient"


DEFAULT_REGISTER: VoiceRegister = VoiceRegister.CONVERSING

DENSITY_SPEED_MAP: dict[str, float] = {
    "presenting": 0.85,
    "focused": 0.92,
    "ambient": 1.0,
    "receptive": 1.05,
}
"""Fallback when no HomagePackage has written a preference and
``stream_mode`` does not force ``ANNOUNCING``."""


__all__ = ["VoiceRegister", "DEFAULT_REGISTER"]
