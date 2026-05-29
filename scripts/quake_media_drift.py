#!/usr/bin/env python3
"""Receiver-local drift for DarkPlaces live texture feeds."""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np


DEFAULT_GAME_DATA = Path.home() / ".darkplaces/screwm/data"


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _read_scalar(game_data: Path, name: str, fallback: float = 0.0) -> float:
    try:
        text = (game_data / name).read_text(encoding="utf-8").strip()
        return _clamp01(float(text))
    except (OSError, ValueError):
        return fallback


def _read_marker(game_data: Path, name: str) -> str:
    try:
        return (game_data / name).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


@dataclass(frozen=True)
class DriftState:
    source: str
    real_source: float
    active_ratio: float
    active_slot_ratio: float
    active_effect_ratio: float
    fast_ratio: float
    slow_ratio: float
    kind_variance: float
    max_delta: float
    region_count: float
    tonal: float
    atmospheric: float
    temporal: float
    texture: float
    edge: float
    compositing: float
    visual_noise: float
    visual_drift: float
    visual_color: float
    visual_feedback: float
    visual_aperture: float
    visual_param_pressure: float
    mode_tonal: float
    mode_atmospheric: float
    mode_temporal: float
    mode_texture: float
    mode_edge: float
    mode_compositing: float

    @property
    def intensity(self) -> float:
        mode_pressure = max(
            self.mode_tonal,
            self.mode_atmospheric,
            self.mode_temporal,
            self.mode_texture,
            self.mode_edge,
            self.mode_compositing,
        )
        return _clamp01(
            0.34
            + self.active_ratio * 0.20
            + self.active_effect_ratio * 0.14
            + self.kind_variance * 0.14
            + self.visual_param_pressure * 0.14
            + self.visual_drift * 0.12
            + self.max_delta * 0.10
            + self.fast_ratio * 0.07
            + self.slow_ratio * 0.05
            + mode_pressure * 0.08
            + self.real_source * 0.06
        )


def load_drift_state(game_data: Path = DEFAULT_GAME_DATA) -> DriftState:
    return DriftState(
        source=_read_marker(game_data, "effect-drift-source.txt"),
        real_source=_read_scalar(game_data, "effect-drift-real-source.txt"),
        active_ratio=_read_scalar(game_data, "effect-drift-active-ratio.txt"),
        active_slot_ratio=_read_scalar(game_data, "effect-drift-active-slot-ratio.txt"),
        active_effect_ratio=_read_scalar(game_data, "effect-drift-active-effect-ratio.txt"),
        fast_ratio=_read_scalar(game_data, "effect-drift-fast-ratio.txt"),
        slow_ratio=_read_scalar(game_data, "effect-drift-slow-ratio.txt"),
        kind_variance=_read_scalar(game_data, "effect-drift-kind-variance.txt"),
        max_delta=_read_scalar(game_data, "effect-drift-max-delta.txt"),
        region_count=_read_scalar(game_data, "effect-drift-region-count.txt"),
        tonal=_read_scalar(game_data, "effect-drift-tonal.txt"),
        atmospheric=_read_scalar(game_data, "effect-drift-atmospheric.txt"),
        temporal=_read_scalar(game_data, "effect-drift-temporal.txt"),
        texture=_read_scalar(game_data, "effect-drift-texture.txt"),
        edge=_read_scalar(game_data, "effect-drift-edge.txt"),
        compositing=_read_scalar(game_data, "effect-drift-compositing.txt"),
        visual_noise=_read_scalar(game_data, "visual-chain-noise.txt"),
        visual_drift=_read_scalar(game_data, "visual-chain-drift.txt"),
        visual_color=_read_scalar(game_data, "visual-chain-color.txt"),
        visual_feedback=_read_scalar(game_data, "visual-chain-feedback.txt"),
        visual_aperture=_read_scalar(game_data, "visual-chain-aperture.txt"),
        visual_param_pressure=_read_scalar(game_data, "visual-chain-param-pressure.txt"),
        mode_tonal=_read_scalar(game_data, "effect-drift-mode-tonal.txt"),
        mode_atmospheric=_read_scalar(game_data, "effect-drift-mode-atmospheric.txt"),
        mode_temporal=_read_scalar(game_data, "effect-drift-mode-temporal.txt"),
        mode_texture=_read_scalar(game_data, "effect-drift-mode-texture.txt"),
        mode_edge=_read_scalar(game_data, "effect-drift-mode-edge.txt"),
        mode_compositing=_read_scalar(game_data, "effect-drift-mode-compositing.txt"),
    )


def _stable_seed(receiver: str, frame: int, now: float) -> int:
    digest = hashlib.blake2s(receiver.encode("utf-8"), digest_size=4).digest()
    receiver_seed = int.from_bytes(digest, "little")
    return receiver_seed ^ (frame * 2654435761) ^ int(now * 3.0)


def _receiver_gain(receiver: str) -> float:
    lowered = receiver.lower()
    if "oarb" in lowered or "youtube" in lowered:
        return 1.38
    if "ticker" in lowered:
        return 1.62
    if "atlas" in lowered or "ward" in lowered:
        return 1.42
    if "reverie" in lowered:
        return 1.46
    if "camera" in lowered or "cam" in lowered:
        return 1.12
    return 1.0


def _receiver_min_chroma_px(receiver: str) -> int:
    lowered = receiver.lower()
    if "ticker" in lowered:
        return 6
    if "camera" in lowered or "cam" in lowered:
        return 14
    if "oarb" in lowered or "youtube" in lowered:
        return 18
    if "atlas" in lowered or "ward" in lowered or "reverie" in lowered:
        return 16
    return 10


def _receiver_is_camera(receiver: str) -> bool:
    lowered = receiver.lower()
    return "camera" in lowered or "cam" in lowered


def _receiver_is_reverie(receiver: str) -> bool:
    return "reverie" in receiver.lower()


def _apply_reverie_tonemap(rgb: np.ndarray, intensity: float) -> np.ndarray:
    """Turn the high-luma Reverie substrate into an in-room material ward."""
    luma = rgb[:, :, 2] * 0.299 + rgb[:, :, 1] * 0.587 + rgb[:, :, 0] * 0.114
    gray = luma[:, :, None]
    saturation = 1.60 + intensity * 0.70
    contrast = 1.22 + intensity * 0.28
    pivot = 170.0 - intensity * 4.0
    lift = 22.0 + intensity * 8.0
    toned = gray + (rgb - gray) * saturation
    toned = (toned - pivot) * contrast + lift
    toned *= np.array([1.08, 0.68, 1.12], dtype=np.float32)
    return np.clip(toned, 0, 255)


def apply_frame_drift(
    data: bytes,
    *,
    width: int,
    height: int,
    state: DriftState,
    receiver: str,
    frame: int,
    now: float,
    previous_rgb: np.ndarray | None = None,
    intensity_scale: float = 1.0,
) -> tuple[bytes, np.ndarray | None]:
    """Apply receiver-local compositing drift to one BGRA frame.

    The renderer deliberately operates on media texture bytes before DarkPlaces
    upload. This makes OARB, camera, ticker, reverie, and atlas receivers carry
    drift even while OBS is still viewing the direct DarkPlaces route.
    """

    expected = width * height * 4
    if width <= 0 or height <= 0 or len(data) != expected:
        return data, previous_rgb

    fast_wave = 0.5 + 0.5 * math.sin(now * (1.70 + state.fast_ratio * 1.20) + frame * 0.31)
    slow_wave = 0.5 + 0.5 * math.sin(now * (0.17 + state.slow_ratio * 0.18) + frame * 0.043)
    mutation_pressure = _clamp01(0.35 + state.kind_variance * 0.45 + state.active_effect_ratio * 0.20)
    cadence_gain = _clamp01(0.62 + state.fast_ratio * fast_wave * 0.42 + state.slow_ratio * slow_wave * 0.26)
    gain = _receiver_gain(receiver)
    intensity = _clamp01(state.intensity * gain * intensity_scale * cadence_gain)
    if intensity <= 0.02:
        return data, previous_rgb

    arr = np.frombuffer(data, dtype=np.uint8).reshape((height, width, 4)).copy()
    rgb = arr[:, :, :3].astype(np.float32)
    phase = now * (0.34 + state.region_count * 0.42 + state.fast_ratio * 0.28) + frame * (
        0.017 + state.kind_variance * 0.011
    )
    min_dim = max(1, min(width, height))
    camera_receiver = _receiver_is_camera(receiver)
    reverie_receiver = _receiver_is_reverie(receiver)

    if reverie_receiver:
        rgb = _apply_reverie_tonemap(rgb, intensity)

    chroma_px = int(
        max(
            _receiver_min_chroma_px(receiver),
            min(
                72 if not camera_receiver else 34,
                round(
                    min_dim
                    * (
                        0.0040
                        + 0.0100 * intensity
                        + 0.0065 * state.compositing
                        + 0.0045 * state.active_slot_ratio
                        + 0.0050 * mutation_pressure
                        + 0.0035 * state.mode_atmospheric
                    )
                ),
            ),
        )
    )
    drift_x = int(round(math.sin(phase) * chroma_px))
    drift_y = int(round(math.cos(phase * 0.73) * max(1, chroma_px // 2)))
    red = np.roll(rgb[:, :, 2], shift=(drift_y, drift_x), axis=(0, 1))
    blue = np.roll(rgb[:, :, 0], shift=(-drift_y, -drift_x), axis=(0, 1))
    chroma_mix = min(
        0.88,
        0.30
        + state.visual_color * 0.20
        + state.compositing * 0.22
        + state.mode_compositing * 0.14
        + state.mode_atmospheric * 0.10
        + intensity * 0.24,
    )
    if camera_receiver:
        chroma_mix = min(chroma_mix, 0.52)
    rgb[:, :, 2] = rgb[:, :, 2] * (1.0 - chroma_mix) + red * chroma_mix
    rgb[:, :, 0] = rgb[:, :, 0] * (1.0 - chroma_mix) + blue * chroma_mix

    if not camera_receiver and previous_rgb is not None and previous_rgb.shape == rgb.shape:
        trail_shift = (
            int(round(math.sin(phase * 0.41) * max(1, chroma_px // 2))),
            int(round(math.cos(phase * 0.37) * max(1, chroma_px))),
        )
        previous = np.roll(previous_rgb, shift=trail_shift, axis=(0, 1))
        feedback = min(
            0.68,
            0.14
            + state.temporal * 0.18
            + state.visual_feedback * 0.16
            + state.mode_temporal * 0.14
            + state.active_effect_ratio * 0.08
            + slow_wave * 0.06,
        )
        rgb = rgb * (1.0 - feedback) + previous * feedback

    luma = rgb[:, :, 2] * 0.299 + rgb[:, :, 1] * 0.587 + rgb[:, :, 0] * 0.114
    saturation = 1.0 + intensity * (
        0.18 + state.tonal * 0.16 + state.visual_color * 0.14 + state.mode_tonal * 0.14
    )
    if camera_receiver:
        saturation = min(saturation, 1.34)
    rgb = luma[:, :, None] + (rgb - luma[:, :, None]) * saturation
    dx = np.abs(np.roll(luma, -1, axis=1) - luma)
    dy = np.abs(np.roll(luma, -1, axis=0) - luma)
    edge_gain = 0.58 if camera_receiver else 1.0
    edge = np.clip(
        (dx + dy)
        * edge_gain
        * (0.012 + state.edge * 0.021 + state.mode_edge * 0.016 + intensity * 0.012),
        0,
        48 if not camera_receiver else 28,
    )
    rgb[:, :, 0] += edge * (1.8 + state.visual_drift)
    rgb[:, :, 2] += edge * (1.1 + state.tonal)

    rng = np.random.default_rng(_stable_seed(receiver, frame, now))
    if camera_receiver:
        block_count = int(state.fast_ratio * 1.4 + state.kind_variance * 0.9 + intensity * 1.2)
    else:
        block_count = int(
            2
            + state.texture * 7
            + state.temporal * 5
            + state.mode_texture * 4
            + state.active_effect_ratio * 5
            + state.fast_ratio * 4
            + state.kind_variance * 3
            + intensity * 4
        )
    for _ in range(min(18, max(0, block_count))):
        bw = int(rng.integers(max(8, width // 32), max(12, width // 8)))
        bh = int(rng.integers(max(6, height // 36), max(10, height // 9)))
        if bw >= width or bh >= height:
            continue
        x0 = int(rng.integers(0, width - bw))
        y0 = int(rng.integers(0, height - bh))
        ox = int(rng.integers(-max(2, width // 42), max(3, width // 42)))
        oy = int(rng.integers(-max(2, height // 48), max(3, height // 48)))
        x1 = min(width - bw, max(0, x0 + ox))
        y1 = min(height - bh, max(0, y0 + oy))
        block = rgb[y1 : y1 + bh, x1 : x1 + bw]
        tint = np.array([1.14, 0.72 + state.tonal * 0.18, 1.08 + state.compositing * 0.24])
        mix = min(0.22 if camera_receiver else 0.58, 0.10 + intensity * 0.18 + state.texture * 0.12 + state.fast_ratio * 0.08)
        rgb[y0 : y0 + bh, x0 : x0 + bw] = (
            rgb[y0 : y0 + bh, x0 : x0 + bw] * (1.0 - mix) + block * tint * mix
        )

    if state.visual_noise > 0.02 or state.texture > 0.02 or state.mode_texture > 0.02:
        noise_amp = 2.0 + 14.0 * min(1.0, state.visual_noise * 0.55 + state.texture * 0.45)
        noise_amp += 8.0 * state.mode_texture + 4.0 * fast_wave * state.fast_ratio
        if camera_receiver:
            noise_amp *= 0.28
        noise = rng.normal(0.0, noise_amp, size=rgb.shape[:2]).astype(np.float32)
        rgb[:, :, 0] += noise * 0.72
        rgb[:, :, 1] += noise * 0.32
        rgb[:, :, 2] -= noise * 0.55

    if state.texture > 0.04 or state.mode_texture > 0.04:
        period = max(3, int(round(min_dim / (18 + 26 * state.texture + 18 * state.mode_texture))))
        thickness = max(1, int(round(period * (0.06 + 0.05 * state.fast_ratio))))
        offset = int(round((phase * 18.0) % period))
        rows = ((np.arange(height) + offset) % period) < thickness
        line_strength = (4.0 + 28.0 * intensity * (0.45 + state.texture + state.mode_texture))
        if camera_receiver:
            line_strength *= 0.35
        rgb[rows, :, 0] += line_strength * 0.72
        rgb[rows, :, 1] += line_strength * 0.18
        rgb[rows, :, 2] -= line_strength * 0.36

    pulse = 0.5 + 0.5 * math.sin(phase * 0.67)
    cyan_magenta = np.array(
        [
            1.0 + state.visual_drift * 0.12 + state.mode_atmospheric * 0.08,
            0.94 + state.slow_ratio * 0.04,
            1.0 + state.compositing * 0.15 + state.mode_compositing * 0.09,
        ]
    )
    amber = np.array([0.93, 1.0 + state.tonal * 0.06, 1.0 + state.tonal * 0.13])
    rgb *= cyan_magenta * pulse + amber * (1.0 - pulse)

    arr[:, :, :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    arr[:, :, 3] = 255
    return arr.tobytes(), None if camera_receiver else rgb.astype(np.float32, copy=False)


class MediaDriftRenderer:
    def __init__(
        self,
        *,
        game_data: Path = DEFAULT_GAME_DATA,
        enabled: bool = True,
        intensity: float = 1.0,
        state_interval_s: float = 0.5,
    ) -> None:
        self.game_data = game_data
        self.enabled = enabled
        self.intensity = intensity
        self.state_interval_s = state_interval_s
        self._state: DriftState | None = None
        self._state_next_read = 0.0
        self._history: dict[str, np.ndarray] = {}

    def state(self, now: float | None = None) -> DriftState:
        if now is None:
            now = time.time()
        if self._state is None or now >= self._state_next_read:
            self._state = load_drift_state(self.game_data)
            self._state_next_read = now + self.state_interval_s
        return self._state

    def apply(
        self,
        data: bytes,
        *,
        width: int,
        height: int,
        receiver: str,
        frame: int,
        now: float | None = None,
    ) -> bytes:
        if not self.enabled:
            return data
        if now is None:
            now = time.time()
        state = self.state(now)
        output, history = apply_frame_drift(
            data,
            width=width,
            height=height,
            state=state,
            receiver=receiver,
            frame=frame,
            now=now,
            previous_rgb=self._history.get(receiver),
            intensity_scale=self.intensity,
        )
        if history is not None:
            self._history[receiver] = history
        return output
