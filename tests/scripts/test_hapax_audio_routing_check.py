"""Regression tests for ``scripts/hapax-audio-routing-check``.

The check script validates the live PipeWire graph. These tests run it against
synthetic ``pw-link`` output so parser behavior can be pinned without requiring
audio hardware in CI.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-audio-routing-check"
WP_DENY_CONF_SOURCE = REPO_ROOT / "config" / "wireplumber" / "98-hapax-link-deny.conf"
WP_DENY_SCRIPT_SOURCE = REPO_ROOT / "config" / "wireplumber" / "scripts" / "hapax" / "link-deny.lua"
FORBIDDEN_LINKS_SOURCE = REPO_ROOT / "config" / "hapax" / "audio-forbidden-links.conf"


def _base_graph(extra_tap_inputs: str = "") -> str:
    # Interim MPC-only return (2026-05-29, L-12 removed): the broadcast return
    # is the MPC's own USB return (hapax-mpc-usb-return-playback). The public
    # mix returns on pro-input-0 capture_AUX0/1; the private monitor mix on
    # capture_AUX2/3 is deliberately absent from this graph (fenced).
    tap_inputs = f"|<- hapax-mpc-usb-return-playback:output_FL\n{extra_tap_inputs}"
    mpc_refs = "\n".join(f"Akai Professional MPC Live III:playback_AUX{i}" for i in range(10))
    mpc_return = "alsa_input.usb-Akai_Professional_MPC_LIVE_III_B-00.pro-input-0"
    return textwrap.dedent(f"""
    {mpc_return}:capture_AUX0
    |-> hapax-mpc-usb-return-capture:input_AUX0
    {mpc_return}:capture_AUX1
    |-> hapax-mpc-usb-return-capture:input_AUX1
    output.loopback.sink.role.broadcast:output_FL
    |-> hapax-voice-fx-capture:playback_FL
hapax-voice-fx-playback:output_FL
|-> hapax-loudnorm-capture:playback_FL
hapax-loudnorm-playback:output_FL
|-> Akai Professional MPC Live III:playback_AUX2
hapax-loudnorm-playback:output_FR
|-> Akai Professional MPC Live III:playback_AUX3
hapax-music-loudnorm-playback:output_FL
|-> Akai Professional MPC Live III:playback_AUX0
hapax-music-loudnorm-playback:output_FR
|-> Akai Professional MPC Live III:playback_AUX1
hapax-private-playback:output_FL
|-> Akai Professional MPC Live III:playback_AUX8
hapax-private-playback:output_FR
|-> Akai Professional MPC Live III:playback_AUX9
hapax-broadcast-normalized:capture_FL
|-> hapax-obs-broadcast-remap-capture:playback_FL
hapax-obs-broadcast-remap:capture_FL
|-> OBS:input_FL
{mpc_refs}
hapax-mpc-usb-return-playback:output_FL
|-> hapax-livestream-tap:playback_FL
hapax-mpc-usb-return-playback:output_FR
|-> hapax-livestream-tap:playback_FR
hapax-broadcast-master:monitor_FL
|-> hapax-livestream:playback_FL
hapax-livestream-tap:playback_FL
{tap_inputs}|-> hapax-broadcast-master:playback_FL
    hapax-livestream-tap:playback_FR
    |<- hapax-mpc-usb-return-playback:output_FR
    |-> hapax-broadcast-master:playback_FR
    """).strip()


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _install_deny_policy(home: Path) -> None:
    """Install WirePlumber deny policy and forbidden links into the fake HOME."""
    wp_conf_dir = home / ".config" / "wireplumber" / "wireplumber.conf.d"
    wp_script_dir = home / ".local" / "share" / "wireplumber" / "scripts" / "hapax"
    hapax_conf_dir = home / ".config" / "hapax"
    wp_conf_dir.mkdir(parents=True, exist_ok=True)
    wp_script_dir.mkdir(parents=True, exist_ok=True)
    hapax_conf_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(WP_DENY_CONF_SOURCE, wp_conf_dir / WP_DENY_CONF_SOURCE.name)
    shutil.copy2(WP_DENY_SCRIPT_SOURCE, wp_script_dir / WP_DENY_SCRIPT_SOURCE.name)
    shutil.copy2(FORBIDDEN_LINKS_SOURCE, hapax_conf_dir / FORBIDDEN_LINKS_SOURCE.name)


def _run_with_graph(
    tmp_path: Path,
    graph: str,
    *,
    install_deny: bool = True,
    env_overrides: dict[str, str] | None = None,
    default_sink: str = "hapax-pc-loudnorm",
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)

    _write_executable(
        bin_dir / "pw-link",
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == '-l' ]]; then\n"
        "cat <<'EOF'\n"
        f"{graph}\n"
        "EOF\n"
        "fi\n",
    )
    _write_executable(
        bin_dir / "pw-cli",
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == 'ls' && \"${2:-}\" == 'Node' ]]; then\n"
        "cat <<'EOF'\n"
        "id 101,\n"
        '    node.name = "input.loopback.sink.role.broadcast"\n'
        "id 102,\n"
        '    node.name = "hapax-voice-fx-capture"\n'
        "id 103,\n"
        '    node.name = "hapax-loudnorm-capture"\n'
        "EOF\n"
        "fi\n",
    )
    _write_executable(
        bin_dir / "wpctl",
        "#!/usr/bin/env bash\nif [[ \"${1:-}\" == 'get-volume' ]]; then\necho 'Volume: 1.00'\nfi\n",
    )
    _write_executable(
        bin_dir / "pactl",
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == 'info' ]]; then\n"
        "cat <<'EOF'\n"
        f"Default Sink: {default_sink}\n"
        "EOF\n"
        "elif [[ \"${1:-}\" == 'list' && \"${2:-}\" == 'sources' && \"${3:-}\" == 'short' ]]; then\n"
        "cat <<'EOF'\n"
        "1\thapax-livestream-tap.monitor\tmodule-null-sink.c\ts16le 2ch 48000Hz\tRUNNING\n"
        "2\thapax-broadcast-master.monitor\tmodule-null-sink.c\ts16le 2ch 48000Hz\tRUNNING\n"
        "3\thapax-broadcast-normalized\tmodule-remap-source.c\ts16le 2ch 48000Hz\tRUNNING\n"
        "4\thapax-obs-broadcast-remap\tmodule-remap-source.c\ts16le 2ch 48000Hz\tRUNNING\n"
        "EOF\n"
        "elif [[ \"${1:-}\" == 'list' && \"${2:-}\" == 'sinks' && \"${3:-}\" == 'short' ]]; then\n"
        "cat <<'EOF'\n"
        "11\thapax-livestream-tap\tmodule-null-sink.c\ts16le 2ch 48000Hz\tRUNNING\n"
        "12\thapax-broadcast-master\tmodule-null-sink.c\ts16le 2ch 48000Hz\tRUNNING\n"
        "EOF\n"
        "fi\n",
    )
    _write_executable(
        bin_dir / "parec",
        "#!/usr/bin/env python3\n"
        "import os, struct, sys\n"
        "amp = int(os.environ.get('HAPAX_TEST_PAREC_AMPLITUDE', '1000'))\n"
        "frames = int(os.environ.get('HAPAX_TEST_PAREC_FRAMES', '96000'))\n"
        "sys.stdout.buffer.write(struct.pack('<h', amp) * frames)\n",
    )

    home = tmp_path / "home"
    (home / ".config" / "pipewire" / "pipewire.conf.d").mkdir(parents=True, exist_ok=True)
    if install_deny:
        _install_deny_policy(home)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(home),
        **(env_overrides or {}),
    }
    return subprocess.run(
        [str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def test_tap_input_parser_ignores_adjacent_livestream_output_block(tmp_path: Path) -> None:
    result = _run_with_graph(tmp_path, _base_graph())

    assert result.returncode == 0, result.stdout + result.stderr
    assert "livestream-tap has only authorized inputs" in result.stdout
    assert "unexpected source" not in result.stdout
    assert "RMS=" in result.stdout
    assert "pw-top" not in result.stdout


def test_signal_flow_advisory_warns_on_parec_silence_without_failing(tmp_path: Path) -> None:
    result = _run_with_graph(
        tmp_path,
        _base_graph(),
        env_overrides={"HAPAX_TEST_PAREC_AMPLITUDE": "0"},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Signal-Flow Advisory" in result.stdout
    assert "below" in result.stdout
    assert "RMS=0.00000000" in result.stdout


def test_tap_input_parser_rejects_s4_direct_tap_until_promoted(tmp_path: Path) -> None:
    result = _run_with_graph(
        tmp_path,
        _base_graph("|<- hapax-s4-tap:output_FL\n"),
    )

    assert result.returncode == 1
    assert "livestream-tap has only authorized inputs" in result.stdout
    assert "hapax-s4-tap:output_FL" in result.stdout


def test_tap_input_parser_fails_direct_non_mpc_input(tmp_path: Path) -> None:
    result = _run_with_graph(
        tmp_path,
        _base_graph("|<- hapax-direct-bypass-playback:output_FL\n"),
    )

    assert result.returncode == 1
    assert "livestream-tap has only authorized inputs" in result.stdout
    assert "hapax-direct-bypass-playback:output_FL" in result.stdout


def test_tap_input_parser_fails_unowned_polyend_direct_tap(tmp_path: Path) -> None:
    result = _run_with_graph(
        tmp_path,
        _base_graph("|<- hapax-polyend-loudnorm-playback:output_FL\n"),
    )

    assert result.returncode == 1
    assert "livestream-tap has only authorized inputs" in result.stdout
    assert "hapax-polyend-loudnorm-playback:output_FL" in result.stdout


def test_tts_direct_bypass_guard_follows_multiline_link_blocks(tmp_path: Path) -> None:
    graph = _base_graph() + textwrap.dedent(
        """

        hapax-tts-broadcast-playback:output_FL
        |-> hapax-livestream-tap:playback_FL
        """
    )

    result = _run_with_graph(tmp_path, graph)

    assert result.returncode == 1
    assert "no TTS bypass to livestream-tap" in result.stdout
    assert "BYPASS DETECTED" in result.stdout


def test_pc_usb56_failclosed_guard_rejects_pc_loudnorm_to_mpc(tmp_path: Path) -> None:
    graph = _base_graph() + textwrap.dedent(
        """

        hapax-pc-loudnorm-playback:output_FL
        |-> Akai Professional MPC Live III:playback_AUX4
        hapax-pc-loudnorm-playback:output_FR
        |-> Akai Professional MPC Live III:playback_AUX5
        """
    )

    result = _run_with_graph(tmp_path, graph)

    assert result.returncode == 1
    assert "PC USB 5/6 is fail-closed" in result.stdout
    assert "PC loudnorm is feeding MPC AUX4/5" in result.stdout


def test_youtube_aux67_send_is_allowed(tmp_path: Path) -> None:
    """Interim MPC-only (2026-05-29): the YouTube send to MPC AUX6/7 is enabled
    (operator-mix plumbing). It is no longer a forbidden boundary; the routing
    check must NOT fail on it. Broadcast eligibility stays gated in policy, not
    by a link-time guard."""
    graph = _base_graph() + textwrap.dedent(
        """

        hapax-yt-loudnorm-playback:output_FL
        |-> Akai Professional MPC Live III:playback_AUX6
        hapax-yt-loudnorm-playback:output_FR
        |-> Akai Professional MPC Live III:playback_AUX7
        """
    )

    result = _run_with_graph(tmp_path, graph)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "YouTube AUX6/7 is disabled" not in result.stdout
    assert "YT loudnorm is feeding MPC AUX6/7" not in result.stdout


def test_notification_private_mpc_bridge_is_rejected(tmp_path: Path) -> None:
    graph = _base_graph() + textwrap.dedent(
        """

        hapax-notification-private-playback:output_FL
        |-> Akai Professional MPC Live III:playback_AUX8
        hapax-notification-private-playback:output_FR
        |-> Akai Professional MPC Live III:playback_AUX9
        """
    )

    result = _run_with_graph(tmp_path, graph)

    assert result.returncode == 1
    assert "notifications do not share private TTS AUX8/9" in result.stdout
    assert "notification-private is feeding MPC AUX8/9" in result.stdout


def test_m8_l12_or_mpc_egress_is_rejected(tmp_path: Path) -> None:
    graph = _base_graph() + textwrap.dedent(
        """

        hapax-m8-loudnorm-playback:output_AUX10
        |-> alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FL
        hapax-m8-loudnorm-playback:output_AUX11
        |-> alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FR
        """
    )

    result = _run_with_graph(tmp_path, graph)

    assert result.returncode == 1
    assert "M8/instrument route is disabled" in result.stdout
    assert "M8 loudnorm has a live MPC/L-12 egress" in result.stdout


def test_assistant_private_fallback_to_multimedia_is_rejected(tmp_path: Path) -> None:
    graph = _base_graph() + textwrap.dedent(
        """

        input.loopback.sink.role.assistant-output:output_FL
        |-> input.loopback.sink.role.multimedia:playback_FL
        input.loopback.sink.role.assistant-output:output_FR
        |-> input.loopback.sink.role.multimedia:playback_FR
        """
    )

    result = _run_with_graph(tmp_path, graph)

    assert result.returncode == 1
    assert "assistant/private does not fall into multimedia" in result.stdout
    assert "assistant role is feeding multimedia/PC" in result.stdout


def test_livestream_tap_bridge_fallback_to_multimedia_is_rejected(tmp_path: Path) -> None:
    graph = _base_graph() + textwrap.dedent(
        """

        output.loopback-2939205-13:output_FL
        |-> input.loopback.sink.role.multimedia:playback_FL
        output.loopback-2939205-13:output_FR
        |-> input.loopback.sink.role.multimedia:playback_FR
        """
    )

    result = _run_with_graph(tmp_path, graph)

    assert result.returncode == 1
    assert "livestream tap bridge does not fall into multimedia" in result.stdout
    assert "tap bridge is feeding multimedia/PC" in result.stdout


def test_optional_polyend_capture_fallback_to_webcam_or_l12_is_rejected(tmp_path: Path) -> None:
    graph = _base_graph() + textwrap.dedent(
        """

        alsa_input.usb-046d_Logitech_BRIO_43B0576A-03.analog-stereo:capture_FL
        |-> hapax-polyend-instrument-capture:input_1
        alsa_input.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.multichannel-input:capture_AUX0
        |-> hapax-polyend-instrument-capture:input_2
        """
    )

    result = _run_with_graph(tmp_path, graph)

    assert result.returncode == 1
    assert "optional Polyend capture is fail-closed" in result.stdout
    assert "Polyend capture fell back to webcam/L-12/default capture" in result.stdout


def test_default_sink_must_be_fail_closed_not_raw_mpc(tmp_path: Path) -> None:
    result = _run_with_graph(
        tmp_path,
        _base_graph(),
        default_sink="alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.pro-output-0",
    )

    assert result.returncode == 1
    assert "default/unclassified audio lands on fail-closed multimedia" in result.stdout
    assert "default sink is live/physical" in result.stdout


def test_mpc_return_capture_requires_upstream_aux_links(tmp_path: Path) -> None:
    """Interim MPC-only (2026-05-29): if the MPC public-mix capture leg
    (capture_AUX0 -> mpc-usb-return-capture) is missing, the broadcast return
    is silently starved — Chain 10 must fail."""
    graph = "\n".join(
        line
        for line in _base_graph().splitlines()
        if "capture_AUX0" not in line and "input_AUX0" not in line
    )

    result = _run_with_graph(tmp_path, graph)

    assert result.returncode == 1
    assert "MPC AUX0 → mpc-usb-return-capture linked" in result.stdout
    assert "MISSING" in result.stdout


def test_deny_policy_missing_forbidden_links_runtime_hard_fails(tmp_path: Path) -> None:
    result = _run_with_graph(tmp_path, _base_graph(), install_deny=False)

    assert result.returncode == 1
    assert "forbidden links runtime conf present" in result.stdout
    assert "deny hook will run in degraded fail-closed mode" in result.stdout


def test_deny_policy_not_installed_hard_fails(tmp_path: Path) -> None:
    home = tmp_path / "home"
    hapax_conf_dir = home / ".config" / "hapax"
    hapax_conf_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FORBIDDEN_LINKS_SOURCE, hapax_conf_dir / FORBIDDEN_LINKS_SOURCE.name)

    result = _run_with_graph(tmp_path, _base_graph(), install_deny=False)

    assert result.returncode == 1
    assert "WirePlumber deny policy not installed" in result.stdout
    assert "boundaries unguarded at link-time" in result.stdout


def test_deny_policy_stale_installed_conf_hard_fails(tmp_path: Path) -> None:
    result = _run_with_graph(tmp_path, _base_graph(), install_deny=True)
    assert result.returncode == 0, result.stdout + result.stderr

    home = tmp_path / "home"
    stale_conf = home / ".config" / "wireplumber" / "wireplumber.conf.d" / "98-hapax-link-deny.conf"
    stale_conf.write_text("# stale content\n")

    result = _run_with_graph(tmp_path, _base_graph(), install_deny=False)

    assert result.returncode == 1
    assert "installed policy differs from source" in result.stdout


def test_deny_policy_legacy_config_script_hard_fails(tmp_path: Path) -> None:
    result = _run_with_graph(tmp_path, _base_graph(), install_deny=True)
    assert result.returncode == 0, result.stdout + result.stderr

    home = tmp_path / "home"
    legacy_script = home / ".config" / "wireplumber" / "scripts" / "hapax" / "link-deny.lua"
    legacy_script.parent.mkdir(parents=True)
    legacy_script.write_text("-- stale legacy script\n")

    result = _run_with_graph(tmp_path, _base_graph(), install_deny=False)

    assert result.returncode == 1
    assert "WirePlumber deny script installed in data path only" in result.stdout
    assert "legacy config script exists" in result.stdout


def test_deny_policy_legacy_path_equal_to_data_path_is_not_stale(tmp_path: Path) -> None:
    home = tmp_path / "home"
    data_script = home / ".local" / "share" / "wireplumber" / "scripts" / "hapax" / "link-deny.lua"

    result = _run_with_graph(
        tmp_path,
        _base_graph(),
        install_deny=True,
        env_overrides={"HAPAX_WP_DENY_SCRIPT_LEGACY_INSTALLED": str(data_script)},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "WirePlumber deny script installed in data path only" in result.stdout
    assert "legacy config script exists" not in result.stdout


def test_deny_policy_stale_forbidden_links_runtime_hard_fails(tmp_path: Path) -> None:
    result = _run_with_graph(tmp_path, _base_graph(), install_deny=True)
    assert result.returncode == 0, result.stdout + result.stderr

    home = tmp_path / "home"
    stale_links = home / ".config" / "hapax" / "audio-forbidden-links.conf"
    stale_links.write_text("# stale forbidden links\n")

    result = _run_with_graph(tmp_path, _base_graph(), install_deny=False)

    assert result.returncode == 1
    assert "runtime file differs from source" in result.stdout


def test_deny_policy_fully_installed_passes(tmp_path: Path) -> None:
    result = _run_with_graph(tmp_path, _base_graph(), install_deny=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "WirePlumber deny policy installed matches source" in result.stdout
    assert "forbidden links runtime conf matches source" in result.stdout
