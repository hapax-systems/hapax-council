"""Tests for scripts/hapax-dev — the unified visible-session launcher.

hapax-dev is the operator's one front door for visible sessions across the
claude / codex / agy runtimes. It does not reimplement launch logic; it picks a
free, non-conflicting identity (distinct from the supervised headless fleet),
refuses collisions, guarantees a fresh HAPAX_SESSION_ID, and dispatches to the
existing per-platform spawner.

The script exposes ``HAPAX_DEV_*`` knobs so its resolver is hermetically
testable without launching anything:

- ``HAPAX_DEV_DRY_RUN=1`` / ``--dry-run`` prints the resolution plan and exits.
- ``HAPAX_DEV_FAKE_LIVE_TMUX`` (set, even empty) replaces the real tmux probe
  with an explicit live-session list — empty therefore means "nothing live".
- ``HAPAX_DEV_CLAIM_DIR`` points the claim/heartbeat probe at a temp dir.
- ``HAPAX_DEV_CLAUDE_POOL`` / ``_CODEX_POOL`` / ``_AGY_POOL`` override pools.

The companion ``scripts/hapax-claude`` dev-pool extension (a non-greek
interactive role that needs no cc-task binding) is covered at the bottom with
stub ``claude`` / ``tmux`` binaries on PATH.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HAPAX_DEV = REPO_ROOT / "scripts" / "hapax-dev"
HAPAX_CLAUDE = REPO_ROOT / "scripts" / "hapax-claude"


def run_dev(
    *args: str,
    claim_dir: Path,
    workdir: Path,
    live_tmux: str = "",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke hapax-dev hermetically (fake tmux probe active by default)."""
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(workdir),
        "HAPAX_DEV_CLAIM_DIR": str(claim_dir),
        "HAPAX_DEV_WORKDIR": str(workdir),
        "HAPAX_DEV_FAKE_LIVE_TMUX": live_tmux,
        "HAPAX_DEV_TMUX": "tmux",
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(HAPAX_DEV), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
        env=env,
    )


def _field(stdout: str, key: str) -> str:
    """Extract a ``key:  value`` field from --dry-run output."""
    for line in stdout.splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    return ""


# ── help / usage ────────────────────────────────────────────────────────────


class TestHelp:
    def test_no_args_prints_usage(self, tmp_path: Path) -> None:
        r = run_dev(claim_dir=tmp_path / "c", workdir=tmp_path)
        assert r.returncode == 0
        assert "one front door" in r.stdout
        assert "hapax-dev <platform>" in r.stdout

    def test_help_lists_pools(self, tmp_path: Path) -> None:
        r = run_dev("help", claim_dir=tmp_path / "c", workdir=tmp_path)
        assert r.returncode == 0
        assert "claude" in r.stdout and "codex" in r.stdout and "agy" in r.stdout


# ── claude auto-selection (distinct from the headless greek fleet) ──────────


class TestClaudeAutoSelect:
    def test_auto_selects_first_free_dev_slot(self, tmp_path: Path) -> None:
        r = run_dev("claude", "--dry-run", claim_dir=tmp_path / "c", workdir=tmp_path)
        assert r.returncode == 0, r.stderr
        assert _field(r.stdout, "identity") == "dev"
        assert (
            _field(r.stdout, "spawn") == f"hapax-claude --role dev --terminal tmux --cd {tmp_path}"
        )

    def test_skips_busy_dev_via_tmux(self, tmp_path: Path) -> None:
        r = run_dev(
            "claude",
            "--dry-run",
            claim_dir=tmp_path / "c",
            workdir=tmp_path,
            live_tmux="hapax-claude-dev",
        )
        assert r.returncode == 0, r.stderr
        assert _field(r.stdout, "identity") == "dev2"

    def test_never_picks_greek_in_auto(self, tmp_path: Path) -> None:
        # Even with every greek tmux session live, auto-select stays in the
        # dev pool — the supervised fleet namespace is off-limits to auto.
        greek = " ".join(
            f"hapax-claude-{g}"
            for g in ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
        )
        r = run_dev(
            "claude", "--dry-run", claim_dir=tmp_path / "c", workdir=tmp_path, live_tmux=greek
        )
        assert r.returncode == 0
        assert _field(r.stdout, "identity") == "dev"


# ── free-detection: claim files + heartbeat (headless lanes lack tmux) ──────


class TestFreeDetection:
    def test_claim_file_marks_busy(self, tmp_path: Path) -> None:
        claim = tmp_path / "c"
        claim.mkdir()
        (claim / "cc-active-task-dev").write_text("some-task-id\n")
        r = run_dev("claude", "--dry-run", claim_dir=claim, workdir=tmp_path)
        assert r.returncode == 0, r.stderr
        # dev is busy by claim (no tmux), so auto moves to dev2.
        assert _field(r.stdout, "identity") == "dev2"

    def test_session_keyed_claim_marks_busy(self, tmp_path: Path) -> None:
        claim = tmp_path / "c"
        claim.mkdir()
        (claim / "cc-active-task-dev-1234abcd-uuid").write_text("x")
        r = run_dev("claude", "--dry-run", claim_dir=claim, workdir=tmp_path)
        assert _field(r.stdout, "identity") == "dev2"

    def test_fresh_heartbeat_marks_busy(self, tmp_path: Path) -> None:
        claim = tmp_path / "c"
        hb = claim / "claude-headless" / "dev"
        hb.mkdir(parents=True)
        (hb / "output.jsonl").write_text("{}\n")  # mtime = now → fresh
        r = run_dev("claude", "--dry-run", claim_dir=claim, workdir=tmp_path)
        assert _field(r.stdout, "identity") == "dev2"

    def test_empty_claim_file_is_not_busy(self, tmp_path: Path) -> None:
        claim = tmp_path / "c"
        claim.mkdir()
        (claim / "cc-active-task-dev").write_text("")  # empty → not a live claim
        r = run_dev("claude", "--dry-run", claim_dir=claim, workdir=tmp_path)
        assert _field(r.stdout, "identity") == "dev"


# ── collisions are refused by construction ──────────────────────────────────


class TestCollisionGuard:
    def test_explicit_busy_name_refused_with_attach_hint(self, tmp_path: Path) -> None:
        r = run_dev(
            "claude",
            "dev",
            claim_dir=tmp_path / "c",
            workdir=tmp_path,
            live_tmux="hapax-claude-dev",
        )
        assert r.returncode == 3
        assert "already live" in r.stderr
        assert "tmux attach -t hapax-claude-dev" in r.stderr

    def test_explicit_busy_greek_refused_via_claim(self, tmp_path: Path) -> None:
        # AC: an operator session must not collide with a running reform lane.
        # The reform lanes are headless (claim + heartbeat, often no tmux).
        claim = tmp_path / "c"
        claim.mkdir()
        (claim / "cc-active-task-theta").write_text("reform-task\n")
        r = run_dev("claude", "theta", claim_dir=claim, workdir=tmp_path)
        assert r.returncode == 3
        assert "already live" in r.stderr

    def test_pool_exhausted_errors(self, tmp_path: Path) -> None:
        r = run_dev(
            "claude",
            "--dry-run",
            claim_dir=tmp_path / "c",
            workdir=tmp_path,
            live_tmux="hapax-claude-dev",
            extra_env={"HAPAX_DEV_CLAUDE_POOL": "dev"},
        )
        assert r.returncode == 1
        assert "no free claude slot" in r.stderr


# ── explicit names + validation ─────────────────────────────────────────────


class TestExplicitNames:
    def test_explicit_greek_role_honored_when_named(self, tmp_path: Path) -> None:
        r = run_dev("claude", "zeta", "--dry-run", claim_dir=tmp_path / "c", workdir=tmp_path)
        assert r.returncode == 0, r.stderr
        assert _field(r.stdout, "identity") == "zeta"
        assert "--role zeta" in _field(r.stdout, "spawn")

    def test_invalid_claude_name_rejected(self, tmp_path: Path) -> None:
        r = run_dev("claude", "bogusname", "--dry-run", claim_dir=tmp_path / "c", workdir=tmp_path)
        assert r.returncode == 2
        assert "invalid claude identity" in r.stderr

    def test_invalid_codex_name_rejected(self, tmp_path: Path) -> None:
        r = run_dev("codex", "notacolor", "--dry-run", claim_dir=tmp_path / "c", workdir=tmp_path)
        assert r.returncode == 2

    def test_unknown_platform_rejected(self, tmp_path: Path) -> None:
        r = run_dev("rust", "--dry-run", claim_dir=tmp_path / "c", workdir=tmp_path)
        assert r.returncode == 2


# ── codex + agy dispatch ────────────────────────────────────────────────────


class TestCodexAndAgy:
    def test_codex_auto_and_passthrough(self, tmp_path: Path) -> None:
        r = run_dev(
            "codex",
            "--dry-run",
            "--",
            "--task",
            "FOO",
            "bar",
            claim_dir=tmp_path / "c",
            workdir=tmp_path,
        )
        assert r.returncode == 0, r.stderr
        assert _field(r.stdout, "identity") == "cx-blue"
        spawn = _field(r.stdout, "spawn")
        assert spawn.startswith(f"hapax-codex --session cx-blue --terminal tmux --cd {tmp_path}")
        assert spawn.endswith("--task FOO bar")

    def test_codex_window_uses_foot(self, tmp_path: Path) -> None:
        r = run_dev("codex", "--window", "--dry-run", claim_dir=tmp_path / "c", workdir=tmp_path)
        assert _field(r.stdout, "visibility") == "window"
        assert "--terminal foot" in _field(r.stdout, "spawn")

    def test_agy_alias_and_default_slot(self, tmp_path: Path) -> None:
        r = run_dev("agy", "--dry-run", claim_dir=tmp_path / "c", workdir=tmp_path)
        assert r.returncode == 0, r.stderr
        assert _field(r.stdout, "identity") == "antigrav"
        assert _field(r.stdout, "spawn").startswith(
            "hapax-antigrav --session antigrav --terminal tmux"
        )

    def test_antigrav_keyword_equivalent_to_agy(self, tmp_path: Path) -> None:
        r = run_dev("antigrav", "--dry-run", claim_dir=tmp_path / "c", workdir=tmp_path)
        assert _field(r.stdout, "identity") == "antigrav"

    def test_agy_window_opens_own_window(self, tmp_path: Path) -> None:
        # agy spawner has no foot path → hapax-dev opens the window itself, so
        # the spawner is still asked for a plain tmux session.
        r = run_dev("agy", "--window", "--dry-run", claim_dir=tmp_path / "c", workdir=tmp_path)
        assert _field(r.stdout, "visibility") == "window"
        assert "--terminal tmux" in _field(r.stdout, "spawn")


# ── visibility flags ────────────────────────────────────────────────────────


class TestVisibility:
    def test_detach_prints_attach_command(self, tmp_path: Path) -> None:
        r = run_dev("claude", "--detach", "--dry-run", claim_dir=tmp_path / "c", workdir=tmp_path)
        assert _field(r.stdout, "visibility") == "detach"
        assert _field(r.stdout, "attach") == "tmux attach -t hapax-claude-dev"

    def test_default_is_attach(self, tmp_path: Path) -> None:
        r = run_dev("claude", "--dry-run", claim_dir=tmp_path / "c", workdir=tmp_path)
        assert _field(r.stdout, "visibility") == "attach"

    def test_window_and_detach_mutually_exclusive(self, tmp_path: Path) -> None:
        r = run_dev(
            "claude",
            "--window",
            "--detach",
            "--dry-run",
            claim_dir=tmp_path / "c",
            workdir=tmp_path,
        )
        assert r.returncode == 2

    def test_cd_nonexistent_rejected(self, tmp_path: Path) -> None:
        r = run_dev(
            "claude",
            "--cd",
            "/no/such/dir",
            "--dry-run",
            claim_dir=tmp_path / "c",
            workdir=tmp_path,
        )
        assert r.returncode == 2


# ── fresh identity guarantee ────────────────────────────────────────────────


class TestFreshSessionId:
    def test_session_id_is_uuid_shaped_and_unique(self, tmp_path: Path) -> None:
        ids = set()
        for _ in range(3):
            r = run_dev("claude", "--dry-run", claim_dir=tmp_path / "c", workdir=tmp_path)
            sid = _field(r.stdout, "session_id")
            assert len(sid) >= 16 and "-" in sid
            ids.add(sid)
        assert len(ids) == 3  # each launch mints a distinct id


# ── ls / attach ─────────────────────────────────────────────────────────────


class TestLsAndAttach:
    def test_ls_shows_pool_state(self, tmp_path: Path) -> None:
        r = run_dev(
            "ls",
            claim_dir=tmp_path / "c",
            workdir=tmp_path,
            live_tmux="hapax-claude-dev hapax-codex-cx-blue",
        )
        assert r.returncode == 0, r.stderr
        lines = r.stdout.splitlines()
        assert any(l.split()[:3] == ["claude", "dev", "live"] for l in lines)
        assert any(l.split()[:3] == ["claude", "dev2", "free"] for l in lines)
        assert any(l.split()[:3] == ["codex", "cx-blue", "live"] for l in lines)

    def test_attach_missing_session_errors(self, tmp_path: Path) -> None:
        r = run_dev("attach", "dev", claim_dir=tmp_path / "c", workdir=tmp_path, live_tmux="")
        assert r.returncode == 3
        assert "no live tmux session" in r.stderr

    def test_attach_dry_run_prints_command(self, tmp_path: Path) -> None:
        r = run_dev(
            "attach",
            "dev",
            claim_dir=tmp_path / "c",
            workdir=tmp_path,
            live_tmux="hapax-claude-dev",
            extra_env={"HAPAX_DEV_DRY_RUN": "1"},
        )
        assert r.returncode == 0
        assert "would attach: tmux attach -t hapax-claude-dev" in r.stdout

    def test_attach_unknown_name_cannot_infer_platform(self, tmp_path: Path) -> None:
        r = run_dev("attach", "weirdname", claim_dir=tmp_path / "c", workdir=tmp_path)
        assert r.returncode == 2


# ── hapax-claude dev-pool extension (stub claude + tmux on PATH) ────────────


def _make_stub_bin(dir_: Path, name: str, body: str) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / name
    p.write_text("#!/usr/bin/env bash\n" + body)
    p.chmod(0o755)


def run_claude(*args: str, home: Path, binstub: Path) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": f"{binstub}:/usr/bin:/bin",
        "HOME": str(home),
        "HAPAX_CLAUDE_WORKTREE_ROOT": str(home),
    }
    return subprocess.run(
        ["bash", str(HAPAX_CLAUDE), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
        env=env,
    )


class TestHapaxClaudeDevPool:
    def _stubs(self, tmp_path: Path) -> tuple[Path, Path, Path]:
        binstub = tmp_path / "bin"
        marker = tmp_path / "tmux-invoked"
        # tmux stub: has-session fails (no session); record new-session; else ok.
        _make_stub_bin(
            binstub,
            "tmux",
            f'case "$1" in\n'
            f"  has-session) exit 1 ;;\n"
            f'  new-session) echo "$@" >> {marker} ; exit 0 ;;\n'
            f"  *) exit 0 ;;\n"
            f"esac\n",
        )
        _make_stub_bin(binstub, "claude", 'echo claude-stub-ran "$@"\nexit 0\n')
        return binstub, marker, tmp_path

    def test_dev_role_accepted_without_task(self, tmp_path: Path) -> None:
        binstub, marker, home = self._stubs(tmp_path)
        wd = tmp_path / "work"
        wd.mkdir()
        r = run_claude(
            "--role", "dev", "--terminal", "tmux", "--cd", str(wd), home=home, binstub=binstub
        )
        # Must NOT hit invalid-role (2) or no-task refusal (13); must spawn tmux.
        assert r.returncode == 0, f"rc={r.returncode} stderr={r.stderr}"
        assert "invalid role" not in r.stderr
        assert "refusing mutating" not in r.stderr
        assert marker.exists() and "new-session" in marker.read_text()
        assert "hapax-claude-dev" in marker.read_text()

    def test_dev2_role_accepted(self, tmp_path: Path) -> None:
        binstub, marker, home = self._stubs(tmp_path)
        wd = tmp_path / "work"
        wd.mkdir()
        r = run_claude(
            "--role", "dev2", "--terminal", "tmux", "--cd", str(wd), home=home, binstub=binstub
        )
        assert r.returncode == 0, r.stderr
        assert "hapax-claude-dev2" in marker.read_text()

    def test_greek_role_still_requires_task(self, tmp_path: Path) -> None:
        # Regression: the headless governance is intact for greek lanes — a
        # mutating greek lane with no claim and no --task is still refused.
        binstub, _marker, home = self._stubs(tmp_path)
        wd = tmp_path / "work"
        wd.mkdir()
        r = run_claude(
            "--role", "gamma", "--terminal", "none", "--cd", str(wd), home=home, binstub=binstub
        )
        assert r.returncode == 13, f"rc={r.returncode} stderr={r.stderr}"
        assert "without governed task binding" in r.stderr

    def test_invalid_role_still_rejected(self, tmp_path: Path) -> None:
        binstub, _marker, home = self._stubs(tmp_path)
        wd = tmp_path / "work"
        wd.mkdir()
        r = run_claude(
            "--role", "devel", "--terminal", "none", "--cd", str(wd), home=home, binstub=binstub
        )
        # 'devel' is not dev/dev<N> nor greek → invalid.
        assert r.returncode == 2
        assert "invalid role" in r.stderr


# ── real (non-dry-run) spawn seam: dispatch to spawner + attach ─────────────


class TestRealSpawn:
    """Exercise the exec path: hapax-dev must actually invoke the spawner with
    the resolved identity + a fresh HAPAX_SESSION_ID, then attach."""

    def _stub_env(self, tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
        binstub = tmp_path / "bin"
        spawn_marker = tmp_path / "spawn.log"
        tmux_marker = tmp_path / "tmux.log"
        _make_stub_bin(
            binstub,
            "spawner",
            f'printf "%s\\n" "$*" > {spawn_marker}\n'
            f'printf "SID=%s\\n" "$HAPAX_SESSION_ID" >> {spawn_marker}\n'
            f"exit 0\n",
        )
        _make_stub_bin(binstub, "tmuxstub", f'printf "%s\\n" "$*" >> {tmux_marker}\nexit 0\n')
        env = {
            "HAPAX_DEV_CLAUDE_BIN": str(binstub / "spawner"),
            "HAPAX_DEV_TMUX": str(binstub / "tmuxstub"),
        }
        return env, spawn_marker, tmux_marker

    def test_detach_invokes_spawner_with_fresh_id(self, tmp_path: Path) -> None:
        env, spawn_marker, tmux_marker = self._stub_env(tmp_path)
        wd = tmp_path / "work"
        wd.mkdir()
        r = run_dev(
            "claude",
            "--detach",
            claim_dir=tmp_path / "c",
            workdir=wd,
            live_tmux="",
            extra_env=env,
        )
        assert r.returncode == 0, r.stderr
        logged = spawn_marker.read_text()
        assert f"--role dev --terminal tmux --cd {wd}" in logged
        sid = next(l[4:] for l in logged.splitlines() if l.startswith("SID="))
        assert len(sid) >= 16 and "-" in sid  # a real uuid was exported
        assert not tmux_marker.exists()  # --detach does not attach

    def test_default_attaches_after_spawn(self, tmp_path: Path) -> None:
        env, spawn_marker, tmux_marker = self._stub_env(tmp_path)
        wd = tmp_path / "work"
        wd.mkdir()
        r = run_dev(
            "claude",
            claim_dir=tmp_path / "c",
            workdir=wd,
            live_tmux="",
            extra_env=env,
        )
        assert r.returncode == 0, r.stderr
        assert "--role dev" in spawn_marker.read_text()
        assert "attach -t hapax-claude-dev" in tmux_marker.read_text()
