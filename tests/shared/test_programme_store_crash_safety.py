"""Tests for ProgrammePlanStore crash-safety + dedup-on-add (D-20)."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.programme import (
    Programme,
    ProgrammeRole,
    ProgrammeStatus,
)
from shared.programme_store import ProgrammePlanStore


def _make(programme_id: str, status: ProgrammeStatus = ProgrammeStatus.PENDING) -> Programme:
    return Programme(
        programme_id=programme_id,
        role=ProgrammeRole.SHOWCASE,
        status=status,
        planned_duration_s=60.0,
        parent_show_id="test-show",
    )


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "programmes.jsonl"


class TestTmpCleanupOnInit:
    def test_orphan_tmp_removed_at_construction(self, store_path: Path) -> None:
        """A .tmp file from a prior crash is cleaned on store construction."""
        tmp = store_path.with_suffix(store_path.suffix + ".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text("garbage\n")
        assert tmp.exists()
        ProgrammePlanStore(path=store_path)
        assert not tmp.exists()

    def test_canonical_file_untouched_by_cleanup(self, store_path: Path) -> None:
        """The live file is never touched by _cleanup_tmp."""
        store = ProgrammePlanStore(path=store_path)
        store.add(_make("a"))
        original = store_path.read_text()
        ProgrammePlanStore(path=store_path)  # second construction
        assert store_path.read_text() == original

    def test_cleanup_missing_tmp_is_noop(self, store_path: Path) -> None:
        """No .tmp sibling → no-op, no exception."""
        ProgrammePlanStore(path=store_path)
        tmp = store_path.with_suffix(store_path.suffix + ".tmp")
        assert not tmp.exists()


class TestAddDedup:
    def test_add_replaces_on_programme_id_collision(self, store_path: Path) -> None:
        """Re-adding a programme with same id REPLACES, does not append."""
        store = ProgrammePlanStore(path=store_path)
        store.add(_make("quiet-frame", status=ProgrammeStatus.PENDING))
        # File has one row.
        assert len(store_path.read_text().strip().splitlines()) == 1
        store.add(_make("quiet-frame", status=ProgrammeStatus.ACTIVE))
        # Still one row — not two.
        rows = store_path.read_text().strip().splitlines()
        assert len(rows) == 1
        # The stored row is the new one.
        loaded = store.get("quiet-frame")
        assert loaded is not None
        assert loaded.status == ProgrammeStatus.ACTIVE

    def test_add_preserves_other_programmes(self, store_path: Path) -> None:
        """Dedup on collision doesn't drop other programmes."""
        store = ProgrammePlanStore(path=store_path)
        store.add(_make("a"))
        store.add(_make("b"))
        store.add(_make("a"))  # re-add a
        ids = {p.programme_id for p in store.all()}
        assert ids == {"a", "b"}

    def test_reactivation_does_not_grow_store(self, store_path: Path) -> None:
        """The quiet-frame reactivation loop — prior monotonic-growth bug."""
        store = ProgrammePlanStore(path=store_path)
        for _ in range(50):
            store.add(_make("quiet-frame"))
        rows = store_path.read_text().strip().splitlines()
        assert len(rows) == 1


class TestQuietFrameDoesNotGrow:
    """End-to-end: quiet_frame module uses store.add() which now dedupes."""

    def test_repeated_activate_stable_row_count(self, store_path: Path) -> None:
        from shared.governance.quiet_frame import activate_quiet_frame

        store = ProgrammePlanStore(path=store_path)
        for i in range(20):
            activate_quiet_frame(store, now=1000.0 + i)
        rows = store_path.read_text().strip().splitlines()
        # One row for quiet_frame; possibly zero additional if no prior
        # activations were COMPLETED.
        assert len(rows) == 1
