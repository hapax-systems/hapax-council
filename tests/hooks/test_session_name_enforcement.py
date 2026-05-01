"""Tests for hooks/scripts/session-name-enforcement.sh.

99-LOC PreToolUse hook that blocks Bash commands referencing a
session name outside the governance-approved set
(``alpha beta gamma delta epsilon``). Greek-letter names beyond that
set (zeta, eta, theta, iota, kappa, lambda, mu, nu, xi, omicron,
sigma, tau, upsilon, phi, chi, psi, omega) are explicitly denied
when they appear:

- as ``session=<name>`` / ``--session <name>`` / ``-s <name>`` flags,
- in worktree slot dirs ``hapax-council--<name>/``,
- as the immediate arg to ``session-context.sh`` / ``hapax-whoami``
  / ``hapax-session`` / ``claude-session``,
- as filenames ``session-<name>.sh`` or ``<name>-session.sh``.

The hook is currently NOT wired in /home/hapax/.claude/settings.json
(per the audit script), but the logic + invariant are part of the
governance task #152 spec; this test suite documents the contract
for when it gets reactivated.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "session-name-enforcement.sh"


def _run(payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def _bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


# ── Wrong-tool path ────────────────────────────────────────────────


class TestToolGating:
    def test_edit_tool_silent(self) -> None:
        result = _run({"tool_name": "Edit", "tool_input": {"file_path": "x"}})
        assert result.returncode == 0
        assert result.stderr == ""


# ── Approved session names pass ────────────────────────────────────


class TestApprovedNames:
    def test_session_alpha_silent(self) -> None:
        result = _run(_bash("hapax-claude-send --session alpha -- 'msg'"))
        assert result.returncode == 0

    def test_session_beta_silent(self) -> None:
        result = _run(_bash("--session beta"))
        assert result.returncode == 0

    def test_session_gamma_silent(self) -> None:
        result = _run(_bash("--session gamma"))
        assert result.returncode == 0

    def test_session_delta_silent(self) -> None:
        result = _run(_bash("--session delta"))
        assert result.returncode == 0

    def test_session_epsilon_silent(self) -> None:
        result = _run(_bash("--session epsilon"))
        assert result.returncode == 0


# ── Unapproved session names blocked in flag form ──────────────────


class TestUnapprovedFlagForms:
    def test_double_dash_session_zeta_blocked(self) -> None:
        result = _run(_bash("hapax-claude-send --session zeta -- 'msg'"))
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr
        assert "zeta" in result.stderr.lower()

    def test_session_equals_eta_blocked(self) -> None:
        result = _run(_bash("foo session=eta"))
        assert result.returncode == 2

    def test_dash_s_theta_blocked(self) -> None:
        result = _run(_bash("hapax-tool -s theta"))
        assert result.returncode == 2

    def test_session_iota_via_session_context_blocked(self) -> None:
        result = _run(_bash("session-context.sh iota"))
        assert result.returncode == 2


# ── Unapproved names in path/filename form ─────────────────────────


class TestUnapprovedPathForms:
    def test_worktree_slot_kappa_blocked(self) -> None:
        result = _run(_bash("ls hapax-council--kappa/"))
        assert result.returncode == 2
        assert "kappa" in result.stderr.lower()

    def test_filename_session_lambda_blocked(self) -> None:
        result = _run(_bash("bash session-lambda.sh"))
        assert result.returncode == 2

    def test_filename_omega_session_blocked(self) -> None:
        result = _run(_bash("bash omega-session.sh"))
        assert result.returncode == 2


# ── False-positive shield ──────────────────────────────────────────


class TestFalsePositiveShield:
    def test_quoted_unapproved_name_silent(self) -> None:
        """Quoted strings are stripped before matching, so an echo of
        a Greek letter inside quotes does NOT trigger the gate."""
        result = _run(_bash("echo 'zeta is the sixth Greek letter'"))
        assert result.returncode == 0

    def test_double_quoted_unapproved_name_silent(self) -> None:
        result = _run(_bash('echo "zeta in greek"'))
        assert result.returncode == 0

    def test_substring_match_silent(self) -> None:
        """An unapproved name as a substring of an unrelated word does
        NOT trigger the gate (word-boundary anchored matching)."""
        result = _run(_bash("ls zetafoo bar"))
        assert result.returncode == 0
