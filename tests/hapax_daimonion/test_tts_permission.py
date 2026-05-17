"""Tests for the dynamic-audio TTS permission scalar."""

from __future__ import annotations

import json
from pathlib import Path

from agents.hapax_daimonion.cpal.tts_permission import (
    MIN_BROADCAST_TTS_PERMISSION,
    resolve_broadcast_tts_permission,
)
from shared.broadcast_audio_health import BroadcastAudioHealth, BroadcastAudioStatus


def _health(*, safe: bool = True) -> BroadcastAudioHealth:
    return BroadcastAudioHealth(
        safe=safe,
        status=BroadcastAudioStatus.SAFE if safe else BroadcastAudioStatus.UNSAFE,
        checked_at="2026-05-17T00:00:00Z",
        freshness_s=0.0,
        evidence={"fixture": True},
    )


def _auth() -> dict[str, object]:
    return {
        "authorized": True,
        "reason_code": "programme_authorization_fresh",
        "programme_id": "prog-a",
    }


def _write_stimmung(
    path: Path,
    *,
    stance: str = "nominal",
    audio_content_mix: float = 0.1,
    freshness_s: float = 0.0,
) -> None:
    path.write_text(
        json.dumps(
            {
                "overall_stance": stance,
                "audio_content_mix": {
                    "value": audio_content_mix,
                    "freshness_s": freshness_s,
                },
            }
        ),
        encoding="utf-8",
    )


def test_low_audio_pressure_keeps_public_tts_permission_high(tmp_path: Path) -> None:
    stimmung = tmp_path / "stimmung.json"
    _write_stimmung(stimmung, stance="nominal", audio_content_mix=0.1)

    decision = resolve_broadcast_tts_permission(
        content={"programme_role": "work_block"},
        programme_auth=_auth(),
        audio_health=_health(),
        stimmung_state_path=stimmung,
        eligible_roles={"work_block", "ambient"},
    )

    assert decision.allowed is True
    assert decision.scalar == 0.9
    assert decision.components == {"programme": 1.0, "audio": 1.0, "stimmung": 0.9}


def test_performance_heavy_audio_content_mix_blocks_public_tts(tmp_path: Path) -> None:
    stimmung = tmp_path / "stimmung.json"
    _write_stimmung(stimmung, stance="nominal", audio_content_mix=0.9)

    decision = resolve_broadcast_tts_permission(
        content={"programme_role": "work_block"},
        programme_auth=_auth(),
        audio_health=_health(),
        stimmung_state_path=stimmung,
        eligible_roles={"work_block", "ambient"},
    )

    assert decision.allowed is False
    assert decision.scalar < MIN_BROADCAST_TTS_PERMISSION
    assert decision.reason_code == "tts_permission_below_threshold"
    assert "tts_permission_below_threshold" in decision.blockers


def test_critical_stimmung_blocks_even_when_audio_mix_is_clear(tmp_path: Path) -> None:
    stimmung = tmp_path / "stimmung.json"
    _write_stimmung(stimmung, stance="critical", audio_content_mix=0.0)

    decision = resolve_broadcast_tts_permission(
        content={"programme_role": "work_block"},
        programme_auth=_auth(),
        audio_health=_health(),
        stimmung_state_path=stimmung,
        eligible_roles={"work_block", "ambient"},
    )

    assert decision.allowed is False
    assert decision.components["stimmung"] == 0.2
    assert decision.reason_code == "tts_permission_below_threshold"


def test_audio_unsafe_sets_permission_scalar_to_zero(tmp_path: Path) -> None:
    stimmung = tmp_path / "stimmung.json"
    _write_stimmung(stimmung)

    decision = resolve_broadcast_tts_permission(
        content={"programme_role": "work_block"},
        programme_auth=_auth(),
        audio_health=_health(safe=False),
        stimmung_state_path=stimmung,
        eligible_roles={"work_block", "ambient"},
    )

    assert decision.allowed is False
    assert decision.scalar == 0.0
    assert "audio_safe_for_broadcast_false" in decision.blockers


def test_ineligible_programme_role_sets_permission_scalar_to_zero(tmp_path: Path) -> None:
    stimmung = tmp_path / "stimmung.json"
    _write_stimmung(stimmung)

    decision = resolve_broadcast_tts_permission(
        content={"programme_role": "ProgrammeRole.LISTENING"},
        programme_auth=_auth(),
        audio_health=_health(),
        stimmung_state_path=stimmung,
        eligible_roles={"work_block", "ambient"},
    )

    assert decision.allowed is False
    assert decision.scalar == 0.0
    assert "programme_role_not_tts_eligible" in decision.blockers


def test_missing_stimmung_damps_permission_instead_of_minting_full_score(
    tmp_path: Path,
) -> None:
    decision = resolve_broadcast_tts_permission(
        content={"programme_role": "work_block"},
        programme_auth=_auth(),
        audio_health=_health(),
        stimmung_state_path=tmp_path / "missing.json",
        eligible_roles={"work_block", "ambient"},
    )

    assert decision.allowed is True
    assert decision.scalar == 0.5
    assert "stimmung_state_missing" in decision.blockers
    assert decision.evidence["stimmung"]["factor"] == 0.5
