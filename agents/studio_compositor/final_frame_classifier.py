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
    luma_mean: float
    luma_standard_deviation: float
    upstream_luma_standard_deviation: float | None
    upstream_luma_correlation: float | None
    checkerboard_fraction: float
    content_regions: int
    quadrant_weights: dict[str, float]
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def classify_final_frame(
    path: Path,
    *,
    upstream_path: Path | None = None,
    max_unclassified_black_fraction: float = 0.08,
    max_checkerboard_fraction: float = 0.05,
    max_uniform_gray_luma_std: float = 2.5,
    min_upstream_content_luma_std: float = 8.0,
    min_geometry_luma_correlation: float = 0.15,
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
    gray_values = list(gray.getdata())
    luma_mean, luma_std = _mean_and_std(gray_values)
    upstream_luma_std, upstream_luma_corr = _upstream_luma_stats(upstream_path, gray_values)
    dark_mask = [value <= 18 for value in gray_values]
    checkerboard_fraction = _checkerboard_fraction(gray)
    content_regions = _content_regions(dark_mask, gray.size[0], gray.size[1])
    quadrant_weights = _quadrant_weights(gray)

    reasons: list[str] = []
    if black_fraction > max_unclassified_black_fraction:
        reasons.append("unclassified_black_exceeds_threshold")
    if checkerboard_fraction > max_checkerboard_fraction:
        reasons.append("checkerboard_fallthrough_detected")
    if (
        18 < luma_mean < 245
        and luma_std <= max_uniform_gray_luma_std
        and (upstream_luma_std is None or upstream_luma_std >= min_upstream_content_luma_std)
    ):
        reasons.append("uniform_gray_final_egress_collapse")
    if content_regions == 0:
        reasons.append("no_content_regions")
    if (
        upstream_luma_std is not None
        and upstream_luma_std >= min_upstream_content_luma_std
        and luma_std >= max_uniform_gray_luma_std
        and upstream_luma_corr is not None
        and abs(upstream_luma_corr) < min_geometry_luma_correlation
    ):
        reasons.append("geometry_decorrelation_final_egress_collapse")

    return FinalFrameClassification(
        width=width,
        height=height,
        black_fraction=round(black_fraction, 6),
        luma_mean=round(luma_mean, 6),
        luma_standard_deviation=round(luma_std, 6),
        upstream_luma_standard_deviation=(
            round(upstream_luma_std, 6) if upstream_luma_std is not None else None
        ),
        upstream_luma_correlation=(
            round(upstream_luma_corr, 6) if upstream_luma_corr is not None else None
        ),
        checkerboard_fraction=round(checkerboard_fraction, 6),
        content_regions=content_regions,
        quadrant_weights=quadrant_weights,
        reasons=tuple(reasons),
    )


def _mean_and_std(values: list[int]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return mean, variance**0.5


def _upstream_luma_stats(
    path: Path | None, final_values: list[int]
) -> tuple[float | None, float | None]:
    if path is None:
        return None, None
    try:
        with Image.open(path) as image:
            gray = image.convert("L").resize((64, 36))
            upstream_values = list(gray.getdata())
            _, std = _mean_and_std(upstream_values)
            return std, _pearson(upstream_values, final_values)
    except OSError:
        return None, None


def _pearson(a: list[int], b: list[int]) -> float | None:
    if not a or len(a) != len(b):
        return None
    mean_a, std_a = _mean_and_std(a)
    mean_b, std_b = _mean_and_std(b)
    if std_a <= 1e-9 or std_b <= 1e-9:
        return None
    cov = sum((av - mean_a) * (bv - mean_b) for av, bv in zip(a, b, strict=True)) / len(a)
    return cov / (std_a * std_b)


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
