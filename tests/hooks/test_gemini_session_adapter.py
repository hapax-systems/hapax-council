"""Tests for hooks/scripts/gemini-session-adapter.sh.

25-LOC adapter wrapping a Claude Code SessionStart hook (which
writes plain text to stdout) into Gemini CLI's SessionStart JSON
shape: ``{"hookSpecificOutput": {"additionalContext": "<text>"}}``.

Tests verify the empty-vs-non-empty output paths and the
delegate-existence guard.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "gemini-session-adapter.sh"


def _make_delegate(tmp_path: Path, stdout_text: str = "") -> Path:
    """Build an executable delegate that emits ``stdout_text`` byte-for-byte
    and exits 0. The text is dropped into a sibling file and ``cat``'d so
    bash printf escape interpretation never mangles it."""
    delegate = tmp_path / "delegate.sh"
    if stdout_text:
        payload = tmp_path / "delegate-payload.txt"
        payload.write_text(stdout_text)
        delegate.write_text(f"#!/usr/bin/env bash\ncat {payload}\nexit 0\n")
    else:
        delegate.write_text("#!/usr/bin/env bash\nexit 0\n")
    delegate.chmod(0o755)
    return delegate


def _run(delegate: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HOOK), str(delegate)],
        input="",
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


# ── Delegate-existence guard ───────────────────────────────────────


class TestDelegateGuard:
    def test_missing_delegate_warns_and_exits_zero(self, tmp_path: Path) -> None:
        bad = tmp_path / "does-not-exist.sh"
        result = subprocess.run(
            ["bash", str(HOOK), str(bad)],
            input="",
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        assert result.returncode == 0
        assert "delegate not executable" in result.stderr


# ── Empty-output path ──────────────────────────────────────────────


class TestEmptyOutput:
    def test_silent_delegate_emits_no_stdout(self, tmp_path: Path) -> None:
        """When the delegate hook produces no stdout, the adapter emits
        nothing — the SessionStart JSON envelope only ships when there's
        context to inject."""
        delegate = _make_delegate(tmp_path, stdout_text="")
        result = _run(delegate)
        assert result.returncode == 0
        assert result.stdout == ""


# ── JSON-envelope wrapping ─────────────────────────────────────────


class TestEnvelopeWrapping:
    def test_plain_text_wrapped_into_session_start_envelope(self, tmp_path: Path) -> None:
        delegate = _make_delegate(tmp_path, stdout_text="alpha is online")
        result = _run(delegate)
        assert result.returncode == 0
        envelope = json.loads(result.stdout)
        assert envelope["hookSpecificOutput"]["additionalContext"] == "alpha is online"

    def test_special_chars_escaped(self, tmp_path: Path) -> None:
        """The adapter uses ``jq -Rs .`` to escape, so newlines, quotes,
        and backslashes must round-trip cleanly."""
        delegate = _make_delegate(
            tmp_path,
            stdout_text='line one\nline two\n"quoted"\nback\\slash',
        )
        result = _run(delegate)
        envelope = json.loads(result.stdout)
        assert (
            envelope["hookSpecificOutput"]["additionalContext"]
            == 'line one\nline two\n"quoted"\nback\\slash'
        )

    def test_unicode_round_trip(self, tmp_path: Path) -> None:
        delegate = _make_delegate(
            tmp_path,
            stdout_text="ᓚᘏᗢ Pipecat — Reverie",
        )
        result = _run(delegate)
        envelope = json.loads(result.stdout)
        assert envelope["hookSpecificOutput"]["additionalContext"] == "ᓚᘏᗢ Pipecat — Reverie"
