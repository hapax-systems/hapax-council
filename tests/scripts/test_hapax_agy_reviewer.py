"""Tests for the agy-backed review-team wrapper."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "scripts" / "hapax-agy-reviewer"


def test_agy_reviewer_invokes_sandboxed_print_mode(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.txt"
    fake_agy = bin_dir / "agy"
    fake_agy.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {calls}
printf '```yaml\\nverdict: accept\\nfindings: []\\n```\\n'
""",
        encoding="utf-8",
    )
    fake_agy.chmod(0o755)

    result = subprocess.run(
        [str(WRAPPER), "--agy-bin", str(fake_agy), "--model", "gemini-3.1-pro-preview"],
        input="diff --git a/x b/x\n+change\n",
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "verdict: accept" in result.stdout
    args = calls.read_text(encoding="utf-8")
    assert "--sandbox" in args
    assert "--print-timeout" in args
    assert "--model" in args
    assert "gemini-3.1-pro-preview" in args
    assert "--print" in args
    assert "UNIFIED DIFF" in args
    assert "no repository access" in args


def test_agy_reviewer_rejects_non_agy_binary_name(tmp_path: Path) -> None:
    fake_legacy = tmp_path / "gemini"
    fake_legacy.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_legacy.chmod(0o755)

    result = subprocess.run(
        [str(WRAPPER), "--agy-bin", str(fake_legacy)],
        input="review\n",
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 64
    assert "must point to agy" in result.stderr


def test_agy_reviewer_reports_missing_agy_binary(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(WRAPPER), "--agy-bin", str(tmp_path / "agy")],
        input="review\n",
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert "failed to launch" in result.stderr


def test_agy_reviewer_preserves_nonzero_agy_exit(tmp_path: Path) -> None:
    fake_agy = tmp_path / "agy"
    fake_agy.write_text(
        "#!/usr/bin/env bash\nprintf 'agy failed\\n' >&2\nexit 7\n",
        encoding="utf-8",
    )
    fake_agy.chmod(0o755)

    result = subprocess.run(
        [str(WRAPPER), "--agy-bin", str(fake_agy)],
        input="review\n",
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 7
    assert "agy failed" in result.stderr
