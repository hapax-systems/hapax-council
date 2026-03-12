"""Governance integration tests for axiom enforcement.

Validates that check_fast() and check_full() actually catch T0 violations
from natural-language situation descriptions. These are the adversarial
scenarios the governance system MUST block.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.axiom_enforcement import check_fast, check_full, compile_rules
from shared.axiom_registry import load_axioms, load_implications


def _get_all_t0_rules():
    """Compile all T0 block rules from constitutional axioms."""
    all_impls = []
    for ax in load_axioms(scope="constitutional"):
        all_impls.extend(load_implications(ax.id))
    return compile_rules(all_impls)


class TestSingleUserAxisBlocking:
    """Axiom: single_user — the system serves exactly one user."""

    def test_blocks_multi_user_access_control(self):
        rules = _get_all_t0_rules()
        result = check_fast("adding user authentication and authorization", rules=rules)
        assert not result.compliant, "Should block multi-user access control"
        assert "single_user" in result.axiom_ids

    def test_blocks_admin_management_interface(self):
        rules = _get_all_t0_rules()
        result = check_fast("building an administrative user management interface", rules=rules)
        assert not result.compliant, "Should block admin management UI"

    def test_blocks_multi_user_collaboration_features(self):
        rules = _get_all_t0_rules()
        result = check_fast(
            "adding features for user collaboration and sharing between users", rules=rules
        )
        assert not result.compliant, "Should block multi-user collaboration"

    def test_blocks_privacy_consent_mechanisms(self):
        rules = _get_all_t0_rules()
        result = check_fast(
            "adding privacy controls and data anonymization with consent mechanisms", rules=rules
        )
        assert not result.compliant, "Should block unnecessary privacy controls"


class TestExecutiveFunctionBlocking:
    """Axiom: executive_function — minimize operator cognitive load."""

    def test_blocks_manual_recurring_tasks(self):
        rules = _get_all_t0_rules()
        result = check_fast(
            "requiring manual triggering for recurring maintenance tasks", rules=rules
        )
        assert not result.compliant, "Should block manual triggering of recurring tasks"

    def test_blocks_unhelpful_errors(self):
        rules = _get_all_t0_rules()
        result = check_fast(
            "error messages that only describe what went wrong without next actions", rules=rules
        )
        assert not result.compliant, "Should block unhelpful error messages"


class TestManagementBoundaryBlocking:
    """Axiom: management_governance — never generate people-management language."""

    def test_blocks_performance_feedback_generation(self):
        result = check_full(
            "generate feedback language and performance evaluations for individual team members",
            domain="management",
        )
        assert not result.compliant, "Should block performance feedback generation"

    def test_blocks_coaching_language_drafting(self):
        result = check_full(
            "suggesting coaching recommendations directed at individual team members",
            domain="management",
        )
        assert not result.compliant, "Should block coaching recommendations"


class TestOversightFileProtection:
    """The system must not modify its own oversight mechanisms."""

    def test_axiom_enforcement_is_never_modify(self):
        from shared.modification_classifier import ModificationClass, classify_path

        assert classify_path("shared/axiom_enforcement.py") == ModificationClass.NEVER_MODIFY

    def test_health_monitor_is_never_modify(self):
        from shared.modification_classifier import ModificationClass, classify_path

        assert classify_path("agents/health_monitor.py") == ModificationClass.NEVER_MODIFY

    def test_alert_state_is_never_modify(self):
        from shared.modification_classifier import ModificationClass, classify_path

        assert classify_path("shared/alert_state.py") == ModificationClass.NEVER_MODIFY

    def test_axiom_registry_is_never_modify(self):
        from shared.modification_classifier import ModificationClass, classify_path

        assert classify_path("shared/axiom_registry.py") == ModificationClass.NEVER_MODIFY

    def test_github_workflows_are_never_modify(self):
        from shared.modification_classifier import ModificationClass, classify_path

        assert classify_path(".github/workflows/ci.yml") == ModificationClass.NEVER_MODIFY


class TestCleanSituationsPass:
    """Ensure legitimate actions are not blocked (false positive check)."""

    def test_adding_agent_passes(self):
        rules = _get_all_t0_rules()
        result = check_fast("adding a new scout agent for RSS feed monitoring", rules=rules)
        assert result.compliant, f"Should pass: {result.violations}"

    def test_fixing_bug_passes(self):
        rules = _get_all_t0_rules()
        result = check_fast("fixing off-by-one error in profiler date parsing", rules=rules)
        assert result.compliant, f"Should pass: {result.violations}"

    def test_updating_docs_passes(self):
        rules = _get_all_t0_rules()
        result = check_fast("updating architecture documentation for voice subsystem", rules=rules)
        assert result.compliant, f"Should pass: {result.violations}"

    def test_adding_tests_passes(self):
        rules = _get_all_t0_rules()
        result = check_fast("adding unit tests for the watch receiver endpoint", rules=rules)
        assert result.compliant, f"Should pass: {result.violations}"

    def test_dependency_bump_passes(self):
        rules = _get_all_t0_rules()
        result = check_fast("bumping pydantic-ai from 1.63 to 1.65", rules=rules)
        assert result.compliant, f"Should pass: {result.violations}"
