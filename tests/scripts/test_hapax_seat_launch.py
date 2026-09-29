"""The seat cannot start with missing, stale or misdirected global instructions."""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/hapax-seat-launch"
loader = importlib.machinery.SourceFileLoader("hapax_seat_launch", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
seat = importlib.util.module_from_spec(spec)
loader.exec_module(seat)
PREFIX = b"<!-- Generated from Council config/agent-instructions; edit the source. -->\n\n"


@pytest.fixture
def binding(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    default = tmp_path / ".codex"
    seat_home = tmp_path / ".codex-seat"
    state = tmp_path / ".config/hapax/agent-instructions"
    activated = tmp_path / ".cache/hapax/source-activation/worktree/config/agent-instructions"
    for directory in (default, seat_home, state, activated):
        directory.mkdir(parents=True)
    shared = b"# Canonical shared body\nKeep the receipt current.\n"
    generated = PREFIX + shared
    (state / "AGENTS.md").write_bytes(shared)
    (activated / "AGENTS.md").write_bytes(shared)
    (default / "AGENTS.md").write_bytes(generated)
    for name in ("auth.json", "config.toml"):
        (default / name).write_text("fixture")
        (seat_home / name).symlink_to(default / name)
    (seat_home / "AGENTS.md").symlink_to(default / "AGENTS.md")
    receipt = {
        "source_revision": "fixture",
        "observation": "filesystem_readback",
        "files": [
            {
                "binding": "shared",
                "path": str(state / "AGENTS.md"),
                "sha256": hashlib.sha256(shared).hexdigest(),
                "bytes": len(shared),
            },
            {
                "binding": "codex",
                "path": str(default / "AGENTS.md"),
                "sha256": hashlib.sha256(generated).hexdigest(),
                "bytes": len(generated),
            },
        ],
    }
    (state / "current.json").write_text(json.dumps(receipt))
    return tmp_path, {"CODEX_HOME": str(seat_home)}


def test_exact_current_binding_admitted(binding):
    home, environment = binding
    evidence = seat.verify_codex_binding(home, environment)
    assert evidence["seat_home"] == str(home / ".codex-seat")
    assert (
        evidence["shared_sha256"]
        == hashlib.sha256(
            (home / ".config/hapax/agent-instructions/AGENTS.md").read_bytes()
        ).hexdigest()
    )


def test_missing_binding_refused(binding):
    home, environment = binding
    (home / ".codex-seat/AGENTS.md").unlink()
    with pytest.raises(seat.SeatBindingError, match="missing_seat_agents_symlink"):
        seat.verify_codex_binding(home, environment)


def test_wrong_codex_home_refused(binding):
    home, environment = binding
    environment["CODEX_HOME"] = str(home / ".codex")
    with pytest.raises(seat.SeatBindingError, match="wrong_home"):
        seat.verify_codex_binding(home, environment)


def test_wrong_binding_target_refused_even_when_bytes_match(binding):
    home, environment = binding
    other = home / "other/AGENTS.md"
    other.parent.mkdir()
    other.write_bytes((home / ".codex/AGENTS.md").read_bytes())
    link = home / ".codex-seat/AGENTS.md"
    link.unlink()
    link.symlink_to(other)
    with pytest.raises(seat.SeatBindingError, match="wrong_home_seat_agents_target"):
        seat.verify_codex_binding(home, environment)


def test_stale_body_refused(binding):
    home, environment = binding
    (home / ".codex/AGENTS.md").write_bytes(PREFIX + b"# Old body\n")
    with pytest.raises(seat.SeatBindingError, match="stale_codex_body"):
        seat.verify_codex_binding(home, environment)


def test_stale_shared_body_refused(binding):
    home, environment = binding
    (home / ".config/hapax/agent-instructions/AGENTS.md").write_text("old")
    with pytest.raises(seat.SeatBindingError, match="stale_shared_body"):
        seat.verify_codex_binding(home, environment)


def test_coherently_stale_install_refused_against_active_source(binding):
    home, environment = binding
    old = b"# Prior shared body\n"
    state = home / ".config/hapax/agent-instructions"
    (state / "AGENTS.md").write_bytes(old)
    (home / ".codex/AGENTS.md").write_bytes(PREFIX + old)
    receipt_path = state / "current.json"
    receipt = json.loads(receipt_path.read_text())
    for item in receipt["files"]:
        body = old if item["binding"] == "shared" else PREFIX + old
        item["sha256"] = hashlib.sha256(body).hexdigest()
        item["bytes"] = len(body)
    receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(seat.SeatBindingError, match="stale_shared_vs_active_source"):
        seat.verify_codex_binding(home, environment)


def test_shadow_override_refused(binding):
    home, environment = binding
    (home / ".codex-seat/AGENTS.override.md").write_text("Replace instructions")
    with pytest.raises(seat.SeatBindingError, match="seat_global_override_shadows_binding"):
        seat.verify_codex_binding(home, environment)


def test_pending_instruction_install_refused(binding):
    home, environment = binding
    (home / ".config/hapax/agent-instructions/pending.json").write_text("{}")
    with pytest.raises(seat.SeatBindingError, match="instruction_install_pending"):
        seat.verify_codex_binding(home, environment)


def test_missing_binding_refuses_before_tmux(binding, monkeypatch):
    home, environment = binding
    (home / ".codex-seat/AGENTS.md").unlink()
    monkeypatch.setattr(seat.Path, "home", lambda: home)
    monkeypatch.setattr(seat.os, "environ", environment)
    monkeypatch.setattr(seat.sys, "argv", [str(SCRIPT), "codex"])

    def unexpected_tmux(*_args, **_kwargs):
        pytest.fail("tmux was called after a refused binding")

    monkeypatch.setattr(seat.subprocess, "run", unexpected_tmux)
    assert seat.main() == 2


def test_direct_inner_invocation_refuses_before_scope(binding, monkeypatch):
    home, environment = binding
    monkeypatch.setattr(seat.Path, "home", lambda: home)
    monkeypatch.setattr(seat.os, "environ", environment)
    monkeypatch.setattr(seat.sys, "argv", [str(SCRIPT), "codex", "--inner-codex"])
    monkeypatch.setattr(seat, "_raise_nofile", lambda: None)
    monkeypatch.setattr(seat.os, "chdir", lambda *_args: None)

    def unexpected_scope(*_args, **_kwargs):
        pytest.fail("direct --inner-codex reached systemd-run")

    monkeypatch.setattr(seat.os, "execvpe", unexpected_scope)
    assert seat.main() == 2


def test_outer_launch_sets_seat_home_and_inner_marker(binding, monkeypatch):
    home, environment = binding
    calls = []
    monkeypatch.setattr(seat.Path, "home", lambda: home)
    monkeypatch.setattr(seat.os, "environ", environment)
    monkeypatch.setattr(seat.sys, "argv", [str(SCRIPT), "codex"])

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1 if len(calls) == 1 else 0)

    monkeypatch.setattr(seat.subprocess, "run", fake_run)
    assert seat.main() == 0
    assert calls[0] == ["tmux", "has-session", "-t", "hapax-codex-seat"]
    launch = calls[1]
    assert launch[:5] == ["tmux", "new-session", "-d", "-s", "hapax-codex-seat"]
    assert launch[launch.index("env") + 1 : launch.index("env") + 3] == [
        f"CODEX_HOME={home / '.codex-seat'}",
        "HAPAX_SEAT_LAUNCH_INNER=hapax-codex-seat",  # pragma: allowlist secret
    ]
    assert launch[-2:] == ["codex", "--inner-codex"]


def test_live_session_refuses_before_tmux_creation(binding, monkeypatch):
    home, environment = binding
    calls = []
    monkeypatch.setattr(seat.Path, "home", lambda: home)
    monkeypatch.setattr(seat.os, "environ", environment)
    monkeypatch.setattr(seat.sys, "argv", [str(SCRIPT), "codex"])

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(seat.subprocess, "run", fake_run)
    assert seat.main() == 2
    assert calls == [["tmux", "has-session", "-t", "hapax-codex-seat"]]


def test_inner_wrong_tmux_session_refuses_before_scope(binding, monkeypatch):
    home, environment = binding
    environment.update(HAPAX_SEAT_LAUNCH_INNER="hapax-codex-seat", TMUX="socket")
    monkeypatch.setattr(seat.Path, "home", lambda: home)
    monkeypatch.setattr(seat.os, "environ", environment)
    monkeypatch.setattr(seat.sys, "argv", [str(SCRIPT), "codex", "--inner-codex"])
    monkeypatch.setattr(
        seat.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, stdout="other\n"),
    )
    monkeypatch.setattr(seat.os, "execvpe", lambda *_args: pytest.fail("scope reached"))
    assert seat.main() == 2


def test_inner_launch_checks_nofile_scope_and_identity(binding, monkeypatch):
    home, environment = binding
    environment.update(HAPAX_SEAT_LAUNCH_INNER="hapax-codex-seat", TMUX="socket")
    events = []
    monkeypatch.setattr(seat.Path, "home", lambda: home)
    monkeypatch.setattr(seat.os, "environ", environment)
    monkeypatch.setattr(seat.sys, "argv", [str(SCRIPT), "codex", "--inner-codex"])

    def fake_run(command, **_kwargs):
        events.append(("tmux", command))
        return subprocess.CompletedProcess(command, 0, stdout="hapax-codex-seat\n")

    monkeypatch.setattr(seat.subprocess, "run", fake_run)
    monkeypatch.setattr(seat.resource, "getrlimit", lambda *_args: (1024, 131072))
    monkeypatch.setattr(
        seat.resource, "setrlimit", lambda kind, limits: events.append(("nofile", kind, limits))
    )
    monkeypatch.setattr(seat.os, "chdir", lambda path: events.append(("chdir", path)))
    monkeypatch.setattr(
        seat.os,
        "execvpe",
        lambda binary, command, env: events.append(("exec", binary, command, env)),
    )
    assert seat.main() == 0
    assert events[0] == ("tmux", ["tmux", "display-message", "-p", "#{session_name}"])
    assert events[1] == ("nofile", seat.resource.RLIMIT_NOFILE, (65536, 131072))
    assert events[2] == ("chdir", home / "projects")
    _, binary, command, child_env = events[3]
    assert binary == "systemd-run"
    assert command[:4] == ["systemd-run", "--user", "--scope", "--collect"]
    assert command[4:8] == ["-p", "MemoryHigh=5G", "-p", "MemoryMax=7G"]
    assert command[8:16] == [
        "codex",
        "-s",
        "danger-full-access",
        "-a",
        "never",
        "-m",
        "gpt-6-sol",
        "-c",
    ]
    assert command[16] == "model_reasoning_effort=high"
    assert "HANDOFF-seat-claude-to-codex-20260929.md" in command[17]
    assert child_env["CODEX_HOME"] == str(home / ".codex-seat")
    assert child_env["HAPAX_AGENT_ROLE"] == "dev1-seat-codex"
    assert "HAPAX_SEAT_LAUNCH_INNER" not in child_env


def test_inner_refuses_insufficient_nofile_hard_limit(binding, monkeypatch):
    home, environment = binding
    environment.update(HAPAX_SEAT_LAUNCH_INNER="hapax-codex-seat", TMUX="socket")
    monkeypatch.setattr(seat.Path, "home", lambda: home)
    monkeypatch.setattr(seat.os, "environ", environment)
    monkeypatch.setattr(seat.sys, "argv", [str(SCRIPT), "codex", "--inner-codex"])
    monkeypatch.setattr(
        seat.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, stdout="hapax-codex-seat\n"
        ),
    )
    monkeypatch.setattr(seat.resource, "getrlimit", lambda *_args: (1024, 4096))
    monkeypatch.setattr(seat.resource, "setrlimit", lambda *_args: pytest.fail("limit changed"))
    monkeypatch.setattr(seat.os, "execvpe", lambda *_args: pytest.fail("scope reached"))
    assert seat.main() == 2
