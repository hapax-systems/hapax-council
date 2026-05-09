"""Tests for the audio self-perception loop (avsdlc-001).

Covers:
- StimmungCollector.update_audio_self_perception() dimension routing
- _update_audio_self_perception() SHM reader in stimmung_methods.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from shared.stimmung import StimmungCollector

# ── StimmungCollector.update_audio_self_perception ──────────────────────────


class TestUpdateAudioSelfPerception:
    def _collector(self) -> StimmungCollector:
        return StimmungCollector(enable_exploration=False)

    def test_healthy_broadcast_records_zero_health(self) -> None:
        c = self._collector()
        c.update_audio_self_perception(
            rms_dbfs=-20.0,
            silence_ratio=0.02,
            witness_age_s=2.0,
        )
        snap = c.snapshot()
        assert snap.health.value == 0.0

    def test_silent_broadcast_degrades_health(self) -> None:
        c = self._collector()
        c.update_audio_self_perception(
            rms_dbfs=-60.0,
            silence_ratio=0.98,
            witness_age_s=2.0,
        )
        snap = c.snapshot()
        assert snap.health.value >= 0.5

    def test_stale_witness_degrades_health(self) -> None:
        c = self._collector()
        c.update_audio_self_perception(witness_age_s=45.0)
        snap = c.snapshot()
        assert snap.health.value >= 0.5

    def test_dead_witness_maximizes_health_pressure(self) -> None:
        c = self._collector()
        c.update_audio_self_perception(witness_age_s=200.0)
        snap = c.snapshot()
        assert snap.health.value == 1.0

    def test_witness_error_degrades_health(self) -> None:
        c = self._collector()
        c.update_audio_self_perception(witness_error="sink not found")
        snap = c.snapshot()
        assert snap.health.value >= 0.7

    def test_clipping_records_high_error_rate(self) -> None:
        c = self._collector()
        c.update_audio_self_perception(
            rms_dbfs=-5.0,
            silence_ratio=0.0,
            witness_age_s=1.0,
            classification="CLIPPING",
        )
        snap = c.snapshot()
        assert snap.error_rate.value >= 0.8

    def test_noise_records_moderate_error_rate(self) -> None:
        c = self._collector()
        c.update_audio_self_perception(
            rms_dbfs=-30.0,
            silence_ratio=0.1,
            witness_age_s=1.0,
            classification="NOISE",
        )
        snap = c.snapshot()
        assert snap.error_rate.value >= 0.4

    def test_music_voice_no_error_contribution(self) -> None:
        c = self._collector()
        c.update_audio_self_perception(
            rms_dbfs=-20.0,
            silence_ratio=0.02,
            witness_age_s=1.0,
            classification="MUSIC_VOICE",
        )
        snap = c.snapshot()
        assert snap.error_rate.value == 0.0

    def test_silent_classification_with_high_silence_ratio(self) -> None:
        c = self._collector()
        c.update_audio_self_perception(
            silence_ratio=0.99,
            witness_age_s=1.0,
            classification="SILENT",
        )
        snap = c.snapshot()
        assert snap.error_rate.value >= 0.3

    def test_case_insensitive_classification(self) -> None:
        c = self._collector()
        c.update_audio_self_perception(
            witness_age_s=1.0,
            classification="clipping",
        )
        snap = c.snapshot()
        assert snap.error_rate.value >= 0.8


# ── VLA SHM reader ──────────────────────────────────────────────────────────


class TestVlaAudioSelfPerceptionReader:
    def test_reads_egress_loopback(self, tmp_path: Path) -> None:
        witness = {
            "checked_at": datetime.now(UTC).isoformat(),
            "rms_dbfs": -25.0,
            "peak_dbfs": -12.0,
            "silence_ratio": 0.03,
            "window_seconds": 5.0,
            "target_sink": "hapax-broadcast-normalized",
            "error": None,
        }
        loopback_path = tmp_path / "egress-loopback.json"
        loopback_path.write_text(json.dumps(witness))

        from agents.visual_layer_aggregator import stimmung_methods as sm

        agg = MagicMock()
        agg._stimmung_collector = MagicMock()

        with (
            patch.object(sm, "_EGRESS_LOOPBACK_PATH", loopback_path),
            patch.object(sm, "_SIGNAL_FLOW_PATH", tmp_path / "nonexistent.json"),
        ):
            sm._update_audio_self_perception(agg)

        agg._stimmung_collector.update_audio_self_perception.assert_called_once()
        kwargs = agg._stimmung_collector.update_audio_self_perception.call_args[1]
        assert kwargs["rms_dbfs"] == -25.0
        assert kwargs["silence_ratio"] == 0.03
        assert kwargs["witness_error"] is None
        assert kwargs["witness_age_s"] < 5.0

    def test_reads_signal_flow_classification(self, tmp_path: Path) -> None:
        flow = {
            "stages": {
                "hapax-broadcast-normalized": {"classification": "MUSIC_VOICE"},
                "hapax-obs-broadcast-remap": {"classification": "CLIPPING"},
            }
        }
        flow_path = tmp_path / "signal-flow.json"
        flow_path.write_text(json.dumps(flow))

        witness = {
            "checked_at": datetime.now(UTC).isoformat(),
            "rms_dbfs": -20.0,
            "silence_ratio": 0.01,
            "error": None,
        }
        loopback_path = tmp_path / "egress-loopback.json"
        loopback_path.write_text(json.dumps(witness))

        from agents.visual_layer_aggregator import stimmung_methods as sm

        agg = MagicMock()
        agg._stimmung_collector = MagicMock()

        with (
            patch.object(sm, "_EGRESS_LOOPBACK_PATH", loopback_path),
            patch.object(sm, "_SIGNAL_FLOW_PATH", flow_path),
        ):
            sm._update_audio_self_perception(agg)

        kwargs = agg._stimmung_collector.update_audio_self_perception.call_args[1]
        assert kwargs["classification"] == "CLIPPING"

    def test_prefers_obs_remap_over_normalized(self, tmp_path: Path) -> None:
        flow = {
            "stages": {
                "hapax-broadcast-normalized": {"classification": "MUSIC_VOICE"},
                "hapax-obs-broadcast-remap": {"classification": "NOISE"},
            }
        }
        flow_path = tmp_path / "signal-flow.json"
        flow_path.write_text(json.dumps(flow))

        from agents.visual_layer_aggregator import stimmung_methods as sm

        agg = MagicMock()
        agg._stimmung_collector = MagicMock()

        with (
            patch.object(sm, "_EGRESS_LOOPBACK_PATH", tmp_path / "nonexistent.json"),
            patch.object(sm, "_SIGNAL_FLOW_PATH", flow_path),
        ):
            sm._update_audio_self_perception(agg)

        kwargs = agg._stimmung_collector.update_audio_self_perception.call_args[1]
        assert kwargs["classification"] == "NOISE"

    def test_missing_files_still_calls_update(self, tmp_path: Path) -> None:
        from agents.visual_layer_aggregator import stimmung_methods as sm

        agg = MagicMock()
        agg._stimmung_collector = MagicMock()

        with (
            patch.object(sm, "_EGRESS_LOOPBACK_PATH", tmp_path / "nope1.json"),
            patch.object(sm, "_SIGNAL_FLOW_PATH", tmp_path / "nope2.json"),
        ):
            sm._update_audio_self_perception(agg)

        agg._stimmung_collector.update_audio_self_perception.assert_called_once()
        kwargs = agg._stimmung_collector.update_audio_self_perception.call_args[1]
        assert kwargs["witness_age_s"] >= 900
        assert kwargs["classification"] == ""

    def test_witness_with_error_passes_through(self, tmp_path: Path) -> None:
        witness = {
            "checked_at": datetime.now(UTC).isoformat(),
            "rms_dbfs": 0.0,
            "silence_ratio": 0.0,
            "error": "sink hapax-broadcast-normalized not found",
        }
        loopback_path = tmp_path / "egress-loopback.json"
        loopback_path.write_text(json.dumps(witness))

        from agents.visual_layer_aggregator import stimmung_methods as sm

        agg = MagicMock()
        agg._stimmung_collector = MagicMock()

        with (
            patch.object(sm, "_EGRESS_LOOPBACK_PATH", loopback_path),
            patch.object(sm, "_SIGNAL_FLOW_PATH", tmp_path / "nope.json"),
        ):
            sm._update_audio_self_perception(agg)

        kwargs = agg._stimmung_collector.update_audio_self_perception.call_args[1]
        assert kwargs["witness_error"] == "sink hapax-broadcast-normalized not found"
