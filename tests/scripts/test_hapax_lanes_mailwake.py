"""Exercise the actual shell loop with isolated mailboxes and a fake tmux on PATH."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/hapax-lanes-mailwake"
UNIT = ROOT / "systemd/units/hapax-lanes-mailwake.service"

FAKE_TMUX = r"""
import json, os, signal, sys, time
from pathlib import Path
root = Path(os.environ["FAKE_ROOT"])
cfg = json.loads((root / "config.json").read_text())
a = sys.argv[1:]
target = a[a.index("-t") + 1] if "-t" in a else "estate"
with (root / "calls.jsonl").open("a") as f:
    f.write(json.dumps({"args": a, "at": time.monotonic()}) + "\n")
if a[0] == "list-sessions":
    p = root / "cycles"
    n = int(p.read_text()) + 1 if p.exists() else 0
    p.write_text(str(n))
    if n == 1:
        for mailbox, names in cfg.get("mail", {}).items():
            d = root / "bus" / mailbox
            d.mkdir(parents=True, exist_ok=True)
            for name in names:
                (d / name).write_text("---\npriority: p0\n---\nRead this.\n")
    if (root / "heartbeat").exists():
        with (root / "heartbeats.jsonl").open("a") as f:
            f.write((root / "heartbeat").read_text())
    if cfg.get("hang_list") and n:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(60)
    if cfg.get("fail_list") and n:
        sys.exit(1)
    print("\n".join(cfg["targets"]))
    sys.exit(0)
key = target.lstrip("=")
if key.startswith("%"):
    key = cfg["targets"][0 if key == "%999" else int(key[1:]) - 100]
index = cfg["targets"].index(key)
bad = cfg.get("bad", {}) if index == 0 else {}
if bad.get("hang") == a[0] and (a[0] != "send-keys" or "-l" in a):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(60)
if bad.get("fail") == a[0]:
    sys.exit(1)
paste = root / ("paste-" + str(index))
if a[0] == "list-panes":
    command = bad.get("command", "codex" if key.startswith("hapax-fugu-") else "kimi-code")
    ident = "%999" if paste.exists() and bad.get("replace") else "%" + str(index + 100)
    print(f"{ident}|{command}|2|5|{bad.get('mode', 0)}")
    if bad.get("multiple"):
        print("%999|bash|0|0|0")
elif a[0] == "capture-pane":
    text = paste.read_text() if paste.exists() else bad.get("input", "")
    if paste.exists() and bad.get("interfere"):
        text += " user typed something"
    if key.startswith("hapax-fugu-") or bad.get("command") == "bash":
        print("ready\n\n› " + text + "\n\n")
    elif bad.get("multiline"):
        print("ready\n ╭────────────╮\n │ >          │\n │ user draft │\n ╰────────────╯")
    else:
        print("ready\n ╭────────────────────────────────────────────────────────────────────╮")
        print(" │ > " + text + " │")
        print(" ╰────────────────────────────────────────────────────────────────────╯")
    print("Thinking… esc to interrupt" if bad.get("busy") or (paste.exists() and bad.get("busy_after"))
          else "Never Ask K3 thinking: max ctrl+o expand")
elif a[0] == "send-keys":
    if "-l" in a:
        paste.write_text(a[-1])
    elif a[-1] == "Enter":
        if bad.get("enter_fail"):
            paste.unlink()
            sys.exit(1)
        if bad.get("enter_hang"):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            time.sleep(60)
        with (root / "submitted.jsonl").open("a") as f:
            f.write(json.dumps({"target": key, "text": paste.read_text(), "at": time.monotonic()}) + "\n")
        paste.unlink()
else:
    raise AssertionError(a)
"""


@pytest.fixture
def run_wake(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "tmux"
    fake.write_text(f"#!{sys.executable}\n" + FAKE_TMUX)
    fake.chmod(0o755)
    # Preserve the real one-second paste/Enter gap; shorten only cycle/stability waits.
    sleeper = bindir / "sleep"
    sleeper.write_text(
        f"#!{sys.executable}\nimport sys,time\ntime.sleep(1 if sys.argv[1] == '1' else 0.01)\n"
    )
    sleeper.chmod(0o755)
    dater = bindir / "date"
    dater.write_text(
        f"#!{sys.executable}\nimport os,sys\nfrom pathlib import Path\n"
        "if sys.argv[1:] == ['+%s']:\n"
        " print(1700000000 + int((Path(os.environ['FAKE_ROOT'])/'cycles').read_text())*180)\n"
        "else:\n os.execv('/usr/bin/date', ['date', *sys.argv[1:]])\n"
    )
    dater.chmod(0o755)
    (tmp_path / "bus").mkdir()
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "FAKE_ROOT": str(tmp_path),
        "HAPAX_LANEBUS_DIR": str(tmp_path / "bus"),
        "HAPAX_MAILWAKE_HEARTBEAT": str(tmp_path / "heartbeat"),
        "HAPAX_MAILWAKE_TMUX_TIMEOUT_SECONDS": "0.15",
        "HAPAX_SESSION_PROTECTION_FILE": str(tmp_path / "protection.md"),
    }

    def run(config, cycles=2, timeout=12):
        (tmp_path / "config.json").write_text(json.dumps(config))
        command = ["bash", str(SCRIPT), "--cycles", str(cycles)]
        with subprocess.Popen(
            command,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        ) as process:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Only this test's isolated fake process group; never a real lane.
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                raise
            result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        assert result.returncode == 0, result.stderr + result.stdout
        calls = [json.loads(x) for x in (tmp_path / "calls.jsonl").read_text().splitlines()]
        submitted = tmp_path / "submitted.jsonl"
        deliveries = (
            [json.loads(x) for x in submitted.read_text().splitlines()]
            if submitted.exists()
            else []
        )
        return result, calls, deliveries

    return run, tmp_path


def config(*roles, bad=None, mail=None):
    return {
        "targets": [f"hapax-glmcp-{r}" for r in roles],
        "mail": mail or {r: ["20261012T170000Z-dev1-work.md"] for r in roles},
        "bad": bad or {},
    }


def test_heartbeat_advances_each_cycle(run_wake):
    run, path = run_wake
    _, _, deliveries = run(config("glm-steward"), cycles=3)
    heartbeat = json.loads((path / "heartbeat").read_text())
    assert heartbeat["cycle"] == 3
    assert heartbeat["targets"] == 1
    assert heartbeat["observed_at"].endswith("Z")
    observed = [json.loads(x) for x in (path / "heartbeats.jsonl").read_text().splitlines()] + [
        heartbeat
    ]
    assert [h["cycle"] for h in observed] == [1, 2, 3]
    assert all(
        a["observed_at"] < b["observed_at"]
        for a, b in zip(observed[:-1], observed[1:], strict=True)
    )
    assert len(deliveries) == 1


@pytest.mark.parametrize("command", ["list-panes", "capture-pane", "send-keys"])
def test_hung_target_does_not_wedge_next_target(run_wake, command):
    run, _ = run_wake
    result, calls, delivered = run(config("bad", "good", bad={"hang": command}))
    assert [d["target"] for d in delivered] == ["hapax-glmcp-good"]
    assert "hapax-glmcp-bad" in result.stderr and "tmux failed" in result.stderr
    assert max(c["at"] for c in calls) - min(c["at"] for c in calls) < 8


@pytest.mark.parametrize("mailbox", ["dev1", "kimi-seat"])
def test_kimi_seat_owns_only_its_mailbox(run_wake, mailbox):
    run, _ = run_wake
    cfg = {
        "targets": ["hapax-kimi-kimi-seat"],
        "mail": {mailbox: ["20261012T170000Z-dev1-work.md"]},
    }
    _, _, delivered = run(cfg)
    assert len(delivered) == (mailbox == "kimi-seat")


@pytest.mark.parametrize(
    "family,role,mailbox",
    [
        ("kimi", "kimi-desk", "kimi-desk"),
        ("glmcp", "glm-steward", "glm-steward"),
        ("fugu", "reins", "fugu-reins"),
    ],
)
def test_mailbox_mapping_and_own_mail_filter(run_wake, family, role, mailbox):
    run, _ = run_wake
    cfg = {
        "targets": [f"hapax-{family}-{role}"],
        "mail": {mailbox: [f"20261012T170000Z-{mailbox}-self.md"]},
    }
    _, calls, delivered = run(cfg)
    assert delivered == []
    assert not any(c["args"][0] == "send-keys" for c in calls)


@pytest.mark.parametrize(
    "bad",
    [
        {"busy": True},
        {"input": "unfinished draft"},
        {"multiline": True},
        {"command": "bash"},
        {"mode": 1},
        {"multiple": True},
    ],
)
def test_busy_nonempty_or_unidentified_input_is_untouched(run_wake, bad):
    run, _ = run_wake
    _, calls, delivered = run(config("bad", "good", bad=bad))
    assert [d["target"] for d in delivered] == ["hapax-glmcp-good"]
    assert not any(c["args"][0] == "send-keys" and c["args"][2] == "%100" for c in calls)


def test_paste_and_delayed_enter_submit_once(run_wake):
    run, _ = run_wake
    _, calls, delivered = run(config("glm-steward"), cycles=3)
    sends = [c for c in calls if c["args"][0] == "send-keys"]
    assert len(sends) == 2
    assert "-l" in sends[0]["args"] and sends[1]["args"][-1] == "Enter"
    assert sends[1]["at"] - sends[0]["at"] >= 1
    assert len(delivered) == 1
    assert "lanebus/glm-steward/" in delivered[0]["text"]


@pytest.mark.parametrize("bad", [{"interfere": True}, {"busy_after": True}, {"replace": True}])
def test_input_change_after_paste_never_submits_or_retries(run_wake, bad):
    run, _ = run_wake
    _, calls, delivered = run(config("bad", "good", bad=bad), cycles=3)
    assert [d["target"] for d in delivered] == ["hapax-glmcp-good"]
    bad_sends = [c for c in calls if c["args"][0] == "send-keys" and c["args"][2] == "%100"]
    assert len(bad_sends) == 1 and "-l" in bad_sends[0]["args"]


@pytest.mark.parametrize("bad", [{"hang": "send-keys"}, {"enter_fail": True}, {"enter_hang": True}])
def test_ambiguous_send_never_retries(run_wake, bad):
    run, _ = run_wake
    _, calls, delivered = run(config("bad", "good", bad=bad), cycles=3)
    assert [d["target"] for d in delivered] == ["hapax-glmcp-good"]
    pastes = [
        c
        for c in calls
        if c["args"][0] == "send-keys" and c["args"][2] == "%100" and "-l" in c["args"]
    ]
    assert len(pastes) == 1
    enters = [
        c
        for c in calls
        if c["args"][0] == "send-keys" and c["args"][2] == "%100" and c["args"][-1] == "Enter"
    ]
    assert len(enters) <= 1


def test_session_discovery_failure_still_heartbeats(run_wake):
    run, path = run_wake
    cfg = config("glm-steward")
    cfg["fail_list"] = True
    _, _, delivered = run(cfg, cycles=3)
    assert not delivered
    assert json.loads((path / "heartbeat").read_text())["cycle"] == 3


def test_protected_and_review_sessions_are_untouched(run_wake):
    run, path = run_wake
    (path / "protection.md").write_text("Protected lane: `glm-steward`\n")
    cfg = config("glm-steward", "review", "frozen", "protected", "good")
    _, calls, delivered = run(cfg)
    assert [d["target"] for d in delivered] == ["hapax-glmcp-good"]
    assert all(
        c["args"][0] == "list-sessions"
        or c["args"][c["args"].index("-t") + 1] in {"=hapax-glmcp-good", "%104"}
        for c in calls
    )


def test_unit_uses_reviewed_source_and_restarts_on_failure():
    unit = UNIT.read_text()
    assert (
        "ExecStart=%h/.cache/hapax/source-activation/worktree/scripts/hapax-lanes-mailwake" in unit
    )
    assert "Restart=on-failure" in unit
    assert "Environment=" not in unit and "ExecStartPre=" not in unit
    assert "[Install]" not in unit


@pytest.mark.parametrize(
    "family,role,mailbox",
    [
        ("kimi", "kimi-desk", "kimi-desk"),
        ("glmcp", "glm-steward", "glm-steward"),
        ("fugu", "reins", "fugu-reins"),
    ],
)
def test_each_family_receives_peer_mail(run_wake, family, role, mailbox):
    run, _ = run_wake
    cfg = {
        "targets": [f"hapax-{family}-{role}"],
        "mail": {mailbox: ["20261012T170000Z-dev1-work.md"]},
    }
    _, _, delivered = run(cfg)
    assert len(delivered) == 1
    assert f"lanebus/{mailbox}/" in delivered[0]["text"]


def test_hung_discovery_is_bounded_and_heartbeats(run_wake):
    run, path = run_wake
    cfg = config("glm-steward")
    cfg["hang_list"] = True
    result, _, delivered = run(cfg, cycles=2)
    assert not delivered
    assert "command=list-sessions" in result.stderr
    assert json.loads((path / "heartbeat").read_text())["cycle"] == 2
