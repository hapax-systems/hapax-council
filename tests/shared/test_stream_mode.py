"""Tests for shared.stream_mode (LRR Phase 6 §2)."""

from __future__ import annotations

import pytest

from shared.stream_mode import (
    StreamMode,
    get_stream_mode,
    get_stream_mode_or_off,
    is_off,
    is_private,
    is_public,
    is_public_research,
    is_publicly_visible,
    is_research_visible,
    set_stream_mode,
)


@pytest.fixture
def mode_file(tmp_path):
    return tmp_path / "stream-mode"


class TestRoundTrip:
    def test_set_then_get(self, mode_file):
        set_stream_mode(StreamMode.PRIVATE, path=mode_file)
        assert get_stream_mode(path=mode_file) is StreamMode.PRIVATE

    @pytest.mark.parametrize(
        "mode",
        [StreamMode.OFF, StreamMode.PRIVATE, StreamMode.PUBLIC, StreamMode.PUBLIC_RESEARCH],
    )
    def test_all_modes_round_trip(self, mode_file, mode):
        set_stream_mode(mode, path=mode_file)
        assert get_stream_mode(path=mode_file) is mode


class TestFailClosed:
    def test_missing_file_fails_closed_to_public(self, mode_file):
        # mode_file does not exist
        assert get_stream_mode(path=mode_file) is StreamMode.PUBLIC

    def test_malformed_file_fails_closed_to_public(self, mode_file):
        mode_file.write_text("not-a-valid-mode\n")
        assert get_stream_mode(path=mode_file) is StreamMode.PUBLIC

    def test_empty_file_fails_closed_to_public(self, mode_file):
        mode_file.write_text("")
        assert get_stream_mode(path=mode_file) is StreamMode.PUBLIC

    def test_is_publicly_visible_true_on_missing(self, mode_file):
        assert is_publicly_visible(path=mode_file) is True

    def test_is_publicly_visible_false_when_off(self, mode_file):
        set_stream_mode(StreamMode.OFF, path=mode_file)
        assert is_publicly_visible(path=mode_file) is False

    def test_is_publicly_visible_false_when_private(self, mode_file):
        set_stream_mode(StreamMode.PRIVATE, path=mode_file)
        assert is_publicly_visible(path=mode_file) is False

    def test_is_publicly_visible_true_for_public(self, mode_file):
        set_stream_mode(StreamMode.PUBLIC, path=mode_file)
        assert is_publicly_visible(path=mode_file) is True

    def test_is_publicly_visible_true_for_public_research(self, mode_file):
        set_stream_mode(StreamMode.PUBLIC_RESEARCH, path=mode_file)
        assert is_publicly_visible(path=mode_file) is True


class TestFailOpenToOff:
    def test_missing_file_or_off_returns_off(self, mode_file):
        # or_off variant defaults to OFF for diagnostic callers
        assert get_stream_mode_or_off(path=mode_file) is StreamMode.OFF


class TestPredicates:
    def test_is_off(self, mode_file):
        set_stream_mode(StreamMode.OFF, path=mode_file)
        assert is_off(path=mode_file) is True
        assert is_private(path=mode_file) is False
        assert is_public(path=mode_file) is False
        assert is_public_research(path=mode_file) is False

    def test_is_private(self, mode_file):
        set_stream_mode(StreamMode.PRIVATE, path=mode_file)
        assert is_off(path=mode_file) is False
        assert is_private(path=mode_file) is True
        assert is_public(path=mode_file) is False

    def test_is_public(self, mode_file):
        set_stream_mode(StreamMode.PUBLIC, path=mode_file)
        assert is_public(path=mode_file) is True
        assert is_public_research(path=mode_file) is False

    def test_is_public_research(self, mode_file):
        set_stream_mode(StreamMode.PUBLIC_RESEARCH, path=mode_file)
        assert is_public_research(path=mode_file) is True
        assert is_public(path=mode_file) is False

    def test_is_research_visible_only_in_public_research(self, mode_file):
        for mode in [StreamMode.OFF, StreamMode.PRIVATE, StreamMode.PUBLIC]:
            set_stream_mode(mode, path=mode_file)
            assert is_research_visible(path=mode_file) is False
        set_stream_mode(StreamMode.PUBLIC_RESEARCH, path=mode_file)
        assert is_research_visible(path=mode_file) is True


class TestAtomicWrite:
    def test_write_leaves_no_tmp_file_on_success(self, mode_file):
        set_stream_mode(StreamMode.PRIVATE, path=mode_file)
        assert mode_file.exists()
        assert not mode_file.with_suffix(".tmp").exists()
