"""Tests for scripts/audio-topology-check.sh (#134 audio pathways core).

The script calls ``pw-cli list-objects Node`` and compares the output to
the expected hapax audio topology. We exercise it by pointing the
``AUDIO_TOPOLOGY_CHECK_PW_CLI`` env override at a tiny shim script that
emits synthetic pw-cli output, so the tests do not require a running
PipeWire instance.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "audio-topology-check.sh"


def _write_fake_pw_cli(tmp_path: Path, payload: str) -> Path:
    """Write a shim that prints ``payload`` when called with any args."""
    shim = tmp_path / "pw-cli-fake"
    # The shim has to print ONLY when invoked with ``list-objects Node`` so
    # that ``command -v`` / availability checks (no args) still succeed.
    shim.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == 'list-objects' && \"${2:-}\" == 'Node' ]]; then\n"
        f"    cat <<'EOF'\n{payload}\nEOF\n"
        "fi\n"
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return shim


def _run(shim: Path, *, strict_hw: str = "0") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["AUDIO_TOPOLOGY_CHECK_PW_CLI"] = str(shim)
    env["AUDIO_TOPOLOGY_CHECK_STRICT_HW"] = strict_hw
    return subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


EXPECTED_TOPOLOGY_OUTPUT = """
 id 52, type PipeWire:Interface:Node/3
    node.name = "echo_cancel_capture"
    media.class = "Audio/Source"
 id 53, type PipeWire:Interface:Node/3
    node.name = "yeti_cancelled"
 id 54, type PipeWire:Interface:Node/3
    node.name = "echo_cancel_sink"
    media.class = "Audio/Sink"
 id 55, type PipeWire:Interface:Node/3
    node.name = "alsa_input.usb-Blue_Microphones_Yeti-00"
 id 56, type PipeWire:Interface:Node/3
    node.name = "alsa_input.usb-PreSonus_Studio_24c-00"
 id 57, type PipeWire:Interface:Node/3
    node.name = "hapax-ytube-ducked"
"""


MISSING_AEC_OUTPUT = """
 id 55, type PipeWire:Interface:Node/3
    node.name = "alsa_input.usb-Blue_Microphones_Yeti-00"
 id 56, type PipeWire:Interface:Node/3
    node.name = "alsa_input.usb-PreSonus_Studio_24c-00"
"""


def test_expected_topology_passes(tmp_path: Path) -> None:
    shim = _write_fake_pw_cli(tmp_path, EXPECTED_TOPOLOGY_OUTPUT)
    result = _run(shim)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_missing_echo_cancel_reports_delta(tmp_path: Path) -> None:
    shim = _write_fake_pw_cli(tmp_path, MISSING_AEC_OUTPUT)
    result = _run(shim)
    assert result.returncode == 1
    assert "MISSING (required)" in result.stdout
    assert "echo_cancel_capture" in result.stdout


def test_empty_output_errors_cleanly(tmp_path: Path) -> None:
    shim = _write_fake_pw_cli(tmp_path, "")
    result = _run(shim)
    # Exit code 3 = pw-cli returned nothing (PipeWire not running).
    assert result.returncode == 3
    assert "no Node objects" in result.stderr or "no Node objects" in result.stdout


def test_missing_hardware_warns_when_not_strict(tmp_path: Path) -> None:
    # AEC present, hardware absent — should still pass (status 0) with a warning.
    payload = """
 id 52, type PipeWire:Interface:Node/3
    node.name = "echo_cancel_capture"
 id 53, type PipeWire:Interface:Node/3
    node.name = "yeti_cancelled"
 id 54, type PipeWire:Interface:Node/3
    node.name = "echo_cancel_sink"
 id 55, type PipeWire:Interface:Node/3
    node.name = "hapax-ytube-ducked"
"""
    shim = _write_fake_pw_cli(tmp_path, payload)
    result = _run(shim, strict_hw="0")
    assert result.returncode == 0
    assert "WARN" in result.stdout
    assert "Blue_Microphones_Yeti" in result.stdout


def test_missing_hardware_fails_when_strict(tmp_path: Path) -> None:
    payload = """
 id 52, type PipeWire:Interface:Node/3
    node.name = "echo_cancel_capture"
 id 53, type PipeWire:Interface:Node/3
    node.name = "yeti_cancelled"
 id 54, type PipeWire:Interface:Node/3
    node.name = "echo_cancel_sink"
 id 55, type PipeWire:Interface:Node/3
    node.name = "hapax-ytube-ducked"
"""
    shim = _write_fake_pw_cli(tmp_path, payload)
    result = _run(shim, strict_hw="1")
    assert result.returncode == 2
    assert "MISSING (hardware)" in result.stdout


@pytest.mark.parametrize(
    "missing_optional,expected_in_stdout",
    [
        ("yeti_cancelled", "MISSING (optional)"),
        ("hapax-ytube-ducked", "MISSING (optional)"),
    ],
)
def test_missing_optional_reports_but_still_succeeds(
    tmp_path: Path, missing_optional: str, expected_in_stdout: str
) -> None:
    # Build a payload that omits exactly one optional node.
    all_nodes = {
        "echo_cancel_capture",
        "yeti_cancelled",
        "echo_cancel_sink",
        "hapax-ytube-ducked",
        "Blue_Microphones_Yeti",
        "PreSonus_Studio_24c",
    }
    present = all_nodes - {missing_optional}
    payload = "\n".join(
        f' id {i}, type PipeWire:Interface:Node/3\n    node.name = "{n}"'
        for i, n in enumerate(sorted(present), start=50)
    )
    shim = _write_fake_pw_cli(tmp_path, payload)
    result = _run(shim)
    assert result.returncode == 0  # optional missing does not fail
    assert expected_in_stdout in result.stdout
    assert missing_optional in result.stdout
