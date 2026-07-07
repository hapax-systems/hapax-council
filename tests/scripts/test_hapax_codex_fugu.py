"""Tests for the governed Sakana Fugu Codex/Reins wrapper path."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tomllib
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
    (home / "projects" / "hapax-council--cx-fugu").mkdir(parents=True)
    (home / "projects" / "hapax-council--cx-fugu-check").mkdir(parents=True)
    (home / "projects" / "hapax-council--cx-fugu-ultra").mkdir(parents=True)
    return env, catalog, bin_dir


def _install_fake_codex(bin_dir: Path, tmp_path: Path) -> tuple[Path, Path]:
    args_file = tmp_path / "codex-args.txt"
    env_file = tmp_path / "codex-env.txt"
    _write_executable(
        bin_dir / "codex",
        f"""printf '%s\\n' "$@" > {args_file}
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


def test_reins_fugu_slot_role_keeps_pinned_session(tmp_path: Path) -> None:
    env, _catalog, _bin_dir = _base_env(tmp_path)

    fugu = subprocess.run(
        [str(REINS_FUGU), "--print-env", "--role", "alpha"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert fugu.returncode == 0, fugu.stderr
    assert "HAPAX_AGENT_ROLE=cx-fugu" in fugu.stdout
    assert "HAPAX_AGENT_SLOT=alpha" in fugu.stdout

    ultra = subprocess.run(
        [str(REINS_FUGU_ULTRA), "--print-env", "--role=beta"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert ultra.returncode == 0, ultra.stderr
    assert "HAPAX_AGENT_ROLE=cx-fugu-ultra" in ultra.stdout
    assert "HAPAX_AGENT_SLOT=beta" in ultra.stdout


def test_reins_fugu_entrypoints_ignore_profile_env_override(tmp_path: Path) -> None:
    env, _catalog, _bin_dir = _base_env(tmp_path)
    env["REINS_FUGU_PROFILE"] = "fugu-ultra"

    fugu = subprocess.run(
        [str(REINS_FUGU), "--print-env"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert fugu.returncode == 0, fugu.stderr
    assert "HAPAX_CODEX_FUGU_PROFILE=fugu" in fugu.stdout
    assert "HAPAX_AGENT_ROLE=cx-fugu" in fugu.stdout

    env["REINS_FUGU_PROFILE"] = "fugu"
    ultra = subprocess.run(
        [str(REINS_FUGU_ULTRA), "--print-env"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert ultra.returncode == 0, ultra.stderr
    assert "HAPAX_CODEX_FUGU_PROFILE=fugu-ultra" in ultra.stdout
    assert "HAPAX_AGENT_ROLE=cx-fugu-ultra" in ultra.stdout


@pytest.mark.parametrize(
    ("script", "override_args"),
    [
        (REINS_FUGU, ["--fugu-profile", "fugu-ultra"]),
        (REINS_FUGU, ["--fugu-profile=fugu-ultra"]),
        (REINS_FUGU_ULTRA, ["--fugu-profile", "fugu"]),
        (REINS_FUGU_ULTRA, ["--fugu=fugu"]),
    ],
)
def test_reins_fugu_shims_refuse_profile_overrides(
    tmp_path: Path, script: Path, override_args: list[str]
) -> None:
    env, _catalog, _bin_dir = _base_env(tmp_path)

    result = subprocess.run(
        [str(script), *override_args, "--print-env"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 2
    assert "refuses caller Fugu profile override" in result.stderr
    assert "HAPAX_CODEX_FUGU_PROFILE" not in result.stdout


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


def test_fugu_check_scrubs_inherited_secret_before_helpers(tmp_path: Path) -> None:
    env, _catalog, bin_dir = _base_env(tmp_path)
    _install_fake_codex(bin_dir, tmp_path)
    pass_env = tmp_path / "pass-env.txt"
    python_env = tmp_path / "python-env.txt"
    real_python = shutil.which("python3")
    assert real_python is not None
    _write_executable(
        bin_dir / "python3",
        f"""printf 'SAKANA_API_KEY=%s\\n' "${{SAKANA_API_KEY:-}}" > {python_env}
exec {shlex.quote(real_python)} "$@"
""",
    )
    _write_executable(
        bin_dir / "pass",
        f"""printf 'SAKANA_API_KEY=%s\\n' "${{SAKANA_API_KEY:-}}" > {pass_env}
if [ "${{1:-}}" = "show" ] && [ "${{2:-}}" = "sakana/api-key" ]; then
  printf '%s\\n' super-secret-value
  exit 0
fi
exit 1
""",
    )
    env["SAKANA_API_KEY"] = "parent-secret-that-must-be-scrubbed"

    result = subprocess.run(
        [str(REINS_FUGU), "--check", "--role", "cx-fugu-check"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert pass_env.read_text(encoding="utf-8") == "SAKANA_API_KEY=\n"
    assert python_env.read_text(encoding="utf-8") == "SAKANA_API_KEY=\n"
    assert "parent-secret-that-must-be-scrubbed" not in result.stdout
    assert "parent-secret-that-must-be-scrubbed" not in result.stderr


def test_fugu_check_refuses_passthrough_args_before_readiness_ok(tmp_path: Path) -> None:
    env, _catalog, bin_dir = _base_env(tmp_path)
    _install_fake_codex_and_pass(bin_dir, tmp_path)

    result = subprocess.run(
        [str(REINS_FUGU), "--check", "--role", "cx-fugu-check", "--", "--model", "gpt-5.5"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 2
    assert "Fugu mode refuses" in result.stderr
    assert "Fugu check ok" not in result.stdout


def test_fugu_check_refuses_missing_explicit_worktree_before_readiness_ok(
    tmp_path: Path,
) -> None:
    env, _catalog, bin_dir = _base_env(tmp_path)
    pass_called = tmp_path / "pass-called"
    _install_fake_codex(bin_dir, tmp_path)
    _write_executable(
        bin_dir / "pass",
        f"""printf called > {pass_called}
printf '%s\\n' super-secret-value
exit 0
""",
    )
    missing_worktree = tmp_path / "missing-worktree"

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "cx-fugu-check",
            "--cd",
            str(missing_worktree),
            "--fugu-profile",
            "fugu",
            "--check",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 3
    assert "no worktree found" in result.stderr
    assert str(missing_worktree) in result.stderr
    assert "Fugu check ok" not in result.stdout
    assert not pass_called.exists()


def test_fugu_print_env_refuses_remote_dispatch_request(tmp_path: Path) -> None:
    env, _catalog, _bin_dir = _base_env(tmp_path)
    env["HAPAX_DISPATCH_HOST"] = "appendix"

    result = subprocess.run(
        [str(REINS_FUGU), "--print-env"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 14
    assert "Fugu launch refuses remote dispatch" in result.stderr
    assert "HAPAX_CODEX_FUGU_PROFILE" not in result.stdout


def test_fugu_check_rejects_empty_pass_entry(tmp_path: Path) -> None:
    env, _catalog, bin_dir = _base_env(tmp_path)
    _install_fake_codex(bin_dir, tmp_path)
    _write_executable(
        bin_dir / "pass",
        """if [ "${1:-}" = "show" ] && [ "${2:-}" = "sakana/api-key" ]; then
  printf '\\n'
  exit 0
fi
exit 1
""",
    )

    result = subprocess.run(
        [str(REINS_FUGU), "--check", "--role", "cx-fugu-check"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 1
    assert "pass entry 'sakana/api-key' returned an empty first line" in result.stderr
    assert "Fugu check ok" not in result.stdout


def test_fugu_check_rejects_unsupported_secret_without_pass_lookup(tmp_path: Path) -> None:
    env, _catalog, bin_dir = _base_env(tmp_path)
    _install_fake_codex(bin_dir, tmp_path)
    pass_called = tmp_path / "pass-called"
    _write_executable(
        bin_dir / "pass",
        f"""printf '%s\\n' "$*" > {pass_called}
printf '%s\\n' should-not-be-read
exit 0
""",
    )
    env["HAPAX_CODEX_FUGU_SECRET_ENTRY"] = "github/pat"

    result = subprocess.run(
        [str(REINS_FUGU), "--check", "--role", "cx-fugu-check"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 1
    assert "unsupported secret entry 'github/pat'" in result.stderr
    assert not pass_called.exists()
    assert "should-not-be-read" not in result.stdout
    assert "should-not-be-read" not in result.stderr


def test_fugu_check_surfaces_pass_stderr(tmp_path: Path) -> None:
    env, _catalog, bin_dir = _base_env(tmp_path)
    _install_fake_codex(bin_dir, tmp_path)
    _write_executable(
        bin_dir / "pass",
        """if [ "${1:-}" = "show" ] && [ "${2:-}" = "sakana/api-key" ]; then
  printf '%s\\n' 'gpg timeout while decrypting' >&2
  exit 2
fi
exit 1
""",
    )

    result = subprocess.run(
        [str(REINS_FUGU), "--check", "--role", "cx-fugu-check"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 1
    assert "pass show exit 2" in result.stderr
    assert "gpg timeout while decrypting" in result.stderr
    assert "Fugu check ok" not in result.stdout


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
    assert "--disable\nimage_generation" in args
    assert "--disable\napps" in args
    assert "litellm" not in args
    assert "openrouter" not in args
    assert "codex-fugu" not in args

    launched_env = env_file.read_text(encoding="utf-8")
    assert "SAKANA_API_KEY=present" in launched_env
    assert "super-secret-value" not in launched_env
    assert "HAPAX_AGENT_ROLE=cx-fugu-test" in launched_env
    assert "HAPAX_AGENT_SLOT=alpha" in launched_env
    assert CODEX_CONFIG.read_text(encoding="utf-8") == config_before


def test_fugu_launch_toml_quotes_catalog_path(tmp_path: Path) -> None:
    env, catalog, bin_dir = _base_env(tmp_path)
    catalog.unlink()
    quoted_catalog = catalog.parent / 'fugu"catalog\\segment\nwith-newline.json'
    quoted_catalog.write_text(
        '{"models":[{"slug":"fugu"},{"slug":"fugu-ultra"}]}\n',
        encoding="utf-8",
    )
    env["HAPAX_CODEX_FUGU_MODEL_CATALOG"] = str(quoted_catalog)
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
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    args = args_file.read_text(encoding="utf-8").splitlines()
    config_values = [args[index + 1] for index, arg in enumerate(args[:-1]) if arg == "-c"]
    parsed_config: dict[str, object] = {}
    for value in config_values:
        parsed_config.update(tomllib.loads(value))

    assert parsed_config["model_catalog_json"] == str(quoted_catalog)
    joined_config = "\n".join(config_values)
    assert '\\"catalog' in joined_config
    assert "\\\\segment" in joined_config
    assert "\\nwith-newline.json" in joined_config


@pytest.mark.parametrize(
    "override_args",
    [
        ["-p", "default"],
        ["--profile=default"],
        ["--PROFILE", "default"],
        ["--enable", "apps"],
        ["--enable=apps"],
        ["-m", "gpt-5.5"],
        ["--model", "fugu-ultra"],
        ["--model=fugu-ultra"],
        ["--Model", "fugu-ultra"],
        ["--model-provider", "litellm"],
        ["--MODEL_PROVIDER", "litellm"],
        ["--api-base", "https://attacker.example/v1"],
        ["--setting", 'model_provider="litellm"'],
        ["Write a prompt that should not be forwarded in governed Fugu mode."],
        ["--base-url=https://attacker.example/v1"],
        ["-c", 'model="gpt-5.5"'],
        ["-c", 'base_url="https://attacker.example/v1"'],
        ["-c", 'env_key="ATTACKER_KEY"'],
        ["-c", 'Model="gpt-5.5"'],
        ['-cmodel_provider="litellm"'],
        ['-c=model_catalog_json="/tmp/evil.json"'],
        ["--config", 'model_providers.sakana.base_url = "https://attacker.example/v1"'],
        ['--config=model_providers."sakana".env_key="ATTACKER_KEY"'],
        ["--config", '[model_providers.sakana]\nenv_key="ATTACKER_KEY"'],
        ["--config", "ui.notifications=false"],
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
    assert "Fugu mode refuses" in result.stderr
    assert "next action" in result.stderr
    assert not args_file.exists()


def test_fugu_launch_refuses_all_passthrough_args_before_loading_secret(
    tmp_path: Path,
) -> None:
    env, _catalog, bin_dir = _base_env(tmp_path)
    args_file, _env_file = _install_fake_codex(bin_dir, tmp_path)
    pass_called = tmp_path / "pass-called"
    _write_executable(
        bin_dir / "pass",
        f"""printf called > {pass_called}
printf '%s\\n' super-secret-value
exit 0
""",
    )
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
            "--future-routing-flag",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 2
    assert "refuses caller-supplied Codex argument" in result.stderr
    assert "next action" in result.stderr
    assert not args_file.exists()
    assert not pass_called.exists()


@pytest.mark.parametrize(
    "remote_args",
    [
        ["--remote", "wss://attacker.example/app"],
        ["--remote=wss://attacker.example/app"],
        ["--remote-auth-token-env", "SAKANA_API_KEY"],
        ["--remote-auth-token-env=SAKANA_API_KEY"],
        ["cloud"],
        ["exec-server"],
    ],
)
def test_fugu_launch_refuses_codex_remote_args_before_loading_secret(
    tmp_path: Path, remote_args: list[str]
) -> None:
    env, _catalog, bin_dir = _base_env(tmp_path)
    args_file, _env_file = _install_fake_codex(bin_dir, tmp_path)
    pass_called = tmp_path / "pass-called"
    _write_executable(
        bin_dir / "pass",
        f"""printf called > {pass_called}
if [ "${{1:-}}" = "show" ] && [ "${{2:-}}" = "sakana/api-key" ]; then
  printf '%s\\n' super-secret-value
  exit 0
fi
exit 1
""",
    )
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
            *remote_args,
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 2
    assert "Fugu mode refuses Codex remote/control override" in result.stderr
    assert "next action" in result.stderr
    assert not args_file.exists()
    assert not pass_called.exists()


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


def test_fugu_terminal_tmux_defers_secret_to_inner_runner(tmp_path: Path) -> None:
    env, _catalog, bin_dir = _base_env(tmp_path)
    args_file, env_file = _install_fake_codex(bin_dir, tmp_path)
    tmux_args = tmp_path / "tmux-args.txt"
    tmux_env = tmp_path / "tmux-env.txt"
    pass_called = tmp_path / "pass-called"
    _write_executable(
        bin_dir / "tmux",
        f"""printf '%s\\n' "$@" > {tmux_args}
printf 'SAKANA_API_KEY=%s\\n' "${{SAKANA_API_KEY:-}}" > {tmux_env}
if [ "${{1:-}}" = "has-session" ]; then
  exit 1
fi
exit 0
""",
    )
    _write_executable(
        bin_dir / "pass",
        f"""printf called > {pass_called}
printf '%s\\n' super-secret-value
exit 0
""",
    )
    env["SAKANA_API_KEY"] = "parent-secret-that-must-not-reach-tmux"
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "cx-fugu-test",
            "--cd",
            str(workdir),
            "--terminal",
            "tmux",
            "--fugu-profile",
            "fugu",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "hapax-codex-cx-fugu-test"
    assert tmux_env.read_text(encoding="utf-8") == "SAKANA_API_KEY=\n"
    assert not pass_called.exists()
    assert not args_file.exists()
    runner = Path(tmux_args.read_text(encoding="utf-8").splitlines()[-1])
    runner_text = runner.read_text(encoding="utf-8")
    assert "--fugu-profile fugu" in runner_text
    assert "--terminal none" in runner_text
    assert "SAKANA_API_KEY" not in runner_text

    inner = subprocess.run(
        [str(runner)],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert inner.returncode == 0, inner.stderr
    assert pass_called.exists()
    assert "SAKANA_API_KEY=present" in env_file.read_text(encoding="utf-8")


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


def test_fugu_launch_reports_pass_failure_without_exporting_partial_stdout(
    tmp_path: Path,
) -> None:
    env, _catalog, bin_dir = _base_env(tmp_path)
    args_file, env_file = _install_fake_codex(bin_dir, tmp_path)
    _write_executable(
        bin_dir / "pass",
        """if [ "${1:-}" = "show" ] && [ "${2:-}" = "sakana/api-key" ]; then
  printf '%s\\n' partial-stdout
  printf '%s\\n' 'gpg timeout while decrypting' >&2
  exit 2
fi
exit 1
""",
    )
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
    assert "pass show 'sakana/api-key' failed with exit 2" in result.stderr
    assert "gpg timeout while decrypting" in result.stderr
    assert "next action" in result.stderr
    assert "partial-stdout" not in result.stderr
    assert not args_file.exists()
    assert not env_file.exists()


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
