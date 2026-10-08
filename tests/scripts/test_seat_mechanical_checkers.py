"""Process-level observations: no providers, network, receipts or mail mutations."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
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


def run_check(
    kind, root, *extra, env=None, explicit_root=True, observation="", now=NOW, threshold="60"
):
    before = snapshot(root)
    cmd = [
        sys.executable,
        "-B",
        "-c",
        AUDITED_RUN.replace("sys.argv = sys.argv[1:]", observation + "\nsys.argv = sys.argv[1:]"),
        str(REPO / "scripts" / f"hapax-seat-{kind}-check"),
    ]
    if explicit_root:
        cmd += ["--root", str(root)]
    if now is not None:
        cmd += ["--now", now]
    if threshold is not None:
        cmd += ["--threshold", threshold]
    cmd += extra
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
    assert "PRIVATE METADATA" not in result.stdout + result.stderr
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


@pytest.mark.parametrize("kind", ["clock", "inbox"])
def test_duplicate_valid_created_at_is_rejected(tmp_path, kind):
    message = mail(tmp_path)
    message.write_text(
        "---\ncreated_at: 2026-10-07T21:59:30Z\ncreated_at: 2026-10-07T22:00:00Z\n---\n"
    )
    os.utime(message, (EPOCH, EPOCH))
    result, rows = run_check(kind, tmp_path)
    assert result.returncode == 2, result.stderr
    assert len(rows) == 1
    assert rows[0]["kind"] == "invalid_evidence"
    assert rows[0]["detail"] == "missing_or_duplicate_created_at"
    assert rows[0]["delta_seconds"] is None
    summary = json.loads(result.stderr)
    assert summary["invalid"] == 1 and summary["findings"] == 0


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


@pytest.mark.parametrize("kind", ["clock", "inbox"])
@pytest.mark.parametrize("value", ["-1", "nan", "inf", "PRIVATE METADATA"])
def test_invalid_threshold_rejected(tmp_path, kind, value):
    result, rows = run_check(kind, tmp_path, threshold=value)
    assert result.returncode == 2
    assert not rows
    assert "threshold must be finite and nonnegative" in result.stderr
    assert "next: supply --threshold with a finite number of seconds >= 0" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("kind", ["clock", "inbox"])
@pytest.mark.parametrize("now", ["", "PRIVATE METADATA"])
def test_invalid_supplied_now_is_actionable(tmp_path, kind, now):
    result, rows = run_check(kind, tmp_path, now=now)
    assert result.returncode == 2, result.stderr
    assert not rows
    assert "invalid_timestamp" in result.stderr
    assert "next: supply --root and aware --now within UTC years 0001..9999" in result.stderr
    assert "Traceback" not in result.stderr and "ValueError" not in result.stderr
    assert len(result.stderr) < 600


@pytest.mark.parametrize("kind", ["clock", "inbox"])
@pytest.mark.parametrize("now", ["0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"])
def test_now_utc_normalization_overflow_is_actionable(tmp_path, kind, now):
    result, rows = run_check(kind, tmp_path, now=now)
    assert result.returncode == 2, result.stderr
    assert not rows
    assert "timestamp_out_of_utc_range" in result.stderr
    assert "next: supply --root and aware --now within UTC years 0001..9999" in result.stderr
    assert "Traceback" not in result.stderr and "OverflowError" not in result.stderr
    assert len(result.stderr) < 600


@pytest.mark.parametrize("kind", ["clock", "inbox"])
@pytest.mark.parametrize(
    "now,expected",
    [
        ("0001-01-01T01:00:00+01:00", "0001-01-01T00:00:00Z"),
        ("9999-12-31T22:59:59.999999-01:00", "9999-12-31T23:59:59.999999Z"),
    ],
)
def test_now_utc_normalization_representable_boundaries(tmp_path, kind, now, expected):
    result, rows = run_check(kind, tmp_path, now=now)
    assert result.returncode == 0, result.stderr
    assert not rows
    summary = json.loads(result.stderr)
    assert summary["now"] == expected
    assert summary["clock_source"] == "injected"


@pytest.mark.parametrize("kind", ["clock", "inbox"])
def test_now_overflow_exception_text_is_redacted(tmp_path, kind):
    observation = """
import datetime
class OverflowClock(datetime.datetime):
    def astimezone(self, tz=None):
        raise OverflowError('PRIVATE METADATA in normalization exception')
datetime.datetime = OverflowClock
"""
    result, rows = run_check(kind, tmp_path, observation=observation)
    assert result.returncode == 2, result.stderr
    assert not rows
    assert "timestamp_out_of_utc_range" in result.stderr
    assert "next:" in result.stderr and "Traceback" not in result.stderr


@pytest.mark.parametrize("kind", ["clock", "inbox"])
def test_system_utc_observation_is_bounded_by_invocation(tmp_path, kind):
    before = datetime.now(UTC)
    result, rows = run_check(kind, tmp_path, now=None, threshold=None)
    after = datetime.now(UTC)
    assert result.returncode == 0, result.stderr
    assert not rows
    summary = json.loads(result.stderr)
    observed = datetime.fromisoformat(summary["observed_at"])
    finished = datetime.fromisoformat(summary["finished_at"])
    assert before <= observed <= finished <= after
    assert summary["now"] == summary["observed_at"]
    assert summary["clock_source"] == "system_utc"
    assert summary["threshold_seconds"] == (60 if kind == "clock" else 2700)


@pytest.mark.parametrize(
    "kind,delta",
    [("clock", delta) for delta in [-60.25, -60, -59.75, 59.75, 60, 60.25]]
    + [("inbox", delta) for delta in [2699.75, 2700, 2700.25]],
)
def test_cli_default_thresholds_with_controlled_system_clock(tmp_path, kind, delta):
    # Freeze the clock observation, not the CLI branch or comparison. No sleeps
    # or simultaneous writer: quarter-second boundaries stay deterministic.
    fixed = datetime(2026, 10, 9, 12, tzinfo=UTC)
    observation = f"""
import datetime
class FixedClock(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        assert tz is datetime.UTC
        return cls.fromisoformat({fixed.isoformat()!r})
datetime.datetime = FixedClock
"""
    stamp = fixed if kind == "clock" else fixed - timedelta(seconds=delta)
    mtime = fixed.timestamp() - delta
    mail(tmp_path, stamp=stamp.isoformat(), mtime=mtime)
    result, rows = run_check(kind, tmp_path, now=None, threshold=None, observation=observation)
    bound = 60 if kind == "clock" else 2700
    beyond = abs(delta) > bound
    assert result.returncode == int(beyond), result.stderr
    reason = "mtime_discrepancy" if kind == "clock" else "missing_read_ack"
    assert [(row["kind"], row["delta_seconds"]) for row in rows] == (
        [(reason, delta)] if beyond else []
    )
    summary = json.loads(result.stderr)
    assert summary["threshold_seconds"] == bound
    assert summary["clock_source"] == "system_utc"
    assert summary["now"] == summary["observed_at"] == fixed.isoformat().replace("+00:00", "Z")
    assert summary["messages"] == 1 and summary["invalid"] == 0
    assert summary["findings"] == int(beyond)


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


@pytest.mark.parametrize("delta", [-60.25, -60, 60, 60.25])
def test_clock_strict_threshold_both_signs(tmp_path, delta):
    mail(tmp_path, mtime=EPOCH - delta)
    result, rows = run_check("clock", tmp_path)
    beyond = abs(delta) > 60
    assert result.returncode == int(beyond), result.stderr
    assert [(row["kind"], row["delta_seconds"]) for row in rows] == (
        [("mtime_discrepancy", delta)] if beyond else []
    )
    summary = json.loads(result.stderr)
    assert summary["invalid"] == 0 and summary["findings"] == int(beyond)


def assert_invalid_then_later_finding(result, rows, kind, detail):
    assert result.returncode == 2, result.stderr
    assert [(row["file"], row["kind"]) for row in rows] == [
        ("bad.md", "invalid_evidence"),
        ("later.md", "mtime_discrepancy" if kind == "clock" else "missing_read_ack"),
    ]
    assert rows[0]["box"] == "seat" and rows[0]["detail"] == detail
    assert rows[0]["delta_seconds"] is None
    assert rows[1]["delta_seconds"] == (-120 if kind == "clock" else 120)
    summary = json.loads(result.stderr)
    assert summary["messages"] == 2
    assert summary["invalid"] == 1 and summary["findings"] == 1
    assert summary["acknowledged"] == 0


@pytest.mark.parametrize("kind", ["clock", "inbox"])
def test_nested_yaml_is_invalid_and_scan_continues(tmp_path, kind):
    message = mail(tmp_path, "bad.md")
    message.write_text(
        f"---\ncreated_at: {NOW}\nother: " + "[" * 1000 + "0" + "]" * 1000 + "\n---\nPRIVATE BODY\n"
    )
    mail(tmp_path, "later.md", "2026-10-07T21:58:00Z")
    result, rows = run_check(kind, tmp_path)
    assert_invalid_then_later_finding(result, rows, kind, "RecursionError")


@pytest.mark.parametrize("kind", ["clock", "inbox"])
@pytest.mark.parametrize("shape", ["sequence", "mapping", "nested", "cycle", "aggregate"])
def test_yaml_merge_resources_are_bounded_before_construction(tmp_path, kind, shape):
    lines = [f"created_at: {NOW}", "a0: &a0 {v: 1}"]
    for index in range(1, 25):
        alias = f"*a{index - 1}"
        merges = f"<<: [{alias}, {alias}]" if shape != "mapping" else f"<<: {alias}, <<: {alias}"
        lines.append(f"a{index}: &a{index} {{{merges}}}")
    if shape == "nested":
        lines = [lines[0], "other:", "  - nested:"] + ["      " + line for line in lines[1:]]
    elif shape == "cycle":
        lines = [lines[0], "other: &loop {<<: *loop}"]
    elif shape == "aggregate":
        # Each chain fits on its own; their combined flattened mappings do not.
        chain = lines[1:16]
        lines = [lines[0], *chain, *(line.replace("a", "b") for line in chain)]
    message = mail(tmp_path, "bad.md")
    message.write_text("---\n" + "\n".join(lines) + "\n---\nPRIVATE BODY\n")
    mail(tmp_path, "later.md", "2026-10-07T21:58:00Z")
    result, rows = run_check(
        kind,
        tmp_path,
        observation="import resource\nresource.setrlimit(resource.RLIMIT_AS, (128 << 20, 128 << 20))",
    )
    assert_invalid_then_later_finding(
        result,
        rows,
        kind,
        "yaml_merge_cycle" if shape == "cycle" else "yaml_merge_expansion_limit",
    )
    assert rows[0]["next_action"] == (
        "Inspect the message header or read-ack format locally; "
        "rerun after an authorized correction."
    )


@pytest.mark.parametrize("kind", ["clock", "inbox"])
@pytest.mark.parametrize(
    "metadata",
    [
        "base: &base {v: 1}\nother: {<<: *base, own: 2}",
        "base: &base {v: 1}\nother: {<<: [*base, *base]}",
        "base: &base {v: 1}\nother: [*base, *base]",
        "other: &loop [*loop]",
        "other: {'<<': normal-string-key}",
        "\n".join(
            ["a0: &a0 {v: 1}"]
            + [f"a{i}: &a{i} {{<<: [*a{i - 1}, *a{i - 1}]}}" for i in range(1, 15)]
        ),
    ],
)
def test_bounded_yaml_metadata_remains_compatible(tmp_path, kind, metadata):
    message = mail(tmp_path)
    message.write_text(f"---\ncreated_at: {NOW}\n{metadata}\n---\nPRIVATE BODY\n")
    os.utime(message, (EPOCH, EPOCH))
    result, rows = run_check(kind, tmp_path)
    assert result.returncode == 0, result.stderr
    assert rows == []
    assert json.loads(result.stderr)["invalid"] == 0


@pytest.mark.parametrize("kind", ["clock", "inbox"])
@pytest.mark.parametrize("merge", ["<<: 42", "<<: [42]", "<<: [broken"])
def test_malformed_yaml_merge_keeps_diagnostics(tmp_path, kind, merge):
    mail(tmp_path, "bad.md").write_text(f"---\ncreated_at: {NOW}\nother: {{{merge}}}\n---\n")
    mail(tmp_path, "later.md", "2026-10-07T21:58:00Z")
    result, rows = run_check(kind, tmp_path)
    assert_invalid_then_later_finding(result, rows, kind, "yaml_error")


@pytest.mark.parametrize("kind,receipt", [("clock", False), ("inbox", False), ("inbox", True)])
@pytest.mark.parametrize("detail", ["metadata_too_large", "invalid_utf8"])
def test_bounded_metadata_errors_continue(tmp_path, kind, receipt, detail):
    message = mail(tmp_path, "bad.md")
    target = ack(message) if receipt else message
    if detail == "metadata_too_large":
        prefix = b"acked: " if receipt else f"---\ncreated_at: {NOW}\nother: ".encode()
        target.write_bytes(prefix + b"x" * 65537 + b"\n---\nPRIVATE BODY\n")
    else:
        prefix = b"acked: " if receipt else b"---\ncreated_at: "
        target.write_bytes(prefix + b"\xff PRIVATE METADATA\n---\nPRIVATE BODY\n")
    mail(tmp_path, "later.md", "2026-10-07T21:58:00Z")
    result, rows = run_check(kind, tmp_path)
    assert_invalid_then_later_finding(result, rows, kind, detail)


@pytest.mark.parametrize("kind,receipt", [("clock", False), ("inbox", False), ("inbox", True)])
@pytest.mark.parametrize("phase", ["open_descriptor", "path_replaced"])
def test_changed_metadata_observations_continue(tmp_path, kind, receipt, phase):
    message = mail(tmp_path, "bad.md")
    target = ack(message) if receipt else message
    mail(tmp_path, "later.md", "2026-10-07T21:58:00Z")
    # Inject only a stat observation, after the process audit is installed. The
    # real fixture remains byte/mode/mtime identical; no timed writer or race.
    observation = f"""
from types import SimpleNamespace
target = {str(target)!r}
phase = {phase!r}
real_fstat, real_stat = os.fstat, os.stat
seen = 0
def changed(info, field):
    fields = {{key: getattr(info, key) for key in dir(info) if key.startswith('st_')}}
    fields[field] += 1
    return SimpleNamespace(**fields)
def observed_fstat(fd):
    global seen
    info = real_fstat(fd)
    if phase == 'open_descriptor' and os.readlink('/proc/self/fd/' + str(fd)) == target:
        seen += 1
        if seen == 2:
            return changed(info, 'st_mtime_ns')
    return info
def observed_stat(path, *args, **kwargs):
    info = real_stat(path, *args, **kwargs)
    parent = kwargs.get('dir_fd')
    if parent is not None and path == 'bad.md':
        if os.readlink('/proc/self/fd/' + str(parent)) + '/' + path == target:
            if phase == 'path_replaced':
                return changed(info, 'st_ino')
            if seen == 2:
                return changed(info, 'st_mtime_ns')
    return info
os.fstat, os.stat = observed_fstat, observed_stat
"""
    result, rows = run_check(kind, tmp_path, observation=observation)
    assert_invalid_then_later_finding(result, rows, kind, "changed_during_read")
    assert rows[0]["next_action"] == (
        "Rerun when the message or receipt is stable; this scan cannot establish its state."
    )


@pytest.mark.parametrize("kind", ["clock", "inbox"])
@pytest.mark.parametrize("category", ["unavailable", "malformed"])
def test_invalid_evidence_has_bounded_next_action(tmp_path, kind, category):
    if category == "unavailable":
        result, rows = run_check(kind, tmp_path, "--root", str(tmp_path / "absent"))
        expected = "Check the declared root, path type and read permissions; rerun when available."
    else:
        mail(tmp_path).write_text('---\ncreated_at: "PRIVATE METADATA\n---\nPRIVATE BODY\n')
        result, rows = run_check(kind, tmp_path)
        expected = (
            "Inspect the message header or read-ack format locally; "
            "rerun after an authorized correction."
        )
    assert result.returncode == 2
    assert len(rows) == 1 and rows[0]["kind"] == "invalid_evidence"
    assert rows[0]["next_action"] == expected
    assert json.loads(result.stderr)["invalid"] == 1


@pytest.mark.parametrize("kind", ["clock", "inbox"])
def test_parser_exception_text_is_never_emitted(tmp_path, kind):
    mail(tmp_path, "bad.md")
    mail(tmp_path, "later.md", "2026-10-07T21:58:00Z")
    observation = """
import yaml
real_compose = yaml.compose
def observed_compose(*args, **kwargs):
    yaml.compose = real_compose
    raise yaml.YAMLError('PRIVATE METADATA in parser exception')
yaml.compose = observed_compose
"""
    result, rows = run_check(kind, tmp_path, observation=observation)
    assert_invalid_then_later_finding(result, rows, kind, "yaml_error")
