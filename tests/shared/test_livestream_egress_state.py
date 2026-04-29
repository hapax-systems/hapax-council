"""Tests for the constitutive livestream egress resolver."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

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
