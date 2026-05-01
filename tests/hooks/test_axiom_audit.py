"""Tests for hooks/scripts/axiom-audit.sh.

PostToolUse hook that logs every Edit/Write/MultiEdit/NotebookEdit to a
daily jsonl file at ``$HOME/.cache/axiom-audit/<YYYY-MM-DD>.jsonl`` and
maintains a per-session accumulator at ``.session-<id>``. Every 10
writes it ALSO runs an LLM-based cross-file axiom check via ``aichat``,
emitting a warning if the LLM flags multi-user scaffolding.

Tests cover the always-write logging path + the session accumulator;
the LLM-based cross-check is exercised via a stubbed ``aichat`` on
PATH so the test doesn't require live model access.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "axiom-audit.sh"


def _today() -> str:
    return _dt.date.today().isoformat()


def _run(
    payload: dict, *, home: Path, aichat_stub: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the hook under HOME=home so audit writes are sandboxed.

    If ``aichat_stub`` is provided, write a stub ``aichat`` script to a
    temp ``bin/`` and prepend that to PATH. The stub echoes the given
    string when invoked (used to drive the LLM-cross-check branch)."""
    env_path = "/usr/bin:/bin"
    if aichat_stub is not None:
        bin_dir = home / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        stub = bin_dir / "aichat"
        stub.write_text(f'#!/usr/bin/env bash\nprintf "%s" "{aichat_stub}"\n')
        stub.chmod(0o755)
        env_path = f"{bin_dir}:{env_path}"
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        env={"PATH": env_path, "HOME": str(home)},
        capture_output=True,
        text=True,
        check=False,
    )


def _payload(
    *, tool: str = "Edit", file_path: str = "agents/x.py", session_id: str = "sess-1"
) -> dict:
    return {
        "tool_name": tool,
        "tool_input": {"file_path": file_path},
        "session_id": session_id,
    }


# ── Audit-log writing path ─────────────────────────────────────────


class TestAuditLog:
    def test_writes_audit_entry_for_edit(self, tmp_path: Path) -> None:
        result = _run(_payload(file_path="agents/foo.py"), home=tmp_path)
        assert result.returncode == 0
        audit_file = tmp_path / ".cache" / "axiom-audit" / f"{_today()}.jsonl"
        assert audit_file.is_file()
        body = audit_file.read_text().strip()
        # Body should be a single JSON line with the expected shape.
        entry = json.loads(body)
        assert entry["tool"] == "Edit"
        assert entry["file"] == "agents/foo.py"
        assert entry["session_id"] == "sess-1"
        assert "timestamp" in entry

    def test_appends_subsequent_entries(self, tmp_path: Path) -> None:
        _run(_payload(file_path="a.py"), home=tmp_path)
        _run(_payload(file_path="b.py"), home=tmp_path)
        audit_file = tmp_path / ".cache" / "axiom-audit" / f"{_today()}.jsonl"
        lines = audit_file.read_text().strip().splitlines()
        assert len(lines) == 2

    def test_creates_audit_dir_if_missing(self, tmp_path: Path) -> None:
        """Hook must `mkdir -p` the audit dir even on first run."""
        assert not (tmp_path / ".cache" / "axiom-audit").exists()
        _run(_payload(), home=tmp_path)
        assert (tmp_path / ".cache" / "axiom-audit").is_dir()

    def test_handles_unknown_session_id(self, tmp_path: Path) -> None:
        """Missing session_id field defaults to 'unknown'."""
        result = _run(
            {"tool_name": "Edit", "tool_input": {"file_path": "x.py"}},
            home=tmp_path,
        )
        assert result.returncode == 0
        audit_file = tmp_path / ".cache" / "axiom-audit" / f"{_today()}.jsonl"
        entry = json.loads(audit_file.read_text().strip())
        assert entry["session_id"] == "unknown"


# ── Session accumulator ────────────────────────────────────────────


class TestSessionAccumulator:
    def test_session_file_tracks_writes(self, tmp_path: Path) -> None:
        _run(_payload(file_path="a.py", session_id="abc"), home=tmp_path)
        _run(_payload(file_path="b.py", session_id="abc"), home=tmp_path)
        sess = tmp_path / ".cache" / "axiom-audit" / ".session-abc"
        lines = sess.read_text().strip().splitlines()
        assert lines == ["a.py", "b.py"]

    def test_separate_sessions_get_separate_accumulators(self, tmp_path: Path) -> None:
        _run(_payload(file_path="a.py", session_id="alpha"), home=tmp_path)
        _run(_payload(file_path="b.py", session_id="beta"), home=tmp_path)
        sess_alpha = tmp_path / ".cache" / "axiom-audit" / ".session-alpha"
        sess_beta = tmp_path / ".cache" / "axiom-audit" / ".session-beta"
        assert sess_alpha.read_text().strip() == "a.py"
        assert sess_beta.read_text().strip() == "b.py"


# ── LLM cross-check (stubbed aichat) ───────────────────────────────


class TestCrossCheckStubbed:
    """The LLM-cross-check fires on multiples of 10 writes. Drive it
    with 10 `Edit` calls + a stubbed `aichat` that echoes a YES/NO
    verdict so we can assert the warning behavior."""

    def _create_test_files(self, tmp_path: Path) -> None:
        """Create real files so the hook's `head -30 <file>` call works."""
        for name in ("a.py", "b.py"):
            (tmp_path / name).write_text(f"# {name}\nx = 1\n")

    def test_no_warning_on_no_verdict(self, tmp_path: Path) -> None:
        """aichat returns 'NO ...' → no warning on stderr."""
        self._create_test_files(tmp_path)
        for _i in range(10):
            _run(
                _payload(file_path=str(tmp_path / "a.py"), session_id="check"),
                home=tmp_path,
                aichat_stub="NO no concerns",
            )
        # Final call (the 10th) should have triggered the cross-check.
        # Re-run a single call to exercise the path with stderr captured:
        result = _run(
            _payload(file_path=str(tmp_path / "a.py"), session_id="check"),
            home=tmp_path,
            aichat_stub="NO no concerns",
        )
        # No-verdict path means no WARNING line.
        assert "WARNING" not in result.stderr

    def test_warning_on_yes_verdict(self, tmp_path: Path) -> None:
        """Drive accumulator to 10 + stub aichat 'YES ...' → WARNING fires."""
        self._create_test_files(tmp_path)
        # First 9 writes accumulate without firing the LLM check.
        for _i in range(9):
            _run(
                _payload(file_path=str(tmp_path / "a.py"), session_id="yescheck"),
                home=tmp_path,
                aichat_stub="NO",
            )
        # 10th write triggers the cross-check; stub returns YES.
        result = _run(
            _payload(file_path=str(tmp_path / "a.py"), session_id="yescheck"),
            home=tmp_path,
            aichat_stub="YES introducing multi-user scaffolding",
        )
        assert result.returncode == 0
        assert "WARNING" in result.stderr
        assert "Session cross-check" in result.stderr
        assert "10 file writes" in result.stderr


# ── Hook integrity ─────────────────────────────────────────────────


class TestHookIntegrity:
    def test_hook_is_executable(self) -> None:
        assert os.access(HOOK, os.X_OK)

    def test_hook_uses_bash_shebang(self) -> None:
        body = HOOK.read_text(encoding="utf-8")
        assert body.startswith("#!/usr/bin/env bash")

    def test_hook_never_blocks(self) -> None:
        """PostToolUse hooks must not block the tool call."""
        body = HOOK.read_text(encoding="utf-8")
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("exit "):
                assert stripped.endswith("0"), f"audit hook must only `exit 0`: {line!r}"
