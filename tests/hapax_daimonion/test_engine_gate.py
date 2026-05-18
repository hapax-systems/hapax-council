"""Tests for engine_gate — Mode D × voice-tier mutex wrappers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agents.hapax_daimonion.engine_gate import (
    activate_from_impingement_gated,
    activate_mode_d_gated,
    apply_tier_gated,
    deactivate_mode_d_gated,
    voice_tier_to_engine_mode,
)
from shared.evil_pet_state import (
    EvilPetMode,
    EvilPetState,
    read_state,
    write_state,
)
from shared.voice_tier import VoiceTier


@pytest.fixture
def tmp_paths(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "evil-pet-state.json", tmp_path / "mode-d-active"


class TestVoiceTierToEngineMode:
    def test_covers_all_seven(self) -> None:
        for t in VoiceTier:
            mode = voice_tier_to_engine_mode(t)
            assert mode == EvilPetMode(f"voice_tier_{int(t)}")

    def test_accepts_integer(self) -> None:
        assert voice_tier_to_engine_mode(3) == EvilPetMode.VOICE_TIER_3

    def test_rejects_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            voice_tier_to_engine_mode(7)
        with pytest.raises(ValueError):
            voice_tier_to_engine_mode(-1)


class TestApplyTierGated:
    def test_accepts_on_free_engine(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, legacy = tmp_paths
        chain = MagicMock()
        result = apply_tier_gated(
            chain,
            VoiceTier.BROADCAST_GHOST,
            state_path=state_path,
            legacy_flag=legacy,
            now=1000.0,
        )
        assert result.accepted is True
        # Chain.apply_tier was called with the tier + impingement kwarg.
        chain.apply_tier.assert_called_once()
        args, kwargs = chain.apply_tier.call_args
        assert args[0] == VoiceTier.BROADCAST_GHOST

    def test_blocks_when_operator_owns_mode_d(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, legacy = tmp_paths
        # Seed: operator claimed mode_d.
        write_state(
            EvilPetState(
                mode=EvilPetMode.MODE_D,
                active_since=1000.0,
                writer="operator",
                heartbeat=1000.0,
            ),
            path=state_path,
            legacy_flag=legacy,
        )
        chain = MagicMock()
        # Director attempts voice tier — blocked.
        result = apply_tier_gated(
            chain,
            VoiceTier.GRANULAR_WASH,
            writer="director",
            state_path=state_path,
            legacy_flag=legacy,
            now=1001.0,
        )
        assert result.accepted is False
        assert "blocked_by_operator" in result.reason
        chain.apply_tier.assert_not_called()
        # State preserved.
        assert read_state(state_path, now=1001.0).mode == EvilPetMode.MODE_D

    def test_blocks_when_programme_owns_mode_d_under_director(
        self, tmp_paths: tuple[Path, Path]
    ) -> None:
        state_path, legacy = tmp_paths
        write_state(
            EvilPetState(
                mode=EvilPetMode.MODE_D,
                active_since=1000.0,
                writer="programme",
                heartbeat=1000.0,
                programme_opt_in=True,
            ),
            path=state_path,
            legacy_flag=legacy,
        )
        chain = MagicMock()
        result = apply_tier_gated(
            chain,
            VoiceTier.GRANULAR_WASH,
            writer="director",
            state_path=state_path,
            legacy_flag=legacy,
            now=1001.0,
        )
        assert result.accepted is False
        assert "blocked_by_programme" in result.reason
        chain.apply_tier.assert_not_called()

    def test_operator_override_preempts_director_tier(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, legacy = tmp_paths
        # Director claimed tier 2.
        apply_tier_gated(
            MagicMock(),
            VoiceTier.BROADCAST_GHOST,
            writer="director",
            state_path=state_path,
            legacy_flag=legacy,
            now=1000.0,
        )
        # Operator overrides to tier 5.
        chain = MagicMock()
        result = apply_tier_gated(
            chain,
            VoiceTier.GRANULAR_WASH,
            writer="operator",
            state_path=state_path,
            legacy_flag=legacy,
            now=1001.0,
        )
        assert result.accepted is True
        assert result.reason == "higher_priority_preempts"
        chain.apply_tier.assert_called_once()
        assert read_state(state_path, now=1001.0).mode == EvilPetMode.VOICE_TIER_5


class TestActivateModeDGated:
    def test_accepts_on_free_engine(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, legacy = tmp_paths
        chain = MagicMock()
        result = activate_mode_d_gated(chain, state_path=state_path, legacy_flag=legacy, now=1000.0)
        assert result.accepted is True
        chain.activate_mode_d.assert_called_once()
        assert legacy.exists()

    def test_programme_writer_tag(self, tmp_paths: tuple[Path, Path]) -> None:
        """Programme-recruited Mode D writes writer=programme for governance revert."""
        state_path, legacy = tmp_paths
        chain = MagicMock()
        result = activate_mode_d_gated(
            chain,
            writer="programme",
            programme_opt_in=True,
            state_path=state_path,
            legacy_flag=legacy,
            now=1000.0,
        )
        assert result.accepted is True
        loaded = read_state(state_path, now=1000.0)
        assert loaded.writer == "programme"
        assert loaded.programme_opt_in is True

    def test_governance_revert_overrides_programme(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, legacy = tmp_paths
        vinyl = MagicMock()
        # Programme claims Mode D.
        activate_mode_d_gated(
            vinyl,
            writer="programme",
            programme_opt_in=True,
            state_path=state_path,
            legacy_flag=legacy,
            now=1000.0,
        )
        # Governance reverts.
        result = deactivate_mode_d_gated(
            vinyl,
            writer="governance",
            state_path=state_path,
            legacy_flag=legacy,
            now=1001.0,
        )
        assert result.accepted is True
        assert result.reason == "higher_priority_preempts"
        vinyl.deactivate_mode_d.assert_called_once()
        assert legacy.exists() is False


class TestBlockedCalleesUntouched:
    """Blocked invocations must NOT mutate the chain."""

    def test_apply_tier_blocked_chain_unchanged(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, legacy = tmp_paths
        write_state(
            EvilPetState(
                mode=EvilPetMode.MODE_D,
                active_since=1000.0,
                writer="operator",
                heartbeat=1000.0,
            ),
            path=state_path,
            legacy_flag=legacy,
        )
        chain = MagicMock()
        apply_tier_gated(
            chain,
            VoiceTier.OBLITERATED,
            writer="director",
            state_path=state_path,
            legacy_flag=legacy,
            now=1001.0,
        )
        # apply_tier MUST NOT be called.
        chain.apply_tier.assert_not_called()
        # deactivate / activate_dimension / anything else — also untouched.
        chain.deactivate.assert_not_called()
        chain.activate_dimension.assert_not_called()

    def test_activate_mode_d_blocked_chain_unchanged(self, tmp_paths: tuple[Path, Path]) -> None:
        """Programme trying Mode D while operator owns it → no-op on vinyl chain."""
        state_path, legacy = tmp_paths
        write_state(
            EvilPetState(
                mode=EvilPetMode.VOICE_TIER_4,
                active_since=1000.0,
                writer="operator",
                heartbeat=1000.0,
            ),
            path=state_path,
            legacy_flag=legacy,
        )
        vinyl = MagicMock()
        result = activate_mode_d_gated(
            vinyl,
            writer="programme",
            state_path=state_path,
            legacy_flag=legacy,
            now=1001.0,
        )
        assert result.accepted is False
        vinyl.activate_mode_d.assert_not_called()


class TestActivateFromImpingementGated:
    """Tests for pipeline-recruited vocal chain dimension activation."""

    def _make_impingement(self) -> MagicMock:
        imp = MagicMock()
        imp.source = "stimmung.evaluative"
        imp.content = {"dimensions": {"intensity": 0.7}}
        imp.strength = 0.6
        return imp

    def test_accepts_on_free_engine(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, _legacy = tmp_paths
        chain = MagicMock()
        imp = self._make_impingement()
        result = activate_from_impingement_gated(
            chain, imp, pipeline_score=0.55, state_path=state_path, now=1000.0
        )
        assert result.accepted is True
        chain.activate_from_impingement.assert_called_once_with(imp)

    def test_blocked_by_mode_d(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, legacy = tmp_paths
        write_state(
            EvilPetState(
                mode=EvilPetMode.MODE_D,
                active_since=1000.0,
                writer="operator",
                heartbeat=1000.0,
            ),
            path=state_path,
            legacy_flag=legacy,
        )
        chain = MagicMock()
        imp = self._make_impingement()
        result = activate_from_impingement_gated(
            chain, imp, pipeline_score=0.8, state_path=state_path, now=1001.0
        )
        assert result.accepted is False
        assert "mode_d" in result.reason
        chain.activate_from_impingement.assert_not_called()

    def test_refreshes_existing_voice_tier(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, legacy = tmp_paths
        write_state(
            EvilPetState(
                mode=EvilPetMode.VOICE_TIER_3,
                active_since=999.0,
                writer="director",
                heartbeat=999.5,
            ),
            path=state_path,
            legacy_flag=legacy,
        )
        chain = MagicMock()
        imp = self._make_impingement()
        result = activate_from_impingement_gated(
            chain, imp, pipeline_score=0.4, state_path=state_path, now=1000.0
        )
        assert result.accepted is True
        assert result.reason == "heartbeat_refresh"
        chain.activate_from_impingement.assert_called_once()
        loaded = read_state(state_path, now=1000.0)
        assert loaded.mode == EvilPetMode.VOICE_TIER_3

    def test_stale_mode_d_allows_activation(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, legacy = tmp_paths
        write_state(
            EvilPetState(
                mode=EvilPetMode.MODE_D,
                active_since=900.0,
                writer="operator",
                heartbeat=900.0,
            ),
            path=state_path,
            legacy_flag=legacy,
        )
        chain = MagicMock()
        imp = self._make_impingement()
        result = activate_from_impingement_gated(
            chain, imp, pipeline_score=0.5, state_path=state_path, now=1000.0
        )
        assert result.accepted is True
        chain.activate_from_impingement.assert_called_once()
