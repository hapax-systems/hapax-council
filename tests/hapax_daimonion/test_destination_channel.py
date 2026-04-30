"""Tests for CPAL TTS destination channel classification.

Covers :mod:`agents.hapax_daimonion.cpal.destination_channel`:

* Rule-matrix for classification (sidechat / debug / TEXTMODE / default).
* Target resolution through the semantic no-default-fallback router.
* Prometheus counter increments per classified utterance.
* Feature flag ``HAPAX_TTS_DESTINATION_ROUTING_ACTIVE`` parsing remains stable.

Each test is self-contained (no shared conftest fixtures) and constructs
impingement-like objects inline. The Pydantic ``Impingement`` model is
used where its validation matters (typed source / content shape); plain
``SimpleNamespace`` stubs are used where classification is the only
concern.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.hapax_daimonion.cpal import destination_channel
from agents.hapax_daimonion.cpal.destination_channel import (
    BROADCAST_MEDIA_ROLE,
    DEFAULT_TARGET_ENV,
    DESTINATION_ROUTING_ENV,
    LIVESTREAM_SINK,
    PRIVATE_MEDIA_ROLE,
    PRIVATE_SINK,
    DestinationChannel,
    classify_and_record,
    classify_destination,
    is_routing_active,
    resolve_role,
    resolve_route,
    resolve_target,
)
from shared.impingement import Impingement, ImpingementType
from shared.voice_output_router import VoiceRouteState
from shared.voice_register import VoiceRegister


def _write_private_status(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "bridge_nodes_present": True,
                "exact_target_present": True,
                "fallback_policy": "no_default_fallback",
                "operator_visible_reason": (
                    "Exact private monitor target and fail-closed bridge are present."
                ),
                "reason_code": "exact_private_monitor_bound",
                "sanitized": True,
                "state": "ready",
                "target_ref": "audio.yeti_monitor",
            }
        ),
        encoding="utf-8",
    )


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
    def test_livestream_ignores_legacy_env_target_when_routing_active(self, monkeypatch):
        monkeypatch.setenv(DEFAULT_TARGET_ENV, "hapax-livestream")
        monkeypatch.delenv(DESTINATION_ROUTING_ENV, raising=False)
        assert resolve_target(DestinationChannel.LIVESTREAM) == "hapax-voice-fx-capture"

    def test_livestream_binds_to_policy_target_without_env(self, monkeypatch):
        monkeypatch.delenv(DEFAULT_TARGET_ENV, raising=False)
        monkeypatch.delenv(DESTINATION_ROUTING_ENV, raising=False)
        assert resolve_target(DestinationChannel.LIVESTREAM) == "hapax-voice-fx-capture"

    def test_private_targets_private_sink_when_exact_monitor_ready(self, monkeypatch, tmp_path):
        monkeypatch.setenv(DEFAULT_TARGET_ENV, "hapax-livestream")
        monkeypatch.delenv(DESTINATION_ROUTING_ENV, raising=False)
        status_path = tmp_path / "private-monitor-target.json"
        _write_private_status(status_path)

        result = resolve_route(DestinationChannel.PRIVATE, private_monitor_status_path=status_path)

        assert result.state is VoiceRouteState.ACCEPTED
        assert result.target_binding is not None
        assert result.target_binding.target == PRIVATE_SINK

    def test_flag_off_does_not_fallback_routes_to_default(self, monkeypatch, tmp_path):
        monkeypatch.setenv(DESTINATION_ROUTING_ENV, "0")
        monkeypatch.setenv(DEFAULT_TARGET_ENV, "some-legacy-sink")
        assert resolve_target(DestinationChannel.LIVESTREAM) == "hapax-voice-fx-capture"
        result = resolve_route(
            DestinationChannel.PRIVATE,
            private_monitor_status_path=tmp_path / "missing.json",
        )
        assert result.state is VoiceRouteState.BLOCKED
        assert result.target_binding is not None
        assert result.target_binding.target is None

    def test_flag_off_without_target_returns_no_default_for_private(self, monkeypatch, tmp_path):
        monkeypatch.setenv(DESTINATION_ROUTING_ENV, "0")
        monkeypatch.delenv(DEFAULT_TARGET_ENV, raising=False)
        assert resolve_target(DestinationChannel.LIVESTREAM) == "hapax-voice-fx-capture"
        result = resolve_route(
            DestinationChannel.PRIVATE,
            private_monitor_status_path=tmp_path / "missing.json",
        )
        assert result.state is VoiceRouteState.BLOCKED
        assert result.target_binding is not None
        assert result.target_binding.target is None

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


# --- resolve_role (cc-task voice-broadcast-role-split) ----------------------


class TestResolveRole:
    """``resolve_role`` maps each :class:`DestinationChannel` to the
    pw-cat ``--media-role`` value that selects the matching wireplumber
    role-based loopback. Pin the mapping so an accidental swap doesn't
    quietly route private cognition to broadcast (or vice-versa)."""

    def test_private_resolves_to_assistant(self) -> None:
        assert resolve_role(DestinationChannel.PRIVATE) == "Assistant"
        assert resolve_role(DestinationChannel.PRIVATE) == PRIVATE_MEDIA_ROLE

    def test_livestream_resolves_to_broadcast(self) -> None:
        assert resolve_role(DestinationChannel.LIVESTREAM) == "Broadcast"
        assert resolve_role(DestinationChannel.LIVESTREAM) == BROADCAST_MEDIA_ROLE

    def test_role_constants_are_distinct(self) -> None:
        """If somebody accidentally aliases one to the other, the
        wireplumber loopback can't tell broadcast from private and the
        leak returns. Pin the distinctness."""
        assert PRIVATE_MEDIA_ROLE != BROADCAST_MEDIA_ROLE
