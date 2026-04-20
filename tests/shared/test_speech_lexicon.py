"""Tests for shared.speech_lexicon — canonical IPA overrides for Hapax terms."""

from __future__ import annotations

from shared.speech_lexicon import apply_lexicon


def test_noop_when_no_terms_present() -> None:
    result = apply_lexicon("The weather is nice today.")
    assert result.was_modified is False
    assert result.hit_count == 0
    assert result.text == "The weather is nice today."


def test_empty_and_whitespace_passthrough() -> None:
    for text in ("", "   ", "\n\t"):
        result = apply_lexicon(text)
        assert result.text == text
        assert result.was_modified is False
        assert result.hit_count == 0


def test_hapax_override_inserted() -> None:
    result = apply_lexicon("I am Hapax.")
    assert result.was_modified is True
    assert result.hit_count == 1
    assert "[Hapax](/hˈæpæks/)" in result.text


def test_all_four_terms() -> None:
    text = "Hapax studies the Legomenon, Legomena, and Oudepode."
    result = apply_lexicon(text)
    assert result.hit_count == 4
    assert "[Hapax](/hˈæpæks/)" in result.text
    assert "[Legomenon](/lɛˈɡɑmənɒn/)" in result.text
    assert "[Legomena](/lɛˈɡɑmənə/)" in result.text
    assert "[Oudepode](/uˈdɛpoʊdeɪ/)" in result.text


def test_case_insensitive_match_preserves_original_casing() -> None:
    result = apply_lexicon("HAPAX is hapax, Hapax everywhere.")
    # Three matches, each bracketed form preserves the input casing.
    assert result.hit_count == 3
    assert "[HAPAX](/hˈæpæks/)" in result.text
    assert "[hapax](/hˈæpæks/)" in result.text
    assert "[Hapax](/hˈæpæks/)" in result.text


def test_word_boundary_avoids_substring_hits() -> None:
    # "Hapaxes" (hypothetical plural) and "Legomenons" should not match —
    # the lexicon only knows base forms.
    result = apply_lexicon("The word Hapaxes and Legomenons are unknown.")
    assert result.was_modified is False
    assert result.hit_count == 0


def test_idempotent_on_already_wrapped() -> None:
    pre_wrapped = "I am [Hapax](/hˈæpæks/) and I speak."
    result = apply_lexicon(pre_wrapped)
    assert result.was_modified is False
    assert result.text == pre_wrapped


def test_applies_to_unwrapped_only_when_mixed() -> None:
    text = "[Hapax](/hˈæpæks/) meets Oudepode today."
    result = apply_lexicon(text)
    assert result.hit_count == 1
    assert result.text == "[Hapax](/hˈæpæks/) meets [Oudepode](/uˈdɛpoʊdeɪ/) today."
