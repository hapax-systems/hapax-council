"""The frontier selection guard, exercised as the shell fragment both launchers source.

The defect this pins is not "a wrong default". It is that two launchers made the same
choice from two copies, coordinated by a comment reading "keep in sync", and had already
diverged: hapax-codex grew a guard on 2026-08-10 and hapax-codex-headless kept
gpt-5.5/xhigh. So the tests assert BOTH that the guard behaves, and that neither launcher
carries its own literal any more.

Self-contained per the repo testing convention (no shared conftest fixtures).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRAGMENT = REPO_ROOT / "scripts" / "codex-frontier-selection.sh"
LAUNCHERS = (
    REPO_ROOT / "scripts" / "hapax-codex",
    REPO_ROOT / "scripts" / "hapax-codex-headless",
)

#: The pair verified from a measured rollout head on 2026-08-10, not a launcher self-report.
FRONTIER_MODEL = "gpt-5.6-sol"
FRONTIER_EFFORT = "ultra"


def _run(env_overrides: dict[str, str], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Source the fragment in a clean bash and echo what it resolved."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        **env_overrides,
    }
    script = f'. "{FRAGMENT}"\nprintf "%s|%s\\n" "$CODEX_MODEL" "$CODEX_EFFORT"\n'
    return subprocess.run(
        ["bash", "-c", script], env=env, capture_output=True, text=True, check=False
    )


def test_default_selection_is_the_frontier_pair(tmp_path: Path) -> None:
    result = _run({}, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"{FRONTIER_MODEL}|{FRONTIER_EFFORT}"


def test_below_frontier_without_a_reason_is_refused(tmp_path: Path) -> None:
    """Refuse, do not warn. An unstated downgrade is the exact failure this prevents."""
    result = _run({"HAPAX_CODEX_EFFORT": "low"}, tmp_path)
    assert result.returncode == 6
    assert "REFUSING a below-frontier selection" in result.stderr
    assert "HAPAX_CODEX_MODEL_REASON" in result.stderr


def test_below_frontier_model_without_a_reason_is_refused(tmp_path: Path) -> None:
    result = _run({"HAPAX_CODEX_MODEL": "gpt-5.5"}, tmp_path)
    assert result.returncode == 6
    assert "REFUSING a below-frontier selection" in result.stderr


def test_below_frontier_with_a_reason_proceeds_and_is_recorded(tmp_path: Path) -> None:
    """The reason is the artifact. Permitting without recording would lose the decision."""
    result = _run(
        {
            "HAPAX_CODEX_EFFORT": "low",
            "HAPAX_CODEX_MODEL_REASON": "mechanical sweep, no reasoning demand",
            "ROLE": "cx-test",
        },
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"{FRONTIER_MODEL}|low"

    log = tmp_path / "cache" / "hapax" / "routing" / "model-decisions.jsonl"
    assert log.is_file(), "a permitted downgrade must leave a record"
    entry = log.read_text(encoding="utf-8").strip()
    assert '"effort":"low"' in entry
    assert '"reason":"mechanical sweep, no reasoning demand"' in entry
    assert f'"frontier_effort":"{FRONTIER_EFFORT}"' in entry


def test_raising_the_frontier_pair_moves_the_default(tmp_path: Path) -> None:
    """The point of the fragment: the pair is a decision point, not a constant."""
    result = _run(
        {"HAPAX_CODEX_FRONTIER_MODEL": "gpt-9", "HAPAX_CODEX_FRONTIER_EFFORT": "max"},
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "gpt-9|max"


def test_no_launcher_carries_its_own_model_or_effort_literal() -> None:
    """The regression that actually happened: one copy moved and the other did not.

    A launcher that hardcodes the pair again silently reintroduces the divergence, and
    nothing else in the suite would notice.
    """
    for launcher in LAUNCHERS:
        text = launcher.read_text(encoding="utf-8")
        assert "codex-frontier-selection.sh" in text, f"{launcher.name} must source the fragment"
        for literal in ('model=\\"gpt-', 'model_reasoning_effort=\\"xhigh', "'model=\"gpt-"):
            assert literal not in text, f"{launcher.name} reintroduced a hardcoded pair: {literal}"
