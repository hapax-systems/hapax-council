"""Tests for apperception tick I/O layer — SHM writes, model persistence, store integration.

All tests use tmp_path with monkeypatched paths. Mocks only for Qdrant
and embedding (external services). No real /dev/shm access.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shared.apperception import ApperceptionCascade, SelfModel
from shared.apperception_tick import ApperceptionTick


@pytest.fixture()
def tick_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up a tick environment with all paths in tmp_path."""
    temporal_dir = tmp_path / "temporal"
    temporal_dir.mkdir()
    stimmung_dir = tmp_path / "stimmung"
    stimmung_dir.mkdir()
    correction_dir = tmp_path / "correction"
    correction_dir.mkdir()
    apperception_dir = tmp_path / "apperception"
    apperception_dir.mkdir()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    monkeypatch.setattr("shared.apperception_tick.TEMPORAL_FILE", temporal_dir / "bands.json")
    monkeypatch.setattr("shared.apperception_tick.STIMMUNG_FILE", stimmung_dir / "state.json")
    monkeypatch.setattr(
        "shared.apperception_tick.CORRECTION_FILE",
        correction_dir / "activity-correction.json",
    )
    monkeypatch.setattr("shared.apperception_tick.APPERCEPTION_DIR", apperception_dir)
    monkeypatch.setattr(
        "shared.apperception_tick.APPERCEPTION_FILE", apperception_dir / "self-band.json"
    )
    monkeypatch.setattr("shared.apperception_tick.APPERCEPTION_CACHE_DIR", cache_dir)
    monkeypatch.setattr(
        "shared.apperception_tick.APPERCEPTION_CACHE_FILE", cache_dir / "self-model.json"
    )

    # Write default stimmung
    (stimmung_dir / "state.json").write_text(
        json.dumps({"overall_stance": "nominal", "timestamp": time.time()})
    )

    # Mock store to avoid Qdrant
    mock_store = MagicMock()
    mock_store.pending_count = 0
    mock_store.flush.return_value = 0

    return {
        "tmp_path": tmp_path,
        "temporal_dir": temporal_dir,
        "stimmung_dir": stimmung_dir,
        "correction_dir": correction_dir,
        "apperception_dir": apperception_dir,
        "cache_dir": cache_dir,
        "mock_store": mock_store,
    }


def _make_tick(tick_env: dict) -> ApperceptionTick:
    """Create a tick instance with mocked store."""
    with patch.object(ApperceptionTick, "__init__", lambda self: None):
        tick = ApperceptionTick()
    tick._cascade = ApperceptionCascade(self_model=SelfModel())
    tick._prev_stimmung_stance = "nominal"
    tick._last_save = 0.0
    tick._last_flush = 0.0
    tick._last_correction_ts = 0.0
    tick._last_perf_snapshot: dict[str, float] = {}
    tick._last_perf_reset = time.monotonic()
    tick._tick_seq = 0
    tick._store = tick_env["mock_store"]
    return tick


# ── SHM Write Tests ──────────────────────────────────────────────────────────


class TestShmWrite:
    def test_payload_structure(self, tick_env: dict):
        """Written payload contains all 5 expected fields."""
        tick = _make_tick(tick_env)
        tick.tick()
        path = tick_env["apperception_dir"] / "self-band.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert "self_model" in data
        assert "pending_actions" in data
        assert "timestamp" in data
        assert "tick_seq" in data
        assert "events_this_tick" in data
        assert data["tick_seq"] == 1
        assert isinstance(data["events_this_tick"], int)

    def test_atomic_write_no_tmp_leftover(self, tick_env: dict):
        """After write, no .tmp file remains (atomic rename succeeded)."""
        tick = _make_tick(tick_env)
        tick.tick()
        tmp_path = tick_env["apperception_dir"] / "self-band.tmp"
        assert not tmp_path.exists()

    def test_creates_directory(self, tick_env: dict):
        """_write_shm creates the directory if missing."""
        import shutil

        shutil.rmtree(tick_env["apperception_dir"])
        tick = _make_tick(tick_env)
        tick._write_shm([], event_count=0)
        assert (tick_env["apperception_dir"] / "self-band.json").exists()

    def test_oserror_graceful(self, tick_env: dict, monkeypatch: pytest.MonkeyPatch):
        """OSError during write doesn't crash — logs and continues."""
        tick = _make_tick(tick_env)
        monkeypatch.setattr(
            "shared.apperception_tick.APPERCEPTION_DIR",
            Path("/nonexistent/readonly/dir"),
        )
        monkeypatch.setattr(
            "shared.apperception_tick.APPERCEPTION_FILE",
            Path("/nonexistent/readonly/dir/self-band.json"),
        )
        tick._write_shm([], event_count=0)  # should not raise


# ── Exploration Writer Tests ─────────────────────────────────────────────────


class TestExplorationWriter:
    """Apperception MUST publish exploration signal every tick — even when
    no events surfaced — or the health monitor flags
    `exploration_apperception` as DEGRADED ('Writer absent') in perpetuity.
    Live regression seen 2026-04-21 (Stack Health: FAILED, 100/110 healthy).
    """

    def test_init_creates_exploration_tracker(self, tick_env: dict):
        from shared.apperception_tick import ApperceptionTick

        tick = ApperceptionTick()
        assert tick._exploration is not None, (
            "ApperceptionTick must construct an ExplorationTrackerBundle "
            "for the apperception component"
        )

    def test_tick_publishes_exploration_signal(
        self, tick_env: dict, monkeypatch: pytest.MonkeyPatch
    ):
        """Even with zero events, tick() must publish a signal — the
        signal is what the health monitor's exploration_apperception
        check reads. Mocks the publisher to verify the call shape
        without touching /dev/shm."""
        from unittest.mock import MagicMock

        from shared.apperception_tick import ApperceptionTick

        captured: list = []
        monkeypatch.setattr(
            "shared.exploration_tracker.publish_exploration_signal",
            lambda sig: captured.append(sig),
        )

        tick = ApperceptionTick()
        # Force a quiet tick — no events.
        tick._collect_events = MagicMock(return_value=[])
        tick._read_stimmung = MagicMock(return_value=("nominal", {}))
        tick.tick()

        assert captured, (
            "publish_exploration_signal was NOT called during a quiet "
            "tick — apperception writer would stay silent and the "
            "health check would flag DEGRADED in perpetuity"
        )
        sig = captured[0]
        assert sig.component == "apperception"

    def test_tick_helper_without_exploration_attr_does_not_crash(self, tick_env: dict):
        """The _make_tick helper bypasses __init__; tick() must remain
        defensive via getattr() so it doesn't AttributeError."""
        tick = _make_tick(tick_env)
        # No _exploration attribute set on this manually-constructed tick.
        assert not hasattr(tick, "_exploration")
        tick.tick()  # must not raise


# ── Model Persistence Tests ──────────────────────────────────────────────────


class TestModelPersistence:
    def test_save_load_roundtrip(self, tick_env: dict):
        """Save model, verify cache file has correct dimensions."""
        tick = _make_tick(tick_env)
        tick._cascade.model.get_or_create_dimension("test_dim")
        tick._cascade.model.dimensions["test_dim"].confidence = 0.8
        tick._cascade.model.dimensions["test_dim"].affirming_count = 5
        tick.save_model()

        cache_file = tick_env["cache_dir"] / "self-model.json"
        assert cache_file.exists()
        data = json.loads(cache_file.read_text())
        assert "test_dim" in data["dimensions"]
        assert data["dimensions"]["test_dim"]["confidence"] == 0.8

    def test_corrupted_cache_starts_fresh(self, tick_env: dict, monkeypatch: pytest.MonkeyPatch):
        """Garbage in cache file -> starts fresh with empty SelfModel."""
        cache_file = tick_env["cache_dir"] / "self-model.json"
        cache_file.write_text("NOT VALID JSON {{{")
        monkeypatch.setattr("shared.apperception_tick.APPERCEPTION_CACHE_FILE", cache_file)
        tick = _make_tick(tick_env)
        cascade = tick._load_model()
        assert len(cascade.model.dimensions) == 0

    def test_missing_cache_starts_fresh(self, tick_env: dict, monkeypatch: pytest.MonkeyPatch):
        """No cache file -> starts fresh."""
        monkeypatch.setattr(
            "shared.apperception_tick.APPERCEPTION_CACHE_FILE",
            tick_env["cache_dir"] / "nonexistent.json",
        )
        tick = _make_tick(tick_env)
        cascade = tick._load_model()
        assert len(cascade.model.dimensions) == 0


# ── Tick Loop Tests ───────────────────────────────────────────────────────────


class TestTickLoop:
    def test_full_cycle(self, tick_env: dict):
        """Synthetic temporal surprise -> tick() -> self-band.json written."""
        (tick_env["temporal_dir"] / "bands.json").write_text(
            json.dumps({"max_surprise": 0.6, "timestamp": time.time()})
        )
        tick = _make_tick(tick_env)
        tick.tick()

        path = tick_env["apperception_dir"] / "self-band.json"
        data = json.loads(path.read_text())
        assert data["tick_seq"] == 1
        assert data["events_this_tick"] >= 1

    def test_multi_tick_accumulates(self, tick_env: dict):
        """Three ticks -> tick_seq increments each time."""
        (tick_env["temporal_dir"] / "bands.json").write_text(
            json.dumps({"max_surprise": 0.6, "timestamp": time.time()})
        )
        tick = _make_tick(tick_env)
        tick.tick()
        tick.tick()
        tick.tick()

        path = tick_env["apperception_dir"] / "self-band.json"
        data = json.loads(path.read_text())
        assert data["tick_seq"] == 3

    def test_save_interval(self, tick_env: dict, monkeypatch: pytest.MonkeyPatch):
        """save_model() fires after 300s (mocked monotonic)."""
        tick = _make_tick(tick_env)
        tick._last_save = 0.0
        mock_time = MagicMock(return_value=301.0)
        monkeypatch.setattr("shared.apperception_tick.time.monotonic", mock_time)
        tick.tick()

        cache_file = tick_env["cache_dir"] / "self-model.json"
        assert cache_file.exists()

    def test_store_flush_cadence(self, tick_env: dict, monkeypatch: pytest.MonkeyPatch):
        """store.flush() fires after 60s."""
        tick = _make_tick(tick_env)
        tick._last_flush = 0.0
        mock_time = MagicMock(return_value=61.0)
        monkeypatch.setattr("shared.apperception_tick.time.monotonic", mock_time)
        tick.tick()

        tick_env["mock_store"].flush.assert_called_once()

    def test_store_add_on_retain(self, tick_env: dict):
        """Correction event -> retained -> store.add() called."""
        (tick_env["correction_dir"] / "activity-correction.json").write_text(
            json.dumps({"label": "test_correction", "timestamp": time.time()})
        )
        tick = _make_tick(tick_env)
        tick.tick()

        assert tick_env["mock_store"].add.called


# ── Event Collection Edge Cases ───────────────────────────────────────────────


class TestEventCollectionEdgeCases:
    def test_corrupted_temporal_json(self, tick_env: dict):
        """Invalid JSON in temporal file -> no crash, tick completes."""
        (tick_env["temporal_dir"] / "bands.json").write_text("NOT JSON {{{")
        tick = _make_tick(tick_env)
        tick.tick()
        assert (tick_env["apperception_dir"] / "self-band.json").exists()

    def test_missing_correction_file(self, tick_env: dict):
        """Missing correction file -> no crash, tick completes."""
        tick = _make_tick(tick_env)
        tick.tick()
        assert (tick_env["apperception_dir"] / "self-band.json").exists()

    def test_unknown_stimmung_stance(self, tick_env: dict):
        """Unknown stance -> generates stimmung_event transition."""
        (tick_env["stimmung_dir"] / "state.json").write_text(
            json.dumps({"overall_stance": "weird_stance", "timestamp": time.time()})
        )
        tick = _make_tick(tick_env)
        tick.tick()
        path = tick_env["apperception_dir"] / "self-band.json"
        data = json.loads(path.read_text())
        assert data["events_this_tick"] >= 1

    def test_rapid_tick_no_duplicate(self, tick_env: dict):
        """Same correction timestamp twice -> only one event."""
        corr_ts = time.time()
        (tick_env["correction_dir"] / "activity-correction.json").write_text(
            json.dumps({"label": "same", "timestamp": corr_ts})
        )
        tick = _make_tick(tick_env)
        tick.tick()
        first_add_count = tick_env["mock_store"].add.call_count

        tick.tick()
        second_add_count = tick_env["mock_store"].add.call_count

        assert second_add_count == first_add_count


# ── Store Integration Tests ───────────────────────────────────────────────────


class TestStoreIntegration:
    def test_retained_apperception_queued(self, tick_env: dict):
        """Retained apperception is queued to store.add() with correct type."""
        (tick_env["correction_dir"] / "activity-correction.json").write_text(
            json.dumps({"label": "verify_add", "timestamp": time.time()})
        )
        tick = _make_tick(tick_env)
        tick.tick()

        assert tick_env["mock_store"].add.call_count >= 1
        from shared.apperception import Apperception

        call_args = tick_env["mock_store"].add.call_args_list
        for call in call_args:
            assert isinstance(call[0][0], Apperception)

    def test_flush_called_on_cadence(self, tick_env: dict, monkeypatch: pytest.MonkeyPatch):
        """flush() called when 60s elapsed since last flush."""
        tick = _make_tick(tick_env)
        tick._last_flush = 0.0
        mock_mono = MagicMock(return_value=61.0)
        monkeypatch.setattr("shared.apperception_tick.time.monotonic", mock_mono)
        tick.tick()
        tick_env["mock_store"].flush.assert_called_once()

    def test_shutdown_flushes(self, tick_env: dict):
        """save_model() calls store.flush() before persisting."""
        tick = _make_tick(tick_env)
        tick.save_model()
        tick_env["mock_store"].flush.assert_called_once()
        cache_file = tick_env["cache_dir"] / "self-model.json"
        assert cache_file.exists()


# ── Defensive readers — non-dict JSON root ──────────────────────────────


class TestReadersRejectNonDictRoot:
    """Pin that the SHM readers in apperception_tick.py survive a writer
    producing valid JSON whose root is not a mapping. Three sites previously
    let AttributeError escape the narrow (OSError, JSONDecodeError) catch
    and crashed the apperception tick loop: cross-resonance (line 274),
    pattern-shifts (line 292), stimmung (line 318)."""

    @pytest.mark.parametrize(
        "payload,kind",
        [("null", "null"), ('"string"', "string"), ("[1,2]", "list"), ("42", "int")],
    )
    def test_read_stimmung_non_dict_root(
        self,
        tick_env: dict,
        monkeypatch: pytest.MonkeyPatch,
        payload: str,
        kind: str,
    ):
        from shared import apperception_tick as at

        # Redirect STIMMUNG_FILE through the test fixture path.
        stimmung_path = tick_env["stimmung_dir"] / "state.json"
        stimmung_path.write_text(payload)
        monkeypatch.setattr(at, "STIMMUNG_FILE", stimmung_path)
        tick = _make_tick(tick_env)
        # Hot-path call inside the apperception tick — must not raise.
        stance, data = tick._read_stimmung()
        assert stance == "nominal", f"root={kind} must yield nominal stance"
        assert data is None, f"root={kind} must yield None data"
