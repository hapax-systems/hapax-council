"""FINDING-X Phase 1 — grounding-provenance synthesis hook tests."""

from __future__ import annotations

import json

from agents.studio_compositor.director_loop import (
    _ensure_impingement_grounded,
    _ensure_intent_grounded,
    _parse_intent_from_llm,
)
from shared.director_intent import CompositionalImpingement, DirectorIntent
from shared.stimmung import Stance

# ── _ensure_impingement_grounded (leaf helper) ──────────────────────


def test_populated_provenance_unchanged() -> None:
    imp = CompositionalImpingement(
        narrative="focus on vinyl",
        intent_family="camera.hero",
        grounding_provenance=["audio.midi.beat_position"],
    )
    result = _ensure_impingement_grounded(imp, stance=Stance.NOMINAL)
    assert result.grounding_provenance == ["audio.midi.beat_position"]
    # No-op path returns the same instance rather than a copy.
    assert result is imp


def test_empty_provenance_synthesized_seeking() -> None:
    imp = CompositionalImpingement(
        narrative="neutral ambient",
        intent_family="preset.bias",
        grounding_provenance=[],
    )
    result = _ensure_impingement_grounded(imp, stance=Stance.SEEKING)
    assert result.grounding_provenance == ["inferred.seeking.preset.bias"]
    # Copy, not mutation
    assert imp.grounding_provenance == []


def test_empty_provenance_synthesized_nominal() -> None:
    imp = CompositionalImpingement(
        narrative="surface this",
        intent_family="ward.highlight",
        grounding_provenance=[],
    )
    result = _ensure_impingement_grounded(imp, stance=Stance.NOMINAL)
    assert result.grounding_provenance == ["inferred.nominal.ward.highlight"]


def test_synth_counter_increments_on_empty() -> None:
    from shared.director_observability import _ungrounded_synth_total

    before = _ungrounded_synth_total.labels(intent_family="ward.highlight")._value.get()
    imp = CompositionalImpingement(
        narrative="surface this",
        intent_family="ward.highlight",
        grounding_provenance=[],
    )
    _ensure_impingement_grounded(imp, stance=Stance.NOMINAL)
    after = _ungrounded_synth_total.labels(intent_family="ward.highlight")._value.get()
    assert after - before == 1.0


def test_synth_counter_untouched_on_populated() -> None:
    from shared.director_observability import _ungrounded_synth_total

    before = _ungrounded_synth_total.labels(intent_family="camera.hero")._value.get()
    imp = CompositionalImpingement(
        narrative="focus",
        intent_family="camera.hero",
        grounding_provenance=["audio.onset"],
    )
    _ensure_impingement_grounded(imp, stance=Stance.NOMINAL)
    after = _ungrounded_synth_total.labels(intent_family="camera.hero")._value.get()
    assert after == before


# ── _ensure_intent_grounded (per-intent) ────────────────────────────

# DirectorIntent requires activity, stance, narrative_text, and at least one
# compositional_impingement. Empty-impingements case isn't constructible by
# the model, so we only exercise "one populated" and "one empty" arrangements.


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


def test_intent_with_one_empty_one_populated_synthesises_only_empty() -> None:
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
    assert result is not intent  # new copy
    assert result.compositional_impingements[0].grounding_provenance == ["audio.onset"]
    assert result.compositional_impingements[1].grounding_provenance == [
        "inferred.cautious.preset.bias"
    ]


def test_intent_top_level_empty_provenance_not_synthesised() -> None:
    """Spec §4: per-impingement synthesis only. Top-level stays empty."""
    intent = DirectorIntent(
        activity="react",
        stance=Stance.NOMINAL,
        narrative_text="x",
        grounding_provenance=[],  # deliberately empty
        compositional_impingements=[
            CompositionalImpingement(
                narrative="c",
                intent_family="ward.highlight",
                grounding_provenance=[],
            ),
        ],
    )
    result = _ensure_intent_grounded(intent)
    # Top-level stays empty (emit_ungrounded_audit still fires on this scope)
    assert result.grounding_provenance == []
    # Per-impingement synthesised
    assert result.compositional_impingements[0].grounding_provenance == [
        "inferred.nominal.ward.highlight"
    ]


# ── _parse_intent_from_llm (end-to-end) ─────────────────────────────


def test_parse_from_llm_synthesises_empty_impingement_provenance() -> None:
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
    assert intent.compositional_impingements, "expected one impingement"
    for imp in intent.compositional_impingements:
        assert imp.grounding_provenance, (
            f"impingement {imp.intent_family} has empty provenance after parse"
        )
        assert imp.grounding_provenance[0].startswith("inferred.")


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
