"""Tests for typed impingement payloads + engine_session context manager."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.evil_pet_state import (
    EngineContention,
    EvilPetMode,
    EvilPetState,
    engine_session,
    write_state,
)
from shared.impingement import Impingement, ImpingementType
from shared.typed_impingements import (
    ENGINE_ACQUIRE_IMPINGEMENT_SOURCE,
    VOICE_TIER_IMPINGEMENT_SOURCE,
    EngineAcquireImpingement,
    VoiceTierImpingement,
)
from shared.voice_tier import VoiceTier


@pytest.fixture
def tmp_paths(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "evil-pet-state.json", tmp_path / "mode-d-active"


class TestVoiceTierImpingement:
    def test_roundtrip_through_impingement(self) -> None:
        payload = VoiceTierImpingement(
            tier=VoiceTier.MEMORY,
            programme_band=(1, 3),
            voice_path="evil_pet",
            monetization_risk="none",
            since=1000.0,
        )
        imp = payload.to_impingement(strength=0.8)
        assert imp.source == VOICE_TIER_IMPINGEMENT_SOURCE
        assert imp.intent_family == "voice.register_shift"
        assert imp.strength == 0.8
        parsed = VoiceTierImpingement.try_from(imp)
        assert parsed is not None
        assert parsed.tier == VoiceTier.MEMORY
        assert parsed.programme_band == (1, 3)
        assert parsed.voice_path == "evil_pet"
        assert parsed.monetization_risk == "none"

    def test_try_from_wrong_source_returns_none(self) -> None:
        imp = Impingement(
            timestamp=1000.0,
            source="something.else",
            type=ImpingementType.STATISTICAL_DEVIATION,
            strength=1.0,
            content={
                "tier": 3,
                "programme_band": [1, 3],
                "voice_path": "evil_pet",
                "monetization_risk": "none",
            },
        )
        assert VoiceTierImpingement.try_from(imp) is None

    def test_try_from_malformed_content_returns_none(self) -> None:
        imp = Impingement(
            timestamp=1000.0,
            source=VOICE_TIER_IMPINGEMENT_SOURCE,
            type=ImpingementType.SALIENCE_INTEGRATION,
            strength=1.0,
            content={"garbage": True},
        )
        assert VoiceTierImpingement.try_from(imp) is None

    def test_excursion_flag_survives_roundtrip(self) -> None:
        payload = VoiceTierImpingement(
            tier=VoiceTier.OBLITERATED,
            programme_band=(0, 0),
            voice_path="evil_pet",
            monetization_risk="high",
            excursion=True,
            clamped_from=VoiceTier.GRANULAR_WASH,
        )
        reparsed = VoiceTierImpingement.try_from(payload.to_impingement())
        assert reparsed is not None
        assert reparsed.excursion is True
        assert reparsed.clamped_from == VoiceTier.GRANULAR_WASH


class TestEngineAcquireImpingement:
    def test_accept_roundtrip(self) -> None:
        payload = EngineAcquireImpingement(
            consumer="director",
            target_mode=EvilPetMode.VOICE_TIER_5,
            accepted=True,
            reason="same_class_override",
            since=1000.0,
        )
        imp = payload.to_impingement()
        assert imp.source == ENGINE_ACQUIRE_IMPINGEMENT_SOURCE
        parsed = EngineAcquireImpingement.try_from(imp)
        assert parsed is not None
        assert parsed.consumer == "director"
        assert parsed.target_mode == EvilPetMode.VOICE_TIER_5
        assert parsed.accepted is True

    def test_reject_carries_reason(self) -> None:
        payload = EngineAcquireImpingement(
            consumer="director",
            target_mode=EvilPetMode.MODE_D,
            accepted=False,
            reason="blocked_by_operator",
        )
        parsed = EngineAcquireImpingement.try_from(payload.to_impingement())
        assert parsed is not None
        assert parsed.accepted is False
        assert "operator" in parsed.reason


class TestEngineSession:
    def test_acquire_and_release(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, legacy = tmp_paths
        with engine_session(
            EvilPetMode.VOICE_TIER_3,
            consumer="director",
            path=state_path,
            legacy_flag=legacy,
        ) as result:
            assert result.accepted is True
            assert result.state.writer == "director"
        # On exit, state released to bypass.
        from shared.evil_pet_state import read_state

        final = read_state(path=state_path, now=result.state.heartbeat + 1.0)
        assert final.mode == EvilPetMode.BYPASS

    def test_contention_raises(self, tmp_paths: tuple[Path, Path]) -> None:
        state_path, legacy = tmp_paths
        # Seed: operator holds mode_d.
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
        with pytest.raises(EngineContention) as excinfo:
            with engine_session(
                EvilPetMode.VOICE_TIER_5,
                consumer="director",
                path=state_path,
                legacy_flag=legacy,
                now=1001.0,
            ):
                pytest.fail("body should not run on contention")
        assert "operator" in excinfo.value.reason
        assert excinfo.value.current_writer == "operator"

    def test_release_on_exception(self, tmp_paths: tuple[Path, Path]) -> None:
        """Body exceptions still release the engine."""
        state_path, legacy = tmp_paths
        with pytest.raises(ValueError):
            with engine_session(
                EvilPetMode.VOICE_TIER_3,
                consumer="director",
                path=state_path,
                legacy_flag=legacy,
            ):
                raise ValueError("body error")
        from shared.evil_pet_state import read_state

        # Heartbeat is recent enough; state should be bypass.
        final = read_state(path=state_path)
        assert final.mode == EvilPetMode.BYPASS

    def test_release_on_exit_false_preserves_ownership(self, tmp_paths: tuple[Path, Path]) -> None:
        """release_on_exit=False supports nested sessions holding the engine."""
        state_path, legacy = tmp_paths
        with engine_session(
            EvilPetMode.VOICE_TIER_3,
            consumer="director",
            path=state_path,
            legacy_flag=legacy,
            release_on_exit=False,
        ):
            pass
        from shared.evil_pet_state import read_state

        final = read_state(path=state_path)
        # Engine still held (no bypass-write on exit).
        assert final.mode == EvilPetMode.VOICE_TIER_3


class TestMetricsRegistered:
    """Smoke check: counters are registered when prometheus_client available."""

    def test_module_imports_cleanly(self) -> None:
        from shared.evil_pet_state import _metrics

        assert _metrics is not None


class TestVocalChainEmit:
    def test_emit_returns_typed_impingement(self) -> None:
        from unittest.mock import MagicMock

        from agents.hapax_daimonion.vocal_chain import VocalChainCapability

        chain = VocalChainCapability(midi_output=MagicMock())
        imp = chain.emit_voice_tier_impingement(VoiceTier.MEMORY)
        parsed = VoiceTierImpingement.try_from(imp)
        assert parsed is not None
        assert parsed.tier == VoiceTier.MEMORY
        # Default public voice path fails closed until FX witness passes.
        assert parsed.voice_path == "held"
        assert parsed.monetization_risk == "none"

    def test_emit_with_excursion_flag(self) -> None:
        from unittest.mock import MagicMock

        from agents.hapax_daimonion.vocal_chain import VocalChainCapability

        chain = VocalChainCapability(midi_output=MagicMock())
        imp = chain.emit_voice_tier_impingement(
            VoiceTier.OBLITERATED,
            programme_band=(0, 0),
            excursion=True,
            clamped_from=VoiceTier.GRANULAR_WASH,
        )
        parsed = VoiceTierImpingement.try_from(imp)
        assert parsed is not None
        assert parsed.excursion is True
        assert parsed.clamped_from == VoiceTier.GRANULAR_WASH
        assert parsed.monetization_risk == "high"  # T6
