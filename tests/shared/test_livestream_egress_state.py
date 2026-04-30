"""Tests for the constitutive livestream egress resolver."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from shared.content_source_provenance_egress import (
    BroadcastManifestAsset,
    EgressKillSwitchState,
    EgressOffender,
    build_broadcast_manifest,
)
from shared.livestream_egress_state import (
    EgressState,
    FloorState,
    LivestreamEgressPaths,
    resolve_livestream_egress_state,
)


def _paths(root: Path) -> LivestreamEgressPaths:
    return LivestreamEgressPaths(
        compositor_status=root / "status.json",
        compositor_snapshot=root / "snapshot.jpg",
        hls_playlist=root / "hls" / "stream.m3u8",
        hls_archive_root=root / "archive",
        livestream_status=root / "livestream-status.json",
        youtube_video_id=root / "youtube-video-id.txt",
        youtube_ingest_proof=root / "youtube-ingest.json",
        broadcast_events=root / "broadcast-events.jsonl",
        stream_mode=root / "stream-mode",
        working_mode=root / "working-mode",
        broadcast_audio_health=root / "audio-safe-for-broadcast.json",
        broadcast_manifest=root / "broadcast-manifest.json",
        egress_kill_switch=root / "egress-kill-switch.json",
        consent_state=root / "consent-state.txt",
        perception_state=root / "perception-state.json",
        monetization_flagged_root=root / "monetization-flagged",
    )


def _write(path: Path, content: str, *, now: float, age_s: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    mtime = now - age_s
    os.utime(path, (mtime, mtime))


def _audio_health_payload(*, safe: bool = True) -> dict:
    reasons = []
    if not safe:
        reasons.append(
            {
                "code": "loudness_out_of_band",
                "severity": "blocking",
                "owner": "shared/audio_loudness.py",
                "message": "broadcast loudness is outside target band",
                "evidence_refs": ["loudness"],
            }
        )
    return {
        "audio_safe_for_broadcast": {
            "safe": safe,
            "status": "safe" if safe else "unsafe",
            "checked_at": "2026-04-28T23:00:00Z",
            "freshness_s": 0.0,
            "blocking_reasons": reasons,
            "warnings": [],
            "evidence": {
                "loudness": {
                    "integrated_lufs_i": -14.0 if safe else -20.0,
                    "true_peak_dbtp": -1.0,
                }
            },
            "owners": {"health_consumer": "livestream-health-group"},
        }
    }


def _write_manifest(
    paths: LivestreamEgressPaths,
    *,
    now: float,
    age_s: float = 0.0,
    audio_assets: tuple[BroadcastManifestAsset, ...] | None = None,
    visual_assets: tuple[BroadcastManifestAsset, ...] | None = None,
) -> None:
    manifest = build_broadcast_manifest(
        audio_assets=audio_assets
        if audio_assets is not None
        else (
            BroadcastManifestAsset(
                token="music:hapax-pool:clear",
                tier="tier_0_owned",
                source="music-bed",
                medium="audio",
            ),
        ),
        visual_assets=visual_assets
        if visual_assets is not None
        else (
            BroadcastManifestAsset(
                token="visual:source:clear",
                tier="tier_0_owned",
                source="compositor:sierpinski",
                medium="visual",
            ),
        ),
        tick_id="tick-good",
        ts=now - age_s,
        max_content_risk="tier_1_platform_cleared",
    )
    _write(paths.broadcast_manifest, manifest.model_dump_json(), now=now, age_s=age_s)


def _write_kill_switch(
    paths: LivestreamEgressPaths,
    *,
    now: float,
    age_s: float = 0.0,
    active: bool = False,
    offenders: tuple[EgressOffender, ...] = (),
) -> None:
    state = EgressKillSwitchState(
        active=active,
        updated_at=now - age_s,
        audio_action="duck_to_negative_infinity" if active else "pass_through",
        visual_action="crossfade_to_tier0_fallback_shader" if active else "pass_through",
        offenders=offenders,
    )
    _write(paths.egress_kill_switch, state.model_dump_json(), now=now, age_s=age_s)


def _write_good_fixture(paths: LivestreamEgressPaths, *, now: float) -> None:
    now_iso = datetime.fromtimestamp(now, tz=UTC).isoformat().replace("+00:00", "Z")
    _write(
        paths.compositor_status,
        json.dumps(
            {
                "state": "running",
                "active_cameras": 6,
                "hls_enabled": True,
                "rtmp_attached": True,
                "rtmp_rebuild_count": 0,
                "consent_recording_allowed": True,
                "guest_present": False,
                "consent_phase": "no_guest",
                "timestamp": now,
            }
        ),
        now=now,
    )
    _write(paths.compositor_snapshot, "jpeg", now=now)
    _write(paths.hls_playlist, "#EXTM3U\n", now=now)
    day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
    _write(paths.hls_archive_root / day / "segment00001.ts.json", "{}", now=now)
    _write(paths.stream_mode, "public_research", now=now)
    _write(paths.working_mode, "fortress", now=now)
    _write(paths.consent_state, "allowed", now=now)
    _write(paths.perception_state, json.dumps({"audio_energy_rms": 0.01}), now=now)
    _write(paths.broadcast_audio_health, json.dumps(_audio_health_payload()), now=now)
    _write_manifest(paths, now=now)
    _write_kill_switch(paths, now=now)
    _write(paths.youtube_video_id, "video-123", now=now)
    _write(
        paths.youtube_ingest_proof,
        json.dumps({"status": "active", "video_id": "video-123"}),
        now=now,
    )
    _write(
        paths.broadcast_events,
        json.dumps(
            {
                "event_type": "broadcast_rotated",
                "timestamp": now_iso,
                "incoming_broadcast_id": "video-123",
                "seed_title": "Legomena Live - Segment 1",
            }
        )
        + "\n",
        now=now,
    )


def test_all_evidence_allows_public_live_claim(tmp_path: Path) -> None:
    now = time.time()
    paths = _paths(tmp_path)
    _write_good_fixture(paths, now=now)

    state = resolve_livestream_egress_state(
        paths=paths,
        now=now,
        http_probe=lambda _url, _timeout: 200,
        env={},
    )

    assert state.state is EgressState.PUBLIC_LIVE
    assert state.public_claim_allowed is True
    assert state.public_ready is True
    assert state.research_capture_ready is True
    assert state.privacy_floor is FloorState.SATISFIED
    assert state.audio_floor is FloorState.SATISFIED
    assert state.operator_action == "none"


def test_mediamtx_404_blocks_public_claim(tmp_path: Path) -> None:
    now = time.time()
    paths = _paths(tmp_path)
    _write_good_fixture(paths, now=now)

    state = resolve_livestream_egress_state(
        paths=paths,
        now=now,
        http_probe=lambda _url, _timeout: 404,
        env={},
    )

    assert state.public_claim_allowed is False
    assert state.public_ready is False
    assert state.state is EgressState.PUBLIC_BLOCKED
    assert state.operator_action == "start mediamtx.service and verify /studio/index.m3u8"


def test_stale_hls_blocks_research_capture_ready(tmp_path: Path) -> None:
    now = time.time()
    paths = _paths(tmp_path)
    _write_good_fixture(paths, now=now)
    _write(paths.hls_playlist, "#EXTM3U\n", now=now, age_s=120)

    state = resolve_livestream_egress_state(
        paths=paths,
        now=now,
        http_probe=lambda _url, _timeout: 200,
        env={},
    )

    assert state.research_capture_ready is False
    assert state.public_claim_allowed is False
    assert state.operator_action == "restore local HLS playlist generation"


def test_disabled_compositor_hls_blocks_research_capture_ready(tmp_path: Path) -> None:
    now = time.time()
    paths = _paths(tmp_path)
    _write_good_fixture(paths, now=now)
    status = json.loads(paths.compositor_status.read_text(encoding="utf-8"))
    status["hls_enabled"] = False
    _write(paths.compositor_status, json.dumps(status), now=now)

    state = resolve_livestream_egress_state(
        paths=paths,
        now=now,
        http_probe=lambda _url, _timeout: 200,
        env={},
    )

    assert state.research_capture_ready is False
    assert state.public_claim_allowed is False
    hls = next(item for item in state.evidence if item.source == "hls_playlist")
    assert hls.status == "fail"
    assert hls.observed["hls_enabled"] is False


def test_face_obscure_disabled_blocks_privacy_floor(tmp_path: Path) -> None:
    now = time.time()
    paths = _paths(tmp_path)
    _write_good_fixture(paths, now=now)

    state = resolve_livestream_egress_state(
        paths=paths,
        now=now,
        http_probe=lambda _url, _timeout: 200,
        env={"HAPAX_FACE_OBSCURE_ACTIVE": "0"},
    )

    assert state.privacy_floor is FloorState.BLOCKED
    assert state.public_claim_allowed is False
    assert state.operator_action == "restore face-obscure/privacy floor before public egress"


def test_unsafe_audio_safe_for_broadcast_blocks_public_claim(tmp_path: Path) -> None:
    now = time.time()
    paths = _paths(tmp_path)
    _write_good_fixture(paths, now=now)
    _write(paths.broadcast_audio_health, json.dumps(_audio_health_payload(safe=False)), now=now)

    state = resolve_livestream_egress_state(
        paths=paths,
        now=now,
        http_probe=lambda _url, _timeout: 200,
        env={},
    )

    assert state.audio_floor is FloorState.BLOCKED
    assert state.public_claim_allowed is False
    assert state.operator_action == "restore broadcast audio floor before public egress"
    audio = next(item for item in state.evidence if item.source == "audio_floor")
    assert audio.observed["audio_safe_for_broadcast"]["safe"] is False


def test_clean_broadcast_manifest_is_non_blocking_evidence(tmp_path: Path) -> None:
    now = time.time()
    paths = _paths(tmp_path)
    _write_good_fixture(paths, now=now)

    state = resolve_livestream_egress_state(
        paths=paths,
        now=now,
        http_probe=lambda _url, _timeout: 200,
        env={},
    )

    evidence = next(item for item in state.evidence if item.source == "egress_provenance")
    assert evidence.status == "pass"
    assert evidence.observed["public_claim_allowed"] is True
    assert evidence.observed["monetization_readiness"]["status"] == "pass"
    assert "egress_provenance_manifest_missing" not in state.public_claim_blockers


def test_missing_broadcast_manifest_blocks_public_claim_with_reason_code(
    tmp_path: Path,
) -> None:
    now = time.time()
    paths = _paths(tmp_path)
    _write_good_fixture(paths, now=now)
    paths.broadcast_manifest.unlink()

    state = resolve_livestream_egress_state(
        paths=paths,
        now=now,
        http_probe=lambda _url, _timeout: 200,
        env={},
    )

    assert state.public_claim_allowed is False
    assert state.public_ready is False
    assert state.state is EgressState.PUBLIC_BLOCKED
    assert state.monetization_risk == "unknown"
    assert "egress_provenance_manifest_missing" in state.public_claim_blockers
    evidence = next(item for item in state.evidence if item.source == "egress_provenance")
    assert evidence.status == "fail"
    assert evidence.observed["reason_codes"] == ["egress_provenance_manifest_missing"]
    assert state.operator_action == (
        "restore fresh broadcast provenance manifest and clear egress kill-switch"
    )


def test_stale_broadcast_manifest_blocks_public_claim(tmp_path: Path) -> None:
    now = time.time()
    paths = _paths(tmp_path)
    _write_good_fixture(paths, now=now)
    _write_manifest(paths, now=now, age_s=60.0)

    state = resolve_livestream_egress_state(
        paths=paths,
        now=now,
        http_probe=lambda _url, _timeout: 200,
        env={},
    )

    assert state.public_claim_allowed is False
    assert "egress_provenance_manifest_stale" in state.public_claim_blockers
    evidence = next(item for item in state.evidence if item.source == "egress_provenance")
    assert evidence.stale is True
    assert evidence.observed["manifest"]["status"] == "stale"


def test_malformed_broadcast_manifest_blocks_public_claim(tmp_path: Path) -> None:
    now = time.time()
    paths = _paths(tmp_path)
    _write_good_fixture(paths, now=now)
    _write(paths.broadcast_manifest, "{", now=now)

    state = resolve_livestream_egress_state(
        paths=paths,
        now=now,
        http_probe=lambda _url, _timeout: 200,
        env={},
    )

    assert state.public_claim_allowed is False
    assert "egress_provenance_manifest_malformed" in state.public_claim_blockers
    evidence = next(item for item in state.evidence if item.source == "egress_provenance")
    assert evidence.observed["manifest"]["status"] == "malformed"


def test_missing_egress_kill_switch_blocks_public_claim_with_reason_code(
    tmp_path: Path,
) -> None:
    now = time.time()
    paths = _paths(tmp_path)
    _write_good_fixture(paths, now=now)
    paths.egress_kill_switch.unlink()

    state = resolve_livestream_egress_state(
        paths=paths,
        now=now,
        http_probe=lambda _url, _timeout: 200,
        env={},
    )

    assert state.public_claim_allowed is False
    assert "egress_kill_switch_missing" in state.public_claim_blockers
    evidence = next(item for item in state.evidence if item.source == "egress_provenance")
    assert evidence.observed["kill_switch"]["status"] == "missing"


def test_stale_egress_kill_switch_blocks_public_claim(tmp_path: Path) -> None:
    now = time.time()
    paths = _paths(tmp_path)
    _write_good_fixture(paths, now=now)
    _write_kill_switch(paths, now=now, age_s=60.0)

    state = resolve_livestream_egress_state(
        paths=paths,
        now=now,
        http_probe=lambda _url, _timeout: 200,
        env={},
    )

    assert state.public_claim_allowed is False
    assert "egress_kill_switch_stale" in state.public_claim_blockers
    evidence = next(item for item in state.evidence if item.source == "egress_provenance")
    assert evidence.observed["kill_switch"]["state_age_s"] == 60.0


def test_malformed_egress_kill_switch_blocks_public_claim(tmp_path: Path) -> None:
    now = time.time()
    paths = _paths(tmp_path)
    _write_good_fixture(paths, now=now)
    _write(paths.egress_kill_switch, "{", now=now)

    state = resolve_livestream_egress_state(
        paths=paths,
        now=now,
        http_probe=lambda _url, _timeout: 200,
        env={},
    )

    assert state.public_claim_allowed is False
    assert "egress_kill_switch_malformed" in state.public_claim_blockers
    evidence = next(item for item in state.evidence if item.source == "egress_provenance")
    assert evidence.observed["kill_switch"]["status"] == "malformed"


def test_over_tier_broadcast_manifest_blocks_public_claim_and_monetization(
    tmp_path: Path,
) -> None:
    now = time.time()
    paths = _paths(tmp_path)
    _write_good_fixture(paths, now=now)
    _write_manifest(
        paths,
        now=now,
        visual_assets=(
            BroadcastManifestAsset(
                token="visual:third-party:uncleared",
                tier="tier_4_risky",
                source="visual-pool-slot-0",
                medium="visual",
            ),
        ),
    )

    state = resolve_livestream_egress_state(
        paths=paths,
        now=now,
        http_probe=lambda _url, _timeout: 200,
        env={},
    )

    assert state.public_claim_allowed is False
    assert state.monetization_risk == "high"
    assert "egress_provenance_over_tier" in state.public_claim_blockers
    evidence = next(item for item in state.evidence if item.source == "egress_provenance")
    offender = evidence.observed["offenders"][0]
    assert offender["token"] == "visual:third-party:uncleared"
    assert offender["risk_tier"] == "tier_4_risky"
    assert offender["source"] == "visual-pool-slot-0"
    assert offender["surface"] == "visual"
    assert offender["fallback_action"] == "crossfade_to_tier0_fallback_shader"


def test_active_egress_kill_switch_blocks_public_claim_with_recovery_fields(
    tmp_path: Path,
) -> None:
    now = time.time()
    paths = _paths(tmp_path)
    _write_good_fixture(paths, now=now)
    offender = EgressOffender(
        token="visual:third-party:uncleared",
        tier="tier_4_risky",
        source="visual-pool-slot-0",
        medium="visual",
        reason="over_tier",
    )
    _write_kill_switch(paths, now=now, active=True, offenders=(offender,))

    state = resolve_livestream_egress_state(
        paths=paths,
        now=now,
        http_probe=lambda _url, _timeout: 200,
        env={},
    )

    assert state.public_claim_allowed is False
    assert "egress_kill_switch_active" in state.public_claim_blockers
    kill = next(item for item in state.evidence if item.source == "egress.kill_switch_fired")
    assert kill.status == "fail"
    assert kill.observed["event_type"] == "egress.kill_switch_fired"
    assert kill.observed["fallback_visual_token"] == "visual:fallback:tier0-wgpu-shader"
    observed_offender = kill.observed["offenders"][0]
    assert observed_offender["token"] == "visual:third-party:uncleared"
    assert observed_offender["risk_tier"] == "tier_4_risky"
    assert observed_offender["source"] == "visual-pool-slot-0"
    assert observed_offender["surface"] == "visual"
    assert observed_offender["recovery_instruction"]


def test_missing_youtube_ingest_proof_fails_closed(tmp_path: Path) -> None:
    now = time.time()
    paths = _paths(tmp_path)
    _write_good_fixture(paths, now=now)
    paths.youtube_ingest_proof.unlink()

    state = resolve_livestream_egress_state(
        paths=paths,
        now=now,
        http_probe=lambda _url, _timeout: 200,
        env={},
    )

    assert state.public_claim_allowed is False
    assert state.public_ready is True
    assert state.state is EgressState.PUBLIC_READY
    assert state.operator_action == "verify YouTube ingest with a fresh active proof"


def test_stale_metadata_event_timestamp_fails_closed_even_when_log_touched(
    tmp_path: Path,
) -> None:
    now = time.time()
    paths = _paths(tmp_path)
    _write_good_fixture(paths, now=now)
    old_timestamp = datetime.fromtimestamp(now - 13 * 3600, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write(
        paths.broadcast_events,
        json.dumps(
            {
                "event_type": "broadcast_rotated",
                "timestamp": old_timestamp,
                "incoming_broadcast_id": "video-123",
            }
        )
        + "\n",
        now=now,
    )

    state = resolve_livestream_egress_state(
        paths=paths,
        now=now,
        http_probe=lambda _url, _timeout: 200,
        env={},
    )

    assert state.public_claim_allowed is False
    assert state.public_ready is False
    assert state.operator_action == "align broadcast metadata with the active video id"
    metadata = next(item for item in state.evidence if item.source == "metadata")
    assert metadata.status == "fail"
    assert metadata.age_s is not None
    assert metadata.age_s > 12 * 3600
