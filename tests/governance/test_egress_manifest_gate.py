from __future__ import annotations

import json
from pathlib import Path

from shared.content_source_provenance_egress import (
    BroadcastManifestAsset,
    EgressManifestGate,
    build_broadcast_manifest,
)
from shared.impingement_consumer import ImpingementConsumer


def _gate(
    tmp_path: Path,
    notify_calls: list[tuple],
    *,
    producer_id: str = "egress_manifest_gate",
) -> EgressManifestGate:
    return EgressManifestGate(
        manifest_path=tmp_path / "manifest.json",
        kill_switch_path=tmp_path / "kill-switch.json",
        impingement_path=tmp_path / "impingements.jsonl",
        producer_id=producer_id,
        notify_fn=lambda *args, **kwargs: notify_calls.append((args, kwargs)),
        now_fn=lambda: 1234.5,
    )


def _asset(
    *,
    token: str | None = "music:hapax-pool:abc",
    tier: str = "tier_0_owned",
    medium: str = "audio",
    source: str = "music-bed",
    broadcast_safe: bool = True,
) -> BroadcastManifestAsset:
    return BroadcastManifestAsset(
        token=token,
        tier=tier,  # type: ignore[arg-type]
        source=source,
        medium=medium,  # type: ignore[arg-type]
        broadcast_safe=broadcast_safe,
    )


def test_missing_token_manifest_triggers_kill_switch_impingement_and_notification(
    tmp_path: Path,
) -> None:
    notify_calls: list[tuple] = []
    gate = _gate(tmp_path, notify_calls)
    manifest = build_broadcast_manifest(
        audio_assets=(_asset(token=None),),
        tick_id="tick-missing",
        ts=100.0,
    )

    decision = gate.evaluate(manifest)
    gate.apply(decision)

    assert decision.kill_switch_fired is True
    assert decision.audio_action == "duck_to_negative_infinity"
    assert decision.visual_action == "crossfade_to_tier0_fallback_shader"
    assert decision.offenders[0].reason == "missing_token"

    state = json.loads((tmp_path / "kill-switch.json").read_text(encoding="utf-8"))
    assert state["active"] is True
    assert state["offenders"][0]["source"] == "music-bed"

    impingements = ImpingementConsumer(tmp_path / "impingements.jsonl").read_new()
    assert len(impingements) == 1
    assert impingements[0].interrupt_token == "egress.kill_switch_fired"
    assert impingements[0].content["metric"] == "egress.kill_switch_fired"
    assert notify_calls
    assert "token=<missing>" in notify_calls[0][0][1]


def test_over_tier_manifest_triggers_safe_failure(tmp_path: Path) -> None:
    notify_calls: list[tuple] = []
    gate = _gate(tmp_path, notify_calls)
    manifest = build_broadcast_manifest(
        visual_assets=(
            _asset(
                token="visual:uncleared:abc",
                tier="tier_4_risky",
                medium="visual",
                source="visual-pool-slot-0",
            ),
        ),
        max_content_risk="tier_1_platform_cleared",
    )

    decision = gate.tick(manifest)

    assert decision is not None
    assert decision.kill_switch_fired is True
    assert decision.offenders[0].reason == "over_tier"
    assert decision.offenders[0].token == "visual:uncleared:abc"
    assert "tier=tier_4_risky" in notify_calls[0][0][1]


def test_clean_manifest_passes_and_clears_kill_switch_state(tmp_path: Path) -> None:
    notify_calls: list[tuple] = []
    gate = _gate(tmp_path, notify_calls)
    manifest = build_broadcast_manifest(
        audio_assets=(_asset(token="music:hapax-pool:abc", tier="tier_1_platform_cleared"),),
        visual_assets=(
            _asset(
                token="visual:hapax-pool:def",
                tier="tier_0_owned",
                medium="visual",
                source="visual-pool-slot-0",
            ),
        ),
    )

    decision = gate.tick(manifest)

    assert decision is not None
    assert decision.kill_switch_fired is False
    assert decision.offenders == ()
    assert notify_calls == []
    state = json.loads((tmp_path / "kill-switch.json").read_text(encoding="utf-8"))
    assert state["active"] is False
    assert not (tmp_path / "impingements.jsonl").exists()


def test_clean_partial_manifest_does_not_clear_other_producer_kill_switch(
    tmp_path: Path,
) -> None:
    notify_calls: list[tuple] = []
    visual_gate = _gate(tmp_path, notify_calls, producer_id="visual_pool")
    audio_gate = _gate(tmp_path, notify_calls, producer_id="local_music_player")

    visual_gate.tick(
        build_broadcast_manifest(
            visual_assets=(
                _asset(
                    token="visual:uncleared:abc",
                    tier="tier_4_risky",
                    medium="visual",
                    source="visual-pool-slot-0",
                ),
            ),
            max_content_risk="tier_1_platform_cleared",
        )
    )

    decision = audio_gate.tick(
        build_broadcast_manifest(
            audio_assets=(
                _asset(
                    token="music:hapax-pool:clear",
                    tier="tier_0_owned",
                    medium="audio",
                    source="music-bed",
                ),
            ),
            max_content_risk="tier_1_platform_cleared",
        )
    )

    assert decision is not None
    assert decision.kill_switch_fired is False
    state = json.loads((tmp_path / "kill-switch.json").read_text(encoding="utf-8"))
    assert state["active"] is True
    assert state["audio_action"] == "duck_to_negative_infinity"
    assert state["visual_action"] == "crossfade_to_tier0_fallback_shader"
    assert state["offenders"][0]["source"] == "visual-pool-slot-0"
    assert state["producer_states"]["visual_pool"]["active"] is True
    assert state["producer_states"]["local_music_player"]["active"] is False
    assert len(notify_calls) == 1


def test_manifest_authority_ceiling_never_grants_public_money_truth_or_rights() -> None:
    manifest = build_broadcast_manifest(
        audio_assets=(_asset(),),
        visual_assets=(
            _asset(
                token="visual:source:abc",
                medium="visual",
                source="compositor:sierpinski",
            ),
        ),
    )

    ceiling = manifest.authority_ceiling
    assert ceiling.grants_public_status is False
    assert ceiling.grants_monetization_status is False
    assert ceiling.grants_truth_status is False
    assert ceiling.grants_rights_status is False
    assert ceiling.grants_safety_status is False
