"""Role-identity resolution coverage for the disambiguation fix
(cc-task-role-resolution-disambiguation).

Subprocess-runs the REAL scripts with a controlled, identity-stripped env + a tmp HOME
(so no real markers are touched). Covers the three changed surfaces:
  - scripts/hapax-whoami            — env-first resolution (the KWin/cc-* bug fix)
  - scripts/hapax-whoami-audit.sh   — approved-set accepts the full lane vocabulary
  - hooks/scripts/agent-role.sh     — assert-identity accepts cc-<name>, rejects unknowns
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
WHOAMI = REPO / "scripts" / "hapax-whoami"
AUDIT = REPO / "scripts" / "hapax-whoami-audit.sh"
AGENT_ROLE = REPO / "hooks" / "scripts" / "agent-role.sh"
ENFORCE = REPO / "hooks" / "scripts" / "session-name-enforcement.sh"


def _run(cmd: list[str], home: Path, env_extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run with a minimal env: PATH + tmp HOME + only the identity vars the test sets."""
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home)}
    env.update(env_extra)
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=10)


# --- hapax-whoami: env-first, WM-independent (the bug: KWin has no hyprctl) ---


def test_whoami_env_resolves_without_marker_or_compositor(tmp_path: Path) -> None:
    r = _run(["bash", str(WHOAMI)], tmp_path, {"HAPAX_AGENT_ROLE": "cc-zai"})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "cc-zai"


def test_whoami_env_precedence_name_over_role(tmp_path: Path) -> None:
    r = _run(
        ["bash", str(WHOAMI)], tmp_path, {"HAPAX_AGENT_NAME": "cc-cns", "HAPAX_AGENT_ROLE": "alpha"}
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "cc-cns"


def test_whoami_marker_still_resolves_when_no_env(tmp_path: Path) -> None:
    # Regression: the pre-existing marker path must keep working.
    (tmp_path / ".cache" / "hapax").mkdir(parents=True)
    (tmp_path / ".cache" / "hapax" / "session-role-sid42").write_text("gamma\n")
    r = _run(["bash", str(WHOAMI)], tmp_path, {"CLAUDE_CODE_SESSION_ID": "sid42"})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "gamma"


# --- hapax-whoami-audit.sh: approved-set == canonical lane vocabulary ---


@pytest.mark.parametrize("name", ["cc-zai", "cx-red", "zeta", "iota", "antigrav", "vbe-2"])
def test_audit_accepts_full_vocabulary(tmp_path: Path, name: str) -> None:
    r = _run(["bash", str(AUDIT)], tmp_path, {"HAPAX_AGENT_ROLE": name})
    assert r.returncode == 0, f"{name}: {r.stderr}"
    assert r.stdout.strip() == name


def test_audit_rejects_unknown(tmp_path: Path) -> None:
    r = _run(["bash", str(AUDIT)], tmp_path, {"HAPAX_AGENT_ROLE": "bogus123"})
    assert r.returncode == 2


# --- agent-role.sh assert-identity: cc-* is a first-class lane ---


def test_assert_identity_accepts_cc_lane(tmp_path: Path) -> None:
    (tmp_path / ".cache" / "hapax").mkdir(parents=True)
    r = _run(
        ["bash", str(AGENT_ROLE), "assert-identity", "cc-zai"],
        tmp_path,
        {"HAPAX_SESSION_ID": "test-sid-123"},
    )
    assert r.returncode == 0, r.stderr
    marker = tmp_path / ".cache" / "hapax" / "session-role-test-sid-123"
    assert marker.read_text().strip() == "cc-zai"


def test_assert_identity_rejects_unknown(tmp_path: Path) -> None:
    r = _run(
        ["bash", str(AGENT_ROLE), "assert-identity", "bogus123"],
        tmp_path,
        {"HAPAX_SESSION_ID": "test-sid-123"},
    )
    assert r.returncode == 2


# --- session-name-enforcement.sh: greek deny-list matches the canonical slots ---


def _hook(command: str, home: Path) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home)}
    return subprocess.run(
        ["bash", str(ENFORCE)], input=payload, env=env, capture_output=True, text=True, timeout=10
    )


def test_enforcement_allows_canonical_greek_slot(tmp_path: Path) -> None:
    # zeta..iota are canonical lanes now — referencing them must NOT be blocked.
    r = _hook("hapax-claude --session zeta", tmp_path)
    assert r.returncode == 0, r.stderr


def test_enforcement_blocks_greek_beyond_iota(tmp_path: Path) -> None:
    r = _hook("hapax-claude --session kappa", tmp_path)
    assert r.returncode == 2


# --- hapax-whoami: env-first beats a PRESENT marker; --match-title seam ---


def test_whoami_env_beats_present_marker(tmp_path: Path) -> None:
    (tmp_path / ".cache" / "hapax").mkdir(parents=True)
    (tmp_path / ".cache" / "hapax" / "session-role-sid99").write_text("gamma\n")
    r = _run(
        ["bash", str(WHOAMI)],
        tmp_path,
        {"HAPAX_AGENT_ROLE": "cc-zai", "CLAUDE_CODE_SESSION_ID": "sid99"},
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "cc-zai"  # env wins over the present marker


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("claude cc-zai", "cc-zai"),
        ("spinner theta - foo", "theta"),
        ("iota", "iota"),
        ("cx-red", "cx-red"),
        ("no identity here", ""),
    ],
)
def test_whoami_match_title(tmp_path: Path, title: str, expected: str) -> None:
    r = _run(["bash", str(WHOAMI), "--match-title", title], tmp_path, {})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == expected


# --- hapax-whoami: full env precedence == hapax_agent_identity's order ---
# NAME -> CODEX thread/session/role -> HAPAX_AGENT_ROLE -> CLAUDE_ROLE.


def test_whoami_name_beats_all_other_env(tmp_path: Path) -> None:
    r = _run(
        ["bash", str(WHOAMI)],
        tmp_path,
        {
            "HAPAX_AGENT_NAME": "cc-zai",
            "CODEX_ROLE": "cx-red",
            "HAPAX_AGENT_ROLE": "alpha",
            "CLAUDE_ROLE": "beta",
        },
    )
    assert r.stdout.strip() == "cc-zai"


def test_whoami_codex_env_precedes_agent_role(tmp_path: Path) -> None:
    r = _run(
        ["bash", str(WHOAMI)],
        tmp_path,
        {"CODEX_ROLE": "cx-blue", "HAPAX_AGENT_ROLE": "alpha", "CLAUDE_ROLE": "gamma"},
    )
    assert r.stdout.strip() == "cx-blue"


def test_whoami_claude_role_is_last_resort_env(tmp_path: Path) -> None:
    r = _run(["bash", str(WHOAMI)], tmp_path, {"CLAUDE_ROLE": "delta"})
    assert r.stdout.strip() == "delta"
