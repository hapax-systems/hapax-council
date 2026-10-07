"""Process-level observations: no providers, network, receipts or mail mutations."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
NOW = "2026-10-07T22:00:00Z"
EPOCH = datetime.fromisoformat(NOW).timestamp()
AUDITED_RUN = """
import os, runpy, sys
def audit(event, args):
    if event == 'open':
        mode, flags = args[1:3]
        if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
            flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        ):
            raise RuntimeError('AUDIT: write attempted')
    if event in {'os.mkdir', 'os.remove', 'os.rename', 'os.rmdir', 'os.chmod',
                 'os.chown', 'os.utime', 'os.link', 'os.symlink', 'os.truncate',
                 'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'} or (
        event.startswith('socket.')
    ):
        raise RuntimeError('AUDIT: mutation/network/process attempted: ' + event)
sys.addaudithook(audit)
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
"""


def snapshot(root):
    result = {}
    for path in [root, *sorted(root.rglob("*"))]:
        info = path.lstat()
        try:
            content = (
                os.readlink(path)
                if path.is_symlink()
                else path.read_bytes()
                if stat.S_ISREG(info.st_mode)
                else None
            )
        except PermissionError:
            content = "unreadable"
        result[str(path.relative_to(root))] = (info.st_mode, info.st_mtime_ns, content)
    return result


def mail(root, name="note.md", stamp=NOW, mtime=EPOCH, box="seat"):
    directory = root / box
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f"---\ncreated_at: {stamp}\n---\nPRIVATE BODY MUST NOT APPEAR\n")
    os.utime(path, (mtime, mtime))
    return path


def ack(message, content="acked: 2026-10-07T21:59:00Z handled\n"):
    path = message.parent / "read" / message.name
    path.parent.mkdir(exist_ok=True)
    path.write_text(content)
    return path


def run_check(kind, root, *extra, env=None, explicit_root=True):
    before = snapshot(root)
    cmd = [
        sys.executable,
        "-B",
        "-c",
        AUDITED_RUN,
        str(REPO / "scripts" / f"hapax-seat-{kind}-check"),
    ]
    if explicit_root:
        cmd += ["--root", str(root)]
    cmd += ["--now", NOW, "--threshold", "60", *extra]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=15,
        env={**os.environ, "HOME": str(root / "isolated-home"), **(env or {})},
        cwd=REPO,
    )
    assert snapshot(root) == before
    assert "AUDIT:" not in result.stderr
    assert "PRIVATE BODY" not in result.stdout + result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    return result, rows


def test_skew_future_and_missing_ack_are_flagged_without_writes(tmp_path):
    mail(tmp_path, stamp="2026-10-07T22:02:00Z")
    clock, rows = run_check("clock", tmp_path)
    assert clock.returncode == 1, clock.stderr
    assert {(r["kind"], r["delta_seconds"]) for r in rows} == {
        ("mtime_discrepancy", 120),
        ("future_stamp", 120),
    }
    assert all(r["box"] == "seat" and r["file"] == "note.md" for r in rows)
    # Inbox age is the declared created_at, not the current filesystem mtime.
    mail(tmp_path, stamp="2026-10-07T21:58:00Z")
    inbox, rows = run_check("inbox", tmp_path)
    assert inbox.returncode == 1, inbox.stderr
    assert [(r["kind"], r["delta_seconds"]) for r in rows] == [("missing_read_ack", 120)]


@pytest.mark.parametrize("kind", ["clock", "inbox"])
def test_valid_ack_recent_and_threshold_boundary_are_clear(tmp_path, kind):
    ack(mail(tmp_path, "acked.md", "2026-10-07T21:58:00Z", EPOCH - 120))
    mail(tmp_path, "recent.md", "2026-10-07T21:59:30Z", EPOCH - 30)
    mail(tmp_path, "boundary.md", "2026-10-07T21:59:00Z", EPOCH - 60)
    result, rows = run_check(kind, tmp_path)
    assert result.returncode == 0, result.stderr
    assert rows == []
    summary = json.loads(result.stderr)
    assert summary["messages"] == 3
    assert summary["invalid"] == 0
    assert summary["now"] == NOW


@pytest.mark.parametrize(
    "stamp",
    [
        "2026-10-07T21:59:30Z",
        '"2026-10-07T16:59:30-05:00"',
        "20261007T215930Z",
        "20261007T2159Z",
        '"2026-10-07T21:59:30.000Z"',
    ],
)
def test_supported_aware_timestamp_shapes(tmp_path, stamp):
    mail(tmp_path, stamp=stamp, mtime=EPOCH - 30)
    result, rows = run_check("clock", tmp_path)
    assert result.returncode == 0, result.stderr
    assert not rows


@pytest.mark.parametrize("kind", ["clock", "inbox"])
@pytest.mark.parametrize(
    "content",
    [
        "no metadata\n",
        "---\ncreated_at: invalid\n---\n",
        "---\ncreated_at: 2026-10-07\n---\n",
        "---\ncreated_at: 2026-10-07T21:00:00\n---\n",
        "---\nother: value\n---\n",
        "---\ncreated_at: [bad\n---\n",
        "---\ncreated_at: 2026-10-07T22:00:00Z\n",
        "---\ncreated_at: 2026-10-07T22:00:00Z\ncreated_at: bad\n---\n",
    ],
)
def test_invalid_metadata_is_not_zero_findings(tmp_path, kind, content):
    message = mail(tmp_path)
    message.write_text(content)
    result, rows = run_check(kind, tmp_path)
    assert result.returncode == 2, result.stderr
    assert rows[0]["kind"] == "invalid_evidence"
    assert rows[0]["delta_seconds"] is None
    assert json.loads(result.stderr)["invalid"] == 1


@pytest.mark.parametrize(
    "shape",
    [
        "directory",
        "empty",
        "malformed",
        "bad-date",
        "future",
        "symlink",
        "dangling",
        "read-symlink",
        "read-file",
    ],
)
def test_invalid_twins_never_count_as_read(tmp_path, shape):
    message = mail(tmp_path, stamp="2026-10-07T21:58:00Z", mtime=EPOCH - 120)
    twin = message.parent / "read" / message.name
    if shape == "read-file":
        twin.parent.write_text("invalid")
    elif shape == "read-symlink":
        target = tmp_path / "outside"
        target.mkdir()
        (target / message.name).write_text("acked: 2026-10-07T21:59:00Z\n")
        twin.parent.symlink_to(target, target_is_directory=True)
    else:
        twin.parent.mkdir()
        if shape == "directory":
            twin.mkdir()
        elif shape in {"symlink", "dangling"}:
            twin.symlink_to(message if shape == "symlink" else tmp_path / "missing")
        else:
            twin.write_text(
                {
                    "empty": "",
                    "malformed": "handled\n",
                    "bad-date": "acked: yesterday\n",
                    "future": "acked: 2026-10-08T00:00:00Z\n",
                }[shape]
            )
    result, rows = run_check("inbox", tmp_path)
    assert result.returncode == 2, result.stderr
    assert any(r["kind"] == "invalid_evidence" and r["box"] == "seat" for r in rows)
    assert json.loads(result.stderr)["acknowledged"] == 0


@pytest.mark.parametrize("kind", ["clock", "inbox"])
def test_symlink_boxes_messages_and_fifo_are_errors(tmp_path, kind):
    message = mail(tmp_path)
    (tmp_path / "linked").symlink_to(message.parent, target_is_directory=True)
    (message.parent / "linked.md").symlink_to(message)
    os.mkfifo(message.parent / "pipe.md")
    result, rows = run_check(kind, tmp_path)
    assert result.returncode == 2, result.stderr
    assert len(rows) == 3
    assert all(r["kind"] == "invalid_evidence" for r in rows)
    assert next(r for r in rows if r["file"] == "pipe.md")["detail"] == "not_regular_file"


@pytest.mark.parametrize("kind", ["clock", "inbox"])
def test_missing_root_is_an_error(tmp_path, kind):
    result, rows = run_check(kind, tmp_path, "--root", str(tmp_path / "absent"))
    assert result.returncode == 2
    assert rows[0]["kind"] == "invalid_evidence"


@pytest.mark.parametrize("kind", ["clock", "inbox"])
def test_default_uses_declared_personal_vault(tmp_path, kind):
    root = tmp_path / "30-areas" / "hapax" / "lanebus"
    mail(root)
    result, rows = run_check(
        kind, tmp_path, explicit_root=False, env={"PERSONAL_VAULT_PATH": str(tmp_path)}
    )
    assert result.returncode == 0, result.stderr
    assert not rows
    assert json.loads(result.stderr)["root"] == str(root)


@pytest.mark.parametrize("value", ["-1", "nan", "inf"])
def test_invalid_threshold_rejected(tmp_path, value):
    result, rows = run_check("clock", tmp_path, "--threshold", value)
    assert result.returncode == 2
    assert not rows


def test_observed_clock_is_separate_from_injected_now(tmp_path):
    mail(tmp_path)
    result, rows = run_check("clock", tmp_path)
    summary = json.loads(result.stderr)
    assert summary["clock_source"] == "injected"
    assert datetime.fromisoformat(summary["observed_at"]).tzinfo is not None
    assert not rows


def test_negative_mtime_discrepancy_and_any_future_stamp(tmp_path):
    mail(tmp_path, "edited.md", mtime=EPOCH + 120)
    mail(tmp_path, "future.md", stamp="2026-10-07T22:00:01Z", mtime=EPOCH + 1)
    result, rows = run_check("clock", tmp_path)
    assert result.returncode == 1
    assert {(r["kind"], r["delta_seconds"]) for r in rows} == {
        ("mtime_discrepancy", -120),
        ("future_stamp", 1),
    }


@pytest.mark.parametrize("kind", ["clock", "inbox"])
def test_scan_boundary_and_stable_order(tmp_path, kind):
    mail(tmp_path, "z.md", "2026-10-07T21:58:00Z", box="z-seat")
    mail(tmp_path, "b.md", "2026-10-07T21:58:00Z", box="a-seat")
    mail(tmp_path, "a.md", "2026-10-07T21:58:00Z", box="a-seat")
    (tmp_path / "PROTOCOL.md").write_text("not a message")
    archive = tmp_path / "a-seat" / "archive"
    archive.mkdir()
    (archive / "nested.md").write_text("not a message")
    result, rows = run_check(kind, tmp_path)
    assert result.returncode == 1
    assert [(r["box"], r["file"]) for r in rows] == [
        ("a-seat", "a.md"),
        ("a-seat", "b.md"),
        ("z-seat", "z.md"),
    ]
    summary = json.loads(result.stderr)
    assert summary["messages"] == 3 and summary["skipped"] == 2


@pytest.mark.parametrize("kind", ["clock", "inbox"])
def test_root_symlink_is_not_followed(tmp_path, kind):
    root = tmp_path / "actual"
    mail(root)
    link = tmp_path / "link"
    link.symlink_to(root, target_is_directory=True)
    result, rows = run_check(kind, tmp_path, "--root", str(link))
    assert result.returncode == 2
    assert len(rows) == 1 and rows[0]["kind"] == "invalid_evidence"


@pytest.mark.parametrize("binding", ["relative", "~someone/vault"])
def test_bad_vault_binding_does_not_fall_back(tmp_path, binding):
    result, rows = run_check(
        "clock", tmp_path, explicit_root=False, env={"PERSONAL_VAULT_PATH": binding}
    )
    assert result.returncode == 2
    assert "next:" in result.stderr
    assert not rows


@pytest.mark.parametrize("kind", ["clock", "inbox"])
def test_unreadable_message_is_explicit_and_other_files_continue(tmp_path, kind):
    if os.geteuid() == 0:
        pytest.skip("root ignores DAC read denial")
    denied = mail(tmp_path, "denied.md")
    mail(tmp_path, "later.md", "2026-10-07T21:58:00Z")
    denied.chmod(0)
    try:
        result, rows = run_check(kind, tmp_path)
        assert result.returncode == 2
        assert rows[0]["detail"] == "PermissionError"
        assert rows[1]["file"] == "later.md"
        assert json.loads(result.stderr)["findings"] == 1
    finally:
        denied.chmod(0o600)
