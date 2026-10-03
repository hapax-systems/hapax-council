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
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-host-recovery"
loader = importlib.machinery.SourceFileLoader("host_recovery", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)

BOOT = "11111111-2222-3333-4444-555555555555"
TRANSCRIPT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.fixture(autouse=True)
def ordinary_test_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module.socket, "gethostname", lambda: "test-host")


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


def test_codex_seat_binding_is_exact_and_keeps_claude_custody(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    predecessor = lane(tmp_path, provider="claude")
    codex_seat = lane(tmp_path)
    codex_seat.update(
        role="dev1-seat-codex",
        tmux="hapax-codex-seat",
        inbox=str(tmp_path / "dev1"),
    )
    module.validate(predecessor)
    module.validate(codex_seat)
    assert "HAPAX_AGENT_ROLE=dev1-seat-codex" in module.launch_args(codex_seat)

    for changed in (
        {"tmux": "hapax-codex-dev1-seat-codex"},
        {"inbox": str(tmp_path / "codex-openmarket")},
        {"provider": "claude"},
        {"role": "dev1-seat-codex-other"},
    ):
        with pytest.raises(ValueError):
            module.validate(codex_seat | changed)

    monkeypatch.setattr(module, "boot_id", lambda: BOOT)
    monkeypatch.setattr(module, "live_lanes", lambda: [codex_seat])
    path = tmp_path / "manifest.json"
    module.atomic_json(
        path,
        {"schema": 1, "host": "test-host", "boot_id": BOOT, "lanes": [predecessor], "units": []},
    )
    captured = module.capture(path)
    assert [(entry["role"], entry["tmux"]) for entry in captured["lanes"]] == [
        ("dev1-seat", "hapax-claude-dev1-seat"),
        ("dev1-seat-codex", "hapax-codex-seat"),
    ]


def test_live_lanes_maps_exact_codex_seat_pane_to_declared_role_and_inbox(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    expected = lane(tmp_path)
    (tmp_path / "dev1").mkdir()
    expected.update(
        role="dev1-seat-codex",
        tmux="hapax-codex-seat",
        inbox=str(tmp_path / "dev1"),
    )
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, f"{expected['tmux']}\t123\t{expected['cwd']}\n", ""
        ),
    )
    monkeypatch.setattr(
        module,
        "agent_process",
        lambda pid, provider: (
            pid,
            ["codex", "resume", TRANSCRIPT, "-s", "danger-full-access", "-a", "never"],
            {"HAPAX_AGENT_ROLE": expected["role"], "HAPAX_SESSION_ID": TRANSCRIPT},
        ),
    )
    monkeypatch.setattr(module, "scope_readback", lambda pid: None)
    assert module.live_lanes() == [expected]
    monkeypatch.setattr(
        module,
        "agent_process",
        lambda pid, provider: (
            pid,
            ["codex", "resume", TRANSCRIPT],
            {"HAPAX_AGENT_ROLE": "codex-seat"},
        ),
    )
    with pytest.raises(ValueError, match="lane role mismatch"):
        module.live_lanes()


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


def test_live_lanes_accepts_matching_node_codex_child_and_refuses_mismatches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    entry = lane(tmp_path)
    native = tmp_path / "native" / "codex"
    native.parent.mkdir()
    native.symlink_to(sys.executable)
    (tmp_path / "resume").write_text("import time; time.sleep(30)\n")
    wrapper = tmp_path / "codex"
    wrapper.write_text(
        "const {spawn} = require('child_process');\n"
        f"const child = spawn({json.dumps(str(native))}, process.argv.slice(2), "
        f"{{cwd: {json.dumps(str(tmp_path))}, stdio: 'ignore'}});\n"
        "child.on('exit', () => process.exit(1));\n"
        "setInterval(() => {}, 1000);\n"
    )
    monkeypatch.setattr(module, "CODEX_NODE_WRAPPER", wrapper, raising=False)
    env = os.environ | {"HAPAX_AGENT_ROLE": entry["role"], "HAPAX_SESSION_ID": TRANSCRIPT}
    pane = subprocess.Popen(
        ["node", str(wrapper), "resume", TRANSCRIPT, "-s", "danger-full-access", "-a", "never"],
        cwd=tmp_path,
        env=env,
        start_new_session=True,
    )
    seen: list[str] = []
    try:
        deadline = time.monotonic() + 3
        while True:
            children = Path(f"/proc/{pane.pid}/task/{pane.pid}/children").read_text().split()
            if len(children) == 1:
                child_pid = children[0]
                child_argv, child_env = module.proc_fields(child_pid)
            else:
                child_argv = []
            if child_argv and Path(child_argv[0]).name == "codex":
                break
            if time.monotonic() >= deadline:
                raise AssertionError("node wrapper did not launch native Codex child")
            time.sleep(0.01)
        assert child_pid != str(pane.pid)
        assert child_argv[2] == child_env["HAPAX_SESSION_ID"] == TRANSCRIPT
        monkeypatch.setattr(
            module.subprocess,
            "run",
            lambda *args, **kwargs: subprocess.CompletedProcess(
                args, 0, f"{entry['tmux']}\t{pane.pid}\t{entry['cwd']}\n", ""
            ),
        )
        monkeypatch.setattr(module, "scope_readback", lambda pid: seen.append(pid))
        assert module.live_lanes() == [entry]
        assert seen == [child_pid]
        monkeypatch.setattr(module, "run", lambda *args: str(pane.pid))
        module.readback(entry)
        assert seen == [child_pid, child_pid]

        monkeypatch.setattr(module, "CODEX_NODE_WRAPPER", tmp_path / "unrelated")
        with pytest.raises(ValueError, match="wrapper or native child"):
            module.agent_process(str(pane.pid), "codex")
        monkeypatch.setattr(module, "CODEX_NODE_WRAPPER", wrapper)
        original_fields = module.proc_fields

        def wrong_transcript(pid: str) -> tuple[list[str], dict[str, str]]:
            argv, found_env = original_fields(pid)
            if pid == child_pid:
                argv[2] = BOOT
            return argv, found_env

        monkeypatch.setattr(module, "proc_fields", wrong_transcript)
        with pytest.raises(ValueError, match="wrapper or native child"):
            module.agent_process(str(pane.pid), "codex")
        monkeypatch.setattr(module, "proc_fields", original_fields)
        monkeypatch.setattr(
            module,
            "agent_process",
            lambda *args: (child_pid, child_argv, {"HAPAX_AGENT_ROLE": "codex-other"}),
        )
        with pytest.raises(ValueError, match="lane role mismatch"):
            module.live_lanes()
        monkeypatch.setattr(
            module, "agent_process", lambda *args: (child_pid, child_argv, child_env)
        )
        monkeypatch.setattr(
            module, "scope_readback", lambda pid: (_ for _ in ()).throw(ValueError("scope differs"))
        )
        with pytest.raises(ValueError, match="scope differs"):
            module.live_lanes()
    finally:
        try:
            os.killpg(pane.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        pane.wait(timeout=5)


def test_agent_process_refuses_node_wrapper_without_native_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wrapper = tmp_path / "codex"
    wrapper.write_text("setInterval(() => {}, 1000);\n")
    monkeypatch.setattr(module, "CODEX_NODE_WRAPPER", wrapper)
    pane = subprocess.Popen(["node", str(wrapper), "resume", TRANSCRIPT], start_new_session=True)
    try:
        deadline = time.monotonic() + 3
        while not Path(f"/proc/{pane.pid}/cmdline").read_bytes().startswith(b"node\0"):
            if time.monotonic() >= deadline:
                raise AssertionError("node wrapper did not start")
            time.sleep(0.01)
        with pytest.raises(ValueError, match="expected one codex agent.*found 0"):
            module.agent_process(str(pane.pid), "codex")
    finally:
        try:
            os.killpg(pane.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        pane.wait(timeout=5)


def test_agent_process_refuses_node_wrapper_with_nonchild_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    native = tmp_path / "native" / "codex"
    native.parent.mkdir()
    native.symlink_to(sys.executable)
    (tmp_path / "resume").write_text("import time; time.sleep(30)\n")
    wrapper = tmp_path / "codex"
    command = shlex.join(
        [str(native), "resume", TRANSCRIPT, "-s", "danger-full-access", "-a", "never"]
    )
    wrapper.write_text(
        "const {spawn} = require('child_process');\n"
        f"spawn('/bin/sh', ['-c', {json.dumps(command + ' & wait')}], "
        f"{{cwd: {json.dumps(str(tmp_path))}, stdio: 'ignore'}});\n"
        "setInterval(() => {}, 1000);\n"
    )
    monkeypatch.setattr(module, "CODEX_NODE_WRAPPER", wrapper)
    pane = subprocess.Popen(
        ["node", str(wrapper), "resume", TRANSCRIPT, "-s", "danger-full-access", "-a", "never"],
        cwd=tmp_path,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 3
        while True:
            try:
                module.agent_process(str(pane.pid), "codex")
            except ValueError as exc:
                if "wrapper or native child differs" in str(exc):
                    break
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)
            else:
                pytest.fail("nonchild native agent was accepted")
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


def test_dry_run_simulates_missing_live_lane_without_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "boot_id", lambda: BOOT)
    entry = lane(tmp_path)
    path = tmp_path / "manifest.json"
    module.atomic_json(path, {"schema": 1, "host": "test-host", "boot_id": BOOT, "lanes": [entry]})
    before = path.read_bytes()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        assert args[:2] == ["tmux", "has-session"]
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "readback", lambda entry: None)
    monkeypatch.setattr(module, "report", lambda result: pytest.fail("unexpected report"))
    result = module.restore(path, dry_run=True, simulate_missing=(entry["tmux"],))
    assert result["restored"] == [entry["tmux"]]
    assert result["already_live"] == []
    assert result["dry_run"] is True
    assert result["simulated_missing"] == [entry["tmux"]]
    assert path.read_bytes() == before
    assert all(call[:2] == ["tmux", "has-session"] for call in calls)


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


def test_capture_session_mode_requires_explicit_allowlisted_flags() -> None:
    codex = ["codex", "resume", TRANSCRIPT, "-s", "workspace-write", "-a", "on-request"]
    assert module.session_mode("codex", codex) == {
        "sandbox": "workspace-write",
        "approval": "on-request",
    }
    with pytest.raises(ValueError, match="permission mode"):
        module.session_mode("codex", ["codex", "resume", TRANSCRIPT])
    with pytest.raises(ValueError, match="permission mode"):
        module.session_mode("codex", [*codex, "-s", "danger-full-access"])
    assert module.session_mode(
        "claude", ["claude", "--resume", TRANSCRIPT, "--dangerously-skip-permissions"]
    ) == {"permission_mode": "bypass"}


def test_restore_reports_agent_readback_timeout_after_20_seconds(
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
            "boot_id": "old-boot",
            "lanes": [entry],
        },
    )
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 1 if args[1] == "has-session" else 0)

    attempts: list[str] = []

    def never_readback(item: dict) -> None:
        attempts.append(item["tmux"])
        raise ValueError("agent absent")

    reports: list[dict] = []
    clock = iter((0, 5, 10, 15, 20))
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "readback", never_readback)
    monkeypatch.setattr(module, "report", lambda result: reports.append(result))
    monkeypatch.setattr(
        module, "time", SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda _: None)
    )
    result = module.restore(path)
    assert attempts == [entry["tmux"]] * 4
    assert "restored lane failed identity/scope readback" in result["failed"][entry["tmux"]]
    assert reports == [result]
    assert json.loads(path.read_text())["boot_id"] == "old-boot"


def test_transcript_id_requires_explicit_uuid() -> None:
    assert module.transcript_id("codex", ["codex", "resume", TRANSCRIPT, "brief"]) == TRANSCRIPT
    assert module.transcript_id("claude", ["claude", "--resume", TRANSCRIPT]) == TRANSCRIPT
    with pytest.raises(ValueError, match="resume identity"):
        module.transcript_id("codex", ["codex", "resume"])
    with pytest.raises(ValueError, match="unique explicit"):
        module.transcript_id("claude", ["claude", "--continue"])


@pytest.mark.parametrize(
    "message", ["no server running", "error connecting to /tmp/tmux-1001/default"]
)
def test_unit_only_host_accepts_absent_tmux_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, message: str
) -> None:
    monkeypatch.setattr(module, "boot_id", lambda: BOOT)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, "", message),
    )
    monkeypatch.setattr(
        module,
        "declare_unit",
        lambda spec: {"scope": "user", "name": "fleet-review.service", "enabled": "enabled"},
    )
    path = tmp_path / "manifest.json"
    data = module.capture(path, ("user:fleet-review.service",))
    assert data["lanes"] == []
    assert data["units"] == [
        {"scope": "user", "name": "fleet-review.service", "enabled": "enabled"}
    ]


def test_restore_refusal_reports_named_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), "restore", "--manifest", str(tmp_path / "missing")]
    )
    monkeypatch.setattr(module, "boot_id", lambda: BOOT)
    reports: list[dict] = []
    monkeypatch.setattr(module, "report", lambda result: reports.append(result))
    assert module.main() == 2
    assert "manifest_or_report" in reports[0]["failed"]


def test_report_delivery_failure_does_not_stamp_boot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(module, "boot_id", lambda: BOOT)
    path = tmp_path / "manifest.json"
    module.atomic_json(
        path,
        {
            "schema": 1,
            "host": module.socket.gethostname().split(".")[0],
            "boot_id": "old-boot",
            "lanes": [],
            "units": [],
        },
    )
    monkeypatch.setattr(
        module, "report", lambda result: (_ for _ in ()).throw(module.ReportError("ntfy"))
    )
    with pytest.raises(module.ReportError, match="ntfy"):
        module.restore(path)
    assert json.loads(path.read_text())["boot_id"] == "old-boot"


def test_report_writes_local_mail_and_delivers_ntfy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("HAPAX_RECOVERY_REPORT_HOST", raising=False)
    monkeypatch.setenv("HAPAX_RECOVERY_NTFY_TOPIC", "recovery-test")
    result = {
        "host": "hapax-appendix",
        "boot_id": BOOT,
        "restored": ["hapax-codex-openmarket"],
        "already_live": [],
        "units_started": [],
        "failed": {},
    }
    requests: list[object] = []

    class Reply:
        def close(self) -> None:
            pass

    def fake_urlopen(request: object, *, timeout: int) -> Reply:
        assert timeout == 10
        requests.append(request)
        return Reply()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    module.report(result, mail_root=tmp_path / "dev1")
    mail = list((tmp_path / "dev1").glob("*-host-recovery-hapax-appendix-*.md"))
    assert len(mail) == 1
    assert "Restored: hapax-codex-openmarket" in mail[0].read_text()
    assert len(requests) == 1
    assert requests[0].full_url.endswith("/recovery-test")
    assert requests[0].data == mail[0].read_bytes()


@pytest.mark.parametrize("remote_ok", [True, False])
def test_report_remote_delivery_has_local_spool_and_named_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, remote_ok: bool
) -> None:
    monkeypatch.setenv("HAPAX_RECOVERY_REPORT_HOST", "hapax-appendix")
    monkeypatch.setenv("HAPAX_RECOVERY_NTFY_TOPIC", "")
    monkeypatch.setattr(module, "STATE", tmp_path)
    sent: list[tuple[list[str], str]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        sent.append((args, str(kwargs["input"])))
        return subprocess.CompletedProcess(args, 0 if remote_ok else 1, "", "offline")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    result = {
        "host": "aperture",
        "boot_id": BOOT,
        "restored": [],
        "already_live": [],
        "units_started": [],
        "failed": {"unit": "down"},
    }
    if remote_ok:
        module.report(result)
    else:
        with pytest.raises(module.ReportError, match="lanebus delivery failed: offline"):
            module.report(result)
    mail = list((tmp_path / "mail").glob("*-host-recovery-aperture-*.md"))
    assert len(mail) == 1
    assert sent[0][0][:3] == ["tailscale", "ssh", "hapax@hapax-appendix"]
    assert sent[0][1] == mail[0].read_text()


def test_appendix_capture_records_disabled_idle_watchdog_even_when_inactive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(module.socket, "gethostname", lambda: "hapax-appendix")
    monkeypatch.setattr(module, "boot_id", lambda: BOOT)
    monkeypatch.setattr(module, "live_lanes", lambda: [])
    monkeypatch.setattr(
        module,
        "unit_property",
        lambda unit, prop: "disabled" if prop == "UnitFileState" else "inactive",
    )
    path = tmp_path / "manifest.json"
    result = module.capture(path)
    assert result["units"] == [module.IDLE_WATCHDOG]
    assert module.read_manifest(path)["units"] == [module.IDLE_WATCHDOG]


@pytest.mark.parametrize(
    ("enabled", "active", "failure"),
    [
        ("disabled", "inactive", None),
        ("enabled", "inactive", "unit enablement differs"),
        ("disabled", "active", "disabled recovery unit is not inactive"),
    ],
)
def test_appendix_restore_never_starts_idle_watchdog_and_flags_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, enabled: str, active: str, failure: str | None
) -> None:
    monkeypatch.setattr(module.socket, "gethostname", lambda: "hapax-appendix")
    monkeypatch.setattr(module, "boot_id", lambda: BOOT)
    path = tmp_path / "manifest.json"
    module.atomic_json(
        path,
        {"schema": 1, "host": "hapax-appendix", "boot_id": "old-boot", "lanes": [], "units": []},
    )
    monkeypatch.setattr(
        module, "unit_property", lambda unit, prop: enabled if prop == "UnitFileState" else active
    )
    monkeypatch.setattr(
        module.subprocess, "run", lambda *args, **kwargs: pytest.fail("watchdog was acted on")
    )
    reports: list[dict] = []
    monkeypatch.setattr(module, "report", lambda result: reports.append(result))
    result = module.restore(path)
    label = "user:hapax-lane-idle-watchdog.timer"
    if failure is None:
        assert result["failed"] == {}
        assert module.read_manifest(path)["units"] == [module.IDLE_WATCHDOG]
    else:
        assert failure in result["failed"][label]
        assert json.loads(path.read_text())["boot_id"] == "old-boot"
    assert result["units_started"] == []
    assert reports == [result]


def test_appendix_manifest_cannot_claim_idle_watchdog_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(module.socket, "gethostname", lambda: "hapax-appendix")
    path = tmp_path / "manifest.json"
    module.atomic_json(
        path,
        {
            "schema": 1,
            "host": "hapax-appendix",
            "boot_id": "old-boot",
            "lanes": [],
            "units": [{**module.IDLE_WATCHDOG, "enabled": "enabled"}],
        },
    )
    monkeypatch.setattr(
        module.subprocess, "run", lambda *args, **kwargs: pytest.fail("restore acted")
    )
    with pytest.raises(ValueError, match="manifest must say disabled"):
        module.restore(path)
