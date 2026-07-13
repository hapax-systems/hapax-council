"""Characterize the legacy SYSTEM-drain helpers and seal their CLI effect ingress.

The read-only liveness, normalization, and transition-preflight helpers remain
covered while the ``--lane __system__`` CLI entry point is contained. A drain may
not consume a capability, write a receipt/audit, or advance a task until it is an
exact action admitted and consumed by the Gate-0 lifecycle spine.
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
PROJECT_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"

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
    parent_spec = task_root / "specs" / f"{authority_case}.md"
    parent_spec.parent.mkdir(parents=True, exist_ok=True)
    if not parent_spec.exists():
        parent_spec.write_text(
            f"---\ncase_id: {authority_case}\n---\n\n# Parent spec\n",
            encoding="utf-8",
        )
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
            parent_spec: {parent_spec}
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
    def test_pr_open_dead_lane_preflight_does_not_consume_or_audit(self, tmp_path, monkeypatch):
        _drain_env(tmp_path, _pid_dir(tmp_path), monkeypatch)
        task_root = tmp_path / "tasks"
        _write_task(task_root, "orphan-1", status="pr_open", assigned_to="delta")
        cap = _mint_cap(tmp_path, "orphan-1", mod.SYSTEM_DRAIN_LANE)

        v = _validate(mod, task_root, "orphan-1", cap)

        assert v.ok is True
        assert v.reason.startswith("system-drain preflight eligible")
        assert v.exempt_read_only is False
        assert not (tmp_path / "audit.jsonl").exists()
        assert not (tmp_path / "consumption.jsonl").exists()

    def test_consumed_capability_replay_rejected_without_second_consume(
        self, tmp_path, monkeypatch
    ):
        _drain_env(tmp_path, _pid_dir(tmp_path), monkeypatch)
        task_root = tmp_path / "tasks"
        _write_task(task_root, "orphan-2", status="pr_open", assigned_to="delta")
        cap = _mint_cap(tmp_path, "orphan-2", mod.SYSTEM_DRAIN_LANE)

        capability_id = json.loads(cap.read_text(encoding="utf-8"))["capability_id"]
        (tmp_path / "consumption.jsonl").write_text(
            json.dumps({"capability_id": capability_id}) + "\n",
            encoding="utf-8",
        )
        result = _validate(mod, task_root, "orphan-2", cap)

        assert result.ok is False
        assert "already consumed (replay)" in result.reason
        assert len((tmp_path / "consumption.jsonl").read_text().splitlines()) == 1

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


# --- CLI containment: no legacy drain effect may cross Gate 0 -----------------


def _cli_env(tmp_path: Path, pid_dir: Path) -> tuple[dict[str, str], Path, Path]:
    """Isolate every path the retired drain could have mutated."""
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
    env.pop("HAPAX_CANON_ECHO_ENFORCEMENT", None)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    return env, home, vault


def test_cli_system_drain_holds_before_every_legacy_effect(tmp_path: Path) -> None:
    pid_dir = _pid_dir(tmp_path)  # empty: the legacy drain would consider delta dead
    env, _home, vault = _cli_env(tmp_path, pid_dir)
    note = _write_task(vault, "orphan-cli-1", status="pr_open", assigned_to="delta")
    cap = _mint_cap(tmp_path, "orphan-cli-1", "__system__")
    claims = tmp_path / "claims"
    claims.mkdir()
    claim = claims / "cc-active-task-delta"
    epoch = claims / "cc-claim-epoch-delta"
    sidecar = claims / "cc-claim-dispatch-delta.json"
    claim.write_text("orphan-cli-1\n", encoding="utf-8")
    epoch.write_text("epoch-sentinel\n", encoding="utf-8")
    sidecar.write_text('{"sentinel": true}\n', encoding="utf-8")

    consumption = tmp_path / "consumption.jsonl"
    audit = tmp_path / "audit.jsonl"
    receipt = tmp_path / "ledger" / "methodology-dispatch.jsonl"
    receipt.parent.mkdir(parents=True)
    consumption.write_text("consumption-sentinel\n", encoding="utf-8")
    audit.write_text("audit-sentinel\n", encoding="utf-8")
    receipt.write_text("receipt-sentinel\n", encoding="utf-8")
    before = {
        path: path.read_bytes()
        for path in (note, cap, claim, epoch, sidecar, consumption, audit, receipt)
    }

    result = subprocess.run(
        [
            str(PROJECT_PYTHON),
            "-I",
            str(SCRIPT),
            "--task",
            "orphan-cli-1",
            "--lane",
            "__system__",
            "--dispatch-capability",
            str(cap),
            "--drain-to-stage",
            "S7_RELEASE",
            "--guard-evidence",
            "implementation_complete=task:orphan-cli-1:implementation",
            "--guard-evidence",
            "evidence_present=task:orphan-cli-1:evidence",
            "--launch",
            "--skip-worktree-check",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 10
    assert result.stdout == ""
    assert "HOLD: admitted_lifecycle_action_required" in result.stderr
    assert "operation=system_drain" in result.stderr
    assert "materialize and consume the exact admitted lifecycle action" in result.stderr
    assert "system-drained" not in result.stderr
    for path, expected in before.items():
        assert path.read_bytes() == expected


def test_cli_system_drain_hold_precedes_legacy_precondition_checks(tmp_path: Path) -> None:
    env, _home, vault = _cli_env(tmp_path, _pid_dir(tmp_path))
    note = _write_task(vault, "orphan-cli-2", status="pr_open", assigned_to="delta")
    before = note.read_bytes()

    result = subprocess.run(
        [
            str(PROJECT_PYTHON),
            "-I",
            str(SCRIPT),
            "--task",
            "orphan-cli-2",
            "--lane",
            "__system__",
            "--launch",
            "--no-receipt",
            "--skip-worktree-check",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 10
    assert "operation=system_drain" in result.stderr
    assert "requires --dispatch-capability" not in result.stderr
    assert "refuses --no-receipt" not in result.stderr
    assert note.read_bytes() == before
    assert not (tmp_path / "consumption.jsonl").exists()
    assert not (tmp_path / "audit.jsonl").exists()
    assert not (tmp_path / "ledger").exists()
