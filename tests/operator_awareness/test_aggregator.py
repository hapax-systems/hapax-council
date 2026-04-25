"""Tests for ``agents.operator_awareness.aggregator``."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

from agents.operator_awareness.aggregator import (
    Aggregator,
    collect_health_block,
    collect_refusals_recent,
    collect_stream_block,
)
from agents.operator_awareness.state import HealthBlock


def _now() -> datetime:
    return datetime.now(UTC)


# ── collect_refusals_recent ────────────────────────────────────────


class TestCollectRefusalsRecent:
    def test_missing_file_returns_empty(self, tmp_path):
        assert collect_refusals_recent(tmp_path / "absent.jsonl") == []

    def test_empty_file_returns_empty(self, tmp_path):
        path = tmp_path / "log.jsonl"
        path.touch()
        assert collect_refusals_recent(path) == []

    def test_yields_well_formed_events(self, tmp_path):
        path = tmp_path / "log.jsonl"
        path.write_text(
            json.dumps(
                {
                    "timestamp": _now().isoformat(),
                    "surface": "twitter",
                    "reason": "ToS prohibits automation",
                }
            )
            + "\n"
            + json.dumps(
                {
                    "timestamp": _now().isoformat(),
                    "surface": "linkedin",
                    "reason": "ToS §8.2",
                    "refused_artifact_slug": "constitutional-brief",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        events = collect_refusals_recent(path)
        assert len(events) == 2
        assert events[0].surface == "twitter"
        assert events[1].refused_artifact_slug == "constitutional-brief"

    def test_skips_malformed_json(self, tmp_path):
        path = tmp_path / "log.jsonl"
        path.write_text(
            "not json\n"
            + json.dumps({"timestamp": _now().isoformat(), "surface": "x", "reason": "y"})
            + "\n",
            encoding="utf-8",
        )
        events = collect_refusals_recent(path)
        assert len(events) == 1
        assert events[0].surface == "x"

    def test_skips_missing_required_fields(self, tmp_path):
        path = tmp_path / "log.jsonl"
        path.write_text(
            json.dumps({"surface": "x", "reason": "y"})
            + "\n"  # no timestamp
            + json.dumps({"timestamp": _now().isoformat(), "reason": "y"})
            + "\n"  # no surface
            + json.dumps({"timestamp": _now().isoformat(), "surface": "z", "reason": "kept"})
            + "\n",
            encoding="utf-8",
        )
        events = collect_refusals_recent(path)
        assert len(events) == 1
        assert events[0].surface == "z"

    def test_caps_at_limit(self, tmp_path):
        path = tmp_path / "log.jsonl"
        ts = _now().isoformat()
        lines = [
            json.dumps({"timestamp": ts, "surface": f"s{i}", "reason": "r"}) for i in range(100)
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        events = collect_refusals_recent(path, limit=10)
        assert len(events) == 10
        # Deque keeps the LAST 10.
        assert events[0].surface == "s90"
        assert events[-1].surface == "s99"

    def test_naive_timestamp_assumed_utc(self, tmp_path):
        path = tmp_path / "log.jsonl"
        naive = datetime.now(UTC).replace(tzinfo=None).isoformat()
        path.write_text(
            json.dumps({"timestamp": naive, "surface": "x", "reason": "y"}) + "\n",
            encoding="utf-8",
        )
        events = collect_refusals_recent(path)
        assert len(events) == 1
        assert events[0].timestamp.tzinfo is not None


# ── collect_health_block ──────────────────────────────────────────


class TestCollectHealthBlock:
    def test_missing_snapshot_returns_unknown(self, tmp_path):
        block = collect_health_block(tmp_path / "absent.json")
        assert block == HealthBlock()  # unknown / zero defaults

    def test_classifies_healthy(self, tmp_path):
        path = tmp_path / "snap.json"
        path.write_text(
            json.dumps(
                {
                    "systemd": {"failed_count": 0},
                    "docker": {"failed_count": 0},
                    "disk": {"pct_used": 40.0},
                    "gpu": {"used_mb": 1000, "total_mb": 24000},
                }
            ),
            encoding="utf-8",
        )
        block = collect_health_block(path)
        assert block.overall_status == "healthy"
        assert block.failed_units == 0
        assert block.disk_pct_used == 40.0

    def test_degraded_on_docker_failure(self, tmp_path):
        path = tmp_path / "snap.json"
        path.write_text(
            json.dumps(
                {
                    "systemd": {"failed_count": 0},
                    "docker": {"failed_count": 1},
                    "disk": {"pct_used": 50.0},
                    "gpu": {"used_mb": 0, "total_mb": 24000},
                }
            ),
            encoding="utf-8",
        )
        block = collect_health_block(path)
        assert block.overall_status == "degraded"
        assert block.docker_containers_failed == 1

    def test_degraded_on_high_gpu(self, tmp_path):
        path = tmp_path / "snap.json"
        path.write_text(
            json.dumps(
                {
                    "systemd": {"failed_count": 0},
                    "docker": {"failed_count": 0},
                    "disk": {"pct_used": 30.0},
                    "gpu": {"used_mb": 23000, "total_mb": 24000},
                }
            ),
            encoding="utf-8",
        )
        block = collect_health_block(path)
        assert block.overall_status == "degraded"

    def test_critical_on_systemd_failure(self, tmp_path):
        path = tmp_path / "snap.json"
        path.write_text(
            json.dumps(
                {
                    "systemd": {"failed_count": 2},
                    "docker": {"failed_count": 0},
                    "disk": {"pct_used": 50.0},
                    "gpu": {"used_mb": 0, "total_mb": 24000},
                }
            ),
            encoding="utf-8",
        )
        block = collect_health_block(path)
        assert block.overall_status == "critical"

    def test_critical_on_disk_full(self, tmp_path):
        path = tmp_path / "snap.json"
        path.write_text(
            json.dumps(
                {
                    "systemd": {"failed_count": 0},
                    "docker": {"failed_count": 0},
                    "disk": {"pct_used": 95.0},
                    "gpu": {"used_mb": 0, "total_mb": 24000},
                }
            ),
            encoding="utf-8",
        )
        block = collect_health_block(path)
        assert block.overall_status == "critical"

    def test_corrupt_snapshot_returns_default(self, tmp_path):
        path = tmp_path / "snap.json"
        path.write_text("not json", encoding="utf-8")
        block = collect_health_block(path)
        assert block.overall_status == "unknown"


# ── collect_stream_block ──────────────────────────────────────────


class TestCollectStreamBlock:
    def test_missing_file_returns_offline(self, tmp_path):
        block = collect_stream_block(tmp_path / "absent.jsonl")
        assert block.live is False
        assert block.chronicle_events_5min == 0

    def test_no_recent_events_offline(self, tmp_path):
        path = tmp_path / "events.jsonl"
        old_ts = time.time() - 600  # 10 min ago
        path.write_text(
            json.dumps({"ts": old_ts, "event_type": "test"}) + "\n",
            encoding="utf-8",
        )
        block = collect_stream_block(path, now=time.time())
        assert block.live is False
        assert block.chronicle_events_5min == 0

    def test_recent_events_live(self, tmp_path):
        path = tmp_path / "events.jsonl"
        now = time.time()
        path.write_text(
            "\n".join(json.dumps({"ts": now - i * 30, "event_type": "test"}) for i in range(8))
            + "\n",
            encoding="utf-8",
        )
        block = collect_stream_block(path, now=now)
        assert block.live is True
        # 5min window covers ts >= now-300, so events at -0..-240 (i=0..8) → 8 events.
        assert block.chronicle_events_5min == 8

    def test_skips_malformed_lines(self, tmp_path):
        path = tmp_path / "events.jsonl"
        now = time.time()
        path.write_text(
            "not json\n" + json.dumps({"ts": now, "event_type": "test"}) + "\n" + "{broken\n",
            encoding="utf-8",
        )
        block = collect_stream_block(path, now=now)
        assert block.chronicle_events_5min == 1


# ── Aggregator.collect ────────────────────────────────────────────


class TestAggregatorCollect:
    def test_assembles_full_state(self, tmp_path):
        # Write all 3 sources.
        refusals = tmp_path / "refusals.jsonl"
        refusals.write_text(
            json.dumps(
                {
                    "timestamp": _now().isoformat(),
                    "surface": "x",
                    "reason": "y",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        infra = tmp_path / "infra.json"
        infra.write_text(
            json.dumps(
                {
                    "systemd": {"failed_count": 0},
                    "docker": {"failed_count": 0},
                    "disk": {"pct_used": 30.0},
                    "gpu": {"used_mb": 0, "total_mb": 24000},
                }
            ),
            encoding="utf-8",
        )
        chronicle = tmp_path / "chronicle.jsonl"
        chronicle.write_text(
            json.dumps({"ts": time.time(), "event_type": "x"}) + "\n",
            encoding="utf-8",
        )

        agg = Aggregator(
            refusals_log_path=refusals,
            infra_snapshot_path=infra,
            chronicle_events_path=chronicle,
        )
        state = agg.collect()

        # All 3 wired sources populate.
        assert len(state.refusals_recent) == 1
        assert state.health_system.overall_status == "healthy"
        assert state.stream.live is True
        # Phase-3 sources keep default-empty (Aggregator doesn't error
        # by leaving them unwired; the spec calls this graceful
        # degradation explicitly).
        assert state.marketing_outreach.pending_count == 0
        assert state.publishing_pipeline.inbox_count == 0

    def test_all_sources_missing_yields_default_state(self, tmp_path):
        agg = Aggregator(
            refusals_log_path=tmp_path / "absent1.jsonl",
            infra_snapshot_path=tmp_path / "absent2.json",
            chronicle_events_path=tmp_path / "absent3.jsonl",
        )
        state = agg.collect()
        # No source crashes; every block falls back to default.
        assert state.refusals_recent == []
        assert state.health_system.overall_status == "unknown"
        assert state.stream.live is False

    def test_clock_override(self, tmp_path):
        fixed = datetime(2026, 4, 25, 22, 0, 0, tzinfo=UTC)
        agg = Aggregator(
            refusals_log_path=tmp_path / "a.jsonl",
            infra_snapshot_path=tmp_path / "b.json",
            chronicle_events_path=tmp_path / "c.jsonl",
            clock=lambda: fixed,
        )
        state = agg.collect()
        assert state.timestamp == fixed
