"""Tests for shared Hapax coding-agent role detection."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HELPER = REPO_ROOT / "hooks" / "scripts" / "agent-role.sh"


def _bash(expr: str, *, cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    merged_env = os.environ.copy()
    merged_env.pop("HAPAX_AGENT_ROLE", None)
    merged_env.pop("HAPAX_AGENT_NAME", None)
    merged_env.pop("HAPAX_WORKTREE_ROLE", None)
    merged_env.pop("HAPAX_AGENT_SLOT", None)
    merged_env.pop("HAPAX_SESSION_ID", None)
    merged_env.pop("CLAUDE_CODE_SESSION_ID", None)
    merged_env.pop("CODEX_THREAD_ID", None)
    merged_env.pop("CODEX_THREAD_NAME", None)
    merged_env.pop("CODEX_SESSION", None)
    merged_env.pop("CODEX_SESSION_NAME", None)
    merged_env.pop("CODEX_HOME", None)
    merged_env.pop("CODEX_ROLE", None)
    merged_env.pop("CLAUDE_ROLE", None)
    merged_env.pop("HAPAX_AGENT_INTERFACE", None)
    if env:
        merged_env.update(env)
    result = subprocess.run(
        ["bash", "-c", f'. "{HELPER}"; {expr}'],
        cwd=str(cwd or REPO_ROOT),
        env=merged_env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_role_env_precedence() -> None:
    out = _bash(
        "hapax_agent_identity",
        env={
            "HAPAX_AGENT_NAME": "cx-red",
            "HAPAX_AGENT_ROLE": "epsilon",
            "CODEX_ROLE": "delta",
            "CLAUDE_ROLE": "alpha",
        },
    )
    assert out == "cx-red"


def test_codex_role_falls_back_before_claude_role() -> None:
    out = _bash("hapax_agent_identity", env={"CODEX_ROLE": "cx-blue", "CLAUDE_ROLE": "alpha"})
    assert out == "cx-blue"


def test_codex_thread_name_precedes_codex_role() -> None:
    out = _bash(
        "hapax_agent_identity",
        env={"CODEX_THREAD_NAME": "cx-green", "CODEX_ROLE": "cx-blue"},
    )
    assert out == "cx-green"


def test_claude_role_supported_for_compatibility() -> None:
    out = _bash("hapax_agent_identity", env={"CLAUDE_ROLE": "beta"})
    assert out == "beta"


def test_role_from_delta_worktree_path(tmp_path: Path) -> None:
    worktree = tmp_path / "hapax-council--delta-omg"
    worktree.mkdir()
    out = _bash("hapax_agent_worktree_role", cwd=worktree)
    assert out == "delta"


def test_codex_interface_detection() -> None:
    out = _bash("hapax_agent_interface", env={"CODEX_THREAD_NAME": "cx-red"})
    assert out == "codex"


def test_codex_thread_id_detects_codex_interface() -> None:
    out = _bash("hapax_agent_interface", env={"CODEX_THREAD_ID": "thread-123"})
    assert out == "codex"


def test_worktree_role_separate_from_codex_thread() -> None:
    out = _bash(
        "hapax_agent_identity; hapax_agent_worktree_role",
        env={"CODEX_THREAD_NAME": "cx-red", "HAPAX_WORKTREE_ROLE": "beta"},
    )
    assert out.splitlines() == ["cx-red", "beta"]


# --- Per-session identity marker (reform-identity-coherence, cluster 11) -------
# A WM-independent identity source keyed by the session id: spawners write it at
# launch and the in-session reassert command writes it, so identity resolves
# without a compositor query (hapax-whoami is dead on niri/KWin). Reader lives in
# agent-role.sh so the gate + cc-claim + whoami all share one source of truth.


def test_session_role_marker_path_uses_session_id(tmp_path: Path) -> None:
    out = _bash("hapax_session_role_marker session-abc123", env={"HOME": str(tmp_path)})
    assert out == str(tmp_path / ".cache/hapax/session-role-session-abc123")


def test_session_role_marker_defaults_to_current_session_id(tmp_path: Path) -> None:
    out = _bash(
        "hapax_session_role_marker", env={"HOME": str(tmp_path), "HAPAX_SESSION_ID": "sid-default"}
    )
    assert out == str(tmp_path / ".cache/hapax/session-role-sid-default")


def test_session_role_write_then_read(tmp_path: Path) -> None:
    out = _bash(
        "hapax_session_role_write alpha session-sid-xyz && hapax_session_role_read session-sid-xyz",
        env={"HOME": str(tmp_path)},
    )
    assert out == "alpha"


def test_session_role_read_missing_returns_nonzero(tmp_path: Path) -> None:
    out = _bash("hapax_session_role_read nope || echo MISS", env={"HOME": str(tmp_path)})
    assert out == "MISS"


def test_session_role_write_without_session_id_fails(tmp_path: Path) -> None:
    # No session id available + none passed -> write refuses (nothing to key on).
    out = _bash("hapax_session_role_write alpha || echo NOWRITE", env={"HOME": str(tmp_path)})
    assert out == "NOWRITE"


def test_session_role_marker_rejects_trailing_newline_without_normalizing(
    tmp_path: Path,
) -> None:
    out = _bash(
        "hapax_session_role_marker || echo INVALID",
        env={"HOME": str(tmp_path), "HAPAX_SESSION_ID": "session-marker-id\n"},
    )
    assert out == "INVALID"


def test_claim_key_rejects_invalid_present_session_without_legacy_downgrade() -> None:
    out = _bash(
        "hapax_agent_claim_key || echo INVALID",
        env={"CLAUDE_ROLE": "beta", "HAPAX_SESSION_ID": "session-claim-id\n"},
    )
    assert out == "INVALID"


def test_identity_resolves_from_session_marker(tmp_path: Path) -> None:
    marker = tmp_path / ".cache/hapax/session-role-session-sess-1"
    marker.parent.mkdir(parents=True)
    marker.write_text("epsilon\n")
    out = _bash(
        "hapax_agent_identity",
        cwd=tmp_path,
        env={"HOME": str(tmp_path), "HAPAX_SESSION_ID": "session-sess-1"},
    )
    assert out == "epsilon"


def test_explicit_env_role_beats_session_marker(tmp_path: Path) -> None:
    marker = tmp_path / ".cache/hapax/session-role-session-sess-2"
    marker.parent.mkdir(parents=True)
    marker.write_text("epsilon\n")
    out = _bash(
        "hapax_agent_identity",
        cwd=tmp_path,
        env={
            "HOME": str(tmp_path),
            "HAPAX_SESSION_ID": "session-sess-2",
            "CLAUDE_ROLE": "alpha",
        },
    )
    assert out == "alpha"
