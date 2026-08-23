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
import subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / "hooks" / "scripts" / "session-context.sh"
MARKER = "COMPACTION BOUNDARY"


def run_hook(payload: str | None, timeout: int = 60) -> str:
    """Run the hook with the given stdin payload; return stdout."""
    proc = subprocess.run(
        ["bash", str(HOOK)],
        input=payload if payload is not None else "",
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return proc.stdout


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


def test_context_still_emitted_alongside_the_marker():
    """The marker prepends; it must not replace the system context the hook exists to inject."""
    out = run_hook(json.dumps({"source": "compact", "session_id": "s1"}))
    assert MARKER in out
    assert "## System Context" in out
    assert out.index(MARKER) < out.index("## System Context")
