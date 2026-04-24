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


def test_oto_letter_by_letter_override() -> None:
    """OTO must be spoken letter-by-letter, not as the word "oto"."""
    result = apply_lexicon("OTO is live on air.")
    assert result.hit_count == 1
    assert result.was_modified is True
    assert "[OTO](/oʊ tiː oʊ/)" in result.text


def test_oto_case_insensitive_preserves_casing() -> None:
    result = apply_lexicon("oto and OTO and Oto.")
    assert result.hit_count == 3
    assert "[oto](/oʊ tiː oʊ/)" in result.text
    assert "[OTO](/oʊ tiː oʊ/)" in result.text
    assert "[Oto](/oʊ tiː oʊ/)" in result.text


def test_oudepode_the_operator_multiword_form() -> None:
    """The multi-word referent "Oudepode The Operator" gets its Oudepode
    prefix wrapped by the existing regex; "The Operator" flows through
    misaki's default G2P natively.
    """
    result = apply_lexicon("Oudepode The Operator is in the room.")
    assert result.hit_count == 1
    assert result.text == "[Oudepode](/uˈdɛpoʊdeɪ/) The Operator is in the room."


def test_all_four_non_formal_referents_round_trip() -> None:
    """Directive 2026-04-24: the four ratified non-formal referents all
    render correctly through the lexicon.
    """
    for text in (
        "The Operator is watching.",
        "Oudepode is watching.",
        "Oudepode The Operator is watching.",
        "OTO is watching.",
    ):
        result = apply_lexicon(text)
        # All four must produce output where known terms are wrapped and
        # the result is a valid string (misaki-parseable).
        assert "watching" in result.text
        # "The Operator" bare has no lexicon hit; others hit at least once.
        if text.startswith("The Operator"):
            assert result.hit_count == 0
        else:
            assert result.hit_count >= 1
