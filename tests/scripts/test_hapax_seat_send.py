"""The seat sender must prove delivery across idle and queued Codex turns."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/hapax-seat-send"
loader = importlib.machinery.SourceFileLoader("hapax_seat_send", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
seat_send = importlib.util.module_from_spec(spec)
loader.exec_module(seat_send)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.after_sleep = lambda: None

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.after_sleep()


class Pane:
    def __init__(
        self, ack_path: Path, *, busy: bool = False, swallow: int = 0, defer_ack: bool = False
    ) -> None:
        self.ack_path = ack_path
        self.busy = busy
        self.swallow = swallow
        self.defer_ack = defer_ack
        self.payload = ""
        self.keys: list[str] = []
        self.pasted = False
        self.queued = False
        self.exists_result = True
        self.clock: Clock | None = None

    def exists(self, _session: str) -> bool:
        return self.exists_result

    def capture(self, _session: str) -> str:
        if self.busy:
            return "Working (3s) · esc to interrupt · tab to queue\n› "
        return f"› {self.payload}" if self.payload else "› "

    def paste(self, _session: str, payload: str) -> None:
        self.pasted = True
        self.payload = payload

    def key(self, _session: str, key: str) -> None:
        self.keys.append(key)
        if key == "Tab":
            self.queued = True
        if key != "Enter":
            return
        if self.swallow:
            self.swallow -= 1
            return
        if self.busy and not self.queued:
            return
        if self.defer_ack:
            return
        self.busy = True
        self.ack_path.write_text("fixture-token\n")

    def release_queued(self) -> None:
        if self.queued and not self.ack_path.exists():
            self.ack_path.write_text("fixture-token\n")


def test_swallowed_first_enter_is_retried_and_acknowledged(tmp_path: Path) -> None:
    """The 09-28 one-call paste/Enter failure must not be reported as delivered."""
    ack = tmp_path / "ack"
    pane = Pane(ack, swallow=1)
    clock = Clock()
    receipt = seat_send.send(
        "hapax-codex-seat",
        "Seat instruction",
        transport=pane,
        ack_path=ack,
        ack_token="fixture-token",
        timeout=15,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert receipt.mode == "idle"
    assert receipt.acknowledged
    assert pane.keys == ["Enter", "Enter"]
    assert clock.now >= 12
    assert "Seat instruction" in pane.payload


def test_swallowed_enters_timeout_as_held(tmp_path: Path) -> None:
    ack = tmp_path / "ack"
    pane = Pane(ack, swallow=2)
    clock = Clock()
    with pytest.raises(seat_send.DeliveryError, match="ack_timeout"):
        seat_send.send(
            "hapax-codex-seat",
            "Seat instruction",
            transport=pane,
            ack_path=ack,
            ack_token="fixture-token",
            timeout=15,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
    assert pane.keys == ["Enter", "Enter"]
    assert not ack.exists()


def test_busy_turn_queues_then_receives_ack(tmp_path: Path) -> None:
    ack = tmp_path / "ack"
    pane = Pane(ack, busy=True, defer_ack=True)
    clock = Clock()
    clock.after_sleep = lambda: pane.release_queued() if clock.now >= 4 else None
    receipt = seat_send.send(
        "hapax-codex-seat",
        "Queued instruction",
        transport=pane,
        ack_path=ack,
        ack_token="fixture-token",
        timeout=15,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert receipt.mode == "queued"
    assert receipt.acknowledged
    assert pane.keys == ["Tab", "Enter"]
    assert clock.now >= 4


def test_existing_composer_text_refuses_before_paste(tmp_path: Path) -> None:
    pane = Pane(tmp_path / "ack")
    pane.payload = "existing operator text"
    with pytest.raises(seat_send.DeliveryError, match="composer_not_empty"):
        seat_send.send(
            "hapax-codex-seat",
            "Instruction",
            transport=pane,
            ack_path=tmp_path / "ack",
            ack_token="fixture-token",
        )
    assert not pane.pasted


def test_queued_turn_without_ack_is_held(tmp_path: Path) -> None:
    ack = tmp_path / "ack"
    pane = Pane(ack, busy=True, defer_ack=True)
    clock = Clock()
    with pytest.raises(seat_send.DeliveryError, match="ack_timeout"):
        seat_send.send(
            "hapax-codex-seat",
            "Queued instruction",
            transport=pane,
            ack_path=ack,
            ack_token="fixture-token",
            timeout=15,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
    assert pane.keys == ["Tab", "Enter"]
    assert not ack.exists()


def test_cli_refuses_other_sessions_before_tmux() -> None:
    result = subprocess.run(
        [str(SCRIPT), "hapax-codex-cx-red", "Instruction"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 2
    assert "unsupported_seat_session" in result.stderr


def test_real_tmux_transport_uses_separate_submit_call(monkeypatch) -> None:
    calls = []

    def fake_tmux(*args, input_text=None):
        calls.append((args, input_text))
        return type("Result", (), {"returncode": 0, "stdout": ""})()

    monkeypatch.setattr(seat_send, "_tmux", fake_tmux)
    transport = seat_send.TmuxTransport()
    transport.paste("hapax-codex-seat", "Seat instruction")
    transport.key("hapax-codex-seat", "Enter")
    assert [args[0] for args, _ in calls] == [
        "load-buffer",
        "paste-buffer",
        "delete-buffer",
        "send-keys",
    ]
    assert calls[-1][0] == ("send-keys", "-t", "hapax-codex-seat", "Enter")
    assert calls[0][1] == "Seat instruction"


def test_missing_session_refuses_before_paste(tmp_path: Path) -> None:
    pane = Pane(tmp_path / "ack")
    pane.exists_result = False
    with pytest.raises(seat_send.DeliveryError, match="missing_session"):
        seat_send.send(
            "hapax-codex-seat",
            "Instruction",
            transport=pane,
            ack_path=tmp_path / "ack",
            ack_token="fixture-token",
        )
    assert not pane.pasted
