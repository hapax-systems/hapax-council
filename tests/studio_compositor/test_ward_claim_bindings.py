"""Tests for agents.studio_compositor.ward_claim_bindings."""

from __future__ import annotations

import pytest

from agents.studio_compositor import ward_claim_bindings as wcb


@pytest.fixture(autouse=True)
def _isolated_bindings():
    """Each test sees an empty binding registry. Reset after."""
    wcb.clear_bindings()
    yield
    wcb.clear_bindings()


def test_get_returns_none_for_unknown_ward():
    assert wcb.get("never-registered") is None


def test_register_binds_provider():
    captured: list[str] = []

    def _provider():
        captured.append("called")
        return None

    wcb.register("album-cover", _provider)
    bound = wcb.get("album-cover")

    assert bound is not None
    bound()
    assert captured == ["called"]


def test_register_overwrites_existing_binding():
    wcb.register("album-cover", lambda: None)

    def _new_provider():
        return None

    wcb.register("album-cover", _new_provider)

    assert wcb.get("album-cover") is _new_provider


def test_bound_wards_returns_snapshot():
    wcb.register("a", lambda: None)
    wcb.register("b", lambda: None)
    wcb.register("c", lambda: None)

    assert wcb.bound_wards() == {"a", "b", "c"}


def test_bound_wards_returns_copy_not_reference():
    """Mutating the returned set must not affect the registry."""
    wcb.register("a", lambda: None)
    snapshot = wcb.bound_wards()
    snapshot.add("b")

    # The registry itself should not have gained "b".
    assert "b" not in wcb.bound_wards()


def test_clear_bindings_drops_all():
    wcb.register("a", lambda: None)
    wcb.register("b", lambda: None)

    wcb.clear_bindings()

    assert wcb.bound_wards() == set()
    assert wcb.get("a") is None


def test_provider_returning_none_is_normal():
    """A provider may return None when the underlying engine declines —
    that's not an error condition, callers must accept it."""
    wcb.register("album-cover", lambda: None)
    provider = wcb.get("album-cover")

    assert provider is not None
    assert provider() is None
