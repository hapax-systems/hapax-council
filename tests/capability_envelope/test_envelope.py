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

import ctypes
import errno
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.capability_envelope import (
    JOB_HOME,
    MASKED_NAMES,
    CredentialBind,
    DeclaredFile,
    DeclaredHook,
    DeclaredMcpServer,
    EnvelopeCarrierError,
    EnvelopeDeclaration,
    EnvelopeRefusal,
    execute,
    render,
)
from shared.capability_envelope import sentinel as sentinel_module
from shared.capability_envelope.sentinel import (
    _EVENT_HEADER,
    _IN_OPEN,
    OpenWatch,
    find_tokens,
    sentinel_token,
)

PROBE = Path(__file__).resolve().parent / "probe_harness.py"
PYTHON = "/usr/bin/python3"


#: Set by the CI job capability-envelope-containment: there, a sandbox that cannot be built is a
#: failure, never a skip, so a green check means the containment tests executed.
REQUIRE_BWRAP = os.environ.get("HAPAX_ENVELOPE_REQUIRE_BWRAP") == "1"


def _bwrap_usable() -> bool:
    """Whether the envelope's own carrier can run a trivial job on this host."""
    if not Path(PYTHON).exists():
        return False
    with tempfile.TemporaryDirectory() as tmp:
        try:
            decl = EnvelopeDeclaration(harness="claude", argv=("/usr/bin/true",))
            rendered = render(decl, run_root=Path(tmp) / "run")
            return execute(rendered, timeout=30).returncode == 0
        except (EnvelopeCarrierError, OSError, subprocess.TimeoutExpired):
            return False


BWRAP_USABLE = _bwrap_usable()

needs_bwrap = pytest.mark.skipif(
    not BWRAP_USABLE and not REQUIRE_BWRAP,
    reason="bubblewrap with unprivileged user namespaces is unavailable",
)


def test_bubblewrap_is_usable_where_the_containment_tests_are_required():
    if not REQUIRE_BWRAP:
        pytest.skip("HAPAX_ENVELOPE_REQUIRE_BWRAP is not set")
    assert BWRAP_USABLE, (
        "the containment job requires bubblewrap with unprivileged user namespaces; next action: "
        "install bubblewrap and lift the runner's AppArmor user-namespace restriction"
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


# ---------------------------------------------------------------- credentials and declared files


def _sh(script: str, **fields) -> EnvelopeDeclaration:
    return EnvelopeDeclaration(harness="claude", argv=("/usr/bin/sh", "-c", script), **fields)


@needs_bwrap
def test_a_read_only_credential_is_readable_and_never_writable(tmp_path: Path):
    token = sentinel_token("credential")
    cred = _write(tmp_path / "host" / "auth.json", f"{token}\n")
    decl = _sh(
        'cat "$HOME/.tool/auth.json"; '
        '(echo x >> "$HOME/.tool/auth.json") 2>/dev/null && echo WROTE || echo READONLY',
        credentials=(CredentialBind(source=cred, target=".tool/auth.json"),),
    )
    rendered = render(decl, run_root=tmp_path / "run")
    result = execute(rendered, timeout=60)
    assert result.returncode == 0, result.stderr
    assert token in result.stdout
    assert "READONLY" in result.stdout and "WROTE" not in result.stdout
    assert cred.read_text() == f"{token}\n"
    # The credential travels as a bind, never as a value in the carrier argv or the run facts.
    assert token not in "\0".join(rendered.argv)
    assert token not in json.dumps(rendered.facts)


@needs_bwrap
def test_a_writable_credential_directory_takes_a_refresh_by_rename(tmp_path: Path):
    creds = tmp_path / "host" / "creds"
    _write(creds / "token", "OLD\n")
    decl = _sh(
        'echo NEW > "$HOME/.tool/creds/token.tmp" && '
        'mv "$HOME/.tool/creds/token.tmp" "$HOME/.tool/creds/token" && echo RENAMED',
        credentials=(CredentialBind(source=creds, target=".tool/creds", writable=True),),
    )
    result = execute(render(decl, run_root=tmp_path / "run"), timeout=60)
    assert "RENAMED" in result.stdout, result.stderr
    assert (creds / "token").read_text() == "NEW\n"


@needs_bwrap
def test_a_declared_home_file_is_readable_and_read_only(tmp_path: Path):
    note = _write(tmp_path / "host" / "note.md", "declared content\n")
    decl = _sh(
        'cat "$HOME/notes/note.md"; '
        '(echo x >> "$HOME/notes/note.md") 2>/dev/null && echo WROTE || echo READONLY',
        home_files=(DeclaredFile(source=note, target="notes/note.md"),),
    )
    result = execute(render(decl, run_root=tmp_path / "run"), timeout=60)
    assert "declared content" in result.stdout, result.stderr
    assert "READONLY" in result.stdout
    assert note.read_text() == "declared content\n"


@needs_bwrap
def test_a_declared_home_directory_is_readable_and_read_only(tmp_path: Path):
    """A harness that runs helpers from its own directory under $HOME (agy) needs that directory
    declared into the job home, read-only."""
    tools = tmp_path / "host" / "tools"
    _write(tools / "helper.txt", "helper content\n")
    decl = _sh(
        'cat "$HOME/.tool/bin/helper.txt"; '
        '(echo x > "$HOME/.tool/bin/new.txt") 2>/dev/null && echo WROTE || echo READONLY',
        home_files=(DeclaredFile(source=tools, target=".tool/bin"),),
    )
    result = execute(render(decl, run_root=tmp_path / "run"), timeout=60)
    assert "helper content" in result.stdout, result.stderr
    assert "READONLY" in result.stdout
    assert not (tools / "new.txt").exists()


# ---------------------------------------------------------------- symlinks in the checkout


def _checkout_with_links(tmp_path: Path) -> Path:
    checkout = tmp_path / "outer" / "repo"
    _write(checkout / "AGENTS.md", "agents body\n")
    (checkout / "CLAUDE.md").symlink_to("AGENTS.md")
    _write(checkout / "docs" / "instructions.txt", "instructions body\n")
    (checkout / "GEMINI.md").symlink_to("docs/instructions.txt")
    return checkout


def test_masking_follows_symlinks_to_what_they_expose(tmp_path: Path):
    checkout = _checkout_with_links(tmp_path)
    rendered = render(_sh("true", workdir=checkout), run_root=tmp_path / "run")
    masked = set(rendered.masked)
    # CLAUDE.md -> AGENTS.md: the target is masked on its own, which is what the link resolves to.
    # The link path is not mounted over — bwrap refuses a symlink destination (see the `.git`
    # specimen below) — so the target is the covering mount.
    assert "AGENTS.md" in masked and "CLAUDE.md" not in masked
    # GEMINI.md -> docs/instructions.txt: the ordinary-named target is what gets covered.
    assert "docs/instructions.txt" in masked


def test_a_chained_masked_name_symlink_masks_its_final_target(tmp_path: Path):
    """glm-1's minor (2026-09-28): the round-3 leak was an assumption inside `_masks`, so a chain
    is pinned by test rather than left to `Path.resolve()`'s semantics alone."""
    checkout = tmp_path / "repo"
    _write(checkout / ".git" / "CLAUDE.md", "leaked instructions\n")
    (checkout / "middle.md").symlink_to(".git/CLAUDE.md")
    (checkout / "AGENTS.md").symlink_to("middle.md")
    rendered = render(_sh("true", workdir=checkout), run_root=tmp_path / "run")
    masked = set(rendered.masked)
    # The FINAL target is what is masked, not the intermediate link whose name is not masked.
    assert ".git/CLAUDE.md" in masked
    assert "middle.md" not in masked


@needs_bwrap
def test_a_chained_masked_name_symlink_reads_empty_in_the_job(tmp_path: Path):
    checkout = tmp_path / "repo"
    _write(checkout / ".git" / "CLAUDE.md", "leaked instructions\n")
    (checkout / "middle.md").symlink_to(".git/CLAUDE.md")
    (checkout / "AGENTS.md").symlink_to("middle.md")
    result = execute(
        render(
            _sh("cat /work/AGENTS.md; echo CHAIN=$?", workdir=checkout), run_root=tmp_path / "run"
        ),
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "leaked instructions" not in result.stdout, result.stdout
    assert "CHAIN=0" in result.stdout


def test_a_masked_name_inside_dot_git_is_masked(tmp_path: Path):
    """Codex-1's major on #4784 (2026-09-28): `_masks` pruned `.git` before looking for masked
    names beneath it, so a checkout containing `.git/AGENTS.md` exposed that file through
    `/work/.git/AGENTS.md`, although the module's masking guarantee is stated over the workdir.
    Masked-named FILES inside `.git` are bound empty; nothing else in `.git` is covered, so git
    keeps working."""
    checkout = tmp_path / "repo"
    _write(checkout / ".git" / "AGENTS.md", "leaked instructions\n")
    _write(checkout / ".git" / "HEAD", "ref: refs/heads/main\n")
    _write(checkout / ".git" / "config", "[core]\n\trepositoryformatversion = 0\n")
    rendered = render(_sh("true", workdir=checkout), run_root=tmp_path / "run")
    masked = set(rendered.masked)
    assert ".git/AGENTS.md" in masked
    assert ".git/HEAD" not in masked and ".git/config" not in masked


@needs_bwrap
def test_a_masked_name_inside_dot_git_reads_empty_and_the_rest_of_git_survives(tmp_path: Path):
    checkout = tmp_path / "repo"
    _write(checkout / ".git" / "AGENTS.md", "leaked instructions\n")
    _write(checkout / ".git" / "HEAD", "ref: refs/heads/main\n")
    script = "cat /work/.git/AGENTS.md; echo GITFILE=$?; cat /work/.git/HEAD"
    result = execute(
        render(_sh(script, workdir=checkout), run_root=tmp_path / "run"),
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "leaked instructions" not in result.stdout, result.stdout
    assert "GITFILE=0" in result.stdout
    assert "ref: refs/heads/main" in result.stdout, "git's own metadata is not covered"


def test_a_masked_name_symlinked_into_a_pruned_directory_is_masked(tmp_path: Path):
    """Review of #4784 (gemini-1, confirmed by dev21 under bwrap 0.12.0, 2026-09-28): a
    masked-named symlink whose target also has a masked name was covered NOWHERE. The walk prunes
    `.git` and masked-name directories, so the resolved target was never reached on its own, and
    the early `continue` skipped appending it — `CLAUDE.md -> .git/CLAUDE.md` read in full."""
    checkout = tmp_path / "repo"
    _write(checkout / ".git" / "CLAUDE.md", "leaked instructions\n")
    (checkout / "CLAUDE.md").symlink_to(".git/CLAUDE.md")
    rendered = render(_sh("true", workdir=checkout), run_root=tmp_path / "run")
    masked = set(rendered.masked)
    assert ".git/CLAUDE.md" in masked
    assert rendered.masked.count(".git/CLAUDE.md") == 1


@needs_bwrap
def test_a_masked_name_symlinked_into_dot_git_reads_empty_in_the_job(tmp_path: Path):
    """The specimen the finding was reported with: the job must not read the file behind the
    link, whichever of the two paths it opens."""
    checkout = tmp_path / "repo"
    _write(checkout / ".git" / "CLAUDE.md", "leaked instructions\n")
    (checkout / "CLAUDE.md").symlink_to(".git/CLAUDE.md")
    script = "cat /work/CLAUDE.md; echo LINK=$?; cat /work/.git/CLAUDE.md; echo TARGET=$?"
    result = execute(render(_sh(script, workdir=checkout), run_root=tmp_path / "run"), timeout=60)
    assert result.returncode == 0, result.stderr
    assert "leaked instructions" not in result.stdout, result.stdout
    assert "LINK=0" in result.stdout and "TARGET=0" in result.stdout


@pytest.mark.parametrize(
    "target",
    ["../outside.md", "/etc/hosts", f"{JOB_HOME}/.claude/.credentials.json"],
    ids=["relative-outside", "absolute-bound-system-file", "absolute-job-credential"],
)
def test_an_instruction_symlink_leaving_the_checkout_is_refused(tmp_path: Path, target: str):
    """Review of #4784 (claude-1): inside the job such a link resolves to whatever the job can
    see at that path, for example a bound credential, and a harness imports it as instructions."""
    checkout = tmp_path / "outer" / "repo"
    checkout.mkdir(parents=True)
    _write(tmp_path / "outer" / "outside.md", "outside body\n")
    (checkout / "AGENTS.md").symlink_to(target)
    with pytest.raises(EnvelopeRefusal, match="points outside the checkout"):
        render(_sh("true", workdir=checkout), run_root=tmp_path / "run")


def test_an_instruction_directory_symlink_leaving_the_checkout_is_refused(tmp_path: Path):
    checkout = tmp_path / "repo"
    checkout.mkdir()
    (checkout / ".claude").symlink_to(f"{JOB_HOME}/.claude")
    with pytest.raises(EnvelopeRefusal, match="points outside the checkout"):
        render(_sh("true", workdir=checkout), run_root=tmp_path / "run")


@needs_bwrap
def test_no_symlinked_instruction_file_leaks_into_the_job(tmp_path: Path):
    checkout = _checkout_with_links(tmp_path)
    script = "for f in AGENTS.md CLAUDE.md GEMINI.md; do cat /work/$f; done 2>/dev/null"
    result = execute(render(_sh(script, workdir=checkout), run_root=tmp_path / "run"), timeout=60)
    for body in ("agents body", "instructions body"):
        assert body not in result.stdout


# ---------------------------------------------------------------- workdir mode, env, hook matcher


@needs_bwrap
@pytest.mark.parametrize("writable", [False, True])
def test_the_workdir_is_writable_only_when_declared(tmp_path: Path, writable: bool):
    checkout = tmp_path / "repo"
    checkout.mkdir()
    decl = _sh(
        "(echo x > /work/out.txt) 2>/dev/null && echo WROTE || echo READONLY",
        workdir=checkout,
        workdir_writable=writable,
    )
    result = execute(render(decl, run_root=tmp_path / "run"), timeout=60)
    assert ("WROTE" if writable else "READONLY") in result.stdout, result.stderr
    assert (checkout / "out.txt").exists() is writable


@needs_bwrap
def test_declared_env_reaches_the_job_and_nothing_else_does(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HAPAX_UNDECLARED_VAR", "host-value")
    decl = _sh("env", env={"HAPAX_DECLARED_VAR": "declared-value"})
    result = execute(render(decl, run_root=tmp_path / "run"), timeout=60)
    assert "HAPAX_DECLARED_VAR=declared-value" in result.stdout
    assert "HAPAX_UNDECLARED_VAR" not in result.stdout


def test_a_declared_hook_matcher_is_rendered_into_the_claude_settings(world: World, tmp_path: Path):
    hooks = (
        DeclaredHook(name="gate", event="PreToolUse", script=world.declared_hook, matcher="Bash"),
        DeclaredHook(name="start", event="SessionStart", script=world.declared_hook),
    )
    rendered = render(world.declaration(hooks=hooks), run_root=tmp_path / "run")
    settings = json.loads((rendered.run_root / "home" / ".claude" / "settings.json").read_text())
    assert settings["hooks"]["PreToolUse"] == [
        {"hooks": [{"type": "command", "command": "/envelope/hooks/gate"}], "matcher": "Bash"}
    ]
    assert "matcher" not in settings["hooks"]["SessionStart"][0]


@needs_bwrap
def test_a_declared_file_stays_readable_through_its_symlink(tmp_path: Path):
    checkout = _checkout_with_links(tmp_path)
    decl = _sh("cat /work/CLAUDE.md", workdir=checkout, declared_work_files=("AGENTS.md",))
    result = execute(render(decl, run_root=tmp_path / "run"), timeout=60)
    assert "agents body" in result.stdout, result.stderr


# ---------------------------------------------------------------- declaration validation


@pytest.mark.parametrize(
    "build",
    [
        lambda p: DeclaredHook(name="Bad Name", event="PreToolUse", script=p),
        lambda p: DeclaredMcpServer(name="-x", command=("x",)),
        lambda p: CredentialBind(source=p, target="/etc/passwd"),
        lambda p: DeclaredFile(source=p, target="../escape.md"),
        lambda p: EnvelopeDeclaration(harness="claude", argv=("x",), declared_work_files=("",)),
    ],
    ids=["hook-name", "mcp-name", "absolute-target", "dotdot-target", "empty-work-file"],
)
def test_invalid_declarations_are_refused_with_a_next_action(tmp_path: Path, build):
    with pytest.raises(ValidationError, match="next action"):
        build(tmp_path / "x")


# ---------------------------------------------------------------- the sentinel audit itself


def test_sentinel_tokens_are_unique_and_found_only_where_present():
    first, second = sentinel_token("a"), sentinel_token("a")
    assert first != second and first.startswith("HAPAX-SENTINEL-a-")
    assert find_tokens(f"x {first} y", [first, second]) == {first}


def test_the_open_watch_sees_an_open_and_refuses_a_missing_sentinel(tmp_path: Path):
    seen = _write(tmp_path / "seen.md", "x\n")
    unseen = _write(tmp_path / "unseen.md", "y\n")
    with OpenWatch([seen, unseen]) as watch:
        seen.read_text()
    assert watch.opened() == {seen}
    with pytest.raises(OSError, match="next action"), OpenWatch([tmp_path / "missing.md"]):
        pass


def test_the_open_watch_refuses_when_the_inotify_instance_cannot_be_created(
    tmp_path: Path, monkeypatch
):
    """Review of #4784 (codex-1, glm-1, 2026-09-28): the `inotify_init1` failure branch and its
    next action had no direct test; the missing-sentinel test above exercises only
    `inotify_add_watch`. An observation that cannot be established must refuse, never report an
    empty set that reads as "nothing was opened"."""

    class _Libc:
        @staticmethod
        def inotify_init1(_flags: int) -> int:
            return -1

    monkeypatch.setattr(ctypes, "CDLL", lambda *args, **kwargs: _Libc())
    monkeypatch.setattr(ctypes, "get_errno", lambda: errno.ENFILE)
    sentinel_file = _write(tmp_path / "sentinel.md", "x\n")
    with pytest.raises(OSError, match="inotify_init1 failed.*next action"):
        with OpenWatch([sentinel_file]):
            pass


def test_the_open_watch_sees_a_grandchild_that_outlives_its_parent(tmp_path: Path):
    """Clause (6) (glm-1's minor on #4784, re-ruled on 2026-09-28): the drain used to run once at
    `__exit__`, so an event queued after the process the caller waited for had returned was lost.
    A grandchild that closes the pipes and opens a sentinel afterwards is still recorded: the
    drain settles after the last event instead of reading once."""
    seen = _write(tmp_path / "seen.md", "x\n")
    inner = f"import time; time.sleep(0.05); open({str(seen)!r}).read()"
    child = (
        "import subprocess, sys\n"
        "subprocess.Popen("
        f"[sys.executable, '-c', {inner!r}], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
    )
    with OpenWatch([seen]) as watch:
        subprocess.run([sys.executable, "-c", child], check=True, timeout=60)
    assert watch.opened() == {seen}


def test_the_drain_keeps_a_partial_event_for_the_next_read(tmp_path: Path, monkeypatch):
    """An inotify event can straddle two reads; a drain that restarts parsing at each read
    misparses the tail. The leftover bytes are carried into the next read, so the second event is
    recorded instead of lost."""
    first = _write(tmp_path / "first.md", "x\n")
    second = _write(tmp_path / "second.md", "y\n")
    with OpenWatch([first, second]) as watch:
        by_path = {path: wd for wd, path in watch._watches.items()}
        blob = _EVENT_HEADER.pack(by_path[first], 0, 0, 0) + _EVENT_HEADER.pack(
            by_path[second], 0, 0, 0
        )
        # The second event's header is split: this read ends one byte into it.
        reads = iter([blob[: _EVENT_HEADER.size + 1], blob[_EVENT_HEADER.size + 1 :]])

        def _read(fd: int, size: int) -> bytes:
            try:
                return next(reads)
            except StopIteration:
                raise BlockingIOError from None

        monkeypatch.setattr(os, "read", _read)
        watch._drain()
    assert watch.opened() == {first, second}


def test_the_watch_reports_an_overflowed_queue(tmp_path: Path, monkeypatch):
    """Clause (7) of the row (codex-1, 2026-09-28): the drain unpacked the mask and never read it,
    so an `IN_Q_OVERFLOW` event (mask 0x4000, wd -1) passed unnoticed and the lost opens made an
    audit read clean. The watch reports the overflow so the verdict can be inconclusive."""
    seen = _write(tmp_path / "seen.md", "x\n")
    with OpenWatch([seen]) as watch:
        overflow = _EVENT_HEADER.pack(-1, 0x4000, 0, 0)
        reads = iter([overflow])

        def _read(fd: int, size: int) -> bytes:
            try:
                return next(reads)
            except StopIteration:
                raise BlockingIOError from None

        monkeypatch.setattr(os, "read", _read)
        watch._drain()
    assert watch.overflowed() is True


def test_the_watch_reports_a_truncated_drain(tmp_path: Path, monkeypatch):
    """Clause (7) follow-up (codex-1's major on #4793, 2026-09-28): the settle bound used to exit
    with no flag, so a queue still being written at the bound read as a complete observation. The
    bound now sets `_truncated`, and the caller treats it like an overflow."""
    seen = _write(tmp_path / "seen.md", "x\n")
    monkeypatch.setattr(sentinel_module, "_SETTLE_BOUND_SECONDS", 0.05)
    monkeypatch.setattr(sentinel_module, "_SETTLE_SECONDS", 10.0)

    class _EndlessRead:
        """A queue that keeps producing an event for a watched path, forever."""

        def __init__(self, wd: int) -> None:
            self._event = _EVENT_HEADER.pack(wd, _IN_OPEN, 0, 0)

        def __call__(self, fd: int, size: int) -> bytes:
            return self._event

    with OpenWatch([seen]) as watch:
        wd = next(iter(watch._watches))
        monkeypatch.setattr(os, "read", _EndlessRead(wd))
        watch._drain(settle=True)
    assert watch.truncated() is True


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
    with pytest.raises(EnvelopeRefusal, match="no hook renderer for harness codex"):
        render(
            EnvelopeDeclaration(harness="codex", argv=("codex",), hooks=(hook,)),
            run_root=tmp_path / "run",
        )
    server = DeclaredMcpServer(name="declared", command=(str(world.declared_server),))
    with pytest.raises(EnvelopeRefusal, match="no MCP renderer for harness codex"):
        render(
            EnvelopeDeclaration(harness="codex", argv=("codex",), mcp_servers=(server,)),
            run_root=tmp_path / "run-mcp",
        )


def _in_operator_home(value: str) -> bool:
    home = str(Path.home())
    return value == home or value.startswith(home + "/")


def test_rendered_argv_never_exposes_root_or_the_operator_home(world: World, tmp_path: Path):
    """glm-1's minor (2026-09-28): the scan covered bind PAIRS only, so `--symlink` destinations,
    `--tmpfs` destinations and `--setenv` values were outside it. Those are the carrier's own
    generated entries, and each is now scanned like a bind destination.

    The declaration's own paths are deliberately not asserted home-free: a declared job may
    legitimately run a binary that lives under the operator's checkout, and the carrier's job here
    is to cover the entries IT generates.
    """
    rendered = render(world.declaration(), run_root=tmp_path / "run")
    argv = list(rendered.argv)
    assert "--clearenv" in argv
    home = str(Path.home())
    for i, arg in enumerate(argv):
        if arg in ("--bind", "--ro-bind", "--bind-try", "--ro-bind-try"):
            src, dst = argv[i + 1], argv[i + 2]
            assert src != "/" and dst != "/", "the host root is never bound whole"
            assert src != home and dst != home, "the operator's home is never bound whole"
        elif arg == "--symlink":
            assert not _in_operator_home(argv[i + 2]), argv[i + 2]
        elif arg == "--tmpfs":
            assert not _in_operator_home(argv[i + 1]), argv[i + 1]
        elif arg == "--setenv":
            assert not _in_operator_home(argv[i + 2]), argv[i + 2]
    # The three forms above are present, so the scan is not vacuous over them: `--tmpfs` covers
    # every masked directory and the private /tmp, and `--setenv` covers the fixed base and the
    # declaration's env. `--symlink` appears only where the host's root links are symlinks.
    assert "--tmpfs" in argv and "--setenv" in argv
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
