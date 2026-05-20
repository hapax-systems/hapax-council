"""Tests for shared.audio_canary_matrix."""

from __future__ import annotations

from shared.audio_canary_matrix import (
    AudioRoute,
    CanaryDetection,
    CapturePoint,
    detect_canary_in_buffer,
    generate_canary_pcm,
    generate_canary_tone,
    prove_boundary,
)


def test_generate_canary_tone_has_unique_frequency() -> None:
    voice = generate_canary_tone(AudioRoute.VOICE)
    music = generate_canary_tone(AudioRoute.MUSIC)
    assert voice.frequency_hz != music.frequency_hz
    assert voice.marker_id != music.marker_id


def test_generate_canary_pcm_produces_bytes() -> None:
    tone = generate_canary_tone(AudioRoute.VOICE)
    pcm = generate_canary_pcm(tone)
    assert len(pcm) > 0
    assert len(pcm) % 4 == 0


def test_detect_canary_finds_generated_tone() -> None:
    tone = generate_canary_tone(AudioRoute.VOICE)
    pcm = generate_canary_pcm(tone)
    snr = detect_canary_in_buffer(pcm, tone.frequency_hz)
    assert snr is not None
    assert snr > -10.0


def test_detect_canary_rejects_wrong_frequency() -> None:
    tone = generate_canary_tone(AudioRoute.VOICE)
    pcm = generate_canary_pcm(tone)
    snr = detect_canary_in_buffer(pcm, 2000.0, detection_threshold_db=-5.0)
    assert snr is None


def test_detect_canary_rejects_silence() -> None:
    silence = b"\x00" * (44100 * 4)
    snr = detect_canary_in_buffer(silence, 440.0)
    assert snr is None


def test_boundary_proof_passes_authorized_only() -> None:
    detections = [
        CanaryDetection(
            route=AudioRoute.VOICE,
            frequency_hz=440.0,
            detected_snr_db=10.0,
            channel=0,
            capture_point=CapturePoint.LIVESTREAM,
        ),
        CanaryDetection(
            route=AudioRoute.MUSIC,
            frequency_hz=554.37,
            detected_snr_db=8.0,
            channel=0,
            capture_point=CapturePoint.LIVESTREAM,
        ),
    ]
    result = prove_boundary(detections, CapturePoint.LIVESTREAM)
    assert result.passed
    assert len(result.unauthorized_detections) == 0


def test_boundary_proof_fails_on_private_leak() -> None:
    detections = [
        CanaryDetection(
            route=AudioRoute.VOICE,
            frequency_hz=440.0,
            detected_snr_db=10.0,
            channel=0,
            capture_point=CapturePoint.LIVESTREAM,
        ),
        CanaryDetection(
            route=AudioRoute.PC_AUDIO,
            frequency_hz=659.25,
            detected_snr_db=6.0,
            channel=0,
            capture_point=CapturePoint.LIVESTREAM,
        ),
    ]
    result = prove_boundary(detections, CapturePoint.LIVESTREAM)
    assert not result.passed
    assert len(result.unauthorized_detections) == 1
    assert result.unauthorized_detections[0].route == AudioRoute.PC_AUDIO


def test_boundary_proof_tracks_missing_authorized() -> None:
    result = prove_boundary([], CapturePoint.LIVESTREAM)
    assert result.passed
    assert len(result.missing_authorized) > 0


def test_private_monitor_accepts_all() -> None:
    detections = [
        CanaryDetection(
            route=AudioRoute.PC_AUDIO,
            frequency_hz=659.25,
            detected_snr_db=10.0,
            channel=0,
            capture_point=CapturePoint.PRIVATE_MONITOR,
        ),
    ]
    result = prove_boundary(detections, CapturePoint.PRIVATE_MONITOR)
    assert result.passed


def test_evidence_dict_populated() -> None:
    result = prove_boundary([], CapturePoint.LIVESTREAM)
    assert "capture_point" in result.evidence
    assert result.evidence["unauthorized_count"] == 0


def test_all_routes_have_unique_frequencies() -> None:
    freqs = set()
    for route in AudioRoute:
        tone = generate_canary_tone(route)
        assert tone.frequency_hz not in freqs, f"duplicate freq for {route}"
        freqs.add(tone.frequency_hz)
