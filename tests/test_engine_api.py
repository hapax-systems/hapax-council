"""Tests for logos/api/routes/engine.py — engine API endpoints.

Self-contained, asyncio_mode="auto", unittest.mock only.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from logos.api.routes.engine import router


def _make_app(engine=None) -> FastAPI:
    """Create a test app with optional engine on state."""
    app = FastAPI()
    app.include_router(router)
    if engine is not None:
        app.state.engine = engine
    return app


def _mock_engine(running=True, paused=False):
    """Create a mock ReactiveEngine with realistic status."""
    engine = MagicMock()
    engine.status = {
        "running": running,
        "paused": paused,
        "uptime_s": 120.5,
        "events_processed": 10,
        "rules_evaluated": 50,
        "actions_executed": 8,
        "errors": 1,
    }

    # Mock registry with rules
    rule1 = MagicMock()
    rule1.name = "collector-refresh"
    rule1.description = "Refresh cache"
    rule1.phase = 0
    rule1.cooldown_s = 0

    rule2 = MagicMock()
    rule2.name = "rag-source-landed"
    rule2.description = "Ingest RAG source"
    rule2.phase = 1
    rule2.cooldown_s = 0

    engine.registry = [rule1, rule2]

    # Mock history
    entry = MagicMock()
    entry.timestamp = datetime(2026, 3, 13, 12, 0, 0)
    entry.event_path = "/profiles/health-history.jsonl"
    entry.doc_type = "health-event"
    entry.rules_matched = ["collector-refresh"]
    entry.actions = ["collector-refresh-fast"]
    entry.errors = []
    engine.history = [entry]

    return engine


# ── TestEngineStatus ────────────────────────────────────────────────────


class TestEngineStatus:
    def test_returns_status(self):
        engine = _mock_engine()
        client = TestClient(_make_app(engine))
        resp = client.get("/api/engine/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is True
        assert data["events_processed"] == 10

    def test_503_when_no_engine(self):
        client = TestClient(_make_app())
        resp = client.get("/api/engine/status")
        assert resp.status_code == 503


# ── TestEngineRules ─────────────────────────────────────────────────────


class TestEngineRules:
    def test_returns_rules_list(self):
        engine = _mock_engine()
        client = TestClient(_make_app(engine))
        resp = client.get("/api/engine/rules")
        assert resp.status_code == 200
        rules = resp.json()
        assert len(rules) == 2
        assert rules[0]["name"] == "collector-refresh"
        assert rules[1]["phase"] == 1

    def test_503_when_no_engine(self):
        client = TestClient(_make_app())
        resp = client.get("/api/engine/rules")
        assert resp.status_code == 503


# ── TestEngineHistory ───────────────────────────────────────────────────


class TestEngineHistory:
    def test_returns_history(self):
        engine = _mock_engine()
        client = TestClient(_make_app(engine))
        resp = client.get("/api/engine/history")
        assert resp.status_code == 200
        history = resp.json()
        assert len(history) == 1
        assert history[0]["event_path"] == "/profiles/health-history.jsonl"
        assert history[0]["doc_type"] == "health-event"

    def test_limit_parameter(self):
        engine = _mock_engine()
        client = TestClient(_make_app(engine))
        resp = client.get("/api/engine/history?limit=0")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_503_when_no_engine(self):
        client = TestClient(_make_app())
        resp = client.get("/api/engine/history")
        assert resp.status_code == 503


# ── TestSystemDegradedStatus ────────────────────────────────────────────


class TestSystemDegradedStatus:
    def test_returns_posterior_and_state(self):
        from agents.hapax_daimonion.system_degraded_engine import SystemDegradedEngine

        sde = SystemDegradedEngine()
        app = _make_app(_mock_engine())
        app.state.system_degraded_engine = sde
        client = TestClient(app)
        resp = client.get("/api/engine/system_degraded")
        assert resp.status_code == 200
        data = resp.json()
        assert "posterior" in data
        assert "state" in data
        assert 0.0 <= data["posterior"] <= 1.0
        assert data["state"] in {"DEGRADED", "UNCERTAIN", "HEALTHY"}

    def test_state_responds_to_observations(self):
        from agents.hapax_daimonion.backends.engine_queue_depth import (
            DEFAULT_WATERMARK_DEPTH,
            queue_depth_observation,
        )
        from agents.hapax_daimonion.system_degraded_engine import SystemDegradedEngine

        class _StubQueue:
            def qsize(self):
                return DEFAULT_WATERMARK_DEPTH + 100

        sde = SystemDegradedEngine(prior=0.1, enter_ticks=2)
        for _ in range(8):
            sde.contribute(queue_depth_observation(_StubQueue()))
        app = _make_app(_mock_engine())
        app.state.system_degraded_engine = sde
        client = TestClient(app)
        resp = client.get("/api/engine/system_degraded")
        assert resp.status_code == 200
        assert resp.json()["state"] == "DEGRADED"

    def test_503_when_no_sde(self):
        client = TestClient(_make_app())
        resp = client.get("/api/engine/system_degraded")
        assert resp.status_code == 503


# ── TestOperatorActivityStatus (Phase 6a-i.B wire-in) ───────────────────


class TestOperatorActivityStatus:
    def test_returns_posterior_and_state(self):
        from agents.hapax_daimonion.operator_activity_engine import OperatorActivityEngine

        oae = OperatorActivityEngine()
        app = _make_app(_mock_engine())
        app.state.operator_activity_engine = oae
        client = TestClient(app)
        resp = client.get("/api/engine/operator_activity")
        assert resp.status_code == 200
        data = resp.json()
        assert "posterior" in data
        assert "state" in data
        assert 0.0 <= data["posterior"] <= 1.0
        assert data["state"] in {"ACTIVE", "UNCERTAIN", "IDLE"}

    def test_state_responds_to_observations(self):
        """Sustained keyboard_active=True drives ACTIVE within enter_ticks=1."""
        from agents.hapax_daimonion.backends.operator_activity_observation import (
            operator_activity_observation,
        )
        from agents.hapax_daimonion.operator_activity_engine import OperatorActivityEngine

        class _StubActive:
            def keyboard_active(self) -> bool:
                return True

            def desk_active(self) -> None:
                return None

            def desktop_focus_changed_recent(self) -> None:
                return None

            def midi_clock_active(self) -> None:
                return None

            def watch_movement(self) -> None:
                # Other-signals stubs are kept at None so this test
                # stays focused on the keyboard signal alone (engine
                # treats None as skip-this-signal-for-this-tick).
                return None

        oae = OperatorActivityEngine()
        for _ in range(3):
            oae.contribute(operator_activity_observation(_StubActive()))
        app = _make_app(_mock_engine())
        app.state.operator_activity_engine = oae
        client = TestClient(app)
        resp = client.get("/api/engine/operator_activity")
        assert resp.status_code == 200
        assert resp.json()["state"] == "ACTIVE"

    def test_503_when_no_oae(self):
        client = TestClient(_make_app())
        resp = client.get("/api/engine/operator_activity")
        assert resp.status_code == 503


# ── TestMoodArousalStatus (Phase 6b-i route) ────────────────────────────


class TestMoodArousalStatus:
    def test_returns_posterior_and_state(self):
        from agents.hapax_daimonion.mood_arousal_engine import MoodArousalEngine

        mae = MoodArousalEngine()
        app = _make_app(_mock_engine())
        app.state.mood_arousal_engine = mae
        client = TestClient(app)
        resp = client.get("/api/engine/mood_arousal")
        assert resp.status_code == 200
        data = resp.json()
        assert "posterior" in data
        assert "state" in data
        assert 0.0 <= data["posterior"] <= 1.0
        assert data["state"] in {"AROUSED", "UNCERTAIN", "CALM"}

    def test_state_responds_to_observations(self):
        """Sustained ambient_audio_rms_high=True drives AROUSED."""
        from agents.hapax_daimonion.backends.mood_arousal_observation import (
            mood_arousal_observation,
        )
        from agents.hapax_daimonion.mood_arousal_engine import MoodArousalEngine

        class _StubAroused:
            def ambient_audio_rms_high(self) -> bool:
                return True

            def contact_mic_onset_rate_high(self) -> bool:
                return True

            def midi_clock_bpm_high(self) -> bool:
                return True

            def hr_bpm_above_baseline(self) -> bool:
                return True

        mae = MoodArousalEngine()
        for _ in range(8):
            mae.contribute(mood_arousal_observation(_StubAroused()))
        app = _make_app(_mock_engine())
        app.state.mood_arousal_engine = mae
        client = TestClient(app)
        resp = client.get("/api/engine/mood_arousal")
        assert resp.status_code == 200
        assert resp.json()["state"] == "AROUSED"

    def test_503_when_no_mae(self):
        client = TestClient(_make_app())
        resp = client.get("/api/engine/mood_arousal")
        assert resp.status_code == 503


# ── TestMoodValenceStatus (Phase 6b-ii route) ───────────────────────────


class TestMoodValenceStatus:
    def test_returns_posterior_and_state(self):
        from agents.hapax_daimonion.mood_valence_engine import MoodValenceEngine

        mve = MoodValenceEngine()
        app = _make_app(_mock_engine())
        app.state.mood_valence_engine = mve
        client = TestClient(app)
        resp = client.get("/api/engine/mood_valence")
        assert resp.status_code == 200
        data = resp.json()
        assert "posterior" in data
        assert "state" in data
        assert 0.0 <= data["posterior"] <= 1.0
        assert data["state"] in {"NEGATIVE", "UNCERTAIN", "POSITIVE"}

    def test_state_responds_to_observations(self):
        """Sustained negative-valence signals drive NEGATIVE state."""
        from agents.hapax_daimonion.backends.mood_valence_observation import (
            mood_valence_observation,
        )
        from agents.hapax_daimonion.mood_valence_engine import MoodValenceEngine

        class _StubNegative:
            def hrv_below_baseline(self) -> bool:
                return True

            def skin_temp_drop(self) -> bool:
                return True

            def sleep_debt_high(self) -> bool:
                return True

            def voice_pitch_elevated(self) -> bool:
                return True

        mve = MoodValenceEngine()
        for _ in range(8):
            mve.contribute(mood_valence_observation(_StubNegative()))
        app = _make_app(_mock_engine())
        app.state.mood_valence_engine = mve
        client = TestClient(app)
        resp = client.get("/api/engine/mood_valence")
        assert resp.status_code == 200
        assert resp.json()["state"] == "NEGATIVE"

    def test_503_when_no_mve(self):
        client = TestClient(_make_app())
        resp = client.get("/api/engine/mood_valence")
        assert resp.status_code == 503


# ── TestMoodCoherenceStatus (Phase 6b-iii route) ────────────────────────


class TestMoodCoherenceStatus:
    def test_returns_posterior_and_state(self):
        from agents.hapax_daimonion.mood_coherence_engine import MoodCoherenceEngine

        mce = MoodCoherenceEngine()
        app = _make_app(_mock_engine())
        app.state.mood_coherence_engine = mce
        client = TestClient(app)
        resp = client.get("/api/engine/mood_coherence")
        assert resp.status_code == 200
        data = resp.json()
        assert "posterior" in data
        assert "state" in data
        assert 0.0 <= data["posterior"] <= 1.0
        assert data["state"] in {"INCOHERENT", "UNCERTAIN", "COHERENT"}

    def test_state_responds_to_observations(self):
        """Sustained volatility-high signals drive INCOHERENT state."""
        from agents.hapax_daimonion.backends.mood_coherence_observation import (
            mood_coherence_observation,
        )
        from agents.hapax_daimonion.mood_coherence_engine import MoodCoherenceEngine

        class _StubIncoherent:
            def hrv_variability_high(self) -> bool:
                return True

            def respiration_irregular(self) -> bool:
                return True

            def movement_jitter_high(self) -> bool:
                return True

            def skin_temp_volatility_high(self) -> bool:
                return True

        mce = MoodCoherenceEngine()
        for _ in range(8):
            mce.contribute(mood_coherence_observation(_StubIncoherent()))
        app = _make_app(_mock_engine())
        app.state.mood_coherence_engine = mce
        client = TestClient(app)
        resp = client.get("/api/engine/mood_coherence")
        assert resp.status_code == 200
        assert resp.json()["state"] == "INCOHERENT"

    def test_503_when_no_mce(self):
        client = TestClient(_make_app())
        resp = client.get("/api/engine/mood_coherence")
        assert resp.status_code == 503


# ── TestLogosPerceptionStateBridge ──────────────────────────────────────


class TestLogosPerceptionStateBridge:
    def test_missing_file_returns_none(self, tmp_path, monkeypatch):
        """Bridge must return None when perception-state.json is absent."""
        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        bridge = LogosPerceptionStateBridge()
        assert bridge.keyboard_active() is None

    def test_reads_keyboard_active_true(self, tmp_path, monkeypatch):
        """Bridge surfaces keyboard_active=True from a live state file."""
        import json

        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        state_dir = tmp_path / ".cache" / "hapax-daimonion"
        state_dir.mkdir(parents=True)
        (state_dir / "perception-state.json").write_text(
            json.dumps({"keyboard_active": True}), encoding="utf-8"
        )
        bridge = LogosPerceptionStateBridge()
        assert bridge.keyboard_active() is True

    def test_reads_keyboard_active_false(self, tmp_path, monkeypatch):
        """Bridge surfaces keyboard_active=False (real negative evidence)."""
        import json

        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        state_dir = tmp_path / ".cache" / "hapax-daimonion"
        state_dir.mkdir(parents=True)
        (state_dir / "perception-state.json").write_text(
            json.dumps({"keyboard_active": False}), encoding="utf-8"
        )
        bridge = LogosPerceptionStateBridge()
        assert bridge.keyboard_active() is False

    def test_missing_field_returns_none(self, tmp_path, monkeypatch):
        """Bridge returns None when the field is absent (not False)."""
        import json

        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        state_dir = tmp_path / ".cache" / "hapax-daimonion"
        state_dir.mkdir(parents=True)
        (state_dir / "perception-state.json").write_text(
            json.dumps({"other_field": "value"}), encoding="utf-8"
        )
        bridge = LogosPerceptionStateBridge()
        assert bridge.keyboard_active() is None

    def test_corrupt_json_returns_none(self, tmp_path, monkeypatch):
        """Bridge fails-soft on corrupt state file (both signals)."""
        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        state_dir = tmp_path / ".cache" / "hapax-daimonion"
        state_dir.mkdir(parents=True)
        (state_dir / "perception-state.json").write_text("not json", encoding="utf-8")
        bridge = LogosPerceptionStateBridge()
        assert bridge.keyboard_active() is None
        assert bridge.desk_active() is None

    def test_desk_active_idle_returns_false(self, tmp_path, monkeypatch):
        """Bridge maps desk_activity='idle' → False (real negative evidence)."""
        import json

        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        state_dir = tmp_path / ".cache" / "hapax-daimonion"
        state_dir.mkdir(parents=True)
        (state_dir / "perception-state.json").write_text(
            json.dumps({"desk_activity": "idle"}), encoding="utf-8"
        )
        bridge = LogosPerceptionStateBridge()
        assert bridge.desk_active() is False

    def test_desk_active_typing_returns_true(self, tmp_path, monkeypatch):
        """Bridge maps desk_activity='typing' → True (engagement signal)."""
        import json

        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        state_dir = tmp_path / ".cache" / "hapax-daimonion"
        state_dir.mkdir(parents=True)
        (state_dir / "perception-state.json").write_text(
            json.dumps({"desk_activity": "typing"}), encoding="utf-8"
        )
        bridge = LogosPerceptionStateBridge()
        assert bridge.desk_active() is True

    def test_desk_active_unknown_state_returns_true(self, tmp_path, monkeypatch):
        """Unknown desk_activity values count as active (anything-but-idle)."""
        import json

        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        state_dir = tmp_path / ".cache" / "hapax-daimonion"
        state_dir.mkdir(parents=True)
        (state_dir / "perception-state.json").write_text(
            json.dumps({"desk_activity": "drumming"}), encoding="utf-8"
        )
        bridge = LogosPerceptionStateBridge()
        assert bridge.desk_active() is True

    def test_desk_active_missing_field_returns_none(self, tmp_path, monkeypatch):
        """Missing desk_activity field → None (not False)."""
        import json

        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        state_dir = tmp_path / ".cache" / "hapax-daimonion"
        state_dir.mkdir(parents=True)
        (state_dir / "perception-state.json").write_text(
            json.dumps({"keyboard_active": True}), encoding="utf-8"
        )
        bridge = LogosPerceptionStateBridge()
        assert bridge.desk_active() is None

    def test_desk_active_case_insensitive(self, tmp_path, monkeypatch):
        """Idle states match case-insensitively (defensive against drift)."""
        import json

        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        state_dir = tmp_path / ".cache" / "hapax-daimonion"
        state_dir.mkdir(parents=True)
        (state_dir / "perception-state.json").write_text(
            json.dumps({"desk_activity": "IDLE"}), encoding="utf-8"
        )
        bridge = LogosPerceptionStateBridge()
        assert bridge.desk_active() is False

    def test_desktop_focus_first_call_returns_none(self, tmp_path, monkeypatch):
        """First observation has no prior state — return None (skip signal)."""
        import json

        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        state_dir = tmp_path / ".cache" / "hapax-daimonion"
        state_dir.mkdir(parents=True)
        (state_dir / "perception-state.json").write_text(
            json.dumps({"active_window_class": "foot"}), encoding="utf-8"
        )
        bridge = LogosPerceptionStateBridge()
        assert bridge.desktop_focus_changed_recent() is None

    def test_desktop_focus_unchanged_returns_false(self, tmp_path, monkeypatch):
        """Same active_window_class across two ticks → False (no change)."""
        import json

        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        state_dir = tmp_path / ".cache" / "hapax-daimonion"
        state_dir.mkdir(parents=True)
        path = state_dir / "perception-state.json"
        path.write_text(json.dumps({"active_window_class": "foot"}), encoding="utf-8")
        bridge = LogosPerceptionStateBridge()
        bridge.desktop_focus_changed_recent()  # prime
        assert bridge.desktop_focus_changed_recent() is False

    def test_desktop_focus_changed_returns_true(self, tmp_path, monkeypatch):
        """Different active_window_class on the second tick → True."""
        import json

        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        state_dir = tmp_path / ".cache" / "hapax-daimonion"
        state_dir.mkdir(parents=True)
        path = state_dir / "perception-state.json"
        path.write_text(json.dumps({"active_window_class": "foot"}), encoding="utf-8")
        bridge = LogosPerceptionStateBridge()
        bridge.desktop_focus_changed_recent()  # prime with "foot"
        path.write_text(json.dumps({"active_window_class": "firefox"}), encoding="utf-8")
        assert bridge.desktop_focus_changed_recent() is True

    def test_desktop_focus_sequential_changes_tracked(self, tmp_path, monkeypatch):
        """Each tick compares to the immediately-prior, not the original."""
        import json

        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        state_dir = tmp_path / ".cache" / "hapax-daimonion"
        state_dir.mkdir(parents=True)
        path = state_dir / "perception-state.json"
        path.write_text(json.dumps({"active_window_class": "foot"}), encoding="utf-8")
        bridge = LogosPerceptionStateBridge()
        bridge.desktop_focus_changed_recent()  # prime: "foot"

        path.write_text(json.dumps({"active_window_class": "firefox"}), encoding="utf-8")
        assert bridge.desktop_focus_changed_recent() is True  # foot → firefox
        path.write_text(json.dumps({"active_window_class": "firefox"}), encoding="utf-8")
        assert bridge.desktop_focus_changed_recent() is False  # firefox → firefox
        path.write_text(json.dumps({"active_window_class": "foot"}), encoding="utf-8")
        assert bridge.desktop_focus_changed_recent() is True  # firefox → foot

    def test_desktop_focus_missing_field_returns_none(self, tmp_path, monkeypatch):
        """Missing active_window_class field → None and prior state preserved."""
        import json

        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        state_dir = tmp_path / ".cache" / "hapax-daimonion"
        state_dir.mkdir(parents=True)
        path = state_dir / "perception-state.json"
        path.write_text(json.dumps({"active_window_class": "foot"}), encoding="utf-8")
        bridge = LogosPerceptionStateBridge()
        bridge.desktop_focus_changed_recent()  # prime: "foot"

        # Field temporarily disappears — None, prior state preserved
        path.write_text(json.dumps({"keyboard_active": True}), encoding="utf-8")
        assert bridge.desktop_focus_changed_recent() is None

        # Field returns with same value — False (compared to preserved prior)
        path.write_text(json.dumps({"active_window_class": "foot"}), encoding="utf-8")
        assert bridge.desktop_focus_changed_recent() is False

    def test_desktop_focus_missing_file_does_not_advance_state(self, tmp_path, monkeypatch):
        """Transient daimonion outage must not produce spurious change reports."""
        import json

        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        state_dir = tmp_path / ".cache" / "hapax-daimonion"
        state_dir.mkdir(parents=True)
        path = state_dir / "perception-state.json"
        path.write_text(json.dumps({"active_window_class": "foot"}), encoding="utf-8")
        bridge = LogosPerceptionStateBridge()
        bridge.desktop_focus_changed_recent()  # prime: "foot"

        path.unlink()
        assert bridge.desktop_focus_changed_recent() is None  # outage
        path.write_text(json.dumps({"active_window_class": "foot"}), encoding="utf-8")
        # Recovery on the same window — must be False, not True (would
        # be a spurious change report if state had been wiped on outage)
        assert bridge.desktop_focus_changed_recent() is False


# ── TestOperatorActivityObservation (adapter-level) ─────────────────────


class TestOperatorActivityObservation:
    def test_returns_dict_with_all_five_signals(self):
        from agents.hapax_daimonion.backends.operator_activity_observation import (
            operator_activity_observation,
        )

        class _StubAll:
            def keyboard_active(self) -> bool:
                return True

            def desk_active(self) -> bool:
                return False

            def desktop_focus_changed_recent(self) -> bool:
                return True

            def midi_clock_active(self) -> bool:
                return False

            def watch_movement(self) -> bool:
                return True

        obs = operator_activity_observation(_StubAll())
        assert obs == {
            "keyboard_active": True,
            "desk_active": False,
            "desktop_focus_changed_recent": True,
            "midi_clock_active": False,
            "watch_movement": True,
        }

    def test_returns_none_when_source_returns_none(self):
        """None propagates per-signal so engine.tick skips that signal."""
        from agents.hapax_daimonion.backends.operator_activity_observation import (
            operator_activity_observation,
        )

        class _StubNone:
            def keyboard_active(self) -> None:
                return None

            def desk_active(self) -> None:
                return None

            def desktop_focus_changed_recent(self) -> None:
                return None

            def midi_clock_active(self) -> None:
                return None

            def watch_movement(self) -> None:
                return None

        obs = operator_activity_observation(_StubNone())
        assert obs == {
            "keyboard_active": None,
            "desk_active": None,
            "desktop_focus_changed_recent": None,
            "midi_clock_active": None,
            "watch_movement": None,
        }

    def test_signals_independent(self):
        """Each signal can be live or None independently of the others."""
        from agents.hapax_daimonion.backends.operator_activity_observation import (
            operator_activity_observation,
        )

        class _StubMixed:
            def keyboard_active(self) -> bool:
                return True

            def desk_active(self) -> None:
                return None

            def desktop_focus_changed_recent(self) -> bool:
                return False

            def midi_clock_active(self) -> None:
                return None

            def watch_movement(self) -> None:
                return None

        obs = operator_activity_observation(_StubMixed())
        assert obs == {
            "keyboard_active": True,
            "desk_active": None,
            "desktop_focus_changed_recent": False,
            "midi_clock_active": None,
            "watch_movement": None,
        }


class TestLogosPerceptionStateBridgeMidiClock:
    """Pin Part 4 wire-in: midi_clock_active reads midi_clock_transport.

    ``MidiClockBackend.contribute()`` publishes ``midi_clock_transport``
    (TransportState enum name); the perception-state writer surfaces it
    in the same JSON file the bridge already reads. PLAYING → True,
    STOPPED → False (real negative evidence: a known-good backend
    reporting no clock pulse is informative). Missing field or empty
    string → None (engine skips the signal).
    """

    def test_midi_clock_active_playing_returns_true(self, tmp_path, monkeypatch):
        import json

        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        state_dir = tmp_path / ".cache" / "hapax-daimonion"
        state_dir.mkdir(parents=True)
        (state_dir / "perception-state.json").write_text(
            json.dumps({"midi_clock_transport": "PLAYING"}), encoding="utf-8"
        )
        assert LogosPerceptionStateBridge().midi_clock_active() is True

    def test_midi_clock_active_stopped_returns_false(self, tmp_path, monkeypatch):
        import json

        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        state_dir = tmp_path / ".cache" / "hapax-daimonion"
        state_dir.mkdir(parents=True)
        (state_dir / "perception-state.json").write_text(
            json.dumps({"midi_clock_transport": "STOPPED"}), encoding="utf-8"
        )
        assert LogosPerceptionStateBridge().midi_clock_active() is False

    def test_midi_clock_active_empty_string_returns_none(self, tmp_path, monkeypatch):
        """Default behavior value (empty string before any tick) → None."""
        import json

        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        state_dir = tmp_path / ".cache" / "hapax-daimonion"
        state_dir.mkdir(parents=True)
        (state_dir / "perception-state.json").write_text(
            json.dumps({"midi_clock_transport": ""}), encoding="utf-8"
        )
        assert LogosPerceptionStateBridge().midi_clock_active() is None

    def test_midi_clock_active_missing_field_returns_none(self, tmp_path, monkeypatch):
        import json

        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        state_dir = tmp_path / ".cache" / "hapax-daimonion"
        state_dir.mkdir(parents=True)
        (state_dir / "perception-state.json").write_text(
            json.dumps({"keyboard_active": True}), encoding="utf-8"
        )
        assert LogosPerceptionStateBridge().midi_clock_active() is None

    def test_midi_clock_active_missing_file_returns_none(self, tmp_path, monkeypatch):
        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        assert LogosPerceptionStateBridge().midi_clock_active() is None


class TestLogosPerceptionStateBridgeWatchMovement:
    """Pin Part 5 wire-in: watch_movement reads activity.json.

    Bridge reads ``~/hapax-state/watch/activity.json`` (written by
    hapax-watch-receiver). State enum maps {STILL, RESTING, SEDENTARY}
    → False, anything else → True. Stale data (>10 min) returns None
    to avoid spurious IDLE decay on a dropped BLE link. Closes the
    OAE bridge surface 5/5 (4 wired + 1 was scaffolded → 5 wired).
    """

    @staticmethod
    def _write_activity(tmp_path, payload: dict) -> None:
        import json

        d = tmp_path / "hapax-state" / "watch"
        d.mkdir(parents=True, exist_ok=True)
        (d / "activity.json").write_text(json.dumps(payload), encoding="utf-8")

    def _fresh_iso(self) -> str:
        from datetime import UTC, datetime

        return datetime.now(UTC).isoformat()

    def test_walking_returns_true(self, tmp_path, monkeypatch):
        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        self._write_activity(tmp_path, {"updated_at": self._fresh_iso(), "state": "WALKING"})
        assert LogosPerceptionStateBridge().watch_movement() is True

    def test_running_returns_true(self, tmp_path, monkeypatch):
        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        self._write_activity(tmp_path, {"updated_at": self._fresh_iso(), "state": "RUNNING"})
        assert LogosPerceptionStateBridge().watch_movement() is True

    def test_still_returns_false(self, tmp_path, monkeypatch):
        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        self._write_activity(tmp_path, {"updated_at": self._fresh_iso(), "state": "STILL"})
        assert LogosPerceptionStateBridge().watch_movement() is False

    def test_resting_returns_false(self, tmp_path, monkeypatch):
        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        self._write_activity(tmp_path, {"updated_at": self._fresh_iso(), "state": "RESTING"})
        assert LogosPerceptionStateBridge().watch_movement() is False

    def test_state_lowercase_normalised(self, tmp_path, monkeypatch):
        """Pixel Watch shouldn't send lowercase but be tolerant of it."""
        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        self._write_activity(tmp_path, {"updated_at": self._fresh_iso(), "state": "still"})
        assert LogosPerceptionStateBridge().watch_movement() is False

    def test_missing_file_returns_none(self, tmp_path, monkeypatch):
        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        assert LogosPerceptionStateBridge().watch_movement() is None

    def test_corrupt_json_returns_none(self, tmp_path, monkeypatch):
        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        d = tmp_path / "hapax-state" / "watch"
        d.mkdir(parents=True, exist_ok=True)
        (d / "activity.json").write_text("not json", encoding="utf-8")
        assert LogosPerceptionStateBridge().watch_movement() is None

    def test_missing_state_field_returns_none(self, tmp_path, monkeypatch):
        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        self._write_activity(tmp_path, {"updated_at": self._fresh_iso()})
        assert LogosPerceptionStateBridge().watch_movement() is None

    def test_stale_data_returns_none(self, tmp_path, monkeypatch):
        """updated_at older than 10 min → None (BLE drop, not still)."""
        from datetime import UTC, datetime, timedelta

        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        stale = (datetime.now(UTC) - timedelta(minutes=15)).isoformat()
        self._write_activity(tmp_path, {"updated_at": stale, "state": "WALKING"})
        assert LogosPerceptionStateBridge().watch_movement() is None

    def test_naive_timestamp_treated_as_utc(self, tmp_path, monkeypatch):
        """A timestamp lacking tz is assumed UTC (don't reject as stale on tz absence)."""
        from datetime import UTC, datetime

        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        naive = datetime.now(UTC).replace(tzinfo=None).isoformat()
        self._write_activity(tmp_path, {"updated_at": naive, "state": "WALKING"})
        assert LogosPerceptionStateBridge().watch_movement() is True

    def test_malformed_timestamp_returns_none(self, tmp_path, monkeypatch):
        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        self._write_activity(tmp_path, {"updated_at": "not-a-timestamp", "state": "WALKING"})
        assert LogosPerceptionStateBridge().watch_movement() is None

    def test_independent_of_perception_state(self, tmp_path, monkeypatch):
        """watch reads its own file — wired regardless of perception-state.json."""
        import json

        from logos.api.app import LogosPerceptionStateBridge

        monkeypatch.setenv("HOME", str(tmp_path))
        # No perception-state.json at all.
        self._write_activity(tmp_path, {"updated_at": self._fresh_iso(), "state": "WALKING"})
        bridge = LogosPerceptionStateBridge()
        assert bridge.watch_movement() is True
        assert bridge.keyboard_active() is None
        # And vice versa: live perception-state, no watch file → None.
        bridge2 = LogosPerceptionStateBridge()
        (tmp_path / ".cache" / "hapax-daimonion").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".cache" / "hapax-daimonion" / "perception-state.json").write_text(
            json.dumps({"keyboard_active": True}), encoding="utf-8"
        )
        (tmp_path / "hapax-state" / "watch" / "activity.json").unlink()
        assert bridge2.keyboard_active() is True
        assert bridge2.watch_movement() is None


# ── TestLogosStimmungBridge (Phase 6b-i.B wire-in) ──────────────────────


class TestLogosStimmungBridge:
    """Stimmung bridge: all 4 mood-arousal signal accessors.

    Part 1 ships the protocol-matching surface with all accessors
    returning ``None`` so the engine math runs with no live signal
    contribution. Per-signal threshold wiring lands in subsequent PRs
    (Part 2-5) — same additive pattern delta used in #1389.
    """

    def test_ambient_audio_rms_high_returns_none(self):
        from logos.api.app import LogosStimmungBridge

        assert LogosStimmungBridge().ambient_audio_rms_high() is None

    def test_contact_mic_onset_rate_high_returns_none(self):
        from logos.api.app import LogosStimmungBridge

        assert LogosStimmungBridge().contact_mic_onset_rate_high() is None

    def test_midi_clock_bpm_high_returns_none(self):
        from logos.api.app import LogosStimmungBridge

        assert LogosStimmungBridge().midi_clock_bpm_high() is None

    def test_hr_bpm_above_baseline_returns_none(self):
        from logos.api.app import LogosStimmungBridge

        assert LogosStimmungBridge().hr_bpm_above_baseline() is None


# ── TestMoodArousalObservation (Phase 6b-i.B adapter) ───────────────────


class TestMoodArousalObservation:
    def test_returns_four_signal_dict_with_none_values(self):
        """Default scaffolding bridge returns all-None observation dict."""
        from agents.hapax_daimonion.backends.mood_arousal_observation import (
            mood_arousal_observation,
        )
        from logos.api.app import LogosStimmungBridge

        obs = mood_arousal_observation(LogosStimmungBridge())
        assert obs == {
            "ambient_audio_rms_high": None,
            "contact_mic_onset_rate_high": None,
            "midi_clock_bpm_high": None,
            "hr_bpm_above_baseline": None,
        }

    def test_propagates_signal_values_when_source_provides_them(self):
        """Non-None values from the source flow through to the engine."""
        from agents.hapax_daimonion.backends.mood_arousal_observation import (
            mood_arousal_observation,
        )

        class _StubMixed:
            def ambient_audio_rms_high(self) -> bool:
                return True

            def contact_mic_onset_rate_high(self) -> None:
                return None

            def midi_clock_bpm_high(self) -> bool:
                return False

            def hr_bpm_above_baseline(self) -> bool:
                return True

        obs = mood_arousal_observation(_StubMixed())
        assert obs == {
            "ambient_audio_rms_high": True,
            "contact_mic_onset_rate_high": None,
            "midi_clock_bpm_high": False,
            "hr_bpm_above_baseline": True,
        }

    def test_engine_consumes_observation_without_error(self):
        """Adapter output is a valid argument to MoodArousalEngine.contribute()."""
        from agents.hapax_daimonion.backends.mood_arousal_observation import (
            mood_arousal_observation,
        )
        from agents.hapax_daimonion.mood_arousal_engine import MoodArousalEngine
        from logos.api.app import LogosStimmungBridge

        engine = MoodArousalEngine()
        for _ in range(5):
            engine.contribute(mood_arousal_observation(LogosStimmungBridge()))
        # All-None observations leave posterior at prior (no log-odds update).
        assert engine.posterior == pytest.approx(0.30)
        assert engine.state == "UNCERTAIN"


# ── TestLogosMoodValenceBridge (Phase 6b-ii.B wire-in) ──────────────────


class TestLogosMoodValenceBridge:
    """Mood-valence bridge: all 4 health/voice signal accessors.

    Missing/stale sources return ``None`` so the engine skips those
    signals. Calibrated live sources are covered in the dedicated mood
    bridge calibration tests.
    """

    def test_hrv_below_baseline_returns_none(self):
        from logos.api.app import LogosMoodValenceBridge

        assert LogosMoodValenceBridge().hrv_below_baseline() is None

    def test_skin_temp_drop_returns_none(self):
        from logos.api.app import LogosMoodValenceBridge

        assert LogosMoodValenceBridge().skin_temp_drop() is None

    def test_sleep_debt_high_returns_none(self):
        from logos.api.app import LogosMoodValenceBridge

        with patch("pathlib.Path.read_text", side_effect=FileNotFoundError):
            assert LogosMoodValenceBridge().sleep_debt_high() is None

    def test_voice_pitch_elevated_returns_none(self):
        from logos.api.app import LogosMoodValenceBridge

        assert LogosMoodValenceBridge().voice_pitch_elevated() is None


# ── TestMoodValenceObservation (Phase 6b-ii.B adapter) ──────────────────


class TestMoodValenceObservation:
    def test_returns_four_signal_dict_with_none_values(self):
        """Missing source files return all-None observation dict."""
        from agents.hapax_daimonion.backends.mood_valence_observation import (
            mood_valence_observation,
        )
        from logos.api.app import LogosMoodValenceBridge

        with patch("pathlib.Path.read_text", side_effect=FileNotFoundError):
            obs = mood_valence_observation(LogosMoodValenceBridge())
        assert obs == {
            "hrv_below_baseline": None,
            "skin_temp_drop": None,
            "sleep_debt_high": None,
            "voice_pitch_elevated": None,
        }

    def test_propagates_signal_values_when_source_provides_them(self):
        """Non-None values from the source flow through to the engine."""
        from agents.hapax_daimonion.backends.mood_valence_observation import (
            mood_valence_observation,
        )

        class _StubMixed:
            def hrv_below_baseline(self) -> bool:
                return True

            def skin_temp_drop(self) -> None:
                return None

            def sleep_debt_high(self) -> bool:
                return False

            def voice_pitch_elevated(self) -> bool:
                return True

        obs = mood_valence_observation(_StubMixed())
        assert obs == {
            "hrv_below_baseline": True,
            "skin_temp_drop": None,
            "sleep_debt_high": False,
            "voice_pitch_elevated": True,
        }

    def test_engine_consumes_observation_without_error(self):
        """Adapter output is a valid argument to MoodValenceEngine.contribute()."""
        from agents.hapax_daimonion.backends.mood_valence_observation import (
            mood_valence_observation,
        )
        from agents.hapax_daimonion.mood_valence_engine import MoodValenceEngine
        from logos.api.app import LogosMoodValenceBridge

        engine = MoodValenceEngine()
        for _ in range(5):
            engine.contribute(mood_valence_observation(LogosMoodValenceBridge()))
        # All-None observations leave posterior at prior. Prior 0.20 is
        # below exit_threshold 0.30, so the engine starts in RETRACTED
        # state — translates to POSITIVE in the valence vocabulary.
        assert engine.posterior == pytest.approx(0.20)
        assert engine.state == "POSITIVE"


# ── TestLogosMoodCoherenceBridge (Phase 6b-iii.B wire-in) ───────────────


class TestLogosMoodCoherenceBridge:
    """Mood-coherence bridge: all 4 health-volatility signal accessors.

    Missing/stale sources return ``None`` so the engine skips those
    signals. Calibrated live sources are covered in the dedicated mood
    bridge calibration tests.
    """

    def test_hrv_variability_high_returns_none(self):
        from logos.api.app import LogosMoodCoherenceBridge

        assert LogosMoodCoherenceBridge().hrv_variability_high() is None

    def test_respiration_irregular_returns_none(self):
        from logos.api.app import LogosMoodCoherenceBridge

        assert LogosMoodCoherenceBridge().respiration_irregular() is None

    def test_movement_jitter_high_returns_none(self):
        from logos.api.app import LogosMoodCoherenceBridge

        with patch("pathlib.Path.read_text", side_effect=FileNotFoundError):
            assert LogosMoodCoherenceBridge().movement_jitter_high() is None

    def test_skin_temp_volatility_high_returns_none(self):
        from logos.api.app import LogosMoodCoherenceBridge

        assert LogosMoodCoherenceBridge().skin_temp_volatility_high() is None


# ── TestMoodCoherenceObservation (Phase 6b-iii.B adapter) ───────────────


class TestMoodCoherenceObservation:
    def test_returns_four_signal_dict_with_none_values(self):
        """Missing source files return all-None observation dict."""
        from agents.hapax_daimonion.backends.mood_coherence_observation import (
            mood_coherence_observation,
        )
        from logos.api.app import LogosMoodCoherenceBridge

        with patch("pathlib.Path.read_text", side_effect=FileNotFoundError):
            obs = mood_coherence_observation(LogosMoodCoherenceBridge())
        assert obs == {
            "hrv_variability_high": None,
            "respiration_irregular": None,
            "movement_jitter_high": None,
            "skin_temp_volatility_high": None,
        }

    def test_propagates_signal_values_when_source_provides_them(self):
        """Non-None values from the source flow through to the engine."""
        from agents.hapax_daimonion.backends.mood_coherence_observation import (
            mood_coherence_observation,
        )

        class _StubMixed:
            def hrv_variability_high(self) -> bool:
                return True

            def respiration_irregular(self) -> None:
                return None

            def movement_jitter_high(self) -> bool:
                return False

            def skin_temp_volatility_high(self) -> bool:
                return True

        obs = mood_coherence_observation(_StubMixed())
        assert obs == {
            "hrv_variability_high": True,
            "respiration_irregular": None,
            "movement_jitter_high": False,
            "skin_temp_volatility_high": True,
        }

    def test_engine_consumes_observation_without_error(self):
        """Adapter output is a valid argument to MoodCoherenceEngine.contribute()."""
        from agents.hapax_daimonion.backends.mood_coherence_observation import (
            mood_coherence_observation,
        )
        from agents.hapax_daimonion.mood_coherence_engine import MoodCoherenceEngine
        from logos.api.app import LogosMoodCoherenceBridge

        engine = MoodCoherenceEngine()
        for _ in range(5):
            engine.contribute(mood_coherence_observation(LogosMoodCoherenceBridge()))
        # All-None observations leave posterior at prior. Prior 0.15 is
        # below exit_threshold (engine starts RETRACTED) — translates to
        # COHERENT in the negative-tier vocabulary INCOHERENT/UNCERTAIN/COHERENT.
        assert engine.posterior == pytest.approx(0.15)
        assert engine.state == "COHERENT"


# ── TestLogosDriftBridge ────────────────────────────────────────────────


class TestLogosDriftBridge:
    """Drift bridge: collect_drift() → drift_score() Protocol."""

    def test_no_summary_yields_zero_score(self):
        from unittest.mock import patch

        from logos.api.app import LogosDriftBridge

        with patch("logos.data.drift.collect_drift", return_value=None):
            assert LogosDriftBridge().drift_score() == 0.0

    def test_no_high_items_yields_zero(self):
        from unittest.mock import MagicMock, patch

        from logos.api.app import LogosDriftBridge

        summary = MagicMock()
        item = MagicMock()
        item.severity = "low"
        summary.items = [item, item, item]
        with patch("logos.data.drift.collect_drift", return_value=summary):
            assert LogosDriftBridge().drift_score() == 0.0

    def test_5_high_items_yields_half_score(self):
        from unittest.mock import MagicMock, patch

        from logos.api.app import LogosDriftBridge

        summary = MagicMock()
        items = [MagicMock(severity="HIGH") for _ in range(5)]
        items.extend([MagicMock(severity="low") for _ in range(2)])
        summary.items = items
        with patch("logos.data.drift.collect_drift", return_value=summary):
            assert LogosDriftBridge().drift_score() == 0.5

    def test_score_saturates_at_one(self):
        from unittest.mock import MagicMock, patch

        from logos.api.app import LogosDriftBridge

        summary = MagicMock()
        summary.items = [MagicMock(severity="HIGH") for _ in range(50)]
        with patch("logos.data.drift.collect_drift", return_value=summary):
            assert LogosDriftBridge().drift_score() == 1.0

    def test_severity_case_insensitive(self):
        from unittest.mock import MagicMock, patch

        from logos.api.app import LogosDriftBridge

        summary = MagicMock()
        summary.items = [
            MagicMock(severity="High"),
            MagicMock(severity="HIGH"),
            MagicMock(severity="high"),
        ]
        with patch("logos.data.drift.collect_drift", return_value=summary):
            assert LogosDriftBridge().drift_score() == 0.3

    def test_drift_bridge_drives_engine_to_degraded(self):
        from unittest.mock import MagicMock, patch

        from agents.hapax_daimonion.backends.drift_significant import (
            drift_significant_observation,
        )
        from agents.hapax_daimonion.system_degraded_engine import SystemDegradedEngine
        from logos.api.app import LogosDriftBridge

        summary = MagicMock()
        summary.items = [MagicMock(severity="HIGH") for _ in range(15)]
        with patch("logos.data.drift.collect_drift", return_value=summary):
            bridge = LogosDriftBridge()
            sde = SystemDegradedEngine(prior=0.1, enter_ticks=2)
            for _ in range(8):
                sde.contribute(drift_significant_observation(bridge))
            assert sde.state == "DEGRADED"


# ── TestLogosGpuBridge ──────────────────────────────────────────────────


class TestLogosGpuBridge:
    """GPU pressure bridge: infra-snapshot.json → gpu_memory_used_total() Protocol."""

    def test_missing_snapshot_yields_zero_zero(self, tmp_path):
        from unittest.mock import patch

        from logos.api.app import LogosGpuBridge

        with patch("logos._config.PROFILES_DIR", tmp_path):
            assert LogosGpuBridge().gpu_memory_used_total() == (0, 0)

    def test_invalid_json_yields_zero_zero(self, tmp_path):
        from unittest.mock import patch

        from logos.api.app import LogosGpuBridge

        (tmp_path / "infra-snapshot.json").write_text("not json")
        with patch("logos._config.PROFILES_DIR", tmp_path):
            assert LogosGpuBridge().gpu_memory_used_total() == (0, 0)

    def test_missing_gpu_block_yields_zero_zero(self, tmp_path):
        import json
        from unittest.mock import patch

        from logos.api.app import LogosGpuBridge

        (tmp_path / "infra-snapshot.json").write_text(json.dumps({"other": "data"}))
        with patch("logos._config.PROFILES_DIR", tmp_path):
            assert LogosGpuBridge().gpu_memory_used_total() == (0, 0)

    def test_gpu_block_with_used_total(self, tmp_path):
        import json
        from unittest.mock import patch

        from logos.api.app import LogosGpuBridge

        (tmp_path / "infra-snapshot.json").write_text(
            json.dumps({"gpu": {"used_mb": 21500, "total_mb": 24576}})
        )
        with patch("logos._config.PROFILES_DIR", tmp_path):
            assert LogosGpuBridge().gpu_memory_used_total() == (21500, 24576)

    def test_gpu_bridge_drives_engine_to_degraded(self, tmp_path):
        import json
        from unittest.mock import patch

        from agents.hapax_daimonion.backends.gpu_pressure import gpu_pressure_observation
        from agents.hapax_daimonion.system_degraded_engine import SystemDegradedEngine
        from logos.api.app import LogosGpuBridge

        (tmp_path / "infra-snapshot.json").write_text(
            json.dumps({"gpu": {"used_mb": 23000, "total_mb": 24576}})
        )
        with patch("logos._config.PROFILES_DIR", tmp_path):
            bridge = LogosGpuBridge()
            sde = SystemDegradedEngine(prior=0.1, enter_ticks=2)
            for _ in range(8):
                sde.contribute(gpu_pressure_observation(bridge))
            assert sde.state == "DEGRADED"
