"""Tests for DMN audit fixes — fortress feedback, sensor logging, API routes."""

import json
import time
from unittest.mock import patch

import pytest

from agents._impingement import Impingement, ImpingementType
from agents.dmn.buffer import DMNBuffer
from agents.dmn.pulse import DMNPulse


class TestFortressFeedbackWiring:
    """Tests that DMN reads fortress.action_taken impingements and suppresses re-emission."""

    def test_consume_fortress_feedback_from_dedicated_file(self, tmp_path):
        """DMNDaemon reads fortress feedback from dedicated fortress-actions.jsonl."""
        from agents.dmn.__main__ import DMNDaemon

        daemon = DMNDaemon()
        actions_file = tmp_path / "fortress-actions.jsonl"

        feedback = Impingement(
            timestamp=time.time(),
            source="fortress.action_taken",
            type=ImpingementType.ABSOLUTE_THRESHOLD,
            strength=0.3,
            content={"trigger_metric": "drink_per_capita", "action_type": "brew"},
        )
        actions_file.write_text(feedback.model_dump_json() + "\n")

        daemon._consume_fortress_feedback(path=actions_file)
        assert "drink_per_capita" in daemon._pulse._fortress_acted_on

    def test_cursor_advances_past_read_lines(self, tmp_path):
        """Feedback cursor advances so lines aren't re-processed."""
        from agents.dmn.__main__ import DMNDaemon

        daemon = DMNDaemon()
        actions_file = tmp_path / "fortress-actions.jsonl"

        feedback = Impingement(
            timestamp=time.time(),
            source="fortress.action_taken",
            type=ImpingementType.ABSOLUTE_THRESHOLD,
            strength=0.3,
            content={"trigger_metric": "drink_per_capita", "action_type": "brew"},
        )
        actions_file.write_text(feedback.model_dump_json() + "\n")

        daemon._consume_fortress_feedback(path=actions_file)
        cursor_after_first = daemon._feedback_cursor

        with actions_file.open("a") as f:
            f.write(feedback.model_dump_json() + "\n")

        daemon._consume_fortress_feedback(path=actions_file)
        assert daemon._feedback_cursor > cursor_after_first

    def test_suppression_prevents_threshold_reemission(self):
        """After fortress acts on drink_per_capita, DMN doesn't re-emit it."""
        buf = DMNBuffer()
        pulse = DMNPulse(buf)

        # Simulate fortress feedback
        feedback = [
            Impingement(
                timestamp=time.time(),
                source="fortress.action_taken",
                type=ImpingementType.ABSOLUTE_THRESHOLD,
                strength=0.3,
                content={"trigger_metric": "drink_per_capita", "action_type": "brew"},
            )
        ]
        pulse.consume_fortress_feedback(feedback)

        # Now check thresholds — drink is low but should be suppressed
        snapshot = {
            "fortress": {"population": 10, "drink": 5, "fortress_name": "test"},
            "stimmung": {"stance": "nominal"},
        }
        pulse._check_absolute_thresholds(snapshot)
        impingements = pulse.drain_impingements()
        drink_imps = [i for i in impingements if i.content.get("metric") == "drink_per_capita"]
        assert len(drink_imps) == 0


class TestConsolidationTick:
    """Tests for the consolidation tick path."""

    async def test_consolidation_tick_sets_summary_and_prunes(self):
        buf = DMNBuffer()
        pulse = DMNPulse(buf)
        for i in range(14):
            buf.add_observation(f"obs {i}", raw_sensor=f"raw sensor data {i}")

        assert buf.needs_consolidation()
        with (
            patch("agents.dmn.pulse.start_thinking") as mock_start,
            patch("agents.dmn.pulse.collect_thinking", return_value=None),
        ):
            await pulse._consolidation_tick()
            mock_start.assert_called_once()

        with patch(
            "agents.dmn.pulse.collect_thinking",
            return_value="Compressed: 14 observations showing stable coding session.",
        ):
            await pulse._consolidation_tick()

        assert "Compressed" in buf._retentional_summary
        assert len(buf) < 14

    async def test_consolidation_tick_noop_when_empty(self):
        buf = DMNBuffer()
        pulse = DMNPulse(buf)
        with (
            patch("agents.dmn.pulse.collect_thinking", return_value=None),
            patch("agents.dmn.pulse.start_thinking") as mock_start,
        ):
            await pulse._consolidation_tick()
            mock_start.assert_not_called()


class TestSensorReadFailures:
    """Tests that sensor read failures are logged (not silent)."""

    def test_read_json_logs_on_decode_error(self, tmp_path, caplog):
        import logging

        from agents.dmn.sensor import _read_json

        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid json content")
        with caplog.at_level(logging.DEBUG, logger="dmn.sensor"):
            result = _read_json(bad_file)
        assert result is None
        assert any("Failed to read" in r.message for r in caplog.records)

    def test_read_json_returns_none_on_missing(self, tmp_path):
        from agents.dmn.sensor import _read_json

        result = _read_json(tmp_path / "nonexistent.json")
        assert result is None


class TestOllamaLogLevel:
    """Tests that Ollama failures are logged at WARNING, not DEBUG."""

    async def test_ollama_failure_logs_warning(self, caplog):
        import logging

        import httpx

        from agents.dmn.ollama import _ollama_fast

        with (
            caplog.at_level(logging.DEBUG, logger="dmn.ollama"),
            patch(
                "agents.dmn.ollama.httpx.AsyncClient.post",
                side_effect=httpx.ConnectError("test connection refused"),
            ),
        ):
            result = await _ollama_fast("test prompt", "test system")
        assert result == ""
        ollama_records = [r for r in caplog.records if r.name == "dmn.ollama"]
        assert any(r.levelno >= logging.WARNING for r in ollama_records)


try:
    import fastapi  # noqa: F401

    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


@pytest.mark.skipif(not _HAS_FASTAPI, reason="fastapi not installed")
class TestDMNApiRoutes:
    """Tests for the Logos API DMN routes."""

    @pytest.fixture
    def dmn_dir(self, tmp_path):
        d = tmp_path / "hapax-dmn"
        d.mkdir()
        return d

    def test_buffer_route_returns_content(self, dmn_dir):
        from starlette.testclient import TestClient

        from logos.api.routes.dmn import router

        buf_file = dmn_dir / "buffer.txt"
        buf_file.write_text("<retentional_summary>test</retentional_summary>")

        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)

        with patch("logos.api.routes.dmn.BUFFER_FILE", buf_file):
            client = TestClient(app)
            resp = client.get("/api/dmn/buffer")
        assert resp.status_code == 200
        assert "retentional_summary" in resp.text

    def test_status_route_returns_json(self, dmn_dir):
        from starlette.testclient import TestClient

        from logos.api.routes.dmn import router

        status_file = dmn_dir / "status.json"
        status_file.write_text(json.dumps({"running": True, "uptime_s": 42.0, "tick": 10}))

        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)

        with patch("logos.api.routes.dmn.STATUS_FILE", status_file):
            client = TestClient(app)
            resp = client.get("/api/dmn/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is True
        assert data["tick"] == 10

    def test_impingements_route_returns_tail(self, dmn_dir):
        from starlette.testclient import TestClient

        from logos.api.routes.dmn import router

        imp_file = dmn_dir / "impingements.jsonl"
        lines = []
        for i in range(10):
            imp = {
                "id": f"imp{i}",
                "timestamp": time.time(),
                "source": "dmn.evaluative",
                "type": "salience_integration",
                "strength": 0.5,
            }
            lines.append(json.dumps(imp))
        imp_file.write_text("\n".join(lines) + "\n")

        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)

        with patch("logos.api.routes.dmn.IMPINGEMENTS_FILE", imp_file):
            client = TestClient(app)
            resp = client.get("/api/dmn/impingements?tail=3")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        assert data[-1]["id"] == "imp9"

    def test_status_route_503_when_not_running(self, dmn_dir):
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from logos.api.routes.dmn import router

        app = FastAPI()
        app.include_router(router)

        missing = dmn_dir / "nonexistent_status.json"
        with patch("logos.api.routes.dmn.STATUS_FILE", missing):
            client = TestClient(app)
            resp = client.get("/api/dmn/status")
        assert resp.status_code == 503
