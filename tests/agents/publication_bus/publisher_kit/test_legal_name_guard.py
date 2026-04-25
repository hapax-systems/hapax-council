"""Tests for ``agents.publication_bus.publisher_kit.legal_name_guard``."""

from __future__ import annotations

import pytest

from agents.publication_bus.publisher_kit.legal_name_guard import (
    LegalNameLeak,
    assert_no_leak,
)


class TestAssertNoLeak:
    def test_clean_text_passes_silently(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
        # No raise
        assert_no_leak("hello world")
        assert_no_leak("attribution by Hapax and Claude Code")

    def test_leak_raises_legal_name_leak(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
        with pytest.raises(LegalNameLeak):
            assert_no_leak("from Test Operator")

    def test_case_insensitive_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
        with pytest.raises(LegalNameLeak):
            assert_no_leak("from test operator")  # lowercased

    def test_no_pattern_no_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty / unset pattern disables the scan entirely."""
        monkeypatch.delenv("HAPAX_OPERATOR_NAME", raising=False)
        # No raise even on legal-name-shaped text — the env wasn't set
        # so there's no pattern to match against.
        assert_no_leak("from Whatever")

    def test_explicit_pattern_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit ``legal_name_pattern`` kwarg takes precedence over env."""
        monkeypatch.setenv("HAPAX_OPERATOR_NAME", "EnvName")
        # Explicit pattern in kwarg, different from env
        with pytest.raises(LegalNameLeak):
            assert_no_leak("from KwName", legal_name_pattern="KwName")
        # Env-pattern would NOT match this text
        assert_no_leak("from KwName")  # uses env, KwName != EnvName


class TestLegalNameLeakAlias:
    def test_alias_matches_underlying_exception(self) -> None:
        """``LegalNameLeak`` (V5 publication-bus name) is the same
        exception class as the v4 ``OperatorNameLeak``. Subclass code
        and tests can use either name interchangeably."""
        from shared.governance.omg_referent import OperatorNameLeak

        assert LegalNameLeak is OperatorNameLeak
