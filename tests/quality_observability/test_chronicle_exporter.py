"""Chronicle quality exporter pins.

Pins:
- the rolling-window aggregations (salience mean, intent cardinality,
  material distribution, grounding coverage, per-source event rate)
  against fixture chronicle files with known content,
- graceful handling of malformed events / missing payload fields,
- the chronicle-unreadable failure mode (no raise, stale gauges, single
  warning log).

Each test uses an isolated `CollectorRegistry` so metric state doesn't
leak across tests.

Spec: ytb-QM1.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry

from agents.quality_observability.chronicle_exporter import (
    CANONICAL_MATERIALS,
    WINDOW_1H_S,
    WINDOW_5M_S,
    ChronicleQualityExporter,
)


def _write_chronicle(path: Path, events: Iterable[dict]) -> None:
    """Write a list of event dicts as JSONL — match shared.chronicle format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for ev in events:
            full = {
                "ts": ev["ts"],
                "trace_id": ev.get("trace_id", "0" * 32),
                "span_id": ev.get("span_id", "0" * 16),
                "parent_span_id": ev.get("parent_span_id"),
                "source": ev["source"],
                "event_type": ev["event_type"],
                "payload": ev.get("payload", {}),
            }
            fh.write(json.dumps(full) + "\n")


@pytest.fixture
def chronicle_path(tmp_path: Path) -> Path:
    return tmp_path / "events.jsonl"


@pytest.fixture
def now() -> float:
    return 1000000.0  # fixed epoch reference


@pytest.fixture
def make_exporter(chronicle_path: Path):
    def _factory() -> ChronicleQualityExporter:
        return ChronicleQualityExporter(
            chronicle_path=chronicle_path,
            registry=CollectorRegistry(),
        )

    return _factory


# ── Salience ──────────────────────────────────────────────────────────


class TestSalience:
    def test_mean_over_5m_window(self, chronicle_path: Path, make_exporter, now: float) -> None:
        # 4 events in window with salience [0.2, 0.4, 0.6, 0.8] → mean 0.5.
        # 1 event outside the window with salience 0.1 — must be excluded.
        _write_chronicle(
            chronicle_path,
            [
                {
                    "ts": now - 600,
                    "source": "x",
                    "event_type": "e",
                    "payload": {"salience": 0.1},
                },  # outside window
                {"ts": now - 200, "source": "x", "event_type": "e", "payload": {"salience": 0.2}},
                {"ts": now - 100, "source": "x", "event_type": "e", "payload": {"salience": 0.4}},
                {"ts": now - 50, "source": "x", "event_type": "e", "payload": {"salience": 0.6}},
                {"ts": now - 10, "source": "x", "event_type": "e", "payload": {"salience": 0.8}},
            ],
        )
        exp = make_exporter()
        exp.tick_once(now=now)
        # Read the gauge value directly via the underlying metric API.
        assert exp.salience_mean_5m._value.get() == pytest.approx(0.5)

    def test_no_salience_events_yields_nan(
        self, chronicle_path: Path, make_exporter, now: float
    ) -> None:
        _write_chronicle(
            chronicle_path,
            [
                {"ts": now - 50, "source": "x", "event_type": "e", "payload": {"other_field": 0.5}},
            ],
        )
        exp = make_exporter()
        exp.tick_once(now=now)
        assert math.isnan(exp.salience_mean_5m._value.get())

    def test_distribution_observes_each_value(
        self, chronicle_path: Path, make_exporter, now: float
    ) -> None:
        _write_chronicle(
            chronicle_path,
            [
                {"ts": now - 50, "source": "x", "event_type": "e", "payload": {"salience": 0.15}},
                {"ts": now - 40, "source": "x", "event_type": "e", "payload": {"salience": 0.85}},
            ],
        )
        exp = make_exporter()
        exp.tick_once(now=now)
        # Histogram should have 2 observations total.
        assert exp.salience_distribution._sum.get() == pytest.approx(1.0)


class TestSalienceCoercion:
    @pytest.mark.parametrize(
        "value",
        [True, False, None, "0.5", [], {}, "not a number"],
    )
    def test_non_numeric_salience_skipped(
        self, chronicle_path: Path, make_exporter, now: float, value: object
    ) -> None:
        _write_chronicle(
            chronicle_path,
            [
                {"ts": now - 50, "source": "x", "event_type": "e", "payload": {"salience": value}},
                {"ts": now - 40, "source": "x", "event_type": "e", "payload": {"salience": 0.7}},
            ],
        )
        exp = make_exporter()
        exp.tick_once(now=now)
        # Only the 0.7 event contributes — mean should be 0.7, not crash.
        assert exp.salience_mean_5m._value.get() == pytest.approx(0.7)


# ── Intent family cardinality ──────────────────────────────────────────


class TestIntentFamilyCardinality:
    def test_distinct_count_over_1h_window(
        self, chronicle_path: Path, make_exporter, now: float
    ) -> None:
        # Chronological write order (oldest first) so the reverse-walk
        # query reads newest first and early-exits cleanly at the
        # window boundary.
        _write_chronicle(
            chronicle_path,
            [
                # Outside window — should NOT count. Written first so it's
                # at the FRONT of the file (last seen in reverse walk).
                {
                    "ts": now - WINDOW_1H_S - 10,
                    "source": "x",
                    "event_type": "e",
                    "payload": {"intent_family": "stale.family"},
                },
                # 3 distinct families inside the 1h window.
                {
                    "ts": now - 1000,
                    "source": "x",
                    "event_type": "e",
                    "payload": {"intent_family": "narrative.autonomous"},
                },
                {
                    "ts": now - 500,
                    "source": "x",
                    "event_type": "e",
                    "payload": {"intent_family": "narrative.autonomous"},
                },  # dup
                {
                    "ts": now - 100,
                    "source": "x",
                    "event_type": "e",
                    "payload": {"intent_family": "content.too-similar"},
                },
                {
                    "ts": now - 10,
                    "source": "x",
                    "event_type": "e",
                    "payload": {"intent_family": "youtube.direction"},
                },
            ],
        )
        exp = make_exporter()
        exp.tick_once(now=now)
        assert exp.intent_family_cardinality_1h._value.get() == 3

    def test_no_intent_families_yields_zero(
        self, chronicle_path: Path, make_exporter, now: float
    ) -> None:
        _write_chronicle(
            chronicle_path,
            [{"ts": now - 50, "source": "x", "event_type": "e", "payload": {}}],
        )
        exp = make_exporter()
        exp.tick_once(now=now)
        assert exp.intent_family_cardinality_1h._value.get() == 0


# ── Material distribution ──────────────────────────────────────────────


class TestMaterialDistribution:
    def test_canonical_materials_pre_zeroed(self, make_exporter) -> None:
        """Even without a tick, all 5 canonical materials should be exported."""
        exp = make_exporter()
        for material in CANONICAL_MATERIALS:
            assert exp.material_distribution.labels(material=material)._value.get() == 0.0

    def test_fractions_sum_to_one(self, chronicle_path: Path, make_exporter, now: float) -> None:
        # 2 water + 1 fire + 1 earth = 4 events. Fractions: 0.5/0.25/0.25/0/0
        _write_chronicle(
            chronicle_path,
            [
                {
                    "ts": now - 50,
                    "source": "x",
                    "event_type": "e",
                    "payload": {"material": "water"},
                },
                {
                    "ts": now - 40,
                    "source": "x",
                    "event_type": "e",
                    "payload": {"material": "water"},
                },
                {"ts": now - 30, "source": "x", "event_type": "e", "payload": {"material": "fire"}},
                {
                    "ts": now - 20,
                    "source": "x",
                    "event_type": "e",
                    "payload": {"material": "earth"},
                },
            ],
        )
        exp = make_exporter()
        exp.tick_once(now=now)
        d = exp.material_distribution
        assert d.labels(material="water")._value.get() == pytest.approx(0.5)
        assert d.labels(material="fire")._value.get() == pytest.approx(0.25)
        assert d.labels(material="earth")._value.get() == pytest.approx(0.25)
        assert d.labels(material="air")._value.get() == 0.0
        assert d.labels(material="void")._value.get() == 0.0

    def test_unknown_material_skipped(
        self, chronicle_path: Path, make_exporter, now: float
    ) -> None:
        _write_chronicle(
            chronicle_path,
            [
                {
                    "ts": now - 50,
                    "source": "x",
                    "event_type": "e",
                    "payload": {"material": "plasma"},
                },  # not canonical
                {
                    "ts": now - 40,
                    "source": "x",
                    "event_type": "e",
                    "payload": {"material": "water"},
                },
            ],
        )
        exp = make_exporter()
        exp.tick_once(now=now)
        # Only the water event counts; fraction = 1/1 = 1.0.
        assert exp.material_distribution.labels(material="water")._value.get() == 1.0
        # No "plasma" label registered.


# ── Grounding coverage ─────────────────────────────────────────────────


class TestGroundingCoverage:
    def test_fraction_with_grounding(self, chronicle_path: Path, make_exporter, now: float) -> None:
        _write_chronicle(
            chronicle_path,
            [
                {
                    "ts": now - 50,
                    "source": "x",
                    "event_type": "e",
                    "payload": {"grounding_provenance": ["ref-1"]},
                },
                {
                    "ts": now - 40,
                    "source": "x",
                    "event_type": "e",
                    "payload": {"grounding_provenance": []},
                },  # claims to be groundable but empty
                {
                    "ts": now - 30,
                    "source": "x",
                    "event_type": "e",
                    "payload": {"grounding_provenance": ["ref-2", "ref-3"]},
                },
                # Field absent — does NOT count toward considered.
                {"ts": now - 20, "source": "x", "event_type": "e", "payload": {}},
            ],
        )
        exp = make_exporter()
        exp.tick_once(now=now)
        # Considered: 3 (events with the field). Grounded: 2 (non-empty list).
        assert exp.grounding_coverage_5m._value.get() == pytest.approx(2.0 / 3.0)

    def test_synthetic_only_grounding_does_not_count_as_grounded(
        self, chronicle_path: Path, make_exporter, now: float
    ) -> None:
        _write_chronicle(
            chronicle_path,
            [
                {
                    "ts": now - 50,
                    "source": "x",
                    "event_type": "e",
                    "payload": {"grounding_provenance": ["fallback.parser_non_dict"]},
                },
                {
                    "ts": now - 40,
                    "source": "x",
                    "event_type": "e",
                    "payload": {"grounding_provenance": ["inferred.nominal.camera.hero"]},
                },
                {
                    "ts": now - 30,
                    "source": "x",
                    "event_type": "e",
                    "payload": {
                        "grounding_provenance": [
                            "fallback.micromove.llm_empty",
                            "audio.contact_mic.desk_activity",
                        ]
                    },
                },
            ],
        )
        exp = make_exporter()
        exp.tick_once(now=now)
        assert exp.grounding_coverage_5m._value.get() == pytest.approx(1.0 / 3.0)

    def test_no_groundable_events_yields_nan(
        self, chronicle_path: Path, make_exporter, now: float
    ) -> None:
        _write_chronicle(
            chronicle_path,
            [{"ts": now - 50, "source": "x", "event_type": "e", "payload": {}}],
        )
        exp = make_exporter()
        exp.tick_once(now=now)
        assert math.isnan(exp.grounding_coverage_5m._value.get())


# ── Event rate per source ──────────────────────────────────────────────


class TestEventRate:
    def test_per_source_events_per_minute(
        self, chronicle_path: Path, make_exporter, now: float
    ) -> None:
        # 10 events from "visual" + 5 from "voice" in 5 min window.
        # → visual = 2/min, voice = 1/min.
        events = []
        for i in range(10):
            events.append(
                {
                    "ts": now - (i * 10),
                    "source": "visual",
                    "event_type": "e",
                    "payload": {},
                }
            )
        for i in range(5):
            events.append(
                {
                    "ts": now - (i * 20),
                    "source": "voice",
                    "event_type": "e",
                    "payload": {},
                }
            )
        _write_chronicle(chronicle_path, events)
        exp = make_exporter()
        exp.tick_once(now=now)
        assert exp.event_rate_per_min.labels(source="visual")._value.get() == pytest.approx(2.0)
        assert exp.event_rate_per_min.labels(source="voice")._value.get() == pytest.approx(1.0)


# ── Failure modes ──────────────────────────────────────────────────────


class TestMalformedEvents:
    def test_malformed_jsonl_lines_dropped(
        self, chronicle_path: Path, make_exporter, now: float
    ) -> None:
        # Mix valid + malformed lines; tick must succeed.
        chronicle_path.parent.mkdir(parents=True, exist_ok=True)
        with chronicle_path.open("w", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "ts": now - 50,
                        "trace_id": "0" * 32,
                        "span_id": "0" * 16,
                        "parent_span_id": None,
                        "source": "x",
                        "event_type": "e",
                        "payload": {"salience": 0.5},
                    }
                )
                + "\n"
            )
            fh.write("not json at all\n")
            fh.write('{"truncated":\n')  # invalid JSON
            fh.write("\n")  # empty line
        exp = make_exporter()
        exp.tick_once(now=now)
        # The 1 valid event with salience=0.5 should land.
        assert exp.salience_mean_5m._value.get() == pytest.approx(0.5)

    def test_chronicle_missing_yields_stale_gauges_no_raise(
        self, tmp_path: Path, make_exporter
    ) -> None:
        # chronicle_path fixture already pointed at tmp_path / "events.jsonl"
        # which doesn't exist yet. Tick must not raise; metrics stay at default.
        exp = make_exporter()
        exp.tick_once()  # no exception
        # Gauges still report (default 0 for raw Gauge).
        assert exp.intent_family_cardinality_1h._value.get() == 0


# ── Window boundary ───────────────────────────────────────────────────


class TestWindowBoundary:
    def test_event_exactly_at_window_edge_included(
        self, chronicle_path: Path, make_exporter, now: float
    ) -> None:
        # Event AT the 5-minute boundary should count (>= since).
        # Chronological order: outside event first (oldest), boundary
        # event second (newest) — so reverse-walk visits the boundary
        # event first and the outside event last, triggering early-exit.
        _write_chronicle(
            chronicle_path,
            [
                {
                    "ts": now - WINDOW_5M_S - 0.001,
                    "source": "x",
                    "event_type": "e",
                    "payload": {"salience": 0.99},
                },  # just outside, must NOT count
                {
                    "ts": now - WINDOW_5M_S,
                    "source": "x",
                    "event_type": "e",
                    "payload": {"salience": 0.4},
                },
            ],
        )
        exp = make_exporter()
        exp.tick_once(now=now)
        # Only the 0.4 event should land in the 5m window.
        assert exp.salience_mean_5m._value.get() == pytest.approx(0.4)


# ── Default port boundary ──────────────────────────────────────────────


class TestPortAllocation:
    def test_default_port_does_not_collide_with_cuepoints(self) -> None:
        """9494 is taken by hapax-live-cuepoints; we must use 9495+."""
        from agents.quality_observability.chronicle_exporter import METRICS_PORT

        assert METRICS_PORT >= 9495
