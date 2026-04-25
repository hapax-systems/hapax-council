"""Tests for ``agents.publication_bus.publisher_kit.allowlist``."""

from __future__ import annotations

import pytest

from agents.publication_bus.publisher_kit.allowlist import (
    AllowlistGate,
    AllowlistViolation,
    load_allowlist,
)


class TestAllowlistGate:
    def test_permits_registered_target(self) -> None:
        gate = AllowlistGate(surface_name="test", permitted=frozenset({"a", "b"}))
        assert gate.permits("a")
        assert gate.permits("b")

    def test_refuses_unregistered_target(self) -> None:
        gate = AllowlistGate(surface_name="test", permitted=frozenset({"a"}))
        assert not gate.permits("z")

    def test_assert_permits_raises_on_unregistered(self) -> None:
        gate = AllowlistGate(surface_name="test", permitted=frozenset())
        with pytest.raises(AllowlistViolation) as exc:
            gate.assert_permits("nope")
        assert "test" in str(exc.value)
        assert "nope" in str(exc.value)

    def test_assert_permits_silent_on_registered(self) -> None:
        gate = AllowlistGate(surface_name="test", permitted=frozenset({"ok"}))
        gate.assert_permits("ok")  # no raise

    def test_empty_allowlist_refuses_all(self) -> None:
        gate = AllowlistGate(surface_name="test", permitted=frozenset())
        assert not gate.permits("anything")
        assert not gate.permits("")


class TestLoadAllowlist:
    def test_constructs_from_list(self) -> None:
        gate = load_allowlist("zenodo", ["zenodo.org", "sandbox.zenodo.org"])
        assert gate.surface_name == "zenodo"
        assert gate.permits("zenodo.org")
        assert gate.permits("sandbox.zenodo.org")
        assert not gate.permits("evil.example.com")

    def test_empty_list_produces_empty_gate(self) -> None:
        gate = load_allowlist("test", [])
        assert not gate.permits("anything")
