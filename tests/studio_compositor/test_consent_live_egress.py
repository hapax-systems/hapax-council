"""Tests for consent live-egress predicate.

Default (gate disabled, 2026-04-18 retirement): predicate always returns
False — face-obscure (#129) is the canonical privacy floor. The legacy
fail-closed layout-swap path is preserved behind
``HAPAX_CONSENT_EGRESS_GATE=1|true|on|enabled`` and exercised by the
``TestLegacyGateEnabled*`` classes below.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.studio_compositor import consent_live_egress as cle
from agents.studio_compositor.consent_live_egress import (
    CONSENT_SAFE_LAYOUT_NAME,
    should_egress_compose_safe,
)


def _od(**kwargs):
    defaults = {
        "consent_phase": None,
        "guest_present": False,
        "persistence_allowed": True,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestDefaultDisabled:
    """Default behavior — gate disabled, always returns False.

    The face-obscure pipeline (#129) is the canonical privacy floor;
    the layout-swap gate is redundant and over-protective.
    """

    def test_none_overlay_data_is_safe_by_default(self, monkeypatch):
        monkeypatch.delenv("HAPAX_CONSENT_EGRESS_GATE", raising=False)
        monkeypatch.setattr(cle, "_gate_enabled", False)
        assert should_egress_compose_safe(None) is False

    def test_stale_state_is_safe_by_default(self, monkeypatch):
        monkeypatch.setattr(cle, "_gate_enabled", False)
        assert should_egress_compose_safe(_od(), state_is_stale=True) is False

    def test_guest_detected_is_safe_by_default(self, monkeypatch):
        monkeypatch.setattr(cle, "_gate_enabled", False)
        assert (
            should_egress_compose_safe(_od(consent_phase="guest_detected", guest_present=True))
            is False
        )

    def test_consent_refused_is_safe_by_default(self, monkeypatch):
        monkeypatch.setattr(cle, "_gate_enabled", False)
        assert should_egress_compose_safe(_od(consent_phase="consent_refused")) is False

    def test_unset_env_means_disabled(self, monkeypatch):
        """With no env var set, _is_gate_enabled returns False."""
        monkeypatch.delenv("HAPAX_CONSENT_EGRESS_GATE", raising=False)
        assert cle._is_gate_enabled() is False


class TestLegacyGateEnabledFailClosed:
    """Gate explicitly enabled — legacy fail-closed behavior preserved."""

    @pytest.fixture(autouse=True)
    def _gate_on(self, monkeypatch):
        monkeypatch.setattr(cle, "_gate_enabled", True)

    def test_none_overlay_data_is_unsafe(self):
        assert should_egress_compose_safe(None) is True

    def test_state_stale_is_unsafe(self):
        assert should_egress_compose_safe(_od(), state_is_stale=True) is True

    def test_guest_detected_is_unsafe(self):
        assert should_egress_compose_safe(_od(consent_phase="guest_detected")) is True

    def test_consent_pending_is_unsafe(self):
        assert should_egress_compose_safe(_od(consent_phase="consent_pending")) is True

    def test_consent_refused_is_unsafe(self):
        assert should_egress_compose_safe(_od(consent_phase="consent_refused")) is True

    def test_unknown_phase_is_unsafe(self):
        assert should_egress_compose_safe(_od(consent_phase="contract_expiring")) is True

    def test_guest_present_without_persistence_is_unsafe(self):
        assert (
            should_egress_compose_safe(_od(guest_present=True, persistence_allowed=False)) is True
        )

    def test_guest_present_without_phase_is_unsafe(self):
        assert should_egress_compose_safe(_od(guest_present=True)) is True


class TestLegacyGateEnabledSafeTriggers:
    """Gate explicitly enabled — safe states still permit broadcast."""

    @pytest.fixture(autouse=True)
    def _gate_on(self, monkeypatch):
        monkeypatch.setattr(cle, "_gate_enabled", True)

    def test_solo_operator_is_safe(self):
        assert should_egress_compose_safe(_od()) is False

    def test_consent_granted_is_safe(self):
        assert (
            should_egress_compose_safe(
                _od(
                    consent_phase="consent_granted",
                    guest_present=True,
                    persistence_allowed=True,
                )
            )
            is False
        )


class TestEnableFlagValues:
    """Exercise env-var parsing for _is_gate_enabled()."""

    def test_enabling_values(self, monkeypatch):
        for val in ("1", "true", "on", "enabled", "TRUE", " On "):
            monkeypatch.setenv("HAPAX_CONSENT_EGRESS_GATE", val)
            assert cle._is_gate_enabled() is True, f"value={val!r}"

    def test_disabling_values(self, monkeypatch):
        for val in ("0", "false", "off", "disabled", "", "random-string"):
            monkeypatch.setenv("HAPAX_CONSENT_EGRESS_GATE", val)
            assert cle._is_gate_enabled() is False, f"value={val!r}"


class TestRegression:
    def test_layout_name_is_stable(self):
        assert CONSENT_SAFE_LAYOUT_NAME == "consent-safe.json"

    def test_public_api_unchanged(self):
        assert "should_egress_compose_safe" in cle.__all__
        assert "CONSENT_SAFE_LAYOUT_NAME" in cle.__all__
