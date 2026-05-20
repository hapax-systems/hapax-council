from __future__ import annotations

import numpy as np

from shared.live_surface_effect_policy import (
    LIVE_SURFACE_GLSL_SOURCE_BOUND_REPAIR_20260520_NODE_TYPES,
)


def _moving_source(shift_x: int) -> np.ndarray:
    h, w = 72, 96
    yy, xx = np.mgrid[0:h, 0:w]
    frame = np.zeros((h, w, 3), dtype=np.float32)
    frame[..., 0] = 0.06 + 0.18 * (xx / (w - 1))
    frame[..., 1] = 0.05 + 0.16 * (yy / (h - 1))
    frame[..., 2] = 0.08
    x0 = 18 + shift_x
    x1 = 42 + shift_x
    y0 = 20
    y1 = 52
    frame[y0:y1, x0:x1, :] = np.array([0.92, 0.82, 0.56], dtype=np.float32)
    frame[y0 + 5 : y1 - 5, x0 + 5 : x1 - 5, :] = np.array([0.98, 0.94, 0.78], dtype=np.float32)
    return frame


def _scanlines(frame: np.ndarray) -> np.ndarray:
    out = frame.copy()
    rows = np.arange(frame.shape[0], dtype=np.float32)
    line = ((rows % 4.0) >= (4.0 - 1.5)).astype(np.float32)
    out *= (1.0 - line[:, None, None] * 0.18)
    return np.clip(out, 0.0, 1.0)


def _pixsort(frame: np.ndarray) -> np.ndarray:
    out = frame.copy()
    luma = frame @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    for y in range(frame.shape[0]):
        row = out[y]
        gated = (luma[y] >= 0.35) & (luma[y] <= 0.55)
        x = 0
        while x < frame.shape[1]:
            if not gated[x]:
                x += 1
                continue
            start = x
            while x < frame.shape[1] and gated[x] and (x - start) < 48:
                x += 1
            stop = x
            if stop - start >= 3:
                order = np.argsort(luma[y, start:stop])
                row[start:stop] = row[start:stop][order]
    return np.clip(out, 0.0, 1.0)


def _glitch_block(frame: np.ndarray) -> np.ndarray:
    out = frame.copy()
    h, w, _ = frame.shape
    block = 8
    intensity = 0.25
    for y0 in range(0, h, block):
        for x0 in range(0, w, block):
            bid = (x0 // block) * 13 + (y0 // block) * 31
            if ((bid * 1103515245 + 12345) & 0xFFFF) / 0xFFFF >= intensity * 0.4:
                continue
            y1 = min(h, y0 + block)
            x1 = min(w, x0 + block)
            patch = frame[y0:y1, x0:x1]
            if bid % 5 == 0:
                dead = np.full_like(patch, ((bid % 17) / 17.0) * 0.3)
                out[y0:y1, x0:x1] = patch * (1.0 - intensity * 0.45) + dead * intensity * 0.45
            elif bid % 5 == 1:
                yy, xx = np.mgrid[y0:y1, x0:x1]
                data = np.stack(
                    [
                        ((xx + yy * 3) % 8) / 8.0,
                        (((xx * 2 + yy) % 6) / 6.0) * 0.7,
                        (((xx + yy * 3) % 8) / 8.0) * 0.5,
                    ],
                    axis=-1,
                ).astype(np.float32)
                out[y0:y1, x0:x1] = patch * (1.0 - intensity * 0.35) + data * intensity * 0.35
            else:
                out[y0:y1, x0:x1] = patch[..., [1, 2, 0]]
    return np.clip(out, 0.0, 1.0)


def _luma(frame: np.ndarray) -> np.ndarray:
    return frame @ np.array([0.299, 0.587, 0.114], dtype=np.float32)


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    aa = a.reshape(-1).astype(np.float64)
    bb = b.reshape(-1).astype(np.float64)
    aa -= aa.mean()
    bb -= bb.mean()
    denom = np.linalg.norm(aa) * np.linalg.norm(bb)
    return 0.0 if denom == 0.0 else float((aa @ bb) / denom)


def _centroid_x(frame: np.ndarray) -> float:
    luma = _luma(frame)
    mask = luma > 0.48
    assert mask.any()
    xs = np.nonzero(mask)[1]
    return float(xs.mean())


def test_source_bound_repair_tranche_has_visual_negative_motion_evidence() -> None:
    transforms = {
        "glitch_block": _glitch_block,
        "pixsort": _pixsort,
        "scanlines": _scanlines,
    }
    assert set(transforms) == LIVE_SURFACE_GLSL_SOURCE_BOUND_REPAIR_20260520_NODE_TYPES

    source_a = _moving_source(0)
    source_b = _moving_source(10)
    source_motion = float(np.mean(np.abs(source_b - source_a)))

    for name, transform in transforms.items():
        out_a = transform(source_a)
        out_b = transform(source_b)
        luma_a = _luma(out_a)

        assert float(np.mean(np.abs(out_b - out_a))) >= source_motion * 0.35, name
        assert _centroid_x(out_b) - _centroid_x(out_a) >= 8.0, name
        assert _corr(source_a, out_a) >= 0.70, name
        assert float(np.mean(np.abs(out_a - source_a))) <= 0.20, name
        assert float(luma_a.std()) >= 0.05, name
        assert float(np.mean(luma_a < 0.02)) <= 0.05, name
