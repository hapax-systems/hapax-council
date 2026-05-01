"""Tests for shared.capability_adapters.PerceptionBackendAdapter.

Wraps a ``PerceptionBackend`` (which exposes ``available()`` with no
args) into the ``Capability`` protocol shape (``available(ctx)``).
Untested before this commit.

Tests use a minimal in-test stub for ``PerceptionBackend`` rather
than importing real backend implementations — the adapter only
touches the four attributes (``name``, ``tier``, ``available()``)
of the wrapped object.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.capability import CapabilityCategory, ResourceTier, SystemContext
from shared.capability_adapters import PerceptionBackendAdapter


@dataclass
class _StubTier:
    """Stand-in for a PerceptionBackend's tier field — only `.value`
    is read by the adapter."""

    value: str


@dataclass
class _StubBackend:
    """Minimal duck-type for PerceptionBackend."""

    name: str
    tier: _StubTier
    _available: bool = True

    def available(self) -> bool:
        return self._available


def _ctx() -> SystemContext:
    return SystemContext()


class TestPassthroughProperties:
    def test_name_passes_through(self) -> None:
        backend = _StubBackend(name="ir-presence", tier=_StubTier("fast"))
        adapter = PerceptionBackendAdapter(backend)
        assert adapter.name == "ir-presence"

    def test_category_is_perception(self) -> None:
        adapter = PerceptionBackendAdapter(_StubBackend(name="x", tier=_StubTier("fast")))
        assert adapter.category == CapabilityCategory.PERCEPTION

    def test_backend_property_returns_wrapped_object(self) -> None:
        backend = _StubBackend(name="x", tier=_StubTier("fast"))
        adapter = PerceptionBackendAdapter(backend)
        assert adapter.backend is backend


class TestResourceTierMapping:
    def test_fast_maps_to_instant(self) -> None:
        adapter = PerceptionBackendAdapter(_StubBackend(name="x", tier=_StubTier("fast")))
        assert adapter.resource_tier == ResourceTier.INSTANT

    def test_slow_maps_to_light(self) -> None:
        adapter = PerceptionBackendAdapter(_StubBackend(name="x", tier=_StubTier("slow")))
        assert adapter.resource_tier == ResourceTier.LIGHT

    def test_unknown_tier_falls_back_to_instant(self) -> None:
        """Tiers outside fast/slow default to INSTANT (the safest pick
        — ``LIGHT``/``HEAVY`` would mark the perception path as
        resource-expensive when the system can't classify it)."""
        adapter = PerceptionBackendAdapter(_StubBackend(name="x", tier=_StubTier("medium")))
        assert adapter.resource_tier == ResourceTier.INSTANT


class TestAvailability:
    def test_delegates_to_backend_available(self) -> None:
        adapter = PerceptionBackendAdapter(
            _StubBackend(name="x", tier=_StubTier("fast"), _available=True)
        )
        assert adapter.available(_ctx())

    def test_unavailable_backend_returns_false(self) -> None:
        adapter = PerceptionBackendAdapter(
            _StubBackend(name="x", tier=_StubTier("fast"), _available=False)
        )
        assert not adapter.available(_ctx())

    def test_ctx_is_ignored_by_adapter(self) -> None:
        """The adapter throws away ``ctx`` because PerceptionBackend
        only checks hardware. Verify by passing different ctx instances
        and observing identical results."""
        backend = _StubBackend(name="x", tier=_StubTier("fast"), _available=True)
        adapter = PerceptionBackendAdapter(backend)
        assert adapter.available(_ctx())
        assert adapter.available(_ctx())


class TestDegradeMessage:
    def test_degrade_includes_backend_name(self) -> None:
        adapter = PerceptionBackendAdapter(_StubBackend(name="ir-presence", tier=_StubTier("fast")))
        msg = adapter.degrade()
        assert "ir-presence" in msg
        assert "unavailable" in msg
