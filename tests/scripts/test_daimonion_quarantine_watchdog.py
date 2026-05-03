"""Tests for the Daimonion quarantine drift watchdog."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-daimonion-quarantine-watchdog"
SERVICE = "hapax-daimonion.service"
SYSTEMD_SHOW_CMD = [
    "systemctl",
    "--user",
    "show",
    SERVICE,
    "-p",
    "LoadState",
    "-p",
    "UnitFileState",
    "-p",
    "ActiveState",
    "-p",
    "SubState",
    "--value",
]
PGREP_CMD = [
    "pgrep",
    "-af",
    r"agents\.hapax_daimonion|hapax-daimonion\.service|rebuild-service\.sh.*hapax-daimonion",
]
# Private-voice quarantine surface — see scripts/hapax-daimonion-quarantine-watchdog
# module docstring for why broadcast-chain nodes were removed (2026-05-02 incident).
SOURCES = (
    "hapax-private-playback",
    "hapax-notification-private-playback",
    "input.loopback.sink.role.assistant.monitor",
)
SINKS = (
    "hapax-private",
    "hapax-notification-private",
    "input.loopback.sink.role.assistant",
)


def _entry(
    argv: list[str],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> dict[str, Any]:
    return {
        "argv": argv,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
    }


def _short_listing(names: tuple[str, ...]) -> str:
    return "".join(
        f"{idx}\t{name}\tPipeWire\tfloat32le 2ch 48000Hz\n" for idx, name in enumerate(names)
    )


def _base_commands(
    *,
    service_stdout: str = "masked\nmasked\ninactive\ndead\n",
    process_stdout: str = "",
    process_returncode: int = 1,
    source_names: tuple[str, ...] = SOURCES,
    sink_names: tuple[str, ...] = SINKS,
    source_mutes: dict[str, bool] | None = None,
    sink_mutes: dict[str, bool] | None = None,
) -> list[dict[str, Any]]:
    source_mutes = source_mutes or {}
    sink_mutes = sink_mutes or {}
    commands = [
        _entry(SYSTEMD_SHOW_CMD, stdout=service_stdout),
        _entry(PGREP_CMD, returncode=process_returncode, stdout=process_stdout),
        _entry(["pactl", "list", "short", "sources"], stdout=_short_listing(source_names)),
        _entry(["pactl", "list", "short", "sinks"], stdout=_short_listing(sink_names)),
    ]
    for name in source_names:
        muted = source_mutes.get(name, True)
        commands.append(
            _entry(["pactl", "get-source-mute", name], stdout=f"Mute: {'yes' if muted else 'no'}\n")
        )
    for name in sink_names:
        muted = sink_mutes.get(name, True)
        commands.append(
            _entry(["pactl", "get-sink-mute", name], stdout=f"Mute: {'yes' if muted else 'no'}\n")
        )
    return commands


def _run(
    tmp_path: Path,
    commands: list[dict[str, Any]],
    *,
    enforce: bool = False,
    bypass: dict[str, Any] | None = None,
    quarantine: dict[str, Any] | None = None,
) -> subprocess.CompletedProcess[str]:
    fixture = tmp_path / "fixture.json"
    witness = tmp_path / "witness.json"
    bypass_path = tmp_path / "restore-bypass.json"
    quarantine_path = tmp_path / "quarantine.json"
    fixture.write_text(json.dumps({"commands": commands}), encoding="utf-8")
    if bypass is not None:
        bypass_path.write_text(json.dumps(bypass), encoding="utf-8")
    if quarantine is not None:
        quarantine_path.write_text(json.dumps(quarantine), encoding="utf-8")
    args = [
        sys.executable,
        str(SCRIPT),
        "--fixture",
        str(fixture),
        "--witness-path",
        str(witness),
        "--restore-bypass-file",
        str(bypass_path),
        "--quarantine-state-file",
        str(quarantine_path),
    ]
    if enforce:
        args.append("--enforce")
    return subprocess.run(args, capture_output=True, text=True, timeout=5, check=False)


def _witness(tmp_path: Path) -> dict[str, Any]:
    return json.loads((tmp_path / "witness.json").read_text(encoding="utf-8"))


def _load_watchdog_module() -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader(
        "daimonion_quarantine_watchdog_under_test", str(SCRIPT)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def test_command_runner_records_subprocess_timeout(monkeypatch) -> None:
    module = _load_watchdog_module()

    def _timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(
            command,
            kwargs["timeout"],
            output=b"partial-out",
            stderr=b"late stderr",
        )

    monkeypatch.setattr(module.subprocess, "run", _timeout)

    result = module.CommandRunner().run(["systemctl", "--user", "stop", SERVICE], timeout_s=0.25)

    assert result.returncode == 124
    assert result.stdout == "partial-out"
    assert "command timed out after 0.25 seconds" in result.stderr
    assert "late stderr" in result.stderr


def test_healthy_quarantine_reports_success_without_actions(tmp_path: Path) -> None:
    result = _run(tmp_path, _base_commands())

    assert result.returncode == 0, result.stdout + result.stderr
    witness = _witness(tmp_path)
    assert witness["success"] is True
    assert witness["service"]["healthy"] is True
    assert witness["process"]["running"] is False
    assert witness["remaining_blockers"] == []
    assert witness["actions"] == []
    assert witness["operator_notification"] == {
        "status": "healthy_quarantine_witnessed",
        "channel": "stdout_journal_and_witness_json",
        "requires_parent_attention": False,
    }


def test_enforce_reapplies_stop_disable_mask_when_service_drifts(tmp_path: Path) -> None:
    commands = _base_commands(service_stdout="loaded\nenabled\nactive\nrunning\n")
    commands.extend(
        [
            _entry(["systemctl", "--user", "stop", SERVICE]),
            _entry(["systemctl", "--user", "disable", SERVICE]),
            _entry(["systemctl", "--user", "mask", SERVICE]),
        ]
    )

    result = _run(tmp_path, commands, enforce=True)

    assert result.returncode == 0, result.stdout + result.stderr
    actions = _witness(tmp_path)["actions"]
    assert [action["kind"] for action in actions] == [
        "stop_service",
        "disable_service",
        "mask_service",
    ]
    assert all(action["attempted"] is True and action["succeeded"] is True for action in actions)
    assert (
        _witness(tmp_path)["operator_notification"]["status"] == "quarantine_correction_witnessed"
    )


def test_enforce_reapplies_containment_when_process_is_running(tmp_path: Path) -> None:
    commands = _base_commands(
        process_stdout="4815 python -m agents.hapax_daimonion\n",
        process_returncode=0,
    )
    commands.extend(
        [
            _entry(["systemctl", "--user", "stop", SERVICE]),
            _entry(["systemctl", "--user", "disable", SERVICE]),
            _entry(["systemctl", "--user", "mask", SERVICE]),
        ]
    )

    result = _run(tmp_path, commands, enforce=True)

    assert result.returncode == 0, result.stdout + result.stderr
    witness = _witness(tmp_path)
    assert witness["process"]["running"] is True
    assert witness["process"]["matches"] == ["4815 python -m agents.hapax_daimonion"]
    assert [action["kind"] for action in witness["actions"]] == [
        "stop_service",
        "disable_service",
        "mask_service",
    ]


def test_dry_run_records_service_drift_without_correcting(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _base_commands(service_stdout="loaded\nenabled\nactive\nrunning\n"),
    )

    assert result.returncode == 2
    witness = _witness(tmp_path)
    assert "dry_run_drift_not_corrected" in witness["remaining_blockers"]
    assert [action["attempted"] for action in witness["actions"]] == [False, False, False]


def test_enforce_mutes_unmuted_source(tmp_path: Path) -> None:
    unmuted = "hapax-private-playback"
    commands = _base_commands(source_mutes={unmuted: False})
    commands.append(_entry(["pactl", "set-source-mute", unmuted, "1"]))

    result = _run(tmp_path, commands, enforce=True)

    assert result.returncode == 0, result.stdout + result.stderr
    actions = _witness(tmp_path)["actions"]
    assert actions == [
        {
            "kind": "mute_source",
            "command": ["pactl", "set-source-mute", unmuted, "1"],
            "attempted": True,
            "succeeded": True,
            "dry_run": False,
            "reason": "source_unmuted",
            "stderr": "",
        }
    ]


def test_missing_node_is_distinct_blocker_not_muted_by_name(tmp_path: Path) -> None:
    missing = "hapax-notification-private-playback"
    source_names = tuple(name for name in SOURCES if name != missing)

    result = _run(tmp_path, _base_commands(source_names=source_names), enforce=True)

    assert result.returncode == 2
    witness = _witness(tmp_path)
    assert f"missing_source:{missing}" in witness["remaining_blockers"]
    assert witness["pipewire"]["sources"][missing]["state"] == "missing"
    assert witness["actions"] == []


def test_correction_failure_remains_blocking(tmp_path: Path) -> None:
    commands = _base_commands(service_stdout="loaded\nenabled\nactive\nrunning\n")
    commands.extend(
        [
            _entry(["systemctl", "--user", "stop", SERVICE]),
            _entry(["systemctl", "--user", "disable", SERVICE], returncode=1, stderr="denied"),
            _entry(["systemctl", "--user", "mask", SERVICE]),
        ]
    )

    result = _run(tmp_path, commands, enforce=True)

    assert result.returncode == 2
    witness = _witness(tmp_path)
    assert "correction_failed:disable_service" in witness["remaining_blockers"]
    assert witness["actions"][1]["stderr"] == "denied"


def test_authorized_restore_bypass_requires_explicit_unexpired_file(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [],
        enforce=True,
        bypass={
            "authorized_restore": True,
            "approved_by": "cx-red/operator",
            "expires_at": "2100-01-01T00:00:00Z",
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    witness = _witness(tmp_path)
    assert witness["mode"] == "authorized_restore_bypass"
    assert witness["quarantine_active"] is False
    assert witness["actions"] == []
    assert witness["operator_notification"] == {
        "status": "restore_bypass_witnessed",
        "channel": "stdout_journal_and_witness_json",
        "requires_parent_attention": True,
    }
    assert "service" not in witness
