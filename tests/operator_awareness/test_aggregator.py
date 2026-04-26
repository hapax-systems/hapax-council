"""Tests for ``agents.operator_awareness.aggregator``."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime

from agents.operator_awareness.aggregator import (
    Aggregator,
    collect_daimonion_block,
    collect_fleet_block,
    collect_health_block,
    collect_publishing_block,
    collect_refusals_recent,
    collect_sprint_block,
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


class TestSourceFailureMetric:
    """Spec acceptance criterion: per-source failure counter increments
    on the degraded-graceful path so operators can see source-level
    health from Grafana without scraping the daemon log."""

    def _label_value(self, source: str) -> float:
        from agents.operator_awareness.aggregator import (
            aggregator_source_failures_total,
        )

        return aggregator_source_failures_total.labels(source=source)._value.get()

    def test_health_corrupt_snapshot_increments(self, tmp_path):
        from agents.operator_awareness.aggregator import collect_health_block

        before = self._label_value("health_system")
        path = tmp_path / "infra.json"
        path.write_text("not json {")  # malformed → graceful degraded
        collect_health_block(path)
        assert self._label_value("health_system") == before + 1

    def test_health_non_dict_root_increments(self, tmp_path):
        """Schema mismatch (list root vs dict root) is also a failure."""
        import json as _j

        from agents.operator_awareness.aggregator import collect_health_block

        before = self._label_value("health_system")
        path = tmp_path / "infra.json"
        path.write_text(_j.dumps([{"x": 1}]))
        collect_health_block(path)
        assert self._label_value("health_system") == before + 1

    def test_health_missing_file_does_not_increment(self, tmp_path):
        """Pre-rollout (file absent) is not a failure — daemon hasn't started."""
        from agents.operator_awareness.aggregator import collect_health_block

        before = self._label_value("health_system")
        collect_health_block(tmp_path / "missing.json")
        assert self._label_value("health_system") == before

    def test_refusals_oserror_increments(self, monkeypatch, tmp_path):
        from agents.operator_awareness.aggregator import collect_refusals_recent

        before = self._label_value("refusals_recent")
        path = tmp_path / "log.jsonl"
        path.write_text("ok\n")  # exists, so we proceed past the absent check

        from pathlib import Path as _Path

        def _boom(*_a, **_kw):
            raise OSError("disk full")

        monkeypatch.setattr(_Path, "open", _boom)
        collect_refusals_recent(path)
        assert self._label_value("refusals_recent") == before + 1

    def test_stream_oserror_increments(self, monkeypatch, tmp_path):
        from agents.operator_awareness.aggregator import collect_stream_block

        before = self._label_value("stream")
        path = tmp_path / "events.jsonl"
        path.write_text("ok\n")

        from pathlib import Path as _Path

        def _boom(*_a, **_kw):
            raise OSError("disk full")

        monkeypatch.setattr(_Path, "open", _boom)
        collect_stream_block(path)
        assert self._label_value("stream") == before + 1


# ── collect_daimonion_block ────────────────────────────────────────


class TestCollectDaimonionBlock:
    def test_missing_file_returns_default(self, tmp_path):
        block = collect_daimonion_block(tmp_path / "absent.json")
        assert block.stance == "unknown"
        assert block.voice_session_active is False

    def test_reads_overall_stance(self, tmp_path):
        path = tmp_path / "stimmung.json"
        path.write_text(
            json.dumps({"overall_stance": "engaged", "health": {"value": 0.1}}),
            encoding="utf-8",
        )
        block = collect_daimonion_block(path)
        assert block.stance == "engaged"

    def test_missing_stance_field_yields_unknown(self, tmp_path):
        path = tmp_path / "stimmung.json"
        path.write_text(json.dumps({"health": {}}), encoding="utf-8")
        block = collect_daimonion_block(path)
        assert block.stance == "unknown"

    def test_malformed_json_returns_default(self, tmp_path):
        path = tmp_path / "stimmung.json"
        path.write_text("not json {", encoding="utf-8")
        block = collect_daimonion_block(path)
        assert block.stance == "unknown"


# ── collect_sprint_block ───────────────────────────────────────────


class TestCollectSprintBlock:
    def test_missing_file_returns_default(self, tmp_path):
        block = collect_sprint_block(tmp_path / "absent.json")
        assert block.sprint_id == ""
        assert block.sprint_day == 0
        assert block.completed_measures == 0
        assert block.blocked_measures == 0

    def test_maps_tracker_fields(self, tmp_path):
        path = tmp_path / "sprint.json"
        path.write_text(
            json.dumps(
                {
                    "current_sprint": 0,
                    "current_day": 28,
                    "measures_completed": 14,
                    "measures_blocked": 1,
                    "measures_total": 28,
                }
            ),
            encoding="utf-8",
        )
        block = collect_sprint_block(path)
        assert block.sprint_id == "0"  # int coerced to string
        assert block.sprint_day == 28
        assert block.completed_measures == 14
        assert block.blocked_measures == 1

    def test_string_sprint_id_preserved(self, tmp_path):
        path = tmp_path / "sprint.json"
        path.write_text(
            json.dumps({"current_sprint": "S2"}),
            encoding="utf-8",
        )
        block = collect_sprint_block(path)
        assert block.sprint_id == "S2"

    def test_malformed_json_returns_default(self, tmp_path):
        path = tmp_path / "sprint.json"
        path.write_text("not json", encoding="utf-8")
        block = collect_sprint_block(path)
        assert block.sprint_id == ""


# ── collect_fleet_block ────────────────────────────────────────────


class TestCollectFleetBlock:
    def test_missing_dir_returns_default(self, tmp_path):
        block = collect_fleet_block(tmp_path / "absent")
        assert block.pi_count_total == 0
        assert block.pi_count_online == 0

    def test_counts_role_files_excluding_cadence(self, tmp_path):
        # 3 role files + 2 cadence files (not heartbeats)
        for name in ("desk.json", "room.json", "overhead.json"):
            (tmp_path / name).write_text("{}", encoding="utf-8")
        for name in ("desk-cadence.json", "room-cadence.json"):
            (tmp_path / name).write_text("{}", encoding="utf-8")
        block = collect_fleet_block(tmp_path)
        assert block.pi_count_total == 3

    def test_online_count_uses_freshness_window(self, tmp_path):
        fresh = tmp_path / "desk.json"
        stale = tmp_path / "room.json"
        fresh.write_text("{}", encoding="utf-8")
        stale.write_text("{}", encoding="utf-8")
        # Make stale file 5 minutes old.
        old_mtime = time.time() - 300
        os.utime(stale, (old_mtime, old_mtime))
        block = collect_fleet_block(tmp_path, freshness_s=120.0)
        assert block.pi_count_total == 2
        assert block.pi_count_online == 1

    def test_path_to_file_returns_default(self, tmp_path):
        # Path exists but is not a directory.
        path = tmp_path / "not-a-dir.json"
        path.write_text("{}", encoding="utf-8")
        block = collect_fleet_block(path)
        assert block.pi_count_total == 0


# ── collect_publishing_block ───────────────────────────────────────


class TestCollectPublishingBlock:
    def test_missing_dir_returns_default(self, tmp_path):
        block = collect_publishing_block(tmp_path / "absent")
        assert block.inbox_count == 0
        assert block.in_flight_count == 0
        assert block.published_24h == 0
        assert block.last_publish_at is None

    def test_counts_inbox_and_draft_files(self, tmp_path):
        (tmp_path / "inbox").mkdir()
        (tmp_path / "draft").mkdir()
        (tmp_path / "inbox" / "a.json").write_text("{}", encoding="utf-8")
        (tmp_path / "inbox" / "b.json").write_text("{}", encoding="utf-8")
        (tmp_path / "draft" / "c.json").write_text("{}", encoding="utf-8")
        block = collect_publishing_block(tmp_path)
        assert block.inbox_count == 2
        assert block.in_flight_count == 1
        assert block.published_24h == 0
        assert block.last_publish_at is None

    def test_published_24h_window_filters_old(self, tmp_path):
        published = tmp_path / "published"
        published.mkdir()
        recent = published / "today.json"
        old = published / "month-old.json"
        recent.write_text("{}", encoding="utf-8")
        old.write_text("{}", encoding="utf-8")
        # Make old file 30 days old.
        old_mtime = time.time() - 30 * 86400
        os.utime(old, (old_mtime, old_mtime))
        block = collect_publishing_block(tmp_path)
        assert block.published_24h == 1
        # last_publish_at picks the max mtime → recent file.
        assert block.last_publish_at is not None

    def test_only_inbox_no_published_dir(self, tmp_path):
        # Common case: queue exists but no completed publishes yet.
        (tmp_path / "inbox").mkdir()
        (tmp_path / "inbox" / "queued.json").write_text("{}", encoding="utf-8")
        block = collect_publishing_block(tmp_path)
        assert block.inbox_count == 1
        assert block.published_24h == 0
        assert block.last_publish_at is None


# ── Aggregator with new sources wired ──────────────────────────────


class TestAggregatorAllSourcesWired:
    """Verifies the 4 new spec-mandated sources are wired in collect()."""

    def test_collect_populates_daimonion_from_stimmung(self, tmp_path):
        stimmung = tmp_path / "stim.json"
        stimmung.write_text(json.dumps({"overall_stance": "cautious"}), encoding="utf-8")
        agg = Aggregator(
            refusals_log_path=tmp_path / "absent1",
            infra_snapshot_path=tmp_path / "absent2",
            chronicle_events_path=tmp_path / "absent3",
            stimmung_state_path=stimmung,
        )
        state = agg.collect()
        assert state.daimonion_voice.stance == "cautious"

    def test_collect_populates_sprint(self, tmp_path):
        sprint = tmp_path / "sprint.json"
        sprint.write_text(
            json.dumps(
                {
                    "current_sprint": 1,
                    "current_day": 5,
                    "measures_completed": 3,
                    "measures_blocked": 0,
                }
            ),
            encoding="utf-8",
        )
        agg = Aggregator(
            refusals_log_path=tmp_path / "absent1",
            infra_snapshot_path=tmp_path / "absent2",
            chronicle_events_path=tmp_path / "absent3",
            sprint_state_path=sprint,
        )
        state = agg.collect()
        assert state.time_sprint.sprint_id == "1"
        assert state.time_sprint.sprint_day == 5
        assert state.time_sprint.completed_measures == 3

    def test_collect_populates_fleet_from_pi_noir_dir(self, tmp_path):
        pi_noir = tmp_path / "pi-noir"
        pi_noir.mkdir()
        (pi_noir / "desk.json").write_text("{}", encoding="utf-8")
        (pi_noir / "overhead.json").write_text("{}", encoding="utf-8")
        agg = Aggregator(
            refusals_log_path=tmp_path / "absent1",
            infra_snapshot_path=tmp_path / "absent2",
            chronicle_events_path=tmp_path / "absent3",
            pi_noir_dir=pi_noir,
        )
        state = agg.collect()
        assert state.hardware_fleet.pi_count_total == 2

    def test_collect_populates_publishing(self, tmp_path):
        publish = tmp_path / "publish"
        (publish / "inbox").mkdir(parents=True)
        (publish / "inbox" / "a.json").write_text("{}", encoding="utf-8")
        agg = Aggregator(
            refusals_log_path=tmp_path / "absent1",
            infra_snapshot_path=tmp_path / "absent2",
            chronicle_events_path=tmp_path / "absent3",
            publish_dir=publish,
        )
        state = agg.collect()
        assert state.publishing_pipeline.inbox_count == 1


# ── Source failure metric — new sources ────────────────────────────


class TestNewSourceFailureMetrics:
    def _label_value(self, source: str) -> float:
        from agents.operator_awareness.aggregator import (
            aggregator_source_failures_total,
        )

        return aggregator_source_failures_total.labels(source=source)._value.get()

    def test_daimonion_malformed_increments(self, tmp_path):
        before = self._label_value("daimonion_voice")
        path = tmp_path / "stim.json"
        path.write_text("not json", encoding="utf-8")
        collect_daimonion_block(path)
        assert self._label_value("daimonion_voice") == before + 1

    def test_sprint_malformed_increments(self, tmp_path):
        before = self._label_value("time_sprint")
        path = tmp_path / "sprint.json"
        path.write_text("[1,2,3]", encoding="utf-8")  # list root, not dict
        collect_sprint_block(path)
        assert self._label_value("time_sprint") == before + 1

    def test_daimonion_missing_does_not_increment(self, tmp_path):
        before = self._label_value("daimonion_voice")
        collect_daimonion_block(tmp_path / "missing.json")
        assert self._label_value("daimonion_voice") == before

    def test_sprint_missing_does_not_increment(self, tmp_path):
        before = self._label_value("time_sprint")
        collect_sprint_block(tmp_path / "missing.json")
        assert self._label_value("time_sprint") == before
