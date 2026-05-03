"""Tests for the Hapax Gemini CLI Interactive parent dispatcher (scripts/hapax-gemini-send)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
SENDER = REPO_ROOT / "scripts" / "hapax-gemini-send"
SMOKE = REPO_ROOT / "scripts" / "hapax-gemini-smoke-send"


def _have_tmux() -> bool:
    return shutil.which("tmux") is not None


@pytest.fixture
def tmux_session(tmp_path: Path):
    """Spawn a throwaway interactive bash tmux session and tear it down."""
    if not _have_tmux():
        pytest.skip("tmux is required for hapax-gemini-send tests")

    role = f"send-{uuid.uuid4().hex[:8]}"
    name = f"hapax-gemini-{role}"
    subprocess.run(
        [
            "tmux",
            "new-session",
            "-d",
            "-s",
            name,
            "-c",
            str(tmp_path),
            "bash --noprofile --norc -i",
        ],
        check=True,
        timeout=10,
    )
    time.sleep(0.2)
    try:
        yield role, name
    finally:
        subprocess.run(["tmux", "kill-session", "-t", name], check=False)


def test_invalid_role_rejected() -> None:
    """Default allowlist refuses non-greek roles."""
    result = subprocess.run(
        [str(SENDER), "--session", "alpha", "--", "noop"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "invalid role" in result.stderr


def test_missing_session_rejected() -> None:
    result = subprocess.run(
        [str(SENDER), "--", "noop"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "--session is required" in result.stderr


def test_empty_message_rejected() -> None:
    env = os.environ.copy()
    env["HAPAX_GEMINI_SEND_ROLE_ALLOWLIST"] = "iota"
    result = subprocess.run(
        [str(SENDER), "--session", "iota", "--", ""],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 2


def test_unknown_transport_rejected() -> None:
    env = os.environ.copy()
    env["HAPAX_GEMINI_SEND_ROLE_ALLOWLIST"] = "iota"
    result = subprocess.run(
        [str(SENDER), "--session", "iota", "--transport", "foot", "--", "hi"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    # Only tmux is supported for the gemini interactive lane (Ink TUI)
    assert result.returncode == 2
    assert "invalid transport" in result.stderr


def test_invalid_ack_mode_rejected() -> None:
    env = os.environ.copy()
    env["HAPAX_GEMINI_SEND_ROLE_ALLOWLIST"] = "iota"
    result = subprocess.run(
        [str(SENDER), "--session", "iota", "--ack-mode", "magic", "--", "hi"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 2
    assert "invalid --ack-mode" in result.stderr


def test_no_live_session_returns_11() -> None:
    """Sending to a role with no tmux session returns the canonical not-found code."""
    env = os.environ.copy()
    env["HAPAX_GEMINI_SEND_ROLE_ALLOWLIST"] = "iota"
    result = subprocess.run(
        [
            str(SENDER),
            "--session",
            "iota",
            "--transport",
            "tmux",
            "--ack-timeout",
            "1",
            "--",
            "hi",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 11


def test_screen_idle_stability_check_clears_stale_pane(tmp_path: Path, tmux_session) -> None:
    """The 10s screen-idle wait + sentinel-ACK loop delivers the message and confirms.

    The fixture session is a plain interactive bash, so the sender's clear-input
    + paste flow lands a cat-into-ack-file command that satisfies the sentinel
    ACK. We use STABILITY_SECONDS=1 (instead of 10) to keep the test fast while
    still exercising the stability path.
    """
    role, _name = tmux_session
    ack_dir = tmp_path / "ack"
    ack_dir.mkdir()
    ack_file = ack_dir / "iota.ack"

    env = os.environ.copy()
    env["HAPAX_GEMINI_SEND_ROLE_ALLOWLIST"] = role
    # Speed: 1s stability, 1s interval — minimum exercise of the loop
    env["HAPAX_GEMINI_SEND_STABILITY_SECONDS"] = "1"
    env["HAPAX_GEMINI_SEND_STABILITY_INTERVAL"] = "1"
    env["HAPAX_GEMINI_SEND_STABILITY_TIMEOUT"] = "30"

    # Seed a stale prompt that the sender must clear
    subprocess.run(
        ["tmux", "send-keys", "-t", f"hapax-gemini-{role}", "STALE_TEXT_TO_CLEAR"],
        check=True,
    )
    time.sleep(0.5)

    result = subprocess.run(
        [
            str(SENDER),
            "--session",
            role,
            "--transport",
            "tmux",
            "--require-ack",
            "--ack-file",
            str(ack_file),
            "--ack-token",
            "smoke-ok",
            "--ack-timeout",
            "10",
            "--ack-mode",
            "sentinel",
            "--json",
            "--no-ack-instruction",
            "--",
            f"printf '%s\\n' smoke-ok > '{ack_file}'",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    payload = json.loads(result.stdout)
    assert payload["session"] == role
    assert payload["transport"] == "tmux"
    assert payload["ack_required"] == 1
    assert payload["ack_mode"] == "sentinel"

    # Verify ACK file landed
    assert ack_file.exists()
    assert ack_file.read_text().strip() == "smoke-ok"

    # Verify stale text was cleared (capture-pane shouldn't show the stale string)
    cap = subprocess.run(
        ["tmux", "capture-pane", "-t", f"hapax-gemini-{role}", "-p", "-S", "-80"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "STALE_TEXT_TO_CLEAR" not in cap.stdout


def test_jsonl_ack_finds_latest_session_file(tmp_path: Path, tmux_session) -> None:
    """The JSONL-tail ACK path picks the newest session-*.jsonl + detects the gemini event with tokens."""
    role, _name = tmux_session
    # Build a fake ~/.gemini/tmp/<friendly>/chats/ tree
    tmp_root = tmp_path / "gemini-tmp"
    chats_dir = tmp_root / f"hapax-council--{role}" / "chats"
    chats_dir.mkdir(parents=True)
    # Write an "old" baseline session file (will be ignored — newer file wins)
    old = chats_dir / "session-2026-04-01T00-00-aaaaaaaa.jsonl"
    old.write_text(
        '{"sessionId":"old","kind":"main"}\n{"id":"u","type":"user","content":[{"text":"hi"}]}\n',
    )
    # Newest session file: starts empty, baseline_count=0
    newest = chats_dir / "session-2026-05-03T00-00-bbbbbbbb.jsonl"
    newest.write_text('{"sessionId":"new","kind":"main"}\n')
    # Make sure file mtimes order correctly
    old.touch()
    time.sleep(0.05)
    newest.touch()

    env = os.environ.copy()
    env["HAPAX_GEMINI_SEND_ROLE_ALLOWLIST"] = role
    env["HAPAX_GEMINI_TMP_DIR"] = str(tmp_root)
    env["HAPAX_GEMINI_SEND_STABILITY_SECONDS"] = "0"  # skip stability for test speed

    # Spawn the sender in the background — it'll wait for jsonl ACK
    proc = subprocess.Popen(
        [
            str(SENDER),
            "--session",
            role,
            "--transport",
            "tmux",
            "--require-ack",
            "--ack-timeout",
            "10",
            "--ack-mode",
            "jsonl",
            "--no-ack-instruction",
            "--",
            "echo dispatched",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Give the sender a moment to baseline the file
    time.sleep(1.5)

    # Append a "model" event with a tokens block — simulates Gemini finishing a reply
    with newest.open("a") as f:
        f.write(
            '{"id":"g1","type":"gemini","content":"reply",'
            '"tokens":{"input":10,"output":5,"total":15},"model":"gemini-3-pro-preview"}\n'
        )

    try:
        stdout, stderr = proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        pytest.fail(f"sender did not exit; stderr={stderr.decode()!r}")

    assert proc.returncode == 0, f"stderr={stderr.decode()!r}"


def test_smoke_send_round_trip(tmp_path: Path) -> None:
    """The smoke-send script (CI harness) successfully round-trips against a throwaway tmux."""
    if not _have_tmux():
        pytest.skip("tmux is required for hapax-gemini-smoke-send")
    env = os.environ.copy()
    env["XDG_RUNTIME_DIR"] = str(tmp_path)
    role = f"smoke-{uuid.uuid4().hex[:8]}"
    result = subprocess.run(
        [str(SMOKE), role],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr={result.stderr}"
    assert "ok:" in result.stdout
