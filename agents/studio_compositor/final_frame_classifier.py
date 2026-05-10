"""Final-frame visual classifier for livestream egress proof images."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image


@dataclass(frozen=True)
class FinalFrameClassification:
    width: int
    height: int
    black_fraction: float
    checkerboard_fraction: float
    content_regions: int
    quadrant_weights: dict[str, float]
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def classify_final_frame(
    path: Path,
    *,
    max_unclassified_black_fraction: float = 0.08,
    max_checkerboard_fraction: float = 0.05,
) -> FinalFrameClassification:
    """Classify a proof image for black/fallthrough and content distribution."""

    with Image.open(path) as image:
        rgb = image.convert("RGB")
    width, height = rgb.size
    pixels = list(rgb.getdata())
    total = len(pixels)
    black_pixels = sum(1 for r, g, b in pixels if r <= 12 and g <= 12 and b <= 12)
    black_fraction = black_pixels / total if total else 1.0

    gray = rgb.convert("L").resize((64, 36))
    dark_mask = [value <= 18 for value in gray.getdata()]
    checkerboard_fraction = _checkerboard_fraction(gray)
    content_regions = _content_regions(dark_mask, gray.size[0], gray.size[1])
    quadrant_weights = _quadrant_weights(gray)

    reasons: list[str] = []
    if black_fraction > max_unclassified_black_fraction:
        reasons.append("unclassified_black_exceeds_threshold")
    if checkerboard_fraction > max_checkerboard_fraction:
        reasons.append("checkerboard_fallthrough_detected")
    if content_regions == 0:
        reasons.append("no_content_regions")

    return FinalFrameClassification(
        width=width,
        height=height,
        black_fraction=round(black_fraction, 6),
        checkerboard_fraction=round(checkerboard_fraction, 6),
        content_regions=content_regions,
        quadrant_weights=quadrant_weights,
        reasons=tuple(reasons),
    )


def _checkerboard_fraction(gray: Image.Image) -> float:
    width, height = gray.size
    values = list(gray.getdata())
    toggles = 0
    edges = 0
    for y in range(height):
        for x in range(width):
            current = values[y * width + x] >= 128
            if x + 1 < width:
                toggles += current != (values[y * width + x + 1] >= 128)
                edges += 1
            if y + 1 < height:
                toggles += current != (values[(y + 1) * width + x] >= 128)
                edges += 1
    return toggles / edges if edges else 0.0


def _content_regions(dark_mask: list[bool], width: int, height: int) -> int:
    visited = [False] * len(dark_mask)
    regions = 0
    for idx, is_dark in enumerate(dark_mask):
        if is_dark or visited[idx]:
            continue
        regions += 1
        visited[idx] = True
        queue: deque[int] = deque([idx])
        while queue:
            current = queue.popleft()
            x = current % width
            y = current // width
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if nx < 0 or ny < 0 or nx >= width or ny >= height:
                    continue
                nidx = ny * width + nx
                if visited[nidx] or dark_mask[nidx]:
                    continue
                visited[nidx] = True
                queue.append(nidx)
    return regions


def _quadrant_weights(gray: Image.Image) -> dict[str, float]:
    width, height = gray.size
    values = list(gray.getdata())
    counts = {"LT": 0, "RT": 0, "LB": 0, "RB": 0}
    total = 0
    for y in range(height):
        for x in range(width):
            if values[y * width + x] <= 18:
                continue
            key = ("L" if x < width / 2 else "R") + ("T" if y < height / 2 else "B")
            counts[key] += 1
            total += 1
    if total == 0:
        return {key: 0.0 for key in counts}
    return {key: round(value / total, 6) for key, value in counts.items()}
