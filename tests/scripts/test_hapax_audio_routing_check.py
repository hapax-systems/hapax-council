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
LINK_MAP_SOURCE = REPO_ROOT / "config" / "hapax" / "audio-link-map.conf"
MK5_OUT = "alsa_output.usb-MOTU_UltraLite-mk5_UL5LFEC2B0-00.pro-output-0"
MK5_IN = "alsa_input.usb-MOTU_UltraLite-mk5_UL5LFEC2B0-00.pro-input-0"


def _base_graph(extra_tap_inputs: str = "") -> str:
    tap_inputs_fl = textwrap.dedent(f"""
        |<- hapax-voice-wet-playback:output_FL
        |<- hapax-mic-rode-playback:output_FL
        |<- hapax-music-loudnorm-playback:output_FL
        |<- hapax-yt-loudnorm-playback:output_FL
        {extra_tap_inputs}""")
    tap_inputs_fr = textwrap.dedent("""
        |<- hapax-voice-wet-playback:output_FR
        |<- hapax-mic-rode-playback:output_FR
        |<- hapax-music-loudnorm-playback:output_FR
        |<- hapax-yt-loudnorm-playback:output_FR
    """)
    return textwrap.dedent(f"""
    input.loopback.sink.role.broadcast-output:output_FL
    |-> hapax-voice-fx-capture:playback_FL
    input.loopback.sink.role.broadcast-output:output_FR
    |-> hapax-voice-fx-capture:playback_FR
    hapax-voice-fx-playback:output_FL
    |-> hapax-loudnorm-capture:playback_FL
    hapax-voice-fx-playback:output_FR
    |-> hapax-loudnorm-capture:playback_FR
    hapax-loudnorm-playback:output_FL
    |-> {MK5_OUT}:playback_AUX2
    hapax-loudnorm-playback:output_FR
    |-> {MK5_OUT}:playback_AUX3
    {MK5_IN}:capture_AUX2
    |-> hapax-voice-wet-capture:input_AUX2
    {MK5_IN}:capture_AUX3
    |-> hapax-voice-wet-capture:input_AUX3
    hapax-voice-wet-playback:output_FL
    |-> hapax-livestream-tap:playback_FL
    hapax-voice-wet-playback:output_FR
    |-> hapax-livestream-tap:playback_FR
    {MK5_IN}:capture_AUX0
    |-> hapax-mic-rode-capture:input_AUX0
    hapax-mic-rode-playback:output_FL
    |-> hapax-livestream-tap:playback_FL
    hapax-mic-rode-playback:output_FR
    |-> hapax-livestream-tap:playback_FR
    hapax-music-loudnorm-playback:output_FL
    |-> hapax-livestream-tap:playback_FL
    hapax-music-loudnorm-playback:output_FR
    |-> hapax-livestream-tap:playback_FR
    hapax-yt-loudnorm-playback:output_FL
    |-> hapax-livestream-tap:playback_FL
    hapax-yt-loudnorm-playback:output_FR
    |-> hapax-livestream-tap:playback_FR
    hapax-private-playback:output_FL
    |-> {MK5_OUT}:playback_AUX10
    hapax-private-playback:output_FR
    |-> {MK5_OUT}:playback_AUX11
    hapax-livestream-tap:monitor_FL
    |-> hapax-broadcast-master-capture:input_FL
    hapax-livestream-tap:monitor_FR
    |-> hapax-broadcast-master-capture:input_FR
    hapax-broadcast-normalized:capture_FL
    |-> hapax-obs-broadcast-remap-capture:input_FL
    hapax-obs-broadcast-remap:capture_FL
    |-> OBS:input_FL
    {MK5_OUT}:playback_AUX2
    {MK5_OUT}:playback_AUX3
    {MK5_OUT}:playback_AUX10
    {MK5_OUT}:playback_AUX11
    hapax-livestream-tap:playback_FL
    {tap_inputs_fl.strip()}
    |-> hapax-broadcast-master-capture:input_FL
    hapax-livestream-tap:playback_FR
    {tap_inputs_fr.strip()}
    |-> hapax-broadcast-master-capture:input_FR
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
    shutil.copy2(LINK_MAP_SOURCE, hapax_conf_dir / LINK_MAP_SOURCE.name)


DEFAULT_PW_CLI_NODES = (
    "input.loopback.sink.role.broadcast",
    "hapax-voice-fx-capture",
    "hapax-loudnorm-capture",
    "hapax-voice-wet-capture",
    "hapax-mic-rode-capture",
)


def _run_with_graph(
    tmp_path: Path,
    graph: str,
    *,
    install_deny: bool = True,
    env_overrides: dict[str, str] | None = None,
    default_sink: str = "hapax-pc-loudnorm",
    pw_cli_nodes: tuple[str, ...] = DEFAULT_PW_CLI_NODES,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)

    # HAPAX_TEST_PW_LINK_SINGLE_SHOT=1 makes the mock serve the graph on the
    # first call only (simulating PipeWire dying mid-run); the check must rely
    # on its initial $GRAPH snapshot, not re-query, or it fails open.
    _write_executable(
        bin_dir / "pw-link",
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == '-l' ]]; then\n"
        f"count_file='{bin_dir}/pw-link-calls'\n"
        'calls=$(cat "$count_file" 2>/dev/null || echo 0)\n'
        'echo $((calls + 1)) > "$count_file"\n'
        'if [[ "${HAPAX_TEST_PW_LINK_SINGLE_SHOT:-}" == "1" && "$calls" -ge 1 ]]; then\n'
        "exit 1\n"
        "fi\n"
        "cat <<'EOF'\n"
        f"{graph}\n"
        "EOF\n"
        "fi\n",
    )
    pw_cli_blocks = "\n".join(
        f'id {101 + idx},\n    node.name = "{name}"' for idx, name in enumerate(pw_cli_nodes)
    )
    _write_executable(
        bin_dir / "pw-cli",
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == 'ls' && \"${2:-}\" == 'Node' ]]; then\n"
        "cat <<'EOF'\n"
        f"{pw_cli_blocks}\n"
        "EOF\n"
        "fi\n",
    )
    _write_executable(
        bin_dir / "wpctl",
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == 'get-volume' ]]; then\n"
        'if [[ -n "${HAPAX_TEST_WPCTL_OUTPUT:-}" ]]; then\n'
        'echo "$HAPAX_TEST_WPCTL_OUTPUT"\n'
        "else\n"
        "echo 'Volume: 1.00'\n"
        "fi\n"
        "fi\n",
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
        "elif [[ \"${1:-}\" == 'get-sink-volume' ]]; then\n"
        'if [[ "${HAPAX_TEST_ZERO_SINK:-}" == "${2:-}" ]]; then\n'
        "echo 'Volume: front-left: 0 /   0% / -inf dB,   front-right: 0 /   0% / -inf dB'\n"
        "else\n"
        "echo 'Volume: front-left: 65536 / 100% / 0.00 dB,   front-right: 65536 / 100% / 0.00 dB'\n"
        "fi\n"
        "elif [[ \"${1:-}\" == 'get-sink-mute' ]]; then\n"
        "echo 'Mute: no'\n"
        "fi\n",
    )
    _write_executable(
        bin_dir / "systemctl",
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == '--user' && \"${2:-}\" == 'is-active' ]]; then\n"
        "exit 0\n"
        "fi\n"
        "exit 1\n",
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


def test_music_loudnorm_zero_input_sink_volume_hard_fails(tmp_path: Path) -> None:
    result = _run_with_graph(
        tmp_path,
        _base_graph(),
        env_overrides={"HAPAX_TEST_ZERO_SINK": "hapax-music-loudnorm"},
    )

    assert result.returncode == 1
    assert "hapax-music-loudnorm input sink audible" in result.stdout
    assert "muted or zero-volume" in result.stdout


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
    assert "livestream-tap has only authorized inputs" in result.stdout
    assert "hapax-tts-broadcast-playback:output_FL" in result.stdout


def test_mk5_dry_send_failclosed_guard_rejects_pc_loudnorm(tmp_path: Path) -> None:
    graph = _base_graph() + textwrap.dedent(
        f"""

        hapax-pc-loudnorm-playback:output_FL
        |-> {MK5_OUT}:playback_AUX2
        hapax-pc-loudnorm-playback:output_FR
        |-> {MK5_OUT}:playback_AUX3
        """
    )

    result = _run_with_graph(tmp_path, graph)

    assert result.returncode == 1
    assert "hapax-pc-loudnorm-playback not on mk5 dry-voice send AUX2/3" in result.stdout
    assert "hapax-pc-loudnorm-playback is feeding the S-4 dry send" in result.stdout


def test_youtube_livestream_tap_send_is_allowed(tmp_path: Path) -> None:
    result = _run_with_graph(tmp_path, _base_graph())

    assert result.returncode == 0, result.stdout + result.stderr
    assert "yt-loudnorm → livestream-tap" in result.stdout
    assert "unexpected source" not in result.stdout


def test_notification_private_mk5_dry_send_is_rejected(tmp_path: Path) -> None:
    graph = _base_graph() + textwrap.dedent(
        f"""

        hapax-notification-private-playback:output_FL
        |-> {MK5_OUT}:playback_AUX2
        hapax-notification-private-playback:output_FR
        |-> {MK5_OUT}:playback_AUX3
        """
    )

    result = _run_with_graph(tmp_path, graph)

    assert result.returncode == 1
    assert "hapax-notification-private-playback not on mk5 dry-voice send AUX2/3" in result.stdout
    assert "hapax-notification-private-playback is feeding the S-4 dry send" in result.stdout


def test_m8_direct_broadcast_egress_is_rejected(tmp_path: Path) -> None:
    graph = _base_graph() + textwrap.dedent(
        """

        hapax-m8-loudnorm-playback:output_AUX10
        |-> hapax-livestream-tap:playback_FL
        """
    )

    result = _run_with_graph(tmp_path, graph)

    assert result.returncode == 1
    assert "livestream-tap has only authorized inputs" in result.stdout
    assert "hapax-m8-loudnorm-playback:output_AUX10" in result.stdout


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
        default_sink=MK5_OUT,
    )

    assert result.returncode == 1
    assert "default/unclassified audio lands on fail-closed multimedia" in result.stdout
    assert "default sink is live/physical" in result.stdout


def test_s4_wet_return_requires_mk5_input_links(tmp_path: Path) -> None:
    graph = "\n".join(
        line
        for line in _base_graph().splitlines()
        if "capture_AUX2" not in line and "input_AUX2" not in line
    )

    result = _run_with_graph(tmp_path, graph)

    assert result.returncode == 1
    assert "mk5 IN AUX2/3 → voice-wet-capture" in result.stdout
    assert "S-4 wet voice not captured" in result.stdout


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
    shutil.copy2(LINK_MAP_SOURCE, hapax_conf_dir / LINK_MAP_SOURCE.name)

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
    assert "link-map runtime targets the mk5" in result.stdout


# ── Canonical exit-semantics pins (Phase 0.1: exit-0-while-RED) ──────────────
# The contract every audio-adjacent gate leans on: a RED topology MUST exit
# nonzero, a GREEN topology MUST exit 0. routing-phase0-audio-check-exit-code-fix.


def _graph_without_dry_voice_send() -> str:
    """Known-RED fixture: the loudnorm → mk5 OUT AUX2/3 dry-voice send is absent."""
    lines: list[str] = []
    skip_targets = False
    for line in _base_graph().splitlines():
        if "hapax-loudnorm-playback:output" in line:
            skip_targets = True
            continue
        if skip_targets and line.lstrip().startswith("|->"):
            continue
        skip_targets = False
        lines.append(line)
    return "\n".join(lines)


def test_known_red_topology_exits_nonzero(tmp_path: Path) -> None:
    result = _run_with_graph(tmp_path, _graph_without_dry_voice_send())

    assert result.returncode != 0, result.stdout + result.stderr
    assert "INVARIANT(S) VIOLATED" in result.stdout
    assert "TTS not reaching the S-4 insert" in result.stdout


def test_known_green_topology_exits_zero(tmp_path: Path) -> None:
    result = _run_with_graph(tmp_path, _base_graph())

    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL INVARIANTS PASSED" in result.stdout


def test_missing_critical_mute_node_hard_fails(tmp_path: Path) -> None:
    """A critical chain node absent from pw-cli must FAIL, not silently skip."""
    nodes = tuple(n for n in DEFAULT_PW_CLI_NODES if n != "hapax-voice-fx-capture")

    result = _run_with_graph(tmp_path, _base_graph(), pw_cli_nodes=nodes)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "hapax-voice-fx-capture not muted" in result.stdout
    assert "critical chain node absent" in result.stdout


def test_unreadable_mute_state_hard_fails(tmp_path: Path) -> None:
    """wpctl output that proves neither muted nor audible must FAIL closed."""
    result = _run_with_graph(
        tmp_path,
        _base_graph(),
        env_overrides={"HAPAX_TEST_WPCTL_OUTPUT": "Error: invalid id"},
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "mute state unreadable" in result.stdout


def test_webcam_leak_detected_from_graph_snapshot(tmp_path: Path) -> None:
    """The webcam-leak guard must read the $GRAPH snapshot, not re-query pw-link."""
    graph = _base_graph() + textwrap.dedent(
        """

        alsa_input.usb-046d_Logitech_BRIO_43B0576A-03.analog-stereo:capture_FL
        |-> hapax-voice-wet-capture:input_AUX2
        """
    )

    result = _run_with_graph(
        tmp_path,
        graph,
        env_overrides={"HAPAX_TEST_PW_LINK_SINGLE_SHOT": "1"},
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "no webcam mic in mk5 voice/mic capture chains" in result.stdout
    assert "LEAK" in result.stdout
