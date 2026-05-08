"""Tests for shared.team_registry — Pydantic models, registry, and freshness gate.

ISAP: SLICE-003A-TEAM-METADATA (CASE-SDLC-REFORM-001)
"""

from __future__ import annotations

import time
from pathlib import Path

from shared.team_registry import (
    FreshnessReceipt,
    LaneMetadata,
    TeamRegistry,
    freshness_gate,
)


def _make_meta(
    lane_id: str = "alpha",
    last_probe: float = 0.0,
    ttl: float = 3600.0,
) -> LaneMetadata:
    return LaneMetadata(
        lane_id=lane_id,
        platform="claude-code",
        model_id="claude-opus-4-6",
        context_window=1_000_000,
        tools_available=["Edit", "Bash"],
        last_probe_utc=last_probe,
        freshness_ttl_s=ttl,
    )


class TestLaneMetadata:
    def test_fresh_when_recent(self) -> None:
        now = time.time()
        m = _make_meta(last_probe=now - 100, ttl=3600)
        assert m.freshness(now) == "fresh"

    def test_stale_when_old(self) -> None:
        now = time.time()
        m = _make_meta(last_probe=now - 7200, ttl=3600)
        assert m.freshness(now) == "stale"

    def test_unknown_when_never_probed(self) -> None:
        m = _make_meta(last_probe=0.0)
        assert m.freshness() == "unknown"

    def test_age_seconds(self) -> None:
        now = time.time()
        m = _make_meta(last_probe=now - 500)
        assert abs(m.age_seconds(now) - 500) < 1

    def test_age_infinite_when_never_probed(self) -> None:
        m = _make_meta(last_probe=0.0)
        assert m.age_seconds() == float("inf")

    def test_boundary_fresh_at_exact_ttl(self) -> None:
        now = time.time()
        m = _make_meta(last_probe=now - 3600, ttl=3600)
        assert m.freshness(now) == "fresh"

    def test_stale_one_second_past_ttl(self) -> None:
        now = time.time()
        m = _make_meta(last_probe=now - 3601, ttl=3600)
        assert m.freshness(now) == "stale"


class TestTeamRegistry:
    def test_write_and_read(self, tmp_path: Path) -> None:
        reg = TeamRegistry(tmp_path)
        m = _make_meta("beta", last_probe=time.time())
        reg.write(m)
        loaded = reg.read("beta")
        assert loaded is not None
        assert loaded.lane_id == "beta"
        assert loaded.model_id == "claude-opus-4-6"

    def test_read_missing(self, tmp_path: Path) -> None:
        reg = TeamRegistry(tmp_path)
        assert reg.read("nonexistent") is None

    def test_all_lanes(self, tmp_path: Path) -> None:
        reg = TeamRegistry(tmp_path)
        for name in ("alpha", "beta", "gamma"):
            reg.write(_make_meta(name, last_probe=time.time()))
        lanes = reg.all_lanes()
        assert len(lanes) == 3
        assert {m.lane_id for m in lanes} == {"alpha", "beta", "gamma"}

    def test_fresh_lanes_filters(self, tmp_path: Path) -> None:
        now = time.time()
        reg = TeamRegistry(tmp_path)
        reg.write(_make_meta("fresh-lane", last_probe=now - 100, ttl=3600))
        reg.write(_make_meta("stale-lane", last_probe=now - 7200, ttl=3600))
        fresh = reg.fresh_lanes(now)
        stale = reg.stale_lanes(now)
        assert len(fresh) == 1
        assert fresh[0].lane_id == "fresh-lane"
        assert len(stale) == 1
        assert stale[0].lane_id == "stale-lane"

    def test_check_freshness_missing(self, tmp_path: Path) -> None:
        reg = TeamRegistry(tmp_path)
        receipt = reg.check_freshness("missing")
        assert receipt.result == "unknown"
        assert "no metadata file" in receipt.blockers

    def test_check_freshness_fresh(self, tmp_path: Path) -> None:
        now = time.time()
        reg = TeamRegistry(tmp_path)
        reg.write(_make_meta("ok", last_probe=now - 10, ttl=3600))
        receipt = reg.check_freshness("ok", now=now)
        assert receipt.result == "fresh"
        assert receipt.blockers == []

    def test_check_freshness_stale(self, tmp_path: Path) -> None:
        now = time.time()
        reg = TeamRegistry(tmp_path)
        reg.write(_make_meta("old", last_probe=now - 7200, ttl=3600))
        receipt = reg.check_freshness("old", now=now)
        assert receipt.result == "stale"
        assert len(receipt.blockers) == 1

    def test_remove(self, tmp_path: Path) -> None:
        reg = TeamRegistry(tmp_path)
        reg.write(_make_meta("doomed", last_probe=time.time()))
        assert reg.remove("doomed")
        assert reg.read("doomed") is None
        assert not reg.remove("doomed")


class TestFreshnessGate:
    def test_gate_fresh(self, tmp_path: Path) -> None:
        now = time.time()
        reg = TeamRegistry(tmp_path)
        reg.write(_make_meta("alpha", last_probe=now - 60, ttl=3600))
        receipt = freshness_gate("alpha", registry=reg, now=now)
        assert receipt.result == "fresh"

    def test_gate_blocks_stale(self, tmp_path: Path) -> None:
        now = time.time()
        reg = TeamRegistry(tmp_path)
        reg.write(_make_meta("alpha", last_probe=now - 7200, ttl=3600))
        receipt = freshness_gate("alpha", registry=reg, now=now)
        assert receipt.result == "stale"

    def test_gate_blocks_unknown(self, tmp_path: Path) -> None:
        reg = TeamRegistry(tmp_path)
        receipt = freshness_gate("nonexistent", registry=reg)
        assert receipt.result == "unknown"


class TestFreshnessReceipt:
    def test_receipt_serialization(self) -> None:
        r = FreshnessReceipt(
            lane_id="alpha",
            platform="claude-code",
            model_id="claude-opus-4-6",
            checked_at=time.time(),
            checked_by="test",
            result="fresh",
            stale_after=time.time() + 3600,
        )
        data = r.model_dump()
        assert data["result"] == "fresh"
        roundtrip = FreshnessReceipt.model_validate(data)
        assert roundtrip.lane_id == "alpha"
