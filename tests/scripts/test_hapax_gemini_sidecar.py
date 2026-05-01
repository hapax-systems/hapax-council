"""Tests for ``scripts/hapax-gemini-sidecar``."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
WRAPPER = REPO_ROOT / "scripts" / "hapax-gemini-sidecar"


def test_sidecar_script_compiles() -> None:
    result = subprocess.run(
        ["python", "-m", "py_compile", str(WRAPPER)],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr


def test_dry_run_uses_plan_mode_default_model_and_guardrails(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            str(WRAPPER),
            "--dry-run",
            "--mode",
            "reviewer",
            "--prompt",
            "Review this patch.",
            "--metadata-log",
            str(tmp_path / "metadata.jsonl"),
            "--artifact-dir",
            str(tmp_path / "artifacts"),
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    command = payload["command"]
    assert command[:3] == ["gemini", "--model", "gemini-3.1-pro-preview"]
    assert "--approval-mode" in command
    assert "plan" in command
    assert "--output-format" in command
    assert "text" in command
    assert "--yolo" not in command
    assert "auto_edit" not in command
    assert "No file edits" in payload["prompt"]
    assert "Codex remains implementation owner" in payload["prompt"]
    assert "read-only sidecar reviewer" in payload["prompt"]
    assert payload["fallback_models"][:2] == ["gemini-3.1-pro-preview", "auto"]


def test_capacity_failure_falls_back_to_auto_without_logging_prompt(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.jsonl"
    fake_gemini = bin_dir / "gemini"
    fake_gemini.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\0' \"$*\" >> {calls}
if printf '%s\\n' \"$*\" | grep -q 'gemini-3.1-pro-preview'; then
  printf '%s\\n' '429 quota exceeded for pro' >&2
  exit 1
fi
printf '%s\\n' 'auto route ok'
"""
    )
    fake_gemini.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    secret_prompt = "Summarize this private-looking token: SECRET_PROMPT_VALUE"

    result = subprocess.run(
        [
            str(WRAPPER),
            "--mode",
            "large-context-summarizer",
            "--prompt",
            secret_prompt,
            "--metadata-log",
            str(tmp_path / "metadata.jsonl"),
            "--artifact-dir",
            str(tmp_path / "artifacts"),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "auto route ok\n"
    call_lines = [line for line in calls.read_text().split("\0") if line]
    assert len(call_lines) == 2
    assert "gemini-3.1-pro-preview" in call_lines[0]
    assert "--model" not in call_lines[1]
    metadata = json.loads((tmp_path / "metadata.jsonl").read_text().splitlines()[0])
    assert metadata["model_requested"] == "gemini-3.1-pro-preview"
    assert metadata["fallback_selected"] == "auto"
    assert metadata["exit_code"] == 0
    assert len(metadata["attempts"]) == 2
    assert "SECRET_PROMPT_VALUE" not in json.dumps(metadata)
    artifact_path = Path(metadata["artifact_path"])
    assert artifact_path.exists()
    assert "auto route ok" in artifact_path.read_text()


def test_non_capacity_error_does_not_fallback(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.txt"
    fake_gemini = bin_dir / "gemini"
    fake_gemini.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\0' \"$*\" >> {calls}
printf '%s\\n' 'syntax failure unrelated to model availability' >&2
exit 2
"""
    )
    fake_gemini.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    result = subprocess.run(
        [
            str(WRAPPER),
            "--prompt",
            "Review",
            "--metadata-log",
            str(tmp_path / "metadata.jsonl"),
            "--artifact-dir",
            str(tmp_path / "artifacts"),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 2
    assert len([line for line in calls.read_text().split("\0") if line]) == 1
    metadata = json.loads((tmp_path / "metadata.jsonl").read_text().splitlines()[0])
    assert metadata["fallback_selected"] == "gemini-3.1-pro-preview"
    assert metadata["attempts"] == [
        {
            "exit_code": 2,
            "fallbackable": False,
            "model": "gemini-3.1-pro-preview",
        }
    ]


def test_strict_model_disables_lower_capability_fallback(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.jsonl"
    fake_gemini = bin_dir / "gemini"
    fake_gemini.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\0' "$*" >> {calls}
printf '%s\\n' '429 quota exceeded for pro' >&2
exit 1
"""
    )
    fake_gemini.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    result = subprocess.run(
        [
            str(WRAPPER),
            "--strict-model",
            "--mode",
            "reviewer",
            "--prompt",
            "Review without fallback.",
            "--metadata-log",
            str(tmp_path / "metadata.jsonl"),
            "--artifact-dir",
            str(tmp_path / "artifacts"),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 1
    call_lines = [line for line in calls.read_text().split("\0") if line]
    assert len(call_lines) == 1
    assert "gemini-3.1-pro-preview" in call_lines[0]
    assert "gemini-3-flash-preview" not in call_lines[0]
    metadata = json.loads((tmp_path / "metadata.jsonl").read_text().splitlines()[0])
    assert metadata["fallback_selected"] == "gemini-3.1-pro-preview"
    assert metadata["attempts"] == [
        {
            "exit_code": 1,
            "fallbackable": True,
            "model": "gemini-3.1-pro-preview",
        }
    ]


def test_strict_model_env_disables_lower_capability_fallback(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.jsonl"
    fake_gemini = bin_dir / "gemini"
    fake_gemini.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\0' "$*" >> {calls}
printf '%s\\n' '429 quota exceeded for pro' >&2
exit 1
"""
    )
    fake_gemini.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_GEMINI_SIDECAR_STRICT_MODEL"] = "1"

    result = subprocess.run(
        [
            str(WRAPPER),
            "--mode",
            "reviewer",
            "--prompt",
            "Review without fallback.",
            "--metadata-log",
            str(tmp_path / "metadata.jsonl"),
            "--artifact-dir",
            str(tmp_path / "artifacts"),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 1
    call_lines = [line for line in calls.read_text().split("\0") if line]
    assert len(call_lines) == 1
    assert "gemini-3.1-pro-preview" in call_lines[0]
    metadata = json.loads((tmp_path / "metadata.jsonl").read_text().splitlines()[0])
    assert metadata["attempts"] == [
        {
            "exit_code": 1,
            "fallbackable": True,
            "model": "gemini-3.1-pro-preview",
        }
    ]
