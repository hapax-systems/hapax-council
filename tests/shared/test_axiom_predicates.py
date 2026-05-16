"""Tests for deterministic axiom predicates — T0/T1 checks without LLM."""

from __future__ import annotations

import string

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from shared.diff_context import (
    DiffContext,
    PredicateResult,
    check_multi_tenant_security,
    check_multi_user_vocabulary,
    check_protected_module_deps,
    evaluate_deterministic,
)

# ── Strategies ──────────────────────────────────────────────────────────────

safe_text = st.text(
    alphabet=string.ascii_lowercase + string.digits + " _.,;:(){}[]=#+-*/\n",
    min_size=0,
    max_size=200,
)

safe_filename = st.text(
    alphabet=string.ascii_lowercase + string.digits + "_/.",
    min_size=1,
    max_size=60,
).filter(lambda s: not s.startswith("/") and ".." not in s)

diff_contexts = st.builds(
    DiffContext,
    changed_files=st.tuples(safe_filename).map(tuple),
    added_lines=st.lists(safe_text, max_size=20).map(tuple),
    removed_lines=st.lists(safe_text, max_size=20).map(tuple),
    pr_title=safe_text,
)


# ── Unit tests ──────────────────────────────────────────────────────────────


class TestDiffContext:
    def test_from_diff_parses_added_removed(self):
        diff = "+added line\n-removed line\n context\n+another added"
        ctx = DiffContext.from_diff(diff, ["file.py"], "test")
        assert "added line" in ctx.added_lines
        assert "another added" in ctx.added_lines
        assert "removed line" in ctx.removed_lines
        assert len(ctx.added_lines) == 2
        assert len(ctx.removed_lines) == 1

    def test_from_diff_ignores_file_headers(self):
        diff = "--- a/file.py\n+++ b/file.py\n+real line"
        ctx = DiffContext.from_diff(diff, ["file.py"], "test")
        assert len(ctx.added_lines) == 1
        assert ctx.added_lines[0] == "real line"


class TestMultiUserVocabulary:
    def test_clean_diff_passes(self):
        ctx = DiffContext(
            changed_files=("shared/config.py",),
            added_lines=("def get_model():", '    return "balanced"'),
            removed_lines=(),
        )
        result = check_multi_user_vocabulary(ctx)
        assert result.passed
        assert result.tier == "T0"

    @pytest.mark.parametrize(
        "bad_line",
        [
            "user_id = request.user",
            "tenant_id = get_tenant()",
            "if multi_tenant:",
            "per_user_quota = 100",
            "role_based_access = True",
            "rbac_check(user)",
            "user_management.create()",
            "authentication_required",
            "authorization_check()",
            "login_required",
            "sign_up(email)",
            "user_permission = get_perms()",
            "current_user = get_user()",
        ],
    )
    def test_multi_user_vocabulary_detected(self, bad_line: str):
        ctx = DiffContext(
            changed_files=("agents/new_agent.py",),
            added_lines=(bad_line,),
            removed_lines=(),
        )
        result = check_multi_user_vocabulary(ctx)
        assert not result.passed
        assert len(result.matches) > 0

    def test_removed_lines_not_flagged(self):
        ctx = DiffContext(
            changed_files=("agents/old.py",),
            added_lines=(),
            removed_lines=("user_id = request.user",),
        )
        result = check_multi_user_vocabulary(ctx)
        assert result.passed


class TestProtectedModuleDeps:
    def test_governance_file_allowed(self):
        ctx = DiffContext(
            changed_files=("shared/governance/consent.py",),
            added_lines=("from shared.axiom_enforcement import check",),
            removed_lines=(),
        )
        result = check_protected_module_deps(ctx)
        assert result.passed

    def test_non_governance_import_blocked(self):
        ctx = DiffContext(
            changed_files=("agents/weather.py",),
            added_lines=("from shared.axiom_enforcement import check",),
            removed_lines=(),
        )
        result = check_protected_module_deps(ctx)
        assert not result.passed
        assert len(result.matches) > 0

    def test_normal_imports_allowed(self):
        ctx = DiffContext(
            changed_files=("agents/weather.py",),
            added_lines=("from shared.config import get_model",),
            removed_lines=(),
        )
        result = check_protected_module_deps(ctx)
        assert result.passed


class TestMultiTenantSecurity:
    def test_clean_passes(self):
        ctx = DiffContext(
            changed_files=("shared/config.py",),
            added_lines=("rate_limit = 100",),
            removed_lines=(),
        )
        result = check_multi_tenant_security(ctx)
        assert result.passed

    def test_per_user_rate_limit_blocked(self):
        ctx = DiffContext(
            changed_files=("logos/api.py",),
            added_lines=("rate_limit_per_user = 50",),
            removed_lines=(),
        )
        result = check_multi_tenant_security(ctx)
        assert not result.passed

    def test_tenant_isolation_blocked(self):
        ctx = DiffContext(
            changed_files=("shared/db.py",),
            added_lines=("enable_tenant_isolation()",),
            removed_lines=(),
        )
        result = check_multi_tenant_security(ctx)
        assert not result.passed


class TestEvaluateDeterministic:
    def test_returns_results_for_all_predicates(self):
        ctx = DiffContext(
            changed_files=("shared/config.py",),
            added_lines=("x = 1",),
            removed_lines=(),
        )
        results = evaluate_deterministic(ctx)
        assert len(results) == 3
        assert all(isinstance(r, PredicateResult) for r in results)

    def test_all_pass_on_clean_diff(self):
        ctx = DiffContext(
            changed_files=("agents/weather.py",),
            added_lines=("def forecast():", '    return "sunny"'),
            removed_lines=(),
        )
        results = evaluate_deterministic(ctx)
        assert all(r.passed for r in results)

    def test_multiple_violations_detected(self):
        ctx = DiffContext(
            changed_files=("agents/new.py",),
            added_lines=(
                "user_id = get_user()",
                "rate_limit_per_user = 10",
            ),
            removed_lines=(),
        )
        results = evaluate_deterministic(ctx)
        failures = [r for r in results if not r.passed]
        assert len(failures) >= 2


# ── Hypothesis property tests ───────────────────────────────────────────────


class TestPredicateProperties:
    @given(ctx=diff_contexts)
    @settings(max_examples=50)
    def test_predicates_never_raise(self, ctx: DiffContext):
        results = evaluate_deterministic(ctx)
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, PredicateResult)
            assert isinstance(r.passed, bool)

    @given(ctx=diff_contexts)
    @settings(max_examples=50)
    def test_empty_added_lines_always_pass(self, ctx: DiffContext):
        clean = DiffContext(
            changed_files=ctx.changed_files,
            added_lines=(),
            removed_lines=ctx.removed_lines,
            pr_title=ctx.pr_title,
        )
        results = evaluate_deterministic(clean)
        assert all(r.passed for r in results)

    @given(
        base=diff_contexts,
        extra_line=st.sampled_from(
            ["user_id = 1", "tenant_id = t", "rbac_check()", "multi_tenant = True"]
        ),
    )
    @settings(max_examples=30)
    def test_adding_violation_never_improves_result(self, base: DiffContext, extra_line: str):
        clean_results = evaluate_deterministic(base)
        dirty = DiffContext(
            changed_files=base.changed_files,
            added_lines=base.added_lines + (extra_line,),
            removed_lines=base.removed_lines,
            pr_title=base.pr_title,
        )
        dirty_results = evaluate_deterministic(dirty)
        for clean_r, dirty_r in zip(clean_results, dirty_results, strict=True):
            if not clean_r.passed:
                assert not dirty_r.passed, "Adding a violation should not fix an existing failure"
