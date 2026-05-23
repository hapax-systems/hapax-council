"""Phenomenal context renderer — faithful rendering of temporal bands + self-band.

Not a compressor. The upstream structures (temporal bands, apperception cascade,
stimmung) already self-compress based on environmental state. This renderer
presents what survived at the available fidelity, preserving directional force.

Design principles:
1. Render what's there — upstream already decided what matters
2. Orient, don't inform — the LLM should BE in a situation, not read ABOUT one
3. Progressive fidelity — truncation at any point leaves coherent orientation
4. Preserve coupling — don't decompose situations into independent facts
5. Stimmung first when non-nominal — global prior shapes everything
6. Never fabricate — absence is signal (filter "unknown", don't render it)
7. One output, tiers consume what fits

The output is ordered by perceptual priority:
  1. Stimmung (non-nominal only) — global attunement
  2. Situation coupling — operator + system + environment in one breath
  3. Temporal impression + horizon — present and near-future
  4. Surprise/deviation — prediction errors (the interesting part)
  5. Temporal depth — retention, protention details
  6. Self-state — apperception when non-trivial

LOCAL naturally gets lines 1-3. FAST gets through 4-5. STRONG/CAPABLE get all.

Epistemic status: NOVEL DESIGN. The term "phenomenal context" does not exist in
the literature. This module uses vocabulary from phenomenology (Husserl, Heidegger,
Merleau-Ponty), ecological psychology (Gibson), and active inference (Friston) to
structure an orientation layer for voice LLMs. It is inspired by these frameworks,
not an implementation of them. The construct is unvalidated — see the epistemic
audit (EPISTEMIC-AUDIT-conversational-continuity.md, HOPE tier) and the Bayesian
validation schedule (measure 4.3) for the planned ablation study.

Module structure:
  phenomenal_context.py — this file, orchestration + public API
  phenomenal_layers.py  — six layer renderers
  phenomenal_parsing.py — XML parsing + JSON readers
"""

from __future__ import annotations

import logging
from pathlib import Path

from agents.hapax_daimonion.phenomenal_layers import (
    render_audio_context,
    render_impression,
    render_self_state,
    render_situation,
    render_stimmung,
    render_surprise,
    render_temporal_depth,
)
from agents.hapax_daimonion.phenomenal_parsing import (
    parse_temporal_snapshot,
    read_json,
)
from shared.aperture_state import read_aperture_state_block
from shared.prosody import read_prosody_block

log = logging.getLogger(__name__)

_TEMPORAL_PATH = Path("/dev/shm/hapax-temporal/bands.json")
_APPERCEPTION_PATH = Path("/dev/shm/hapax-apperception/self-band.json")
_STIMMUNG_PATH = Path("/dev/shm/hapax-stimmung/state.json")
_PERCEPTION_STATE_PATH = Path.home() / ".cache" / "hapax-daimonion" / "perception-state.json"
_AUDIO_PERCEPTION_PATH = Path("/dev/shm/hapax-perception/audio.json")
_ACTIVE_SEGMENT_PATH = Path("/dev/shm/hapax-compositor/active-segment.json")

# Re-exports for backward compatibility with tests
_read_json = read_json
_parse_temporal_snapshot = parse_temporal_snapshot
_render_stimmung = render_stimmung
_render_situation = render_situation
_render_audio_context = render_audio_context
_render_impression = render_impression
_render_surprise = render_surprise
_render_temporal_depth = render_temporal_depth
_render_self_state = render_self_state
_TEMPORAL_STALE_S = 30.0
_APPERCEPTION_STALE_S = 30.0
_STIMMUNG_STALE_S = 300.0


def _clear_cache() -> None:
    """No-op. Retained for backward compatibility with existing tests."""


def render(tier: str = "CAPABLE") -> str:
    """Render phenomenal context for voice LLM injection.

    Returns a progressive-fidelity block of natural language that
    orients the LLM in the current experiential situation.
    """
    stimmung_data = read_json(_STIMMUNG_PATH)
    _raw_temporal = read_json(_TEMPORAL_PATH)
    apperception_data = read_json(_APPERCEPTION_PATH)
    perception_data = read_json(_PERCEPTION_STATE_PATH)
    audio_data = read_json(_AUDIO_PERCEPTION_PATH)
    segment_data = read_json(_ACTIVE_SEGMENT_PATH)

    temporal_data = parse_temporal_snapshot(_raw_temporal)

    lines: list[str] = []

    # ── Layer 1: Stimmung (non-nominal only) ─────────────────────
    if s := render_stimmung(stimmung_data):
        lines.append(s)

    # ── Layer 2: Situation coupling ──────────────────────────────
    if s := render_situation(temporal_data):
        lines.append(s)

    # ── Layer 2a: Audio activity + segment binding ───────────────
    if s := render_audio_context(stimmung_data, perception_data, audio_data, segment_data):
        lines.append(s)

    # ── Layer 2b: Aperture awareness (self-grounding) ───────────
    if s := read_aperture_state_block():
        lines.append(s)

    # ── Layer 2c: Speech prosody (how the operator is speaking) ─
    if s := read_prosody_block():
        lines.append(s)

    # ── Layer 3: Temporal impression + horizon ───────────────────
    if s := render_impression(temporal_data):
        lines.append(s)

    if tier == "LOCAL":
        return "\n".join(lines) if lines else ""

    # ── Layer 4: Surprise / deviation ────────────────────────────
    if s := render_surprise(temporal_data):
        lines.append(s)

    # ── Layer 5: Temporal depth (retention + protention) ─────────
    if s := render_temporal_depth(temporal_data):
        lines.append(s)

    if tier == "FAST":
        return "\n".join(lines) if lines else ""

    # ── Layer 6: Self-state (apperception) ───────────────────────
    if s := render_self_state(apperception_data):
        lines.append(s)

    return "\n".join(lines) if lines else ""
