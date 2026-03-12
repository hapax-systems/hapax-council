"""Tests for source-qualified behavior naming — pure string algebra.

Trinary tests for each function + Hypothesis roundtrip and disjointness properties.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from agents.hapax_voice.primitives import Behavior
from agents.hapax_voice.source_naming import (
    behaviors_for_base,
    behaviors_for_source,
    is_qualified,
    parse,
    qualify,
    validate_source_id,
)

# Valid source IDs for Hypothesis
valid_source_ids = st.from_regex(r"[a-z0-9_]{1,30}", fullmatch=True)
valid_base_names = st.from_regex(r"[a-z][a-z0-9_]{0,29}", fullmatch=True)


# ===========================================================================
# Trinary: validate_source_id
# ===========================================================================


class TestValidateSourceId:
    def test_valid_lowercase(self):
        validate_source_id("monitor_mix")  # no exception

    def test_valid_with_digits(self):
        validate_source_id("sp404_left_2")  # no exception

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            validate_source_id("")

    def test_colon_raises(self):
        with pytest.raises(ValueError, match="lowercase"):
            validate_source_id("bad:id")

    def test_uppercase_raises(self):
        with pytest.raises(ValueError, match="lowercase"):
            validate_source_id("MonitorMix")

    def test_space_raises(self):
        with pytest.raises(ValueError, match="lowercase"):
            validate_source_id("monitor mix")


# ===========================================================================
# Trinary: qualify
# ===========================================================================


class TestQualify:
    def test_valid(self):
        assert qualify("audio_energy_rms", "monitor_mix") == "audio_energy_rms:monitor_mix"

    def test_empty_base_raises(self):
        with pytest.raises(ValueError, match="Base name"):
            qualify("", "monitor_mix")

    def test_empty_source_raises(self):
        with pytest.raises(ValueError, match="empty"):
            qualify("audio_energy_rms", "")

    def test_invalid_source_raises(self):
        with pytest.raises(ValueError, match="lowercase"):
            qualify("audio_energy_rms", "Bad-Source")


# ===========================================================================
# Trinary: parse
# ===========================================================================


class TestParse:
    def test_qualified(self):
        base, source = parse("audio_energy_rms:monitor_mix")
        assert base == "audio_energy_rms"
        assert source == "monitor_mix"

    def test_unqualified(self):
        base, source = parse("stream_bitrate")
        assert base == "stream_bitrate"
        assert source is None

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            parse("")

    def test_multiple_colons_splits_on_first(self):
        base, source = parse("a:b:c")
        assert base == "a"
        assert source == "b:c"


# ===========================================================================
# Trinary: is_qualified
# ===========================================================================


class TestIsQualified:
    def test_qualified_true(self):
        assert is_qualified("audio_energy_rms:monitor_mix") is True

    def test_unqualified_false(self):
        assert is_qualified("stream_bitrate") is False


# ===========================================================================
# Trinary: behaviors_for_source
# ===========================================================================


class TestBehaviorsForSource:
    def _make_behaviors(self):
        return {
            "audio_energy_rms:monitor_mix": Behavior(0.7, watermark=1.0),
            "audio_onset:monitor_mix": Behavior(False, watermark=1.0),
            "audio_energy_rms:oxi_one": Behavior(0.3, watermark=1.0),
            "stream_bitrate": Behavior(4500.0, watermark=1.0),
        }

    def test_filters_matching_source(self):
        result = behaviors_for_source(self._make_behaviors(), "monitor_mix")
        assert set(result.keys()) == {
            "audio_energy_rms:monitor_mix",
            "audio_onset:monitor_mix",
        }

    def test_excludes_other_sources(self):
        result = behaviors_for_source(self._make_behaviors(), "monitor_mix")
        assert "audio_energy_rms:oxi_one" not in result

    def test_excludes_unqualified(self):
        result = behaviors_for_source(self._make_behaviors(), "monitor_mix")
        assert "stream_bitrate" not in result

    def test_empty_on_no_match(self):
        result = behaviors_for_source(self._make_behaviors(), "nonexistent")
        assert len(result) == 0


# ===========================================================================
# Trinary: behaviors_for_base
# ===========================================================================


class TestBehaviorsForBase:
    def _make_behaviors(self):
        return {
            "audio_energy_rms:monitor_mix": Behavior(0.7, watermark=1.0),
            "audio_energy_rms:oxi_one": Behavior(0.3, watermark=1.0),
            "audio_onset:monitor_mix": Behavior(False, watermark=1.0),
            "stream_bitrate": Behavior(4500.0, watermark=1.0),
        }

    def test_returns_all_sources_for_base(self):
        result = behaviors_for_base(self._make_behaviors(), "audio_energy_rms")
        assert set(result.keys()) == {
            "audio_energy_rms:monitor_mix",
            "audio_energy_rms:oxi_one",
        }

    def test_excludes_different_base(self):
        result = behaviors_for_base(self._make_behaviors(), "audio_energy_rms")
        assert "audio_onset:monitor_mix" not in result

    def test_includes_unqualified_if_matching(self):
        result = behaviors_for_base(self._make_behaviors(), "stream_bitrate")
        assert "stream_bitrate" in result

    def test_empty_on_no_match(self):
        result = behaviors_for_base(self._make_behaviors(), "nonexistent")
        assert len(result) == 0


# ===========================================================================
# Hypothesis property tests
# ===========================================================================


class TestSourceNamingProperties:
    @given(valid_base_names, valid_source_ids)
    def test_qualify_parse_roundtrip(self, base: str, source: str):
        """parse(qualify(base, source)) == (base, source) for all valid inputs."""
        qualified = qualify(base, source)
        parsed_base, parsed_source = parse(qualified)
        assert parsed_base == base
        assert parsed_source == source

    @given(valid_base_names, valid_source_ids)
    def test_qualify_produces_qualified(self, base: str, source: str):
        """is_qualified(qualify(base, source)) is always True."""
        assert is_qualified(qualify(base, source)) is True

    @given(valid_base_names, valid_source_ids, valid_source_ids)
    def test_different_sources_produce_different_names(self, base: str, s1: str, s2: str):
        """qualify(base, s1) != qualify(base, s2) when s1 != s2."""
        if s1 != s2:
            assert qualify(base, s1) != qualify(base, s2)

    @given(valid_base_names, valid_source_ids)
    def test_qualify_contains_separator(self, base: str, source: str):
        """Qualified names always contain the separator."""
        assert ":" in qualify(base, source)
