"""Unit tests for grounding_triage — Bayesian pre-emission self-check.

Tests that the grounding posterior correctly distinguishes grounded
narration (specific, novel, technically dense) from ungrounded slop
(generic, repetitive, filler).
"""

from __future__ import annotations

from agents.hapax_daimonion.autonomous_narrative.grounding_triage import (
    EMIT_FLOOR,
    RECOMPOSE_FLOOR,
    grounding_posterior,
    novelty_score,
    specificity_score,
    technical_density,
    triage,
)


# ── technical_density ─────────────────────────────────────────────────


def test_technical_density_high_for_specific_prose() -> None:
    text = "The AUX5 stimmung envelope holds at 0.72Hz. CPAL evaluator gain steady."
    density = technical_density(text)
    assert density >= 0.5, f"Expected high density, got {density}"


def test_technical_density_low_for_generic_prose() -> None:
    text = "Things are looking really interesting today. Let's see what happens next."
    density = technical_density(text)
    assert density < 0.5, f"Expected low density, got {density}"


def test_technical_density_zero_for_pure_filler() -> None:
    text = "It's worth noting that this is a great example of something."
    density = technical_density(text)
    assert density == 0.0, f"Expected zero density, got {density}"


# ── novelty_score ─────────────────────────────────────────────────────


def test_novelty_high_when_no_recent_speech() -> None:
    score = novelty_score("The broadcast safety gate fired twice.", [])
    assert score == 1.0


def test_novelty_low_when_repeating() -> None:
    candidate = "The broadcast safety gate fired twice in the last 90 seconds."
    recent = ["The broadcast safety gate fired twice in the last 90 seconds."]
    score = novelty_score(candidate, recent)
    assert score < 0.3, f"Expected low novelty for repetition, got {score}"


def test_novelty_moderate_for_related_content() -> None:
    candidate = "The broadcast safety gate resolved the conflict successfully."
    recent = ["The broadcast safety gate fired twice in the last 90 seconds."]
    score = novelty_score(candidate, recent)
    assert 0.2 < score < 0.8, f"Expected moderate novelty, got {score}"


# ── specificity_score ─────────────────────────────────────────────────


def test_specificity_neutral_with_no_impingements() -> None:
    score = specificity_score("Anything goes.", [])
    assert score == 0.5, f"Expected neutral specificity, got {score}"


def test_specificity_high_when_terms_overlap() -> None:
    candidate = "The broadcast safety gate fired during the stimmung check."
    impingements = [
        {"content": {"narrative": "broadcast safety gate triggered during stimmung evaluation"}}
    ]
    score = specificity_score(candidate, impingements)
    assert score > 0.3, f"Expected high specificity overlap, got {score}"


def test_specificity_low_for_generic_against_specific_context() -> None:
    candidate = "Things are looking really interesting and fascinating."
    impingements = [
        {"content": {"narrative": "AUX5 channel dropout detected at 0.72Hz threshold"}}
    ]
    score = specificity_score(candidate, impingements)
    assert score < 0.3, f"Expected low specificity for generic prose, got {score}"


# ── grounding_posterior ───────────────────────────────────────────────


def test_grounded_prose_scores_above_emit_floor() -> None:
    candidate = "The AUX5 channel resolved 14 false positives in the CPAL evaluator pass."
    impingements = [
        {"content": {"narrative": "AUX5 channel triage resolved false positives in CPAL"}}
    ]
    p = grounding_posterior(
        candidate, impingements=impingements, recent_speech=[], gqi=0.8,
    )
    assert p >= EMIT_FLOOR, f"Grounded prose should score >= {EMIT_FLOOR}, got {p}"


def test_generic_slop_scores_below_recompose_floor() -> None:
    candidate = "Today we're diving into some fascinating developments in the field."
    p = grounding_posterior(
        candidate, impingements=[], recent_speech=[], gqi=0.8,
    )
    assert p < RECOMPOSE_FLOOR, f"Generic slop should score < {RECOMPOSE_FLOOR}, got {p}"


# ── triage ────────────────────────────────────────────────────────────


def test_triage_emits_grounded_content() -> None:
    candidate = "The CPAL evaluator gain dropped 0.02 after the GQI fell below 0.4."
    impingements = [
        {"content": {"narrative": "CPAL evaluator gain adjustment triggered by GQI decline"}}
    ]
    action, p = triage(
        candidate, impingements=impingements, recent_speech=[], gqi=0.8,
    )
    assert action == "emit", f"Expected 'emit', got '{action}' (p={p})"


def test_triage_silences_pure_filler() -> None:
    candidate = "It is worth noting that things are getting really interesting here."
    action, p = triage(
        candidate, impingements=[], recent_speech=[], gqi=0.8,
    )
    assert action in ("silence", "marginal"), (
        f"Expected silence/marginal for filler, got '{action}' (p={p})"
    )
