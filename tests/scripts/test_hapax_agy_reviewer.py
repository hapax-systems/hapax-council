"""Tests for the agy-backed review-team wrapper."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "scripts" / "hapax-agy-reviewer"


def test_agy_reviewer_invokes_sandboxed_print_mode(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.txt"
    cwd_file = tmp_path / "cwd.txt"
    home_file = tmp_path / "home.txt"
    prompt_copy = tmp_path / "prompt.md"
    secret_file = tmp_path / "secret.txt"
    operator_home = tmp_path / "operator-home"
    fake_agy = bin_dir / "agy"
    fake_agy.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {calls}
pwd > {cwd_file}
cp review-dossier.md {prompt_copy}
printf '%s\\n' "$HOME" > {home_file}
printf '%s\\n' "${{HAPAX_SHOULD_NOT_LEAK:-unset}}" > {secret_file}
printf '```yaml\\nverdict: accept\\nfindings: []\\n```\\n'
""",
        encoding="utf-8",
    )
    fake_agy.chmod(0o755)

    env = {**os.environ, "HAPAX_SHOULD_NOT_LEAK": "secret", "HOME": str(operator_home)}
    result = subprocess.run(
        [str(WRAPPER), "--agy-bin", str(fake_agy), "--model", "gemini-3.1-pro-preview"],
        input="diff --git a/x b/x\n+change\n",
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "verdict: accept" in result.stdout
    args = calls.read_text(encoding="utf-8")
    assert "--sandbox" in args
    assert "--log-file" in args
    assert "--print-timeout" in args
    assert "--model" in args
    assert "gemini-3.1-pro-preview" in args
    assert "--print" in args
    assert "Read ./review-dossier.md" in args
    assert "diff --git a/x b/x" not in args
    prompt = prompt_copy.read_text(encoding="utf-8")
    assert "UNIFIED DIFF" in prompt
    assert "no repository access" in prompt
    assert "Do not inspect files" in prompt
    assert "Your entire stdout must be exactly one fenced yaml code block" in prompt
    assert "must be nested by lens id" in prompt
    assert "checklist item slugs" in prompt
    assert "directly under checklist" in prompt
    assert "Never emit legacy" in prompt
    assert "minor_finding" in prompt
    assert "severity, lens, file, line, title, and detail" in prompt
    assert "diff --git a/x b/x" in prompt
    assert not cwd_file.read_text(encoding="utf-8").strip().startswith(str(REPO_ROOT))
    assert home_file.read_text(encoding="utf-8").strip() != str(operator_home)
    assert secret_file.read_text(encoding="utf-8").strip() == "unset"


def test_agy_reviewer_spools_large_dossier_out_of_argv(tmp_path: Path) -> None:
    fake_agy = tmp_path / "agy"
    arg_lengths = tmp_path / "arg-lengths.txt"
    prompt_bytes = tmp_path / "prompt-bytes.txt"
    fake_agy.write_text(
        f"""#!/usr/bin/env bash
for arg in "$@"; do printf '%s\\n' "${{#arg}}"; done > {arg_lengths}
wc -c < review-dossier.md > {prompt_bytes}
printf '```yaml\\nverdict: accept\\nfindings: []\\n```\\n'
""",
        encoding="utf-8",
    )
    fake_agy.chmod(0o755)
    large_dossier = "diff --git a/x b/x\n+" + ("x" * 2_500_000)

    result = subprocess.run(
        [str(WRAPPER), "--agy-bin", str(fake_agy)],
        input=large_dossier,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert max(int(line) for line in arg_lengths.read_text(encoding="utf-8").splitlines()) < 1000
    assert int(prompt_bytes.read_text(encoding="utf-8")) > len(large_dossier)


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
    assert "absolute path named agy" in result.stderr


def test_agy_reviewer_rejects_path_lookup_for_agy() -> None:
    result = subprocess.run(
        [str(WRAPPER), "--agy-bin", "agy"],
        input="review\n",
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 64
    assert "absolute path named agy" in result.stderr


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
    assert "install agy or pass --agy-bin /absolute/path/to/agy" in result.stderr


def test_agy_reviewer_reports_missing_configured_default_agy_binary(tmp_path: Path) -> None:
    env = {**os.environ, "HAPAX_AGY_BIN": str(tmp_path / "agy")}
    result = subprocess.run(
        [str(WRAPPER)],
        input="review\n",
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 2
    assert "failed to launch" in result.stderr
    assert "install agy or pass --agy-bin /absolute/path/to/agy" in result.stderr


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
