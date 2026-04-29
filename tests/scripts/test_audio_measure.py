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
