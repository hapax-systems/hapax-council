"""Tests for the SDLC axiom compliance gate (structural checks).

These are deterministic unit tests — no LLM calls needed.
"""

from __future__ import annotations

# The structural check function is importable directly.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.sdlc_axiom_judge import COMMIT_MSG_RE, SemanticVerdict, _call_judge, _check_structural


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
            ["systemd/hapax-daimonion.service"],
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


# ---------------------------------------------------------------------------
# Semantic verdict decision logic property tests
# ---------------------------------------------------------------------------


class TestDecisionLogic:
    """Property tests for the overall result determination at lines 280-289."""

    @staticmethod
    def _decide(semantic, structural_passed=True, precedent_compliant=True):
        """Reproduce the decision logic from run_axiom_gate."""
        from typing import Literal

        has_t0 = any(not v.compliant and v.tier_violated == "T0" for v in semantic)
        has_structural_failure = not structural_passed
        has_advisory = any(not v.compliant and v.tier_violated != "T0" for v in semantic)

        if has_t0 or has_structural_failure:
            overall: Literal["pass", "block", "advisory"] = "block"
        elif has_advisory or not precedent_compliant:
            overall = "advisory"
        else:
            overall = "pass"
        return overall

    def test_t0_violation_blocks(self):
        verdicts = [SemanticVerdict(axiom_id="single_user", compliant=False, tier_violated="T0")]
        assert self._decide(verdicts) == "block"

    def test_t1_violation_is_advisory(self):
        verdicts = [SemanticVerdict(axiom_id="single_user", compliant=False, tier_violated="T1")]
        assert self._decide(verdicts) == "advisory"

    def test_structural_failure_blocks_despite_llm_pass(self):
        verdicts = [SemanticVerdict(axiom_id="single_user", compliant=True)]
        assert self._decide(verdicts, structural_passed=False) == "block"

    def test_all_pass_produces_pass(self):
        verdicts = [SemanticVerdict(axiom_id="single_user", compliant=True)]
        assert self._decide(verdicts) == "pass"

    def test_precedent_failure_is_advisory(self):
        verdicts = [SemanticVerdict(axiom_id="single_user", compliant=True)]
        assert self._decide(verdicts, precedent_compliant=False) == "advisory"

    def test_t0_plus_structural_still_blocks(self):
        verdicts = [SemanticVerdict(axiom_id="single_user", compliant=False, tier_violated="T0")]
        assert self._decide(verdicts, structural_passed=False) == "block"

    def test_t0_violation_never_downgraded_to_advisory(self):
        verdicts = [
            SemanticVerdict(axiom_id="single_user", compliant=False, tier_violated="T0"),
            SemanticVerdict(axiom_id="executive_function", compliant=True),
        ]
        assert self._decide(verdicts, precedent_compliant=True) == "block"


class TestFailClosedParsing:
    """Tests for fail-closed JSON parsing in _call_judge."""

    def test_json_parse_failure_blocks(self):
        from unittest.mock import MagicMock, patch

        import anthropic

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="not valid json at all")]

        with patch.object(
            anthropic,
            "Anthropic",
            return_value=MagicMock(
                messages=MagicMock(create=MagicMock(return_value=mock_response))
            ),
        ):
            result = _call_judge("system prompt", "diff content")
            assert len(result) == 1
            assert not result[0].compliant
            assert result[0].tier_violated == "T0"
            assert "parse_failure" in result[0].axiom_id

    def test_json_parse_failure_never_passes(self):
        from unittest.mock import MagicMock, patch

        import anthropic

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"partial": true')]

        with patch.object(
            anthropic,
            "Anthropic",
            return_value=MagicMock(
                messages=MagicMock(create=MagicMock(return_value=mock_response))
            ),
        ):
            result = _call_judge("system prompt", "diff content")
            assert all(not v.compliant for v in result)
