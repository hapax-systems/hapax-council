"""Tests for reform-identity-coherence-20260601.

Covers the four hollow identity-recovery paths the final audit (cluster 11) found:
per-spawn session id (no parent-id reuse), in-session role reassert, a cross-role
stale-claim sweeper, and retired dead identity fallbacks.

Self-contained per project convention — no shared conftest fixtures.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
DISPATCH = REPO_ROOT / "scripts" / "hapax-methodology-dispatch"
HEADLESS = REPO_ROOT / "scripts" / "hapax-claude-headless"
WHOAMI = REPO_ROOT / "scripts" / "hapax-whoami"
AGENT_ROLE = REPO_ROOT / "hooks" / "scripts" / "agent-role.sh"

_IDENTITY_ENV = (
    "CLAUDE_ROLE",
    "HAPAX_AGENT_NAME",
    "HAPAX_AGENT_ROLE",
    "HAPAX_WORKTREE_ROLE",
    "HAPAX_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
)


def _clean_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = os.environ.copy()
    for k in _IDENTITY_ENV:
        env.pop(k, None)
    env["HOME"] = str(tmp_path)
    env.update(extra)
    return env


def _load_dispatch() -> ModuleType:
    """Load scripts/hapax-methodology-dispatch despite its extensionless name."""
    loader = importlib.machinery.SourceFileLoader("hapax_methodology_dispatch_idc", str(DISPATCH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses in the module can resolve cls.__module__.
    sys.modules[loader.name] = mod
    loader.exec_module(mod)
    return mod


# --- AC1: per-spawn HAPAX_SESSION_ID, never inherited from the dispatcher -------


class TestSessionIdNotInherited:
    def test_headless_launch_does_not_propagate_parent_session_id(self) -> None:
        mod = _load_dispatch()
        captured: dict[str, object] = {}

        def fake_sliced(args: list[str], env: dict[str, str] | None = None) -> int:
            captured["env"] = env
            return 0

        route = SimpleNamespace(profile="full")
        with (
            patch.dict(os.environ, {"HAPAX_SESSION_ID": "parent-leaked-id"}),
            patch.object(mod, "_sliced_call", fake_sliced),
        ):
            rc = mod.launch_claude_headless("task-x", "zeta", "prompt", route)
        assert rc == 0
        env = captured["env"]
        assert isinstance(env, dict)
        # The child must mint its OWN id; the dispatcher's must not leak through.
        assert env.get("HAPAX_SESSION_ID", "") == ""

    def test_interactive_launch_does_not_propagate_parent_session_id(self) -> None:
        mod = _load_dispatch()
        captured: dict[str, object] = {}

        def fake_call(args: list[str], env: dict[str, str] | None = None) -> int:
            captured["env"] = env
            return 0

        # task=None → status "" → the no-claim branch, which historically inherited
        # the full parent environment (HAPAX_SESSION_ID included).
        validation = SimpleNamespace(task=None)
        with (
            patch.dict(os.environ, {"HAPAX_SESSION_ID": "parent-leaked-id"}),
            patch.object(mod.subprocess, "call", fake_call),
        ):
            rc = mod.launch_claude_interactive("task-y", "zeta", validation)
        assert rc == 0
        env = captured["env"]
        assert isinstance(env, dict), (
            "interactive launch must pass a scrubbed env, not inherit os.environ"
        )
        assert env.get("HAPAX_SESSION_ID", "") == ""

    def test_headless_script_mints_fresh_id_ignoring_inherited(self, tmp_path: Path) -> None:
        """The launcher itself mints a fresh id even when one is inherited, and writes
        a per-session identity marker (role) keyed by that fresh id."""
        env = os.environ.copy()
        for k in ("CLAUDE_ROLE", "HAPAX_AGENT_NAME", "HAPAX_AGENT_ROLE", "HAPAX_WORKTREE_ROLE"):
            env.pop(k, None)
        env["HOME"] = str(tmp_path)
        env["HAPAX_CLAUDE_HEADLESS_ALLOW"] = "1"
        env["HAPAX_SDLC_SLICE_ATTACH"] = "0"  # skip the systemd-run self-attach re-exec
        env["HAPAX_SESSION_ID"] = "inherited-parent-id"  # must be IGNORED
        # Worktree $HOME/projects/hapax-council--zeta does not exist under tmp HOME,
        # so the launcher exits 3 right after minting + writing the marker.
        subprocess.run(
            [str(HEADLESS), "zeta", "governed msg"],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        markers = sorted((tmp_path / ".cache" / "hapax").glob("session-role-*"))
        assert len(markers) == 1, f"expected exactly one session marker, got {markers}"
        sid = markers[0].name.removeprefix("session-role-")
        assert sid != "inherited-parent-id", "launcher inherited the parent session id"
        assert markers[0].read_text().strip() == "zeta"


# --- AC4: hapax-whoami resolves identity WM-independently (dead on niri before) -


class TestWhoamiMarker:
    def test_whoami_resolves_from_session_marker_without_compositor(self, tmp_path: Path) -> None:
        marker = tmp_path / ".cache" / "hapax" / "session-role-sidW"
        marker.parent.mkdir(parents=True)
        marker.write_text("gamma\n")
        env = _clean_env(tmp_path, HAPAX_SESSION_ID="sidW")
        r = subprocess.run([str(WHOAMI)], env=env, capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "gamma"

    def test_whoami_uses_claude_code_session_id_fallback(self, tmp_path: Path) -> None:
        marker = tmp_path / ".cache" / "hapax" / "session-role-ccsid"
        marker.parent.mkdir(parents=True)
        marker.write_text("delta\n")
        env = _clean_env(tmp_path, CLAUDE_CODE_SESSION_ID="ccsid")
        r = subprocess.run([str(WHOAMI)], env=env, capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "delta"


# --- AC2: in-session role reassert, no process restart -------------------------


class TestInSessionReassert:
    def test_assert_identity_writes_marker_and_resolves(self, tmp_path: Path) -> None:
        env = _clean_env(tmp_path, HAPAX_SESSION_ID="sidR")
        r = subprocess.run(
            ["bash", str(AGENT_ROLE), "assert-identity", "alpha"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert r.returncode == 0, r.stderr
        marker = tmp_path / ".cache" / "hapax" / "session-role-sidR"
        assert marker.read_text().strip() == "alpha"
        # The gate's resolver now reports the asserted role — no process restart.
        r2 = subprocess.run(
            ["bash", "-c", f'. "{AGENT_ROLE}"; hapax_effective_role'],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert r2.returncode == 0, r2.stderr
        assert r2.stdout.strip() == "alpha"

    def test_assert_identity_rejects_unknown_role(self, tmp_path: Path) -> None:
        env = _clean_env(tmp_path, HAPAX_SESSION_ID="sidR")
        r = subprocess.run(
            ["bash", str(AGENT_ROLE), "assert-identity", "not-a-real-lane"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert r.returncode != 0
        assert not (tmp_path / ".cache" / "hapax" / "session-role-sidR").exists()

    def test_assert_identity_requires_a_session_id(self, tmp_path: Path) -> None:
        env = _clean_env(tmp_path)  # no HAPAX_SESSION_ID / CLAUDE_CODE_SESSION_ID
        r = subprocess.run(
            ["bash", str(AGENT_ROLE), "assert-identity", "alpha"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert r.returncode != 0

    def test_sourcing_does_not_trigger_cli(self, tmp_path: Path) -> None:
        # Consumers source the helper as a library; the CLI must not run then.
        r = subprocess.run(
            ["bash", "-c", f'. "{AGENT_ROLE}"; echo sourced-ok'],
            env=_clean_env(tmp_path),
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "sourced-ok"


# --- AC3: cross-role stale-claim sweeper ---------------------------------------


class TestStaleClaimSweeper:
    @staticmethod
    def _dirs(tmp_path: Path) -> tuple[Path, Path]:
        claims = tmp_path / "claims"
        active = tmp_path / "active"
        claims.mkdir()
        active.mkdir()
        return claims, active

    @staticmethod
    def _age(path: Path, seconds: float) -> None:
        t = time.time() - seconds
        os.utime(path, (t, t))

    _UUID = "12345678-1234-1234-1234-123456789abc"

    def test_reaps_lease_expired_claim(self, tmp_path: Path) -> None:
        mod = _load_dispatch()
        claims, active = self._dirs(tmp_path)
        # The task is still in active/, but the claim file is 14 days stale: a
        # dead/abandoned lane (the real council-eqi-phase0-run test-probe case).
        (active / "council-eqi-phase0-run.md").write_text("---\nstatus: in_progress\n---\n")
        cf = claims / "cc-active-task-test-probe"
        cf.write_text("council-eqi-phase0-run\n")
        self._age(cf, 14 * 86400)
        reaped = mod.sweep_stale_claims(claims, active, now=time.time())
        assert not cf.exists()
        assert any(
            name == "cc-active-task-test-probe" and reason == "lease-expired"
            for name, _task, reason in reaped
        )

    def test_keeps_fresh_live_claim(self, tmp_path: Path) -> None:
        mod = _load_dispatch()
        claims, active = self._dirs(tmp_path)
        (active / "t.md").write_text("---\nstatus: in_progress\n---\n")
        cf = claims / f"cc-active-task-zeta-{self._UUID}"
        cf.write_text("t\n")
        reaped = mod.sweep_stale_claims(claims, active, now=time.time())
        assert cf.exists()
        assert reaped == []

    def test_reaps_claim_for_terminal_or_missing_task(self, tmp_path: Path) -> None:
        mod = _load_dispatch()
        claims, active = self._dirs(tmp_path)
        # No note in active/ → task closed/withdrawn/missing → the slot is dead.
        cf = claims / f"cc-active-task-eta-{self._UUID}"
        cf.write_text("vanished-task\n")
        self._age(cf, 3600)  # past the settle grace, but well within the lease TTL
        reaped = mod.sweep_stale_claims(claims, active, now=time.time())
        assert not cf.exists()
        assert any(reason == "terminal-or-missing" for _n, _t, reason in reaped)

    def test_live_session_protects_its_roles_stale_legacy_file(self, tmp_path: Path) -> None:
        # The gate refreshes only the session-keyed file, so a live role's LEGACY
        # file ages out — it must not be reaped while a fresh sibling proves life.
        mod = _load_dispatch()
        claims, active = self._dirs(tmp_path)
        (active / "t.md").write_text("---\nstatus: in_progress\n---\n")
        legacy = claims / "cc-active-task-delta"
        legacy.write_text("t\n")
        self._age(legacy, 14 * 86400)
        sk = claims / f"cc-active-task-delta-{self._UUID}"
        sk.write_text("t\n")  # fresh → role delta is demonstrably live
        reaped = mod.sweep_stale_claims(claims, active, now=time.time())
        assert legacy.exists(), "a live role's stale legacy claim must not be reaped"
        assert reaped == []

    def test_does_not_reap_recently_touched_missing_task(self, tmp_path: Path) -> None:
        # A just-written claim for a momentarily-absent note (mid cc-close race) is
        # left to settle, not reaped.
        mod = _load_dispatch()
        claims, active = self._dirs(tmp_path)
        cf = claims / f"cc-active-task-theta-{self._UUID}"
        cf.write_text("in-flight-task\n")  # fresh mtime, note absent
        reaped = mod.sweep_stale_claims(claims, active, now=time.time())
        assert cf.exists()
        assert reaped == []
