"""Tests for shared.stream_transition_gate (LRR Phase 6 §5 + §6)."""

from __future__ import annotations

import json

import pytest

from shared.stream_mode import StreamMode
from shared.stream_transition_gate import (
    presence_t0_gate,
    read_presence_probability,
    read_stimmung_snapshot,
    stimmung_auto_private_needed,
)


class TestPresenceT0Gate:
    @pytest.mark.parametrize("mode", [StreamMode.OFF, StreamMode.PRIVATE])
    def test_off_or_private_always_allowed(self, mode):
        result = presence_t0_gate(
            mode, presence_probability=1.0, active_broadcast_contracts=frozenset()
        )
        assert result.allowed

    @pytest.mark.parametrize("mode", [StreamMode.PUBLIC, StreamMode.PUBLIC_RESEARCH])
    def test_public_blocked_without_contracts_when_presence(self, mode):
        result = presence_t0_gate(
            mode, presence_probability=0.9, active_broadcast_contracts=frozenset()
        )
        assert not result.allowed
        assert result.blocked_by == "presence_t0"

    @pytest.mark.parametrize("mode", [StreamMode.PUBLIC, StreamMode.PUBLIC_RESEARCH])
    def test_public_allowed_with_contracts_when_presence(self, mode):
        result = presence_t0_gate(
            mode,
            presence_probability=0.9,
            active_broadcast_contracts=frozenset(["broadcast-alice-2026-04-16"]),
        )
        assert result.allowed

    def test_public_allowed_below_presence_threshold(self):
        result = presence_t0_gate(
            StreamMode.PUBLIC,
            presence_probability=0.3,
            active_broadcast_contracts=frozenset(),
        )
        assert result.allowed

    def test_threshold_boundary(self):
        # At exactly the threshold, the gate engages (>=)
        result = presence_t0_gate(
            StreamMode.PUBLIC,
            presence_probability=0.5,
            active_broadcast_contracts=frozenset(),
        )
        assert not result.allowed


class TestStimmungAutoPrivate:
    def test_nominal_stimmung_allows_public(self):
        stimmung = {
            "overall_stance": "nominal",
            "resource_pressure": {"value": 0.1},
            "operator_stress": {"value": 0.1},
            "error_rate": {"value": 0.0},
        }
        assert stimmung_auto_private_needed(stimmung).allowed

    def test_critical_stance_forces_private(self):
        stimmung = {"overall_stance": "critical"}
        result = stimmung_auto_private_needed(stimmung)
        assert not result.allowed
        assert "critical" in result.reason
        assert result.blocked_by == "stimmung_critical"

    def test_high_resource_pressure(self):
        stimmung = {
            "overall_stance": "cautious",
            "resource_pressure": {"value": 0.95},
        }
        result = stimmung_auto_private_needed(stimmung)
        assert not result.allowed
        assert "resource_pressure" in result.reason

    def test_high_operator_stress(self):
        stimmung = {
            "overall_stance": "cautious",
            "operator_stress": {"value": 0.95},
        }
        result = stimmung_auto_private_needed(stimmung)
        assert not result.allowed
        assert "operator_stress" in result.reason

    def test_high_error_rate(self):
        stimmung = {
            "overall_stance": "nominal",
            "error_rate": {"value": 0.9},
        }
        result = stimmung_auto_private_needed(stimmung)
        assert not result.allowed
        assert "error_rate" in result.reason

    def test_empty_stimmung_allows_public(self):
        """Missing stimmung data defaults to allowing (gate fails open for
        data-unavailable case; §5 is a FORCE-private trigger, not a default-
        private posture)."""
        assert stimmung_auto_private_needed({}).allowed


class TestReaders:
    def test_read_stimmung_missing_file_returns_empty(self, tmp_path):
        assert read_stimmung_snapshot(tmp_path / "no-file.json") == {}

    def test_read_stimmung_valid(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text(json.dumps({"overall_stance": "nominal"}))
        snap = read_stimmung_snapshot(p)
        assert snap["overall_stance"] == "nominal"

    def test_read_presence_missing_file_returns_zero(self, tmp_path):
        assert read_presence_probability(tmp_path / "no-file.json") == 0.0

    def test_read_presence_scalar_value(self, tmp_path):
        p = tmp_path / "health.json"
        p.write_text(json.dumps({"presence_probability": 0.82}))
        assert read_presence_probability(p) == pytest.approx(0.82)

    def test_read_presence_nested_value(self, tmp_path):
        p = tmp_path / "health.json"
        p.write_text(json.dumps({"presence_probability": {"value": 0.75}}))
        assert read_presence_probability(p) == pytest.approx(0.75)

    def test_read_presence_malformed_returns_zero(self, tmp_path):
        p = tmp_path / "health.json"
        p.write_text("not json")
        assert read_presence_probability(p) == 0.0
