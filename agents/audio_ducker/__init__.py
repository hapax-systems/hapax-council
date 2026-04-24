"""Hapax audio ducker — VAD-driven mixer-gain controller.

Phase 4 of the unified audio architecture. Watches operator voice
(Rode) and TTS chain envelopes; writes duck gain to the
`hapax-music-duck` and `hapax-tts-duck` mixer nodes via PipeWire's
control protocol.

Spec: docs/superpowers/specs/2026-04-23-livestream-audio-unified-architecture-design.md
"""

from __future__ import annotations
