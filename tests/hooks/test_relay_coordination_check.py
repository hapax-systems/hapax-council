"""Tests for `hooks/scripts/relay-coordination-check.sh` (AUDIT-06+26).

The existing advisory-only behavior is preserved; this test suite pins
the new BLOCKING layer that fires when a peer session yaml advertises
a `path_claims:` overlap with the current Edit/Write target.

Invokes the shell hook via subprocess against synthetic relay fixtures
under tmp_path so the operator's real `~/.cache/hapax/relay/` is never
mutated.

Decision matrix:
  - no peer claim → exit 0 (allow)
  - peer claim path != edit path, no prefix → exit 0
  - peer claim path == edit path, claim still active → exit 1 (BLOCK)
  - peer claim path is directory, edit is in subtree → exit 1 (BLOCK)
  - peer claim with `until` in the past → skipped silently → exit 0
  - HAPAX_INCIDENT=1 → bypass even when blocked → exit 0
  - HAPAX_RELAY_CHECK_HOOK=0 → bypass entirely → exit 0
  - Self-claim does not block self → exit 0
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "relay-coordination-check.sh"


def _iso_utc(offset_minutes: int = 0) -> str:
    """ISO-8601 UTC timestamp offset by N minutes from now."""
    return (datetime.now(UTC) + timedelta(minutes=offset_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_peer_yaml(
    relay_dir: Path,
    peer: str,
    *,
    claims: list[dict] | None = None,
    session_status: str = "ACTIVE — fixture",
) -> Path:
    """Build a minimal peer yaml. claims is a list of {path, until, reason}."""
    relay_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = relay_dir / f"{peer}.yaml"
    body = [
        f"session: {peer}",
        f'session_status: "{session_status}"',
    ]
    if claims:
        body.append("path_claims:")
        for c in claims:
            body.append(f"  - path: {c['path']}")
            if "until" in c:
                body.append(f"    until: {c['until']}")
            if "reason" in c:
                body.append(f'    reason: "{c["reason"]}"')
    yaml_path.write_text("\n".join(body) + "\n")
    return yaml_path


def _run_hook(
    *,
    relay_dir: Path,
    file_path: str,
    self_session: str = "beta",
    role_env: str = "CLAUDE_ROLE",
    incident_bypass: bool = False,
    full_bypass: bool = False,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the hook with synthesized stdin + env."""
    payload = {
        "tool_name": "Edit",
        "tool_input": {"file_path": file_path},
    }
    env = os.environ.copy()
    # Point HOME to a directory whose .cache/hapax/relay = relay_dir.
    fake_home = relay_dir.parent.parent.parent  # tmp_path
    env["HOME"] = str(fake_home)
    env.pop("HAPAX_AGENT_NAME", None)
    env.pop("HAPAX_AGENT_ROLE", None)
    env.pop("HAPAX_WORKTREE_ROLE", None)
    env.pop("CODEX_THREAD_NAME", None)
    env.pop("CODEX_ROLE", None)
    env.pop("CLAUDE_ROLE", None)
    env[role_env] = self_session
    if incident_bypass:
        env["HAPAX_INCIDENT"] = "1"
    if full_bypass:
        env["HAPAX_RELAY_CHECK_HOOK"] = "0"
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd or REPO_ROOT),
    )


# ── Fixture: a tmp_path-rooted relay directory ──────────────────────


@pytest.fixture
def relay_dir(tmp_path: Path) -> Path:
    """Returns ~/.cache/hapax/relay equivalent under tmp_path."""
    return tmp_path / ".cache" / "hapax" / "relay"


# ── Decision matrix tests ────────────────────────────────────────────


def test_no_peer_claim_allows(relay_dir: Path) -> None:
    """No peer yaml has path_claims → exit 0."""
    _write_peer_yaml(relay_dir, "alpha")
    _write_peer_yaml(relay_dir, "delta")
    result = _run_hook(
        relay_dir=relay_dir,
        file_path="agents/studio_compositor/durf_source.py",
    )
    assert result.returncode == 0, f"stderr={result.stderr!r}"


def test_peer_claim_unrelated_path_allows(relay_dir: Path) -> None:
    """Peer claims a different path → exit 0."""
    _write_peer_yaml(
        relay_dir,
        "delta",
        claims=[{"path": "agents/different_file.py", "until": _iso_utc(60)}],
    )
    result = _run_hook(
        relay_dir=relay_dir,
        file_path="agents/studio_compositor/durf_source.py",
    )
    assert result.returncode == 0, f"stderr={result.stderr!r}"


def test_exact_path_claim_blocks(relay_dir: Path) -> None:
    """Peer claims the exact file → exit 1 with BLOCKED message."""
    _write_peer_yaml(
        relay_dir,
        "delta",
        claims=[
            {
                "path": "agents/studio_compositor/durf_source.py",
                "until": _iso_utc(60),
                "reason": "AUDIT-01 redaction primitive",
            }
        ],
    )
    result = _run_hook(
        relay_dir=relay_dir,
        file_path="agents/studio_compositor/durf_source.py",
    )
    assert result.returncode == 1, (
        f"Expected block; got exit {result.returncode}, stderr={result.stderr!r}"
    )
    assert "BLOCKED" in result.stderr
    assert "delta" in result.stderr
    assert "AUDIT-01" in result.stderr


def test_directory_claim_blocks_subtree(relay_dir: Path) -> None:
    """Peer claims a directory → blocks edits within its subtree."""
    _write_peer_yaml(
        relay_dir,
        "delta",
        claims=[
            {
                "path": "agents/studio_compositor",
                "until": _iso_utc(60),
                "reason": "scrim-taxonomy refresh",
            }
        ],
    )
    result = _run_hook(
        relay_dir=relay_dir,
        file_path="agents/studio_compositor/cairo_source.py",
    )
    assert result.returncode == 1, f"Expected block on subtree match; got {result.returncode}"


def test_stale_claim_skipped(relay_dir: Path) -> None:
    """Claim with `until` in the past → silently skipped → exit 0."""
    _write_peer_yaml(
        relay_dir,
        "delta",
        claims=[
            {
                "path": "agents/studio_compositor/durf_source.py",
                "until": _iso_utc(-60),  # 1h ago
                "reason": "stale claim",
            }
        ],
    )
    result = _run_hook(
        relay_dir=relay_dir,
        file_path="agents/studio_compositor/durf_source.py",
    )
    assert result.returncode == 0, f"Stale claim should not block; stderr={result.stderr!r}"


def test_incident_bypass(relay_dir: Path) -> None:
    """HAPAX_INCIDENT=1 bypasses even an active block."""
    _write_peer_yaml(
        relay_dir,
        "delta",
        claims=[
            {
                "path": "agents/studio_compositor/durf_source.py",
                "until": _iso_utc(60),
            }
        ],
    )
    result = _run_hook(
        relay_dir=relay_dir,
        file_path="agents/studio_compositor/durf_source.py",
        incident_bypass=True,
    )
    assert result.returncode == 0


def test_full_bypass(relay_dir: Path) -> None:
    """HAPAX_RELAY_CHECK_HOOK=0 short-circuits the whole hook."""
    _write_peer_yaml(
        relay_dir,
        "delta",
        claims=[
            {
                "path": "agents/studio_compositor/durf_source.py",
                "until": _iso_utc(60),
            }
        ],
    )
    result = _run_hook(
        relay_dir=relay_dir,
        file_path="agents/studio_compositor/durf_source.py",
        full_bypass=True,
    )
    assert result.returncode == 0


def test_self_claim_does_not_block_self(relay_dir: Path) -> None:
    """A session's own claim doesn't block its own edits."""
    _write_peer_yaml(
        relay_dir,
        "beta",  # self
        claims=[
            {
                "path": "agents/studio_compositor/durf_source.py",
                "until": _iso_utc(60),
                "reason": "beta's own work",
            }
        ],
    )
    result = _run_hook(
        relay_dir=relay_dir,
        file_path="agents/studio_compositor/durf_source.py",
        self_session="beta",
    )
    assert result.returncode == 0


def test_codex_role_self_claim_does_not_block_self(relay_dir: Path) -> None:
    """Codex cx-* thread names participate in the same identity contract."""
    _write_peer_yaml(
        relay_dir,
        "cx-red",
        claims=[
            {
                "path": "agents/studio_compositor/durf_source.py",
                "until": _iso_utc(60),
                "reason": "cx-red's own work",
            }
        ],
    )
    result = _run_hook(
        relay_dir=relay_dir,
        file_path="agents/studio_compositor/durf_source.py",
        self_session="cx-red",
        role_env="CODEX_THREAD_NAME",
    )
    assert result.returncode == 0


def test_worktree_prefixed_path_resolves(relay_dir: Path, tmp_path: Path) -> None:
    """An absolute path under a worktree resolves to repo-relative form
    so peer-yaml repo-relative claims can match."""
    _write_peer_yaml(
        relay_dir,
        "delta",
        claims=[
            {
                "path": "agents/studio_compositor/durf_source.py",
                "until": _iso_utc(60),
            }
        ],
    )
    abs_path = (
        "/home/hapax/projects/hapax-council--main-red/agents/studio_compositor/durf_source.py"
    )
    result = _run_hook(
        relay_dir=relay_dir,
        file_path=abs_path,
    )
    assert result.returncode == 1, (
        f"Worktree-prefixed path should resolve and match; got {result.returncode}, "
        f"stderr={result.stderr!r}"
    )


def test_non_edit_tool_passes(relay_dir: Path) -> None:
    """The hook only fires on Edit/Write/MultiEdit/NotebookEdit; Bash etc skip."""
    _write_peer_yaml(
        relay_dir,
        "delta",
        claims=[{"path": "agents/file.py", "until": _iso_utc(60)}],
    )
    payload = {"tool_name": "Read", "tool_input": {"file_path": "agents/file.py"}}
    env = os.environ.copy()
    env["HOME"] = str(relay_dir.parent.parent.parent)
    env["CLAUDE_ROLE"] = "beta"
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0
