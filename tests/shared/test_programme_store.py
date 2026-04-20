"""Tests for shared.programme_store — Programme persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.programme import (
    Programme,
    ProgrammeConstraintEnvelope,
    ProgrammeRole,
    ProgrammeStatus,
)
from shared.programme_store import ProgrammePlanStore


def _make_programme(
    programme_id: str,
    *,
    role: ProgrammeRole = ProgrammeRole.SHOWCASE,
    status: ProgrammeStatus = ProgrammeStatus.PENDING,
    started_at: float | None = None,
) -> Programme:
    return Programme(
        programme_id=programme_id,
        role=role,
        status=status,
        planned_duration_s=60.0,
        parent_show_id="test-show",
        actual_started_at=started_at,
    )


@pytest.fixture
def store(tmp_path: Path) -> ProgrammePlanStore:
    return ProgrammePlanStore(path=tmp_path / "programmes.jsonl")


class TestReads:
    def test_empty_store(self, store: ProgrammePlanStore) -> None:
        assert store.all() == []
        assert store.get("missing") is None
        assert store.active_programme() is None

    def test_add_round_trip(self, store: ProgrammePlanStore) -> None:
        p = _make_programme("alpha")
        store.add(p)
        reloaded = store.get("alpha")
        assert reloaded is not None
        assert reloaded.programme_id == "alpha"
        assert reloaded.status == ProgrammeStatus.PENDING

    def test_all_preserves_order(self, store: ProgrammePlanStore) -> None:
        for pid in ("a", "b", "c"):
            store.add(_make_programme(pid))
        assert [p.programme_id for p in store.all()] == ["a", "b", "c"]

    def test_malformed_row_skipped(self, store: ProgrammePlanStore) -> None:
        store.add(_make_programme("good"))
        # Append a garbage line manually — store must not crash.
        with store.path.open("a") as f:
            f.write("{not valid json\n")
            f.write('{"programme_id": "orphan"}\n')  # missing required fields
        assert [p.programme_id for p in store.all()] == ["good"]


class TestActivate:
    def test_pending_becomes_active(self, store: ProgrammePlanStore) -> None:
        store.add(_make_programme("a", status=ProgrammeStatus.PENDING))
        result = store.activate("a", now=1000.0)
        assert result.status == ProgrammeStatus.ACTIVE
        assert result.actual_started_at == 1000.0
        # Persisted.
        assert store.get("a").status == ProgrammeStatus.ACTIVE

    def test_active_singleton_invariant(self, store: ProgrammePlanStore) -> None:
        """Activating one programme deactivates any prior active."""
        store.add(_make_programme("a", status=ProgrammeStatus.ACTIVE, started_at=1000.0))
        store.add(_make_programme("b", status=ProgrammeStatus.PENDING))
        store.activate("b", now=2000.0)
        a = store.get("a")
        b = store.get("b")
        assert a.status == ProgrammeStatus.COMPLETED
        assert a.actual_ended_at == 2000.0
        assert b.status == ProgrammeStatus.ACTIVE
        # active_programme returns the live one.
        assert store.active_programme().programme_id == "b"

    def test_activate_unknown_raises(self, store: ProgrammePlanStore) -> None:
        with pytest.raises(KeyError, match="missing"):
            store.activate("missing")


class TestDeactivate:
    def test_completed_status(self, store: ProgrammePlanStore) -> None:
        store.add(_make_programme("a", status=ProgrammeStatus.ACTIVE))
        result = store.deactivate("a", now=1500.0)
        assert result.status == ProgrammeStatus.COMPLETED
        assert result.actual_ended_at == 1500.0

    def test_aborted_status(self, store: ProgrammePlanStore) -> None:
        store.add(_make_programme("a", status=ProgrammeStatus.ACTIVE))
        result = store.deactivate("a", status=ProgrammeStatus.ABORTED)
        assert result.status == ProgrammeStatus.ABORTED

    def test_rejects_non_terminal_status(self, store: ProgrammePlanStore) -> None:
        store.add(_make_programme("a"))
        with pytest.raises(ValueError, match="COMPLETED or ABORTED"):
            store.deactivate("a", status=ProgrammeStatus.PENDING)


class TestActiveResolver:
    def test_returns_most_recent_when_multiple_active(self, store: ProgrammePlanStore) -> None:
        """Planner bug-guard: if two ACTIVE appear, tiebreak on start time."""
        store.add(_make_programme("old", status=ProgrammeStatus.ACTIVE, started_at=100.0))
        store.add(_make_programme("new", status=ProgrammeStatus.ACTIVE, started_at=500.0))
        result = store.active_programme()
        assert result is not None
        assert result.programme_id == "new"

    def test_returns_none_when_no_active(self, store: ProgrammePlanStore) -> None:
        store.add(_make_programme("p", status=ProgrammeStatus.PENDING))
        assert store.active_programme() is None


class TestMonetizationOptInsRoundTrip:
    """Phase 5 opt-ins survive store round-trip."""

    def test_opt_ins_preserved(self, store: ProgrammePlanStore) -> None:
        env = ProgrammeConstraintEnvelope(
            monetization_opt_ins={"knowledge.web_search", "world.news_headlines"}
        )
        p = Programme(
            programme_id="showcase-with-opt-ins",
            role=ProgrammeRole.SHOWCASE,
            planned_duration_s=60.0,
            parent_show_id="test",
            constraints=env,
        )
        store.add(p)
        reloaded = store.get("showcase-with-opt-ins")
        assert reloaded is not None
        assert reloaded.monetization_opt_ins == {
            "knowledge.web_search",
            "world.news_headlines",
        }


class TestAtomicWrite:
    def test_tmp_file_cleaned_up(self, store: ProgrammePlanStore) -> None:
        """After each write, no .tmp sibling remains."""
        store.add(_make_programme("a"))
        tmp = store.path.with_suffix(store.path.suffix + ".tmp")
        assert not tmp.exists()

    def test_activation_preserves_other_programmes(self, store: ProgrammePlanStore) -> None:
        """Rewrite on activate() must not drop unrelated programmes."""
        for pid in ("a", "b", "c"):
            store.add(_make_programme(pid, status=ProgrammeStatus.PENDING))
        store.activate("b", now=1000.0)
        all_ids = {p.programme_id for p in store.all()}
        assert all_ids == {"a", "b", "c"}
