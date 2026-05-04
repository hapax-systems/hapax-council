"""Tests for the grounding context envelope and clause verifier."""

from shared.grounding_context import GroundingContextVerifier


def test_build_envelope_fresh():
    bands = {"impression": {"freshness": "fresh"}}
    envelope = GroundingContextVerifier.build_envelope(
        turn_id="test_turn",
        temporal_bands=bands,
        phenomenal_lines=["Fresh environment"],
        available_tools=["generate_image"],
    )
    assert envelope.source_freshness == "fresh"
    assert "present-tense current-world factual claims" not in envelope.forbidden_assertions


def test_build_envelope_stale():
    bands = {"impression": {"freshness": "stale"}}
    envelope = GroundingContextVerifier.build_envelope(
        turn_id="test_turn",
        temporal_bands=bands,
        phenomenal_lines=["Stale environment"],
        available_tools=[],
    )
    assert envelope.source_freshness == "stale"
    assert "present-tense current-world factual claims" in envelope.forbidden_assertions
    assert (
        "live deictic visual references without visual tool output" in envelope.forbidden_assertions
    )


def test_build_envelope_protention():
    bands = {"impression": {"freshness": "missing"}, "protention": {"expected": "event"}}
    envelope = GroundingContextVerifier.build_envelope(
        turn_id="test_turn",
        temporal_bands=bands,
        phenomenal_lines=[],
        available_tools=[],
    )
    assert (
        "protention stated as fact without anticipatory language" in envelope.forbidden_assertions
    )


def test_verify_clause_stale_now():
    bands = {"impression": {"freshness": "stale"}}
    envelope = GroundingContextVerifier.build_envelope("1", bands, [], [])

    # Should block "now" and "currently"
    is_safe, reason = GroundingContextVerifier.verify_clause(
        envelope, "The system is currently stable."
    )
    assert not is_safe
    assert reason == "stale impression cannot ground 'now' or 'currently'"

    is_safe, reason = GroundingContextVerifier.verify_clause(envelope, "It happened yesterday.")
    assert is_safe


def test_verify_clause_protention_not_fact():
    bands = {"impression": {"freshness": "missing"}, "protention": {"expected": "event"}}
    envelope = GroundingContextVerifier.build_envelope("1", bands, [], [])

    # Should block "is happening"
    is_safe, reason = GroundingContextVerifier.verify_clause(envelope, "The event is happening.")
    assert not is_safe
    assert reason == "protention stated as fact"

    # Should allow "expected" or "likely"
    is_safe, reason = GroundingContextVerifier.verify_clause(
        envelope, "The event is likely to happen."
    )
    assert is_safe


def test_verify_clause_deictic_visual():
    bands = {"impression": {"freshness": "stale"}}
    envelope = GroundingContextVerifier.build_envelope("1", bands, [], [])

    # Should block ungrounded deictic visual ref
    is_safe, reason = GroundingContextVerifier.verify_clause(envelope, "Take a look at this.")
    assert not is_safe
    assert reason == "ungrounded deictic visual reference"

    is_safe, reason = GroundingContextVerifier.verify_clause(
        envelope, "This is an interesting idea."
    )
    # "this" without the visual deictic phrases is safe
    assert is_safe
