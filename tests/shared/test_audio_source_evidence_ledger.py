"""Tests for the role-scoped audio source evidence ledger."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import jsonschema

from shared.audio_reactivity import AudioSignals, BusSnapshot, UnifiedReactivityBus
from shared.audio_routing_policy import load_audio_routing_policy
from shared.audio_source_evidence import (
    ActivityBasis,
    AudioActivityMarker,
    AudioReactiveOutcome,
    AudioSourceRole,
    FreshnessState,
    PublicPrivatePosture,
    build_audio_source_ledger,
    read_audio_source_ledger,
)
from shared.broadcast_audio_health import BroadcastAudioHealth, BroadcastAudioStatus

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "audio-source-evidence-ledger.schema.json"

NOW = 1_777_500_000.0

if TYPE_CHECKING:
    import pytest


def _sig(rms: float = 0.0, *, onset: float = 0.0) -> AudioSignals:
    return AudioSignals(
        rms=rms,
        onset=onset,
        centroid=0.2,
        zcr=0.1,
        bpm_estimate=120.0,
        energy_delta=0.0,
        bass_band=rms,
        mid_band=rms / 2.0,
        treble_band=rms / 3.0,
    )


def _snapshot(per_source: dict[str, AudioSignals]) -> BusSnapshot:
    return BusSnapshot(
        blended=AudioSignals.zero(),
        per_source=per_source,
        active_sources=[name for name, sig in per_source.items() if sig.rms > 0.0001],
    )


def _policy():
    return load_audio_routing_policy()


def _health(*, safe: bool, integrated_lufs_i: float | None) -> BroadcastAudioHealth:
    return BroadcastAudioHealth(
        safe=safe,
        status=BroadcastAudioStatus.SAFE if safe else BroadcastAudioStatus.UNKNOWN,
        checked_at="2026-04-29T22:00:00Z",
        freshness_s=0.5,
        evidence={
            "loudness": {
                "integrated_lufs_i": integrated_lufs_i,
                "true_peak_dbtp": -3.0,
                "within_target_band": safe and integrated_lufs_i is not None,
            }
        },
    )


def _validator() -> jsonschema.Draft202012Validator:
    schema = cast("dict[str, Any]", json.loads(SCHEMA.read_text(encoding="utf-8")))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _rows(ledger: Any) -> dict[str, Any]:
    return {row.source_id: row for row in ledger.source_rows}


def test_ledger_exposes_role_scoped_rows_and_legacy_aliases() -> None:
    ledger = build_audio_source_ledger(
        snapshot=_snapshot({"mixer": _sig(0.4), "desk": _sig(0.0)}),
        policy=_policy(),
        broadcast_health=_health(safe=False, integrated_lufs_i=-70.0),
        now=NOW,
    )

    rows = _rows(ledger)
    assert {"music-bed", "youtube-bed", "broadcast-tts", "mixer", "desk"} <= set(rows)
    assert rows["mixer"].role is AudioSourceRole.LEGACY_MIXER
    assert rows["mixer"].active is True
    assert rows["desk"].active is False
    assert ledger.compatibility_aliases["mixer_master"] == "mixer"
    assert ledger.compatibility_aliases["mixer_energy"] == "mixer"
    assert ledger.compatibility_aliases["desk_energy"] == "desk"
    assert rows["mixer"].permissions.public_claim is False


def test_process_activity_marker_cannot_mark_youtube_source_active() -> None:
    marker = AudioActivityMarker(
        source_id="youtube-bed",
        role=AudioSourceRole.YOUTUBE,
        active=True,
        basis=ActivityBasis.PROCESS_ACTIVITY,
        observed_at="2026-04-29T22:00:00Z",
        evidence_refs=("shm:hapax-compositor/yt-audio-state.json",),
    )
    ledger = build_audio_source_ledger(
        snapshot=_snapshot({"mixer": _sig(0.0)}),
        policy=_policy(),
        markers=(marker,),
        now=NOW,
    )

    row = _rows(ledger)["youtube-bed"]
    assert row.active is False
    assert row.activity_basis is ActivityBasis.PROCESS_ACTIVITY
    assert "process_activity_not_signal_evidence" in row.blocking_reasons
    decision = ledger.audio_reactive_decision([AudioSourceRole.YOUTUBE])
    assert decision.outcome is AudioReactiveOutcome.BLOCKED
    assert "process_activity_not_signal_evidence" in decision.blocked_reasons


def test_explicit_marker_row_can_mark_source_active_without_pcm() -> None:
    marker = AudioActivityMarker(
        source_id="music-bed",
        role=AudioSourceRole.MUSIC,
        active=True,
        basis=ActivityBasis.EXPLICIT_MARKER,
        observed_at="2026-04-29T22:00:00Z",
        evidence_refs=("marker:music-level-probe:window-1",),
    )
    ledger = build_audio_source_ledger(
        snapshot=_snapshot({}),
        policy=_policy(),
        markers=(marker,),
        now=NOW,
    )

    row = _rows(ledger)["music-bed"]
    assert row.active is True
    assert row.activity_basis is ActivityBasis.EXPLICIT_MARKER
    assert row.permissions.visual_modulation is True
    assert row.permissions.public_claim is False
    assert ledger.audio_reactive_decision([AudioSourceRole.MUSIC]).outcome is (
        AudioReactiveOutcome.VERIFIED
    )


def test_stale_route_marker_blocks_audio_reactive_decision() -> None:
    marker = AudioActivityMarker(
        source_id="music-bed",
        role=AudioSourceRole.MUSIC,
        active=True,
        basis=ActivityBasis.EXPLICIT_MARKER,
        observed_at="2026-04-29T21:59:50Z",
        ttl_s=2.0,
        evidence_refs=("marker:music-level-probe:old",),
    )
    ledger = build_audio_source_ledger(
        snapshot=_snapshot({}),
        policy=_policy(),
        markers=(marker,),
        now=NOW,
    )

    row = _rows(ledger)["music-bed"]
    assert row.freshness.state is FreshnessState.STALE
    assert row.active is False
    assert row.permissions.visual_modulation is False
    assert (
        ledger.audio_reactive_decision([AudioSourceRole.MUSIC]).outcome
        is AudioReactiveOutcome.STALE
    )


def test_route_existence_and_broadcast_egress_are_distinct() -> None:
    ledger = build_audio_source_ledger(
        snapshot=_snapshot({"tts": _sig(0.5)}),
        policy=_policy(),
        broadcast_health=_health(safe=True, integrated_lufs_i=-14.0),
        now=NOW,
    )
    rows = _rows(ledger)
    tts = rows["broadcast-tts"]
    egress = rows["broadcast-egress"]

    assert tts.active is True
    assert tts.route_posture.route_exists is True
    assert tts.route_posture.egress_verified is False
    assert tts.permissions.public_claim is False
    assert egress.active is True
    assert egress.egress_posture.public_audible is True
    assert egress.permissions.public_claim is True


def test_private_route_posture_blocks_public_permissions() -> None:
    ledger = build_audio_source_ledger(
        snapshot=_snapshot({}),
        policy=_policy(),
        now=NOW,
    )
    row = _rows(ledger)["assistant-private"]

    assert row.public_private_posture is PublicPrivatePosture.PRIVATE_ONLY
    assert row.permissions.public_claim is False
    assert row.permissions.clip_candidate is False
    assert row.route_posture.private_monitor_verified is True


def test_schema_validates_emitted_ledger() -> None:
    ledger = build_audio_source_ledger(
        snapshot=_snapshot({"mixer": _sig(0.3)}),
        policy=_policy(),
        broadcast_health=_health(safe=False, integrated_lufs_i=-70.0),
        now=NOW,
    )

    assert json.loads(SCHEMA.read_text(encoding="utf-8"))["x-fail_closed_policy"] == {
        "process_activity_marks_source_active": False,
        "route_existence_satisfies_egress": False,
        "public_claim_without_public_audible_egress": False,
        "legacy_aliases_bypass_role_scope": False,
    }
    _validator().validate(ledger.model_dump(mode="json"))


def test_bus_publish_writes_ledger_even_when_unified_consumer_flag_is_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HAPAX_UNIFIED_REACTIVITY_ACTIVE", raising=False)
    ledger_path = tmp_path / "audio-source-ledger.json"
    bus = UnifiedReactivityBus(
        shm_path=tmp_path / "unified-reactivity.json",
        ledger_path=ledger_path,
        ledger_durable_dir=tmp_path / "durable",
        ledger_enabled=True,
        ledger_min_period_s=0.0,
    )

    class Source:
        @property
        def name(self) -> str:
            return "mixer"

        def get_signals(self) -> AudioSignals:
            return _sig(0.6)

        def is_active(self) -> bool:
            return True

    bus.register(Source())
    bus.tick(publish=True)

    ledger = read_audio_source_ledger(ledger_path)
    assert ledger is not None
    assert _rows(ledger)["mixer"].active is True
    jsonl_files = list((tmp_path / "durable").glob("*.jsonl"))
    assert len(jsonl_files) == 1
    assert '"active_source_ids": ["mixer"]' in jsonl_files[0].read_text(encoding="utf-8")
