"""The real-harness import audit's world and verdict (the harness runs themselves need
credentials and are rerun by an operator or lane; see docs/runbooks/capability-envelope.md)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import shutil
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
        (_obs(overflowed=True), ("inconclusive", 2)),
    ],
    ids=[
        "opened",
        "token",
        "undeclared-marker",
        "leak-outranks-failure",
        "failed",
        "clean",
        "enveloped-overflow",
    ],
)
def test_the_verdict(enveloped: dict, expected: tuple[str, int]):
    baseline = _obs(sentinels_opened=["mirror-home/AGENTS.md"])
    assert _audit().verdict(baseline, enveloped, ("undeclared-user-hook-ran",)) == expected


def test_the_verdict_cannot_be_clean_on_an_overflowed_or_failed_baseline():
    """Clause (7) of the row (codex-1, 2026-09-28): an overflowed queue drops events, so a clean
    enveloped run proves nothing; and a baseline that FAILED proves only that the probe can detect
    one import, not that it reached every sentinel."""
    audit = _audit()
    witnessed = _obs(sentinels_opened=["mirror-home/AGENTS.md"])
    assert audit.verdict(_obs(overflowed=True), witnessed, ()) == ("inconclusive", 2)
    assert audit.verdict(
        _obs(sentinels_opened=["mirror-home/AGENTS.md"], returncode=1), _obs(), ()
    ) == ("inconclusive", 2)


def test_a_clean_run_without_a_witnessed_baseline_import_says_so():
    """Review of #4784 (codex-1): the control is what makes a clean run evidence. With no
    witnessed baseline import the same observation is what a dead probe produces, so the audit
    reports it and exits non-zero — never 0."""
    audit = _audit()
    assert audit.verdict(_obs(), _obs(), ()) == ("clean-no-control", 2)


def test_main_exits_nonzero_when_the_baseline_control_witnessed_nothing(tmp_path, monkeypatch):
    """The exit code, not only the label: a clean-no-control audit must not leave a caller with a
    passing status. Runs main() end to end with the harness launch stubbed out."""
    import json

    audit = _audit()

    class _World:
        def __init__(self, root: Path):
            self.root = root
            self.home = root / "home"
            self.spool = root / "spool"
            self.home.mkdir(parents=True, exist_ok=True)
            self.spool.mkdir(parents=True, exist_ok=True)
            self.markers = ("declared-hook-fired",)

    monkeypatch.setattr(audit, "build_world", lambda root, home: _World(root))
    monkeypatch.setitem(audit.LAUNCHES, "codex", lambda world: None)
    # The baseline control witnessed nothing; the enveloped run imported nothing.
    monkeypatch.setattr(audit, "run_baseline", lambda world, launch: _obs())
    monkeypatch.setattr(audit, "run_enveloped", lambda world, launch: _obs())
    out = tmp_path / "report.json"
    code = audit.main(["--harness", "codex", "--out", str(out), "--root", str(tmp_path / "w")])
    assert code == 2
    assert json.loads(out.read_text(encoding="utf-8"))["verdict"] == "clean-no-control"


# ---------------------------------------------------------------- the baseline's writable surface
# Review of #4793 (dev21, 2026-09-28): the baseline ran `bwrap --dev-bind / /`, so the host root
# was read-write — /tmp, /etc and /store-fast were writable to the baseline harness — while the
# script claimed the operator's files were "neither read nor changed". The baseline must read what
# a real harness reads (that is how it detects imports) and change nothing outside its mirror.

needs_bwrap = pytest.mark.skipif(
    shutil.which("bwrap") is None and os.environ.get("HAPAX_ENVELOPE_REQUIRE_BWRAP") != "1",
    reason="bubblewrap is unavailable",
)


@needs_bwrap
def test_the_baseline_changes_nothing_outside_its_mirror(tmp_path: Path):
    audit = _audit()
    home = tmp_path / "home"
    home.mkdir(parents=True)
    world = audit.build_world(tmp_path / "world", home)
    outside = tmp_path / "host" / "written-by-the-baseline"
    outside.parent.mkdir(parents=True, exist_ok=True)
    launch = audit.Launch(
        baseline_argv=[
            "/bin/sh",
            "-c",
            f'touch {outside}; echo OUTSIDE=$?; touch "$HOME/written-in-mirror"; echo MIRROR=$?',
        ],
        binds=[],
        declaration=audit.EnvelopeDeclaration(harness="claude", argv=("/bin/true",)),
    )
    observed = audit.run_baseline(world, launch)
    assert not outside.exists(), "the baseline wrote outside its mirror"
    assert (world.mirror / "written-in-mirror").exists(), "the mirrored home must stay writable"
    assert "MIRROR=0" in f"{observed['stdout_tail']}{observed['stderr_tail']}"


# ---------------------------------------------------------------- launch builders and refusals
# Review of #4793 (dev21, 2026-09-28): the builders and their refusal paths were untested although
# the audit's evidence rests on them. Each builder runs against a fake home and fake binaries here;
# no harness is executed.


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


def test_claude_builder_refuses_without_a_binary(tmp_path, monkeypatch):
    audit, world = _world(tmp_path)
    monkeypatch.delenv("HAPAX_CLAUDE_BIN", raising=False)
    monkeypatch.setattr(audit.shutil, "which", lambda _name: None)
    with pytest.raises(audit.Refused, match="claude binary not found"):
        audit.claude_launch(world)


def _fake_wrapper(plan: str, binary: Path, command):
    class _Wrapper:
        TEAM_PLAN_TYPE = "team"

        @staticmethod
        def binding_plan_type(home: Path) -> str:
            return plan

        @staticmethod
        def vibe_bin() -> str:
            return "" if binary is None else str(binary)

        @staticmethod
        def muse_bin() -> str:
            return "" if binary is None else str(binary)

        @staticmethod
        def command(binary_: str, prompt: Path, workdir: Path) -> list[str]:
            return command(binary_, prompt, workdir)

    return _Wrapper


def test_vibe_builder_declares_its_key_and_trusted_folders(tmp_path, monkeypatch):
    audit, world = _world(tmp_path)
    binary = _exe(tmp_path / "pkg" / "bin" / "vibe")
    _file(world.home / ".vibe" / ".env", "VIBE_API_KEY=x\n")  # pragma: allowlist secret
    monkeypatch.setattr(
        audit,
        "_load_script",
        lambda _name: _fake_wrapper(
            "team", binary, lambda b, prompt, workdir: [b, "-p", str(prompt), str(workdir)]
        ),
    )
    launch = audit.vibe_launch(world)
    decl = launch.declaration
    assert decl.harness == "vibe"
    assert decl.binaries == (tmp_path / "pkg",)
    assert _targets(decl) == {".vibe/.env", ".vibe/trusted_folders.toml"}


def test_vibe_builder_refuses_off_the_team_allowance(tmp_path, monkeypatch):
    audit, world = _world(tmp_path)
    binary = _exe(tmp_path / "pkg" / "bin" / "vibe")
    monkeypatch.setattr(
        audit, "_load_script", lambda _name: _fake_wrapper("chat", binary, lambda *a: ["vibe"])
    )
    with pytest.raises(audit.Refused, match="not the Team allowance"):
        audit.vibe_launch(world)


def test_muse_builder_runs_the_release_beside_the_launcher(tmp_path, monkeypatch):
    audit, world = _world(tmp_path)
    directory = tmp_path / "pkg" / "bin"
    launcher = _exe(directory / "muse")
    release = _exe(directory / "muse-bin-1.4.0")
    _file(directory / ".muse-version", "1.4.0\n")
    _file(world.home / ".config" / "muse" / "auth.json")
    monkeypatch.setenv("HAPAX_MUSE_BIN", str(launcher))
    monkeypatch.setattr(
        audit,
        "_load_script",
        lambda _name: _fake_wrapper(
            "team", launcher, lambda b, prompt, workdir: [b, str(prompt), str(workdir)]
        ),
    )
    launch = audit.muse_launch(world)
    decl = launch.declaration
    assert decl.harness == "muse"
    # The self-updater (the launcher) is never the binary the envelope runs.
    assert decl.binaries == (release.resolve(),)
    assert decl.argv[0] == str(release)
    assert _targets(decl) == {"review-prompt.md", ".config/muse/auth.json"}
    assert decl.env == {"MUSE_NO_AUTO_UPDATE": "1"}
    assert launch.baseline_argv[0] == str(launcher)


def test_muse_builder_refuses_without_a_binary(tmp_path, monkeypatch):
    audit, world = _world(tmp_path)
    monkeypatch.setattr(
        audit, "_load_script", lambda _name: _fake_wrapper("team", None, lambda *a: ["m"])
    )
    with pytest.raises(audit.Refused, match="muse binary not found"):
        audit.muse_launch(world)


def test_muse_release_accepts_a_direct_release_binary(tmp_path: Path):
    """codex-1's major (2026-09-28): the refusal advises pointing HAPAX_MUSE_BIN at the release
    binary, so that path must actually work."""
    audit = _audit()
    release = _exe(tmp_path / "bin" / "muse-bin-9.9.9")
    assert audit._muse_release(release) == release.resolve()


def test_a_root_that_already_exists_is_refused(tmp_path: Path, monkeypatch, capsys):
    """glm-1's minor (2026-09-28): an existing --root used to raise FileExistsError as a
    traceback rather than a refusal with a next action."""
    audit = _audit()
    existing = tmp_path / "already-there"
    existing.mkdir()
    monkeypatch.setattr(audit, "LAUNCHES", {"claude": lambda world: None})
    code = audit.main(
        ["--harness", "claude", "--out", str(tmp_path / "o.json"), "--root", str(existing)]
    )
    assert code == 64
    assert "already exists" in capsys.readouterr().err


def test_muse_release_refuses_rather_than_running_the_self_updating_launcher(tmp_path: Path):
    """codex-1's minor, ruled clause (7) (2026-09-28): the audit must never run muse's
    self-updater inside the envelope, so every way the release cannot be established REFUSES
    rather than falling back to the launcher."""
    audit = _audit()
    launcher = _exe(tmp_path / "bin" / "muse")
    # No version file beside the launcher: the release cannot be established, so refuse.
    with pytest.raises(audit.Refused, match="names no release.*next action"):
        audit._muse_release(launcher)
    # A version file naming a release that is not there: refuse too.
    _file(tmp_path / "bin" / ".muse-version", "9.9.9\n")
    with pytest.raises(audit.Refused, match="is not there.*next action"):
        audit._muse_release(launcher)
    # A version naming a real release binary: the release runs, never the self-updating launcher.
    release = _exe(tmp_path / "bin" / "muse-bin-9.9.9")
    assert audit._muse_release(launcher) == release


def test_vibe_builder_refuses_without_a_binary(tmp_path, monkeypatch):
    audit, world = _world(tmp_path)
    monkeypatch.setattr(
        audit, "_load_script", lambda _name: _fake_wrapper("team", None, lambda *a: ["v"])
    )
    with pytest.raises(audit.Refused, match="vibe binary not found"):
        audit.vibe_launch(world)


def test_opencode_builder_drops_secret_fields_and_needs_the_local_provider(tmp_path, monkeypatch):
    import json

    audit, world = _world(tmp_path)
    monkeypatch.setenv("HAPAX_OPENCODE_BIN", str(_exe(tmp_path / "pkg" / "bin" / "opencode.exe")))
    config = world.home / ".config" / "opencode" / "opencode.json"
    provider = {
        "options": {
            "baseURL": "http://127.0.0.1:8080/v1",
            "apiKey": "sk-fixture",  # pragma: allowlist secret
        },  # pragma: allowlist secret
        "models": {"m": {}},
    }  # pragma: allowlist secret
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
    "services": {
        "search": {"base_url": "https://s", "api_key": "svc-secret"}  # pragma: allowlist secret
    },  # pragma: allowlist secret
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

KIMI_CONFIG_TOML = """default_model = "kimi-code/k3"

[thinking]
enabled = true
effort = "high"
budget = 9

[[hooks]]
event = "PreToolUse"
command = "gate"

[services.search]
base_url = "https://s"
api_key = "svc-secret"  # pragma: allowlist secret

[providers."managed:kimi-code"]
type = "kimi"
base_url = "https://k/v1"
api_key = ""
oauth.storage = "file"
oauth.key = "kimi-code"

[models."kimi-code/k3"]
provider = "managed:kimi-code"
model = "k3"
max_context_size = 9
"""


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
    config["providers"]["managed:kimi-code"]["api_key"] = "sk-fixture"  # pragma: allowlist secret
    with pytest.raises(audit.Refused, match="carries an api_key"):
        audit.kimi_config(config, "kimi-code/k3")
    with pytest.raises(audit.Refused, match="no model"):
        audit.kimi_config(copy.deepcopy(KIMI_CONFIG), "kimi-code/other")


def test_a_binary_override_that_is_not_an_executable_file_is_refused(tmp_path, monkeypatch):
    """codex-1's major (2026-09-28): a stale HAPAX_*_BIN used to pass the "not found" refusal and
    fail later, at launch, where the failure reads as a harness problem."""
    audit = _audit()
    missing = tmp_path / "nowhere" / "agy"
    monkeypatch.setenv("HAPAX_AGY_BIN", str(missing))
    with pytest.raises(audit.Refused, match="is not an executable file; next action"):
        audit._binary("HAPAX_AGY_BIN", "agy")
    plain = _file(tmp_path / "not-executable")
    plain.chmod(0o644)
    monkeypatch.setenv("HAPAX_AGY_BIN", str(plain))
    with pytest.raises(audit.Refused, match="is not an executable file; next action"):
        audit._binary("HAPAX_AGY_BIN", "agy")


def test_the_claude_builder_routes_through_the_same_checked_binary(tmp_path, monkeypatch):
    audit, world = _world(tmp_path)
    _file(world.home / ".claude" / ".credentials.json")
    monkeypatch.setenv("HAPAX_CLAUDE_BIN", str(tmp_path / "nowhere" / "claude"))
    with pytest.raises(audit.Refused, match="is not an executable file; next action"):
        audit.claude_launch(world)


def test_kimi_builder_declares_credentials_device_and_the_rebuilt_config(tmp_path, monkeypatch):
    """gemini-1's major (2026-09-28): the kimi builder's binds, declaration and refusals were
    never exercised directly, only `kimi_config` was."""
    import tomllib

    audit, world = _world(tmp_path)
    kimi_home = world.home / ".kimi-code"
    kimi_bin = _exe(kimi_home / "bin" / "kimi")
    monkeypatch.setenv("HAPAX_KIMI_BIN", str(kimi_bin))
    _file(kimi_home / "credentials")
    _file(kimi_home / "device_id")
    _file(kimi_home / "config.toml", KIMI_CONFIG_TOML)
    launch = audit.kimi_launch(world)
    decl = launch.declaration
    assert decl.harness == "kimi"
    assert decl.binaries == (kimi_bin,)
    assert {c.target: c.writable for c in decl.credentials} == {".kimi-code/credentials": True}
    assert {f.target for f in decl.home_files} == {".kimi-code/device_id", ".kimi-code/config.toml"}
    rebuilt = (world.root / "declared" / "kimi-config.toml").read_text(encoding="utf-8")
    assert "svc-secret" not in rebuilt and "hooks" not in rebuilt  # pragma: allowlist secret
    assert tomllib.loads(rebuilt)["providers"]["managed:kimi-code"]["api_key"] == ""
    assert [source for source, _ in launch.binds] == [
        kimi_home / "credentials",
        kimi_home / "device_id",
        kimi_home / "bin" / "kimi",
    ]
    _, other = _world(tmp_path / "again")
    _exe(other.home / ".kimi-code" / "bin" / "kimi")
    _file(other.home / ".kimi-code" / "credentials")
    _file(other.home / ".kimi-code" / "device_id")
    _file(other.home / ".kimi-code" / "config.toml", "not = [toml\n")
    with pytest.raises(audit.Refused, match="kimi config unreadable.*next action"):
        audit.kimi_launch(other)


def test_the_agy_builder_omits_the_helpers_directory_when_it_is_not_one(tmp_path, monkeypatch):
    """gemini-1's minor (2026-09-28): the `helpers` branch — a directory is declared and bound, a
    non-directory is left out rather than rejected."""
    audit, world = _world(tmp_path)
    monkeypatch.setenv("HAPAX_AGY_BIN", str(_exe(tmp_path / "bin" / "agy")))
    agy_home = world.home / ".gemini" / "antigravity-cli"
    _file(agy_home / "antigravity-oauth-token")
    _file(agy_home / "installation_id")
    _file(agy_home / "bin")  # a FILE where the builder expects a directory
    launch = audit.agy_launch(world)
    assert ".gemini/antigravity-cli/bin" not in _targets(launch.declaration)
    assert all(source != agy_home / "bin" for source, _ in launch.binds)


def test_carries_secret_sees_a_secret_inside_a_list():
    """gemini-1's minor (2026-09-28): the list branch of `_carries_secret`."""
    audit = _audit()
    assert audit._carries_secret({"redirects": ["https://x"]}) is False
    present = {"redirects": [{"api_key": "x"}]}  # pragma: allowlist secret
    assert audit._carries_secret(present) is True
    blank = {"redirects": [{"api_key": ""}]}  # pragma: allowlist secret
    assert audit._carries_secret(blank) is False


def test_the_opencode_builder_refuses_an_unreadable_config(tmp_path, monkeypatch):
    audit, world = _world(tmp_path)
    monkeypatch.setenv("HAPAX_OPENCODE_BIN", str(_exe(tmp_path / "pkg" / "bin" / "opencode.exe")))
    _file(world.home / ".config" / "opencode" / "opencode.json", "{not json")
    with pytest.raises(audit.Refused, match="opencode config unreadable.*next action"):
        audit.opencode_launch(world)


def test_the_opencode_builder_refuses_a_remote_endpoint(tmp_path, monkeypatch):
    """codex-1's major (2026-09-28): the provider NAME does not prove the endpoint is local, so the
    "$0 launch" claim could hold for a remote endpoint."""
    import json

    audit, world = _world(tmp_path)
    monkeypatch.setenv("HAPAX_OPENCODE_BIN", str(_exe(tmp_path / "pkg" / "bin" / "opencode.exe")))
    provider = {"options": {"baseURL": "https://api.example.com/v1"}, "models": {"m": {}}}
    _file(
        world.home / ".config" / "opencode" / "opencode.json",
        json.dumps({"provider": {"local-research": provider}}),
    )
    with pytest.raises(audit.Refused, match="is not a local, zero-cost endpoint.*next action"):
        audit.opencode_launch(world)
    # A host declared local is accepted.
    monkeypatch.setenv("HAPAX_OPENCODE_LOCAL_HOSTS", "spark-01df")
    provider["options"]["baseURL"] = "http://spark-01df:8000/v1"
    _file(
        world.home / ".config" / "opencode" / "opencode.json",
        json.dumps({"provider": {"local-research": provider}}),
    )
    assert audit.opencode_launch(world).declaration.harness == "opencode"


def test_the_opencode_builder_refuses_a_config_that_is_not_an_object(tmp_path, monkeypatch):
    """codex-1's minor (2026-09-28): a JSON ARRAY parses, then `config.get` raised AttributeError
    instead of a Refused with exit 64."""
    import json

    audit, world = _world(tmp_path)
    monkeypatch.setenv("HAPAX_OPENCODE_BIN", str(_exe(tmp_path / "pkg" / "bin" / "opencode.exe")))
    _file(
        world.home / ".config" / "opencode" / "opencode.json", json.dumps(["not", "an", "object"])
    )
    with pytest.raises(audit.Refused, match="is not an object; next action"):
        audit.opencode_launch(world)


def test_the_opencode_builder_refuses_a_provider_that_is_not_a_table(tmp_path, monkeypatch):
    """glm-1's minor (2026-09-28): the refusal for a provider that is not a table fires BEFORE the
    scrub, so it is reachable — the `assert` that used to stand after the scrub could never fail
    and is stripped by `python -O` besides."""
    import json

    audit, world = _world(tmp_path)
    monkeypatch.setenv("HAPAX_OPENCODE_BIN", str(_exe(tmp_path / "pkg" / "bin" / "opencode.exe")))
    _file(
        world.home / ".config" / "opencode" / "opencode.json",
        json.dumps({"provider": {"local-research": ["not", "a", "table"]}}),
    )
    with pytest.raises(audit.Refused, match="has no local-research provider with a model"):
        audit.opencode_launch(world)


def test_without_secrets_drops_secret_keys_inside_lists_too():
    """gemini-1's minor (2026-09-28): the list branch of `_without_secrets`."""
    audit = _audit()
    scrubbed = audit._without_secrets(
        {
            "servers": [
                {"api_key": "sk-fixture", "keep": 1},  # pragma: allowlist secret
                {"token": "x", "keep": 2},  # pragma: allowlist secret
            ]
        }
    )
    assert scrubbed == {"servers": [{"keep": 1}, {"keep": 2}]}


def test_a_binary_override_falls_back_to_the_default_path(tmp_path, monkeypatch):
    """gemini-1's minor (2026-09-28): the `default=` branch of `_binary` (kimi's vendored path)."""
    audit = _audit()
    vendor = _exe(tmp_path / "vendor" / "kimi")
    monkeypatch.delenv("HAPAX_KIMI_BIN", raising=False)
    monkeypatch.setattr(audit.shutil, "which", lambda _name: None)
    assert audit._binary("HAPAX_KIMI_BIN", "kimi", default=vendor) == vendor.resolve()


def test_kimi_refusals_name_their_next_actions():
    """gemini-1's minor (2026-09-28): the missing-provider and the OAuth-secret refusals."""
    import copy

    audit = _audit()
    config = copy.deepcopy(KIMI_CONFIG)
    config["models"]["kimi-code/k3"]["provider"] = "managed:absent"
    with pytest.raises(audit.Refused, match="no provider.*next action"):
        audit.kimi_config(config, "kimi-code/k3")
    secret = copy.deepcopy(KIMI_CONFIG)
    secret["providers"]["managed:kimi-code"]["oauth"] = {
        "storage": "file",
        "key": "kimi-code",
        "api_key": "sk-fixture",  # pragma: allowlist secret
    }
    with pytest.raises(audit.Refused, match="OAuth block carries a secret; next action"):
        audit.kimi_config(secret, "kimi-code/k3")


def test_a_launch_stdin_reaches_both_runs(tmp_path, monkeypatch):
    """gemini-1's minor (2026-09-28): codex's one-shot needs its stdin closed, and that travels
    from the Launch into BOTH the baseline subprocess call and the enveloped carrier. The runs
    themselves are stubbed; the plumbing under test is not."""
    import subprocess as _subprocess

    audit = _audit()
    home = tmp_path / "home"
    home.mkdir(parents=True)
    world = audit.build_world(tmp_path / "world", home)

    class _Watch:
        def __init__(self, paths):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def opened(self):
            return set()

        def overflowed(self):
            return False

        def truncated(self):
            return False

    calls: dict[str, object] = {}
    completed = _subprocess.CompletedProcess([], 0, stdout="", stderr="")

    def _run(argv, **kwargs):
        calls["baseline"] = kwargs.get("input")
        return completed

    def _execute(rendered, **kwargs):
        calls["enveloped"] = kwargs.get("stdin")
        return completed

    monkeypatch.setattr(audit, "OpenWatch", _Watch)
    monkeypatch.setattr(audit.subprocess, "run", _run)
    monkeypatch.setattr(audit, "execute", _execute)
    closed = audit.Launch(
        ["/bin/true"],
        [],
        audit.EnvelopeDeclaration(harness="claude", argv=("/bin/true",)),
        stdin="",
    )
    audit.run_baseline(world, closed)
    audit.run_enveloped(world, closed)
    assert calls == {"baseline": "", "enveloped": ""}


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
        ("kimi", "HAPAX_KIMI_BIN"),
    ],
)
def test_a_missing_binary_is_refused(tmp_path, monkeypatch, harness, env_var):
    audit, world = _world(tmp_path)
    monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(audit.Refused, match="binary not found"):
        audit.LAUNCHES[harness](world)
