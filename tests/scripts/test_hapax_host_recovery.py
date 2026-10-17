from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-host-recovery"
loader = importlib.machinery.SourceFileLoader("host_recovery", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)

BOOT = "11111111-2222-3333-4444-555555555555"
TRANSCRIPT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def lane(tmp_path: Path, *, provider: str = "codex") -> dict:
    role = "codex-openmarket" if provider == "codex" else "dev1-seat"
    tmux = "hapax-codex-openmarket" if provider == "codex" else "hapax-claude-dev1-seat"
    inbox = tmp_path / ("codex-openmarket" if provider == "codex" else "dev1")
    inbox.mkdir(exist_ok=True)
    cwd = tmp_path / "workspace"
    cwd.mkdir(exist_ok=True)
    return {
        "role": role,
        "tmux": tmux,
        "provider": provider,
        "transcript": TRANSCRIPT,
        "session_id": TRANSCRIPT,
        "cwd": str(cwd),
        "inbox": str(inbox),
        "memory": {"high": "5G", "max": "7G", "swap": "1G"},
        **(
            {"sandbox": "danger-full-access", "approval": "never"}
            if provider == "codex"
            else {"permission_mode": "bypass"}
        ),
    }


def test_capture_refuses_to_erase_previous_boot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "boot_id", lambda: BOOT)
    path = tmp_path / "manifest.json"
    old = {
        "schema": 1,
        "host": module.socket.gethostname().split(".")[0],
        "boot_id": "old-boot",
        "lanes": [lane(tmp_path)],
    }
    module.atomic_json(path, old)
    monkeypatch.setattr(module, "live_lanes", lambda: [])
    with pytest.raises(ValueError, match="previous boot has not been restored"):
        module.capture(path)
    assert json.loads(path.read_text())["boot_id"] == old["boot_id"]


def test_manifest_rejects_unbounded_or_forged_lane(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    entry = lane(tmp_path)
    entry["memory"]["max"] = "infinity"
    with pytest.raises(ValueError, match="memory ceiling"):
        module.launch_args(entry)
    entry["memory"]["max"] = "7G"
    entry["tmux"] = "hapax-claude-dev1-seat"
    with pytest.raises(ValueError, match="identity"):
        module.launch_args(entry)


def test_restore_preserves_measured_session_permissions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    entry = lane(tmp_path)
    entry["sandbox"] = "read-only"
    entry["approval"] = "on-request"
    command = module.launch_args(entry)
    assert command[command.index("-s") + 1] == "read-only"
    assert command[command.index("-a") + 1] == "on-request"
    del entry["approval"]
    with pytest.raises(ValueError, match="permission mode"):
        module.launch_args(entry)


def test_readback_rejects_changed_session_permissions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    entry = lane(tmp_path)
    monkeypatch.setattr(module, "run", lambda *args: "123")
    monkeypatch.setattr(
        module,
        "agent_process",
        lambda pid, provider: (
            pid,
            ["codex", "resume", TRANSCRIPT, "-s", "read-only", "-a", "on-request"],
            {"HAPAX_AGENT_ROLE": entry["role"], "HAPAX_SESSION_ID": TRANSCRIPT},
        ),
    )
    monkeypatch.setattr(module, "scope_readback", lambda pid: None)
    with pytest.raises(ValueError, match="permission mode differs"):
        module.readback(entry)


def test_readback_walks_a_real_shell_exec_chain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    entry = lane(tmp_path)
    (tmp_path / "resume").write_text("import time; time.sleep(30)\n")
    agent = tmp_path / "codex"
    agent.symlink_to(sys.executable)
    inner = "exec " + shlex.join(
        [str(agent), "resume", TRANSCRIPT, "-s", "danger-full-access", "-a", "never"]
    )
    env = os.environ | {"HAPAX_AGENT_ROLE": entry["role"], "HAPAX_SESSION_ID": TRANSCRIPT}
    pane = subprocess.Popen(
        ["/bin/bash", "-c", "/bin/bash -c " + shlex.quote(inner) + " & wait"],
        cwd=tmp_path,
        env=env,
        start_new_session=True,
    )
    seen: list[str] = []
    monkeypatch.setattr(module, "run", lambda *args: str(pane.pid))
    monkeypatch.setattr(module, "scope_readback", lambda pid: seen.append(pid))
    try:
        deadline = time.monotonic() + 3
        while True:
            try:
                module.readback(entry)
                break
            except ValueError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)
        assert seen and seen[-1] != str(pane.pid)
        assert (
            Path(f"/proc/{seen[-1]}/cmdline")
            .read_bytes()
            .startswith(os.fsencode(agent) + b"\0resume\0")
        )
    finally:
        try:
            os.killpg(pane.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        pane.wait(timeout=5)


def test_restore_rebuilds_bounded_commands_and_reports_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "boot_id", lambda: BOOT)
    entries = [lane(tmp_path), lane(tmp_path, provider="claude")]
    path = tmp_path / "manifest.json"
    module.atomic_json(
        path,
        {
            "schema": 1,
            "host": module.socket.gethostname().split(".")[0],
            "boot_id": "old-boot",
            "lanes": entries,
        },
    )
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[1] == "has-session":
            return subprocess.CompletedProcess(args, 1)
        if args[1] == "new-session" and args[4] == "hapax-claude-dev1-seat":
            raise subprocess.CalledProcessError(1, args)
        return subprocess.CompletedProcess(args, 0)

    reports: list[dict] = []
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "readback", lambda entry: None)
    monkeypatch.setattr(module, "report", lambda result: reports.append(result))
    result = module.restore(path)
    launches = [call for call in calls if call[1] == "new-session"]
    assert len(launches) == 2
    for call in launches:
        command = call[-1]
        assert call[-3:-1] == ["/bin/sh", "-c"]
        assert command.startswith("exec systemd-run ")
        assert "MemoryHigh=5G" in command
        assert "MemoryMax=7G" in command
        assert "MemorySwapMax=1G" in command
        assert "prlimit --nofile=65536:1048576 -- env" in command
        assert TRANSCRIPT in command
        assert "SEAT " not in command
    assert "hapax-claude-dev1-seat" in result["failed"]
    assert result["restored"] == ["hapax-codex-openmarket"]
    assert len(reports) == 1
    assert json.loads(path.read_text())["boot_id"] == "old-boot"


def test_restore_same_boot_and_all_live_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "boot_id", lambda: BOOT)
    entry = lane(tmp_path)
    path = tmp_path / "manifest.json"
    module.atomic_json(
        path,
        {
            "schema": 1,
            "host": module.socket.gethostname().split(".")[0],
            "boot_id": BOOT,
            "lanes": [entry],
        },
    )
    monkeypatch.setattr(
        module.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0)
    )
    monkeypatch.setattr(module, "readback", lambda entry: None)
    monkeypatch.setattr(module, "report", lambda result: pytest.fail("unexpected report"))
    result = module.restore(path)
    assert result["already_live"] == [entry["tmux"]]
    assert not result["restored"]


def test_unit_recovery_starts_missing_declared_unit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(module, "boot_id", lambda: BOOT)
    path = tmp_path / "manifest.json"
    unit = {"scope": "user", "name": "fleet-review-tailnet.service", "enabled": "static"}
    module.atomic_json(
        path,
        {
            "schema": 1,
            "host": module.socket.gethostname().split(".")[0],
            "boot_id": "old-boot",
            "lanes": [],
            "units": [unit],
        },
    )
    active = False
    calls: list[list[str]] = []

    def fake_property(entry: dict, prop: str) -> str:
        return "static" if prop == "UnitFileState" else "active" if active else "inactive"

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal active
        calls.append(args)
        if args == ["systemctl", "--user", "start", "fleet-review-tailnet.service"]:
            active = True
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(module, "unit_property", fake_property)
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "report", lambda result: None)
    result = module.restore(path)
    assert result["units_started"] == ["user:fleet-review-tailnet.service"]
    assert calls == [["systemctl", "--user", "start", "fleet-review-tailnet.service"]]
    assert json.loads(path.read_text())["boot_id"] == BOOT


def test_unit_recovery_refuses_changed_enablement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(module, "boot_id", lambda: BOOT)
    path = tmp_path / "manifest.json"
    unit = {"scope": "user", "name": "fleet-review-tailnet.service", "enabled": "static"}
    module.atomic_json(
        path,
        {
            "schema": 1,
            "host": module.socket.gethostname().split(".")[0],
            "boot_id": "old-boot",
            "lanes": [],
            "units": [unit],
        },
    )
    monkeypatch.setattr(module, "unit_property", lambda entry, prop: "disabled")
    monkeypatch.setattr(
        module.subprocess, "run", lambda *args, **kwargs: pytest.fail("unexpected start")
    )
    monkeypatch.setattr(module, "report", lambda result: None)
    result = module.restore(path)
    assert "user:fleet-review-tailnet.service" in result["failed"]
    assert json.loads(path.read_text())["boot_id"] == "old-boot"


def test_scope_readback_rejects_unbounded_lane(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup"
    group = "/user.slice/user-1000.slice/user@1000.service/app.slice/run-p1.scope"
    (proc / "123").mkdir(parents=True)
    (proc / "123" / "cgroup").write_text(f"0::{group}\n")
    (proc / "123" / "limits").write_text(
        "Max open files            1024                 1048576              files\n"
    )
    scope = cgroup / group.lstrip("/")
    scope.mkdir(parents=True)
    for name, value in {
        "memory.high": "5368709120",
        "memory.max": "max",
        "memory.swap.max": "1073741824",
    }.items():
        (scope / name).write_text(value)
    with pytest.raises(ValueError, match="memory.max"):
        module.scope_readback("123", proc, cgroup)
    (scope / "memory.max").write_text("7516192768")
    with pytest.raises(ValueError, match="soft NOFILE"):
        module.scope_readback("123", proc, cgroup)
    (proc / "123" / "limits").write_text(
        "Max open files            65536                1048576              files\n"
    )
    module.scope_readback("123", proc, cgroup)


def test_wrong_manifest_hash_refuses_before_restore_action(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    entry = lane(tmp_path)
    path = tmp_path / "manifest.json"
    module.atomic_json(
        path,
        {
            "schema": 1,
            "host": module.socket.gethostname().split(".")[0],
            "boot_id": "old-boot",
            "lanes": [entry],
        },
    )
    forged = json.loads(path.read_text())
    forged["lanes"][0]["transcript"] = "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee"
    path.write_text(json.dumps(forged))
    monkeypatch.setattr(
        module.subprocess, "run", lambda *args, **kwargs: pytest.fail("restore acted")
    )
    with pytest.raises(ValueError, match="hash mismatch"):
        module.restore(path)
