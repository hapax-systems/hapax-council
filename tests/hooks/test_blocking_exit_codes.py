"""Pins the blocking-intent exit codes (exit 2) and dependency
fail-closed guards repaired in the SDLC config-conformance P0.

In Claude Code only exit 2 blocks a tool call; exit 1 is advisory. These
tests confirm the repaired hooks fail closed (jq/PCRE) and block (exit 2)
where their intent is to block.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
SCRIPTS = REPO_ROOT / "hooks" / "scripts"
BASH = shutil.which("bash") or "bash"


def _bin_without_jq(tmp_path: Path) -> str:
    """A PATH dir holding the coreutils the hooks need, minus jq."""
    binr = tmp_path / "bin"
    binr.mkdir()
    needed = [
        "bash",
        "cat",
        "grep",
        "sed",
        "head",
        "tr",
        "dirname",
        "basename",
        "date",
        "mkdir",
        "env",
        "awk",
        "cut",
        "rm",
    ]
    for tool in needed:
        src = shutil.which(tool)
        if src:
            (binr / tool).symlink_to(src)
    return str(binr)


# ── jq fail-closed guards ──────────────────────────────────────────


def test_axiom_scan_blocks_without_jq(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PATH"] = _bin_without_jq(tmp_path)
    result = subprocess.run(
        [BASH, str(SCRIPTS / "axiom-scan.sh")],
        input='{"tool_name":"Write","tool_input":{"file_path":"x.py","content":"y=1"}}',
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 2, f"stderr={result.stderr!r}"
    assert "jq" in result.stderr


def test_pii_guard_blocks_without_jq(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PATH"] = _bin_without_jq(tmp_path)
    result = subprocess.run(
        [BASH, str(SCRIPTS / "pii-guard.sh")],
        input='{"tool_name":"Write","tool_input":{"file_path":"x.py","content":"y=1"}}',
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 2, f"stderr={result.stderr!r}"
    assert "jq" in result.stderr


def test_pii_guard_has_pcre_probe() -> None:
    body = (SCRIPTS / "pii-guard.sh").read_text(encoding="utf-8")
    # Fail-closed PCRE capability probe so grep -P patterns can't no-op.
    assert "grep -qP 'probe'" in body


# ── exit-2 blocking intent ─────────────────────────────────────────


def test_pr_admission_blocks_pr_create_in_drain(tmp_path: Path) -> None:
    cache = tmp_path / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "pr-admission-governor.yaml").write_text("mode: drain\n")
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    result = subprocess.run(
        [BASH, str(SCRIPTS / "pr-admission-gate.sh")],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "gh pr create --fill"}}),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 2, f"stderr={result.stderr!r} stdout={result.stdout!r}"


def test_vale_style_check_blocks_with_exit_2() -> None:
    body = (SCRIPTS / "vale-style-check.sh").read_text(encoding="utf-8")
    assert "exit 1" not in body
    assert "exit 2" in body


def test_relay_path_claim_blocks_with_exit_2() -> None:
    body = (SCRIPTS / "relay-coordination-check.sh").read_text(encoding="utf-8")
    # The path-claim BLOCK must use exit 2 (blocking), not advisory exit 1.
    assert "  exit 2\nfi" in body
    assert "  exit 1\n" not in body
