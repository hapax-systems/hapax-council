"""Tests for `shared.face_obscure_policy` (task #129)."""

from __future__ import annotations

from shared.face_obscure_policy import (
    DEFAULT_POLICY,
    FaceObscurePolicy,
    is_feature_active,
    parse_policy,
    resolve_policy,
)


class TestFaceObscurePolicyEnum:
    def test_has_expected_members(self):
        assert FaceObscurePolicy.ALWAYS_OBSCURE.value == "always_obscure"
        assert FaceObscurePolicy.OBSCURE_NON_OPERATOR.value == "obscure_non_operator"
        assert FaceObscurePolicy.DISABLED.value == "disabled"

    def test_default_is_always_obscure(self):
        # Fail-safe default: if config is missing, obscure everyone.
        assert DEFAULT_POLICY is FaceObscurePolicy.ALWAYS_OBSCURE

    def test_is_str_enum_for_env_and_json_roundtrip(self):
        # String-valued enum lets the policy round-trip through env vars,
        # JSON config, and Prometheus labels without custom serialization.
        assert isinstance(FaceObscurePolicy.ALWAYS_OBSCURE.value, str)
        assert FaceObscurePolicy("disabled") is FaceObscurePolicy.DISABLED


class TestParsePolicy:
    def test_none_returns_default(self):
        assert parse_policy(None) is DEFAULT_POLICY

    def test_empty_string_returns_default(self):
        assert parse_policy("") is DEFAULT_POLICY
        assert parse_policy("   ") is DEFAULT_POLICY

    def test_unknown_value_falls_back_to_default(self):
        # Fail-safe: never raise, always land on ALWAYS_OBSCURE.
        assert parse_policy("bogus") is DEFAULT_POLICY
        assert parse_policy("off") is DEFAULT_POLICY

    def test_parses_canonical_values(self):
        assert parse_policy("always_obscure") is FaceObscurePolicy.ALWAYS_OBSCURE
        assert parse_policy("obscure_non_operator") is FaceObscurePolicy.OBSCURE_NON_OPERATOR
        assert parse_policy("disabled") is FaceObscurePolicy.DISABLED

    def test_parses_hyphenated_and_mixed_case(self):
        # Operators often write `always-obscure` in env vars.
        assert parse_policy("always-obscure") is FaceObscurePolicy.ALWAYS_OBSCURE
        assert parse_policy("ALWAYS_OBSCURE") is FaceObscurePolicy.ALWAYS_OBSCURE
        assert parse_policy("  Obscure-Non-Operator  ") is FaceObscurePolicy.OBSCURE_NON_OPERATOR


class TestFeatureFlag:
    def test_unset_flag_defaults_on(self):
        # Fail-safe: unset env keeps obscure pipeline active.
        assert is_feature_active({}) is True

    def test_explicit_off_values_disable(self):
        for value in ("0", "false", "no", "off", "disabled", "FALSE", "Off"):
            assert is_feature_active({"HAPAX_FACE_OBSCURE_ACTIVE": value}) is False, value

    def test_explicit_on_values_enable(self):
        for value in ("1", "true", "yes", "on", "enabled", "TRUE"):
            assert is_feature_active({"HAPAX_FACE_OBSCURE_ACTIVE": value}) is True, value

    def test_garbage_value_defaults_on(self):
        # Misconfiguration must not silently disable privacy floor.
        assert is_feature_active({"HAPAX_FACE_OBSCURE_ACTIVE": "maybe"}) is True


class TestResolvePolicy:
    def test_flag_off_forces_disabled(self):
        env = {
            "HAPAX_FACE_OBSCURE_ACTIVE": "0",
            "HAPAX_FACE_OBSCURE_POLICY": "always_obscure",
        }
        assert resolve_policy(env) is FaceObscurePolicy.DISABLED

    def test_flag_on_uses_policy_env(self):
        env = {"HAPAX_FACE_OBSCURE_POLICY": "obscure_non_operator"}
        assert resolve_policy(env) is FaceObscurePolicy.OBSCURE_NON_OPERATOR

    def test_unset_env_returns_default_policy(self):
        assert resolve_policy({}) is DEFAULT_POLICY
