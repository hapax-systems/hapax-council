"""M8 sample-capture routing and button-orchestration tests."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from agents.m8_control.sample_capture import (
    DEFAULT_M8_USB_SINK,
    M8SampleCapture,
    M8SampleCaptureConfig,
    M8SampleCaptureError,
)


class _RecordingClient:
    def __init__(self, *, fail_at_call: int | None = None) -> None:
        self.calls: list[tuple[tuple[str, ...], int]] = []
        self.fail_at_call = fail_at_call

    def button(self, *names: str, hold_ms: int = 16) -> dict:
        self.calls.append((tuple(names), hold_ms))
        if self.fail_at_call is not None and len(self.calls) - 1 == self.fail_at_call:
            return {"ok": False, "error": "synthetic daemon failure"}
        return {"ok": True}


class _RecordingPactl:
    def __init__(self, *, fail_on: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, args: Sequence[str]) -> str:
        call = list(args)
        self.calls.append(call)
        if self.fail_on is not None and call[0] == self.fail_on:
            raise subprocess.CalledProcessError(
                1,
                ["pactl", *call],
                stderr=f"{self.fail_on} failed",
            )
        if call[:2] == ["load-module", "module-loopback"]:
            return "72\n"
        return ""


def test_capture_loads_loopback_buttons_duration_and_unloads() -> None:
    client = _RecordingClient()
    pactl = _RecordingPactl()
    sleeps: list[float] = []
    capture = M8SampleCapture(
        client=client,
        pactl_runner=pactl,
        sleep_fn=sleeps.append,
    )

    result = capture.capture("livestream_tap", 4.0, "reverie_glow")

    assert result == {
        "ok": True,
        "audio_source": "livestream_tap",
        "source_node": "hapax-livestream-tap.monitor",
        "slot_name": "reverie_glow",
        "duration_s": 4.0,
        "loopback_module_id": "72",
    }
    load_call, unload_call = pactl.calls
    assert load_call[:2] == ["load-module", "module-loopback"]
    assert "source=hapax-livestream-tap.monitor" in load_call
    assert f"sink={DEFAULT_M8_USB_SINK}" in load_call
    assert "source_dont_move=true" in load_call
    assert "sink_dont_move=true" in load_call
    assert "remix=false" in load_call
    assert any("hapax-m8-sample-input capture" in arg for arg in load_call)
    assert unload_call == ["unload-module", "72"]
    assert client.calls == [(("EDIT",), 80), (("EDIT",), 80)]
    assert sleeps == [4.0]


def test_custom_button_plan_supports_navigation_chords() -> None:
    client = _RecordingClient()
    pactl = _RecordingPactl()
    config = M8SampleCaptureConfig(
        start_sequence=(("EDIT",), ("RIGHT", "EDIT")),
        stop_sequence=(("PLAY",),),
        hold_ms=120,
    )
    capture = M8SampleCapture(
        client=client, config=config, pactl_runner=pactl, sleep_fn=lambda _: None
    )

    result = capture.capture("reverie", 1.25, "slot_a")

    assert result["ok"] is True
    assert result["source_node"] == "hapax-livestream-tap.monitor"
    assert client.calls == [
        (("EDIT",), 120),
        (("RIGHT", "EDIT"), 120),
        (("PLAY",), 120),
    ]


def test_unknown_audio_source_refuses_without_pipewire_or_button_side_effects() -> None:
    client = _RecordingClient()
    pactl = _RecordingPactl()
    capture = M8SampleCapture(client=client, pactl_runner=pactl)

    result = capture.capture("turntable", 4.0, "slot")

    assert result["ok"] is False
    assert result["error_type"] == "audio_source"
    assert "unknown audio_source" in result["error"]
    assert pactl.calls == []
    assert client.calls == []


def test_duration_cap_refuses_without_side_effects() -> None:
    client = _RecordingClient()
    pactl = _RecordingPactl()
    capture = M8SampleCapture(client=client, pactl_runner=pactl)

    result = capture.capture("livestream_tap", 31.0, "slot")

    assert result["ok"] is False
    assert result["error_type"] == "duration"
    assert "exceeds cap" in result["error"]
    assert pactl.calls == []
    assert client.calls == []


def test_blank_slot_name_refuses_without_side_effects() -> None:
    client = _RecordingClient()
    pactl = _RecordingPactl()
    capture = M8SampleCapture(client=client, pactl_runner=pactl)

    result = capture.capture("livestream_tap", 4.0, "  ")

    assert result["ok"] is False
    assert result["error_type"] == "slot_name"
    assert pactl.calls == []
    assert client.calls == []


def test_route_restored_when_m8_button_sequence_fails() -> None:
    client = _RecordingClient(fail_at_call=0)
    pactl = _RecordingPactl()
    capture = M8SampleCapture(client=client, pactl_runner=pactl, sleep_fn=lambda _: None)

    result = capture.capture("livestream_tap", 4.0, "slot")

    assert result["ok"] is False
    assert result["error_type"] == "m8_control"
    assert "restore_error" not in result
    assert pactl.calls[-1] == ["unload-module", "72"]
    assert len(client.calls) == 1


def test_stop_is_attempted_and_route_restored_when_sleep_fails() -> None:
    client = _RecordingClient()
    pactl = _RecordingPactl()

    def fail_sleep(_duration: float) -> None:
        raise RuntimeError("sleep interrupted")

    capture = M8SampleCapture(client=client, pactl_runner=pactl, sleep_fn=fail_sleep)

    result = capture.capture("livestream_tap", 4.0, "slot")

    assert result["ok"] is False
    assert result["error_type"] == "RuntimeError"
    assert "sleep interrupted" in result["error"]
    assert "stop_error" not in result
    assert pactl.calls[-1] == ["unload-module", "72"]
    assert client.calls == [(("EDIT",), 80), (("EDIT",), 80)]


def test_route_restore_error_is_reported() -> None:
    pactl = _RecordingPactl(fail_on="unload-module")
    capture = M8SampleCapture(
        client=_RecordingClient(),
        pactl_runner=pactl,
        sleep_fn=lambda _: None,
    )

    result = capture.capture("livestream_tap", 1.0, "slot")

    assert result["ok"] is False
    assert result["error_type"] == "route_restore"
    assert "unload-module failed" in result["error"]


def test_unknown_button_in_config_rejected_before_capture() -> None:
    config = M8SampleCaptureConfig(start_sequence=(("TURBO",),))

    with pytest.raises(M8SampleCaptureError, match="unknown button"):
        M8SampleCapture(client=_RecordingClient(), config=config, pactl_runner=_RecordingPactl())


def test_affordance_registered_for_m8_sample_capture() -> None:
    from shared.affordance_registry import STUDIO_AFFORDANCES

    record = next(r for r in STUDIO_AFFORDANCES if r.name == "studio.m8_sample_capture")
    assert record.daemon == "m8_control"
    assert record.operational.consent_required is False
    assert record.operational.medium == "audio"
    assert record.operational.persistence == "bounded"


def test_m8_sample_input_conf_declares_staging_sink_not_boot_loopback() -> None:
    conf = Path("config/pipewire/hapax-m8-sample-input.conf").read_text(encoding="utf-8")

    assert "support.null-audio-sink" in conf
    assert 'node.name        = "hapax-m8-sample-input"' in conf
    assert "monitor.passthrough     = true" in conf
    assert "libpipewire-module-loopback" not in conf
