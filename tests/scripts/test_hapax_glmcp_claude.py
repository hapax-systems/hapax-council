"""Tests for the GLM Coding Plan Claude Code launcher."""

from __future__ import annotations

import os
import subprocess
import textwrap
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-glmcp-claude"


def _write_executable(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body), encoding="utf-8")
    path.chmod(0o755)


def _base_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["HOME"] = str(tmp_path / "home")
    return env, bin_dir


def _install_pass_stub(
    bin_dir: Path,
    token: str = "test-secret-token",
    entry: str = "glmcp/api-key",
) -> None:
    _write_executable(
        bin_dir / "pass",
        f"""
        if [[ "$1" == "show" && "$2" == "{entry}" ]]; then
          printf '%s\\n' {token!r}
          exit 0
        fi
        printf 'missing entry: %s\\n' "$2" >&2
        exit 1
        """,
    )


def test_check_mode_sets_glm_52_environment_without_printing_secret(tmp_path: Path) -> None:
    env, bin_dir = _base_env(tmp_path)
    _install_pass_stub(bin_dir)
    env_file = tmp_path / "claude-env.txt"
    _write_executable(
        bin_dir / "claude",
        f"""
        if [[ "$1" == "--version" ]]; then
          printf 'ANTHROPIC_BASE_URL=%s\\n' "$ANTHROPIC_BASE_URL" > {env_file}
          printf 'ANTHROPIC_DEFAULT_OPUS_MODEL=%s\\n' "$ANTHROPIC_DEFAULT_OPUS_MODEL" >> {env_file}
          printf 'ANTHROPIC_DEFAULT_SONNET_MODEL=%s\\n' "$ANTHROPIC_DEFAULT_SONNET_MODEL" >> {env_file}
          printf 'ANTHROPIC_DEFAULT_HAIKU_MODEL=%s\\n' "$ANTHROPIC_DEFAULT_HAIKU_MODEL" >> {env_file}
          printf 'CLAUDE_CODE_AUTO_COMPACT_WINDOW=%s\\n' "$CLAUDE_CODE_AUTO_COMPACT_WINDOW" >> {env_file}
          printf 'HAPAX_LLM_PROVIDER=%s\\n' "$HAPAX_LLM_PROVIDER" >> {env_file}
          printf 'HAPAX_GLMCP_SECRET_ENTRY_PRESENT=%s\\n' "${{HAPAX_GLMCP_SECRET_ENTRY:+yes}}" >> {env_file}
          printf 'TOKEN_PRESENT=%s\\n' "${{ANTHROPIC_AUTH_TOKEN:+yes}}" >> {env_file}
          printf 'claude 0.0-test\\n'
          exit 0
        fi
        exit 9
        """,
    )

    result = subprocess.run(
        [str(SCRIPT), "--check"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "+ set -x" not in result.stderr
    assert "ANTHROPIC_AUTH_TOKEN" not in result.stderr
    assert "test-secret-token" not in result.stdout
    assert "test-secret-token" not in result.stderr
    launched_env = env_file.read_text(encoding="utf-8")
    assert "ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic" in launched_env
    assert "ANTHROPIC_DEFAULT_OPUS_MODEL=glm-5.2[1m]" in launched_env
    assert "ANTHROPIC_DEFAULT_SONNET_MODEL=glm-5.2[1m]" in launched_env
    assert "ANTHROPIC_DEFAULT_HAIKU_MODEL=glm-4.5-air" in launched_env
    assert "CLAUDE_CODE_AUTO_COMPACT_WINDOW=1000000" in launched_env
    assert "HAPAX_LLM_PROVIDER=zai-glm-coding-plan" in launched_env
    assert "HAPAX_GLMCP_SECRET_ENTRY_PRESENT=\n" in launched_env
    assert "HAPAX_GLMCP_SECRET_ENTRY_PRESENT=yes" not in launched_env
    assert "TOKEN_PRESENT=\n" in launched_env
    assert "TOKEN_PRESENT=yes" not in launched_env


def test_exec_path_preserves_claude_arguments(tmp_path: Path) -> None:
    env, bin_dir = _base_env(tmp_path)
    _install_pass_stub(bin_dir)
    args_file = tmp_path / "claude-args.txt"
    env_file = tmp_path / "claude-env.txt"
    _write_executable(
        bin_dir / "claude",
        f"""
        printf '%s\\n' "$@" > {args_file}
        printf 'TOKEN_PRESENT=%s\\n' "${{ANTHROPIC_AUTH_TOKEN:+yes}}" > {env_file}
        exit 0
        """,
    )

    result = subprocess.run(
        [str(SCRIPT), "-p", "--no-session-persistence", "hello world"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert args_file.read_text(encoding="utf-8").splitlines() == [
        "-p",
        "--no-session-persistence",
        "hello world",
    ]
    assert env_file.read_text(encoding="utf-8") == "TOKEN_PRESENT=yes\n"


def test_launcher_uses_exact_positional_argument_expansion() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'exec claude "$@"' in text
    assert '"$ @"' not in text


def test_exec_path_propagates_claude_failure(tmp_path: Path) -> None:
    env, bin_dir = _base_env(tmp_path)
    _install_pass_stub(bin_dir)
    _write_executable(
        bin_dir / "claude",
        """
        printf 'provider failed\\n' >&2
        exit 42
        """,
    )

    result = subprocess.run(
        [str(SCRIPT), "-p", "hello world"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 42
    assert "provider failed" in result.stderr


def test_rejects_non_glm_52_primary_model_by_default(tmp_path: Path) -> None:
    env, bin_dir = _base_env(tmp_path)
    _install_pass_stub(bin_dir)
    _write_executable(bin_dir / "claude", "exit 0\n")
    env["HAPAX_GLMCP_MODEL"] = "glm-4.5"

    result = subprocess.run(
        [str(SCRIPT), "--check"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 2
    assert "refusing primary model 'glm-4.5'" in result.stderr


def test_allows_non_glm_52_primary_model_only_with_explicit_gate(tmp_path: Path) -> None:
    env, bin_dir = _base_env(tmp_path)
    _install_pass_stub(bin_dir)
    _write_executable(bin_dir / "claude", "printf 'claude 0.0-test\\n'\n")
    env["HAPAX_GLMCP_MODEL"] = "glm-4.5"
    env["HAPAX_GLMCP_ALLOW_NON_52"] = "1"

    result = subprocess.run(
        [str(SCRIPT), "--check"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "primary_model=glm-4.5" in result.stdout


def test_rejects_secret_entry_override_without_gate(tmp_path: Path) -> None:
    env, bin_dir = _base_env(tmp_path)
    _install_pass_stub(bin_dir, entry="glmcp/alt-key")
    _write_executable(bin_dir / "claude", "printf 'claude 0.0-test\\n'\n")
    env["HAPAX_GLMCP_SECRET_ENTRY"] = "glmcp/alt-key"

    result = subprocess.run(
        [str(SCRIPT), "--check"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 8
    assert "refusing pass entry 'glmcp/alt-key'" in result.stderr


def test_secret_entry_override_is_limited_to_glmcp_prefix(tmp_path: Path) -> None:
    env, bin_dir = _base_env(tmp_path)
    _install_pass_stub(bin_dir, entry="other/api-key")
    _write_executable(bin_dir / "claude", "printf 'claude 0.0-test\\n'\n")
    env["HAPAX_GLMCP_SECRET_ENTRY"] = "other/api-key"
    env["HAPAX_GLMCP_ALLOW_SECRET_ENTRY_OVERRIDE"] = "1"

    result = subprocess.run(
        [str(SCRIPT), "--check"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 8
    assert "only reads glmcp/* secrets" in result.stderr


def test_secret_entry_override_requires_exact_glmcp_slash_prefix(tmp_path: Path) -> None:
    env, bin_dir = _base_env(tmp_path)
    _install_pass_stub(bin_dir, entry="glmcp-malicious/api-key")
    _write_executable(bin_dir / "claude", "printf 'claude 0.0-test\\n'\n")
    env["HAPAX_GLMCP_SECRET_ENTRY"] = "glmcp-malicious/api-key"
    env["HAPAX_GLMCP_ALLOW_SECRET_ENTRY_OVERRIDE"] = "1"

    result = subprocess.run(
        [str(SCRIPT), "--check"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 8
    assert "only reads glmcp/* secrets" in result.stderr


def test_allows_reviewed_glmcp_secret_entry_override(tmp_path: Path) -> None:
    env, bin_dir = _base_env(tmp_path)
    _install_pass_stub(bin_dir, token="alt-secret-token", entry="glmcp/alt-key")
    _write_executable(bin_dir / "claude", "printf 'claude 0.0-test\\n'\n")
    env["HAPAX_GLMCP_SECRET_ENTRY"] = "glmcp/alt-key"
    env["HAPAX_GLMCP_ALLOW_SECRET_ENTRY_OVERRIDE"] = "1"

    result = subprocess.run(
        [str(SCRIPT), "--check"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "secret=available" in result.stdout
    assert "secret_entry=glmcp/alt-key" not in result.stdout
    assert "alt-secret-token" not in result.stdout
    assert "alt-secret-token" not in result.stderr


def test_rejects_token_endpoint_override(tmp_path: Path) -> None:
    env, bin_dir = _base_env(tmp_path)
    _install_pass_stub(bin_dir)
    _write_executable(bin_dir / "claude", "exit 0\n")
    env["HAPAX_GLMCP_ANTHROPIC_BASE_URL"] = "https://example.invalid/api/anthropic"

    result = subprocess.run(
        [str(SCRIPT), "--check"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 7
    assert "refusing base URL" in result.stderr
    assert "test-secret-token" not in result.stderr


def test_rejects_non_zai_endpoint_even_with_override_gate(tmp_path: Path) -> None:
    env, bin_dir = _base_env(tmp_path)
    _install_pass_stub(bin_dir)
    _write_executable(bin_dir / "claude", "exit 0\n")
    env["HAPAX_GLMCP_ALLOW_BASE_URL_OVERRIDE"] = "1"
    env["HAPAX_GLMCP_ANTHROPIC_BASE_URL"] = "https://example.invalid/api/anthropic"

    result = subprocess.run(
        [str(SCRIPT), "--check"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 7
    assert "only sends the pass-backed token to https://api.z.ai/" in result.stderr
    assert "test-secret-token" not in result.stderr


def test_explicit_endpoint_override_is_limited_to_zai_api_host(tmp_path: Path) -> None:
    env, bin_dir = _base_env(tmp_path)
    _install_pass_stub(bin_dir)
    env_file = tmp_path / "claude-env.txt"
    _write_executable(
        bin_dir / "claude",
        f"""
        printf '%s\\n' "$ANTHROPIC_BASE_URL" > {env_file}
        exit 0
        """,
    )
    env["HAPAX_GLMCP_ALLOW_BASE_URL_OVERRIDE"] = "1"
    env["HAPAX_GLMCP_ANTHROPIC_BASE_URL"] = "https://api.z.ai/api/anthropic-preview"

    result = subprocess.run(
        [str(SCRIPT), "--check"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert env_file.read_text(encoding="utf-8").strip() == (
        "https://api.z.ai/api/anthropic-preview"
    )


def test_help_exits_before_dependency_checks(tmp_path: Path) -> None:
    env, _bin_dir = _base_env(tmp_path)

    result = subprocess.run(
        ["/usr/bin/bash", str(SCRIPT), "--help"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0
    assert "usage: hapax-glmcp-claude" in result.stdout
    assert "glmcp/api-key" in result.stdout


def test_missing_pass_reports_next_action(tmp_path: Path) -> None:
    env, bin_dir = _base_env(tmp_path)
    env["PATH"] = str(bin_dir)

    result = subprocess.run(
        ["/usr/bin/bash", str(SCRIPT), "--check"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 3
    assert "pass is not on PATH" in result.stderr


def test_missing_claude_reports_next_action(tmp_path: Path) -> None:
    env, bin_dir = _base_env(tmp_path)
    env["PATH"] = str(bin_dir)
    _install_pass_stub(bin_dir)

    result = subprocess.run(
        ["/usr/bin/bash", str(SCRIPT), "--check"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 4
    assert "claude is not on PATH" in result.stderr


def test_empty_pass_first_line_is_rejected(tmp_path: Path) -> None:
    env, bin_dir = _base_env(tmp_path)
    _write_executable(
        bin_dir / "pass",
        """
        printf '\\n'
        exit 0
        """,
    )
    _write_executable(bin_dir / "claude", "printf 'claude 0.0-test\\n'\n")

    result = subprocess.run(
        [str(SCRIPT), "--check"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 6
    assert "returned an empty first line" in result.stderr


def test_pass_failure_reports_next_action_without_pass_stderr(tmp_path: Path) -> None:
    env, bin_dir = _base_env(tmp_path)
    env["TMPDIR"] = str(tmp_path)
    _write_executable(
        bin_dir / "pass",
        """
        printf 'gpg: decryption failed\\n' >&2
        exit 1
        """,
    )
    _write_executable(bin_dir / "claude", "exit 0\n")

    result = subprocess.run(
        [str(SCRIPT), "--check"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 5
    assert "run: pass show 'glmcp/api-key'" in result.stderr
    assert "pass returned an error" in result.stderr
    assert "gpg: decryption failed" not in result.stderr
    assert "pass said:" not in result.stderr
    assert not list(tmp_path.glob("hapax-glmcp-pass.*"))


def test_check_mode_does_not_print_ok_when_claude_version_fails(tmp_path: Path) -> None:
    env, bin_dir = _base_env(tmp_path)
    _install_pass_stub(bin_dir)
    _write_executable(
        bin_dir / "claude",
        """
        printf 'version failed\\n' >&2
        exit 42
        """,
    )

    result = subprocess.run(
        [str(SCRIPT), "--check"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 9
    assert "hapax-glmcp-claude: ok" not in result.stdout
    assert "claude --version failed" in result.stderr


def test_xtrace_does_not_disclose_token(tmp_path: Path) -> None:
    env, bin_dir = _base_env(tmp_path)
    _install_pass_stub(bin_dir)
    _write_executable(bin_dir / "claude", "printf 'claude 0.0-test\\n'\n")

    result = subprocess.run(
        ["/usr/bin/bash", "-x", str(SCRIPT), "--check"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "+ set -x" not in result.stderr
    assert "ANTHROPIC_AUTH_TOKEN" not in result.stderr
    assert "test-secret-token" not in result.stdout
    assert "test-secret-token" not in result.stderr


def test_signal_during_secret_read_exits_without_execing_claude(tmp_path: Path) -> None:
    env, bin_dir = _base_env(tmp_path)
    pass_started = tmp_path / "pass-started"
    claude_executed = tmp_path / "claude-executed"
    _write_executable(
        bin_dir / "pass",
        f"""
        if [[ "$1" == "show" && "$2" == "glmcp/api-key" ]]; then
          touch {pass_started}
          sleep 2
          printf '%s\\n' test-secret-token
          exit 0
        fi
        exit 1
        """,
    )
    _write_executable(
        bin_dir / "claude",
        f"""
        touch {claude_executed}
        exit 0
        """,
    )

    proc = subprocess.Popen(
        [str(SCRIPT), "--check"],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    for _ in range(50):
        if pass_started.exists():
            break
        time.sleep(0.05)
    assert pass_started.exists()

    proc.terminate()
    stdout, stderr = proc.communicate(timeout=10)

    assert proc.returncode == 143
    assert not claude_executed.exists()
    assert "test-secret-token" not in stdout
    assert "test-secret-token" not in stderr
