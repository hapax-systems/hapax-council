from __future__ import annotations

import pytest

from shared.source_packet import (
    ResolvedSourceSet,
    SourcePacket,
    bind_source_hashes,
    validate_source_set,
)


def _packet(ref: str = "source:test.md", consequence: str = "scope narrows") -> SourcePacket:
    return SourcePacket(
        source_ref=ref,
        content_hash="abc123",
        snippet="test content",
        freshness="current",
        source_consequence=consequence,
    )


class TestSourcePacket:
    def test_creates_with_required_fields(self) -> None:
        p = _packet()
        assert p.source_ref == "source:test.md"
        assert p.freshness == "current"

    def test_frozen(self) -> None:
        p = _packet()
        with pytest.raises(Exception):
            p.source_ref = "hacked"  # type: ignore[misc]


class TestResolvedSourceSet:
    def test_requires_at_least_one_packet(self) -> None:
        with pytest.raises(Exception):
            ResolvedSourceSet(topic="test", packets=())

    def test_compute_set_hash_stable(self) -> None:
        s = ResolvedSourceSet(topic="test", packets=(_packet(),))
        h1 = s.compute_set_hash()
        h2 = s.compute_set_hash()
        assert h1 == h2
        assert len(h1) == 64


class TestValidateSourceSet:
    def test_valid_set_passes(self) -> None:
        s = ResolvedSourceSet(topic="test", packets=(_packet(),))
        result = validate_source_set(s)
        assert result["ok"]

    def test_missing_consequence_flagged(self) -> None:
        s = ResolvedSourceSet(topic="test", packets=(_packet(consequence=""),))
        result = validate_source_set(s)
        assert not result["ok"]
        assert any("source_consequence" in v for v in result["violations"])

    def test_stale_packet_flagged(self) -> None:
        p = SourcePacket(
            source_ref="source:old.md",
            content_hash="xyz",
            snippet="old data",
            freshness="stale",
            source_consequence="scope narrows",
        )
        s = ResolvedSourceSet(topic="test", packets=(p,))
        result = validate_source_set(s)
        assert not result["ok"]
        assert any("stale" in v for v in result["violations"])

    def test_duplicate_source_ref_flagged(self) -> None:
        s = ResolvedSourceSet(
            topic="test",
            packets=(_packet("source:a.md"), _packet("source:a.md")),
        )
        result = validate_source_set(s)
        assert not result["ok"]
        assert any("duplicate" in v for v in result["violations"])


class TestBindSourceHashes:
    def test_produces_set_hash(self) -> None:
        s = ResolvedSourceSet(topic="test", packets=(_packet(),))
        hashes = bind_source_hashes(s)
        assert "source_set_hash" in hashes
        assert len(hashes["source_set_hash"]) == 64

    def test_produces_per_packet_hashes(self) -> None:
        s = ResolvedSourceSet(topic="test", packets=(_packet(), _packet("source:b.md")))
        hashes = bind_source_hashes(s)
        assert "source_packet_0_hash" in hashes
        assert "source_packet_1_hash" in hashes
