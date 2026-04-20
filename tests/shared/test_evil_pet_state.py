"""Tests for shared.evil_pet_state — single-owner arbitration for Evil Pet granular engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.evil_pet_state import (
    DEBOUNCE_WINDOW_S,
    HEARTBEAT_STALE_S,
    ArbitrationResult,
    EvilPetMode,
    EvilPetState,
    acquire_engine,
    arbitrate,
    read_state,
    write_state,
)


@pytest.fixture
def tmp_paths(tmp_path: Path) -> tuple[Path, Path]:
    state = tmp_path / "evil-pet-state.json"
    legacy = tmp_path / "mode-d-active"
    return state, legacy


class TestEvilPetMode:
    def test_nine_modes(self) -> None:
        assert len(list(EvilPetMode)) == 9

    def test_voice_tier_modes_cover_zero_through_six(self) -> None:
        tier_modes = [m for m in EvilPetMode if m.value.startswith("voice_tier_")]
        tiers = sorted(int(m.value.split("_")[-1]) for m in tier_modes)
        assert tiers == [0, 1, 2, 3, 4, 5, 6]


class TestEvilPetStateShape:
    def test_bypass_factory_is_fresh(self) -> None:
        s = EvilPetState.bypass(now=1000.0)
        assert s.mode == EvilPetMode.BYPASS
        assert s.active_since == 1000.0
        assert s.heartbeat == 1000.0
        assert s.is_stale(now=1001.0) is False

    def test_is_stale_after_window(self) -> None:
        s = EvilPetState.bypass(now=0.0)
        assert s.is_stale(now=HEARTBEAT_STALE_S - 0.1) is False
        assert s.is_stale(now=HEARTBEAT_STALE_S + 0.1) is True


class TestArbitrateStaleBypass:
    def test_stale_current_releases_engine(self) -> None:
        old = EvilPetState(
            mode=EvilPetMode.MODE_D,
            active_since=0.0,
            writer="operator",
            heartbeat=0.0,
        )
        result = arbitrate(
            target_mode=EvilPetMode.VOICE_TIER_5,
            writer="director",
            current=old,
            now=HEARTBEAT_STALE_S + 1.0,
        )
        assert result.accepted is True
        assert result.reason == "stale_heartbeat_released"
        assert result.state.mode == EvilPetMode.VOICE_TIER_5
        assert result.state.tier == 5


class TestArbitratePriorityRules:
    def _current(self, mode: EvilPetMode, writer: str, now: float = 1000.0) -> EvilPetState:
        return EvilPetState(
            mode=mode,
            active_since=now - 10.0,
            writer=writer,
            heartbeat=now,  # fresh
        )

    def test_operator_preempts_director(self) -> None:
        current = self._current(EvilPetMode.VOICE_TIER_5, writer="director")
        result = arbitrate(
            target_mode=EvilPetMode.MODE_D,
            writer="operator",
            current=current,
            now=1001.0,
        )
        assert result.accepted is True
        assert result.reason == "higher_priority_preempts"

    def test_programme_preempts_director(self) -> None:
        current = self._current(EvilPetMode.VOICE_TIER_5, writer="director")
        result = arbitrate(
            target_mode=EvilPetMode.MODE_D,
            writer="programme",
            current=current,
            now=1001.0,
        )
        assert result.accepted is True
        assert result.reason == "higher_priority_preempts"

    def test_director_blocked_by_programme(self) -> None:
        current = self._current(EvilPetMode.MODE_D, writer="programme")
        result = arbitrate(
            target_mode=EvilPetMode.VOICE_TIER_6,
            writer="director",
            current=current,
            now=1001.0,
        )
        assert result.accepted is False
        assert result.reason == "blocked_by_programme"
        assert result.state is current  # unchanged

    def test_director_blocked_by_operator(self) -> None:
        current = self._current(EvilPetMode.MODE_D, writer="operator")
        result = arbitrate(
            target_mode=EvilPetMode.VOICE_TIER_5,
            writer="director",
            current=current,
            now=1001.0,
        )
        assert result.accepted is False
        assert result.reason == "blocked_by_operator"

    def test_governance_shares_operator_priority(self) -> None:
        """Governance revert must not be blocked by operator — same priority."""
        current = self._current(EvilPetMode.MODE_D, writer="operator")
        # Debounce window elapsed (active_since = 10 s ago).
        result = arbitrate(
            target_mode=EvilPetMode.BYPASS,
            writer="governance",
            current=current,
            now=1001.0,
        )
        assert result.accepted is True
        assert result.reason == "same_class_override"

    def test_programme_blocked_by_operator(self) -> None:
        current = self._current(EvilPetMode.BYPASS, writer="operator")
        result = arbitrate(
            target_mode=EvilPetMode.MODE_D,
            writer="programme",
            current=current,
            now=1001.0,
        )
        assert result.accepted is False
        assert result.reason == "blocked_by_operator"


class TestArbitrateDebounce:
    def test_rapid_toggle_rejected(self) -> None:
        current = EvilPetState(
            mode=EvilPetMode.MODE_D,
            active_since=1000.0,
            writer="operator",
            heartbeat=1000.0,
        )
        # Inside debounce window.
        result = arbitrate(
            target_mode=EvilPetMode.BYPASS,
            writer="operator",
            current=current,
            now=1000.0 + DEBOUNCE_WINDOW_S * 0.5,
        )
        assert result.accepted is False
        assert "debounce" in result.reason

    def test_same_class_accepts_after_debounce(self) -> None:
        current = EvilPetState(
            mode=EvilPetMode.MODE_D,
            active_since=1000.0,
            writer="operator",
            heartbeat=1000.5,
        )
        # Outside debounce window.
        result = arbitrate(
            target_mode=EvilPetMode.BYPASS,
            writer="operator",
            current=current,
            now=1000.0 + DEBOUNCE_WINDOW_S + 0.1,
        )
        assert result.accepted is True
        assert result.reason == "same_class_override"

    def test_heartbeat_refresh_ignores_debounce(self) -> None:
        """Same mode = heartbeat refresh; debounce does not apply."""
        current = EvilPetState(
            mode=EvilPetMode.MODE_D,
            active_since=1000.0,
            writer="operator",
            heartbeat=1000.0,
        )
        result = arbitrate(
            target_mode=EvilPetMode.MODE_D,
            writer="operator",
            current=current,
            now=1000.1,  # inside debounce window
        )
        assert result.accepted is True
        assert result.reason == "heartbeat_refresh"
        assert result.state.active_since == 1000.0  # preserved
        assert result.state.heartbeat == 1000.1  # refreshed


class TestReadWriteState:
    def test_roundtrip(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, legacy = tmp_paths
        s = EvilPetState(
            mode=EvilPetMode.VOICE_TIER_3,
            active_since=1000.0,
            writer="director",
            programme_opt_in=False,
            heartbeat=1000.5,
            tier=3,
        )
        write_state(s, path=state_path, legacy_flag=legacy)
        loaded = read_state(path=state_path, now=1001.0)
        assert loaded.mode == EvilPetMode.VOICE_TIER_3
        assert loaded.writer == "director"
        assert loaded.tier == 3
        assert loaded.heartbeat == 1000.5

    def test_missing_file_returns_bypass(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, _ = tmp_paths
        loaded = read_state(path=state_path, now=100.0)
        assert loaded.mode == EvilPetMode.BYPASS

    def test_stale_heartbeat_returns_bypass(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, legacy = tmp_paths
        s = EvilPetState(
            mode=EvilPetMode.MODE_D,
            active_since=0.0,
            writer="operator",
            heartbeat=0.0,
        )
        write_state(s, path=state_path, legacy_flag=legacy)
        loaded = read_state(path=state_path, now=HEARTBEAT_STALE_S + 1.0)
        assert loaded.mode == EvilPetMode.BYPASS

    def test_corrupt_json_returns_bypass(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, _ = tmp_paths
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("{not json")
        loaded = read_state(path=state_path, now=100.0)
        assert loaded.mode == EvilPetMode.BYPASS

    def test_atomic_write_persists_json(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, legacy = tmp_paths
        s = EvilPetState(
            mode=EvilPetMode.MODE_D,
            active_since=1000.0,
            writer="operator",
            heartbeat=1000.0,
        )
        write_state(s, path=state_path, legacy_flag=legacy)
        raw = json.loads(state_path.read_text())
        assert raw["mode"] == "mode_d"
        assert raw["writer"] == "operator"


class TestLegacyFlag:
    def test_mode_d_creates_legacy_flag(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, legacy = tmp_paths
        s = EvilPetState(
            mode=EvilPetMode.MODE_D,
            active_since=100.0,
            writer="operator",
            heartbeat=100.0,
        )
        write_state(s, path=state_path, legacy_flag=legacy)
        assert legacy.exists()

    def test_non_mode_d_removes_legacy_flag(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, legacy = tmp_paths
        # Create a pre-existing legacy flag then transition away.
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.touch()
        s = EvilPetState(
            mode=EvilPetMode.VOICE_TIER_2,
            active_since=100.0,
            writer="director",
            heartbeat=100.0,
        )
        write_state(s, path=state_path, legacy_flag=legacy)
        assert legacy.exists() is False

    def test_non_mode_d_noop_when_legacy_missing(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, legacy = tmp_paths
        s = EvilPetState(
            mode=EvilPetMode.BYPASS,
            active_since=100.0,
            writer="system",
            heartbeat=100.0,
        )
        # Does not raise on missing legacy flag.
        write_state(s, path=state_path, legacy_flag=legacy)


class TestAcquireEngine:
    def test_acquire_writes_on_accept(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, legacy = tmp_paths
        result: ArbitrationResult = acquire_engine(
            target_mode=EvilPetMode.VOICE_TIER_3,
            writer="director",
            path=state_path,
            legacy_flag=legacy,
            now=1000.0,
        )
        assert result.accepted is True
        assert state_path.exists()
        loaded = read_state(path=state_path, now=1000.0)
        assert loaded.mode == EvilPetMode.VOICE_TIER_3

    def test_acquire_no_write_on_reject(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, legacy = tmp_paths
        # First, operator claims mode_d.
        acquire_engine(
            target_mode=EvilPetMode.MODE_D,
            writer="operator",
            path=state_path,
            legacy_flag=legacy,
            now=1000.0,
        )
        # Director tries to claim immediately — rejected.
        result = acquire_engine(
            target_mode=EvilPetMode.VOICE_TIER_5,
            writer="director",
            path=state_path,
            legacy_flag=legacy,
            now=1001.0,
        )
        assert result.accepted is False
        assert "blocked_by_operator" in result.reason
        # File still reflects operator state.
        loaded = read_state(path=state_path, now=1001.0)
        assert loaded.mode == EvilPetMode.MODE_D
        assert loaded.writer == "operator"

    def test_acquire_governance_revert(self, tmp_paths: tuple[Path, Path]) -> None:
        """Programme opt-in revoked → governance forces bypass mid-session."""
        state_path, legacy = tmp_paths
        acquire_engine(
            target_mode=EvilPetMode.MODE_D,
            writer="programme",
            path=state_path,
            legacy_flag=legacy,
            programme_opt_in=True,
            now=1000.0,
        )
        # Programme opt-in goes away; governance reverts.
        result = acquire_engine(
            target_mode=EvilPetMode.BYPASS,
            writer="governance",
            path=state_path,
            legacy_flag=legacy,
            now=1001.0,
        )
        assert result.accepted is True
        # Governance (priority 3) preempted programme (priority 2).
        assert result.reason == "higher_priority_preempts"
        assert legacy.exists() is False  # legacy flag cleared on mode exit
