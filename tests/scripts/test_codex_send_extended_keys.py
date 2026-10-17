"""Real isolated tmux/pane effects; the composer is an offline fixture, not Codex."""

from __future__ import annotations

import importlib.util
import json
import os
import pty
import select
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SENDER = ROOT / "scripts/hapax-codex-send"
COMPOSER = ROOT / "tests/fixtures/codex/extended_keys_composer.py"
SESSION = "hapax-codex-cx-fixture"


def require_distinct_control_m(wire: bytes) -> None:
    if wire == b"\r":
        pytest.skip(
            "tmux emits CR for C-m despite the extended-keys request; "
            "CSI-u distinguishing witness unavailable on this transport"
        )
    assert wire == b"\x1b[109;5u", f"unexpected C-m bytes: {wire!r}"


def test_cr_only_transport_is_an_explicit_skip():
    with pytest.raises(pytest.skip.Exception, match="emits CR for C-m.*CSI-u"):
        require_distinct_control_m(b"\r")


def test_csi_u_transport_is_not_skipped():
    try:
        require_distinct_control_m(b"\x1b[109;5u")
    except pytest.skip.Exception as exc:
        pytest.fail(f"observed CSI-u transport was skipped: {exc}")


@pytest.mark.parametrize("wire", [b"", b"\n", b"\x1b[109;", b"\x1b[109;5u\r"])
def test_missing_or_unexpected_key_is_not_a_capability_skip(wire):
    try:
        with pytest.raises(AssertionError, match="unexpected C-m bytes"):
            require_distinct_control_m(wire)
    except pytest.skip.Exception as exc:
        pytest.fail(f"missing or unexpected key was skipped: {exc}")


def test_fixture_csi_u_bytes_do_not_submit_but_cr_does(tmp_path):
    """Pin the composer boundary without depending on a tmux version or installation."""
    master, slave = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, str(COMPOSER), str(tmp_path), "normal", "extended"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
    )
    os.close(slave)

    def read_until(needle):
        output = b""
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                output += os.read(master, 4096)
                if needle in output:
                    return output
        pytest.fail(f"fixture did not emit {needle!r}: {output!r}")

    try:
        read_until(b"Idle (fixture)\r\n\xe2\x80\xba ")
        os.write(master, b"byte-witness")
        read_until(b"byte-witness")
        os.write(master, b"\x1b[109;5u")
        assert b"Working" not in read_until(b"byte-witness")
        assert (tmp_path / "wire.bin").read_bytes() == b"byte-witness\x1b[109;5u"
        assert not (tmp_path / "submitted.json").exists()
        assert not (tmp_path / "ack").exists()
        os.write(master, b"\r")
        read_until(b"Working (fixture)\r\n\xe2\x80\xba ")
        assert (tmp_path / "wire.bin").read_bytes() == b"byte-witness\x1b[109;5u\r"
        assert json.loads((tmp_path / "submitted.json").read_text()) == "byte-witness"
        assert (tmp_path / "ack").read_text() == "fixture-token\n"
    finally:
        process.terminate()
        process.wait(timeout=5)
        os.close(master)


class Pane:
    def __init__(self, root: Path, mode: str, extended: bool):
        self.root = root
        self.tmux = shutil.which("tmux")
        if self.tmux is None:
            pytest.skip("real tmux required for extended-key transport witness")
        self.socket = root / "tmux.sock"
        self.env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(root),
            "TERM": "xterm-256color",
            "LANG": "C.UTF-8",
        }
        config = root / "tmux.conf"
        config.write_text("set -s extended-keys on\nset -s extended-keys-format csi-u\n")
        command = shlex.join(
            [sys.executable, str(COMPOSER), str(root), mode, "extended" if extended else "legacy"]
        )
        self.run("-f", str(config), "new-session", "-d", "-s", SESSION, "-x", "240", command)
        try:
            self.wait_for("Idle (fixture)")
        except BaseException:
            self.run("kill-server")
            raise
        bindir = root / "bin"
        bindir.mkdir()
        wrapper = bindir / "tmux"
        wrapper.write_text(
            "#!/bin/sh\nexec " + shlex.join([self.tmux, "-S", str(self.socket)]) + ' "$@"\n'
        )
        wrapper.chmod(0o755)
        self.env.update(
            PATH=f"{bindir}:/usr/bin:/bin",
            HAPAX_CODEX_SEND_SUBMIT_DELAY="0.1",
            HAPAX_CODEX_SEND_CLEAR_DELAY="0",
            HAPAX_CODEX_SEND_ACK_NUDGE_SECONDS="0.25",
            HAPAX_CODEX_SEND_ACK_NUDGE_LIMIT="1",
        )

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.tmux, "-S", str(self.socket), *args],
            env=self.env,
            text=True,
            capture_output=True,
            timeout=5,
            check=True,
        )

    def capture(self) -> str:
        pane = self.run("capture-pane", "-p", "-t", SESSION).stdout.rstrip()
        (self.root / "pane.txt").write_text(pane)
        return pane

    def wait_for(self, text: str) -> str:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            pane = self.capture()
            if text in pane:
                return pane
            time.sleep(0.025)
        pytest.fail(f"pane never showed {text!r}: {pane!r}")

    def wait_for_key(self, offset: int) -> bytes:
        deadline = time.monotonic() + 3
        wire = b""
        while time.monotonic() < deadline:
            wire = (self.root / "wire.bin").read_bytes()[offset:]
            if wire and (not wire.startswith(b"\x1b") or wire.endswith((b"u", b"~"))):
                return wire
            time.sleep(0.025)
        pytest.fail(f"no complete C-m key observed: {wire!r}")

    def send(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SENDER), "--session", "cx-fixture", "--transport", "tmux", *args],
            env=self.env,
            text=True,
            capture_output=True,
            timeout=8,
        )

    def ack_args(self) -> list[str]:
        return [
            "--require-ack",
            "--no-ack-instruction",
            "--ack-timeout",
            "2",
            "--ack-file",
            str(self.root / "ack"),
            "--ack-token",
            "fixture-token",
            "--json",
        ]

    def assert_submitted(self, text: str) -> None:
        pane = self.wait_for("Working (fixture)")
        assert pane.splitlines()[-1] == "\u203a", pane
        assert text not in pane
        assert json.loads((self.root / "submitted.json").read_text()) == text


@pytest.fixture
def pane_factory(tmp_path: Path):
    panes = []

    def create(mode="normal", *, extended=True):
        root = tmp_path / str(len(panes))
        root.mkdir()
        pane = Pane(root, mode, extended)
        panes.append(pane)
        return pane

    yield create
    for pane in panes:
        pane.run("kill-server")


@pytest.mark.parametrize("extended", [False, True])
def test_real_tmux_distinguishes_control_m_from_enter(pane_factory, extended):
    pane = pane_factory(extended=extended)
    pane.run("send-keys", "-t", SESSION, "-l", "wire-witness")
    pane.wait_for("wire-witness")
    offset = (pane.root / "wire.bin").stat().st_size
    pane.run("send-keys", "-t", SESSION, "C-m")
    wire = pane.wait_for_key(offset)
    if extended:
        require_distinct_control_m(wire)
        assert "wire-witness" in pane.capture()
        assert "Working" not in pane.capture()
        pane.run("send-keys", "-t", SESSION, "Enter")
    pane.assert_submitted("wire-witness")
    assert b"\r" in (pane.root / "wire.bin").read_bytes()


def test_initial_submit_clears_extended_composer(pane_factory):
    pane = pane_factory()
    result = pane.send("--", "initial-witness")
    assert result.returncode == 0, result.stderr
    pane.assert_submitted("initial-witness")


def test_ack_nudge_submits_after_initial_return_is_swallowed(pane_factory):
    pane = pane_factory("drop-first")
    result = pane.send(*pane.ack_args(), "--", "nudge-witness")
    assert result.returncode == 0, (result.stderr, pane.capture())
    pane.assert_submitted("nudge-witness")
    assert (pane.root / "wire.bin").read_bytes().count(b"\r") == 2
    assert (pane.root / "ack").read_text() == "fixture-token\n"


def test_review_wake_clears_extended_composer(pane_factory, tmp_path):
    pane = pane_factory()
    name = "codex_submit_wake_dispatch"
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts/cc-pr-review-dispatch.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    calls = []

    def send_runner(cmd):
        calls.append(cmd)
        result = subprocess.run(cmd, env=pane.env, text=True, capture_output=True, timeout=8)
        assert result.returncode == 0, result.stderr

    wake = module.auto_wake(
        {"assigned_to": "cx-fixture"},
        module.review_team.load_lens_registry(),
        {
            "task_id": "fixture-task",
            "head_sha": "a" * 40,
            "pr": 123,
            "review_team_verdict": "blocked",
            "reviewers": [],
            "escalations": [],
        },
        wake_dir=tmp_path / "wake",
        send_runner=send_runner,
    )
    assert len(calls) == 1
    assert Path(calls[0][0]) == SENDER
    assert str(wake) in calls[0][-1]
    pane.assert_submitted(calls[0][-1])


@pytest.mark.parametrize("mode", ["never-submit", "no-ack"])
def test_unobserved_ack_stays_a_timeout(pane_factory, mode):
    pane = pane_factory(mode)
    result = pane.send(*pane.ack_args(), "--", "not-acknowledged")
    assert result.returncode == 12
    assert "ack timeout" in result.stderr
    assert not result.stdout
    assert not (pane.root / "ack").exists()
    if mode == "never-submit":
        assert "not-acknowledged" in pane.capture()
        assert "Working" not in pane.capture()
    else:
        pane.assert_submitted("not-acknowledged")


def test_no_submit_preserves_composer_and_times_out(pane_factory):
    pane = pane_factory()
    result = pane.send(*pane.ack_args(), "--no-submit", "--", "draft-only")
    assert result.returncode == 12
    assert "draft-only" in pane.capture()
    assert "Working" not in pane.capture()
    assert b"\r" not in (pane.root / "wire.bin").read_bytes()
