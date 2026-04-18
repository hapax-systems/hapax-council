"""Regression pin: operator no-vacuum invariant (2026-04-18).

Every DirectorIntent emitted by the parser MUST carry at least one
compositional_impingement. Empty-impingement intents were the 25%
leak observed on 2026-04-18 (184 / 735 live ticks). This test
exercises each parser-error path and asserts the invariant.

Operator quote: "The director loop should be having some kind of
actual effect on the livestream every time. There is no justifiable
context where 'do nothing interesting' is acceptable."
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.studio_compositor.director_loop import (
    _parse_intent_from_llm,
    _silence_hold_fallback_intent,
    _silence_hold_impingement,
)
from shared.director_intent import DirectorIntent


@pytest.mark.parametrize(
    ("raw", "label"),
    [
        ("", "parser_empty_text"),
        ("not json at all", "parser_non_json_prefix"),
        ("{malformed json", "parser_json_decode"),
        ("[1, 2, 3]", "parser_non_dict"),
        ('{"activity": "silence"}', "parser_legacy_shape"),
        ('{"activity": "react", "react": "cut to the triangle"}', "parser_legacy_with_narrative"),
        (
            '{"stance": "nominal", "activity": "react", "narrative_text": "", '
            '"compositional_impingements": []}',
            "parser_full_shape_empty_impingements",
        ),
    ],
)
def test_parser_never_emits_empty_impingements(raw: str, label: str) -> None:
    """Regression pin: every parser fallback path must populate at least
    one compositional_impingement, even when the LLM returned malformed
    or legacy-shape output."""
    intent = _parse_intent_from_llm(raw, condition_id=f"test-{label}", tier="test")
    assert isinstance(intent, DirectorIntent)
    assert len(intent.compositional_impingements) >= 1, (
        f"Parser case {label!r} emitted empty impingements — violates "
        "operator no-vacuum invariant (2026-04-18)."
    )


def test_silence_hold_impingement_is_valid() -> None:
    """The silence-hold helper must produce a construction-valid impingement."""
    imp = _silence_hold_impingement()
    assert imp.narrative
    assert imp.intent_family == "overlay.emphasis"
    assert imp.material == "void"
    assert 0.0 <= imp.salience <= 1.0


def test_silence_hold_fallback_intent_is_valid() -> None:
    """The fallback-intent helper must satisfy the tightened schema."""
    intent = _silence_hold_fallback_intent(
        activity="silence",
        narrative_text="",
        reason="test_reason",
        tier="test",
        condition_id="test-condition",
    )
    assert len(intent.compositional_impingements) == 1
    assert intent.activity == "silence"


def test_schema_rejects_empty_impingements() -> None:
    """Pydantic validation must reject DirectorIntent with no impingements."""
    from shared.stimmung import Stance

    with pytest.raises(ValidationError):
        DirectorIntent(
            activity="silence",
            stance=Stance.NOMINAL,
            narrative_text="",
            compositional_impingements=[],
        )
