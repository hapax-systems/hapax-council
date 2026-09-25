"""The declared execution envelope: nothing reaches a job unless its declaration names it.

The unsafe cases come from the row harness-import-scrub-for-panels-reviews-benchmarks-20260925
and DESIGN v1.3 section 3.2a / canary C10:
- a canary in an ancestor AGENTS.md must not reach the job;
- an undeclared MCP server must not start;
- undeclared instruction files, hooks, memory and settings in the checkout or the operator's home
  are never opened;
- a declared governance hook does fire, so an empty envelope cannot pass by stripping everything.

Absence is observed at the filesystem boundary (inotify open events on the sentinel files), not
only in what the job reports. The control test shows the same probe and watch do see every
sentinel when no envelope is applied, so a pass is not vacuous.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from shared.capability_envelope import (
    MASKED_NAMES,
    DeclaredHook,
    DeclaredMcpServer,
    EnvelopeCarrierError,
    EnvelopeDeclaration,
    EnvelopeRefusal,
    execute,
    render,
)
from shared.capability_envelope.sentinel import OpenWatch, find_tokens, sentinel_token

PROBE = Path(__file__).resolve().parent / "probe_harness.py"
PYTHON = "/usr/bin/python3"


def _bwrap_usable() -> bool:
    if shutil.which("bwrap") is None or not Path(PYTHON).exists():
        return False
    probe = [
        "bwrap",
        "--ro-bind",
        "/usr",
        "/usr",
        "--symlink",
        "usr/bin",
        "/bin",
        "--symlink",
        "usr/lib",
        "/lib",
        "--symlink",
        "usr/lib",
        "/lib64",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--unshare-pid",
        "--",
        "/usr/bin/true",
    ]
    try:
        return subprocess.run(probe, capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


needs_bwrap = pytest.mark.skipif(
    not _bwrap_usable(), reason="bubblewrap with unprivileged user namespaces is unavailable"
)


def _write(path: Path, text: str, *, executable: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if executable:
        path.chmod(0o755)
    return path


class World:
    """A fake operator home, an ancestor directory and a checkout, each seeded with sentinels."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.tokens: dict[Path, str] = {}
        self.home = root / "operator-home"
        self.checkout = root / "ancestor" / "repo"
        self.spool = root / "spool"
        self.spool.mkdir()
        leak_marker = self.spool / "undeclared-mcp-started"

        def sentinel(path: Path, label: str) -> Path:
            token = sentinel_token(label)
            self.tokens[path] = token
            return _write(path, f"{token}\n")

        for rel in (
            "AGENTS.md",
            "CLAUDE.md",
            ".claude/CLAUDE.md",
            ".codex/AGENTS.md",
            ".gemini/GEMINI.md",
            ".grok/AGENTS.md",
            ".kimi-code/AGENTS.md",
            ".vibe/AGENTS.md",
            ".claude/projects/p/memory/MEMORY.md",
        ):
            sentinel(self.home / rel, "home-" + rel.replace("/", "-"))
        sentinel(root / "ancestor" / "AGENTS.md", "ancestor-agents")
        sentinel(root / "ancestor" / "CLAUDE.md", "ancestor-claude")
        for rel in ("CLAUDE.md", "AGENTS.md", "GEMINI.md", "sub/AGENTS.md"):
            sentinel(self.checkout / rel, "checkout-" + rel.replace("/", "-"))
        _write(self.checkout / "README.md", "an ordinary file the job may read\n")

        self.undeclared_hook = _write(
            root / "undeclared-hook.sh",
            f"#!/bin/sh\ntouch {self.spool}/undeclared-hook-ran\n",
            executable=True,
        )
        self.tokens[self.undeclared_hook] = "undeclared-hook"
        self.undeclared_server = _write(
            root / "undeclared-server.sh", f"#!/bin/sh\ntouch {leak_marker}\n", executable=True
        )
        self.tokens[self.undeclared_server] = "undeclared-server"
        checkout_server = _write(
            self.checkout / "leak-server.sh", f"#!/bin/sh\ntouch {leak_marker}\n", executable=True
        )
        self.tokens[checkout_server] = "checkout-server"
        hooks = {
            "PreToolUse": [{"hooks": [{"type": "command", "command": str(self.undeclared_hook)}]}]
        }
        for settings in (
            self.home / ".claude/settings.json",
            self.checkout / ".claude/settings.json",
        ):
            _write(settings, json.dumps({"hooks": hooks}))
            self.tokens[settings] = "settings"
        _write(
            self.home / ".claude.json",
            json.dumps({"mcpServers": {"leak": {"command": str(self.undeclared_server)}}}),
        )
        _write(
            self.checkout / ".mcp.json",
            json.dumps({"mcpServers": {"leak": {"command": "./leak-server.sh"}}}),
        )
        for path in (self.home / ".claude.json", self.checkout / ".mcp.json"):
            self.tokens[path] = "mcp-config"

        self.declared_hook = _write(
            root / "declared" / "gate-hook.sh",
            "#!/bin/sh\ntouch /spool/declared-hook-fired\n",
            executable=True,
        )
        self.declared_server = _write(
            root / "declared" / "declared-server.sh",
            "#!/bin/sh\ntouch /spool/declared-mcp-started\n",
            executable=True,
        )

    @property
    def sentinel_paths(self) -> list[Path]:
        return sorted(self.tokens)

    def probe_argv(self, report: str) -> tuple[str, ...]:
        return (
            PYTHON,
            str(PROBE),
            "--report",
            report,
            "--extra",
            *(str(p) for p in self.sentinel_paths),
        )

    def declaration(self, **overrides) -> EnvelopeDeclaration:
        fields = {
            "harness": "claude",
            "argv": self.probe_argv("/spool/report.json"),
            "binaries": (PROBE,),
            "workdir": self.checkout,
            "spool": self.spool,
        }
        fields.update(overrides)
        return EnvelopeDeclaration(**fields)

    def report(self) -> dict:
        return json.loads((self.spool / "report.json").read_text())


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def _run_enveloped(world: World, decl: EnvelopeDeclaration, run_root: Path) -> dict:
    rendered = render(decl, run_root=run_root)
    with OpenWatch(world.sentinel_paths) as watch:
        result = execute(rendered, timeout=60)
    assert result.returncode == 0, result.stderr
    report = world.report()
    report["_opened"] = watch.opened()
    return report


# ---------------------------------------------------------------- the control


@needs_bwrap
def test_control_without_envelope_every_sentinel_is_reached(world: World, tmp_path: Path):
    """The probe and the watch detect imports, so the enveloped tests cannot pass vacuously."""
    env = {"HOME": str(world.home), "PATH": "/usr/bin:/bin"}
    with OpenWatch(world.sentinel_paths) as watch:
        subprocess.run(
            world.probe_argv(str(world.spool / "report.json")),
            cwd=world.checkout,
            env=env,
            check=True,
            timeout=60,
        )
    report = world.report()
    text = json.dumps(report["read"])
    assert find_tokens(text, world.tokens.values()) >= {
        world.tokens[world.root / "ancestor" / "AGENTS.md"],
        world.tokens[world.home / ".claude/CLAUDE.md"],
        world.tokens[world.checkout / "CLAUDE.md"],
    }
    assert world.root / "ancestor" / "AGENTS.md" in watch.opened()
    assert (world.spool / "undeclared-mcp-started").exists()
    assert (world.spool / "undeclared-hook-ran").exists()


# ---------------------------------------------------------------- unsafe cases


@needs_bwrap
def test_no_undeclared_import_is_opened_or_reaches_the_job(world: World, tmp_path: Path):
    report = _run_enveloped(world, world.declaration(), tmp_path / "run")
    assert report["_opened"] == set(), f"sentinels opened: {sorted(map(str, report['_opened']))}"
    leaked = find_tokens(json.dumps(report["read"]), world.tokens.values())
    assert leaked == set(), f"sentinel tokens reached the job: {leaked}"
    assert report["read"].get("/work/README.md") == "an ordinary file the job may read\n"


@needs_bwrap
def test_ancestor_agents_md_canary_does_not_reach_the_job(world: World, tmp_path: Path):
    report = _run_enveloped(world, world.declaration(), tmp_path / "run")
    ancestor = world.tokens[world.root / "ancestor" / "AGENTS.md"]
    opened = report.pop("_opened")
    assert ancestor not in json.dumps(report)
    assert world.root / "ancestor" / "AGENTS.md" not in opened


@needs_bwrap
def test_undeclared_mcp_server_does_not_start(world: World, tmp_path: Path):
    report = _run_enveloped(world, world.declaration(), tmp_path / "run")
    assert report["mcp_spawned"] == []
    assert not (world.spool / "undeclared-mcp-started").exists()
    assert world.undeclared_server not in report["_opened"]


@needs_bwrap
def test_undeclared_hook_does_not_run(world: World, tmp_path: Path):
    report = _run_enveloped(world, world.declaration(), tmp_path / "run")
    assert report["hooks_run"] == []
    assert not (world.spool / "undeclared-hook-ran").exists()


@needs_bwrap
def test_host_environment_does_not_reach_the_job(world: World, tmp_path: Path, monkeypatch):
    token = sentinel_token("env")
    monkeypatch.setenv("HAPAX_ENVELOPE_ENV_SENTINEL", token)
    report = _run_enveloped(world, world.declaration(), tmp_path / "run")
    assert token not in json.dumps(report["env"])
    assert report["env"]["HOME"] != str(Path.home())


@needs_bwrap
def test_job_home_is_fresh_per_run_and_run_roots_are_create_once(world: World, tmp_path: Path):
    first = _run_enveloped(world, world.declaration(), tmp_path / "run-1")
    assert first["prior_marker"] is False
    second = _run_enveloped(world, world.declaration(), tmp_path / "run-2")
    assert second["prior_marker"] is False
    with pytest.raises(EnvelopeRefusal):
        render(world.declaration(), run_root=tmp_path / "run-1")


# ---------------------------------------------------------------- positive cases


@needs_bwrap
def test_declared_governance_hook_fires(world: World, tmp_path: Path):
    decl = world.declaration(
        hooks=(DeclaredHook(name="gate", event="PreToolUse", script=world.declared_hook),)
    )
    report = _run_enveloped(world, decl, tmp_path / "run")
    assert (world.spool / "declared-hook-fired").exists()
    assert len(report["hooks_run"]) == 1
    assert not (world.spool / "undeclared-hook-ran").exists()


@needs_bwrap
def test_declared_mcp_server_starts_and_only_it(world: World, tmp_path: Path):
    decl = world.declaration(
        mcp_servers=(
            DeclaredMcpServer(
                name="declared",
                command=(str(world.declared_server),),
                binds=(world.declared_server,),
            ),
        )
    )
    report = _run_enveloped(world, decl, tmp_path / "run")
    assert (world.spool / "declared-mcp-started").exists()
    assert not (world.spool / "undeclared-mcp-started").exists()
    assert len(report["mcp_spawned"]) == 1


@needs_bwrap
def test_declared_checkout_instruction_file_is_readable_and_the_rest_stay_masked(
    world: World, tmp_path: Path
):
    decl = world.declaration(declared_work_files=("AGENTS.md",))
    report = _run_enveloped(world, decl, tmp_path / "run")
    assert world.tokens[world.checkout / "AGENTS.md"] in report["read"]["/work/AGENTS.md"]
    assert world.checkout / "AGENTS.md" in report["_opened"]
    others = set(report["_opened"]) - {world.checkout / "AGENTS.md"}
    assert others == set()
    assert world.tokens[world.checkout / "CLAUDE.md"] not in json.dumps(report["read"])


# ---------------------------------------------------------------- carrier failures


def test_missing_bubblewrap_is_a_carrier_error_and_nothing_runs(
    world: World, tmp_path: Path, monkeypatch
):
    rendered = render(world.declaration(), run_root=tmp_path / "run")
    empty = tmp_path / "no-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    with pytest.raises(EnvelopeCarrierError, match="bubblewrap not found"):
        execute(rendered, timeout=30)
    assert not (world.spool / "report.json").exists()


@needs_bwrap
def test_a_bubblewrap_failure_is_a_carrier_error(tmp_path: Path):
    """The declared binary is not inside the job, so bubblewrap cannot exec it."""
    decl = EnvelopeDeclaration(harness="claude", argv=(str(tmp_path / "missing-binary"),))
    rendered = render(decl, run_root=tmp_path / "run")
    with pytest.raises(EnvelopeCarrierError, match="carrier failed"):
        execute(rendered, timeout=30)


# ---------------------------------------------------------------- render-time refusals


def test_bare_needs_declared_api_billing(tmp_path: Path):
    decl = EnvelopeDeclaration(harness="claude", argv=("claude", "-p", "--bare", "hi"))
    with pytest.raises(EnvelopeRefusal, match="billing"):
        render(decl, run_root=tmp_path / "run")
    render(decl.model_copy(update={"billing_surface": "api"}), run_root=tmp_path / "run-api")


@pytest.mark.parametrize("key", ["ANTHROPIC_API_KEY", "GH_TOKEN", "SOME_SECRET", "DB_PASSWORD"])
def test_secret_shaped_env_is_refused(tmp_path: Path, key: str):
    decl = EnvelopeDeclaration(harness="claude", argv=("claude",), env={key: "x"})
    with pytest.raises(EnvelopeRefusal, match="credential"):
        render(decl, run_root=tmp_path / "run")


def test_hooks_or_mcp_for_a_harness_without_a_renderer_are_refused(world: World, tmp_path: Path):
    hook = DeclaredHook(name="gate", event="PreToolUse", script=world.declared_hook)
    with pytest.raises(EnvelopeRefusal, match="codex"):
        render(
            EnvelopeDeclaration(harness="codex", argv=("codex",), hooks=(hook,)),
            run_root=tmp_path / "run",
        )


def test_rendered_argv_never_exposes_root_or_the_operator_home(world: World, tmp_path: Path):
    rendered = render(world.declaration(), run_root=tmp_path / "run")
    argv = list(rendered.argv)
    assert "--clearenv" in argv
    home = str(Path.home())
    for i, arg in enumerate(argv):
        if arg in ("--bind", "--ro-bind", "--bind-try", "--ro-bind-try"):
            src, dst = argv[i + 1], argv[i + 2]
            assert src != "/" and dst != "/", "the host root is never bound whole"
            assert src != home and dst != home, "the operator's home is never bound whole"
    masked = set(rendered.masked)
    assert {
        "CLAUDE.md",
        "AGENTS.md",
        "GEMINI.md",
        "sub/AGENTS.md",
        ".claude",
        ".mcp.json",
    } <= masked


def test_mask_list_covers_the_measured_harness_imports():
    """M153 (ENCOUNTERED-MACHINERY, 2026-09-25): what each CLI harness on appendix loads."""
    assert {
        "CLAUDE.md",
        "AGENTS.md",
        "GEMINI.md",
        ".claude",
        ".mcp.json",
        ".codex",
        ".gemini",
        ".grok",
        ".kimi-code",
        ".vibe",
    } <= set(MASKED_NAMES)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
