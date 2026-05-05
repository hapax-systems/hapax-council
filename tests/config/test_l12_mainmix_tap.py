"""H5 Phase 2 secondary L-12 mainmix tap regression pins."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONF = REPO_ROOT / "config" / "pipewire" / "hapax-l12-mainmix-tap.conf"
LOADER = REPO_ROOT / "scripts" / "hapax-l12-mainmix-tap-load"
LOOPBACK_UNIT = REPO_ROOT / "systemd" / "units" / "hapax-l12-mainmix-tap-loopback.service"
RECORDER_UNIT = REPO_ROOT / "systemd" / "units" / "hapax-audio-ab-recorder.service"
DASHBOARD = REPO_ROOT / "grafana" / "dashboards" / "audio-ab-l12-vs-software.json"


def test_l12_mainmix_tap_conf_declares_monitor_sink_only() -> None:
    text = CONF.read_text(encoding="utf-8")

    assert "support.null-audio-sink" in text
    assert 'node.name        = "hapax-obs-broadcast-mainmix-tap"' in text
    assert "monitor.passthrough     = true" in text
    assert "libpipewire-module-loopback" not in text

    forbidden_targets = [
        "hapax-livestream-tap",
        "hapax-broadcast-master",
        "hapax-broadcast-normalized",
        "hapax-obs-broadcast-remap",
    ]
    body_without_comments = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    for target in forbidden_targets:
        assert target not in body_without_comments, f"{target} must not be a tap target"


def test_l12_mainmix_loader_pins_source_channels_and_fail_closed_flags() -> None:
    text = LOADER.read_text(encoding="utf-8")

    assert "alsa_input.usb-ZOOM_Corporation_L-12" in text
    assert "hapax-obs-broadcast-mainmix-tap" in text
    assert "AUX10 AUX11" in text
    assert "source_dont_move=true" in text
    assert "sink_dont_move=true" in text
    assert "remix=false" in text
    assert "stream.dont-remix=true" in text
    assert "node.dont-reconnect=true" in text
    assert "pactl load-module module-loopback" in text
    assert "did not retain AUX10/AUX11 binding" in text

    forbidden_mutators = re.compile(r"\b(amixer|alsactl|wpctl\s+set-profile|pw-cli\s+set-param)\b")
    assert forbidden_mutators.search(text) is None, "loader must not mutate L-12 hardware state"


def test_l12_mainmix_loopback_unit_is_oneshot_and_not_rtmp_path() -> None:
    text = LOOPBACK_UNIT.read_text(encoding="utf-8")

    assert "Type=oneshot" in text
    assert "RemainAfterExit=yes" in text
    assert "hapax-l12-mainmix-tap-load" in text
    assert "hapax-livestream-tap" not in text
    assert "hapax-broadcast-normalized" not in text


def test_audio_ab_recorder_unit_samples_expected_monitors() -> None:
    text = RECORDER_UNIT.read_text(encoding="utf-8")

    assert "python -m agents.audio_ab_recorder" in text
    assert "HAPAX_AUDIO_AB_SOFTWARE_DEVICE=hapax-broadcast-normalized.monitor" in text
    assert "HAPAX_AUDIO_AB_L12_DEVICE=hapax-obs-broadcast-mainmix-tap.monitor" in text
    assert "HAPAX_AUDIO_AB_INTERVAL_S=0.2" in text
    assert "load modules or mutate PipeWire" in text


def test_grafana_dashboard_targets_audio_ab_metrics() -> None:
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    text = json.dumps(dashboard, sort_keys=True)

    assert dashboard["uid"] == "audio-ab-l12-vs-software"
    assert "hapax_audio_ab_lufs_i" in text
    assert "hapax_audio_ab_delta_lufs" in text
    assert "hapax_audio_ab_crest_factor" in text
    assert "hapax_audio_ab_sample_ok" in text
