"""Tests for AudioInputStream — async pw-cat subprocess audio source.

The module was rewritten away from PyAudio in commit 3b176e0a9 (and
again in ecefe6a22 for AEC source routing) but the test file kept
the legacy pyaudio-mocking shape, producing 15 stale failures in
every CI run. This file replaces the dead tests with focused
coverage of the current async-subprocess implementation.

Three concerns covered:

1. Frame math — sample rate × duration → frame_samples / frame_bytes.
2. Source resolution — env-driven AEC vs raw Yeti default + the
   priority-list helper for multi-source fallback.
3. Lifecycle state — start sets active, stop clears it, double-stop
   tolerated.

Subprocess + asyncio.Queue plumbing is exercised by the live audio
path during the operator's regression smoke (audio-pathways Phase 4
T4.1) — those paths require a running PipeWire graph and are not
mock-friendly without rewriting half the module.
"""

from __future__ import annotations

import asyncio

import pytest  # noqa: TC002 — used at runtime for MonkeyPatch type annotations

from agents.hapax_daimonion.audio_input import (
    AudioInputStream,
    _resolve_default_source,
    resolve_source,
)

# ── Frame-math properties ─────────────────────────────────────────────


class TestFrameMath:
    def test_frame_samples_30ms_16khz(self) -> None:
        s = AudioInputStream(sample_rate=16000, frame_ms=30)
        # 16000 samples/sec × 0.030 sec = 480 samples
        assert s.frame_samples == 480

    def test_frame_bytes_int16(self) -> None:
        s = AudioInputStream(sample_rate=16000, frame_ms=30)
        # int16 = 2 bytes/sample → 480 × 2 = 960
        assert s.frame_bytes == 960

    def test_frame_samples_other_rates(self) -> None:
        # 44.1 kHz × 20 ms → 882 samples / 1764 bytes
        s = AudioInputStream(sample_rate=44100, frame_ms=20)
        assert s.frame_samples == 882
        assert s.frame_bytes == 1764


# ── Default source resolution ─────────────────────────────────────────


class TestDefaultSourceResolution:
    def test_aec_disabled_uses_raw_yeti(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without HAPAX_AEC_ACTIVE=1 the resolver falls through to the
        raw Yeti pattern — the daimonion does not chase a virtual source
        that may not exist in the live graph."""
        monkeypatch.delenv("HAPAX_AEC_ACTIVE", raising=False)
        result = _resolve_default_source()
        assert "Yeti" in result or "yeti" in result.lower()

    def test_aec_enabled_returns_echo_cancel_capture(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HAPAX_AEC_ACTIVE=1 routes daimonion through the
        echo_cancel_capture virtual source (#134 Phase 2 wire-in)."""
        monkeypatch.setenv("HAPAX_AEC_ACTIVE", "1")
        assert _resolve_default_source() == "echo_cancel_capture"

    def test_aec_off_explicit_returns_yeti(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HAPAX_AEC_ACTIVE", "0")
        result = _resolve_default_source()
        assert result != "echo_cancel_capture"

    def test_aec_empty_string_returns_yeti(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty env var (set but blank) is NOT truthy — match the
        explicit `==1` semantics."""
        monkeypatch.setenv("HAPAX_AEC_ACTIVE", "")
        result = _resolve_default_source()
        assert result != "echo_cancel_capture"


# ── resolve_source priority-list helper ──────────────────────────────


class TestResolveSource:
    def test_returns_first_present_node(self) -> None:
        """Walks the candidate list, returns the first one present in
        the live graph (per the pw-cli runner)."""

        def _runner() -> str:
            return "alsa_input.usb-Yeti.analog-stereo\necho_cancel_capture\n"

        result = resolve_source(
            ["echo_cancel_capture", "alsa_input.usb-Yeti.analog-stereo"],
            pw_cli=_runner,
            fallback="default",
        )
        assert result == "echo_cancel_capture"

    def test_falls_through_when_first_missing(self) -> None:
        """First candidate not in the graph → second wins."""

        def _runner() -> str:
            return "alsa_input.usb-Yeti.analog-stereo\n"

        result = resolve_source(
            ["echo_cancel_capture", "alsa_input.usb-Yeti.analog-stereo"],
            pw_cli=_runner,
            fallback="default",
        )
        assert result == "alsa_input.usb-Yeti.analog-stereo"

    def test_uses_fallback_when_all_absent(self) -> None:
        """No candidate matches the live graph → returns fallback."""

        def _runner() -> str:
            return "some_other_node\nanother_node\n"

        result = resolve_source(
            ["echo_cancel_capture"],
            pw_cli=_runner,
            fallback="alsa_input.fallback",
        )
        assert result == "alsa_input.fallback"

    def test_pw_cli_failure_uses_fallback(self) -> None:
        """A pw-cli runner that raises must NOT crash the resolver —
        fall back so the daimonion keeps starting."""

        def _runner() -> str:
            raise RuntimeError("pw-cli not available")

        result = resolve_source(
            ["echo_cancel_capture"],
            pw_cli=_runner,
            fallback="alsa_input.fallback",
        )
        assert result == "alsa_input.fallback"


# ── Lifecycle state ──────────────────────────────────────────────────


class TestLifecycle:
    def test_starts_inactive(self) -> None:
        s = AudioInputStream(source_name="test-source")
        assert s.is_active is False

    def test_stop_when_inactive_is_safe(self) -> None:
        """stop() on a never-started stream must not raise — the
        daimonion shutdown path calls stop() unconditionally."""
        s = AudioInputStream(source_name="test-source")
        s.stop()  # No assertion needed — must not raise.
        assert s.is_active is False

    def test_double_stop_idempotent(self) -> None:
        s = AudioInputStream(source_name="test-source")
        s.stop()
        s.stop()  # Second stop must not raise.
        assert s.is_active is False

    def test_start_outside_event_loop_handles_failure(self) -> None:
        """start() needs a running asyncio loop. Outside one, it must
        log + leave _active False rather than crashing."""
        s = AudioInputStream(source_name="test-source")
        # Calling start() with no asyncio loop running falls into the
        # exception path which sets _active=False.
        s.start()
        assert s.is_active is False

    def test_start_inside_event_loop_sets_active(self) -> None:
        """When called from within an asyncio loop, start() spawns the
        reader task and flips _active=True."""

        async def _go() -> bool:
            s = AudioInputStream(source_name="test-source")
            s.start()
            active = s.is_active
            s.stop()
            return active

        assert asyncio.run(_go()) is True


# ── Overrun streak telemetry ─────────────────────────────────────────


class TestOverrunTelemetry:
    """Drop streaks must be quantified: the old single 'queue full'
    warning gave no count or duration, making soak evidence ambiguous
    (audit SS3 'mic integrity' row)."""

    def test_streak_start_logs_once(self, caplog: pytest.LogCaptureFixture) -> None:
        s = AudioInputStream(source_name="test-source", queue_maxsize=2)
        with caplog.at_level("WARNING", logger="agents.hapax_daimonion.audio_input"):
            s._enqueue_frame(b"a")
            s._enqueue_frame(b"b")
            s._enqueue_frame(b"c")  # dropped — streak start
            s._enqueue_frame(b"d")  # dropped — same streak, no extra log
        full_warnings = [r for r in caplog.records if "queue full" in r.getMessage()]
        assert len(full_warnings) == 1

    def test_recovery_logs_dropped_count_and_audio_seconds(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        s = AudioInputStream(source_name="test-source", frame_ms=30, queue_maxsize=2)
        s._enqueue_frame(b"a")
        s._enqueue_frame(b"b")
        s._enqueue_frame(b"c")  # dropped
        s._enqueue_frame(b"d")  # dropped
        s._queue.get_nowait()
        with caplog.at_level("WARNING", logger="agents.hapax_daimonion.audio_input"):
            s._enqueue_frame(b"e")  # fits — streak ends
        recovery = [r.getMessage() for r in caplog.records if "recovered" in r.getMessage()]
        assert len(recovery) == 1
        assert "dropped 2 frames" in recovery[0]
        assert "0.1s of audio" in recovery[0]  # 2 × 30ms rounded

    def test_total_dropped_accumulates_across_streaks(self) -> None:
        s = AudioInputStream(source_name="test-source", queue_maxsize=1)
        s._enqueue_frame(b"a")
        s._enqueue_frame(b"b")  # dropped (streak 1)
        s._queue.get_nowait()
        s._enqueue_frame(b"c")  # recovery
        s._enqueue_frame(b"d")  # dropped (streak 2)
        assert s.total_dropped_frames == 2


# ── Source name override ─────────────────────────────────────────────


class TestSourceOverride:
    def test_explicit_source_name_overrides_resolver(self) -> None:
        """Constructor-supplied source_name bypasses _resolve_default_source."""
        s = AudioInputStream(source_name="alsa_input.test-explicit")
        # Internal field — pinning here so a future rename of the
        # private attribute is caught.
        assert s._source_name == "alsa_input.test-explicit"

    def test_none_source_name_triggers_resolver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HAPAX_AEC_ACTIVE", "1")
        s = AudioInputStream(source_name=None)
        assert s._source_name == "echo_cancel_capture"


# ── Registry-derived stt.ear priority (voice-p2-perception-registry) ────


class TestSttSourcePriority:
    def test_derived_from_registry_respeaker_first(self) -> None:
        from agents.hapax_daimonion import audio_input as ai_mod

        priority = ai_mod.stt_source_priority()
        assert priority[0].startswith("alsa_input.usb-Seeed_Studio_reSpeaker_XVF3800")
        assert "echo_cancel_capture" in priority
        assert any("Yeti" in s for s in priority)

    def test_falls_back_to_legacy_constants_without_registry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agents.hapax_daimonion import audio_input as ai_mod

        monkeypatch.setattr(ai_mod, "load_default_registry", lambda: None)
        assert ai_mod.stt_source_priority() == ai_mod._LEGACY_SOURCE_PRIORITY

    def test_falls_back_when_subscription_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from agents.hapax_daimonion import audio_input as ai_mod
        from shared.perception_registry import PerceptionRegistry

        empty = PerceptionRegistry(schema_version=1)
        monkeypatch.setattr(ai_mod, "load_default_registry", lambda: empty)
        assert ai_mod.stt_source_priority() == ai_mod._LEGACY_SOURCE_PRIORITY

    def test_module_default_matches_function(self) -> None:
        from agents.hapax_daimonion import audio_input as ai_mod

        assert ai_mod.stt_source_priority() == ai_mod.DEFAULT_SOURCE_PRIORITY


class TestConfigDefaultFromRegistry:
    def test_config_default_is_registry_priority(self) -> None:
        from agents.hapax_daimonion import audio_input as ai_mod
        from agents.hapax_daimonion.config import DaimonionConfig

        assert DaimonionConfig().audio_input_source == ai_mod.stt_source_priority()
