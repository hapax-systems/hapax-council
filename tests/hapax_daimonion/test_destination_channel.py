"""Tests for CPAL TTS destination channel classification.

Covers :mod:`agents.hapax_daimonion.cpal.destination_channel`:

* Rule-matrix for classification (sidechat / debug / TEXTMODE / default).
* Target resolution (routing active → split sinks; routing off → legacy).
* Prometheus counter increments per classified utterance.
* Feature flag ``HAPAX_TTS_DESTINATION_ROUTING_ACTIVE`` toggles routing.

Each test is self-contained (no shared conftest fixtures) and constructs
impingement-like objects inline. The Pydantic ``Impingement`` model is
used where its validation matters (typed source / content shape); plain
``SimpleNamespace`` stubs are used where classification is the only
concern.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from agents.hapax_daimonion.cpal import destination_channel
from agents.hapax_daimonion.cpal.destination_channel import (
    DEFAULT_TARGET_ENV,
    DESTINATION_ROUTING_ENV,
    LIVESTREAM_SINK,
    PRIVATE_SINK,
    DestinationChannel,
    classify_and_record,
    classify_destination,
    is_routing_active,
    resolve_target,
)
from shared.impingement import Impingement, ImpingementType
from shared.voice_register import VoiceRegister

# --- Classification rule matrix ---------------------------------------------


class TestClassification:
    """Pin the rule matrix from the module docstring."""

    def test_sidechat_source_routes_private(self):
        imp = Impingement(
            timestamp=time.time(),
            source="operator.sidechat",
            type=ImpingementType.PATTERN_MATCH,
            strength=0.9,
            content={
                "narrative": "remind me to call mom",
                "channel": "sidechat",
                "msg_id": "abc",
                "role": "operator",
            },
            interrupt_token="operator_sidechat",
        )
        assert classify_destination(imp) == DestinationChannel.PRIVATE

    def test_sidechat_channel_content_routes_private(self):
        """Even without the canonical source, channel=sidechat diverts private."""
        imp = SimpleNamespace(
            source="some.other.source",
            content={"channel": "sidechat", "narrative": "note"},
        )
        assert classify_destination(imp) == DestinationChannel.PRIVATE

    def test_director_narrative_routes_livestream(self):
        """No channel / no debug kind / no sidechat source → livestream."""
        imp = Impingement(
            timestamp=time.time(),
            source="director.narrative",
            type=ImpingementType.STATISTICAL_DEVIATION,
            strength=0.6,
            content={"metric": "tempo_shift", "narrative": "the beat opened up"},
        )
        assert classify_destination(imp) == DestinationChannel.LIVESTREAM

    def test_debug_kind_routes_private(self):
        """kind='debug' diverts private even without sidechat provenance."""
        imp = SimpleNamespace(
            source="daimonion.internal",
            content={"kind": "debug", "narrative": "diagnostic message"},
        )
        assert classify_destination(imp) == DestinationChannel.PRIVATE

    def test_textmode_without_sidechat_routes_livestream(self):
        """Register alone never flips destination — sidechat origin must be present."""
        imp = Impingement(
            timestamp=time.time(),
            source="homage.bitchx.announce",
            type=ImpingementType.PATTERN_MATCH,
            strength=0.7,
            content={"narrative": "textmode salutation"},
        )
        assert (
            classify_destination(imp, voice_register=VoiceRegister.TEXTMODE)
            == DestinationChannel.LIVESTREAM
        )

    def test_textmode_with_sidechat_routes_private(self):
        """TEXTMODE + sidechat provenance → private (rules 1/2 catch it)."""
        imp = Impingement(
            timestamp=time.time(),
            source="operator.sidechat",
            type=ImpingementType.PATTERN_MATCH,
            strength=0.9,
            content={
                "narrative": "typing reply",
                "channel": "sidechat",
                "msg_id": "deadbeef",
                "role": "operator",
            },
            interrupt_token="operator_sidechat",
        )
        assert (
            classify_destination(imp, voice_register=VoiceRegister.TEXTMODE)
            == DestinationChannel.PRIVATE
        )

    def test_none_impingement_is_livestream(self):
        """Defensive default when something upstream passes None."""
        assert classify_destination(None) == DestinationChannel.LIVESTREAM

    def test_missing_content_is_livestream(self):
        """Object without content attribute still classifies safely."""
        imp = SimpleNamespace(source="")
        assert classify_destination(imp) == DestinationChannel.LIVESTREAM


# --- Target resolution ------------------------------------------------------


class TestTargetResolution:
    def test_livestream_uses_env_target_when_routing_active(self, monkeypatch):
        monkeypatch.setenv(DEFAULT_TARGET_ENV, "hapax-livestream")
        monkeypatch.delenv(DESTINATION_ROUTING_ENV, raising=False)
        assert resolve_target(DestinationChannel.LIVESTREAM) == "hapax-livestream"

    def test_livestream_falls_back_to_canonical_sink(self, monkeypatch):
        monkeypatch.delenv(DEFAULT_TARGET_ENV, raising=False)
        monkeypatch.delenv(DESTINATION_ROUTING_ENV, raising=False)
        assert resolve_target(DestinationChannel.LIVESTREAM) == LIVESTREAM_SINK

    def test_private_always_targets_private_sink_when_active(self, monkeypatch):
        monkeypatch.setenv(DEFAULT_TARGET_ENV, "hapax-livestream")
        monkeypatch.delenv(DESTINATION_ROUTING_ENV, raising=False)
        assert resolve_target(DestinationChannel.PRIVATE) == PRIVATE_SINK

    def test_flag_off_forces_everything_to_default(self, monkeypatch):
        monkeypatch.setenv(DESTINATION_ROUTING_ENV, "0")
        monkeypatch.setenv(DEFAULT_TARGET_ENV, "some-legacy-sink")
        assert resolve_target(DestinationChannel.LIVESTREAM) == "some-legacy-sink"
        # Private collapses to legacy target too — that's the whole point
        # of the kill-switch.
        assert resolve_target(DestinationChannel.PRIVATE) == "some-legacy-sink"

    def test_flag_off_without_target_returns_none(self, monkeypatch):
        monkeypatch.setenv(DESTINATION_ROUTING_ENV, "0")
        monkeypatch.delenv(DEFAULT_TARGET_ENV, raising=False)
        assert resolve_target(DestinationChannel.LIVESTREAM) is None
        assert resolve_target(DestinationChannel.PRIVATE) is None

    @pytest.mark.parametrize(
        "raw,expected_active",
        [
            (None, True),
            ("", True),
            ("1", True),
            ("0", False),
            (" 0 ", False),
            ("true", True),  # anything non-"0" is active; conservative default
        ],
    )
    def test_routing_flag_parsing(self, monkeypatch, raw, expected_active):
        if raw is None:
            monkeypatch.delenv(DESTINATION_ROUTING_ENV, raising=False)
        else:
            monkeypatch.setenv(DESTINATION_ROUTING_ENV, raw)
        assert is_routing_active() is expected_active


# --- Counter increments -----------------------------------------------------


class TestCounter:
    def test_classify_and_record_increments_per_destination(self, monkeypatch):
        """Counter tracks destination of each classified utterance."""
        try:
            from prometheus_client import REGISTRY
        except ImportError:
            pytest.skip("prometheus_client not available")

        def _sample(destination: str) -> float:
            # REGISTRY.get_sample_value returns None if the sample is absent;
            # pre-init in _DestinationCounter ensures it's 0.0 after import.
            val = REGISTRY.get_sample_value(
                "hapax_tts_destination_total",
                {"destination": destination},
            )
            return val if val is not None else 0.0

        baseline_live = _sample("livestream")
        baseline_priv = _sample("private")

        # One livestream utterance.
        livestream_imp = SimpleNamespace(source="director.narrative", content={"metric": "x"})
        assert classify_and_record(livestream_imp) == DestinationChannel.LIVESTREAM

        # Two private utterances (sidechat + debug).
        sidechat_imp = SimpleNamespace(
            source="operator.sidechat",
            content={"channel": "sidechat", "narrative": "ping"},
        )
        debug_imp = SimpleNamespace(
            source="daimonion.internal",
            content={"kind": "debug", "narrative": "diagnostic"},
        )
        assert classify_and_record(sidechat_imp) == DestinationChannel.PRIVATE
        assert classify_and_record(debug_imp) == DestinationChannel.PRIVATE

        assert _sample("livestream") == pytest.approx(baseline_live + 1)
        assert _sample("private") == pytest.approx(baseline_priv + 2)


# --- Module-level guarantees -------------------------------------------------


class TestModuleShape:
    def test_destination_values_are_stable(self):
        """Label values must stay wire-stable for Grafana dashboards."""
        assert DestinationChannel.LIVESTREAM.value == "livestream"
        assert DestinationChannel.PRIVATE.value == "private"

    def test_sink_names_match_pipewire_config(self):
        """Canonical sink names must match the hapax-stream-split.conf file."""
        assert LIVESTREAM_SINK == "hapax-livestream"
        assert PRIVATE_SINK == "hapax-private"

    def test_no_private_payload_leaks_into_log(self, caplog, monkeypatch):
        """Classification log must not include narrative / body / operator text."""
        monkeypatch.delenv(DESTINATION_ROUTING_ENV, raising=False)
        imp = Impingement(
            timestamp=time.time(),
            source="operator.sidechat",
            type=ImpingementType.PATTERN_MATCH,
            strength=0.9,
            content={
                "narrative": "REDACTED_SECRET_NOTE",
                "channel": "sidechat",
                "msg_id": "abc",
                "role": "operator",
            },
            interrupt_token="operator_sidechat",
        )
        with caplog.at_level("INFO", logger=destination_channel.log.name):
            classify_and_record(imp)
        joined = "\n".join(record.getMessage() for record in caplog.records)
        assert "REDACTED_SECRET_NOTE" not in joined
