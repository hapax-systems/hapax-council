"""Tests for ``scripts/hapax-gemini-jr-team``."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
RUNNER = REPO_ROOT / "scripts" / "hapax-gemini-jr-team"


def _env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HAPAX_GEMINI_JR_ROOT"] = str(tmp_path / "jr")
    env["HAPAX_GEMINI_JR_RELAY"] = str(tmp_path / "relay" / "gemini-jr.yaml")
    env["HAPAX_GEMINI_JR_DASHBOARD"] = str(tmp_path / "dashboard" / "gemini-jr-team.md")
    return env


def test_jr_team_script_compiles() -> None:
    result = subprocess.run(
        ["python", "-m", "py_compile", str(RUNNER)],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr


def test_dry_run_uses_strict_latest_model_and_redacts_prompt(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            str(RUNNER),
            "dispatch",
            "--role",
            "jr-reviewer",
            "--task-id",
            "secret-review",
            "--title",
            "Secret review",
            "--prompt",
            "SECRET_PROMPT_VALUE",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["model"] == "gemini-3.1-pro-preview"
    assert payload["strict_latest_model"] is True
    command = payload["command"]
    assert "--strict-model" in command
    assert "gemini-3.1-pro-preview" in command
    assert "gemini-3-flash-preview" not in json.dumps(payload)
    assert "SECRET_PROMPT_VALUE" not in json.dumps(payload)
    assert "<redacted-prompt>" in command


def test_dispatch_writes_packet_relay_dashboard_and_no_prompt_metadata(tmp_path: Path) -> None:
    fake_sidecar = tmp_path / "fake-sidecar"
    calls = tmp_path / "calls.jsonl"
    fake_sidecar.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\0' "$*" >> {calls}
case "$*" in
  *"gemini-3.1-pro-preview"*"--strict-model"*) ;;
  *) echo "missing strict latest model" >&2; exit 9 ;;
esac
printf '%s\\n' 'Finding: supplied packet has one test gap.'
printf '%s\\n' 'Created execution plan for SessionEnd: 2 hook(s)'
printf '%s\\n' 'Expanding hook command: noisy-hook'
printf '%s\\n' 'Hook execution for SessionEnd: 2 hooks executed successfully'
"""
    )
    fake_sidecar.chmod(0o755)
    secret_prompt = "PRIVATE_PROMPT_SHOULD_NOT_ENTER_METADATA"

    result = subprocess.run(
        [
            str(RUNNER),
            "--sidecar-bin",
            str(fake_sidecar),
            "dispatch",
            "--role",
            "jr-test-scout",
            "--task-id",
            "packet-test-gap",
            "--title",
            "Packet test gap",
            "--prompt",
            secret_prompt,
            "--timeout",
            "5",
        ],
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    packet = Path(result.stdout.strip())
    assert packet.exists()
    assert "Finding: supplied packet has one test gap." in packet.read_text()
    assert "strict_latest_model: true" in packet.read_text()
    assert "Created execution plan for SessionEnd" not in packet.read_text()
    assert "Expanding hook command:" not in packet.read_text()
    assert "Hook execution for SessionEnd" not in packet.read_text()
    metadata = (tmp_path / "jr" / "metadata.jsonl").read_text()
    assert "PRIVATE_PROMPT_SHOULD_NOT_ENTER_METADATA" not in metadata
    record = json.loads(metadata.splitlines()[0])
    assert record["model"] == "gemini-3.1-pro-preview"
    assert record["strict_latest_model"] is True
    assert record["status"] == "ready_for_senior_review"
    relay = tmp_path / "relay" / "gemini-jr.yaml"
    dashboard = tmp_path / "dashboard" / "gemini-jr-team.md"
    assert relay.exists()
    assert dashboard.exists()
    assert "authority: no_repo_edits_no_claims_no_prs_no_merge_no_deploy" in relay.read_text()
    assert "Gemini CLI is a packet-only junior support team" in dashboard.read_text()
    call_line = calls.read_text()
    assert "--strict-model" in call_line
    assert "gemini-3.1-pro-preview" in call_line
    assert "gemini-3-flash-preview" not in call_line
