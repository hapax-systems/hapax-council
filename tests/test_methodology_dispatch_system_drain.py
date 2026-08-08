"""Tests for the capability-gated SYSTEM drain of an orphaned cc-task whose owning
lane process is verifiably dead (``dn-validate-task-relax``; CASE-SDLC-REFORM-001).

The drain admits a ``pr_open`` (or ``claimed``/``in_progress``) task for advancement
through the reserved ``__system__`` lane sentinel IFF:

1. the task's ``assigned_to`` lane process is verifiably ABSENT (no pid file, or a
   dead/stale pid — ``os.kill(pid, 0)`` raises ``ProcessLookupError``), and
2. a single-use ``DispatchCapability`` bound to ``(task_id, "__system__")``
   verifies against the live signing key and consumes against the replay ledger.

A LIVE lane (its pid answers ``os.kill(pid, 0)``) is NEVER drainable — that is the
load-bearing critical-failure guard. Normal-lane dispatch is byte-for-byte
unchanged: the ``__system__`` branch short-circuits before the legacy status gate.

These tests inject every external path via env (``HAPAX_LANE_PID_DIR``,
``HAPAX_COORD_GRANT_KEY``, ``HAPAX_COORD_CONSUMPTION_LEDGER``,
``HAPAX_SYSTEM_DRAIN_AUDIT``, ``HAPAX_CC_CLAIMS_DIR``) so no live lane pid file or
real ledger is ever touched.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import ModuleType

from shared.governance.coord_capabilities import mint_dispatch_capability, serialize_capability

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "hapax-methodology-dispatch"

KEY = b"test-operator-key-0123456789abcdef0123"


def _load() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("hapax_methodology_dispatch_drain", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load()


# --- fixtures / helpers -------------------------------------------------------


def _dead_pid() -> int:
    """A pid that has exited and been reaped — ``os.kill(pid, 0)`` raises."""
    proc = subprocess.Popen(["/bin/true"])
    proc.wait()
    return proc.pid


def _pid_dir(tmp_path: Path) -> Path:
    d = tmp_path / "run" / "hapax-claude"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _key_file(tmp_path: Path) -> Path:
    kf = tmp_path / "grant-key"
    kf.write_bytes(KEY)
    return kf


def _mint_cap(
    tmp_path: Path, task_id: str, lane: str, *, ttl: float = 600.0, now: float | None = None
) -> Path:
    cap = mint_dispatch_capability(
        task_id=task_id, lane=lane, ttl_s=ttl, key=KEY, now=time.time() if now is None else now
    )
    path = tmp_path / f"cap-{cap.capability_id}.json"
    path.write_text(serialize_capability(cap), encoding="utf-8")
    return path


def _drain_env(tmp_path: Path, pid_dir: Path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_LANE_PID_DIR", str(pid_dir))
    monkeypatch.setenv("HAPAX_COORD_GRANT_KEY", str(_key_file(tmp_path)))
    monkeypatch.setenv("HAPAX_COORD_CONSUMPTION_LEDGER", str(tmp_path / "consumption.jsonl"))
    monkeypatch.setenv("HAPAX_SYSTEM_DRAIN_AUDIT", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("HAPAX_CC_CLAIMS_DIR", str(tmp_path / "claims"))


def _write_task(
    task_root: Path,
    task_id: str,
    *,
    status: str,
    assigned_to: str,
    stage: str = "S6_IMPLEMENTATION",
    authority_case: str = "CASE-SDLC-REFORM-001",
    kind: str = "hardening",
) -> Path:
    path = task_root / "active" / f"{task_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        textwrap.dedent(
            f"""\
            ---
            type: cc-task
            task_id: {task_id}
            title: "{task_id}"
            status: {status}
            assigned_to: {assigned_to}
            authority_case: {authority_case}
            parent_spec: null
            kind: {kind}
            stage: {stage}
            updated_at: 2026-06-02T00:00:00Z
            ---

            # {task_id}
            """
        ),
        encoding="utf-8",
    )
    return path


# --- lane_process_absent: the load-bearing liveness predicate (AC) ------------


class TestLaneProcessAbsent:
    def test_absent_pid_file_is_absent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HAPAX_LANE_PID_DIR", str(_pid_dir(tmp_path)))
        absent, why = mod.lane_process_absent("delta")
        assert absent is True
        assert "absent" in why

    def test_malformed_pid_file_is_absent(self, tmp_path, monkeypatch):
        pid_dir = _pid_dir(tmp_path)
        (pid_dir / "delta.pid").write_text("not-a-pid", encoding="utf-8")
        monkeypatch.setenv("HAPAX_LANE_PID_DIR", str(pid_dir))
        absent, why = mod.lane_process_absent("delta")
        assert absent is True
        assert "malformed" in why

    def test_dead_pid_is_absent(self, tmp_path, monkeypatch):
        pid_dir = _pid_dir(tmp_path)
        (pid_dir / "delta.pid").write_text(str(_dead_pid()), encoding="utf-8")
        monkeypatch.setenv("HAPAX_LANE_PID_DIR", str(pid_dir))
        absent, why = mod.lane_process_absent("delta")
        assert absent is True
        assert "crashed" in why

    def test_live_pid_is_present(self, tmp_path, monkeypatch):
        pid_dir = _pid_dir(tmp_path)
        (pid_dir / "delta.pid").write_text(str(os.getpid()), encoding="utf-8")
        monkeypatch.setenv("HAPAX_LANE_PID_DIR", str(pid_dir))
        absent, why = mod.lane_process_absent("delta")
        assert absent is False
        assert "ALIVE" in why

    def test_signal_zero_only_no_process_group_kill(self):
        """The diff must use a liveness probe only — never a terminating signal."""
        source = SCRIPT.read_text(encoding="utf-8")
        assert "killpg" not in source
        assert "os.kill(pid, 0)" in source
        assert "SIGKILL" not in source
        assert "SIGTERM" not in source


# --- lane-name normalization (reviewer must-fix #6) ---------------------------


class TestNormalizeLaneName:
    def test_bare_lane_unchanged(self):
        assert mod.normalize_lane_name("delta") == "delta"

    def test_platform_qualified_stripped(self):
        assert mod.normalize_lane_name("claude/delta") == "delta"

    def test_quoted_and_spaced_stripped(self):
        assert mod.normalize_lane_name('  "delta" ') == "delta"

    def test_codex_qualified_keeps_bare_role(self):
        assert mod.normalize_lane_name("codex/cx-red") == "cx-red"


# --- _validate_system_drain admit / refuse matrix -----------------------------


def _validate(mod_, task_root, task_id, cap_path):
    return mod_.validate_task(
        task_id=task_id,
        lane=mod_.SYSTEM_DRAIN_LANE,
        platform="claude",
        task_root=task_root,
        strict_worktree=False,
        dispatch_capability_path=cap_path,
    )


class TestSystemDrainValidation:
    def test_pr_open_dead_lane_admitted_and_audited(self, tmp_path, monkeypatch):
        _drain_env(tmp_path, _pid_dir(tmp_path), monkeypatch)
        task_root = tmp_path / "tasks"
        _write_task(task_root, "orphan-1", status="pr_open", assigned_to="delta")
        cap = _mint_cap(tmp_path, "orphan-1", mod.SYSTEM_DRAIN_LANE)

        v = _validate(mod, task_root, "orphan-1", cap)

        assert v.ok is True
        assert v.reason.startswith("system-drain eligible")
        audit_lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(audit_lines) == 1
        rec = json.loads(audit_lines[0])
        assert rec["task_id"] == "orphan-1"
        assert rec["drained_from_lane"] == "delta"
        assert rec["actor"] == mod.SYSTEM_DRAIN_LANE

    def test_same_capability_replay_rejected(self, tmp_path, monkeypatch):
        _drain_env(tmp_path, _pid_dir(tmp_path), monkeypatch)
        task_root = tmp_path / "tasks"
        _write_task(task_root, "orphan-2", status="pr_open", assigned_to="delta")
        cap = _mint_cap(tmp_path, "orphan-2", mod.SYSTEM_DRAIN_LANE)

        first = _validate(mod, task_root, "orphan-2", cap)
        second = _validate(mod, task_root, "orphan-2", cap)

        assert first.ok is True
        assert second.ok is False
        assert "already consumed (replay)" in second.reason

    def test_live_lane_refused_critical_guard(self, tmp_path, monkeypatch):
        pid_dir = _pid_dir(tmp_path)
        (pid_dir / "delta.pid").write_text(str(os.getpid()), encoding="utf-8")
        _drain_env(tmp_path, pid_dir, monkeypatch)
        task_root = tmp_path / "tasks"
        _write_task(task_root, "orphan-3", status="pr_open", assigned_to="delta")
        cap = _mint_cap(tmp_path, "orphan-3", mod.SYSTEM_DRAIN_LANE)

        v = _validate(mod, task_root, "orphan-3", cap)

        assert v.ok is False
        assert "is ALIVE; refusing to drain a live lane" in v.reason
        # The capability must NOT be consumed when the live-lane guard rejects.
        assert not (tmp_path / "consumption.jsonl").exists()

    def test_wrong_task_binding_refused(self, tmp_path, monkeypatch):
        _drain_env(tmp_path, _pid_dir(tmp_path), monkeypatch)
        task_root = tmp_path / "tasks"
        _write_task(task_root, "orphan-4", status="pr_open", assigned_to="delta")
        cap = _mint_cap(tmp_path, "a-different-task", mod.SYSTEM_DRAIN_LANE)

        v = _validate(mod, task_root, "orphan-4", cap)

        assert v.ok is False
        assert "invalid/expired/mismatched" in v.reason

    def test_capability_bound_to_real_lane_refused(self, tmp_path, monkeypatch):
        _drain_env(tmp_path, _pid_dir(tmp_path), monkeypatch)
        task_root = tmp_path / "tasks"
        _write_task(task_root, "orphan-5", status="pr_open", assigned_to="delta")
        # Minted for a real lane name, not the __system__ sentinel.
        cap = _mint_cap(tmp_path, "orphan-5", "delta")

        v = _validate(mod, task_root, "orphan-5", cap)

        assert v.ok is False
        assert "invalid/expired/mismatched" in v.reason

    def test_expired_capability_refused(self, tmp_path, monkeypatch):
        _drain_env(tmp_path, _pid_dir(tmp_path), monkeypatch)
        task_root = tmp_path / "tasks"
        _write_task(task_root, "orphan-6", status="pr_open", assigned_to="delta")
        cap = _mint_cap(
            tmp_path, "orphan-6", mod.SYSTEM_DRAIN_LANE, ttl=1.0, now=time.time() - 10_000
        )

        v = _validate(mod, task_root, "orphan-6", cap)

        assert v.ok is False
        assert "invalid/expired/mismatched" in v.reason

    def test_missing_capability_path_refused(self, tmp_path, monkeypatch):
        _drain_env(tmp_path, _pid_dir(tmp_path), monkeypatch)
        task_root = tmp_path / "tasks"
        _write_task(task_root, "orphan-7", status="pr_open", assigned_to="delta")

        v = _validate(mod, task_root, "orphan-7", None)

        assert v.ok is False
        assert "requires --dispatch-capability" in v.reason

    def test_unassigned_task_refused(self, tmp_path, monkeypatch):
        _drain_env(tmp_path, _pid_dir(tmp_path), monkeypatch)
        task_root = tmp_path / "tasks"
        _write_task(task_root, "orphan-8", status="pr_open", assigned_to="unassigned")
        cap = _mint_cap(tmp_path, "orphan-8", mod.SYSTEM_DRAIN_LANE)

        v = _validate(mod, task_root, "orphan-8", cap)

        assert v.ok is False
        assert "no assigned lane" in v.reason

    def test_non_drainable_status_refused(self, tmp_path, monkeypatch):
        _drain_env(tmp_path, _pid_dir(tmp_path), monkeypatch)
        task_root = tmp_path / "tasks"
        _write_task(task_root, "orphan-9", status="offered", assigned_to="delta")
        cap = _mint_cap(tmp_path, "orphan-9", mod.SYSTEM_DRAIN_LANE)

        v = _validate(mod, task_root, "orphan-9", cap)

        assert v.ok is False
        assert "not drainable" in v.reason

    def test_unknown_substrate_lane_refused(self, tmp_path, monkeypatch):
        """A lane whose liveness substrate is not verified must fail closed."""
        _drain_env(tmp_path, _pid_dir(tmp_path), monkeypatch)
        task_root = tmp_path / "tasks"
        _write_task(task_root, "orphan-10", status="pr_open", assigned_to="cx-red")
        cap = _mint_cap(tmp_path, "orphan-10", mod.SYSTEM_DRAIN_LANE)

        v = _validate(mod, task_root, "orphan-10", cap)

        assert v.ok is False
        assert "not a known claude-substrate lane" in v.reason

    def test_platform_qualified_assigned_to_normalized_before_liveness(self, tmp_path, monkeypatch):
        """A platform-qualified assigned_to must resolve to the bare-role pid file,
        not be treated as absent (reviewer must-fix #6 — the live-lane-drain hole)."""
        pid_dir = _pid_dir(tmp_path)
        (pid_dir / "delta.pid").write_text(str(os.getpid()), encoding="utf-8")  # delta is ALIVE
        _drain_env(tmp_path, pid_dir, monkeypatch)
        task_root = tmp_path / "tasks"
        _write_task(task_root, "orphan-11", status="pr_open", assigned_to="claude/delta")
        cap = _mint_cap(tmp_path, "orphan-11", mod.SYSTEM_DRAIN_LANE)

        v = _validate(mod, task_root, "orphan-11", cap)

        assert v.ok is False
        assert "is ALIVE; refusing to drain a live lane" in v.reason


# --- normal-lane behavior must be byte-for-byte unchanged (AC #4) -------------


class TestNormalLaneUnchanged:
    def test_pr_open_still_not_dispatchable_for_a_real_lane(self, tmp_path, monkeypatch):
        _drain_env(tmp_path, _pid_dir(tmp_path), monkeypatch)
        task_root = tmp_path / "tasks"
        _write_task(task_root, "pr-task", status="pr_open", assigned_to="beta")

        v = mod.validate_task(
            task_id="pr-task",
            lane="beta",
            platform="claude",
            task_root=task_root,
            strict_worktree=False,
        )

        assert v.ok is False
        assert "is not dispatchable" in v.reason

    def test_claimed_task_to_assigned_lane_still_eligible(self, tmp_path, monkeypatch):
        _drain_env(tmp_path, _pid_dir(tmp_path), monkeypatch)
        task_root = tmp_path / "tasks"
        # Authority-exempt (read-only) kind so the normal-lane path reaches eligible
        # without an ISAP parent_spec — this isolates the assigned-lane gate, which
        # the claimed-task-to-its-own-lane case must continue to pass unchanged.
        _write_task(
            task_root, "claimed-task", status="claimed", assigned_to="beta", kind="research"
        )

        v = mod.validate_task(
            task_id="claimed-task",
            lane="beta",
            platform="claude",
            task_root=task_root,
            strict_worktree=False,
        )

        assert v.ok is True

    def test_claimed_task_to_wrong_lane_still_rejected(self, tmp_path, monkeypatch):
        _drain_env(tmp_path, _pid_dir(tmp_path), monkeypatch)
        task_root = tmp_path / "tasks"
        _write_task(
            task_root, "claimed-other", status="claimed", assigned_to="beta", kind="research"
        )

        v = mod.validate_task(
            task_id="claimed-other",
            lane="delta",
            platform="claude",
            task_root=task_root,
            strict_worktree=False,
        )

        assert v.ok is False
        assert "may only be dispatched to assigned lane" in v.reason


# --- sentinel may never reach the launch path (reviewer must-fix #3) ----------


class TestSentinelRejectedForLaunch:
    def test_build_prompt_rejects_sentinel(self, tmp_path):
        task_root = tmp_path / "tasks"
        _write_task(task_root, "phantom", status="pr_open", assigned_to="delta")
        task = mod.read_task(task_root, "phantom")
        validation = mod.Validation(True, "x", task)
        route = mod.RECEIPT_ONLY_ROUTE
        try:
            mod.build_prompt(
                "phantom", mod.SYSTEM_DRAIN_LANE, "claude", "headless", "full", validation, route
            )
        except ValueError as exc:
            assert "__system__" in str(exc)
        else:
            raise AssertionError("build_prompt must refuse the __system__ sentinel lane")


# --- end-to-end CLI: the drain actually MUTATES via cc-stage-advance ----------


def _cli_env(tmp_path: Path, pid_dir: Path) -> tuple[dict[str, str], Path, Path]:
    """Env where validate_task's task root and cc-stage-advance's hardcoded VAULT
    (``$HOME/Documents/Personal/20-projects/hapax-cc-tasks``) coincide, so the real
    cc-stage-advance subprocess mutates the same note the drain validated."""
    home = tmp_path / "home"
    vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    vault.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["HAPAX_CC_TASK_ROOT"] = str(vault)
    env["HAPAX_LANE_PID_DIR"] = str(pid_dir)
    env["HAPAX_COORD_GRANT_KEY"] = str(_key_file(tmp_path))
    env["HAPAX_COORD_CONSUMPTION_LEDGER"] = str(tmp_path / "consumption.jsonl")
    env["HAPAX_SYSTEM_DRAIN_AUDIT"] = str(tmp_path / "audit.jsonl")
    env["HAPAX_CC_CLAIMS_DIR"] = str(tmp_path / "claims")
    env["HAPAX_ORCHESTRATION_LEDGER_DIR"] = str(tmp_path / "ledger")
    env["HAPAX_COORD_DIR"] = str(tmp_path / "coord")
    env["HAPAX_AUTHORITY_CASE_LEDGER"] = str(tmp_path / "authority-case-ledger.jsonl")
    return env, home, vault


def _stage(note: Path) -> str:
    for line in note.read_text(encoding="utf-8").splitlines():
        if line.startswith("stage:"):
            return line.split(":", 1)[1].strip()
    return ""


def test_cli_drain_advances_stage_via_cc_stage_advance(tmp_path):
    pid_dir = _pid_dir(tmp_path)  # empty -> delta absent
    env, _home, vault = _cli_env(tmp_path, pid_dir)
    note = _write_task(vault, "orphan-cli-1", status="pr_open", assigned_to="delta")
    cap = _mint_cap(tmp_path, "orphan-cli-1", "__system__")

    result = subprocess.run(
        [
            str(SCRIPT),
            "--task",
            "orphan-cli-1",
            "--lane",
            "__system__",
            "--dispatch-capability",
            str(cap),
            "--drain-to-stage",
            "S7_RELEASE",
            "--skip-worktree-check",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert _stage(note) == "S7_RELEASE"
    consumed = (tmp_path / "consumption.jsonl").read_text(encoding="utf-8")
    assert json.loads(consumed.strip().splitlines()[0])["capability_id"]


def test_cli_drain_replay_blocked_no_second_advance(tmp_path):
    pid_dir = _pid_dir(tmp_path)
    env, _home, vault = _cli_env(tmp_path, pid_dir)
    note = _write_task(vault, "orphan-cli-2", status="pr_open", assigned_to="delta")
    cap = _mint_cap(tmp_path, "orphan-cli-2", "__system__")
    args = [
        str(SCRIPT),
        "--task",
        "orphan-cli-2",
        "--lane",
        "__system__",
        "--dispatch-capability",
        str(cap),
        "--drain-to-stage",
        "S7_RELEASE",
        "--skip-worktree-check",
    ]

    first = subprocess.run(args, env=env, text=True, capture_output=True, check=False)
    second = subprocess.run(args, env=env, text=True, capture_output=True, check=False)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 10
    assert "replay" in second.stderr or "already consumed" in second.stderr
    assert _stage(note) == "S7_RELEASE"


def test_cli_live_lane_blocked_no_mutation(tmp_path):
    pid_dir = _pid_dir(tmp_path)
    (pid_dir / "delta.pid").write_text(str(os.getpid()), encoding="utf-8")  # delta ALIVE
    env, _home, vault = _cli_env(tmp_path, pid_dir)
    note = _write_task(vault, "orphan-cli-3", status="pr_open", assigned_to="delta")
    cap = _mint_cap(tmp_path, "orphan-cli-3", "__system__")

    result = subprocess.run(
        [
            str(SCRIPT),
            "--task",
            "orphan-cli-3",
            "--lane",
            "__system__",
            "--dispatch-capability",
            str(cap),
            "--drain-to-stage",
            "S7_RELEASE",
            "--skip-worktree-check",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 10
    assert "ALIVE" in result.stderr
    assert _stage(note) == "S6_IMPLEMENTATION"  # untouched


def test_cli_sentinel_without_capability_blocks_without_launch(tmp_path):
    """``--lane __system__`` must route to the drain (never launch a phantom
    ``hapax-council--__system__`` worktree) and refuse cleanly without a cap."""
    pid_dir = _pid_dir(tmp_path)
    env, _home, vault = _cli_env(tmp_path, pid_dir)
    _write_task(vault, "orphan-cli-4", status="pr_open", assigned_to="delta")

    result = subprocess.run(
        [
            str(SCRIPT),
            "--task",
            "orphan-cli-4",
            "--lane",
            "__system__",
            "--drain-to-stage",
            "S7_RELEASE",
            "--launch",
            "--skip-worktree-check",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 10
    assert "requires --dispatch-capability" in result.stderr
    assert "hapax-council--__system__" not in result.stderr
