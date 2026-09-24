"""Dispatch -> real launcher -> runner -> child, with synthetic auth and no provider calls."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import shlex
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
from tests.scripts.test_hapax_quota_telemetry_writer import _run_writer

NOW = datetime.now(UTC)


def bound_ledger(tmp_path):
    """Synthetic fresh A observation, independently construct the opaque proof."""
    path = _fresh_claude_subscription_quota_ledger(tmp_path, route_id="claude.interactive.full")
    payload = json.loads(path.read_text())
    for snapshot in payload["quota_snapshots"]:
        if snapshot["route_id"] != "claude.interactive.full":
            continue
        refs = []
        for ref in snapshot["evidence_refs"]:
            stamp = datetime.fromisoformat(
                ref.split(":observed_at:")[1].split(":fresh_until:")[0]
            ).isoformat()
            proof = hmac.new(
                b"synthetic-subscription-access-token",
                f"hapax:claude:subscription:first-party:credential-binding:v1:{stamp}".encode(),
                hashlib.sha256,
            ).hexdigest()
            refs.append(
                ref.replace(
                    ":account-live-quota:observed",
                    f":credential_binding:{proof}:account-live-quota:observed",
                )
            )
        snapshot["evidence_refs"] = refs
    path = tmp_path / "bound-ledger.json"
    path.write_text(json.dumps(payload))
    return path


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
        "export HAPAX_QUOTA_SPEND_LEDGER=/synthetic-unbound-ledger\n"
        'exec "$runner" ;;\n*) exit 0 ;;\nesac\n'
    )
    (binary / "tmux").chmod(0o700)
    (config / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": []}}))
    env = {
        "PATH": f"{binary}:{Path(sys.executable).parent}:/usr/bin:/bin",
        "HAPAX_METHODOLOGY_CLAUDE_LAUNCHER": str(REPO_ROOT / "scripts/hapax-claude"),
        "HAPAX_COUNCIL_DIR": str(REPO_ROOT),
        "HAPAX_CLAUDE_WORKTREE_ROOT": str(home / "projects"),
        "HAPAX_QUOTA_SPEND_LEDGER": str(bound_ledger(tmp_path)),
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
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER", str(bound_ledger(tmp_path)))
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


@pytest.mark.parametrize("when", ["before-dispatch", "inside-tmux"])
def test_receipt_for_account_a_cannot_launch_account_b(tmp_path, when):
    env, config, _, observed, credential = launch_fixture(tmp_path)
    other = tmp_path / "account-b"
    other.mkdir()
    data = json.loads(credential.read_text())
    data["claudeAiOauth"]["accessToken"] = "synthetic-distinct-account-b"
    (other / ".credentials.json").write_text(json.dumps(data))
    if when == "before-dispatch":
        env["CLAUDE_CONFIG_DIR"] = str(other)
    else:
        tmux = tmp_path / "bin/tmux"
        tmux.write_text(
            tmux.read_text().replace(
                "for runner; do :; done",
                f'for runner; do :; done\ncp "{other}/.credentials.json" "{config}/.credentials.json"',
            )
        )
    result = dispatch(tmp_path, env)
    assert result.returncode != 0
    assert "credential" in result.stderr and "Next action:" in result.stderr
    assert "synthetic-distinct-account-b" not in result.stdout + result.stderr
    assert not observed.exists()
    if when == "before-dispatch":
        assert not (tmp_path / "home/.cache/hapax/claude-spawns").exists()


@pytest.mark.parametrize("source", ["registry", "listed"])
def test_advertised_interactive_launcher_invokes_subscription_guard(tmp_path, source):
    env, _, _, observed, credential = launch_fixture(tmp_path)
    if source == "registry":
        registry = json.loads((REPO_ROOT / "config/platform-capability-registry.json").read_text())
        route = next(r for r in registry["routes"] if r["route_id"] == "claude.interactive.full")
    else:
        result = subprocess.run(
            [str(REPO_ROOT / "scripts/hapax-methodology-dispatch"), "--list-platform-paths"],
            text=True,
            capture_output=True,
            check=True,
        )
        line = next(
            line
            for line in result.stdout.splitlines()
            if line.startswith("claude/interactive/full:")
        )
        route = {"launcher": line.split(" -> ", 1)[1]}
    command = shlex.split(
        route["launcher"].replace("<lane>", "beta").replace("<task>", "governed-build")
    )
    assert "--subscription-only" in command
    credential.unlink()
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env={**os.environ, **env, "HOME": str(tmp_path / "home")},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "subscription authentication or host policy is unproven" in result.stderr
    assert not observed.exists()


@pytest.mark.parametrize("defect", ["legacy", "malformed", "missing", "wrong-proof"])
def test_launch_holds_without_readable_matching_proof(tmp_path, defect):
    env, _, _, observed, _ = launch_fixture(tmp_path)
    path = Path(env["HAPAX_QUOTA_SPEND_LEDGER"])
    if defect == "missing":
        path.unlink()
    elif defect == "malformed":
        path.write_text("{}")
    else:
        payload = json.loads(path.read_text())
        for snapshot in payload["quota_snapshots"]:
            if snapshot["route_id"] != "claude.interactive.full":
                continue
            ref = snapshot["evidence_refs"][0]
            start, suffix = ref.split(":credential_binding:")
            proof, end = suffix.split(":", 1)
            snapshot["evidence_refs"] = [
                start + ":" + end
                if defect == "legacy"
                else start + ":credential_binding:" + "0" * 64 + ":" + end
            ]
        path.write_text(json.dumps(payload))
    result = dispatch(tmp_path, env)
    assert result.returncode != 0
    assert not observed.exists()


@pytest.mark.parametrize("failure", ["exec", "evidence-expired"])
@pytest.mark.usefixtures("subscription_probe_home")
def test_final_exec_boundary_holds_without_leaking_errors(tmp_path, monkeypatch, capsys, failure):
    ledger = bound_ledger(tmp_path)
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER", str(ledger))

    def check(argv, **kwargs):
        if "--version" in argv:
            return subprocess.CompletedProcess(argv, 0, "2.1.281 (Claude Code)", "")
        if failure == "evidence-expired":
            ledger.unlink()
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps(
                {
                    "loggedIn": True,
                    "authMethod": "oauth_token",
                    "apiProvider": "firstParty",
                    "apiKeySource": None,
                }
            ),
            "",
        )

    calls = []

    def fail_exec(*args):
        calls.append(True)
        raise OSError("synthetic-sensitive-exec-error")

    monkeypatch.setattr(obs.subprocess, "run", check)
    monkeypatch.setattr(obs.os, "execvpe", fail_exec)
    assert obs.interactive_subscription(["claude"], execute=True) == 4
    assert bool(calls) is (failure == "exec")
    error = capsys.readouterr().err
    expected = "bound CLI could not start" if failure == "exec" else "evidence expired or changed"
    assert expected in error and "Next action:" in error
    assert "synthetic-sensitive-exec-error" not in error


@pytest.mark.parametrize("change_account", [False, True])
def test_real_probe_receipt_and_telemetry_bind_actual_launch(tmp_path, monkeypatch, change_account):
    env, _, _, observed, credential = launch_fixture(tmp_path)
    now = datetime.now(UTC).replace(microsecond=0)
    real_run = subprocess.run

    def served(argv, **kwargs):
        if argv == list(obs.PROBE_ARGV):
            assert kwargs["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "synthetic-subscription-access-token"
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps(
                    {
                        "model": "claude-opus-5",
                        "usage": {"input_tokens": 1, "output_tokens": 1},
                        "is_error": False,
                    }
                ),
                "",
            )
        return real_run(argv, **kwargs)

    with monkeypatch.context() as context:
        context.setenv("CLAUDE_CONFIG_DIR", env["CLAUDE_CONFIG_DIR"])
        for name in list(obs.provider_redirect_env()):
            context.delenv(name)
        context.setattr(obs.subprocess, "run", served)
        observation = obs.probe(now)
        assert observation is not None and observation.kind == "served"
        results = obs.mint(
            observation,
            now=now,
            route_ids=("claude.interactive.full",),
            stale_after_seconds=900,
            receipt_dir=tmp_path / "relay-receipts",
            dry_run=False,
        )
        assert results[0]["returncode"] == 0
    writer, ledger = _run_writer(tmp_path, now=now.isoformat())
    assert writer.returncode == 0, writer.stderr
    env["HAPAX_QUOTA_SPEND_LEDGER"] = str(ledger)
    if change_account:
        data = json.loads(credential.read_text())
        data["claudeAiOauth"]["accessToken"] = "synthetic-distinct-account-b"
        credential.write_text(json.dumps(data))
    result = dispatch(tmp_path, env)
    assert (result.returncode == 0) is not change_account, result.stdout + result.stderr
    assert observed.exists() is not change_account
    for path in [ledger, *list((tmp_path / "relay-receipts").glob("*.yaml"))]:
        assert "synthetic-subscription-access-token" not in path.read_text()


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
        "HAPAX_QUOTA_SPEND_LEDGER": str(bound_ledger(tmp_path)),
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


def test_installed_cli_request_does_not_reach_settings_gateway(tmp_path):
    """Positive canary control plus guarded real request, isolated from all providers."""
    binary = os.environ.get("HAPAX_CLAUDE_CONTRACT_BINARY")
    if not binary:
        pytest.skip("set HAPAX_CLAUDE_CONTRACT_BINARY for isolated installed-CLI check")
    env, config, workdir, _, _ = launch_fixture(tmp_path)
    result = subprocess.run(
        [
            "unshare",
            "--user",
            "--map-root-user",
            "--net",
            sys.executable,
            str(REPO_ROOT / "tests/fixtures/claude_gateway_contract.py"),
            binary,
            str(REPO_ROOT / "scripts/hapax-claude-account-live-observe"),
        ],
        cwd=workdir,
        env={
            "HOME": str(tmp_path / "home"),
            "CLAUDE_CONFIG_DIR": str(config),
            "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
            "HAPAX_QUOTA_SPEND_LEDGER": env["HAPAX_QUOTA_SPEND_LEDGER"],
        },
        capture_output=True,
        text=True,
        timeout=100,
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout)
    (tmp_path / "gateway-observation.json").write_text(result.stdout)
    assert evidence["unguarded"]["gateway_requests"] > 0, evidence
    assert evidence["guarded"]["gateway_requests"] == 0, evidence
    assert evidence["guarded"]["connection_failure"] is True, evidence
    assert evidence["guarded"]["timed_out"] is False, evidence
    assert evidence["settings_unchanged"] is True
