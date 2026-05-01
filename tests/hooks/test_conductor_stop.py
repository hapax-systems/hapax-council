"""Tests for hooks/scripts/conductor-stop.sh.

Wired Stop hook that shuts down the per-role conductor sidecar by
running `python -m agents.session_conductor stop` (with `|| true`
so any failure is swallowed). This is the simplest of the four
conductor hooks; the only branching logic is the early-exit on
missing session_id.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "conductor-stop.sh"


def _run(
    payload: dict,
    role: str = "test-stop-role",
    *,
    home: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["HAPAX_AGENT_ROLE"] = role
    if home is not None:
        env["HOME"] = str(home)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=15,
    )


# ── Early-exit paths ───────────────────────────────────────────────


class TestEarlyExits:
    def test_empty_stdin_exits_zero(self) -> None:
        result = subprocess.run(
            ["bash", str(HOOK)],
            input="",
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        assert result.returncode == 0

    def test_missing_session_id_exits_zero(self) -> None:
        """No session_id in payload → no python invocation, exit 0."""
        result = _run({"tool_name": "Stop"})
        assert result.returncode == 0
        assert result.stderr == ""


# ── Failure-tolerance ──────────────────────────────────────────────


class TestFailureTolerance:
    def test_council_dir_missing_still_exits_zero(self, tmp_path: Path) -> None:
        """Hook trails with `|| true`; even when COUNCIL_DIR doesn't exist
        the cd-and-run pipeline failure is swallowed. Hook MUST NEVER
        fail a Stop event since that could destabilise session shutdown."""
        # Override $HOME so the hook's hardcoded
        # `$HOME/projects/hapax-council` resolves to a non-existent path.
        result = _run(
            {"session_id": "stop-session-001", "tool_name": "Stop"},
            home=tmp_path,
        )
        assert result.returncode == 0
