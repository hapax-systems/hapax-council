"""Unit tests for autonomous_narrative.gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

from agents.hapax_daimonion.autonomous_narrative import gates


@dataclass
class _FakeRole:
    value: str


@dataclass
class _FakeProgramme:
    role: Any = None


@dataclass
class _FakeContext:
    programme: Any = None
    stimmung_tone: str = "ambient"
    director_activity: str = "observe"
    chronicle_events: tuple = field(default_factory=tuple)


def _absent_daemon(*, presence_score: float = 0.0) -> MagicMock:
    """Build a daemon mock that signals operator-absent."""
    daemon = MagicMock()
    daemon.perception.latest.presence_score = presence_score
    daemon.session.is_active = False
    daemon._processing_utterance = False
    return daemon


# ── env helpers ────────────────────────────────────────────────────────────


def test_env_enabled_default_off(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_AUTONOMOUS_NARRATIVE_ENABLED", raising=False)
    assert gates.env_enabled() is False


def test_env_enabled_when_set_to_1(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_AUTONOMOUS_NARRATIVE_ENABLED", "1")
    assert gates.env_enabled() is True


def test_env_interval_default(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_AUTONOMOUS_NARRATIVE_INTERVAL_S", raising=False)
    assert gates.env_interval_s() == gates.DEFAULT_INTERVAL_S


def test_env_interval_overridden(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_AUTONOMOUS_NARRATIVE_INTERVAL_S", "300")
    assert gates.env_interval_s() == 300.0


def test_env_interval_invalid_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_AUTONOMOUS_NARRATIVE_INTERVAL_S", "garbage")
    assert gates.env_interval_s() == gates.DEFAULT_INTERVAL_S


def test_env_interval_negative_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_AUTONOMOUS_NARRATIVE_INTERVAL_S", "-50")
    assert gates.env_interval_s() == gates.DEFAULT_INTERVAL_S


# ── allow path ─────────────────────────────────────────────────────────────


def test_evaluate_allows_when_all_gates_clear() -> None:
    result = gates.evaluate(
        _absent_daemon(),
        _FakeContext(),
        last_emission_ts=0.0,
        now=10_000.0,
        min_gap_s=120.0,
        interval_s=150.0,
    )
    assert result.allow is True
    assert result.reason == "ok"


# ── rate-limit gate ────────────────────────────────────────────────────────


def test_evaluate_blocks_within_rate_limit() -> None:
    result = gates.evaluate(
        _absent_daemon(),
        _FakeContext(),
        last_emission_ts=10_000.0 - 60.0,  # 60 s ago
        now=10_000.0,
        min_gap_s=120.0,
    )
    assert result.allow is False
    assert result.reason == "rate_limit"


# ── operator-presence gate ─────────────────────────────────────────────────


def test_evaluate_blocks_when_operator_present_by_score() -> None:
    daemon = _absent_daemon(presence_score=0.9)
    result = gates.evaluate(daemon, _FakeContext(), last_emission_ts=0.0, now=10_000.0)
    assert result.allow is False
    assert result.reason == "operator_present"


def test_evaluate_blocks_when_session_active() -> None:
    daemon = _absent_daemon()
    daemon.session.is_active = True
    result = gates.evaluate(daemon, _FakeContext(), last_emission_ts=0.0, now=10_000.0)
    assert result.allow is False
    assert result.reason == "operator_present"


def test_evaluate_blocks_when_processing_utterance() -> None:
    daemon = _absent_daemon()
    daemon._processing_utterance = True
    result = gates.evaluate(daemon, _FakeContext(), last_emission_ts=0.0, now=10_000.0)
    assert result.allow is False
    assert result.reason == "operator_present"


# ── programme-role gate ───────────────────────────────────────────────────


def test_evaluate_blocks_on_quiet_programme_role() -> None:
    quiet = _FakeContext(programme=_FakeProgramme(role=_FakeRole(value="ritual")))
    result = gates.evaluate(_absent_daemon(), quiet, last_emission_ts=0.0, now=10_000.0)
    assert result.allow is False
    assert result.reason == "programme_quiet"


def test_evaluate_allows_when_programme_role_active() -> None:
    active = _FakeContext(programme=_FakeProgramme(role=_FakeRole(value="showcase")))
    result = gates.evaluate(
        _absent_daemon(),
        active,
        last_emission_ts=0.0,
        now=10_000.0,
        interval_s=1.0,  # so cadence doesn't block
    )
    assert result.allow is True


# ── stimmung gate ─────────────────────────────────────────────────────────


def test_evaluate_blocks_on_high_pressure_stimmung() -> None:
    ctx = _FakeContext(stimmung_tone="hothouse")
    result = gates.evaluate(_absent_daemon(), ctx, last_emission_ts=0.0, now=10_000.0)
    assert result.allow is False
    assert result.reason == "stimmung_quiet"


def test_evaluate_blocks_on_fortress_mode() -> None:
    ctx = _FakeContext(stimmung_tone="fortress")
    result = gates.evaluate(_absent_daemon(), ctx, last_emission_ts=0.0, now=10_000.0)
    assert result.allow is False
    assert result.reason == "stimmung_quiet"


# ── cadence gate ──────────────────────────────────────────────────────────


def test_evaluate_cadence_blocks_when_too_soon() -> None:
    """Past rate-limit but inside cadence → cadence gate fires."""
    result = gates.evaluate(
        _absent_daemon(),
        _FakeContext(),
        last_emission_ts=10_000.0 - 130.0,  # past 120s rate-limit
        now=10_000.0,
        min_gap_s=120.0,
        interval_s=150.0,
    )
    assert result.allow is False
    assert result.reason == "cadence"
