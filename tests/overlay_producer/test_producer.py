"""Tests for ``agents.overlay_producer.producer``.

Coverage:

- Construction: rejects non-positive default TTL.
- ``tick`` with no sources / no candidates → no entries added,
  ``ProducerTickResult`` zeroed.
- ``tick`` adds candidates via ``TextRepo.add_entry`` with the source's
  body / context_keys / priority preserved.
- Default TTL applied when source omits ``expires_ts``; source-supplied
  ``expires_ts`` honored.
- Dedup-by-id: a candidate whose id is already in the repo is skipped
  and counted as ``skipped_existing``.
- Source exception is caught + counted in ``source_failures``; remaining
  sources still run.
- Zone-context propagation: candidate's ``context_keys`` reach the repo
  so ``select_for_context`` matches the right zone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.overlay_producer.producer import (
    DEFAULT_ENTRY_TTL_S,
    ContentSource,
    OverlayProducer,
    ProducerTickResult,
)
from shared.text_repo import TextEntry, TextRepo

# ── Test doubles ─────────────────────────────────────────────────────────


class _StaticSource:
    """Returns the same list of TextEntry objects on every collect."""

    def __init__(self, entries: list[TextEntry]) -> None:
        self._entries = list(entries)
        self.collect_count = 0

    def collect(self, now: float) -> list[TextEntry]:
        del now
        self.collect_count += 1
        return list(self._entries)


class _FailingSource:
    """Always raises — used to verify failure isolation."""

    def __init__(self) -> None:
        self.collect_count = 0

    def collect(self, now: float) -> list[TextEntry]:
        del now
        self.collect_count += 1
        raise RuntimeError("simulated source failure")


def _make_repo(tmp_path: Path) -> TextRepo:
    repo = TextRepo(path=tmp_path / "entries.jsonl")
    repo.load()
    return repo


def _make_entry(
    *,
    entry_id: str = "abc123",
    body: str = "hello",
    context_keys: list[str] | None = None,
    priority: int = 5,
    expires_ts: float | None = None,
    tags: list[str] | None = None,
) -> TextEntry:
    return TextEntry(
        id=entry_id,
        body=body,
        tags=tags or [],
        priority=priority,
        expires_ts=expires_ts,
        context_keys=context_keys or [],
    )


# ── Construction ─────────────────────────────────────────────────────────


class TestConstruction:
    def test_default_ttl_must_be_positive(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        with pytest.raises(ValueError, match="must be > 0"):
            OverlayProducer(repo=repo, sources=[], default_ttl_s=0)
        with pytest.raises(ValueError, match="must be > 0"):
            OverlayProducer(repo=repo, sources=[], default_ttl_s=-5.0)

    def test_constructs_with_no_sources(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        producer = OverlayProducer(repo=repo, sources=[])
        result = producer.tick(now=1000.0)
        assert result == ProducerTickResult(added=0, skipped_existing=0, source_failures=0)


# ── Tick behavior ────────────────────────────────────────────────────────


class TestTick:
    def test_no_candidates_yields_zero(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        source = _StaticSource(entries=[])
        producer = OverlayProducer(repo=repo, sources=[source])
        result = producer.tick(now=1000.0)
        assert result == ProducerTickResult(added=0, skipped_existing=0, source_failures=0)
        assert source.collect_count == 1

    def test_adds_candidate_to_repo(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        candidate = _make_entry(entry_id="git-001", body="[GIT] abc1234 hello")
        producer = OverlayProducer(repo=repo, sources=[_StaticSource(entries=[candidate])])
        result = producer.tick(now=1000.0)
        assert result.added == 1
        all_entries = repo.all_entries()
        assert len(all_entries) == 1
        stored = all_entries[0]
        assert stored.id == "git-001"
        assert stored.body == "[GIT] abc1234 hello"

    def test_default_ttl_applied_when_source_omits(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        candidate = _make_entry(entry_id="git-002", expires_ts=None)
        producer = OverlayProducer(repo=repo, sources=[_StaticSource(entries=[candidate])])
        producer.tick(now=1000.0)
        stored = repo.all_entries()[0]
        assert stored.expires_ts is not None
        assert stored.expires_ts == pytest.approx(1000.0 + DEFAULT_ENTRY_TTL_S)

    def test_source_supplied_ttl_honored(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        candidate = _make_entry(entry_id="git-003", expires_ts=2000.0)
        producer = OverlayProducer(repo=repo, sources=[_StaticSource(entries=[candidate])])
        producer.tick(now=1000.0)
        stored = repo.all_entries()[0]
        assert stored.expires_ts == pytest.approx(2000.0)

    def test_zone_context_keys_propagate(self, tmp_path: Path) -> None:
        """Producer must preserve ``context_keys`` so the compositor's
        ``select_for_context`` routes the entry to the right zone."""
        repo = _make_repo(tmp_path)
        candidate = _make_entry(
            entry_id="git-004",
            body="[GIT] xyz7890 commit",
            context_keys=["main"],
        )
        producer = OverlayProducer(repo=repo, sources=[_StaticSource(entries=[candidate])])
        # Use the same logical time for both ticks and the selector so
        # the default-TTL expiry doesn't excluded this entry.
        ts = 1000.0
        producer.tick(now=ts)
        picked = repo.select_for_context(activity="main", now=ts)
        assert picked is not None
        assert picked.id == "git-004"


# ── Dedup ────────────────────────────────────────────────────────────────


class TestDedup:
    def test_same_id_skipped_on_second_tick(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        candidate = _make_entry(entry_id="git-005")
        source = _StaticSource(entries=[candidate])
        producer = OverlayProducer(repo=repo, sources=[source])

        first = producer.tick(now=1000.0)
        assert first.added == 1
        assert first.skipped_existing == 0

        second = producer.tick(now=2000.0)
        assert second.added == 0
        assert second.skipped_existing == 1
        # Still only one entry in the repo.
        assert len(repo.all_entries()) == 1

    def test_different_ids_in_same_tick_both_added(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        candidates = [
            _make_entry(entry_id="git-006", body="commit-a"),
            _make_entry(entry_id="git-007", body="commit-b"),
        ]
        producer = OverlayProducer(repo=repo, sources=[_StaticSource(entries=candidates)])
        result = producer.tick(now=1000.0)
        assert result.added == 2
        assert result.skipped_existing == 0
        ids = {e.id for e in repo.all_entries()}
        assert ids == {"git-006", "git-007"}


# ── Failure isolation ────────────────────────────────────────────────────


class TestFailureIsolation:
    def test_failing_source_counted_does_not_block_others(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        good = _StaticSource(entries=[_make_entry(entry_id="git-008")])
        bad = _FailingSource()
        # Order: bad first, then good — proving the producer doesn't bail.
        producer = OverlayProducer(repo=repo, sources=[bad, good])
        result = producer.tick(now=1000.0)
        assert result.added == 1
        assert result.source_failures == 1
        assert good.collect_count == 1
        assert bad.collect_count == 1

    def test_satisfies_content_source_protocol(self) -> None:
        """The Protocol is structural — any object with ``.collect``
        satisfying the signature should be accepted."""
        source: ContentSource = _StaticSource(entries=[])
        assert callable(source.collect)
