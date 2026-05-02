"""R8 grounding-act-gate tests (effect+cam orchestration audit, 2026-05-02).

Replaces the FINDING-X Phase 1 silent-synthesis tests. The gate now
REJECTS LLM-emitted impingements that arrive with empty real
grounding_provenance and no deterministic-code fallback marker, drops
them from the downstream list, increments
``hapax_director_ungrounded_rejection_total`` and warn-logs. Fallback
emitters (silence_hold, micromove, parser fallbacks) populate
``synthetic_grounding_markers`` eagerly and pass the gate untouched.
"""

from __future__ import annotations

import json
import logging

from agents.studio_compositor.director_loop import (
    _ensure_impingement_grounded,
    _ensure_intent_grounded,
    _parse_intent_from_llm,
)
from shared.director_intent import CompositionalImpingement, DirectorIntent
from shared.stimmung import Stance

# ── _ensure_impingement_grounded (leaf gate) ────────────────────────


def test_populated_provenance_passes_gate_unchanged() -> None:
    imp = CompositionalImpingement(
        narrative="focus on vinyl",
        intent_family="camera.hero",
        grounding_provenance=["audio.midi.beat_position"],
    )
    result = _ensure_impingement_grounded(imp, stance=Stance.NOMINAL)
    assert result is imp  # no-op path returns same instance


def test_fallback_marker_passes_gate_unchanged() -> None:
    """Deterministic-code fallback paths set ``synthetic_grounding_markers``
    eagerly and must not be rejected by the R8 gate."""
    imp = CompositionalImpingement(
        narrative="silence hold",
        intent_family="overlay.emphasis",
        grounding_provenance=[],
        synthetic_grounding_markers=["fallback.silence_hold"],
    )
    result = _ensure_impingement_grounded(imp, stance=Stance.NOMINAL)
    assert result is imp


def test_empty_provenance_rejected_loudly_seeking(caplog) -> None:
    imp = CompositionalImpingement(
        narrative="neutral ambient",
        intent_family="preset.bias",
        grounding_provenance=[],
    )
    with caplog.at_level(logging.WARNING, logger="agents.studio_compositor.director_loop"):
        result = _ensure_impingement_grounded(imp, stance=Stance.SEEKING)
    assert result is None
    rejected = [r for r in caplog.records if "REJECTED ungrounded impingement" in r.getMessage()]
    assert len(rejected) == 1
    assert "intent_family=preset.bias" in rejected[0].getMessage()
    assert "stance=seeking" in rejected[0].getMessage()


def test_empty_provenance_rejected_loudly_nominal(caplog) -> None:
    imp = CompositionalImpingement(
        narrative="surface this",
        intent_family="ward.highlight",
        grounding_provenance=[],
    )
    with caplog.at_level(logging.WARNING, logger="agents.studio_compositor.director_loop"):
        result = _ensure_impingement_grounded(imp, stance=Stance.NOMINAL)
    assert result is None
    rejected = [r for r in caplog.records if "REJECTED ungrounded impingement" in r.getMessage()]
    assert len(rejected) == 1
    assert "intent_family=ward.highlight" in rejected[0].getMessage()


def test_rejection_counter_increments_on_empty() -> None:
    from shared.director_observability import _ungrounded_rejection_total

    before = _ungrounded_rejection_total.labels(intent_family="ward.highlight")._value.get()
    imp = CompositionalImpingement(
        narrative="surface this",
        intent_family="ward.highlight",
        grounding_provenance=[],
    )
    _ensure_impingement_grounded(imp, stance=Stance.NOMINAL)
    after = _ungrounded_rejection_total.labels(intent_family="ward.highlight")._value.get()
    assert after - before == 1.0


def test_rejection_counter_untouched_on_populated() -> None:
    from shared.director_observability import _ungrounded_rejection_total

    before = _ungrounded_rejection_total.labels(intent_family="camera.hero")._value.get()
    imp = CompositionalImpingement(
        narrative="focus",
        intent_family="camera.hero",
        grounding_provenance=["audio.onset"],
    )
    _ensure_impingement_grounded(imp, stance=Stance.NOMINAL)
    after = _ungrounded_rejection_total.labels(intent_family="camera.hero")._value.get()
    assert after == before


def test_rejection_counter_untouched_on_fallback_marker() -> None:
    from shared.director_observability import _ungrounded_rejection_total

    before = _ungrounded_rejection_total.labels(intent_family="overlay.emphasis")._value.get()
    imp = CompositionalImpingement(
        narrative="silence hold",
        intent_family="overlay.emphasis",
        grounding_provenance=[],
        synthetic_grounding_markers=["fallback.silence_hold"],
    )
    _ensure_impingement_grounded(imp, stance=Stance.NOMINAL)
    after = _ungrounded_rejection_total.labels(intent_family="overlay.emphasis")._value.get()
    assert after == before


def test_long_narrative_truncated_in_warning(caplog) -> None:
    long_narrative = "x" * 200
    imp = CompositionalImpingement(
        narrative=long_narrative,
        intent_family="preset.bias",
        grounding_provenance=[],
    )
    with caplog.at_level(logging.WARNING, logger="agents.studio_compositor.director_loop"):
        _ensure_impingement_grounded(imp, stance=Stance.NOMINAL)
    rejected = [r for r in caplog.records if "REJECTED ungrounded impingement" in r.getMessage()]
    assert any("..." in r.getMessage() for r in rejected)


# ── _ensure_intent_grounded (per-intent filter + silence-hold fallback) ─────


def test_intent_with_all_populated_returns_unchanged() -> None:
    intent = DirectorIntent(
        activity="react",
        stance=Stance.NOMINAL,
        narrative_text="steady",
        grounding_provenance=["audio.bpm"],
        compositional_impingements=[
            CompositionalImpingement(
                narrative="hero",
                intent_family="camera.hero",
                grounding_provenance=["audio.bpm"],
            ),
        ],
    )
    result = _ensure_intent_grounded(intent)
    assert result is intent


def test_intent_with_one_empty_one_populated_drops_only_empty() -> None:
    """The R8 gate filters out only the ungrounded impingement; the
    populated one survives. The intent is rebuilt with the survivor."""
    intent = DirectorIntent(
        activity="react",
        stance=Stance.CAUTIOUS,
        narrative_text="active",
        grounding_provenance=[],
        compositional_impingements=[
            CompositionalImpingement(
                narrative="a",
                intent_family="camera.hero",
                grounding_provenance=["audio.onset"],
            ),
            CompositionalImpingement(
                narrative="b",
                intent_family="preset.bias",
                grounding_provenance=[],
            ),
        ],
    )
    result = _ensure_intent_grounded(intent)
    assert result is not intent
    assert len(result.compositional_impingements) == 1
    survivor = result.compositional_impingements[0]
    assert survivor.intent_family == "camera.hero"
    assert survivor.grounding_provenance == ["audio.onset"]


def test_intent_all_empty_substitutes_silence_hold() -> None:
    """When every impingement is rejected, ``_ensure_intent_grounded``
    substitutes a single silence-hold so DirectorIntent's no-vacuum
    invariant (≥1 impingement) stays satisfied. The silence-hold is
    deterministic-code fallback and carries
    ``synthetic_grounding_markers=['fallback.all_impingements_rejected_ungrounded']``."""
    intent = DirectorIntent(
        activity="react",
        stance=Stance.NOMINAL,
        narrative_text="x",
        grounding_provenance=[],
        compositional_impingements=[
            CompositionalImpingement(
                narrative="c",
                intent_family="ward.highlight",
                grounding_provenance=[],
            ),
        ],
    )
    result = _ensure_intent_grounded(intent)
    assert len(result.compositional_impingements) == 1
    silence = result.compositional_impingements[0]
    assert silence.synthetic_grounding_markers == ["fallback.all_impingements_rejected_ungrounded"]
    assert silence.intent_family == "overlay.emphasis"
    assert silence.diagnostic is True


def test_intent_top_level_empty_provenance_unchanged_at_top_level() -> None:
    """Spec: top-level intent provenance is NOT touched by R8. Only
    per-impingement gating happens here. (The scope='intent' branch of
    ``emit_ungrounded_audit`` records top-level empties separately.)"""
    intent = DirectorIntent(
        activity="react",
        stance=Stance.NOMINAL,
        narrative_text="x",
        grounding_provenance=[],
        compositional_impingements=[
            CompositionalImpingement(
                narrative="grounded",
                intent_family="ward.highlight",
                grounding_provenance=["audio.onset"],
            ),
        ],
    )
    result = _ensure_intent_grounded(intent)
    assert result.grounding_provenance == []  # untouched


# ── _parse_intent_from_llm (end-to-end) ─────────────────────────────


def test_parse_from_llm_drops_ungrounded_impingement_substitutes_silence_hold() -> None:
    """End-to-end: LLM emits one impingement with empty grounding. The
    parser runs ``_ensure_intent_grounded`` which rejects it via R8 and
    substitutes a silence-hold so the no-vacuum invariant holds."""
    raw = json.dumps(
        {
            "activity": "react",
            "stance": "nominal",
            "narrative_text": "steady",
            "grounding_provenance": [],
            "compositional_impingements": [
                {
                    "narrative": "neutral ambient",
                    "intent_family": "preset.bias",
                    "grounding_provenance": [],
                    "salience": 0.3,
                },
            ],
        }
    )
    intent = _parse_intent_from_llm(raw, condition_id="test")
    assert len(intent.compositional_impingements) == 1
    surviving = intent.compositional_impingements[0]
    assert surviving.synthetic_grounding_markers == [
        "fallback.all_impingements_rejected_ungrounded"
    ]
    assert surviving.intent_family == "overlay.emphasis"


def test_parse_from_llm_preserves_populated_impingement_provenance() -> None:
    raw = json.dumps(
        {
            "activity": "react",
            "stance": "nominal",
            "narrative_text": "steady",
            "grounding_provenance": ["audio.bpm"],
            "compositional_impingements": [
                {
                    "narrative": "focus",
                    "intent_family": "camera.hero",
                    "grounding_provenance": ["audio.onset"],
                    "salience": 0.4,
                },
            ],
        }
    )
    intent = _parse_intent_from_llm(raw, condition_id="test")
    assert intent.compositional_impingements[0].grounding_provenance == ["audio.onset"]
    assert intent.compositional_impingements[0].intent_family == "camera.hero"


def test_parse_from_llm_mixed_keeps_only_grounded() -> None:
    raw = json.dumps(
        {
            "activity": "react",
            "stance": "nominal",
            "narrative_text": "steady",
            "grounding_provenance": ["audio.bpm"],
            "compositional_impingements": [
                {
                    "narrative": "grounded",
                    "intent_family": "camera.hero",
                    "grounding_provenance": ["audio.onset"],
                    "salience": 0.4,
                },
                {
                    "narrative": "ungrounded",
                    "intent_family": "preset.bias",
                    "grounding_provenance": [],
                    "salience": 0.3,
                },
            ],
        }
    )
    intent = _parse_intent_from_llm(raw, condition_id="test")
    assert len(intent.compositional_impingements) == 1
    assert intent.compositional_impingements[0].intent_family == "camera.hero"
