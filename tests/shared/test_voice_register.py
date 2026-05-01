"""Tests for shared.voice_register.VoiceRegister.

42-LOC enum module: CPAL-readable tonal mode for the daimonion.
Untested before this commit. The module is small but it pins a
shared vocabulary that crosses the daimonion/CPAL/HOMAGE boundary —
testing the contract guards against silent drift.
"""

from __future__ import annotations

import pytest

from shared.voice_register import DEFAULT_REGISTER, VoiceRegister

# ── Enum membership pin ────────────────────────────────────────────


class TestEnumMembership:
    def test_three_documented_members(self) -> None:
        """The HOMAGE spec defines exactly three voice registers; pin
        the count so accidental additions/removals are caught."""
        assert {member.name for member in VoiceRegister} == {
            "ANNOUNCING",
            "CONVERSING",
            "TEXTMODE",
        }

    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("ANNOUNCING", "announcing"),
            ("CONVERSING", "conversing"),
            ("TEXTMODE", "textmode"),
        ],
    )
    def test_member_values_pinned(self, name: str, value: str) -> None:
        """Pin the wire-protocol values — these strings cross the
        daimonion/CPAL boundary and downstream code does string
        comparisons against them."""
        assert VoiceRegister[name].value == value


# ── StrEnum behaviour ──────────────────────────────────────────────


class TestStrEnumBehaviour:
    def test_member_is_str(self) -> None:
        """StrEnum members are str subclasses — equality with the
        backing string must hold without explicit conversion."""
        assert VoiceRegister.ANNOUNCING == "announcing"
        assert VoiceRegister.CONVERSING == "conversing"
        assert VoiceRegister.TEXTMODE == "textmode"

    def test_member_str_returns_value(self) -> None:
        assert str(VoiceRegister.ANNOUNCING) == "announcing"

    def test_lookup_by_value(self) -> None:
        assert VoiceRegister("conversing") is VoiceRegister.CONVERSING

    def test_unknown_value_raises(self) -> None:
        with pytest.raises(ValueError):
            VoiceRegister("shouting")


# ── Default contract ───────────────────────────────────────────────


class TestDefault:
    def test_default_is_conversing(self) -> None:
        """Per docstring: fallback when no HomagePackage has written a
        preference and stream_mode doesn't force ANNOUNCING."""
        assert DEFAULT_REGISTER is VoiceRegister.CONVERSING


# ── Public API ─────────────────────────────────────────────────────


class TestPublicApi:
    def test_all_exports_match_documented(self) -> None:
        """``__all__`` is the public surface; pin it to catch silent
        widening of what callers may legitimately import."""
        from shared import voice_register

        assert set(voice_register.__all__) == {"VoiceRegister", "DEFAULT_REGISTER"}
