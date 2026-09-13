"""Greps for the governed Codex Astra launcher pin."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HEADLESS = REPO_ROOT / "scripts" / "hapax-codex-headless"
INTERACTIVE = REPO_ROOT / "scripts" / "hapax-codex"
LAUNCHERS = (("headless", HEADLESS), ("interactive", INTERACTIVE))
ASTRA_MODEL_ARG = "-c 'model=\"gpt-6-astra\"'"
LEGACY_MODEL_ARG = "-c 'model=\"gpt-5.5\"'"
XHIGH_ARG = "-c 'model_reasoning_effort=\"xhigh\"'"
ASTRA_MODEL_VALUE = 'model="gpt-6-astra"'
LEGACY_MODEL_VALUE = 'model="gpt-5.5"'
XHIGH_VALUE = 'model_reasoning_effort="xhigh"'


@pytest.mark.parametrize(("launcher_name", "launcher"), LAUNCHERS)
def test_codex_launchers_pin_astra_xhigh_without_legacy_gpt55(
    launcher_name: str,
    launcher: Path,
) -> None:
    text = launcher.read_text(encoding="utf-8")
    assert text.count(ASTRA_MODEL_ARG) == 1, f"{launcher_name} must pin the Astra model arg"
    assert LEGACY_MODEL_ARG not in text, f"{launcher_name} must not retain the gpt-5.5 model arg"
    assert text.count(XHIGH_ARG) == 1, f"{launcher_name} must retain xhigh reasoning"
    assert text.index(ASTRA_MODEL_ARG) < text.index(XHIGH_ARG)


def _env_with_fake_codex(tmp_path: Path) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "codex-args.txt"
    fake_codex = bin_dir / "codex"
    fake_codex.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                'if [ "${1:-}" = "exec" ] && [[ "$*" == *HAPAX_CODEX_EXEC_AUTH_OK* ]]; then',
                "  printf '%s\\n' "
                + shlex.quote(
                    '{"type":"item.completed","item":{"type":"agent_message","text":"HAPAX_CODEX_EXEC_AUTH_OK"}}'
                ),
                "  exit 0",
                "fi",
                f"printf '%s\\n' \"$@\" > {shlex.quote(str(args_file))}",
                "exit 0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)

    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_EXEC_AUTH_TIMEOUT_SECONDS"] = "5"
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_PID_DIR"] = str(tmp_path / "headless-pids")
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_TERMINAL"] = "none"
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    return env, args_file


def _assert_astra_xhigh_args(args_file: Path) -> None:
    args = args_file.read_text(encoding="utf-8").splitlines()

    assert ASTRA_MODEL_VALUE in args
    assert LEGACY_MODEL_VALUE not in args
    assert XHIGH_VALUE in args
    assert args.index(ASTRA_MODEL_VALUE) < args.index(XHIGH_VALUE)


def test_interactive_launcher_executes_codex_with_astra_xhigh(tmp_path: Path) -> None:
    env, args_file = _env_with_fake_codex(tmp_path)

    result = subprocess.run(
        [
            str(INTERACTIVE),
            "--session",
            "cx-amber",
            "--slot",
            "alpha",
            "--cd",
            str(REPO_ROOT),
            "--terminal",
            "none",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    _assert_astra_xhigh_args(args_file)


def test_headless_launcher_executes_codex_with_astra_xhigh(tmp_path: Path) -> None:
    env, args_file = _env_with_fake_codex(tmp_path)

    result = subprocess.run(
        [
            str(HEADLESS),
            "--task",
            "task-x",
            "--no-claim",
            "--force",
            "cx-amber",
            "governed prompt",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    _assert_astra_xhigh_args(args_file)
