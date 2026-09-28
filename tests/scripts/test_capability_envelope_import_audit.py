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
    ],
    ids=["opened", "token", "undeclared-marker", "leak-outranks-failure", "failed", "clean"],
)
def test_the_verdict(enveloped: dict, expected: tuple[str, int]):
    baseline = _obs(sentinels_opened=["mirror-home/AGENTS.md"])
    assert _audit().verdict(baseline, enveloped, ("undeclared-user-hook-ran",)) == expected


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
    monkeypatch.setitem(audit.LAUNCHES, "claude", lambda world: None)
    # The baseline control witnessed nothing; the enveloped run imported nothing.
    monkeypatch.setattr(audit, "run_baseline", lambda world, launch: _obs())
    monkeypatch.setattr(audit, "run_enveloped", lambda world, launch: _obs())
    out = tmp_path / "report.json"
    code = audit.main(["--harness", "claude", "--out", str(out), "--root", str(tmp_path / "w")])
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


def test_vibe_builder_refuses_without_a_binary(tmp_path, monkeypatch):
    audit, world = _world(tmp_path)
    monkeypatch.setattr(
        audit, "_load_script", lambda _name: _fake_wrapper("team", None, lambda *a: ["v"])
    )
    with pytest.raises(audit.Refused, match="vibe binary not found"):
        audit.vibe_launch(world)
