"""Dispatch -> real launcher -> runner -> child, with synthetic auth and no provider calls."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.scripts.test_claude_account_live_observe_per_route import obs
from tests.scripts.test_claude_probe_subscription_boundary import (
    subscription_probe_home,  # noqa: F401
)
from tests.scripts.test_hapax_methodology_dispatch import (
    REPO_ROOT,
    _fresh_claude_subscription_quota_ledger,
    _run,
    _spec,
    _task,
    _worktree,
)

NOW = datetime.now(UTC)


def launch_fixture(tmp_path):
    home = tmp_path / "home"
    config = home / ".claude"
    config.mkdir(parents=True)
    credential = config / ".credentials.json"
    credential.write_text(
        json.dumps(
            {
                "claudeAiOauth": {
                    "accessToken": "synthetic-subscription-access-token",
                    "subscriptionType": "max",
                    "scopes": ["user:inference"],
                    "expiresAt": int(datetime.now(UTC).timestamp() * 1000) + 3600000,
                }
            }
        )
    )
    credential.chmod(0o600)
    workdir = home / "projects/hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache/hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-beta").write_text("governed-build\n")
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "spec.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"kind: build\nauthority_case: CASE-TEST-001\nparent_spec: {spec}\n",
    )
    binary = tmp_path / "bin"
    binary.mkdir()
    observed = tmp_path / "child.json"
    # Emulate the CLI's late settings application and host-managed routing.
    # The installed vendor CLI is checked separately in a network namespace.
    (binary / "claude").write_text(
        f"#!{sys.executable}\n"
        + """
import json, os, sys
from pathlib import Path
env = dict(os.environ)
if '--version' in sys.argv:
    version = Path("""
        + repr(str(tmp_path / "cli-version.txt"))
        + """)
    print(version.read_text() if version.exists() else '2.1.281 (Claude Code)')
    raise SystemExit(0)
config = Path(env.get('CLAUDE_CONFIG_DIR') or Path.home()/'.claude')
host = env.get('CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST') == '1'
settings = {}
for path in (config/'settings.json', Path.cwd()/'.claude/settings.json',
             Path.cwd()/'.claude/settings.local.json'):
    if path.exists():
        data = json.loads(path.read_text())
        settings.update({k:v for k,v in data.items() if k != 'env'})
        for key, value in data.get('env', {}).items():
            if host and key.startswith(('ANTHROPIC_', 'CLAUDE_CODE_OAUTH_', 'CLAUDE_CODE_USE_')):
                continue
            env[key] = value
for i, arg in enumerate(sys.argv[:-1]):
    if arg == '--settings':
        data = json.loads(sys.argv[i+1])
        settings.update({k:v for k,v in data.items() if k != 'env'})
        env.update(data.get('env', {}))
if 'auth' in sys.argv and 'status' in sys.argv:
    status = {'loggedIn': True, 'authMethod': 'oauth_token', 'apiProvider': 'firstParty',
              'apiKeySource': None if not settings.get('apiKeyHelper') else 'apiKeyHelper'}
    override = Path("""
        + repr(str(tmp_path / "auth-status.json"))
        + """)
    if override.exists(): status = json.loads(override.read_text())
    print(json.dumps(status))
else:
    binding = {'endpoint': env.get('ANTHROPIC_BASE_URL') or 'https://api.anthropic.com',
      'oauth_bound': env.get('CLAUDE_CODE_OAUTH_TOKEN') == 'synthetic-subscription-access-token',
      'api_auth_present': bool(env.get('ANTHROPIC_AUTH_TOKEN') or env.get('ANTHROPIC_API_KEY')),
      'host_bound': env.get('CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST') == '1',
      'api_helper': bool(settings.get('apiKeyHelper')),
      'hooks_preserved': settings.get('hooks') == {'SessionStart': []},
      'home': env['HOME'], 'config': str(config), 'argv': sys.argv[1:],
      'env_names': sorted(env)}
    Path("""
        + repr(str(observed))
        + """).write_text(json.dumps(binding))
"""
    )
    (binary / "claude").chmod(0o700)
    # A pre-existing tmux server has its OWN environment; execute the real runner
    # after injecting gateway controls and dropping the dispatcher's opt-in env.
    (binary / "tmux").write_text(
        '#!/usr/bin/env bash\ncase "$1" in\n'
        "has-session) exit 1 ;;\nnew-session)\n"
        "for runner; do :; done\n"
        "export ANTHROPIC_BASE_URL=https://tmux-gateway.invalid\n"
        "export ANTHROPIC_AUTH_TOKEN=synthetic-tmux-token\n"
        "unset CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST CLAUDE_CODE_OAUTH_TOKEN\n"
        "export HOME=/synthetic-unbound-home CLAUDE_CONFIG_DIR=/synthetic-unbound-config\n"
        'exec "$runner" ;;\n*) exit 0 ;;\nesac\n'
    )
    (binary / "tmux").chmod(0o700)
    (config / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": []}}))
    env = {
        "PATH": f"{binary}:{Path(sys.executable).parent}:/usr/bin:/bin",
        "HAPAX_METHODOLOGY_CLAUDE_LAUNCHER": str(REPO_ROOT / "scripts/hapax-claude"),
        "HAPAX_COUNCIL_DIR": str(REPO_ROOT),
        "HAPAX_CLAUDE_WORKTREE_ROOT": str(home / "projects"),
        "HAPAX_QUOTA_SPEND_LEDGER": str(
            _fresh_claude_subscription_quota_ledger(tmp_path, route_id="claude.interactive.full")
        ),
        "CLAUDE_CONFIG_DIR": str(config),
        "XDG_CACHE_HOME": str(home / ".cache"),
    }
    return env, config, workdir, observed, credential


def dispatch(tmp_path, env):
    return _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "beta",
        "--platform",
        "claude",
        "--mode",
        "interactive",
        "--launch",
        extra_env=env,
    )


@pytest.mark.parametrize("source", ["environment", "user", "project", "local"])
def test_fresh_subscription_receipt_cannot_launch_gateway_child(tmp_path, monkeypatch, source):
    # Keep the test independent of actual operator provider controls.
    for name in list(os.environ):
        if name.startswith(("ANTHROPIC_", "CLAUDE_CODE_")):
            monkeypatch.delenv(name)
    env, config, workdir, observed, _ = launch_fixture(tmp_path)
    redirect = {
        "ANTHROPIC_BASE_URL": "https://gateway.invalid",
        "ANTHROPIC_AUTH_TOKEN": "synthetic-gateway-token",
        "CLAUDE_CODE_OAUTH_TOKEN": "synthetic-inherited-token",
        "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST": "0",
    }
    if source == "environment":
        env.update(redirect)
    else:
        path = config / "settings.json"
        if source != "user":
            path = (
                workdir
                / ".claude"
                / ("settings.local.json" if source == "local" else "settings.json")
            )
            path.parent.mkdir()
        path.write_text(
            json.dumps(
                {
                    "env": redirect,
                    "apiKeyHelper": "echo synthetic-helper",  # pragma: allowlist secret
                    "hooks": {"SessionStart": []},
                }
            )
        )
    before = (config / "settings.json").read_bytes()
    result = dispatch(tmp_path, env)
    assert result.returncode == 0, result.stdout + result.stderr
    binding = json.loads(observed.read_text())
    assert binding["endpoint"] == "https://api.anthropic.com"
    assert binding["oauth_bound"] is True
    assert binding["api_auth_present"] is False
    assert binding["host_bound"] is True
    assert binding["api_helper"] is False
    assert binding["hooks_preserved"] is True
    assert binding["home"] == str(tmp_path / "home")
    assert binding["config"] == str(config)
    assert (config / "settings.json").read_bytes() == before
    assert "claude-opus-4-8" in binding["argv"] and "max" in binding["argv"]
    for runner in (tmp_path / "home/.cache/hapax/claude-spawns").glob("*.sh"):
        assert "synthetic-subscription-access-token" not in runner.read_text()


@pytest.mark.parametrize(
    "defect",
    ["missing-login", "gateway", "helper", "wrong-method", "malformed", "old-cli", "unknown-cli"],
)
def test_unproven_launch_auth_holds_despite_fresh_quota(tmp_path, defect):
    env, _, _, observed, credential = launch_fixture(tmp_path)
    status = {
        "loggedIn": True,
        "authMethod": "oauth_token",
        "apiProvider": "firstParty",
        "apiKeySource": None,
    }
    if defect == "missing-login":
        credential.unlink()
    elif defect in {"old-cli", "unknown-cli"}:
        (tmp_path / "cli-version.txt").write_text(
            "2.0.1 (Claude Code)" if defect == "old-cli" else "unknown"
        )
    elif defect == "gateway":
        status["apiProvider"] = "gateway"
    elif defect == "helper":
        status["apiKeySource"] = "apiKeyHelper"  # pragma: allowlist secret
    elif defect == "wrong-method":
        status["authMethod"] = "api_key"
    else:
        status = []
    (tmp_path / "auth-status.json").write_text(json.dumps(status))
    result = dispatch(tmp_path, env)
    assert result.returncode != 0
    assert "Next action:" in result.stderr
    assert not observed.exists()
    assert not (tmp_path / "home/.cache/hapax/claude-spawns").exists()


@pytest.mark.parametrize(
    "override", ["--settings", "--settings={}", "--setting-sources=user", "--"]
)
@pytest.mark.usefixtures("subscription_probe_home")
def test_caller_cannot_override_bound_auth_settings(monkeypatch, override):
    def unexpected(*args, **kwargs):
        pytest.fail("unbound configuration started a subprocess")

    monkeypatch.setattr(obs.subprocess, "run", unexpected)
    assert obs.interactive_subscription(["claude", override], execute=True) == 4


@pytest.mark.parametrize("failure", ["timeout", "invalid-json", "nonzero", "policy-change"])
@pytest.mark.usefixtures("subscription_probe_home")
def test_auth_check_failure_never_executes_or_exposes_output(
    tmp_path, monkeypatch, capsys, failure
):
    def check(argv, **kwargs):
        if "--version" in argv:
            return subprocess.CompletedProcess(argv, 0, "2.1.281 (Claude Code)", "")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 15, output="synthetic-sensitive-output")
        status = {
            "loggedIn": True,
            "authMethod": "oauth_token",
            "apiProvider": "firstParty",
            "apiKeySource": None,
        }
        if failure == "policy-change":
            obs.PROBE_MANAGED_DIR.mkdir()
        return subprocess.CompletedProcess(
            argv,
            1 if failure == "nonzero" else 0,
            "synthetic-sensitive-output" if failure == "invalid-json" else json.dumps(status),
            "",
        )

    monkeypatch.setattr(obs.subprocess, "run", check)
    monkeypatch.setattr(obs.os, "execvpe", lambda *args: pytest.fail("unproven launch executed"))
    assert obs.interactive_subscription(["claude"], execute=True) == 4
    error = capsys.readouterr().err
    assert "Next action:" in error and "synthetic-sensitive-output" not in error


def test_tmux_rechecks_credentials_at_actual_execution(tmp_path):
    env, _, _, observed, credential = launch_fixture(tmp_path)
    tmux = tmp_path / "bin/tmux"
    tmux.write_text(
        tmux.read_text().replace(
            "for runner; do :; done", f'for runner; do :; done\nrm -- "{credential}"'
        )
    )
    result = dispatch(tmp_path, env)
    assert result.returncode != 0
    assert "subscription authentication or host policy is unproven" in result.stderr
    assert not observed.exists()


def test_installed_cli_keeps_routing_bound_after_loading_settings(tmp_path):
    """Opt-in local contract: real CLI Setup hook, synthetic auth, no network/inference."""
    binary = os.environ.get("HAPAX_CLAUDE_CONTRACT_BINARY")
    if not binary:
        pytest.skip("set HAPAX_CLAUDE_CONTRACT_BINARY for isolated installed-CLI check")
    _, config, workdir, observed, _ = launch_fixture(tmp_path)
    capture = tmp_path / "capture.py"
    capture.write_text(
        "import json,os\nfrom pathlib import Path\n"
        f"Path({str(observed)!r}).write_text(json.dumps({{"
        "'host_bound': os.environ.get('CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST') == '1',"
        "'endpoint_redirected': bool(os.environ.get('ANTHROPIC_BASE_URL')),"
        "'gateway_auth_present': bool(os.environ.get('ANTHROPIC_AUTH_TOKEN')),"
        "'proxy_present': bool(os.environ.get('HTTPS_PROXY')),"
        "'useful_setting': os.environ.get('HAPAX_SYNTHETIC_SETTING') == 'retained'}))\n"
    )
    (config / "settings.json").write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "https://gateway.invalid",
                    "ANTHROPIC_AUTH_TOKEN": "synthetic-gateway-token",
                    "CLAUDE_CODE_OAUTH_TOKEN": "synthetic-wrong-token",
                    "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST": "0",
                    "HTTPS_PROXY": "https://proxy.invalid",
                    "HAPAX_SYNTHETIC_SETTING": "retained",
                    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                },
                "apiKeyHelper": "echo synthetic-helper",  # pragma: allowlist secret
                "hooks": {
                    "Setup": [
                        {"hooks": [{"type": "command", "command": f"{sys.executable} {capture}"}]}
                    ]
                },
            }
        )
    )
    before = (config / "settings.json").read_bytes()
    env = {
        "HOME": str(tmp_path / "home"),
        "CLAUDE_CONFIG_DIR": str(config),
        "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
    }
    result = subprocess.run(
        [
            "unshare",
            "--user",
            "--map-root-user",
            "--net",
            sys.executable,
            str(REPO_ROOT / "scripts/hapax-claude-account-live-observe"),
            "--exec-interactive-subscription",
            binary,
            "--init-only",
        ],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, "isolated installed CLI initialization failed"
    assert json.loads(observed.read_text()) == {
        "host_bound": True,
        "endpoint_redirected": False,
        "gateway_auth_present": False,
        "proxy_present": False,
        "useful_setting": True,
    }
    assert (config / "settings.json").read_bytes() == before
