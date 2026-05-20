"""Semantic audio canary matrix for livestream boundary proof.

Generates distinguishable per-route/per-channel canary tones and
witnesses whether they appear at authorized capture points. Proves
that livestream-bound canaries reach only livestream outputs, and
PC/private canaries do NOT leak into livestream capture.

Authority case: CASE-AUDIO-GRAPH-SSOT-AND-ROUTER-DAEMON-DESIG
"""

from __future__ import annotations

import hashlib
import logging
import math
import struct
from dataclasses import dataclass, field
from enum import StrEnum

log = logging.getLogger(__name__)

SAMPLE_RATE = 44100
CANARY_DURATION_S = 0.5
CANARY_AMPLITUDE = 0.05


class AudioRoute(StrEnum):
    VOICE = "voice"
    MUSIC = "music"
    PC_AUDIO = "pc_audio"
    YOUTUBE_RETURN = "youtube_return"
    PRIVATE = "private"
    LIVESTREAM_TAP = "livestream_tap"
    BROADCAST_MASTER = "broadcast_master"
    OBS_BROADCAST = "obs_broadcast"


class CapturePoint(StrEnum):
    LIVESTREAM = "livestream"
    PRIVATE_MONITOR = "private_monitor"
    RECORDING = "recording"


LIVESTREAM_AUTHORIZED_ROUTES: frozenset[AudioRoute] = frozenset(
    {
        AudioRoute.VOICE,
        AudioRoute.MUSIC,
        AudioRoute.LIVESTREAM_TAP,
        AudioRoute.BROADCAST_MASTER,
        AudioRoute.OBS_BROADCAST,
    }
)

PRIVATE_ONLY_ROUTES: frozenset[AudioRoute] = frozenset(
    {
        AudioRoute.PC_AUDIO,
        AudioRoute.YOUTUBE_RETURN,
        AudioRoute.PRIVATE,
    }
)

ROUTE_FREQUENCIES: dict[AudioRoute, float] = {
    AudioRoute.VOICE: 440.0,
    AudioRoute.MUSIC: 554.37,
    AudioRoute.PC_AUDIO: 659.25,
    AudioRoute.YOUTUBE_RETURN: 783.99,
    AudioRoute.PRIVATE: 880.0,
    AudioRoute.LIVESTREAM_TAP: 987.77,
    AudioRoute.BROADCAST_MASTER: 1108.73,
    AudioRoute.OBS_BROADCAST: 1318.51,
}


@dataclass(frozen=True)
class CanaryTone:
    route: AudioRoute
    frequency_hz: float
    channel: int
    duration_s: float = CANARY_DURATION_S
    amplitude: float = CANARY_AMPLITUDE

    @property
    def marker_id(self) -> str:
        raw = f"{self.route.value}:{self.frequency_hz}:{self.channel}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class CanaryDetection:
    route: AudioRoute
    frequency_hz: float
    detected_snr_db: float
    channel: int
    capture_point: CapturePoint


@dataclass(frozen=True)
class BoundaryProofResult:
    capture_point: CapturePoint
    authorized_detections: list[CanaryDetection] = field(default_factory=list)
    unauthorized_detections: list[CanaryDetection] = field(default_factory=list)
    missing_authorized: list[AudioRoute] = field(default_factory=list)
    passed: bool = True
    evidence: dict[str, object] = field(default_factory=dict)


def generate_canary_tone(route: AudioRoute, *, channel: int = 0) -> CanaryTone:
    freq = ROUTE_FREQUENCIES[route]
    return CanaryTone(route=route, frequency_hz=freq, channel=channel)


def generate_canary_pcm(tone: CanaryTone) -> bytes:
    num_samples = int(SAMPLE_RATE * tone.duration_s)
    samples = []
    for i in range(num_samples):
        t = i / SAMPLE_RATE
        value = tone.amplitude * math.sin(2 * math.pi * tone.frequency_hz * t)
        samples.append(struct.pack("<f", value))
    return b"".join(samples)


def detect_canary_in_buffer(
    pcm_float32: bytes,
    target_freq: float,
    *,
    sample_rate: int = SAMPLE_RATE,
    detection_threshold_db: float = -40.0,
) -> float | None:
    """Detect a canary tone via Goertzel algorithm. Returns SNR in dB or None."""
    num_samples = len(pcm_float32) // 4
    if num_samples < 64:
        return None

    samples = [struct.unpack_from("<f", pcm_float32, i * 4)[0] for i in range(num_samples)]

    k = round(target_freq * num_samples / sample_rate)
    omega = 2 * math.pi * k / num_samples
    coeff = 2 * math.cos(omega)
    s0, s1, s2 = 0.0, 0.0, 0.0
    for sample in samples:
        s0 = sample + coeff * s1 - s2
        s2 = s1
        s1 = s0
    power = s1 * s1 + s2 * s2 - coeff * s1 * s2
    power /= num_samples * num_samples

    total_power = sum(s * s for s in samples) / num_samples
    if total_power < 1e-12:
        return None

    snr = 10 * math.log10(max(power, 1e-12) / max(total_power - power, 1e-12))
    return snr if snr >= detection_threshold_db else None


def prove_boundary(
    detections: list[CanaryDetection],
    capture_point: CapturePoint,
) -> BoundaryProofResult:
    authorized: list[CanaryDetection] = []
    unauthorized: list[CanaryDetection] = []

    for det in detections:
        if capture_point == CapturePoint.LIVESTREAM:
            if det.route in LIVESTREAM_AUTHORIZED_ROUTES:
                authorized.append(det)
            else:
                unauthorized.append(det)
        elif capture_point == CapturePoint.PRIVATE_MONITOR:
            authorized.append(det)
        else:
            authorized.append(det)

    missing: list[AudioRoute] = []
    if capture_point == CapturePoint.LIVESTREAM:
        detected_routes = {d.route for d in authorized}
        for route in LIVESTREAM_AUTHORIZED_ROUTES:
            if route not in detected_routes:
                missing.append(route)

    passed = len(unauthorized) == 0
    evidence = {
        "capture_point": capture_point.value,
        "authorized_count": len(authorized),
        "unauthorized_count": len(unauthorized),
        "missing_authorized_count": len(missing),
        "unauthorized_routes": [d.route.value for d in unauthorized],
        "missing_routes": [r.value for r in missing],
    }

    return BoundaryProofResult(
        capture_point=capture_point,
        authorized_detections=authorized,
        unauthorized_detections=unauthorized,
        missing_authorized=missing,
        passed=passed,
        evidence=evidence,
    )


__all__ = [
    "LIVESTREAM_AUTHORIZED_ROUTES",
    "PRIVATE_ONLY_ROUTES",
    "AudioRoute",
    "BoundaryProofResult",
    "CanaryDetection",
    "CanaryTone",
    "CapturePoint",
    "detect_canary_in_buffer",
    "generate_canary_pcm",
    "generate_canary_tone",
    "prove_boundary",
]
