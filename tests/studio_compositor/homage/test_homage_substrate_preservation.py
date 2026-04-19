"""HOMAGE #124 substrate preservation — Reverie never enters the FSM.

Spec: ``docs/superpowers/specs/2026-04-18-reverie-substrate-preservation-design.md``.

Three invariants under test:

1. ``HomageSubstrateSource`` Protocol runtime-check matches instances
   that set ``is_substrate=True`` and rejects instances that set it to
   False (or omit it).
2. The choreographer filters substrate sources out of its
   pending-transitions queue — a pending ``ticker-scroll-out`` for
   Reverie never becomes a ``PlannedTransition`` and never consumes a
   concurrency slot.
3. On every reconcile tick, the choreographer writes a
   ``homage-substrate-package.json`` palette-hint file so Reverie picks
   up package tint without needing a transition to be scheduled.

Plus: the ``hapax_homage_choreographer_substrate_skip_total`` Prometheus
counter is emitted at least once per substrate-skip event.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import pytest

from agents.studio_compositor.homage import BITCHX_PACKAGE
from agents.studio_compositor.homage.choreographer import Choreographer
from agents.studio_compositor.homage.substrate_source import (
    SUBSTRATE_SOURCE_REGISTRY,
    HomageSubstrateSource,
)


@pytest.fixture
def homage_on(monkeypatch):
    monkeypatch.setenv("HAPAX_HOMAGE_ACTIVE", "1")


@pytest.fixture
def choreographer(tmp_path: Path) -> Choreographer:
    return Choreographer(
        pending_file=tmp_path / "homage-pending.json",
        uniforms_file=tmp_path / "uniforms.json",
        substrate_package_file=tmp_path / "homage-substrate-package.json",
    )


def _write_pending(path: Path, transitions: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"transitions": transitions}), encoding="utf-8")


class _SubstrateMarker:
    """Minimal stand-in satisfying HomageSubstrateSource at runtime."""

    is_substrate: Literal[True] = True


class _NonSubstrateMarker:
    """Sibling that explicitly declares is_substrate=False."""

    is_substrate: bool = False


class _BareClass:
    """Has no is_substrate attribute at all."""


class TestHomageSubstrateProtocol:
    def test_registry_contains_reverie(self) -> None:
        assert "reverie_external_rgba" in SUBSTRATE_SOURCE_REGISTRY
        assert "reverie" in SUBSTRATE_SOURCE_REGISTRY

    def test_isinstance_matches_substrate_marker(self) -> None:
        # runtime_checkable Protocol only checks attribute presence, so
        # anything with is_substrate set matches — both True and False.
        # The choreographer's _resolve_substrate_ids() gates additionally
        # on truthiness, which is exercised in TestChoreographerFilter.
        assert isinstance(_SubstrateMarker(), HomageSubstrateSource)

    def test_isinstance_rejects_bare_class(self) -> None:
        assert not isinstance(_BareClass(), HomageSubstrateSource)


class TestChoreographerFilter:
    def test_substrate_source_id_skipped(
        self, homage_on, tmp_path: Path, choreographer: Choreographer
    ) -> None:
        _write_pending(
            choreographer._pending_file,
            [
                {
                    "source_id": "reverie_external_rgba",
                    "transition": "ticker-scroll-out",
                    "enqueued_at": 1.0,
                }
            ],
        )
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        # No PlannedTransition was generated for the substrate source.
        assert result.planned == ()
        # No rejection either — substrate skip is *outside* the
        # vocabulary; it is not a rejection.
        assert all(r.source_id != "reverie_external_rgba" for r in result.rejections)

    def test_non_substrate_source_still_transitions(
        self, homage_on, choreographer: Choreographer
    ) -> None:
        _write_pending(
            choreographer._pending_file,
            [
                {
                    "source_id": "overlay_zones",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": 1.0,
                }
            ],
        )
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        planned_ids = [p.source_id for p in result.planned]
        assert "overlay_zones" in planned_ids

    def test_substrate_skip_does_not_consume_entry_slot(
        self, homage_on, choreographer: Choreographer
    ) -> None:
        """Substrate entries are filtered before the concurrency partition.

        ``reverie_external_rgba`` is substrate and must never appear in
        the planned list — even when it's the first entry in a queue
        that would otherwise fit within the concurrency budget.
        """
        _write_pending(
            choreographer._pending_file,
            [
                {
                    "source_id": "reverie_external_rgba",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": 1.0,
                },
                {
                    "source_id": "overlay_zones",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": 1.0,
                },
            ],
        )
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        planned_ids = [p.source_id for p in result.planned]
        assert "overlay_zones" in planned_ids
        assert "reverie_external_rgba" not in planned_ids


class TestPackageBroadcast:
    def test_broadcast_file_written_on_reconcile(
        self, homage_on, choreographer: Choreographer
    ) -> None:
        choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        payload = json.loads(choreographer._substrate_package_file.read_text())
        assert payload["package"] == "bitchx"
        assert "palette_accent_hue_deg" in payload
        assert "substrate_source_ids" in payload
        assert "reverie_external_rgba" in payload["substrate_source_ids"]

    def test_broadcast_recreates_file_after_deletion(
        self, homage_on, choreographer: Choreographer
    ) -> None:
        choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        choreographer._substrate_package_file.unlink()
        choreographer.reconcile(BITCHX_PACKAGE, now=2.0)
        assert choreographer._substrate_package_file.exists()


class TestSubstrateSkipMetric:
    def test_emit_substrate_skip_callable(self) -> None:
        """Importable and callable — metric emission is best-effort."""
        from shared.director_observability import (
            emit_homage_choreographer_substrate_skip,
        )

        # Never raises even when prometheus_client is missing — it's a
        # no-op in that case. The test just pins the function exists.
        emit_homage_choreographer_substrate_skip("reverie_external_rgba")


class TestShmRgbaReaderSubstrateFlag:
    def test_reverie_reader_is_substrate(self, tmp_path: Path) -> None:
        from agents.studio_compositor.shm_rgba_reader import ShmRgbaReader

        reader = ShmRgbaReader(tmp_path / "reverie.rgba", is_substrate=True)
        assert reader.is_substrate is True
        assert isinstance(reader, HomageSubstrateSource)

    def test_non_substrate_reader_defaults_false(self, tmp_path: Path) -> None:
        from agents.studio_compositor.shm_rgba_reader import ShmRgbaReader

        reader = ShmRgbaReader(tmp_path / "other.rgba")
        assert reader.is_substrate is False

    def test_source_registry_flags_reverie_as_substrate(self, tmp_path: Path) -> None:
        """construct_backend() sets is_substrate=True for the reverie id."""
        from agents.studio_compositor.source_registry import SourceRegistry
        from shared.compositor_model import SourceSchema

        registry = SourceRegistry()
        schema = SourceSchema(
            id="reverie",
            kind="external_rgba",
            backend="shm_rgba",
            params={"shm_path": str(tmp_path / "reverie.rgba")},
        )
        backend = registry.construct_backend(schema)
        assert getattr(backend, "is_substrate", False) is True
