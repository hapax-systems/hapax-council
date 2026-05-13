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
    _BROADCAST_ELIGIBLE_ROLES,
    BROADCAST_BIAS_ENV,
    BROADCAST_MEDIA_ROLE,
    DEFAULT_TARGET_ENV,
    DESTINATION_ROUTING_ENV,
    LIVESTREAM_SINK,
    PRIVATE_MEDIA_ROLE,
    PRIVATE_SINK,
    DestinationChannel,
    _is_broadcast_bias_enabled,
    classify_and_record,
    classify_destination,
    is_routing_active,
    resolve_playback_decision,
    resolve_role,
    resolve_route,
    resolve_target,
)
from shared.broadcast_audio_health import (
    BroadcastAudioHealth,
    BroadcastAudioStatus,
    write_broadcast_audio_health_state,
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
                "target_ref": "audio.s4_private_monitor",
            }
        ),
        encoding="utf-8",
    )


def _write_broadcast_health(path: Path, *, safe: bool) -> None:
    write_broadcast_audio_health_state(
        BroadcastAudioHealth(
            safe=safe,
            status=BroadcastAudioStatus.SAFE if safe else BroadcastAudioStatus.UNSAFE,
            checked_at="2026-04-30T02:50:00Z",
            freshness_s=0.0,
            evidence={"fixture": True},
        ),
        path=path,
    )


def _broadcast_imp(*, now: float) -> SimpleNamespace:
    return SimpleNamespace(
        source="director.narrative",
        content={
            "public_broadcast_intent": True,
            "programme_authorization": {
                "authorized": True,
                "authorized_at": now,
                "programme_id": "programme:test-public",
                "evidence_ref": "programme:test-public:broadcast-voice",
            },
            "narrative": "Authorized public narration.",
        },
    )


def _bridge_broadcast_imp(*, now: float, source: str = "autonomous_narrative") -> SimpleNamespace:
    return SimpleNamespace(
        source=source,
        content={
            "narrative": "Bridge-authorized public narration.",
            "public_broadcast_intent": True,
            "destination": "broadcast",
            "bridge_outcome": "public_action_proposal",
            "route_posture": "broadcast_authorized",
            "claim_ceiling": "public_gate_required",
            "programme_id": "programme:test-public",
            "programme_authorization_ref": "programme:programme:test-public",
            "programme_authorization": {
                "authorized": True,
                "authorized_at": now,
                "expires_at": now + 90.0,
                "programme_id": "programme:test-public",
                "evidence_ref": "programme:programme:test-public",
            },
        },
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

    def test_director_narrative_defaults_private(self):
        """No explicit broadcast intent now resolves private/drop, not livestream."""
        imp = Impingement(
            timestamp=time.time(),
            source="director.narrative",
            type=ImpingementType.STATISTICAL_DEVIATION,
            strength=0.6,
            content={"metric": "tempo_shift", "narrative": "the beat opened up"},
        )
        assert classify_destination(imp) == DestinationChannel.PRIVATE

    def test_explicit_broadcast_intent_routes_livestream_for_later_gate(self):
        imp = SimpleNamespace(
            source="autonomous_narrative",
            content={"public_broadcast_intent": True, "narrative": "public voice"},
        )
        assert classify_destination(imp) == DestinationChannel.LIVESTREAM

    def test_private_context_wins_over_public_looking_token(self):
        imp = SimpleNamespace(
            source="operator.sidechat",
            content={
                "channel": "sidechat",
                "public_broadcast_intent": True,
                "narrative": "still private",
            },
        )
        assert classify_destination(imp) == DestinationChannel.PRIVATE

    def test_debug_kind_routes_private(self):
        """kind='debug' diverts private even without sidechat provenance."""
        imp = SimpleNamespace(
            source="daimonion.internal",
            content={"kind": "debug", "narrative": "diagnostic message"},
        )
        assert classify_destination(imp) == DestinationChannel.PRIVATE

    def test_textmode_without_sidechat_defaults_private(self):
        """Register alone never authorizes public/broadcast voice."""
        imp = Impingement(
            timestamp=time.time(),
            source="homage.bitchx.announce",
            type=ImpingementType.PATTERN_MATCH,
            strength=0.7,
            content={"narrative": "textmode salutation"},
        )
        assert (
            classify_destination(imp, voice_register=VoiceRegister.TEXTMODE)
            == DestinationChannel.PRIVATE
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

    def test_none_impingement_is_private(self):
        """Defensive default when something upstream passes None."""
        assert classify_destination(None) == DestinationChannel.PRIVATE

    def test_missing_content_is_private(self):
        """Object without content attribute still classifies safely."""
        imp = SimpleNamespace(source="")
        assert classify_destination(imp) == DestinationChannel.PRIVATE


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


# --- Playback hard-stop gate -------------------------------------------------


class TestPlaybackDecision:
    def test_blue_yeti_operator_call_resolves_private_when_monitor_ready(self, tmp_path):
        now = time.time()
        status_path = tmp_path / "private-monitor-target.json"
        _write_private_status(status_path)
        imp = SimpleNamespace(
            source="operator.microphone.blue_yeti",
            content={"wake_word": "hapax", "input_device": "blue_yeti"},
        )

        decision = resolve_playback_decision(
            imp,
            private_monitor_status_path=status_path,
            now=now,
        )

        assert decision.allowed is True
        assert decision.destination is DestinationChannel.PRIVATE
        assert decision.target == PRIVATE_SINK
        assert decision.media_role == PRIVATE_MEDIA_ROLE

    def test_sidechat_resolves_private_when_monitor_ready(self, tmp_path):
        now = time.time()
        status_path = tmp_path / "private-monitor-target.json"
        _write_private_status(status_path)
        imp = SimpleNamespace(
            source="operator.sidechat",
            content={"channel": "sidechat", "narrative": "private reply"},
        )

        decision = resolve_playback_decision(
            imp,
            private_monitor_status_path=status_path,
            now=now,
        )

        assert decision.allowed is True
        assert decision.destination is DestinationChannel.PRIVATE
        assert decision.target == PRIVATE_SINK

    def test_autonomous_narration_with_bias_stays_private_without_bridge_metadata(
        self, monkeypatch, tmp_path
    ):
        """Broadcast bias alone no longer mints public playback intent."""
        monkeypatch.delenv(BROADCAST_BIAS_ENV, raising=False)
        monkeypatch.setattr(
            "agents.hapax_daimonion.cpal.destination_channel._programme_authorizes_broadcast",
            lambda: True,
        )
        private_status_path = tmp_path / "private-monitor-status.json"
        _write_private_status(private_status_path)
        imp = SimpleNamespace(
            source="autonomous_narrative",
            content={"narrative": "No public contract."},
        )

        decision = resolve_playback_decision(
            imp,
            private_monitor_status_path=private_status_path,
            now=1_800_000_000.0,
        )

        assert decision.allowed is False
        assert decision.destination is DestinationChannel.PRIVATE
        assert decision.reason_code == "private_monitor_status_stale"
        assert decision.safety_gate["explicit_broadcast_intent"] is False

    def test_old_broadcast_bias_soft_prior_blocks_without_bridge_metadata(self, tmp_path):
        """The former runner-minted payload cannot reach allowed LIVESTREAM."""
        now = time.time()
        health_path = tmp_path / "audio-safe-for-broadcast.json"
        _write_broadcast_health(health_path, safe=True)
        imp = SimpleNamespace(
            source="autonomous_narrative",
            content={
                "narrative": "Old soft-prior payload.",
                "voice_output_destination": "broadcast",
                "broadcast_intent": True,
                "programme_authorization": {
                    "authorized": True,
                    "broadcast_voice_authorized": True,
                    "authorized_at": now,
                    "programme_id": "programme:test-public",
                    "evidence_ref": "broadcast_bias_soft_prior",
                },
            },
        )

        decision = resolve_playback_decision(
            imp,
            broadcast_audio_health_path=health_path,
            now=now,
        )

        assert decision.allowed is False
        assert decision.destination is DestinationChannel.LIVESTREAM
        assert decision.reason_code == "bridge_metadata_missing"
        assert decision.safety_gate["private_to_public_bridge"]["required"] is True
        assert decision.safety_gate["programme_authorization"]["evidence_ref"] == (
            "broadcast_bias_soft_prior"
        )

    def test_explicit_broadcast_requires_fresh_programme_auth_and_audio_safe(self, tmp_path):
        now = time.time()
        health_path = tmp_path / "audio-safe-for-broadcast.json"
        _write_broadcast_health(health_path, safe=True)

        decision = resolve_playback_decision(
            _broadcast_imp(now=now),
            broadcast_audio_health_path=health_path,
            now=now,
        )

        assert decision.allowed is True
        assert decision.destination is DestinationChannel.LIVESTREAM
        assert decision.reason_code == "broadcast_voice_authorized"
        assert decision.target == "hapax-voice-fx-capture"
        assert decision.media_role == BROADCAST_MEDIA_ROLE
        assert decision.safety_gate["audio_safe_for_broadcast"]["safe"] is True

    def test_explicit_broadcast_blocks_when_audio_safe_for_broadcast_false(self, tmp_path):
        now = time.time()
        health_path = tmp_path / "audio-safe-for-broadcast.json"
        _write_broadcast_health(health_path, safe=False)

        decision = resolve_playback_decision(
            _broadcast_imp(now=now),
            broadcast_audio_health_path=health_path,
            now=now,
        )

        assert decision.allowed is False
        assert decision.destination is DestinationChannel.LIVESTREAM
        assert decision.reason_code == "audio_safe_for_broadcast_false"
        assert decision.target is None

    def test_explicit_broadcast_blocks_without_programme_authorization(self, tmp_path):
        now = time.time()
        health_path = tmp_path / "audio-safe-for-broadcast.json"
        _write_broadcast_health(health_path, safe=True)
        imp = SimpleNamespace(
            source="autonomous_narrative",
            content={"public_broadcast_intent": True, "narrative": "No auth."},
        )

        decision = resolve_playback_decision(
            imp,
            broadcast_audio_health_path=health_path,
            now=now,
        )

        assert decision.allowed is False
        assert decision.reason_code == "programme_authorization_missing"

    def test_valid_bridge_metadata_allows_autonomous_livestream(self, tmp_path):
        now = time.time()
        health_path = tmp_path / "audio-safe-for-broadcast.json"
        _write_broadcast_health(health_path, safe=True)

        decision = resolve_playback_decision(
            _bridge_broadcast_imp(now=now),
            broadcast_audio_health_path=health_path,
            now=now,
        )

        assert decision.allowed is True
        assert decision.destination is DestinationChannel.LIVESTREAM
        assert decision.reason_code == "broadcast_voice_authorized"
        assert decision.safety_gate["private_to_public_bridge"]["authorized"] is True

    def test_bridge_metadata_rejects_soft_prior_programme_ref(self, tmp_path):
        now = time.time()
        health_path = tmp_path / "audio-safe-for-broadcast.json"
        _write_broadcast_health(health_path, safe=True)
        imp = _bridge_broadcast_imp(now=now)
        imp.content["programme_authorization"]["evidence_ref"] = "broadcast_bias_soft_prior"
        imp.content["programme_authorization_ref"] = "broadcast_bias_soft_prior"

        decision = resolve_playback_decision(
            imp,
            broadcast_audio_health_path=health_path,
            now=now,
        )

        assert decision.allowed is False
        assert decision.reason_code == "bridge_programme_authorization_soft_prior"

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

        # One explicitly-public utterance.
        livestream_imp = SimpleNamespace(
            source="director.narrative",
            content={"public_broadcast_intent": True, "metric": "x"},
        )
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


# --- Broadcast bias (candidate only; bridge metadata authorizes public) ------


def _mock_programme(role: str = "work_block", status: str = "active"):
    """Build a minimal Programme-like object for broadcast bias tests."""
    return SimpleNamespace(
        programme_id="programme:test-bias",
        role=SimpleNamespace(value=role),
        status=status,
        parent_show_id="show:test",
    )


class TestBroadcastBias:
    """Pin broadcast bias as a candidate signal, not public intent."""

    def test_flag_enabled_with_active_programme_stays_private_without_bridge(self, monkeypatch):
        """Bias ON + eligible programme still needs bridge-produced metadata."""
        monkeypatch.delenv(BROADCAST_BIAS_ENV, raising=False)
        monkeypatch.setattr(
            "agents.hapax_daimonion.cpal.destination_channel._programme_authorizes_broadcast",
            lambda: True,
        )
        imp = SimpleNamespace(
            source="autonomous_narrative",
            content={"narrative": "The rhythm settles into place."},
        )
        assert classify_destination(imp) == DestinationChannel.PRIVATE

    def test_flag_disabled_routes_private(self, monkeypatch):
        """Bias OFF → autonomous narrative still defaults PRIVATE."""
        monkeypatch.setenv(BROADCAST_BIAS_ENV, "0")
        imp = SimpleNamespace(
            source="autonomous_narrative",
            content={"narrative": "This should stay private."},
        )
        assert classify_destination(imp) == DestinationChannel.PRIVATE

    def test_no_active_programme_routes_private(self, monkeypatch):
        """Bias ON but no programme → fail-closed to PRIVATE."""
        monkeypatch.delenv(BROADCAST_BIAS_ENV, raising=False)
        monkeypatch.setattr(
            "agents.hapax_daimonion.cpal.destination_channel._programme_authorizes_broadcast",
            lambda: False,
        )
        imp = SimpleNamespace(
            source="autonomous_narrative",
            content={"narrative": "No programme context."},
        )
        assert classify_destination(imp) == DestinationChannel.PRIVATE

    def test_listening_role_routes_private(self, monkeypatch):
        """LISTENING role is excluded from broadcast-eligible set."""
        monkeypatch.delenv(BROADCAST_BIAS_ENV, raising=False)
        assert "listening" not in _BROADCAST_ELIGIBLE_ROLES

        # Wire up a mock that returns a listening programme
        from unittest.mock import patch

        with patch(
            "agents.hapax_daimonion.cpal.destination_channel._programme_authorizes_broadcast",
            return_value=False,
        ):
            imp = SimpleNamespace(
                source="autonomous_narrative",
                content={"narrative": "Should not broadcast during listening."},
            )
            assert classify_destination(imp) == DestinationChannel.PRIVATE

    def test_private_risk_overrides_broadcast_bias(self, monkeypatch):
        """Private-risk context always wins, even with bias enabled."""
        monkeypatch.delenv(BROADCAST_BIAS_ENV, raising=False)
        monkeypatch.setattr(
            "agents.hapax_daimonion.cpal.destination_channel._programme_authorizes_broadcast",
            lambda: True,
        )
        imp = SimpleNamespace(
            source="operator.sidechat",
            content={"channel": "sidechat", "narrative": "This is private."},
        )
        assert classify_destination(imp) == DestinationChannel.PRIVATE

    def test_non_autonomous_source_unaffected(self, monkeypatch):
        """Broadcast bias only applies to autonomous_narrative source."""
        monkeypatch.delenv(BROADCAST_BIAS_ENV, raising=False)
        monkeypatch.setattr(
            "agents.hapax_daimonion.cpal.destination_channel._programme_authorizes_broadcast",
            lambda: True,
        )
        imp = SimpleNamespace(
            source="director.narrative",
            content={"narrative": "Director-origin utterance."},
        )
        assert classify_destination(imp) == DestinationChannel.PRIVATE

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, True),
            ("", True),
            ("1", True),
            ("0", False),
            (" 0 ", False),
            ("true", True),
        ],
    )
    def test_broadcast_bias_flag_parsing(self, monkeypatch, raw, expected):
        if raw is None:
            monkeypatch.delenv(BROADCAST_BIAS_ENV, raising=False)
        else:
            monkeypatch.setenv(BROADCAST_BIAS_ENV, raw)
        assert _is_broadcast_bias_enabled() is expected

    def test_all_eligible_roles_present(self):
        """All roles except LISTENING are broadcast-eligible."""
        from shared.programme import ProgrammeRole

        expected_excluded = {"listening"}
        all_roles = {r.value for r in ProgrammeRole}
        assert all_roles - expected_excluded == _BROADCAST_ELIGIBLE_ROLES

    def test_explicit_broadcast_intent_takes_priority(self, monkeypatch):
        """Explicit broadcast intent tokens route LIVESTREAM regardless of bias state."""
        monkeypatch.setenv(BROADCAST_BIAS_ENV, "0")
        imp = SimpleNamespace(
            source="autonomous_narrative",
            content={"public_broadcast_intent": True, "narrative": "Explicit intent."},
        )
        assert classify_destination(imp) == DestinationChannel.LIVESTREAM

    # --- Endogenous narrative-drive sources (cc-task vocal-as-fuck) ---

    def test_endogenous_narrative_drive_stays_private_without_bridge(self, monkeypatch):
        """endogenous.narrative_drive source is only a bridge candidate."""
        monkeypatch.delenv(BROADCAST_BIAS_ENV, raising=False)
        monkeypatch.setattr(
            "agents.hapax_daimonion.cpal.destination_channel._programme_authorizes_broadcast",
            lambda: True,
        )
        imp = SimpleNamespace(
            source="endogenous.narrative_drive",
            content={"narrative": "Sustained vocal presence on broadcast."},
        )
        assert classify_destination(imp) == DestinationChannel.PRIVATE

    def test_endogenous_gem_stays_private_without_bridge(self, monkeypatch):
        """endogenous.gem source is only a bridge candidate."""
        monkeypatch.delenv(BROADCAST_BIAS_ENV, raising=False)
        monkeypatch.setattr(
            "agents.hapax_daimonion.cpal.destination_channel._programme_authorizes_broadcast",
            lambda: True,
        )
        imp = SimpleNamespace(
            source="endogenous.gem",
            content={"narrative": "Gem-frame intent."},
        )
        assert classify_destination(imp) == DestinationChannel.PRIVATE

    def test_endogenous_source_with_bias_off_stays_private(self, monkeypatch):
        """Bias OFF ⇒ even endogenous.narrative_drive falls through to PRIVATE."""
        monkeypatch.setenv(BROADCAST_BIAS_ENV, "0")
        imp = SimpleNamespace(
            source="endogenous.narrative_drive",
            content={"narrative": "Bias off, expect private."},
        )
        assert classify_destination(imp) == DestinationChannel.PRIVATE

    def test_endogenous_resolve_unblocks_broadcast_with_bridge_metadata(
        self, monkeypatch, tmp_path
    ):
        """Endogenous source needs bridge metadata plus the existing gates."""
        monkeypatch.delenv(BROADCAST_BIAS_ENV, raising=False)
        monkeypatch.setattr(
            "agents.hapax_daimonion.cpal.destination_channel._programme_authorizes_broadcast",
            lambda: True,
        )
        now = time.time()
        health_path = tmp_path / "audio-safe-for-broadcast.json"
        _write_broadcast_health(health_path, safe=True)

        decision = resolve_playback_decision(
            _bridge_broadcast_imp(now=now, source="endogenous.narrative_drive"),
            broadcast_audio_health_path=health_path,
            now=now,
        )

        assert decision.allowed is True
        assert decision.destination is DestinationChannel.LIVESTREAM
        assert decision.reason_code == "broadcast_voice_authorized"
        assert decision.target == "hapax-voice-fx-capture"
        assert decision.media_role == BROADCAST_MEDIA_ROLE
        assert decision.safety_gate["broadcast_intent"]["bias_implicit"] is False
        assert decision.safety_gate["private_to_public_bridge"]["authorized"] is True

    def test_endogenous_resolve_blocks_when_audio_unsafe(self, monkeypatch, tmp_path):
        """Bridge metadata preserves the audio_safe_for_broadcast gate."""
        monkeypatch.delenv(BROADCAST_BIAS_ENV, raising=False)
        monkeypatch.setattr(
            "agents.hapax_daimonion.cpal.destination_channel._programme_authorizes_broadcast",
            lambda: True,
        )
        now = time.time()
        health_path = tmp_path / "audio-safe-for-broadcast.json"
        _write_broadcast_health(health_path, safe=False)

        decision = resolve_playback_decision(
            _bridge_broadcast_imp(now=now, source="endogenous.narrative_drive"),
            broadcast_audio_health_path=health_path,
            now=now,
        )

        assert decision.allowed is False
        assert decision.reason_code == "audio_safe_for_broadcast_false"

    def test_endogenous_resolve_blocks_when_programme_auth_missing(self, monkeypatch, tmp_path):
        """Bridge metadata still requires fresh programme_authorization."""
        monkeypatch.delenv(BROADCAST_BIAS_ENV, raising=False)
        monkeypatch.setattr(
            "agents.hapax_daimonion.cpal.destination_channel._programme_authorizes_broadcast",
            lambda: True,
        )
        now = time.time()
        health_path = tmp_path / "audio-safe-for-broadcast.json"
        _write_broadcast_health(health_path, safe=True)
        imp = SimpleNamespace(
            source="endogenous.narrative_drive",
            content={
                "narrative": "No programme_authorization in payload.",
                "public_broadcast_intent": True,
                "destination": "broadcast",
                "bridge_outcome": "public_action_proposal",
                "route_posture": "broadcast_authorized",
                "claim_ceiling": "public_gate_required",
                "programme_id": "programme:test-public",
                "programme_authorization_ref": "programme:programme:test-public",
            },
        )

        decision = resolve_playback_decision(
            imp,
            broadcast_audio_health_path=health_path,
            now=now,
        )

        assert decision.allowed is False
        assert decision.reason_code == "programme_authorization_missing"
