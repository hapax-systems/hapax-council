"""Tests for CPAL signal cache."""

from unittest.mock import MagicMock

from agents.hapax_daimonion.cpal.signal_cache import (
    ACKNOWLEDGMENT_PHRASES,
    BACKCHANNEL_PHRASES,
    FORMULATION_PHRASES,
    SIGNAL_CATEGORIES,
    SignalCache,
)


class TestSignalCacheStructure:
    def test_three_categories(self):
        assert len(SIGNAL_CATEGORIES) == 3
        assert "vocal_backchannel" in SIGNAL_CATEGORIES
        assert "acknowledgment" in SIGNAL_CATEGORIES
        assert "formulation_onset" in SIGNAL_CATEGORIES

    def test_initial_state(self):
        cache = SignalCache()
        assert not cache.is_ready
        assert cache.total_signals == 0


class TestPresynthesis:
    def test_presynthesize_populates_cache(self):
        tts = MagicMock()
        tts.synthesize.return_value = b"\x00\x01" * 100

        cache = SignalCache()
        cache.presynthesize(tts)

        assert cache.is_ready
        expected = len(BACKCHANNEL_PHRASES) + len(ACKNOWLEDGMENT_PHRASES) + len(FORMULATION_PHRASES)
        assert cache.total_signals == expected

    def test_presynthesize_handles_failures(self):
        tts = MagicMock()
        call_count = 0

        def flaky_synth(text, use_case):
            nonlocal call_count
            call_count += 1
            if call_count % 3 == 0:
                return b""  # empty = failed
            return b"\x00\x01" * 50

        tts.synthesize = flaky_synth
        cache = SignalCache()
        cache.presynthesize(tts)

        assert cache.is_ready  # some succeeded
        assert cache.total_signals > 0
        assert cache.total_signals < len(BACKCHANNEL_PHRASES) + len(ACKNOWLEDGMENT_PHRASES) + len(
            FORMULATION_PHRASES
        )

    def test_presynthesize_no_tts_method(self):
        tts = object()  # no synthesize method
        cache = SignalCache()
        cache.presynthesize(tts)
        assert not cache.is_ready


class TestSelection:
    def test_select_backchannel(self):
        tts = MagicMock()
        tts.synthesize.return_value = b"\x00\x01" * 100

        cache = SignalCache()
        cache.presynthesize(tts)

        result = cache.select("vocal_backchannel")
        assert result is not None
        phrase, pcm = result
        assert phrase in BACKCHANNEL_PHRASES
        assert len(pcm) > 0

    def test_select_acknowledgment(self):
        tts = MagicMock()
        tts.synthesize.return_value = b"\x00\x01" * 100

        cache = SignalCache()
        cache.presynthesize(tts)

        result = cache.select("acknowledgment")
        assert result is not None
        assert result[0] in ACKNOWLEDGMENT_PHRASES

    def test_select_unknown_category(self):
        cache = SignalCache()
        assert cache.select("nonexistent") is None

    def test_select_empty_cache(self):
        cache = SignalCache()
        assert cache.select("vocal_backchannel") is None

    def test_get_by_phrase(self):
        tts = MagicMock()
        tts.synthesize.return_value = b"\xaa\xbb" * 50

        cache = SignalCache()
        cache.presynthesize(tts)

        pcm = cache.get_by_phrase("Mm-hm.")
        assert pcm is not None
        assert pcm == b"\xaa\xbb" * 50

    def test_get_by_phrase_missing(self):
        cache = SignalCache()
        assert cache.get_by_phrase("nonexistent") is None
