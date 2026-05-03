"""Tests for cc-task u3 — agents.novelty_emitter.

Pin the rising-edge detector + impingement payload shape against
synthetic gqi time series. No /dev/shm or PipeWire deps at CI time.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agents.novelty_emitter import (
    GQI_HIGH_THRESHOLD,
    GQI_LOW_THRESHOLD,
    NoveltyShiftEmitter,
    NoveltyShiftReading,
    build_impingement_payload,
    emit_if_shifted,
)
from agents.novelty_emitter._emitter import (
    DEFAULT_IMPINGEMENTS_PATH,
    detect_rising_shift,
)


class TestRisingEdgeDetector:
    def test_no_prev_returns_false(self) -> None:
        assert detect_rising_shift(None, 0.9) is False

    def test_low_to_high_returns_true(self) -> None:
        assert detect_rising_shift(0.2, 0.85) is True

    def test_high_to_high_returns_false(self) -> None:
        """The detector must not fire on sustained high gqi — only on
        the rising-edge crossing. Otherwise it would spam impingements
        every tick during a stable high-grounding period."""
        assert detect_rising_shift(0.85, 0.90) is False

    def test_low_to_low_returns_false(self) -> None:
        assert detect_rising_shift(0.2, 0.3) is False

    def test_falling_edge_returns_false(self) -> None:
        """A drop in gqi is not a novelty SHIFT — that's a different signal."""
        assert detect_rising_shift(0.85, 0.2) is False

    def test_below_high_returns_false(self) -> None:
        """Just because we crossed low doesn't mean we're high enough."""
        assert detect_rising_shift(0.3, 0.5) is False

    def test_custom_thresholds_respected(self) -> None:
        assert detect_rising_shift(0.1, 0.95, low=0.2, high=0.9) is True
        assert detect_rising_shift(0.3, 0.95, low=0.2, high=0.9) is False

    def test_default_thresholds_match_module_constants(self) -> None:
        assert GQI_LOW_THRESHOLD < GQI_HIGH_THRESHOLD


class TestImpingementPayloadShape:
    def test_payload_has_all_required_fields(self) -> None:
        reading = NoveltyShiftReading(gqi=0.85, timestamp=time.time(), source_age_s=0.1)
        payload = build_impingement_payload(reading, prev_gqi=0.20, now=1700000000.0)
        for key in (
            "id",
            "timestamp",
            "source",
            "type",
            "strength",
            "content",
            "context",
            "intent_family",
            "embedding",
            "interrupt_token",
            "parent_id",
            "trace_id",
            "span_id",
        ):
            assert key in payload, f"impingement payload missing required field {key!r}"

    def test_intent_family_is_novelty_shift(self) -> None:
        """The whole point — pin the routing intent_family so a refactor
        that changes it silently breaks recruitment."""
        reading = NoveltyShiftReading(gqi=0.85, timestamp=0.0, source_age_s=0.1)
        payload = build_impingement_payload(reading, prev_gqi=0.20, now=0.0)
        assert payload["intent_family"] == "novelty.shift"

    def test_strength_clamped_to_unit_interval(self) -> None:
        for gqi in (-0.5, 0.0, 0.3, 1.0, 1.5):
            reading = NoveltyShiftReading(gqi=gqi, timestamp=0.0, source_age_s=0.1)
            payload = build_impingement_payload(reading, prev_gqi=0.0, now=0.0)
            assert 0.0 <= payload["strength"] <= 1.0, (
                f"strength {payload['strength']} out of [0,1] for gqi={gqi}"
            )

    def test_narrative_includes_delta_when_prev_present(self) -> None:
        reading = NoveltyShiftReading(gqi=0.85, timestamp=0.0, source_age_s=0.1)
        payload = build_impingement_payload(reading, prev_gqi=0.20, now=0.0)
        narrative = payload["content"]["narrative"]
        assert "0.20" in narrative and "0.85" in narrative

    def test_narrative_handles_missing_prev(self) -> None:
        reading = NoveltyShiftReading(gqi=0.85, timestamp=0.0, source_age_s=0.1)
        payload = build_impingement_payload(reading, prev_gqi=None, now=0.0)
        assert "0.85" in payload["content"]["narrative"]
        assert payload["content"]["prev_gqi"] is None


class TestEmitterTickIntegration:
    """End-to-end: synthetic gqi file in tmp → emitter → impingement bus +
    textfile + state. No global state pollution."""

    def _setup(self, tmp_path: Path, gqi: float, ts: float | None = None) -> dict:
        gqi_path = tmp_path / "gq.json"
        gqi_path.write_text(json.dumps({"gqi": gqi, "timestamp": ts or time.time()}))
        bus = tmp_path / "imp.jsonl"
        textfile = tmp_path / "metrics.prom"
        state = tmp_path / "state.json"
        emitter = NoveltyShiftEmitter(
            gqi_path=gqi_path,
            bus_path=bus,
            textfile=textfile,
            state_path=state,
        )
        return {"emitter": emitter, "bus": bus, "textfile": textfile, "state": state}

    def test_first_tick_does_not_dispatch(self, tmp_path: Path) -> None:
        """No prev_gqi → no rising-edge possible. Must absorb."""
        env = self._setup(tmp_path, gqi=0.85)
        report = env["emitter"].tick()
        assert report["status"] == "absorbed"
        assert report["shifted"] is False
        assert not env["bus"].exists() or env["bus"].read_text() == ""

    def test_low_then_high_dispatches_one_impingement(self, tmp_path: Path) -> None:
        env = self._setup(tmp_path, gqi=0.20)
        env["emitter"].tick()  # seed prev=0.20

        # Mutate gqi file to a high reading; emitter re-reads on tick.
        env["emitter"].gqi_path.write_text(json.dumps({"gqi": 0.85, "timestamp": time.time()}))
        report = env["emitter"].tick()
        assert report["status"] == "dispatched"
        assert report["shifted"] is True
        assert report["dispatched_total"] == 1

        # The bus file now contains exactly one impingement.
        lines = env["bus"].read_text().strip().splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["intent_family"] == "novelty.shift"

    def test_sustained_high_does_not_re_dispatch(self, tmp_path: Path) -> None:
        env = self._setup(tmp_path, gqi=0.20)
        env["emitter"].tick()

        env["emitter"].gqi_path.write_text(json.dumps({"gqi": 0.85, "timestamp": time.time()}))
        env["emitter"].tick()  # dispatches once

        env["emitter"].gqi_path.write_text(json.dumps({"gqi": 0.90, "timestamp": time.time()}))
        report = env["emitter"].tick()
        # Sustained high is not a NEW shift; absorb.
        assert report["status"] == "absorbed"
        assert report["dispatched_total"] == 1, (
            "dispatched_total must not increment on sustained-high — would spam the impingement bus"
        )

    def test_textfile_renders_counter_metric(self, tmp_path: Path) -> None:
        env = self._setup(tmp_path, gqi=0.20)
        env["emitter"].tick()
        assert env["textfile"].exists()
        content = env["textfile"].read_text()
        assert "hapax_novelty_shift_impingement_total" in content
        assert 'outcome="dispatched"' in content
        assert 'outcome="absorbed"' in content

    def test_missing_gqi_file_skips_cleanly(self, tmp_path: Path) -> None:
        env = self._setup(tmp_path, gqi=0.5)
        env["emitter"].gqi_path.unlink()
        report = env["emitter"].tick()
        assert report["status"] == "skipped"


class TestImpingementBusContract:
    """Pin: the emitter writes to the SAME impingement bus the
    AffordancePipeline's _maybe_emit_perceptual_distance_impingement
    writes to. Both consumers (daimonion + reverie) tail the same file."""

    def test_default_bus_path_matches_perceptual_emission_path(self) -> None:
        from shared.affordance_pipeline import _PERCEPTUAL_IMPINGEMENTS_FILE

        assert DEFAULT_IMPINGEMENTS_PATH == _PERCEPTUAL_IMPINGEMENTS_FILE


class TestModuleEntryPoint:
    """The systemd unit calls `python -m agents.novelty_emitter`; pin
    that the entry point exists and emit_if_shifted is exported."""

    def test_emit_if_shifted_is_callable(self) -> None:
        assert callable(emit_if_shifted)

    def test_main_module_importable(self) -> None:
        from agents.novelty_emitter import __main__

        assert hasattr(__main__, "main")


@pytest.fixture(autouse=False)
def _no_real_dev_shm(monkeypatch, tmp_path):
    """Defensive fixture to stop any test that forgets to override paths
    from writing to /dev/shm. Use opt-in via fixture argument."""
    monkeypatch.setattr("agents.novelty_emitter._emitter.DEFAULT_GQI_PATH", tmp_path / "gqi.json")
    monkeypatch.setattr(
        "agents.novelty_emitter._emitter.DEFAULT_IMPINGEMENTS_PATH",
        tmp_path / "bus.jsonl",
    )
    return tmp_path
