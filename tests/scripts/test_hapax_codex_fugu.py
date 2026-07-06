"""Tests for the governed Sakana Fugu Codex/Reins wrapper path."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = REPO_ROOT / "scripts" / "hapax-codex"
REINS_FUGU = REPO_ROOT / "scripts" / "reins-fugu"
REINS_FUGU_ULTRA = REPO_ROOT / "scripts" / "reins-fugu-ultra"
CODEX_CONFIG = REPO_ROOT / "config" / "codex" / "config.toml"


def _write_executable(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _base_env(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    home = tmp_path / "home"
    home.mkdir()
    catalog = home / ".codex" / "fugu.json"
    catalog.parent.mkdir()
    catalog.write_text(
        '{"models":[{"slug":"fugu"},{"slug":"fugu-ultra"}]}\n',
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "HAPAX_COUNCIL_DIR": str(REPO_ROOT),
            "HAPAX_CODEX_FUGU_MODEL_CATALOG": str(catalog),
            "HAPAX_CODEX_TERMINAL": "none",
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        }
    )
    for key in (
        "CODEX_THREAD_NAME",
        "CODEX_ROLE",
        "CODEX_SESSION_NAME",
        "CODEX_SESSION",
        "HAPAX_AGENT_NAME",
        "HAPAX_AGENT_ROLE",
        "HAPAX_DISPATCH_HOST",
        "SAKANA_API_KEY",
    ):
        env.pop(key, None)
    return env, catalog, bin_dir


def _install_fake_codex(bin_dir: Path, tmp_path: Path) -> tuple[Path, Path]:
    args_file = tmp_path / "codex-args.txt"
    env_file = tmp_path / "codex-env.txt"
    _write_executable(
        bin_dir / "codex",
        f"""printf '%s\\n' "$*" > {args_file}
if [ "${{SAKANA_API_KEY:-}}" = "super-secret-value" ]; then
  printf 'SAKANA_API_KEY=present\\n' > {env_file}
else
  printf 'SAKANA_API_KEY=missing\\n' > {env_file}
fi
printf 'HAPAX_AGENT_ROLE=%s\\n' "${{HAPAX_AGENT_ROLE:-}}" >> {env_file}
printf 'HAPAX_AGENT_SLOT=%s\\n' "${{HAPAX_AGENT_SLOT:-}}" >> {env_file}
exit 0
""",
    )
    return args_file, env_file


def _install_fake_codex_and_pass(bin_dir: Path, tmp_path: Path) -> tuple[Path, Path]:
    args_file, env_file = _install_fake_codex(bin_dir, tmp_path)
    _write_executable(
        bin_dir / "pass",
        """if [ "${1:-}" = "show" ] && [ "${2:-}" = "sakana/api-key" ]; then
  printf '%s\\n' super-secret-value
  exit 0
fi
exit 1
""",
    )
    return args_file, env_file


def test_reins_fugu_print_env_is_sanitized_and_role_aware(tmp_path: Path) -> None:
    env, _catalog, _bin_dir = _base_env(tmp_path)

    result = subprocess.run(
        [str(REINS_FUGU), "--print-env", "--role", "cx-fugu-lane"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "HAPAX_AGENT_ROLE=cx-fugu-lane" in out
    assert "HAPAX_CODEX_FUGU_MODEL=fugu" in out
    assert "HAPAX_CODEX_FUGU_BASE_URL=https://api.sakana.ai/v1" in out
    assert "HAPAX_CODEX_FUGU_WIRE_API=responses" in out
    assert "HAPAX_CODEX_FUGU_SECRET_ENTRY=pass:sakana/api-key" in out
    assert "HAPAX_CODEX_FUGU_SECRET_VALUE=<redacted>" in out
    assert "super-secret-value" not in out


def test_reins_fugu_ultra_print_env_selects_ultra_model(tmp_path: Path) -> None:
    env, _catalog, _bin_dir = _base_env(tmp_path)

    result = subprocess.run(
        [str(REINS_FUGU_ULTRA), "--print-env", "--role", "cx-fugu-ultra"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "HAPAX_AGENT_ROLE=cx-fugu-ultra" in result.stdout
    assert "HAPAX_CODEX_FUGU_PROFILE=fugu-ultra" in result.stdout
    assert "HAPAX_CODEX_FUGU_MODEL=fugu-ultra" in result.stdout

    default_role = subprocess.run(
        [str(REINS_FUGU_ULTRA), "--print-env"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert default_role.returncode == 0, default_role.stderr
    assert "HAPAX_AGENT_ROLE=cx-fugu-ultra" in default_role.stdout


def test_fugu_check_uses_pass_without_exposing_secret(tmp_path: Path) -> None:
    env, _catalog, bin_dir = _base_env(tmp_path)
    _install_fake_codex_and_pass(bin_dir, tmp_path)

    result = subprocess.run(
        [str(REINS_FUGU), "--check", "--role", "cx-fugu-check"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "Fugu check ok" in result.stdout
    assert "prompt_sent=false" in result.stdout
    assert "provider_spend=false" in result.stdout
    assert "raw_codex_fugu_bypass=false" in result.stdout
    assert "secret_entry=pass:sakana/api-key" in result.stdout
    assert "secret_value=<redacted>" in result.stdout
    assert "super-secret-value" not in result.stdout
    assert "super-secret-value" not in result.stderr


def test_fugu_refuses_unknown_endpoint_and_secret_route(tmp_path: Path) -> None:
    env, _catalog, _bin_dir = _base_env(tmp_path)
    env["HAPAX_CODEX_FUGU_BASE_URL"] = "https://router.requesty.ai/v1"

    endpoint = subprocess.run(
        [str(REINS_FUGU), "--print-env"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert endpoint.returncode == 2
    assert "unsupported endpoint" in endpoint.stderr
    assert "https://api.sakana.ai/v1" in endpoint.stderr

    env["HAPAX_CODEX_FUGU_BASE_URL"] = "https://api.sakana.ai/v1"
    env["HAPAX_CODEX_FUGU_SECRET_ENTRY"] = "openrouter/key"
    secret = subprocess.run(
        [str(REINS_FUGU), "--print-env"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert secret.returncode == 2
    assert "unsupported secret entry" in secret.stderr
    assert "pass:sakana/api-key" in secret.stderr


def test_fugu_launch_injects_governed_codex_config_without_global_rewrite(
    tmp_path: Path,
) -> None:
    env, catalog, bin_dir = _base_env(tmp_path)
    args_file, env_file = _install_fake_codex_and_pass(bin_dir, tmp_path)
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    config_before = CODEX_CONFIG.read_text(encoding="utf-8")

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "cx-fugu-test",
            "--slot",
            "alpha",
            "--cd",
            str(workdir),
            "--fugu-profile",
            "fugu-ultra",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    args = args_file.read_text(encoding="utf-8")
    assert 'model="fugu-ultra"' in args
    assert 'model_provider="sakana"' in args
    assert f'model_catalog_json="{catalog}"' in args
    assert 'model_providers.sakana.base_url="https://api.sakana.ai/v1"' in args
    assert 'model_providers.sakana.wire_api="responses"' in args
    assert "--disable image_generation" in args
    assert "--disable apps" in args
    assert "litellm" not in args
    assert "openrouter" not in args
    assert "codex-fugu" not in args

    launched_env = env_file.read_text(encoding="utf-8")
    assert "SAKANA_API_KEY=present" in launched_env
    assert "super-secret-value" not in launched_env
    assert "HAPAX_AGENT_ROLE=cx-fugu-test" in launched_env
    assert "HAPAX_AGENT_SLOT=alpha" in launched_env
    assert CODEX_CONFIG.read_text(encoding="utf-8") == config_before


@pytest.mark.parametrize(
    "override_args",
    [
        ["-p", "default"],
        ["--profile=default"],
        ["--enable", "apps"],
        ["--enable=apps"],
        ["-m", "gpt-5.5"],
        ["--model=fugu-ultra"],
        ["--model-provider", "litellm"],
        ["--base-url=https://attacker.example/v1"],
        ["-c", 'model="gpt-5.5"'],
        ['-cmodel_provider="litellm"'],
        ['-c=model_catalog_json="/tmp/evil.json"'],
        ["--config", 'model_providers.sakana.base_url = "https://attacker.example/v1"'],
        ['--config=model_providers."sakana".env_key="ATTACKER_KEY"'],
        ["-c", "features.image_generation = true"],
        ["-c", "'features'.apps = true"],
    ],
)
def test_fugu_launch_refuses_codex_override_variants(
    tmp_path: Path, override_args: list[str]
) -> None:
    env, _catalog, bin_dir = _base_env(tmp_path)
    args_file, _env_file = _install_fake_codex_and_pass(bin_dir, tmp_path)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "cx-fugu-test",
            "--cd",
            str(workdir),
            "--fugu-profile",
            "fugu",
            "--",
            *override_args,
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 2
    assert "Fugu mode refuses Codex" in result.stderr
    assert not args_file.exists()


def test_fugu_launch_refuses_remote_dispatch(tmp_path: Path) -> None:
    env, _catalog, bin_dir = _base_env(tmp_path)
    args_file, _env_file = _install_fake_codex_and_pass(bin_dir, tmp_path)
    _write_executable(bin_dir / "ssh", "exit 0\n")
    env["HAPAX_DISPATCH_HOST"] = "appendix"
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "cx-fugu-test",
            "--cd",
            str(workdir),
            "--fugu-profile",
            "fugu",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 14
    assert "Fugu launch refuses remote dispatch" in result.stderr
    assert "next action" in result.stderr
    assert not args_file.exists()


def test_fugu_launch_refuses_missing_pass_secret(tmp_path: Path) -> None:
    env, _catalog, bin_dir = _base_env(tmp_path)
    args_file, _env_file = _install_fake_codex(bin_dir, tmp_path)
    _write_executable(bin_dir / "pass", "exit 1\n")
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "cx-fugu-test",
            "--cd",
            str(workdir),
            "--fugu-profile",
            "fugu",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 7
    assert "pass:sakana/api-key" in result.stderr
    assert "next action" in result.stderr
    assert not args_file.exists()


def test_fugu_print_env_reports_missing_catalog_setup_action(tmp_path: Path) -> None:
    env, catalog, _bin_dir = _base_env(tmp_path)
    catalog.unlink()

    result = subprocess.run(
        [str(REINS_FUGU), "--print-env"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 2
    assert "model catalog" in result.stderr
    assert "does not exist" in result.stderr
    assert "next action" in result.stderr


def test_fugu_print_env_reports_malformed_catalog(tmp_path: Path) -> None:
    env, catalog, _bin_dir = _base_env(tmp_path)
    catalog.write_text("{not json", encoding="utf-8")

    result = subprocess.run(
        [str(REINS_FUGU), "--print-env"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 2
    assert "not valid JSON" in result.stderr
    assert "next action" in result.stderr


def test_fugu_check_requires_profile_with_next_action(tmp_path: Path) -> None:
    env, _catalog, _bin_dir = _base_env(tmp_path)

    result = subprocess.run(
        [str(LAUNCHER), "--check"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 2
    assert "--fugu-profile fugu|fugu-ultra" in result.stderr
    assert "next action" in result.stderr
