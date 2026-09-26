"""The real-harness import audit's world and verdict (the harness runs themselves need
credentials and are rerun by an operator or lane; see docs/runbooks/capability-envelope.md)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "capability-envelope-import-audit"


def _audit():
    loader = importlib.machinery.SourceFileLoader("capability_envelope_import_audit", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def test_the_world_seeds_a_unique_sentinel_at_every_common_import_path(tmp_path: Path):
    audit = _audit()
    world = audit.build_world(tmp_path / "world", tmp_path / "home")
    tokens = list(world.tokens.values())
    assert len(tokens) == len(set(tokens)) == 8
    for rel in ("ancestor/AGENTS.md", "ancestor/repo/CLAUDE.md", "mirror-home/AGENTS.md"):
        path = world.root / rel
        assert world.tokens[path] in path.read_text()


def test_the_world_is_create_once(tmp_path: Path):
    audit = _audit()
    audit.build_world(tmp_path / "world", tmp_path / "home")
    with pytest.raises(FileExistsError):
        audit.build_world(tmp_path / "world", tmp_path / "home")


def _obs(**overrides):
    base = {"returncode": 0, "tokens_in_reply": [], "sentinels_opened": [], "markers": []}
    return {**base, **overrides}


@pytest.mark.parametrize(
    ("enveloped", "expected"),
    [
        (_obs(sentinels_opened=["mirror-home/AGENTS.md"]), ("leak", 1)),
        (_obs(tokens_in_reply=["ancestor/AGENTS.md"]), ("leak", 1)),
        (_obs(markers=["undeclared-user-hook-ran"]), ("leak", 1)),
        (_obs(returncode=1, sentinels_opened=["x"]), ("leak", 1)),
        (_obs(returncode=1), ("inconclusive", 2)),
        (_obs(markers=["declared-hook-fired"]), ("clean", 0)),
    ],
    ids=["opened", "token", "undeclared-marker", "leak-outranks-failure", "failed", "clean"],
)
def test_the_verdict(enveloped: dict, expected: tuple[str, int]):
    baseline = _obs(sentinels_opened=["mirror-home/AGENTS.md"])
    assert _audit().verdict(baseline, enveloped, ("undeclared-user-hook-ran",)) == expected


def test_a_clean_run_without_a_witnessed_baseline_import_says_so():
    audit = _audit()
    assert audit.verdict(_obs(), _obs(), ()) == ("clean-no-control", 0)


# ---------------------------------------------------------------- launch builders and refusals
# Review of #4784 (claude-1): the builders and their refusal paths were untested. Each builder runs
# against a fake home and fake binaries; no harness is executed.


def _file(path: Path, text: str = "x\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _exe(path: Path) -> Path:
    _file(path, "#!/bin/sh\n").chmod(0o755)
    return path


def _world(tmp_path: Path):
    audit = _audit()
    home = tmp_path / "home"
    home.mkdir(parents=True)
    return audit, audit.build_world(tmp_path / "world", home)


def _targets(declaration) -> set[str]:
    return {c.target for c in declaration.credentials} | {f.target for f in declaration.home_files}


def test_claude_builder_binds_only_its_credential_and_package(tmp_path, monkeypatch):
    audit, world = _world(tmp_path)
    exe = _exe(tmp_path / "pkg" / "bin" / "claude.exe")
    monkeypatch.setenv("HAPAX_CLAUDE_BIN", str(exe))
    _file(world.home / ".claude" / ".credentials.json")
    launch = audit.claude_launch(world)
    decl = launch.declaration
    assert decl.harness == "claude" and decl.binaries == (tmp_path / "pkg",)
    assert _targets(decl) == {".claude/.credentials.json"}
    assert [h.event for h in decl.hooks] == ["SessionStart"]
    assert "--tools" in launch.baseline_argv


def test_opencode_builder_drops_secret_fields_and_needs_the_local_provider(tmp_path, monkeypatch):
    import json

    audit, world = _world(tmp_path)
    monkeypatch.setenv("HAPAX_OPENCODE_BIN", str(_exe(tmp_path / "pkg" / "bin" / "opencode.exe")))
    config = world.home / ".config" / "opencode" / "opencode.json"
    provider = {"options": {"baseURL": "http://x/v1", "apiKey": "sk-fixture"}, "models": {"m": {}}}
    _file(config, json.dumps({"provider": {"local-research": provider}}))
    launch = audit.opencode_launch(world)
    declared = (world.root / "declared" / "opencode.json").read_text()
    assert "sk-fixture" not in declared and "apiKey" not in declared
    assert launch.declaration.argv[1:4] == ("run", "--model", "local-research/m")
    _, other = _world(tmp_path / "again")
    _file(other.home / ".config" / "opencode" / "opencode.json", json.dumps({"provider": {}}))
    with pytest.raises(audit.Refused, match="no local-research provider"):
        audit.opencode_launch(other)


def test_grok_builder_binds_auth_writable_and_refuses_without_it(tmp_path, monkeypatch):
    audit, world = _world(tmp_path)
    monkeypatch.setenv("HAPAX_GROK_BIN", str(_exe(tmp_path / "bin" / "grok")))
    with pytest.raises(audit.Refused, match="sign grok in"):
        audit.grok_launch(world)
    _file(world.home / ".grok" / "auth.json")
    decl = audit.grok_launch(world).declaration
    assert [(c.target, c.writable) for c in decl.credentials] == [(".grok/auth.json", True)]
    assert "--disable-web-search" in decl.argv


def test_agy_builder_declares_token_installation_settings_and_helpers(tmp_path, monkeypatch):
    audit, world = _world(tmp_path)
    monkeypatch.setenv("HAPAX_AGY_BIN", str(_exe(tmp_path / "bin" / "agy")))
    agy_home = world.home / ".gemini" / "antigravity-cli"
    _file(agy_home / "antigravity-oauth-token")
    _file(agy_home / "installation_id")
    _exe(agy_home / "bin" / "helper")
    decl = audit.agy_launch(world).declaration
    assert _targets(decl) == {
        ".gemini/antigravity-cli/antigravity-oauth-token",
        ".gemini/antigravity-cli/installation_id",
        ".gemini/antigravity-cli/settings.json",
        ".gemini/antigravity-cli/bin",
    }
    assert not any("GEMINI.md" in t for t in _targets(decl))


def test_codex_builder_closes_stdin_and_refuses_without_auth(tmp_path, monkeypatch):
    audit, world = _world(tmp_path)
    monkeypatch.setenv("HAPAX_CODEX_BIN", str(_exe(tmp_path / "rel" / "bin" / "codex")))
    with pytest.raises(audit.Refused, match="sign codex in"):
        audit.codex_launch(world)
    _file(world.home / ".codex" / "auth.json")
    launch = audit.codex_launch(world)
    assert launch.stdin == ""
    assert launch.declaration.binaries == (tmp_path / "rel",)
    assert _targets(launch.declaration) == {".codex/auth.json"}


KIMI_CONFIG = {
    "default_model": "kimi-code/k3",
    "thinking": {"enabled": True, "effort": "high", "budget": 9},
    "hooks": [{"event": "PreToolUse", "command": "gate"}],
    "services": {"search": {"base_url": "https://s", "api_key": "svc-secret"}},
    "providers": {
        "managed:kimi-code": {
            "type": "kimi",
            "base_url": "https://k/v1",
            "api_key": "",
            "oauth": {"storage": "file", "key": "kimi-code"},
        }
    },
    "models": {
        "kimi-code/k3": {"provider": "managed:kimi-code", "model": "k3", "max_context_size": 9}
    },
}


def test_kimi_config_keeps_only_the_model_route():
    import copy
    import tomllib

    audit = _audit()
    text = audit.kimi_config(copy.deepcopy(KIMI_CONFIG), "kimi-code/k3")
    parsed = tomllib.loads(text)
    assert set(parsed) == {"default_model", "thinking", "providers", "models"}
    assert parsed["thinking"] == {"enabled": True, "effort": "high"}
    provider = parsed["providers"]["managed:kimi-code"]
    assert provider["api_key"] == "" and provider["oauth"] == {
        "storage": "file",
        "key": "kimi-code",
    }
    assert "svc-secret" not in text and "hooks" not in text and "services" not in text


def test_kimi_config_refuses_a_provider_api_key():
    import copy

    audit = _audit()
    config = copy.deepcopy(KIMI_CONFIG)
    config["providers"]["managed:kimi-code"]["api_key"] = "sk-fixture"
    with pytest.raises(audit.Refused, match="carries an api_key"):
        audit.kimi_config(config, "kimi-code/k3")
    with pytest.raises(audit.Refused, match="no model"):
        audit.kimi_config(copy.deepcopy(KIMI_CONFIG), "kimi-code/other")


def test_muse_builder_runs_the_release_binary_and_refuses_without_auth(tmp_path, monkeypatch):
    audit, world = _world(tmp_path)
    launcher = _exe(tmp_path / "bin" / "muse")
    release = _exe(tmp_path / "bin" / "muse-bin-1.4.0-R1")
    _file(tmp_path / "bin" / ".muse-version", "1.4.0-R1\n")
    monkeypatch.setenv("HAPAX_MUSE_BIN", str(launcher))
    with pytest.raises(audit.Refused, match="sign muse in"):
        audit.muse_launch(world)
    _file(world.home / ".config" / "muse" / "auth.json")
    launch = audit.muse_launch(world)
    assert launch.declaration.argv[0] == str(release)
    assert launch.baseline_argv[0] == str(launcher)


@pytest.mark.parametrize(
    ("harness", "env_var"),
    [
        ("claude", "HAPAX_CLAUDE_BIN"),
        ("opencode", "HAPAX_OPENCODE_BIN"),
        ("grok", "HAPAX_GROK_BIN"),
        ("agy", "HAPAX_AGY_BIN"),
        ("codex", "HAPAX_CODEX_BIN"),
    ],
)
def test_a_missing_binary_is_refused(tmp_path, monkeypatch, harness, env_var):
    audit, world = _world(tmp_path)
    monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(audit.Refused, match="binary not found"):
        audit.LAUNCHES[harness](world)


def test_vibe_builder_refuses_off_the_team_allowance(tmp_path, monkeypatch):
    import hashlib
    import json

    audit, world = _world(tmp_path)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setenv("HAPAX_VIBE_BIN", str(_exe(tmp_path / "tool" / "bin" / "vibe")))
    key = "fixture-key"
    _file(world.home / ".vibe" / ".env", f"MISTRAL_API_KEY={key}\n")
    entry = {hashlib.sha256(key.encode()).hexdigest()[:32]: {"payload": {"plan_type": "api"}}}
    _file(world.home / ".vibe" / "whoami_cache.json", json.dumps(entry))
    with pytest.raises(audit.Refused, match="not the Team allowance"):
        audit.vibe_launch(world)
    entry[next(iter(entry))]["payload"]["plan_type"] = "chat"
    _file(world.home / ".vibe" / "whoami_cache.json", json.dumps(entry))
    decl = audit.vibe_launch(world).declaration
    assert _targets(decl) == {".vibe/.env", ".vibe/trusted_folders.toml"}
