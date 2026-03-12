"""Tests for the SDLC axiom compliance gate (structural checks).

These are deterministic unit tests — no LLM calls needed.
"""

from __future__ import annotations

# The structural check function is importable directly.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.sdlc_axiom_judge import COMMIT_MSG_RE, _check_structural


class TestProtectedPathDetection:
    """Structural gate: protected path checks."""

    def test_health_monitor_blocked(self):
        result = _check_structural(
            ["agents/health_monitor.py"],
            "diff content",
            "[agent] update health monitor",
        )
        assert not result.passed
        assert any("health_monitor" in v for v in result.violations)

    def test_axiom_enforcement_blocked(self):
        result = _check_structural(
            ["shared/axiom_enforcement.py"],
            "diff",
            "[agent] refactor",
        )
        assert not result.passed

    def test_config_blocked(self):
        result = _check_structural(
            ["shared/config.py"],
            "diff",
            "[agent] update config",
        )
        assert not result.passed

    def test_axioms_dir_blocked(self):
        result = _check_structural(
            ["axioms/registry.yaml"],
            "diff",
            "[agent] update axioms",
        )
        assert not result.passed

    def test_hooks_dir_blocked(self):
        result = _check_structural(
            ["hooks/pre-commit"],
            "diff",
            "[agent] update hooks",
        )
        assert not result.passed

    def test_systemd_blocked(self):
        result = _check_structural(
            ["systemd/hapax-voice.service"],
            "diff",
            "[agent] update service",
        )
        assert not result.passed

    def test_safe_path_passes(self):
        result = _check_structural(
            ["agents/scout.py", "tests/test_scout.py"],
            "some diff\nlines\nhere",
            "[agent] update scout",
        )
        assert result.passed
        assert result.violations == []

    def test_alert_state_blocked(self):
        result = _check_structural(
            ["shared/alert_state.py"],
            "diff",
            "[agent] fix alert",
        )
        assert not result.passed

    def test_backup_script_blocked(self):
        result = _check_structural(
            ["hapax-backup-local.sh"],
            "diff",
            "[agent] fix backup",
        )
        assert not result.passed

    def test_axiom_registry_blocked(self):
        result = _check_structural(
            ["shared/axiom_registry.py"],
            "diff",
            "[agent] update registry",
        )
        assert not result.passed

    def test_axiom_tools_blocked(self):
        result = _check_structural(
            ["shared/axiom_tools.py"],
            "diff",
            "[agent] update tools",
        )
        assert not result.passed

    def test_github_workflows_blocked(self):
        result = _check_structural(
            [".github/workflows/ci.yml"],
            "diff",
            "[agent] update CI",
        )
        assert not result.passed


class TestDiffSizeCheck:
    """Structural gate: diff size bounds."""

    def test_small_diff_passes(self):
        diff = "\n".join(f"line {i}" for i in range(100))
        result = _check_structural(["agents/scout.py"], diff, "[agent] fix", "S")
        assert result.passed

    def test_large_s_diff_fails(self):
        diff = "\n".join(f"line {i}" for i in range(600))
        result = _check_structural(["agents/scout.py"], diff, "[agent] fix", "S")
        assert not result.passed
        assert any("Diff size" in v for v in result.violations)

    def test_m_diff_within_limit(self):
        diff = "\n".join(f"line {i}" for i in range(1000))
        result = _check_structural(["agents/scout.py"], diff, "[agent] fix", "M")
        assert result.passed

    def test_m_diff_over_limit(self):
        diff = "\n".join(f"line {i}" for i in range(1600))
        result = _check_structural(["agents/scout.py"], diff, "[agent] fix", "M")
        assert not result.passed


class TestCommitMessageFormat:
    """Structural gate: commit message / PR title validation."""

    def test_conventional_feat(self):
        assert COMMIT_MSG_RE.match("feat: add new feature")

    def test_conventional_fix_scoped(self):
        assert COMMIT_MSG_RE.match("fix(watch): resolve timeout")

    def test_conventional_chore(self):
        assert COMMIT_MSG_RE.match("chore: update deps")

    def test_agent_prefix_allowed(self):
        # Agent PRs use [agent] prefix — allowed by structural check.
        result = _check_structural(["agents/scout.py"], "diff", "[agent] fix something")
        # Should not fail on title format.
        assert not any("conventional commits" in v.lower() for v in result.violations)

    def test_random_title_fails(self):
        result = _check_structural(["agents/scout.py"], "diff", "yolo deploy friday")
        assert any("conventional commits" in v.lower() for v in result.violations)
