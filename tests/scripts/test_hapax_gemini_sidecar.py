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


# --- jr-test-scout coverage gaps (audit 20260503T041448Z) ----------------


def test_prompt_and_prompt_file_mutex_exits_with_error(tmp_path: Path) -> None:
    """Gap 9: ``--prompt`` and ``--prompt-file`` together must exit with error."""

    prompt_file = tmp_path / "p.txt"
    prompt_file.write_text("from file", encoding="utf-8")
    result = subprocess.run(
        [
            str(WRAPPER),
            "--prompt",
            "from arg",
            "--prompt-file",
            str(prompt_file),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "--prompt and --prompt-file are mutually exclusive" in result.stderr


def test_subprocess_timeout_yields_exit_code_124(tmp_path: Path) -> None:
    """Gap 6: ``subprocess.TimeoutExpired`` must produce ``final_code = 124``.

    Fake gemini binary sleeps longer than the sidecar's --timeout; the
    wrapper kills the subprocess and reports 124 (canonical Linux
    timeout exit). Output stream must contain the timeout marker.
    """

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_gemini = bin_dir / "gemini"
    fake_gemini.write_text(
        """#!/usr/bin/env bash
sleep 5
exit 0
"""
    )
    fake_gemini.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_GEMINI_SIDECAR_STRICT_MODEL"] = "1"  # one attempt only

    result = subprocess.run(
        [
            str(WRAPPER),
            "--prompt",
            "noop",
            "--timeout",
            "0.5",
            "--metadata-log",
            str(tmp_path / "metadata.jsonl"),
            "--artifact-dir",
            str(tmp_path / "artifacts"),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 124
    assert "timeout after" in result.stderr
    metadata = json.loads((tmp_path / "metadata.jsonl").read_text().splitlines()[0])
    assert metadata["exit_code"] == 124


def test_missing_binary_yields_exit_code_2(tmp_path: Path) -> None:
    """Gap 7: ``OSError`` (binary not found) must produce ``final_code = 2``."""

    env = os.environ.copy()
    env.pop("HAPAX_GEMINI_SIDECAR_STRICT_MODEL", None)

    result = subprocess.run(
        [
            str(WRAPPER),
            "--gemini-bin",
            str(tmp_path / "no-such-binary"),
            "--prompt",
            "noop",
            "--strict-model",
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
    assert "failed to launch" in result.stderr
    metadata = json.loads((tmp_path / "metadata.jsonl").read_text().splitlines()[0])
    assert metadata["exit_code"] == 2


def test_global_timeout_during_fallback_yields_124(tmp_path: Path) -> None:
    """Gap 8: global timeout exhaustion across fallback attempts → 124.

    Fake gemini completes the first attempt in ~0.6s with a 429 marker
    on stderr (fallbackable=True), so the wrapper enters the second
    iteration with ~0.4s of budget remaining. The fake's second
    invocation runs with the reduced ``remaining_timeout`` and is
    killed by ``subprocess.run``'s timeout, producing the canonical
    Linux 124 exit. Two attempt records land in metadata.

    Note: the ``remaining_timeout <= 0`` short-circuit branch in the
    wrapper is hard to hit deterministically from a subprocess test
    (it requires the post-attempt clock to have advanced past the
    deadline at loop-top, which depends on scheduler quantum). This
    test pins the broader contract: "global budget exhaustion across
    multiple fallback attempts → final_code 124". The
    TimeoutExpired-on-second-attempt path is the most reliably
    reachable equivalent.
    """

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_gemini = bin_dir / "gemini"
    fake_gemini.write_text(
        """#!/usr/bin/env bash
printf '429 quota exceeded; would fall back\\n' >&2
sleep 0.6
exit 1
"""
    )
    fake_gemini.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    result = subprocess.run(
        [
            str(WRAPPER),
            "--prompt",
            "noop",
            "--timeout",
            "1.0",
            "--metadata-log",
            str(tmp_path / "metadata.jsonl"),
            "--artifact-dir",
            str(tmp_path / "artifacts"),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 124
    metadata = json.loads((tmp_path / "metadata.jsonl").read_text().splitlines()[0])
    assert metadata["exit_code"] == 124
    # First attempt: fallbackable (marker on stderr, exit 1).
    # Second attempt: 124 from sub-budget exhaustion.
    assert len(metadata["attempts"]) == 2
    assert metadata["attempts"][0]["exit_code"] == 1
    assert metadata["attempts"][0]["fallbackable"] is True
    assert metadata["attempts"][-1]["exit_code"] == 124


def test_all_fallback_markers_trigger_fallback(tmp_path: Path) -> None:
    """Gap 10: every entry in ``FALLBACK_MARKERS`` must trigger fallback.

    Only ``429`` is exercised by the existing capacity-fallback test.
    Walk the full marker list (capacity / daily usage limit / does not
    exist / model not found / not available / quota / rate limit /
    resource_exhausted / too many requests). Each must produce two
    attempts (initial pro-preview, then auto fallback).
    """

    markers = [
        "429 explicit",
        "capacity exhausted",
        "daily usage limit reached",
        "model does not exist",
        "model not found at this version",
        "not available right now",
        "quota exhausted for project",
        "rate limit hit",
        "RESOURCE_EXHAUSTED upstream",
        "too many requests, slow down",
    ]
    for marker in markers:
        bin_dir = tmp_path / f"bin-{abs(hash(marker))}"
        bin_dir.mkdir()
        fake_gemini = bin_dir / "gemini"
        fake_gemini.write_text(
            f"""#!/usr/bin/env bash
if [[ "$*" == *"--model"* ]]; then
  printf '%s\\n' '{marker}' >&2
  exit 1
fi
printf '%s\\n' 'auto route ok'
exit 0
"""
        )
        fake_gemini.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env['PATH']}"

        metadata_path = tmp_path / f"metadata-{abs(hash(marker))}.jsonl"
        result = subprocess.run(
            [
                str(WRAPPER),
                "--prompt",
                "noop",
                "--metadata-log",
                str(metadata_path),
                "--artifact-dir",
                str(tmp_path / f"artifacts-{abs(hash(marker))}"),
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0, f"marker={marker!r} stderr={result.stderr}"
        metadata = json.loads(metadata_path.read_text().splitlines()[0])
        assert metadata["fallback_selected"] == "auto", f"marker={marker!r}"
        assert len(metadata["attempts"]) == 2, f"marker={marker!r}"
        assert metadata["attempts"][0]["fallbackable"] is True, f"marker={marker!r}"
