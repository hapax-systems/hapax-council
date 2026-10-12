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
SCRIPT = ROOT / "systemd/scripts/hapax-lanes-mailwake"
UNIT = ROOT / "systemd/units/hapax-lanes-mailwake.service.md"

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
    mail = cfg.get("mail", {}) if n == 1 else {}
    mail = {**mail, **cfg.get("mail_by_cycle", {}).get(str(n), {})}
    if mail:
        for mailbox, names in mail.items():
            d = root / "bus" / mailbox
            d.mkdir(parents=True, exist_ok=True)
            for name in names:
                (d / name).write_text("---\npriority: p0\n---\nRead this.\n")
    if (root / "heartbeat").is_file():
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
text = paste.read_text() if paste.exists() else bad.get("input", "")
if paste.exists():
    if bad.get("interfere"):
        text += " user typed something"
    if bad.get("whitespace_edit") == "remove":
        text = text.replace(" ", "")
    if bad.get("whitespace_edit") == "append":
        text += " "
    if bad.get("whitespace_edit") == "insert":
        text = text.replace("Read new", "Read  new")
codex = key.startswith("hapax-fugu-") or bad.get("command") == "bash"
if a[0] == "list-panes":
    command = bad.get("command", "codex" if key.startswith("hapax-fugu-") else "kimi-code")
    ident = "%999" if paste.exists() and bad.get("replace") else "%" + str(index + 100)
    print(f"{ident}|{command}|2|{(2 if codex else 5) + len(text)}|{bad.get('mode', 0)}")
    if bad.get("multiple"):
        print("%999|bash|0|0|0")
elif a[0] == "capture-pane":
    if bad.get("wrapped") and (paste.exists() or bad.get("input")):
        if codex:
            print("ready\n\n› " + text[:12] + "\n  " + text[12:] + "\n")
        else:
            print("ready\n ╭────────────────╮\n │ > " + text[:12] + " │\n │ " + text[12:] + " │\n ╰────────────────╯")
    elif codex:
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
        if bad.get("protect_after"):
            (root / "protection.md").write_text("Protected: `" + key + "`\n")
    elif a[-1] == "Enter":
        if bad.get("enter_fail"):
            paste.unlink()
            sys.exit(1)
        if bad.get("enter_hang"):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            time.sleep(60)
        with (root / "submitted.jsonl").open("a") as f:
            f.write(json.dumps({"target": key, "text": paste.read_text(), "at": time.monotonic(),
                                "cycle": int((root / "cycles").read_text())}) + "\n")
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
        f"#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\n"
        "if sys.argv[1:] == ['+%s']:\n"
        " root=Path(os.environ['FAKE_ROOT'])\n"
        " cfg=json.loads((root/'config.json').read_text())\n"
        " n=int((root/'cycles').read_text())\n"
        " print(1700000000 + cfg.get('clock_by_cycle', {}).get(str(n), n*180))\n"
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

    def run(config, cycles=2, timeout=12, args=None, extra_env=None, expected_rc=0):
        (tmp_path / "config.json").write_text(json.dumps(config))
        command = ["bash", str(SCRIPT), *(args if args is not None else ["--cycles", str(cycles)])]
        with subprocess.Popen(
            command,
            env={**env, **(extra_env or {})},
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
        assert result.returncode == expected_rc, result.stderr + result.stdout
        call_file = tmp_path / "calls.jsonl"
        calls = (
            [json.loads(x) for x in call_file.read_text().splitlines()]
            if call_file.exists()
            else []
        )
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
        "ExecStart=%h/.cache/hapax/source-activation/worktree/systemd/scripts/hapax-lanes-mailwake"
        in unit
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


@pytest.mark.parametrize("family", ["glmcp", "fugu"])
@pytest.mark.parametrize("edit", ["remove", "append", "insert", "draft"])
def test_whitespace_changes_are_not_empty_or_our_payload(run_wake, family, edit):
    run, _ = run_wake
    bad = {"input": "   "} if edit == "draft" else {"whitespace_edit": edit}
    mailbox = "fugu-bad" if family == "fugu" else "bad"
    cfg = {
        "targets": [f"hapax-{family}-bad"],
        "bad": bad,
        "mail": {mailbox: ["20261012T170000Z-dev1-work.md"]},
    }
    _, calls, delivered = run(cfg, cycles=3)
    assert not delivered
    sends = [c for c in calls if c["args"][0] == "send-keys"]
    assert len(sends) == (0 if edit == "draft" else 1)
    assert all("-l" in c["args"] for c in sends)


@pytest.mark.parametrize("family", ["glmcp", "fugu"])
@pytest.mark.parametrize("draft", [False, True])
def test_wrapped_input_remains_untouched_or_held(run_wake, family, draft):
    run, _ = run_wake
    mailbox = "fugu-bad" if family == "fugu" else "bad"
    cfg = {
        "targets": [f"hapax-{family}-bad"],
        "bad": {"wrapped": True, "input": "a sufficiently long draft" if draft else ""},
        "mail": {mailbox: ["20261012T170000Z-dev1-work.md"]},
    }
    _, calls, delivered = run(cfg, cycles=3)
    assert not delivered
    sends = [c for c in calls if c["args"][0] == "send-keys"]
    assert len(sends) == (0 if draft else 1)
    assert all("-l" in c["args"] for c in sends)


def test_protection_added_after_paste_holds_enter(run_wake):
    run, path = run_wake
    result, calls, delivered = run(config("bad", "good", bad={"protect_after": True}), cycles=3)
    assert [d["target"] for d in delivered] == ["hapax-glmcp-good"]
    sends = [c for c in calls if c["args"][0] == "send-keys" and c["args"][2] == "%100"]
    assert len(sends) == 1 and "-l" in sends[0]["args"]
    assert "hapax-glmcp-bad" in json.loads((path / "heartbeat").read_text())["held_targets"]
    assert "reconcile uncertain submission before recovery" in result.stderr


@pytest.mark.parametrize("bad", [{"interfere": True}, {"enter_fail": True}, {"hang": "send-keys"}])
def test_persistent_hold_is_visible_every_cycle(run_wake, bad):
    run, path = run_wake
    result, _, _ = run(config("bad", "good", bad=bad), cycles=3)
    observed = [json.loads(x) for x in (path / "heartbeats.jsonl").read_text().splitlines()]
    observed.append(json.loads((path / "heartbeat").read_text()))
    assert all(h["held_targets"] == ["hapax-glmcp-bad"] for h in observed)
    assert all(h["status"] == "held" for h in observed)
    assert result.stderr.count("still held target=hapax-glmcp-bad") == 3
    assert (
        "inspect receiving pane and reconcile uncertain submission before recovery" in result.stderr
    )


@pytest.mark.parametrize("failed", [False, True])
def test_heartbeat_distinguishes_failed_discovery_from_idle(run_wake, failed):
    run, path = run_wake
    run({"targets": [], "fail_list": failed}, cycles=2)
    h = json.loads((path / "heartbeat").read_text())
    assert h["targets"] == 0
    assert h["discovery_complete"] is not failed
    assert h["status"] == ("discovery_failed" if failed else "ready")


def test_pending_mail_coalesces_until_exact_cooldown_boundary(run_wake):
    run, _ = run_wake
    cfg = config("good")
    cfg["mail_by_cycle"] = {str(n): {"good": [f"20261012T17000{n}Z-dev1-more.md"]} for n in (2, 3)}
    cfg["clock_by_cycle"] = {"1": 180, "2": 200, "3": 299, "4": 300, "5": 480}
    _, _, delivered = run(cfg, cycles=5)
    assert [d["cycle"] for d in delivered] == [1, 4]


def test_heartbeat_write_failure_exits_with_repair_action(run_wake):
    run, path = run_wake
    (path / "not-a-directory").write_text("preserve")
    result, _, _ = run(
        {"targets": []},
        expected_rc=1,
        extra_env={"HAPAX_MAILWAKE_HEARTBEAT": str(path / "not-a-directory" / "heartbeat")},
    )
    assert "heartbeat write failed; restore cache binding" in result.stderr
    assert (path / "not-a-directory").read_text() == "preserve"


@pytest.mark.parametrize("value", ["0", "-1", "11", "garbage"])
def test_invalid_timeout_is_rejected_before_tmux(run_wake, value):
    run, _ = run_wake
    result, calls, _ = run(
        {"targets": []}, expected_rc=2, extra_env={"HAPAX_MAILWAKE_TMUX_TIMEOUT_SECONDS": value}
    )
    assert "must be >0 and <=10" in result.stderr
    assert not calls


@pytest.mark.parametrize(
    "args",
    [
        ["--cycles"],
        ["--cycles", "0"],
        ["--cycles", "-1"],
        ["--cycles", "x"],
        ["--cycles", "1", "extra"],
        ["--bad", "1"],
    ],
)
def test_invalid_cycles_are_rejected_before_tmux(run_wake, args):
    run, _ = run_wake
    result, calls, _ = run({"targets": []}, args=args, expected_rc=2)
    assert "usage:" in result.stderr
    assert not calls
