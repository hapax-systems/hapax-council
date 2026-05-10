"""Regression coverage for scripts/audio-measure.sh."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "audio-measure.sh"


def _write_stub(path: Path, body: str) -> None:
    path.write_text(f"#!/usr/bin/env bash\n{textwrap.dedent(body).strip()}\n", encoding="utf-8")
    path.chmod(0o755)


def test_audio_measure_launches_background_pw_cat_and_analyzes_capture(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    invocation = tmp_path / "pw-cat-invocation"

    _write_stub(
        bin_dir / "pw-cli",
        """
        if [[ "$*" == "ls Node" ]]; then
          cat <<'EOF'
        id 82, type PipeWire:Interface:Node/3
            node.name = "hapax-broadcast-normalized"
            media.class = "Audio/Source"
        EOF
          exit 0
        fi
        exit 1
        """,
    )
    _write_stub(
        bin_dir / "pactl",
        """
        if [[ "$*" == "list short sources" ]]; then
          printf '42\\thapax-broadcast-normalized\\tPipeWire\\ts16le 2ch 48000Hz\\tRUNNING\\n'
          exit 0
        fi
        exit 1
        """,
    )
    _write_stub(
        bin_dir / "pw-cat",
        f"""
        printf '%s\\n' "$@" > {invocation}
        out=""
        while [[ $# -gt 0 ]]; do
          if [[ "$1" == "--record" ]]; then
            out="$2"
            shift 2
            continue
          fi
          shift
        done
        head -c 4096 /dev/zero > "$out"
        sleep 2
        """,
    )
    _write_stub(
        bin_dir / "ffmpeg",
        """
        cat >&2 <<'EOF'
        [Parsed_ebur128_0 @ 0x1] Summary:
            I:         -14.0 LUFS
            LRA:         1.0 LU
            Threshold:  -24.0 LUFS
            Peak:       -1.2 dBFS
        EOF
        """,
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    result = subprocess.run(
        [str(SCRIPT), "1", "hapax-test-node"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert invocation.exists()
    assert "--target" in invocation.read_text(encoding="utf-8")
    assert "hapax-test-node.monitor" in invocation.read_text(encoding="utf-8")
    assert "Hapax broadcast loudness measurement" in result.stdout


def test_audio_measure_targets_requested_node_when_it_is_already_a_source(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    invocation = tmp_path / "pw-cat-invocation"

    _write_stub(
        bin_dir / "pw-cli",
        """
        if [[ "$*" == "ls Node" ]]; then
          cat <<'EOF'
        id 82, type PipeWire:Interface:Node/3
            node.name = "hapax-broadcast-normalized"
            media.class = "Audio/Source"
        EOF
          exit 0
        fi
        exit 1
        """,
    )
    _write_stub(
        bin_dir / "pactl",
        """
        if [[ "$*" == "list short sources" ]]; then
          printf '42\\thapax-broadcast-normalized\\tPipeWire\\ts16le 2ch 48000Hz\\tRUNNING\\n'
          exit 0
        fi
        exit 1
        """,
    )
    _write_stub(
        bin_dir / "pw-cat",
        f"""
        printf '%s\\n' "$@" > {invocation}
        out=""
        while [[ $# -gt 0 ]]; do
          if [[ "$1" == "--record" ]]; then
            out="$2"
            shift 2
            continue
          fi
          shift
        done
        head -c 4096 /dev/zero > "$out"
        sleep 2
        """,
    )
    _write_stub(
        bin_dir / "ffmpeg",
        """
        cat >&2 <<'EOF'
        [Parsed_ebur128_0 @ 0x1] Summary:
            I:         -14.0 LUFS
            LRA:         1.0 LU
            Threshold:  -24.0 LUFS
            Peak:       -1.2 dBFS
        EOF
        """,
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    result = subprocess.run(
        [str(SCRIPT), "1", "hapax-broadcast-normalized"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert invocation.exists()
    target_line = invocation.read_text(encoding="utf-8")
    assert "--target" in target_line
    assert "hapax-broadcast-normalized\n" in target_line
    assert "hapax-broadcast-normalized.monitor" not in target_line
