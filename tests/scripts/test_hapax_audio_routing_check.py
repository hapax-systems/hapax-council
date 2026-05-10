"""Regression tests for ``scripts/hapax-audio-routing-check``.

The check script validates the live PipeWire graph. These tests run it against
synthetic ``pw-link`` output so parser behavior can be pinned without requiring
audio hardware in CI.
"""

from __future__ import annotations

import os
import stat
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-audio-routing-check"


def _base_graph(extra_tap_inputs: str = "") -> str:
    tap_inputs = (
        "|<- hapax-l12-evilpet-playback:output_FL\n"
        "|<- hapax-l12-usb-return-playback:output_FL\n"
        f"{extra_tap_inputs}"
    )
    mpc_refs = "\n".join(f"Akai Professional MPC Live III:playback_AUX{i}" for i in range(10))
    return textwrap.dedent(f"""
    alsa_input.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.multichannel-input:capture_AUX8
    |-> hapax-l12-usb-return-capture:input_AUX8
    alsa_input.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.multichannel-input:capture_AUX9
    |-> hapax-l12-usb-return-capture:input_AUX9
    alsa_input.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.multichannel-input:capture_AUX10
    |-> hapax-l12-usb-return-capture:input_AUX10
    alsa_input.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.multichannel-input:capture_AUX11
    |-> hapax-l12-usb-return-capture:input_AUX11
    output.loopback.sink.role.broadcast:output_FL
    |-> hapax-voice-fx-capture:playback_FL
hapax-voice-fx-playback:output_FL
|-> hapax-loudnorm-capture:playback_FL
hapax-loudnorm-playback:output_FL
|-> Akai Professional MPC Live III:playback_AUX2
hapax-broadcast-normalized:capture_FL
|-> hapax-obs-broadcast-remap-capture:playback_FL
hapax-obs-broadcast-remap:capture_FL
|-> OBS:input_FL
{mpc_refs}
hapax-l12-evilpet-playback:output_FL
|-> hapax-livestream-tap:playback_FL
hapax-l12-usb-return-playback:output_FL
|-> hapax-livestream-tap:playback_FR
hapax-broadcast-master:monitor_FL
|-> hapax-livestream:playback_FL
hapax-livestream-tap:playback_FL
{tap_inputs}|-> hapax-broadcast-master:playback_FL
    hapax-livestream-tap:playback_FR
    |<- hapax-l12-evilpet-playback:output_FR
    |<- hapax-l12-usb-return-playback:output_FR
    |-> hapax-broadcast-master:playback_FR
    """).strip()


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run_with_graph(tmp_path: Path, graph: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

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

    home = tmp_path / "home"
    (home / ".config" / "pipewire" / "pipewire.conf.d").mkdir(parents=True)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(home),
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
    assert "livestream-tap has only L12 inputs" in result.stdout
    assert "unexpected source" not in result.stdout


def test_tap_input_parser_fails_direct_non_l12_input(tmp_path: Path) -> None:
    result = _run_with_graph(
        tmp_path,
        _base_graph("|<- hapax-direct-bypass-playback:output_FL\n"),
    )

    assert result.returncode == 1
    assert "livestream-tap has only L12 inputs" in result.stdout
    assert "hapax-direct-bypass-playback:output_FL" in result.stdout


def test_l12_wet_return_capture_requires_upstream_aux_links(tmp_path: Path) -> None:
    graph = "\n".join(
        line
        for line in _base_graph().splitlines()
        if "capture_AUX8" not in line and "input_AUX8" not in line
    )

    result = _run_with_graph(tmp_path, graph)

    assert result.returncode == 1
    assert "L-12 AUX8 → l12-usb-return-capture linked" in result.stdout
    assert "MISSING" in result.stdout
