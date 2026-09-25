"""Request-time configuration tests. Credentials/provider responses are synthetic."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.scripts.test_claude_account_live_observe_per_route import obs

NOW = datetime(2026, 8, 19, 16, 0, 0, tzinfo=UTC)


@pytest.fixture
def subscription_probe_home(tmp_path, monkeypatch, request):
    home = tmp_path / "operator-home"
    config = home / ".claude"
    config.mkdir(parents=True)
    credential = config / ".credentials.json"
    credential.write_text(
        json.dumps(
            {
                "claudeAiOauth": {
                    "accessToken": "synthetic-subscription-access-token",
                    "refreshToken": "synthetic-refresh-token-must-not-be-forwarded",
                    "subscriptionType": "max",
                    "scopes": ["user:inference", "user:profile"],
                    "expiresAt": int(request.module.NOW.timestamp() * 1000) + 3600000,
                },
                "primaryApiKey": "synthetic-saved-api-key-must-not-be-forwarded",  # pragma: allowlist secret
            }
        )
    )
    credential.chmod(0o600)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    for name in list(os.environ):
        if name.startswith(("ANTHROPIC_", "CLAUDE_CODE_USE_")):
            monkeypatch.delenv(name)
    # Host policy is separately exercised; no real managed configuration is read.
    monkeypatch.setattr(request.module.obs, "PROBE_MANAGED_DIR", tmp_path / "absent-managed")
    return home, config, credential


def _fake_claude(tmp_path, monkeypatch):
    """Executable fixture loads settings AFTER exec, like the provider CLI."""
    observed = tmp_path / "request-binding.json"
    binary = tmp_path / "bin" / "claude"
    binary.parent.mkdir()
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "env = dict(os.environ)\n"
        "config = Path(env.get('CLAUDE_CONFIG_DIR', str(Path.home()/'.claude')))\n"
        "sources = sys.argv[sys.argv.index('--setting-sources')+1] "
        "if '--setting-sources' in sys.argv else 'user,project,local'\n"
        "paths = []\n"
        "if 'user' in sources: paths.append(config/'settings.json')\n"
        "if 'project' in sources: paths.append(Path.cwd()/'.claude/settings.json')\n"
        "if 'local' in sources: paths.append(Path.cwd()/'.claude/settings.local.json')\n"
        "for path in paths:\n"
        "    if path.exists(): env.update(json.loads(path.read_text()).get('env', {}))\n"
        "binding = {'endpoint': env.get('ANTHROPIC_BASE_URL', 'https://api.anthropic.com'),\n"
        " 'oauth_bound': env.get('CLAUDE_CODE_OAUTH_TOKEN') == 'synthetic-subscription-access-token',\n"
        " 'api_auth_present': bool(env.get('ANTHROPIC_API_KEY') or env.get('ANTHROPIC_AUTH_TOKEN')),\n"
        " 'home': env['HOME'], 'config': str(config), 'cwd': str(Path.cwd()),\n"
        " 'credential_file_present': (config/'.credentials.json').exists(),\n"
        " 'global_config_present': (Path.home()/'.claude.json').exists(),\n"
        " 'env_names': sorted(env)}\n"
        f"Path({str(observed)!r}).write_text(json.dumps(binding))\n"
        "print(json.dumps({'is_error': False, 'model': 'claude-opus-5',\n"
        " 'usage': {'input_tokens': 1, 'output_tokens': 1}}))\n"
    )
    binary.chmod(0o700)
    monkeypatch.setenv("PATH", f"{binary.parent}:{os.environ['PATH']}")
    return observed


@pytest.mark.parametrize("scope", ["user", "project", "local", "custom-config"])
def test_probe_request_cannot_reapply_gateway_settings(
    tmp_path, monkeypatch, subscription_probe_home, scope
):
    home, config, credential = subscription_probe_home
    project = tmp_path / "project"
    project.mkdir()
    if scope == "custom-config":
        config = tmp_path / "custom-config"
        config.mkdir()
        (config / ".credentials.json").write_bytes(credential.read_bytes())
        (config / ".credentials.json").chmod(0o600)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    path = config / "settings.json"
    if scope in {"project", "local"}:
        path = (
            project / ".claude" / ("settings.local.json" if scope == "local" else "settings.json")
        )
        path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "https://gateway.invalid",
                    "ANTHROPIC_AUTH_TOKEN": "synthetic-gateway-token",
                }
            }
        )
    )
    (home / ".claude.json").write_text(
        '{"primaryApiKey":"synthetic-api-key"}'  # pragma: allowlist secret
    )
    observed = _fake_claude(tmp_path, monkeypatch)
    event = obs.probe(NOW, cwd=str(project))
    assert event is not None and event.kind == "served"
    binding = json.loads(observed.read_text())
    assert binding["endpoint"] == "https://api.anthropic.com"
    assert binding["oauth_bound"] is True
    assert binding["api_auth_present"] is False
    assert binding["credential_file_present"] is False
    assert binding["global_config_present"] is False
    assert binding["home"] != str(home)
    assert binding["config"] != str(config)
    assert binding["cwd"] != str(project)
    assert not Path(binding["home"]).exists(), "temporary probe configuration must be removed"


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "invalid-json",
        "api-only",
        "empty-token",
        "expired",
        "expires-during-probe",
        "no-inference",
        "team",
        "unknown-plan",
    ],
)
def test_unproven_subscription_never_starts_request(
    tmp_path, monkeypatch, subscription_probe_home, defect
):
    _, _, credential = subscription_probe_home
    data = json.loads(credential.read_text())
    oauth = data["claudeAiOauth"]
    if defect == "missing":
        credential.unlink()
    elif defect == "invalid-json":
        credential.write_text("{")
    else:
        if defect == "api-only":
            del data["claudeAiOauth"]
        elif defect == "empty-token":
            oauth["accessToken"] = ""
        elif defect in {"expired", "expires-during-probe"}:
            oauth["expiresAt"] = int(NOW.timestamp() * 1000) + (
                1000 if defect == "expires-during-probe" else 0
            )
        elif defect == "no-inference":
            oauth["scopes"] = ["user:profile"]
        elif defect == "team":
            oauth["subscriptionType"] = "team"
        else:
            oauth["subscriptionType"] = None
        credential.write_text(json.dumps(data))
    observed = _fake_claude(tmp_path, monkeypatch)
    assert obs.probe(NOW) is None
    assert not observed.exists(), "unproven auth must hold before starting an inference"


def test_managed_configuration_is_held_not_bypassed(tmp_path, monkeypatch, subscription_probe_home):
    policy = tmp_path / "managed"
    policy.mkdir()
    (policy / "managed-settings.json").write_text(
        '{"env":{"ANTHROPIC_BASE_URL":"https://gateway.invalid"}}'
    )
    monkeypatch.setattr(obs, "PROBE_MANAGED_DIR", policy, raising=False)
    observed = _fake_claude(tmp_path, monkeypatch)
    assert obs.probe(NOW) is None
    assert not observed.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("subscriptionType", {}),
        ("scopes", "user:inference"),
        ("expiresAt", "9999999999999"),
        ("expiresAt", float("inf")),
        ("expiresAt", float("nan")),
        ("expiresAt", 10**400),
        ("expiresAt", True),
        ("accessToken", "synthetic token"),
        ("accessToken", {}),
    ],
)
def test_malformed_auth_metadata_holds_before_request(
    tmp_path, monkeypatch, subscription_probe_home, field, value
):
    credential = subscription_probe_home[2]
    data = json.loads(credential.read_text())
    data["claudeAiOauth"][field] = value
    credential.write_text(json.dumps(data))
    observed = _fake_claude(tmp_path, monkeypatch)
    assert obs.probe(NOW) is None
    assert not observed.exists()


def test_only_subscription_token_enters_child_and_failure_is_sanitized(
    tmp_path, monkeypatch, subscription_probe_home
):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "synthetic-inherited-token")
    monkeypatch.setenv("NODE_OPTIONS", "synthetic-injection")
    monkeypatch.setenv("HTTPS_PROXY", "https://gateway.invalid")
    child = {}

    def fail(argv, **kwargs):
        child.update(kwargs)
        raise obs.subprocess.TimeoutExpired(argv, 180, output="synthetic-sensitive-output")

    monkeypatch.setattr(obs.subprocess, "run", fail)
    event = obs.probe(NOW)
    assert event is not None and event.kind == "probe_failed"
    assert event.detail == "TimeoutExpired"
    assert child["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "synthetic-subscription-access-token"
    assert "NODE_OPTIONS" not in child["env"]
    assert "HTTPS_PROXY" not in child["env"]
    assert not Path(child["cwd"]).exists()


@pytest.mark.parametrize("changed_policy", [False, True])
def test_failed_process_or_changed_policy_cannot_mint(
    tmp_path, monkeypatch, subscription_probe_home, changed_policy
):
    def run(argv, **kwargs):
        if changed_policy:
            obs.PROBE_MANAGED_DIR.mkdir()
        return obs.subprocess.CompletedProcess(
            argv,
            0 if changed_policy else 1,
            json.dumps({"model": "claude-opus-5", "usage": {"input_tokens": 1}}),
            "",
        )

    monkeypatch.setattr(obs.subprocess, "run", run)
    assert obs.probe(NOW) is None


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_unbound_os_policy_holds_before_request(
    tmp_path, monkeypatch, subscription_probe_home, platform
):
    monkeypatch.setattr(obs.sys, "platform", platform)
    observed = _fake_claude(tmp_path, monkeypatch)
    assert obs.probe(NOW) is None
    assert not observed.exists()


def test_wsl_policy_holds_before_request(tmp_path, monkeypatch, subscription_probe_home):
    from types import SimpleNamespace

    monkeypatch.setattr(obs.os, "uname", lambda: SimpleNamespace(release="6.6-microsoft-WSL2"))
    observed = _fake_claude(tmp_path, monkeypatch)
    assert obs.probe(NOW) is None
    assert not observed.exists()


def test_unreadable_policy_holds_before_request(tmp_path, monkeypatch, subscription_probe_home):
    original = Path.stat

    def stat(path, *args, **kwargs):
        if path == obs.PROBE_MANAGED_DIR:
            raise PermissionError("synthetic policy denial")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    observed = _fake_claude(tmp_path, monkeypatch)
    assert obs.probe(NOW) is None
    assert not observed.exists()


def test_redirect_refusal_names_recovery_without_values(
    tmp_path, monkeypatch, subscription_probe_home, capsys
):
    monkeypatch.setenv("ANTHROPIC_UNBOUND_ROUTE", "synthetic-sensitive-value")
    observed = _fake_claude(tmp_path, monkeypatch)
    assert obs.probe(NOW) is None
    assert not observed.exists()
    error = capsys.readouterr().err
    assert "ANTHROPIC_UNBOUND_ROUTE" in error
    assert "Next action:" in error and "unset" in error and "retry" in error
    assert "synthetic-sensitive-value" not in error
