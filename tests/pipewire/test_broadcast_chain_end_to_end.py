"""Structural integration pins for the MPC-first music broadcast chain.

The old host-side chain was ``pw-cat -> loudnorm -> music-duck -> L-12``.
That is intentionally retired. The current chain is hardware-first:

    pw-cat -> hapax-music-loudnorm -> reconciler link map -> MPC USB IN 1/2
        -> MPC hardware mix -> L-12 physical/Evil Pet return
        -> hapax-l12-evilpet-capture -> hapax-livestream-tap
        -> hapax-broadcast-master -> hapax-broadcast-normalized

CI cannot inspect the MPC/L-12 patch bay, so this file pins the host-side
contracts around that hardware gap: music-loudnorm must be reconciler-owned
instead of target.object-owned, L-12 capture must feed the livestream tap,
and OBS must remain bound to the post-master normalized source.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config" / "pipewire"

# Configs that compose the host-observable portion of the chain. Order is
# documentary only; the tests assert edges and node contracts.
CHAIN_CONFIGS = (
    "hapax-music-loudnorm.conf",
    "hapax-l12-evilpet-capture.conf",
    "hapax-livestream-tap.conf",
    "hapax-broadcast-master.conf",
)

L12_USB_IN_PATTERN = re.compile(
    r"alsa_input\.usb-ZOOM_Corporation_L-12_[0-9A-F]+-00\.multichannel-input"
)


@pytest.fixture(scope="module")
def chain_configs() -> dict[str, str]:
    """Read every chain config; skip if any is missing from the checkout."""
    payloads: dict[str, str] = {}
    for name in CHAIN_CONFIGS:
        path = CONFIG_DIR / name
        if not path.exists():
            pytest.skip(f"chain config {name} missing from repo checkout")
        payloads[name] = path.read_text(encoding="utf-8")
    return payloads


def _strip_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _extract_playback_target(conf_text: str, owning_node: str) -> str | None:
    """Return the next target.object after an owning node declaration."""
    stripped = _strip_comments(conf_text)
    capture_match = re.search(rf'node\.name\s*=\s*"{re.escape(owning_node)}"', stripped)
    if capture_match is None:
        return None
    rest = stripped[capture_match.end() :]
    target_match = re.search(r'target\.object\s*=\s*"([^"]+)"', rest)
    if target_match is None:
        return None
    return target_match.group(1)


def _playback_props_tail(conf_text: str) -> str:
    stripped = _strip_comments(conf_text)
    playback_idx = stripped.find("playback.props")
    assert playback_idx >= 0, "config missing playback.props block"
    return stripped[playback_idx:]


class TestStage1MusicLoudnormToMpc:
    def test_loudnorm_sink_exists(self, chain_configs: dict[str, str]) -> None:
        text = chain_configs["hapax-music-loudnorm.conf"]
        assert 'node.name = "hapax-music-loudnorm"' in text
        assert 'media.class = "Audio/Sink"' in text

    def test_loudnorm_playback_is_reconciler_owned(self, chain_configs: dict[str, str]) -> None:
        tail = _playback_props_tail(chain_configs["hapax-music-loudnorm.conf"])
        assert "target.object" not in tail
        assert "node.autoconnect = false" in tail
        assert "audio.position = [ FL FR ]" in tail
        assert 'node.description = "Hapax Music Loudnorm → MPC USB IN 1/2"' in tail

    def test_no_retired_duck_or_direct_l12_target(self, chain_configs: dict[str, str]) -> None:
        tail = _playback_props_tail(chain_configs["hapax-music-loudnorm.conf"])
        assert "hapax-music-duck" not in tail
        assert "alsa_output.usb-ZOOM_Corporation_L-12" not in tail


class TestStage2L12CaptureToTap:
    def test_l12_capture_binds_multichannel_input(self, chain_configs: dict[str, str]) -> None:
        target = _extract_playback_target(
            chain_configs["hapax-l12-evilpet-capture.conf"],
            "hapax-l12-evilpet-capture",
        )
        assert target is not None, "L-12 capture missing capture target.object"
        assert L12_USB_IN_PATTERN.fullmatch(target)

    def test_l12_capture_is_narrow_and_identity_mapped(self, chain_configs: dict[str, str]) -> None:
        text = _strip_comments(chain_configs["hapax-l12-evilpet-capture.conf"])
        assert "stream.dont-remix = true" in text
        assert "audio.channels = 4" in text
        assert "audio.position = [ AUX1 AUX3 AUX4 AUX5 ]" in text

    def test_l12_capture_playback_targets_livestream_tap(
        self, chain_configs: dict[str, str]
    ) -> None:
        target = _extract_playback_target(
            chain_configs["hapax-l12-evilpet-capture.conf"],
            "hapax-l12-evilpet-playback",
        )
        assert target == "hapax-livestream-tap"


class TestStage3LivestreamTap:
    def test_tap_is_null_audio_sink(self, chain_configs: dict[str, str]) -> None:
        text = chain_configs["hapax-livestream-tap.conf"]
        assert 'node.name        = "hapax-livestream-tap"' in text
        assert "support.null-audio-sink" in text

    def test_tap_exposes_monitor_port(self, chain_configs: dict[str, str]) -> None:
        text = chain_configs["hapax-livestream-tap.conf"]
        assert "monitor.passthrough     = true" in text or "monitor.passthrough = true" in text


class TestStage4BroadcastMaster:
    def test_master_captures_from_livestream_tap(self, chain_configs: dict[str, str]) -> None:
        target = _extract_playback_target(
            chain_configs["hapax-broadcast-master.conf"],
            "hapax-broadcast-master-capture",
        )
        assert target == "hapax-livestream-tap"

    def test_master_playback_exposes_audio_source(self, chain_configs: dict[str, str]) -> None:
        text = chain_configs["hapax-broadcast-master.conf"]
        assert 'node.name = "hapax-broadcast-master"' in text
        assert 'media.class = "Audio/Source"' in text


class TestStage5BroadcastNormalized:
    def test_normalized_capture_targets_master(self, chain_configs: dict[str, str]) -> None:
        target = _extract_playback_target(
            chain_configs["hapax-broadcast-master.conf"],
            "hapax-broadcast-normalized-capture",
        )
        assert target == "hapax-broadcast-master"

    def test_obs_binding_name_documented_in_master_conf(
        self, chain_configs: dict[str, str]
    ) -> None:
        text = chain_configs["hapax-broadcast-master.conf"]
        assert "hapax-broadcast-normalized" in text
        assert "OBS audio source MUST bind to" in text


class TestEndToEndHostSideChain:
    def test_host_side_chain_around_hardware_gap(self, chain_configs: dict[str, str]) -> None:
        edges: dict[str, str | None] = {
            "hapax-l12-evilpet-playback": _extract_playback_target(
                chain_configs["hapax-l12-evilpet-capture.conf"],
                "hapax-l12-evilpet-playback",
            ),
            "hapax-broadcast-master-capture": _extract_playback_target(
                chain_configs["hapax-broadcast-master.conf"],
                "hapax-broadcast-master-capture",
            ),
            "hapax-broadcast-normalized-capture": _extract_playback_target(
                chain_configs["hapax-broadcast-master.conf"],
                "hapax-broadcast-normalized-capture",
            ),
        }
        assert edges["hapax-l12-evilpet-playback"] == "hapax-livestream-tap"
        assert edges["hapax-broadcast-master-capture"] == "hapax-livestream-tap"
        assert edges["hapax-broadcast-normalized-capture"] == "hapax-broadcast-master"

    def test_no_chain_stage_targets_pre_master_obs_sink(
        self, chain_configs: dict[str, str]
    ) -> None:
        for name, text in chain_configs.items():
            assert "hapax-livestream:monitor" not in _strip_comments(text), (
                f"{name} must not target hapax-livestream:monitor "
                "(pre-master, bypasses safety-net limiter)"
            )
