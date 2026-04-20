"""Integration tests for scripts/hapax-pin-check-probe.sh — B5.

Mocks pactl + pw-cat + ffmpeg via a stubbed PATH so the wrapper's
parse logic + CLI hand-off can be exercised without a live PipeWire
graph or audio hardware.

Test approach: each test composes a tmp_path bin/ directory with
shell-script stubs for pactl, pw-cat, ffmpeg, and the hapax-audio-
topology CLI, prepends it to PATH, then runs the wrapper. The CLI
stub captures the args the wrapper passes for assertion.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[2] / "scripts" / "hapax-pin-check-probe.sh"


def _write_stub(path: Path, body: str) -> None:
    path.write_text(f"#!/usr/bin/env bash\n{textwrap.dedent(body).strip()}\n", encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture()
def stub_env(tmp_path: Path):
    """Stand up a tmp_path bin/ with stubbed external binaries +
    return (env, capture_file). Tests mutate the stubs before calling
    the wrapper."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "cli-capture.txt"

    # Default stubs — tests override per-scenario.
    _write_stub(bin_dir / "pactl", 'echo "" >&2\nexit 0\n')
    _write_stub(bin_dir / "pw-cat", "exit 0\n")
    _write_stub(bin_dir / "ffmpeg", "exit 0\n")
    # Hapax CLI stub — captures argv for assertion + returns 0 by default.
    _write_stub(
        bin_dir / "hapax-audio-topology",
        f'printf "%s\\n" "$@" > "{capture}"\nexit 0\n',
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["HAPAX_PIN_CHECK_STATE_FILE"] = str(tmp_path / "state.json")
    env["HAPAX_PIN_CHECK_CAPTURE_S"] = "0.1"  # Speed up the sleep.
    env["HAPAX_PIN_CHECK_AUTO_FIX"] = "0"  # Default off so capture stays focused.
    # Point the wrapper at the stub CLI rather than the real one.
    env["HAPAX_AUDIO_TOPOLOGY_CLI"] = str(bin_dir / "hapax-audio-topology")
    return env, capture, bin_dir


def _run_wrapper(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the wrapper with the test env. The CLI path is overridden
    via HAPAX_AUDIO_TOPOLOGY_CLI to point at the stub bin_dir's
    hapax-audio-topology rather than the real one."""
    return subprocess.run(
        [str(WRAPPER)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=10,
    )


class TestSinkNotFound:
    def test_missing_sink_exits_zero_no_cli_call(self, stub_env, tmp_path):
        env, capture, bin_dir = stub_env
        # pactl returns no sinks at all.
        _write_stub(bin_dir / "pactl", "exit 0\n")
        # Replace the wrapper's CLI with our captured one so the
        # PATH lookup resolves to the stub for normal runs.
        # (When sink missing, CLI shouldn't be called at all.)

        # Use a custom sink name unlikely to match anything.
        env["HAPAX_PIN_CHECK_SINK"] = "alsa_output.absent"
        result = _run_wrapper(env)

        assert result.returncode == 0, f"stderr={result.stderr}"
        assert "not found in pactl listing" in result.stderr
        # CLI capture file should NOT have been written.
        assert not capture.exists()


class TestProbeAssembly:
    def test_running_sink_with_input_invokes_cli_with_correct_flags(self, stub_env, tmp_path):
        env, capture, bin_dir = stub_env

        # pactl `list sinks` mocks RUNNING + active input.
        # pactl `list short sinks` returns "<id>\t<name>..." for sink-id lookup.
        # pactl `list short sink-inputs` returns one line bound to the sink.
        _write_stub(
            bin_dir / "pactl",
            r"""
            case "$1 $2" in
              "list sinks")
                printf "Sink #42\n\tName: alsa_output.test\n\tState: RUNNING\n"
                ;;
              "list short")
                if [[ "$3" == "sinks" ]]; then
                    printf "42\talsa_output.test\tPipeWire\ts32le 2ch 48000Hz\tRUNNING\n"
                elif [[ "$3" == "sink-inputs" ]]; then
                    printf "100\tPipeWire\t-\t42\ts16le 2ch\n"
                fi
                ;;
            esac
            exit 0
            """,
        )
        # pw-cat record stub — touch the wav file (mktemp made it
        # already, just exit 0 to simulate successful capture).
        _write_stub(bin_dir / "pw-cat", "exit 0\n")
        # ffmpeg volumedetect stub — print mean_volume so awk picks it up.
        _write_stub(
            bin_dir / "ffmpeg",
            r"""
            echo "[Parsed_volumedetect_0 @ 0x55] mean_volume: -25.50 dB" >&2
            exit 0
            """,
        )

        env["HAPAX_PIN_CHECK_SINK"] = "alsa_output.test"
        result = _run_wrapper(env)

        assert result.returncode == 0, f"stderr={result.stderr}"
        assert capture.exists(), "CLI was not invoked"
        argv = capture.read_text().splitlines()
        # Verify the wrapper's hand-off shape.
        assert "pin-check" in argv
        assert "--state" in argv
        # State extracted from pactl was RUNNING.
        state_idx = argv.index("--state")
        assert argv[state_idx + 1] == "RUNNING"
        # Active input → --has-active-input flag set.
        assert "--has-active-input" in argv
        # rms-db was passed (value is the mean_volume from ffmpeg).
        assert "--rms-db" in argv
        rms_idx = argv.index("--rms-db")
        assert argv[rms_idx + 1] == "-25.50"

    def test_idle_sink_no_input_uses_no_active_input_flag(self, stub_env, tmp_path):
        env, capture, bin_dir = stub_env

        _write_stub(
            bin_dir / "pactl",
            r"""
            case "$1 $2" in
              "list sinks")
                printf "Sink #42\n\tName: alsa_output.test\n\tState: IDLE\n"
                ;;
              "list short")
                if [[ "$3" == "sinks" ]]; then
                    printf "42\talsa_output.test\tPipeWire\ts32le 2ch 48000Hz\tIDLE\n"
                elif [[ "$3" == "sink-inputs" ]]; then
                    printf ""
                fi
                ;;
            esac
            exit 0
            """,
        )
        _write_stub(bin_dir / "pw-cat", "exit 0\n")
        _write_stub(
            bin_dir / "ffmpeg",
            r'echo "[Parsed_volumedetect_0 @ 0x55] mean_volume: -90.00 dB" >&2' "\nexit 0\n",
        )

        env["HAPAX_PIN_CHECK_SINK"] = "alsa_output.test"
        result = _run_wrapper(env)

        assert result.returncode == 0, f"stderr={result.stderr}"
        argv = capture.read_text().splitlines()
        assert "--no-active-input" in argv
        assert "--has-active-input" not in argv
        # State is IDLE.
        assert "IDLE" in argv

    def test_pw_cat_failure_passes_inf_dB(self, stub_env, tmp_path):
        env, capture, bin_dir = stub_env

        _write_stub(
            bin_dir / "pactl",
            r"""
            case "$1 $2" in
              "list sinks")
                printf "Sink #42\n\tName: alsa_output.test\n\tState: RUNNING\n"
                ;;
              "list short")
                if [[ "$3" == "sinks" ]]; then
                    printf "42\talsa_output.test\tPipeWire\ts32le 2ch 48000Hz\tRUNNING\n"
                elif [[ "$3" == "sink-inputs" ]]; then
                    printf "100\tPipeWire\t-\t42\ts16le 2ch\n"
                fi
                ;;
            esac
            exit 0
            """,
        )
        # pw-cat stub fails immediately — the wrapper's fallback path
        # passes `-inf` so the detector treats it as silent.
        _write_stub(bin_dir / "pw-cat", "exit 1\n")

        env["HAPAX_PIN_CHECK_SINK"] = "alsa_output.test"
        result = _run_wrapper(env)

        assert result.returncode == 0, f"stderr={result.stderr}"
        # Wrapper logged the failure to stderr.
        assert "pw-cat record failed" in result.stderr
        # rms_db should have been passed as -inf.
        argv = capture.read_text().splitlines()
        rms_idx = argv.index("--rms-db")
        assert argv[rms_idx + 1] == "-inf"


class TestAutoFixWiring:
    def test_auto_fix_off_omits_card_args(self, stub_env, tmp_path):
        env, capture, bin_dir = stub_env

        _write_stub(
            bin_dir / "pactl",
            r"""
            case "$1 $2" in
              "list sinks")
                printf "Sink #42\n\tName: alsa_output.test\n\tState: IDLE\n"
                ;;
              "list short")
                printf ""
                ;;
            esac
            exit 0
            """,
        )
        _write_stub(bin_dir / "pw-cat", "exit 0\n")
        _write_stub(bin_dir / "ffmpeg", "exit 0\n")

        env["HAPAX_PIN_CHECK_SINK"] = "alsa_output.test"
        env["HAPAX_PIN_CHECK_AUTO_FIX"] = "0"
        result = _run_wrapper(env)

        assert result.returncode == 0
        argv = capture.read_text().splitlines()
        assert "--auto-fix" not in argv
        assert "--card" not in argv

    def test_auto_fix_on_passes_card_and_profile(self, stub_env, tmp_path):
        env, capture, bin_dir = stub_env

        _write_stub(
            bin_dir / "pactl",
            r"""
            case "$1 $2" in
              "list sinks")
                printf "Sink #42\n\tName: alsa_output.test\n\tState: RUNNING\n"
                ;;
              "list short")
                if [[ "$3" == "sinks" ]]; then
                    printf "42\talsa_output.test\tPipeWire\ts32le 2ch 48000Hz\tRUNNING\n"
                elif [[ "$3" == "sink-inputs" ]]; then
                    printf "100\tPipeWire\t-\t42\ts16le 2ch\n"
                fi
                ;;
            esac
            exit 0
            """,
        )
        _write_stub(bin_dir / "pw-cat", "exit 0\n")
        _write_stub(
            bin_dir / "ffmpeg",
            r'echo "[Parsed_volumedetect_0 @ 0x55] mean_volume: -90.00 dB" >&2' "\nexit 0\n",
        )

        env["HAPAX_PIN_CHECK_SINK"] = "alsa_output.test"
        env["HAPAX_PIN_CHECK_AUTO_FIX"] = "1"
        env["HAPAX_PIN_CHECK_CARD"] = "alsa_card.test"
        env["HAPAX_PIN_CHECK_PROFILE"] = "output:test-stereo"
        result = _run_wrapper(env)

        assert result.returncode == 0
        argv = capture.read_text().splitlines()
        assert "--auto-fix" in argv
        card_idx = argv.index("--card")
        assert argv[card_idx + 1] == "alsa_card.test"
        profile_idx = argv.index("--profile")
        assert argv[profile_idx + 1] == "output:test-stereo"
