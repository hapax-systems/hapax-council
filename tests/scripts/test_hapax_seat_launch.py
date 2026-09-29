"""The seat cannot start with missing, stale or misdirected global instructions."""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
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
