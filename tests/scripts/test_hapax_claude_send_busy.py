"""Exercise the sender at its tmux boundary without sending to a live seat."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

SEND = Path(__file__).resolve().parents[2] / "scripts/hapax-claude-send"
RULE = "─" * 60


def pane(status: str, *, output: str = "● Previous answer", composer: str = "") -> str:
    return f"{output}\n\n{status}\n\n{RULE}\n❯ {composer}\n{RULE}\n  bypass permissions on\n"


def send(
    tmp_path: Path,
    visible: str,
    *,
    history: str = "",
    message: str = "relay",
    require_ack: bool = True,
    **env,
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "visible").write_text(visible)
    (tmp_path / "history").write_text(history)
    tmux = bin_dir / "tmux"
    tmux.write_text(
        """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
p = Path(os.environ['FIXTURE_DIR'])
a = sys.argv[1:]
with (p / 'calls').open('a') as f: f.write(json.dumps(a) + '\\n')
if a[0] == 'display-message': print('claude')
elif a[0] == 'capture-pane':
    if os.environ.get('CAPTURE_FAIL'): sys.exit(1)
    if '-S' in a and a[a.index('-S') + 1] != '0':
        print((p / 'history').read_text())
    screen = (p / 'visible').read_text()
    # A record separator models tmux soft-wrap metadata: -J rejoins it.
    print(screen.replace('\\x1e', '' if '-J' in a else '\\n'))
elif a[0] == 'load-buffer': (p / 'payload').write_bytes(Path(a[-1]).read_bytes())
elif a[0] == 'send-keys' and a[-1] == 'C-m' and os.environ.get('HAPAX_CLAUDE_SEND_ACK_FILE'):
    Path(os.environ['HAPAX_CLAUDE_SEND_ACK_FILE']).write_text(
        os.environ['HAPAX_CLAUDE_SEND_ACK_TOKEN'] + '\\n')
"""
    )
    tmux.chmod(0o755)
    rte = bin_dir / "hapax-rte-state"
    rte.write_text("#!/bin/sh\necho green\n")
    rte.chmod(0o755)
    run_env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("HAPAX_CLAUDE_SEND_") and k != "HAPAX_DISPATCH_HOST"
    }
    run_env.update(
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        XDG_RUNTIME_DIR=str(tmp_path),
        FIXTURE_DIR=str(tmp_path),
        HAPAX_CLAUDE_SEND_CLEAR_DELAY="0",
        HAPAX_CLAUDE_SEND_SUBMIT_DELAY="0",
        HAPAX_CLAUDE_SEND_ACK_NUDGE_LIMIT="0",
        **env,
    )
    result = subprocess.run(
        [
            str(SEND),
            "--session",
            "alpha",
            "--transport",
            "tmux",
            *(["--require-ack"] if require_ack else []),
            "--ack-timeout",
            "0",
            "--",
            message,
        ],
        env=run_env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    calls = [json.loads(line) for line in (tmp_path / "calls").read_text().splitlines()]
    return result, calls


@pytest.mark.parametrize("old", ["✢ Photosynthesizing… (1m 1s · ↓ 4.9k tokens)", "Working..."])
def test_idle_old_spinner_in_scrollback_is_delivered(tmp_path, old):
    result, calls = send(tmp_path, pane("✻ Worked for 3m14s"), history=old)
    assert result.returncode == 0, result.stderr
    assert any(c[0] == "paste-buffer" for c in calls)


@pytest.mark.parametrize("status", ["✻ Worked for 3m14s", "Loading… (", "Loading… (22s)", ""])
def test_idle_visible_output_is_not_live_status(tmp_path, status):
    result, _ = send(tmp_path, pane(status, output="Working...\n\n● Finished answer"))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "status",
    [
        "✢ Photosynthesizing… (1m 1s · ↓ 4.9k tokens)",
        "✻ Swirling… (22s · ↓ 1.2k tokens · thinking with high effort)",
        "✽ Prestidigitating... (35s · ↓ 1.4k tokens)",
        "* Ruminating… (running UserPromptSubmit hook · 0s)",
        "✳ Re-checking… (1s · ↓ 1 token)",
        "✶ Thinking… (1s)",
        "· Working… (1s)",
        "✻ Prestidigitating… (35s · ↓ 1.4k tokens)\n  ⎿ Tip: Use /btw\n     current work",
        "✢ Photosynthesizing…\n(1m 1s · ↓ 4.9k tokens)",
        "✻ Swirling...\n  (22s · thinking with high effort)",
        "✢ Photosynthe\x1esizing… (1m 1s · ↓ 4.9k tokens)",
        "Working...",
        "esc to interrupt",
        "Messages to be submitted after next tool call",
    ],
)
def test_live_busy_refuses_before_input_mutation(tmp_path, status):
    result, calls = send(tmp_path, pane(status))
    assert result.returncode == 14, result.stderr
    assert not any(c[0] in {"load-buffer", "paste-buffer", "send-keys"} for c in calls)


def test_composer_text_is_not_status(tmp_path):
    result, _ = send(tmp_path, pane("✻ Worked for 2s", composer="Working...\nLoading… ("))
    assert result.returncode == 0, result.stderr


def test_tip_text_is_not_status(tmp_path):
    result, _ = send(tmp_path, pane("✻ Worked for 2s\n  ⎿ Tip: Working... describes an old UI"))
    assert result.returncode == 0, result.stderr


def test_non_ack_send_keeps_plain_payload_and_transport(tmp_path):
    result, calls = send(tmp_path, "unobservable", require_ack=False, message="plain relay")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "payload").read_text() == "plain relay"
    assert not any(c[0] == "capture-pane" or "-l" in c for c in calls)
    assert "-p" not in next(c for c in calls if c[0] == "paste-buffer")
    assert any(c[0] == "send-keys" and c[-1] == "C-m" for c in calls)


def test_legacy_footer_busy_indicator(tmp_path):
    result, _ = send(tmp_path, pane("") + "  esc to interrupt\n")
    assert result.returncode == 14, result.stderr


def test_busy_regex_override(tmp_path):
    result, _ = send(tmp_path, pane("CUSTOM BUSY"), HAPAX_CLAUDE_SEND_BUSY_REGEX="CUSTOM BUSY")
    assert result.returncode == 14, result.stderr


def test_explicit_allow_busy(tmp_path):
    result, calls = send(tmp_path, "unobservable", HAPAX_CLAUDE_SEND_ALLOW_BUSY="1")
    assert result.returncode == 0, result.stderr
    assert not any(c[0] == "capture-pane" for c in calls)


def test_invalid_busy_regex_refuses_before_paste(tmp_path):
    result, calls = send(tmp_path, pane(""), HAPAX_CLAUDE_SEND_BUSY_REGEX="[")
    assert result.returncode == 15, result.stderr
    assert "unset HAPAX_CLAUDE_SEND_BUSY_REGEX" in result.stderr
    assert not any(c[0] in {"load-buffer", "paste-buffer", "send-keys"} for c in calls)


def test_spinner_in_c_locale(tmp_path):
    result, _ = send(tmp_path, pane("✢ Photosynthesizing… (1m 1s · ↓ 4.9k tokens)"), LC_ALL="C")
    assert result.returncode == 14, result.stderr


@pytest.mark.parametrize(
    "visible,extra",
    [("no composer", {}), (pane(""), {"CAPTURE_FAIL": "1"}), (f"{RULE}\n❯ ", {})],
)
def test_unobservable_status_refuses_before_paste(tmp_path, visible, extra):
    result, calls = send(tmp_path, visible, **extra)
    assert result.returncode == 15, result.stderr
    assert "inspect" in result.stderr and "composer" in result.stderr
    assert not any(c[0] in {"load-buffer", "paste-buffer", "send-keys"} for c in calls)


def test_long_ack_relay_has_typed_instruction_outside_paste(tmp_path):
    message = "Long relayed instruction.\n" * 80
    result, calls = send(tmp_path, pane("✻ Worked for 2s"), message=message)
    assert result.returncode == 0, result.stderr
    typed = [c for c in calls if c[0] == "send-keys" and "-l" in c]
    assert len(typed) == 1
    assert "Follow the relayed instruction in the paste" in typed[0][-1]
    assert "ACK REQUIRED" in typed[0][-1]
    assert "printf" in typed[0][-1] and "hapax-claude-acks" in typed[0][-1]
    assert "\n" not in typed[0][-1]
    # Execute only the generated ACK command, in this test's private directory.
    ack_command = typed[0][-1].split("before substantial work: ", 1)[1].removesuffix("; ")
    ack = next((tmp_path / "hapax-claude-acks").iterdir())
    expected = ack.read_bytes()
    ack.unlink()
    subprocess.run(["bash", "-c", ack_command], check=True, timeout=5)
    assert ack.read_bytes() == expected
    paste = next(c for c in calls if c[0] == "paste-buffer")
    assert "-p" in paste
    assert calls.index(typed[0]) < calls.index(paste)
    assert (tmp_path / "payload").read_text() == message
