"""Validator tests — synthetic conf surfaces gap correctly."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from shared.audio_graph import AudioGraphValidator


def _write_conf(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(dedent(body))
    return p


def test_validator_decomposes_simple_null_sink_conf(tmp_path: Path) -> None:
    pw_dir = tmp_path / "pipewire.conf.d"
    pw_dir.mkdir()
    _write_conf(
        pw_dir,
        "hapax-livestream-tap.conf",
        """\
        context.objects = [
            {   factory = adapter
                args = {
                    factory.name     = support.null-audio-sink
                    node.name        = "hapax-livestream-tap"
                    node.description = "Hapax Livestream (OBS monitor tap)"
                    media.class      = Audio/Sink
                    audio.position   = [ FL FR ]
                }
            }
        ]
        """,
    )
    v = AudioGraphValidator(pw_dir, tmp_path / "wp.conf.d-empty")
    result = v.decompose_confs()
    assert any(n.id == "hapax-livestream-tap" for n in result.graph.nodes)
    tap = next(n for n in result.graph.nodes if n.id == "hapax-livestream-tap")
    assert tap.kind.value == "tap"
    assert tap.channels.count == 2


def test_validator_detects_loopback_with_g8_flags(tmp_path: Path) -> None:
    pw_dir = tmp_path / "pipewire.conf.d"
    pw_dir.mkdir()
    _write_conf(
        pw_dir,
        "hapax-private-bridge.conf",
        """\
        context.modules = [
            {   name = libpipewire-module-loopback
                args = {
                    node.description = "private monitor bridge"
                    capture.props = {
                        node.name = "hapax-private-monitor-capture"
                        target.object = "hapax-private"
                        audio.channels = 2
                        audio.position = [ FL FR ]
                        stream.dont-remix = true
                    }
                    playback.props = {
                        node.name = "hapax-private-playback"
                        target.object = "alsa_output.usb-Torso_Electronics_S-4.multichannel-output"
                        audio.channels = 2
                        audio.position = [ FL FR ]
                        node.dont-fallback = true
                        node.dont-reconnect = true
                        node.dont-move = true
                        node.linger = true
                        state.restore = false
                    }
                }
            }
        ]
        """,
    )
    v = AudioGraphValidator(pw_dir, tmp_path / "wp.conf.d-empty")
    result = v.decompose_confs()
    lb = next(lb for lb in result.graph.loopbacks if lb.node_id == "hapax-private-playback")
    assert lb.dont_reconnect is True
    assert lb.dont_move is True
    assert lb.linger is True
    assert lb.state_restore is False


def test_validator_extracts_quantum_tunables(tmp_path: Path) -> None:
    pw_dir = tmp_path / "pipewire.conf.d"
    pw_dir.mkdir()
    _write_conf(
        pw_dir,
        "10-voice-quantum.conf",
        """\
        context.properties = {
            default.clock.quantum = 128
            default.clock.min-quantum = 64
            default.clock.max-quantum = 1024
            default.clock.allowed-rates = [ 16000 44100 48000 ]
        }
        """,
    )
    v = AudioGraphValidator(pw_dir, tmp_path / "wp.conf.d-empty")
    result = v.decompose_confs()
    assert len(result.graph.tunables) == 1
    t = result.graph.tunables[0]
    assert t.default_clock_quantum == 128
    assert t.allowed_rates == [16000, 44100, 48000]


def test_validator_extracts_alsa_profile_pin(tmp_path: Path) -> None:
    pw_dir = tmp_path / "pipewire.conf.d"
    pw_dir.mkdir()
    _write_conf(
        pw_dir,
        "hapax-s4-usb-sink.conf",
        """\
        monitor.alsa.rules = [
            {
                matches = [
                    { device.name = "~alsa_card.usb-Torso_Electronics_S-4*" }
                ]
                actions = {
                    update-props = {
                        api.alsa.use-acp = false
                        device.profile = "pro-audio"
                        priority.session = 1500
                        priority.driver = 1500
                    }
                }
            }
        ]
        """,
    )
    v = AudioGraphValidator(pw_dir, tmp_path / "wp.conf.d-empty")
    result = v.decompose_confs()
    assert len(result.graph.alsa_profile_pins) >= 1
    pin = result.graph.alsa_profile_pins[0]
    assert "Torso_Electronics_S-4" in pin.card_match
    assert pin.profile == "pro-audio"
    assert pin.api_alsa_use_acp is False


def test_validator_detects_role_loopback_infra(tmp_path: Path) -> None:
    wp_dir = tmp_path / "wp.conf.d"
    wp_dir.mkdir()
    _write_conf(
        wp_dir,
        "50-hapax-voice-duck.conf",
        """\
        wireplumber.profiles = {
          main = {
            policy.linking.role-based.loopbacks = required
          }
        }

        wireplumber.settings = {
          node.stream.default-media-role = "Multimedia"
          linking.role-based.duck-level = 0.3
        }

        wireplumber.components = [
          {
            type = virtual, provides = policy.linking.role-based.loopbacks
            requires = [ loopback.sink.role.multimedia ]
          }
          {
            name = libpipewire-module-loopback, type = pw-module
            arguments = {
              node.name = "loopback.sink.role.multimedia"
              node.description = "Multimedia"
              capture.props = {
                device.intended-roles = [ "Music", "Movie", "Multimedia" ]
                policy.role-based.priority = 10
                policy.role-based.preferred-target = "hapax-pc-loudnorm"
                node.volume = 0.5
              }
            }
            provides = loopback.sink.role.multimedia
          }
        ]
        """,
    )
    v = AudioGraphValidator(tmp_path / "pw.conf.d-empty", wp_dir)
    result = v.decompose_confs()
    assert len(result.graph.media_role_sinks) == 1
    sink = result.graph.media_role_sinks[0]
    assert sink.duck_policy.duck_level == 0.3
    assert sink.duck_policy.default_media_role == "Multimedia"
    assert len(sink.loopbacks) >= 1
    multi = next(lb for lb in sink.loopbacks if lb.role == "Music")
    assert multi.priority == 10
    assert multi.preferred_target == "hapax-pc-loudnorm"


def test_validator_surfaces_synthetic_broken_conf_as_warning(tmp_path: Path) -> None:
    pw_dir = tmp_path / "pipewire.conf.d"
    pw_dir.mkdir()
    # Conf that has no recognisable structure.
    _write_conf(pw_dir, "broken.conf", "this is not a valid pipewire conf at all")
    v = AudioGraphValidator(pw_dir, tmp_path / "wp.conf.d-empty")
    result = v.decompose_confs()
    assert "broken.conf" in result.gaps.untyped_confs


def test_validator_skips_disabled_and_bak_files(tmp_path: Path) -> None:
    pw_dir = tmp_path / "pipewire.conf.d"
    pw_dir.mkdir()
    (pw_dir / "live.conf").write_text("context.modules = []")
    (pw_dir / "live.conf.bak-1234567").write_text("context.modules = []")
    (pw_dir / "live.conf.disabled-2026-04-25").write_text("context.modules = []")
    (pw_dir / "live.conf.replaced-by-systemd-2026").write_text("context.modules = []")
    v = AudioGraphValidator(pw_dir, tmp_path / "wp.conf.d-empty")
    active = v.list_active_pipewire_confs()
    assert [p.name for p in active] == ["live.conf"]
