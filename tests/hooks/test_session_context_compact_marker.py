"""The SessionStart hook must mark a compaction boundary, and only a compaction boundary.

Claude Code resumes a compacted session with an agent-authored summary standing where the
record was, carrying no provenance and no confidence marker. Measured on this estate:
6,781,491 bytes compressed to 23,694 (286:1), roughly half the operator's turns surviving as
quotation with nothing marking which half. Kimi's harness warns; Claude Code does not, and the
summariser is not ours to change — so the boundary is what we can mark.

The negative direction matters as much as the positive: a marker that fires on ordinary startup
is noise injected into every session, and noise is the failure mode this whole programme is
trying not to add.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / "hooks" / "scripts" / "session-context.sh"
MARKER = "COMPACTION BOUNDARY"


def run_hook(payload: str | None, timeout: int = 60, env: dict[str, str] | None = None) -> str:
    """Run the hook with the given stdin payload; return stdout."""
    proc = subprocess.run(
        ["bash", str(HOOK)],
        input=payload if payload is not None else "",
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )
    return proc.stdout


def _path_without(tmp_path: Path, excluded: str) -> dict[str, str]:
    """A copy of the environment whose PATH resolves everything except `excluded`.

    Mirrors every executable on the real PATH into one directory and omits the named
    one. Mirroring rather than hand-picking is deliberate: this hook shells out to
    awk, cat, cut, date, df, find, gh, git, grep, head, ls, python3, realpath, sed,
    sort, stat, systemctl, tail, timeout, tr and wc, and a curated allowlist that
    misses one of them would make the hook fail for a reason unrelated to the branch
    under test — measuring the wrong thing while appearing to pass.
    """
    farm = tmp_path / "path-farm"
    farm.mkdir(exist_ok=True)
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        src_dir = Path(entry)
        if not src_dir.is_dir():
            continue
        for item in src_dir.iterdir():
            if item.name == excluded:
                continue
            link = farm / item.name
            if link.exists() or link.is_symlink():
                continue  # first match on PATH wins, as the real resolver does
            try:
                link.symlink_to(item)
            except OSError:
                pass
    env = dict(os.environ)
    env["PATH"] = str(farm)
    return env


def test_marker_present_for_compact_source():
    out = run_hook(json.dumps({"source": "compact", "session_id": "s1"}))
    assert MARKER in out
    assert "notes, not proof" in out


def test_marker_absent_for_every_other_source():
    """The negative direction: only a compaction boundary may be marked."""
    for source in ("startup", "resume", "clear", "fork"):
        out = run_hook(json.dumps({"source": source, "session_id": "s1"}))
        assert MARKER not in out, f"marker leaked into source={source}"


def test_marker_absent_when_source_missing():
    out = run_hook(json.dumps({"session_id": "s1"}))
    assert MARKER not in out


def test_hook_survives_malformed_and_empty_payloads():
    """The hook predates any stdin contract; adding one must not make it fail closed."""
    for payload in ("", "not json at all", "{", '{"source":'):
        out = run_hook(payload)
        assert "## System Context" in out, f"hook stopped emitting context for payload {payload!r}"
        assert MARKER not in out


def test_no_marker_when_jq_is_unavailable(tmp_path):
    """The compatibility branch the exit predicate names, actually exercised.

    Without jq the hook cannot read `.source`, so it must fall back to exactly the
    behaviour it had before the stdin contract existed: full context, no marker, even
    on a payload that would otherwise fire it.
    """
    env = _path_without(tmp_path, "jq")
    assert shutil.which("jq", path=env["PATH"]) is None, "farm still resolves jq"

    out = run_hook(json.dumps({"source": "compact", "session_id": "s1"}), env=env)
    assert MARKER not in out, "marker fired without jq, so .source was read some other way"
    assert "## System Context" in out, "hook stopped emitting context when jq was absent"


def test_jq_is_present_on_the_normal_path(tmp_path):
    """Guards the guard: if jq were missing normally, the test above would pass vacuously."""
    assert shutil.which("jq") is not None
    out = run_hook(json.dumps({"source": "compact", "session_id": "s1"}))
    assert MARKER in out


def test_stdin_read_is_bounded_when_the_writer_never_closes():
    """`timeout 2` bounds the read; a writer that never closes must not hang session start.

    The pipe is deliberately never closed. `subprocess.communicate()` cannot be used
    here — it closes stdin, `cat` sees EOF, and the hook returns promptly whether or
    not any bound exists, so the test would pass against an unbounded read. Verified:
    with `timeout 2` removed this assertion fails, and with it restored it passes.
    """
    started = time.monotonic()
    proc = subprocess.Popen(
        ["bash", str(HOOK)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdin is not None
    try:
        proc.stdin.write(json.dumps({"source": "compact", "session_id": "s1"}))
        proc.stdin.flush()
        # Hold the pipe open and wait for the hook to finish on its own.
        deadline = started + 25
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.2)
        elapsed = time.monotonic() - started
        exited = proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.stdin.close()
        out = proc.stdout.read() if proc.stdout else ""
        proc.wait(timeout=10)

    assert exited, f"hook never exited with stdin held open: unbounded read ({elapsed:.1f}s)"
    assert "## System Context" in out, "hook produced no context after a bounded read"


def test_transcript_path_is_supplied_when_the_payload_carries_one():
    """The marker's one concrete recovery action has to be executable.

    Naming the transcript without naming its location told the reader to consult a
    payload the hook had already consumed — an instruction with no way to follow it.
    """
    out = run_hook(
        json.dumps(
            {
                "source": "compact",
                "session_id": "s1",
                "transcript_path": "/tmp/session-xyz.jsonl",
            }
        )
    )
    assert MARKER in out
    assert "/tmp/session-xyz.jsonl" in out, "the payload's transcript path never reached the reader"


def test_transcript_sentence_omitted_when_the_payload_has_no_path():
    """Absent a path, say nothing — do not advertise a recovery route that is not there."""
    out = run_hook(json.dumps({"source": "compact", "session_id": "s1"}))
    assert MARKER in out
    assert "The full transcript is on disk" not in out


def test_the_provenance_statement_itself_is_pinned():
    """The marker's whole purpose is this claim; a reworded marker must fail loudly."""
    out = run_hook(json.dumps({"source": "compact", "session_id": "s1"}))
    assert "your own\ngenerated summary, not the record" in out
    assert "verify that\n  yourself" in out


def test_context_still_emitted_alongside_the_marker():
    """The marker prepends; it must not replace the system context the hook exists to inject."""
    out = run_hook(json.dumps({"source": "compact", "session_id": "s1"}))
    assert MARKER in out
    assert "## System Context" in out
    assert out.index(MARKER) < out.index("## System Context")
