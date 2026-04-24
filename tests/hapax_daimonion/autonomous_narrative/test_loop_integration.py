"""Integration tests for the autonomous_narrative loop end-to-end."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.hapax_daimonion.autonomous_narrative import emit, loop, state_readers


@pytest.fixture
def absent_daemon() -> MagicMock:
    """Daemon mock that signals operator-absent + has the necessary surfaces."""
    daemon = MagicMock()
    daemon._running = True
    daemon.perception.latest.presence_score = 0.0
    daemon.session.is_active = False
    daemon._processing_utterance = False
    daemon.programme_manager.store.active_programme.return_value = None
    return daemon


def _populate_chronicle(path: Path, narrative: str = "vinyl side change") -> None:
    """Seed a chronicle file with one in-window event (current Unix time).

    Uses ``time.time()`` so the loop's ``now - 600`` cutoff doesn't filter
    it out as ancient. The reader requires the event ``ts`` to be within
    the last 600 s of wall-clock time.
    """
    import time as _time

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "ts": _time.time() - 30.0,  # 30 s ago, comfortably in window
                "source": "audio.vinyl",
                "intent_family": "vinyl.side_change",
                "content": {"salience": 0.8, "narrative": narrative},
            }
        )
        + "\n"
    )


# ── env-flag gate (default OFF) ───────────────────────────────────────────


def test_loop_is_no_op_when_disabled(absent_daemon, monkeypatch) -> None:
    """Default OFF: loop spins as no-op until env var flips."""
    monkeypatch.delenv("HAPAX_AUTONOMOUS_NARRATIVE_ENABLED", raising=False)

    async def _run_briefly():
        async def _stop_after():
            await asyncio.sleep(0.05)
            absent_daemon._running = False

        await asyncio.gather(loop.autonomous_narrative_loop(absent_daemon), _stop_after())

    # Should not raise; should not emit anything.
    asyncio.run(_run_briefly())


# ── full happy path: gate→compose→emit ────────────────────────────────────


def test_full_tick_emits_when_all_gates_pass(absent_daemon, monkeypatch, tmp_path) -> None:
    """End-to-end: enabled + absent operator + chronicle event + LLM ok → emit."""
    monkeypatch.setenv("HAPAX_AUTONOMOUS_NARRATIVE_ENABLED", "1")
    monkeypatch.setenv("HAPAX_AUTONOMOUS_NARRATIVE_INTERVAL_S", "0.001")  # any tick passes cadence

    chronicle_path = tmp_path / "impingements.jsonl"
    _populate_chronicle(chronicle_path)

    monkeypatch.setattr(state_readers, "_CHRONICLE_PATH", chronicle_path)
    monkeypatch.setattr(state_readers, "_STIMMUNG_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(state_readers, "_RESEARCH_MARKER_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(state_readers, "_DIRECTOR_INTENT_PATH", tmp_path / "missing.jsonl")
    monkeypatch.setattr(emit, "_IMPINGEMENT_PATH", chronicle_path)

    # Stub LLM to return clean prose
    def fake_llm(*, prompt: str, seed: str) -> str:
        return "Vinyl side change recorded on AUX5."

    with patch(
        "agents.hapax_daimonion.autonomous_narrative.compose._call_llm_balanced",
        side_effect=fake_llm,
    ):

        async def _run_briefly():
            async def _stop_after():
                await asyncio.sleep(0.5)  # at least one tick
                absent_daemon._running = False

            await asyncio.gather(loop.autonomous_narrative_loop(absent_daemon), _stop_after())

        asyncio.run(_run_briefly())

    contents = chronicle_path.read_text(encoding="utf-8")
    # Original chronicle event + 1 impingement + 1 chronicle echo
    assert "Vinyl side change recorded on AUX5" in contents
    assert "autonomous_narrative" in contents
    assert "self_authored_narrative" in contents


# ── operator-present blocks the emit ──────────────────────────────────────


def test_loop_does_not_emit_when_operator_present(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HAPAX_AUTONOMOUS_NARRATIVE_ENABLED", "1")
    monkeypatch.setenv("HAPAX_AUTONOMOUS_NARRATIVE_INTERVAL_S", "0.001")

    chronicle_path = tmp_path / "impingements.jsonl"
    _populate_chronicle(chronicle_path)

    monkeypatch.setattr(state_readers, "_CHRONICLE_PATH", chronicle_path)
    monkeypatch.setattr(state_readers, "_STIMMUNG_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(state_readers, "_RESEARCH_MARKER_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(state_readers, "_DIRECTOR_INTENT_PATH", tmp_path / "missing.jsonl")
    monkeypatch.setattr(emit, "_IMPINGEMENT_PATH", chronicle_path)

    daemon = MagicMock()
    daemon._running = True
    daemon.perception.latest.presence_score = 0.95  # operator HERE
    daemon.session.is_active = False
    daemon._processing_utterance = False
    daemon.programme_manager.store.active_programme.return_value = None

    with patch(
        "agents.hapax_daimonion.autonomous_narrative.compose._call_llm_balanced",
        side_effect=lambda **_: "should not appear",
    ):

        async def _run_briefly():
            async def _stop_after():
                await asyncio.sleep(0.3)
                daemon._running = False

            await asyncio.gather(loop.autonomous_narrative_loop(daemon), _stop_after())

        asyncio.run(_run_briefly())

    contents = chronicle_path.read_text(encoding="utf-8")
    # Only the original event; no autonomous_narrative source written.
    assert "autonomous_narrative" not in contents
    assert "should not appear" not in contents


# ── exception in tick body does not kill the loop ─────────────────────────


def test_tick_exception_does_not_propagate(monkeypatch, absent_daemon, tmp_path) -> None:
    monkeypatch.setenv("HAPAX_AUTONOMOUS_NARRATIVE_ENABLED", "1")
    monkeypatch.setenv("HAPAX_AUTONOMOUS_NARRATIVE_INTERVAL_S", "0.001")

    monkeypatch.setattr(state_readers, "_CHRONICLE_PATH", tmp_path / "missing.jsonl")
    monkeypatch.setattr(state_readers, "_STIMMUNG_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(state_readers, "_RESEARCH_MARKER_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(state_readers, "_DIRECTOR_INTENT_PATH", tmp_path / "missing.jsonl")

    # Force the assemble_context to raise so the tick body errors
    def boom(*_a, **_kw):
        raise RuntimeError("synthetic")

    with patch.object(state_readers, "assemble_context", side_effect=boom):

        async def _run_briefly():
            async def _stop_after():
                await asyncio.sleep(0.2)
                absent_daemon._running = False

            # Must complete without raising
            await asyncio.gather(loop.autonomous_narrative_loop(absent_daemon), _stop_after())

        asyncio.run(_run_briefly())  # if exception escaped, this would raise


def test_referent_picker_soft_import_returns_none_when_no_programme(absent_daemon) -> None:
    from dataclasses import dataclass

    @dataclass
    class _Ctx:
        programme = None

    assert loop._pick_referent_for_programme(_Ctx()) is None
