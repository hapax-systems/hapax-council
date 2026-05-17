"""Tests for AMBIENT voice register and anti-personification enforcement."""

from __future__ import annotations

from shared.anti_personification_linter import lint_text
from shared.voice_register import DENSITY_SPEED_MAP, VoiceRegister


def test_ambient_register_exists() -> None:
    assert VoiceRegister.AMBIENT == "ambient"


def test_density_speed_map_values() -> None:
    assert DENSITY_SPEED_MAP["presenting"] == 0.85
    assert DENSITY_SPEED_MAP["ambient"] == 1.0
    assert DENSITY_SPEED_MAP["receptive"] == 1.05


# --- Positive corpus: should PASS the linter (no findings) ---

_POSITIVE_CORPUS = [
    "Recruitment threshold halved. Three dormant capabilities surfacing.",
    "Stimmung cautious — consent gates at elevated stringency.",
    "DMN pulse completed. Evaluative tick graded 0.73 on grounding quality.",
    "Operator active in the hapax-council workspace.",
    "Presence posterior declining; AWAY threshold approaching.",
    "The substrate is in SEEKING stance.",
]


def test_positive_corpus_passes_linter() -> None:
    for text in _POSITIVE_CORPUS:
        findings = lint_text(text)
        voice_findings = [f for f in findings if f.rule_id.startswith("voice_posture_violations.")]
        assert not voice_findings, f"False positive on: {text!r} -> {voice_findings}"


# --- Negative corpus: should FAIL the linter ---

_NEGATIVE_CORPUS = [
    ("Happy to help with that.", "social_performance"),
    ("Always here for you.", "availability_performance"),
    ("Hapax experiences a sense of wonder.", "inner_experience_claim"),
    ("Pleased to assist with this task.", "social_performance"),
    ("Hapax notices a feeling of satisfaction.", "inner_experience_claim"),
]


def test_negative_corpus_caught_by_linter() -> None:
    for text, expected_pattern in _NEGATIVE_CORPUS:
        findings = lint_text(text)
        voice_findings = [f for f in findings if f.rule_id.startswith("voice_posture_violations.")]
        assert voice_findings, f"Missed violation in: {text!r} (expected {expected_pattern})"
