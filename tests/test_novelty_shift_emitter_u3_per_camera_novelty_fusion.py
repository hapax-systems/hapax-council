"""u3-per-camera-novelty-fusion — visual-novelty signal fused with GQI rising-edge.

cc-task `u3-per-camera-novelty-fusion`. The novelty-shift emitter previously
triggered only on GQI rising-edge. The visual-novelty signal aggregated by
`agents/visual_chain.py` from `signal_mappers.py` per-camera detections
(published to `/dev/shm/hapax-exploration/<component>.json` as
`ExplorationSignal.max_novelty_score`) was unused by the emitter — a fresh
person walking into frame couldn't trigger an exploration impulse unless
GQI also happened to rise. This wires the fusion: rising-edge on EITHER
signal triggers a single dispatch.

Test surface:
  * `read_max_visual_novelty` aggregates max across all components in
    /dev/shm/hapax-exploration/*.json
  * `detect_rising_visual_novelty_shift` mirrors GQI rising-edge logic
  * `build_visual_novelty_impingement_payload` produces correct shape
    with `metric: "visual_novelty_rising_shift"` discriminator
  * State roundtrip preserves `prev_max_novelty`
  * Tick: visual-novelty rising-edge alone dispatches (no GQI shift)
  * Tick: GQI rising-edge alone still dispatches (existing path)
  * Tick: both signals firing same tick → exactly 1 dispatch
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agents.novelty_emitter._emitter import (
    DEFAULT_EXPLORATION_DIR,
    VISUAL_NOVELTY_HIGH_THRESHOLD,
    VISUAL_NOVELTY_LOW_THRESHOLD,
    NoveltyShiftEmitter,
    _load_prev_state,
    _save_state,
    build_visual_novelty_impingement_payload,
    detect_rising_visual_novelty_shift,
    read_max_visual_novelty,
)

# ── read_max_visual_novelty ─────────────────────────────────────────


class TestReadMaxVisualNovelty:
    def test_missing_dir_returns_zero(self, tmp_path: Path) -> None:
        score, edge = read_max_visual_novelty(tmp_path / "missing")
        assert score == pytest.approx(0.0)
        assert edge is None

    def test_empty_dir_returns_zero(self, tmp_path: Path) -> None:
        d = tmp_path / "exploration"
        d.mkdir()
        score, edge = read_max_visual_novelty(d)
        assert score == pytest.approx(0.0)
        assert edge is None

    def test_aggregates_max_across_components(self, tmp_path: Path) -> None:
        d = tmp_path / "exploration"
        d.mkdir()
        (d / "visual_chain.json").write_text(
            json.dumps({"max_novelty_score": 0.6, "max_novelty_edge": "person@desk"})
        )
        (d / "salience_router.json").write_text(
            json.dumps({"max_novelty_score": 0.85, "max_novelty_edge": "object@overhead"})
        )
        (d / "contact_mic.json").write_text(json.dumps({"max_novelty_score": 0.2}))
        score, edge = read_max_visual_novelty(d)
        assert score == pytest.approx(0.85)
        assert edge == "object@overhead"

    def test_skips_malformed_components(self, tmp_path: Path) -> None:
        d = tmp_path / "exploration"
        d.mkdir()
        (d / "good.json").write_text(
            json.dumps({"max_novelty_score": 0.5, "max_novelty_edge": "ok"})
        )
        (d / "bad.json").write_text("{not valid json")
        (d / "wrong_type.json").write_text(json.dumps([1, 2, 3]))  # not a dict
        (d / "non_numeric.json").write_text(json.dumps({"max_novelty_score": "not-a-float"}))
        score, edge = read_max_visual_novelty(d)
        assert score == pytest.approx(0.5)
        assert edge == "ok"

    def test_default_path_constant(self) -> None:
        """Pin: emitter reads from the directory the exploration writer
        publishes to (`shared/exploration_writer.py` → /dev/shm/hapax-
        exploration/)."""
        assert str(DEFAULT_EXPLORATION_DIR) == "/dev/shm/hapax-exploration"


# ── detect_rising_visual_novelty_shift ──────────────────────────────


class TestDetectRisingVisualNoveltyShift:
    def test_no_prev_returns_false(self) -> None:
        assert detect_rising_visual_novelty_shift(None, 0.9) is False

    def test_low_to_high_returns_true(self) -> None:
        assert detect_rising_visual_novelty_shift(0.2, 0.85) is True

    def test_high_to_high_returns_false(self) -> None:
        assert detect_rising_visual_novelty_shift(0.85, 0.90) is False

    def test_low_to_low_returns_false(self) -> None:
        assert detect_rising_visual_novelty_shift(0.2, 0.3) is False

    def test_falling_edge_returns_false(self) -> None:
        assert detect_rising_visual_novelty_shift(0.85, 0.2) is False

    def test_below_high_returns_false(self) -> None:
        assert detect_rising_visual_novelty_shift(0.2, 0.5) is False

    def test_default_thresholds_distinct(self) -> None:
        assert VISUAL_NOVELTY_LOW_THRESHOLD < VISUAL_NOVELTY_HIGH_THRESHOLD


# ── build_visual_novelty_impingement_payload ────────────────────────


class TestBuildVisualNoveltyPayload:
    def test_payload_shape(self) -> None:
        p = build_visual_novelty_impingement_payload(
            current_novelty=0.85,
            prev_novelty=0.20,
            edge_label="person@desk",
            now=1234.5,
        )
        # Shape pin — distinguishes visual-novelty from GQI dispatches.
        assert p["intent_family"] == "novelty.shift"
        assert p["source"] == "agents.novelty_emitter.visual_novelty_shift"
        assert p["content"]["metric"] == "visual_novelty_rising_shift"
        assert p["content"]["max_novelty_score"] == pytest.approx(0.85)
        assert p["content"]["prev_max_novelty"] == pytest.approx(0.20)
        assert p["content"]["edge"] == "person@desk"
        assert "narrative" in p["content"]
        assert p["timestamp"] == 1234.5

    def test_payload_handles_missing_prev_and_edge(self) -> None:
        p = build_visual_novelty_impingement_payload(
            current_novelty=0.9, prev_novelty=None, edge_label=None, now=1.0
        )
        # Should not crash when both prev and edge are absent.
        assert p["content"]["prev_max_novelty"] is None
        assert p["content"]["edge"] is None
        assert "Visual novelty crossed" in p["content"]["narrative"]


# ── State roundtrip — prev_max_novelty preserved ────────────────────


class TestStatePrevMaxNovelty:
    def test_save_and_load_preserves_prev_max_novelty(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        _save_state(
            state_file,
            gqi=0.5,
            dispatched_total=1,
            absorbed_total=0,
            pending_dispatches=[10.0],
            prev_max_novelty=0.65,
        )
        prev_gqi, dispatched, absorbed, pending, prev_novelty = _load_prev_state(state_file)
        assert prev_novelty == pytest.approx(0.65)

    def test_load_old_format_state_returns_none_for_novelty(self, tmp_path: Path) -> None:
        """Pre-fusion state files lack `prev_max_novelty` — must default
        to None so the first post-deploy tick can't fire on a stale value."""
        p = tmp_path / "old.json"
        p.write_text(json.dumps({"prev_gqi": 0.5, "dispatched_total": 7}))
        prev_gqi, _, _, _, prev_novelty = _load_prev_state(p)
        assert prev_gqi == pytest.approx(0.5)
        assert prev_novelty is None

    def test_load_corrupt_prev_max_novelty_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "corrupt.json"
        p.write_text(json.dumps({"prev_gqi": 0.5, "prev_max_novelty": "not-a-float"}))
        _, _, _, _, prev_novelty = _load_prev_state(p)
        assert prev_novelty is None


# ── Tick fusion integration ─────────────────────────────────────────


class TestTickFusionIntegration:
    """End-to-end: dispatch fires on either signal alone or both."""

    def _setup(self, tmp_path: Path, gqi: float, ts: float | None = None) -> dict:
        gqi_path = tmp_path / "gq.json"
        gqi_path.write_text(json.dumps({"gqi": gqi, "timestamp": ts or time.time()}))
        exploration_dir = tmp_path / "exploration"
        exploration_dir.mkdir()
        return {
            "emitter": NoveltyShiftEmitter(
                gqi_path=gqi_path,
                bus_path=tmp_path / "imp.jsonl",
                textfile=tmp_path / "metrics.prom",
                state_path=tmp_path / "state.json",
                recent_recruitment_path=tmp_path / "recent-recruitment.json",
                exploration_dir=exploration_dir,
                absorption_window_s=5.0,
            ),
            "gqi_path": gqi_path,
            "exploration_dir": exploration_dir,
        }

    def _write_visual_novelty(
        self, exploration_dir: Path, score: float, edge: str = "test_edge"
    ) -> None:
        (exploration_dir / "visual_chain.json").write_text(
            json.dumps({"max_novelty_score": score, "max_novelty_edge": edge})
        )

    def test_visual_novelty_rising_alone_dispatches(self, tmp_path: Path) -> None:
        env = self._setup(tmp_path, gqi=0.20)
        self._write_visual_novelty(env["exploration_dir"], 0.20)  # below low
        env["emitter"].tick()  # seed prev_gqi=0.20, prev_max_novelty=0.20

        # GQI stays low (no GQI shift), but visual-novelty crosses high.
        env["gqi_path"].write_text(json.dumps({"gqi": 0.20, "timestamp": time.time()}))
        self._write_visual_novelty(env["exploration_dir"], 0.85)
        report = env["emitter"].tick()
        assert report["status"] == "dispatched"
        assert report["trigger"] == "visual_novelty"
        assert report["dispatched_total"] == 1

        # Bus contains a payload with the visual-novelty metric.
        bus_lines = (env["emitter"].bus_path).read_text().strip().splitlines()
        assert len(bus_lines) == 1
        payload = json.loads(bus_lines[0])
        assert payload["content"]["metric"] == "visual_novelty_rising_shift"
        assert payload["intent_family"] == "novelty.shift"

    def test_gqi_rising_alone_still_dispatches(self, tmp_path: Path) -> None:
        """Backward-compat: existing GQI path unchanged."""
        env = self._setup(tmp_path, gqi=0.20)
        self._write_visual_novelty(env["exploration_dir"], 0.10)  # below low
        env["emitter"].tick()  # seed

        # GQI rises; visual-novelty stays low.
        env["gqi_path"].write_text(json.dumps({"gqi": 0.85, "timestamp": time.time()}))
        self._write_visual_novelty(env["exploration_dir"], 0.10)
        report = env["emitter"].tick()
        assert report["status"] == "dispatched"
        assert report["trigger"] == "gqi"
        assert report["dispatched_total"] == 1

        bus_lines = (env["emitter"].bus_path).read_text().strip().splitlines()
        assert len(bus_lines) == 1
        payload = json.loads(bus_lines[0])
        assert payload["content"]["metric"] == "gqi_rising_shift"

    def test_both_signals_same_tick_one_dispatch(self, tmp_path: Path) -> None:
        """No double-counting: GQI takes precedence when both fire."""
        env = self._setup(tmp_path, gqi=0.20)
        self._write_visual_novelty(env["exploration_dir"], 0.20)
        env["emitter"].tick()  # seed prev=0.20 for both

        # Both signals cross high simultaneously.
        env["gqi_path"].write_text(json.dumps({"gqi": 0.85, "timestamp": time.time()}))
        self._write_visual_novelty(env["exploration_dir"], 0.85)
        report = env["emitter"].tick()
        assert report["status"] == "dispatched"
        assert report["dispatched_total"] == 1  # exactly one
        assert report["trigger"] == "gqi"  # GQI wins precedence

        bus_lines = (env["emitter"].bus_path).read_text().strip().splitlines()
        assert len(bus_lines) == 1  # exactly one impingement on the bus

    def test_neither_signal_no_dispatch(self, tmp_path: Path) -> None:
        env = self._setup(tmp_path, gqi=0.20)
        self._write_visual_novelty(env["exploration_dir"], 0.10)
        env["emitter"].tick()  # seed

        # Both stay low.
        env["gqi_path"].write_text(json.dumps({"gqi": 0.30, "timestamp": time.time()}))
        self._write_visual_novelty(env["exploration_dir"], 0.20)
        report = env["emitter"].tick()
        assert report["status"] == "absorbed"  # no shift outcome
        assert report["dispatched_total"] == 0
        assert report["trigger"] is None

    def test_missing_exploration_dir_falls_through_to_gqi_only(self, tmp_path: Path) -> None:
        """Defensive: if /dev/shm/hapax-exploration/ doesn't exist (e.g.
        early-boot before any component has published), the GQI path
        still works."""
        gqi_path = tmp_path / "gq.json"
        gqi_path.write_text(json.dumps({"gqi": 0.20, "timestamp": time.time()}))
        emitter = NoveltyShiftEmitter(
            gqi_path=gqi_path,
            bus_path=tmp_path / "imp.jsonl",
            textfile=tmp_path / "metrics.prom",
            state_path=tmp_path / "state.json",
            recent_recruitment_path=tmp_path / "recent-recruitment.json",
            exploration_dir=tmp_path / "missing-exploration-dir",
        )
        emitter.tick()  # seed; exploration dir absent
        gqi_path.write_text(json.dumps({"gqi": 0.85, "timestamp": time.time()}))
        report = emitter.tick()
        assert report["status"] == "dispatched"
        assert report["trigger"] == "gqi"  # GQI still works

    def test_state_persists_prev_max_novelty_across_ticks(self, tmp_path: Path) -> None:
        """Pin: prev_max_novelty round-trips through the state file so
        the rising-edge detector compares to the previous tick's value
        (not always 0)."""
        env = self._setup(tmp_path, gqi=0.20)
        self._write_visual_novelty(env["exploration_dir"], 0.85)
        # First tick: prev_max_novelty=None → no rising-edge possible.
        env["emitter"].tick()
        # State now has prev_max_novelty=0.85.
        _, _, _, _, prev_novelty = _load_prev_state(env["emitter"].state_path)
        assert prev_novelty == pytest.approx(0.85)

        # Drop visual novelty back down. Next tick's prev=0.85 → low<0.85,
        # so no rising-edge (we're falling, not rising).
        self._write_visual_novelty(env["exploration_dir"], 0.10)
        env["gqi_path"].write_text(json.dumps({"gqi": 0.20, "timestamp": time.time()}))
        report = env["emitter"].tick()
        assert report["dispatched_total"] == 0  # falling-edge is not a shift


# ── Module export pin ───────────────────────────────────────────────


def test_module_exports() -> None:
    from agents.novelty_emitter._emitter import (  # noqa: F401
        DEFAULT_EXPLORATION_DIR,
        VISUAL_NOVELTY_HIGH_THRESHOLD,
        VISUAL_NOVELTY_LOW_THRESHOLD,
        build_visual_novelty_impingement_payload,
        detect_rising_visual_novelty_shift,
        read_max_visual_novelty,
    )

    assert callable(read_max_visual_novelty)
    assert callable(detect_rising_visual_novelty_shift)
    assert callable(build_visual_novelty_impingement_payload)
    assert VISUAL_NOVELTY_LOW_THRESHOLD < VISUAL_NOVELTY_HIGH_THRESHOLD
