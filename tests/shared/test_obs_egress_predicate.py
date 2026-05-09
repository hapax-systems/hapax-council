"""Tests for the read-only OBS audio egress predicate."""

from __future__ import annotations

import textwrap

from shared.obs_egress_predicate import (
    HealthImpact,
    ObsApiEvidence,
    ObsEgressState,
    SignalEvidence,
    classify_obs_egress,
    parse_pw_link_output,
    sanitize_obs_payload,
)

NOW = 1_778_353_000.0


def _pw(text: str):
    return parse_pw_link_output(textwrap.dedent(text).strip())


def _good_pipewire():
    return _pw(
        """
        hapax-broadcast-normalized:capture_FL
          |-> hapax-obs-broadcast-remap-capture:input_FL
        hapax-broadcast-normalized:capture_FR
          |-> hapax-obs-broadcast-remap-capture:input_FR
        hapax-obs-broadcast-remap:capture_FL
          |-> OBS:input_FL
        hapax-obs-broadcast-remap:capture_FR
          |-> OBS:input_FR
        """
    )


def _good_obs_api(**overrides):
    data = {
        "available": True,
        "input_present": True,
        "input_name": "Audio Input Capture (PulseAudio)",
        "input_kind": "pulse_input_capture",
        "settings": {"device_id": "hapax-obs-broadcast-remap"},
        "muted": False,
        "volume_mul": 1.0,
        "audio_tracks": {"1": True, "2": False},
        "stream_active": True,
        "stream_reconnecting": False,
    }
    data.update(overrides)
    return ObsApiEvidence(**data)


def _live_signal(**overrides):
    data = {
        "available": True,
        "rms_dbfs": -24.0,
        "peak_dbfs": -10.0,
        "silence_ratio": 0.02,
        "checked_at": "2026-05-09T18:50:00Z",
        "max_age_s": 120.0,
    }
    data.update(overrides)
    return SignalEvidence(**data)


def test_parse_pw_link_output_records_forward_and_reverse_links() -> None:
    evidence = _pw(
        """
        OBS:input_FL
          |<- hapax-obs-broadcast-remap:capture_FL
        hapax-obs-broadcast-remap:capture_FR
          |-> OBS:input_FR
        """
    )

    assert ("hapax-obs-broadcast-remap:capture_FL", "OBS:input_FL") in evidence.links
    assert ("hapax-obs-broadcast-remap:capture_FR", "OBS:input_FR") in evidence.links
    assert "OBS:input_FL" in evidence.ports


def test_healthy_requires_pipewire_obs_api_stream_and_signal() -> None:
    result = classify_obs_egress(
        pipewire=_good_pipewire(),
        obs_api=_good_obs_api(),
        remap_signal=_live_signal(),
        now=NOW,
    )

    assert result.state == ObsEgressState.HEALTHY
    assert result.health_impact == HealthImpact.SAFE
    assert result.safe is True
    assert result.remediation_allowed is False


def test_pipewire_unavailable_is_unknown_and_blocking() -> None:
    result = classify_obs_egress(
        pipewire=parse_pw_link_output(None),
        now=NOW,
    )

    assert result.state == ObsEgressState.UNKNOWN
    assert result.health_impact == HealthImpact.BLOCKING
    assert result.safe is False
    assert result.reason_codes == ["pipewire_unavailable"]


def test_silent_remap_is_upstream_silent_and_not_remediable() -> None:
    result = classify_obs_egress(
        pipewire=_good_pipewire(),
        obs_api=_good_obs_api(),
        remap_signal=_live_signal(rms_dbfs=-90.0, silence_ratio=1.0),
        now=NOW,
    )

    assert result.state == ObsEgressState.UPSTREAM_SILENT
    assert result.safe is False
    assert result.remediation_allowed is False


def test_missing_remap_or_upstream_link_is_remap_missing() -> None:
    result = classify_obs_egress(
        pipewire=_pw(
            """
            hapax-broadcast-normalized:capture_FL
              |-> some-other-capture:input_FL
            OBS:input_FL
            OBS:input_FR
            """
        ),
        now=NOW,
    )

    assert result.state == ObsEgressState.REMAP_MISSING
    assert "remap_missing" in result.reason_codes
    assert result.safe is False


def test_obs_absent_when_remap_exists_but_no_obs_ports() -> None:
    result = classify_obs_egress(
        pipewire=_pw(
            """
            hapax-broadcast-normalized:capture_FL
              |-> hapax-obs-broadcast-remap-capture:input_FL
            hapax-broadcast-normalized:capture_FR
              |-> hapax-obs-broadcast-remap-capture:input_FR
            hapax-obs-broadcast-remap:capture_FL
            hapax-obs-broadcast-remap:capture_FR
            """
        ),
        now=NOW,
    )

    assert result.state == ObsEgressState.OBS_ABSENT
    assert result.health_impact == HealthImpact.BLOCKING
    assert result.remediation_allowed is True


def test_obs_detached_when_obs_ports_exist_but_no_remap_links() -> None:
    result = classify_obs_egress(
        pipewire=_pw(
            """
            hapax-broadcast-normalized:capture_FL
              |-> hapax-obs-broadcast-remap-capture:input_FL
            hapax-broadcast-normalized:capture_FR
              |-> hapax-obs-broadcast-remap-capture:input_FR
            hapax-obs-broadcast-remap:capture_FL
            hapax-obs-broadcast-remap:capture_FR
            OBS:input_FL
            OBS:input_FR
            """
        ),
        now=NOW,
    )

    assert result.state == ObsEgressState.OBS_DETACHED
    assert result.safe is False
    assert result.remediation_allowed is True


def test_only_one_channel_linked_is_detached_not_green() -> None:
    result = classify_obs_egress(
        pipewire=_pw(
            """
            hapax-broadcast-normalized:capture_FL
              |-> hapax-obs-broadcast-remap-capture:input_FL
            hapax-broadcast-normalized:capture_FR
              |-> hapax-obs-broadcast-remap-capture:input_FR
            hapax-obs-broadcast-remap:capture_FL
              |-> OBS:input_FL
            hapax-obs-broadcast-remap:capture_FR
            OBS:input_FR
            """
        ),
        now=NOW,
    )

    assert result.state == ObsEgressState.OBS_DETACHED
    assert result.safe is False


def test_wrong_source_cannot_produce_green_health() -> None:
    result = classify_obs_egress(
        pipewire=_pw(
            """
            hapax-broadcast-normalized:capture_FL
              |-> hapax-obs-broadcast-remap-capture:input_FL
            hapax-broadcast-normalized:capture_FR
              |-> hapax-obs-broadcast-remap-capture:input_FR
            other-source:capture_FL
              |-> OBS:input_FL
            other-source:capture_FR
              |-> OBS:input_FR
            """
        ),
        obs_api=_good_obs_api(),
        now=NOW,
    )

    assert result.state == ObsEgressState.OBS_WRONG_SOURCE
    assert result.health_impact == HealthImpact.BLOCKING
    assert result.safe is False
    assert result.remediation_allowed is True


def test_obs_api_wrong_device_is_wrong_source_even_when_pipewire_is_linked() -> None:
    result = classify_obs_egress(
        pipewire=_good_pipewire(),
        obs_api=_good_obs_api(settings={"device_id": "alsa_input.webcam-mic"}),
        now=NOW,
    )

    assert result.state == ObsEgressState.OBS_WRONG_SOURCE
    assert result.safe is False


def test_missing_obs_websocket_is_capability_absence_not_restart_permission() -> None:
    result = classify_obs_egress(
        pipewire=_good_pipewire(),
        obs_api=ObsApiEvidence(available=False, error="server disabled"),
        remap_signal=_live_signal(),
        now=NOW,
    )

    assert result.state == ObsEgressState.OBS_BOUND_UNVERIFIED
    assert result.health_impact == HealthImpact.DEGRADED
    assert result.safe is False
    assert result.capabilities["obs_websocket"] is False
    assert result.remediation_allowed is False
    assert result.reason_codes == ["obs_websocket_unavailable"]


def test_muted_or_trackless_input_is_blocking_unverified_state() -> None:
    muted = classify_obs_egress(
        pipewire=_good_pipewire(),
        obs_api=_good_obs_api(muted=True),
        now=NOW,
    )
    trackless = classify_obs_egress(
        pipewire=_good_pipewire(),
        obs_api=_good_obs_api(audio_tracks={"1": False, "2": False}),
        now=NOW,
    )

    assert muted.state == ObsEgressState.OBS_BOUND_UNVERIFIED
    assert muted.health_impact == HealthImpact.BLOCKING
    assert muted.safe is False
    assert muted.reason_codes == ["obs_input_muted"]
    assert trackless.state == ObsEgressState.OBS_BOUND_UNVERIFIED
    assert trackless.reason_codes == ["obs_input_no_audio_tracks"]


def test_stream_inactive_is_public_egress_unknown() -> None:
    result = classify_obs_egress(
        pipewire=_good_pipewire(),
        obs_api=_good_obs_api(stream_active=False),
        remap_signal=_live_signal(),
        now=NOW,
    )

    assert result.state == ObsEgressState.PUBLIC_EGRESS_UNKNOWN
    assert result.health_impact == HealthImpact.DEGRADED
    assert result.safe is False
    assert result.remediation_allowed is False


def test_health_predicate_drift_and_analyzer_failure_deny_win() -> None:
    drift = classify_obs_egress(
        pipewire=_good_pipewire(),
        obs_api=_good_obs_api(),
        health_predicate_drift=["l12-scene ok/not-ok contradiction"],
        now=NOW,
    )
    analyzer = classify_obs_egress(
        pipewire=_good_pipewire(),
        obs_api=_good_obs_api(),
        analyzer_failures=["ProbeMeasurement.samples_mono AttributeError"],
        now=NOW,
    )

    assert drift.state == ObsEgressState.HEALTH_PREDICATE_DRIFT
    assert drift.safe is False
    assert analyzer.state == ObsEgressState.ANALYZER_INTERNAL_FAILURE
    assert analyzer.safe is False


def test_secret_bearing_obs_fields_are_redacted_from_evidence() -> None:
    payload = {
        "server_password": "nope",
        "authentication": "derived-nope",
        "settings": {
            "device_id": "hapax-obs-broadcast-remap",
            "stream_key": "nope",
            "nested_token": "nope",
        },
    }

    redacted = sanitize_obs_payload(payload)

    assert redacted["server_password"] == "<redacted>"
    assert redacted["authentication"] == "<redacted>"
    assert redacted["settings"]["stream_key"] == "<redacted>"
    assert redacted["settings"]["nested_token"] == "<redacted>"
    assert redacted["settings"]["device_id"] == "hapax-obs-broadcast-remap"


def test_obs_api_evidence_redacts_secret_like_keys() -> None:
    result = classify_obs_egress(
        pipewire=_good_pipewire(),
        obs_api=_good_obs_api(
            settings={"device_id": "hapax-obs-broadcast-remap", "stream_key": "nope"}
        ),
        now=NOW,
    )

    obs_record = next(item for item in result.evidence if item.source == "obs_websocket")
    assert obs_record.observed["settings"]["stream_key"] == "<redacted>"
    assert obs_record.observed["stream_active"] is True
    assert "nope" not in str(result.model_dump(mode="json"))
