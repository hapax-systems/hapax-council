"""Final-frame visual classifier for livestream egress proof images."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median

from PIL import Image

_ANALYSIS_SIZE = (64, 36)
_MAX_UNIFORM_LUMA_STDDEV = 3.0
_MIN_SERIES_FRAMES = 6
_MIN_PAIRED_FRAMES = 6
_MIN_UPSTREAM_LUMA = 5.0
_MIN_UPSTREAM_EDGE_MEAN = 2.0
_MIN_UPSTREAM_EDGE_STDDEV = 2.0


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


@dataclass(frozen=True)
class FinalFrameSeriesClassification:
    frame_count: int
    paired_frame_count: int
    upstream_content_frame_count: int
    black_fraction_max: float | None
    checkerboard_fraction_max: float | None
    uniform_frame_count: int
    content_region_min: int | None
    edge_correlation_median: float | None
    edge_correlation_min: float | None
    low_edge_correlation_frames: int
    luma_ratio_median: float | None
    luma_ratio_span: float | None
    max_luma_ratio_step: float | None
    reasons: tuple[str, ...]
    frames: tuple[dict[str, object], ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _FrameStats:
    path: str
    width: int
    height: int
    black_fraction: float
    checkerboard_fraction: float
    content_regions: int
    luma_mean: float
    luma_stddev: float
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

    gray = rgb.convert("L").resize(_ANALYSIS_SIZE)
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


def classify_final_frame_series(
    final_paths: Sequence[Path],
    *,
    upstream_paths: Sequence[Path] | None = None,
    ignored_rects: Sequence[tuple[int, int, int, int]] | None = None,
    ignored_masks: Sequence[Path] | None = None,
    require_upstream: bool = False,
    min_frame_count: int = _MIN_SERIES_FRAMES,
    min_paired_frame_count: int = _MIN_PAIRED_FRAMES,
    max_unclassified_black_fraction: float = 0.08,
    max_checkerboard_fraction: float = 0.05,
    min_luma_ratio_median: float = 0.25,
    max_luma_ratio_median: float = 4.0,
    max_luma_ratio_span: float = 0.18,
    max_luma_ratio_step: float = 0.12,
    min_edge_correlation_median: float = 0.45,
    min_edge_correlation_floor: float = 0.25,
    max_low_edge_correlation_frames: int = 1,
) -> FinalFrameSeriesClassification:
    """Classify a short proof-window series of final egress frames."""

    final_list = [Path(path) for path in final_paths]
    upstream_list = [Path(path) for path in (upstream_paths or ())]
    final_stats = [
        _analyze_frame(
            path,
            ignored_rects=ignored_rects,
            ignored_masks=ignored_masks,
            max_unclassified_black_fraction=max_unclassified_black_fraction,
            max_checkerboard_fraction=max_checkerboard_fraction,
        )
        for path in final_list
    ]

    paired_frame_count = min(len(final_list), len(upstream_list))
    luma_ratios: list[float] = []
    edge_correlations: list[float] = []
    upstream_content_frame_count = 0
    frame_payloads: list[dict[str, object]] = []

    for index, stats in enumerate(final_stats):
        frame_payload = stats.as_dict()
        if index < paired_frame_count:
            ratio, edge_correlation, upstream_has_content = _paired_frame_metrics(
                final_list[index],
                upstream_list[index],
                ignored_rects=ignored_rects,
                ignored_masks=ignored_masks,
            )
            if upstream_has_content:
                upstream_content_frame_count += 1
            if ratio is not None:
                luma_ratios.append(ratio)
                frame_payload["luma_ratio"] = round(ratio, 6)
            if edge_correlation is not None:
                edge_correlations.append(edge_correlation)
                frame_payload["edge_correlation"] = round(edge_correlation, 6)
        frame_payloads.append(frame_payload)

    black_values = [stats.black_fraction for stats in final_stats]
    checker_values = [stats.checkerboard_fraction for stats in final_stats]
    content_regions = [stats.content_regions for stats in final_stats]
    uniform_frame_count = sum(
        1 for stats in final_stats if "uniform_frame_detected" in stats.reasons
    )
    low_edge_count = sum(1 for value in edge_correlations if value < min_edge_correlation_floor)

    luma_ratio_median = _rounded_median(luma_ratios)
    luma_ratio_span = _rounded_span(luma_ratios)
    max_luma_step = _rounded_max_step(luma_ratios)
    edge_correlation_median = _rounded_median(edge_correlations)
    edge_correlation_min = round(min(edge_correlations), 6) if edge_correlations else None

    reasons: list[str] = []
    if len(final_stats) < min_frame_count:
        reasons.append(
            f"final_pixel_proof:insufficient_final_frames:{len(final_stats)}<{min_frame_count}"
        )
    if require_upstream and paired_frame_count < min_paired_frame_count:
        reasons.append(
            "final_pixel_proof:"
            f"insufficient_paired_frames:{paired_frame_count}<{min_paired_frame_count}"
        )
    if (
        black_values
        and max(black_values) > max_unclassified_black_fraction
        and (not content_regions or min(content_regions) == 0)
    ):
        reasons.append("final_pixel_proof:black_fraction_exceeds_threshold")
    if checker_values and max(checker_values) > max_checkerboard_fraction:
        reasons.append("final_pixel_proof:checkerboard_fallthrough_detected")
    if uniform_frame_count:
        reasons.append(f"final_pixel_proof:uniform_frames_detected:{uniform_frame_count}")
    if content_regions and min(content_regions) == 0:
        reasons.append("final_pixel_proof:no_content_regions")

    if require_upstream or luma_ratios:
        if len(luma_ratios) < min_paired_frame_count:
            reasons.append(
                "final_pixel_proof:"
                f"insufficient_luma_ratio_frames:{len(luma_ratios)}<{min_paired_frame_count}"
            )
        elif luma_ratio_median is not None and not (
            min_luma_ratio_median <= luma_ratio_median <= max_luma_ratio_median
        ):
            reasons.append(
                f"final_pixel_proof:luma_ratio_median_out_of_range:{luma_ratio_median:.3f}"
            )
        if luma_ratio_span is not None and luma_ratio_span > max_luma_ratio_span:
            reasons.append(
                "final_pixel_proof:"
                f"luma_ratio_span_exceeds_threshold:{luma_ratio_span:.3f}>"
                f"{max_luma_ratio_span:.3f}"
            )
        if max_luma_step is not None and max_luma_step > max_luma_ratio_step:
            reasons.append(
                "final_pixel_proof:"
                f"luma_ratio_step_exceeds_threshold:{max_luma_step:.3f}>"
                f"{max_luma_ratio_step:.3f}"
            )

    if require_upstream or edge_correlations:
        if upstream_content_frame_count and len(edge_correlations) < min_paired_frame_count:
            reasons.append(
                "final_pixel_proof:"
                f"insufficient_geometry_frames:{len(edge_correlations)}<{min_paired_frame_count}"
            )
        if (
            edge_correlation_median is not None
            and edge_correlation_median < min_edge_correlation_median
        ):
            reasons.append(
                "final_pixel_proof:"
                f"edge_correlation_median_below_threshold:{edge_correlation_median:.3f}<"
                f"{min_edge_correlation_median:.3f}"
            )
        if low_edge_count > max_low_edge_correlation_frames:
            reasons.append(
                "final_pixel_proof:"
                f"low_edge_correlation_frames:{low_edge_count}>{max_low_edge_correlation_frames}"
            )

    return FinalFrameSeriesClassification(
        frame_count=len(final_stats),
        paired_frame_count=paired_frame_count,
        upstream_content_frame_count=upstream_content_frame_count,
        black_fraction_max=round(max(black_values), 6) if black_values else None,
        checkerboard_fraction_max=round(max(checker_values), 6) if checker_values else None,
        uniform_frame_count=uniform_frame_count,
        content_region_min=min(content_regions) if content_regions else None,
        edge_correlation_median=edge_correlation_median,
        edge_correlation_min=edge_correlation_min,
        low_edge_correlation_frames=low_edge_count,
        luma_ratio_median=luma_ratio_median,
        luma_ratio_span=luma_ratio_span,
        max_luma_ratio_step=max_luma_step,
        reasons=tuple(dict.fromkeys(reasons)),
        frames=tuple(frame_payloads),
    )


def _analyze_frame(
    path: Path,
    *,
    ignored_rects: Sequence[tuple[int, int, int, int]] | None,
    ignored_masks: Sequence[Path] | None,
    max_unclassified_black_fraction: float,
    max_checkerboard_fraction: float,
) -> _FrameStats:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
    width, height = rgb.size
    gray = rgb.convert("L").resize(_ANALYSIS_SIZE)
    valid_mask = _valid_mask(
        _ANALYSIS_SIZE,
        original_size=(width, height),
        ignored_rects=ignored_rects,
        ignored_masks=ignored_masks,
    )
    values = list(gray.getdata())
    valid_values = [value for value, valid in zip(values, valid_mask, strict=True) if valid]
    total = len(valid_values)
    black_fraction = sum(1 for value in valid_values if value <= 12) / total if total else 1.0
    checkerboard_fraction = _checkerboard_fraction(gray, valid_mask=valid_mask)
    dark_mask = [value <= 18 or not valid for value, valid in zip(values, valid_mask, strict=True)]
    content_regions = _content_regions(dark_mask, gray.size[0], gray.size[1])
    luma_mean, luma_stddev = _mean_and_std(valid_values)

    reasons: list[str] = []
    if black_fraction > max_unclassified_black_fraction and content_regions == 0:
        reasons.append("unclassified_black_exceeds_threshold")
    if checkerboard_fraction > max_checkerboard_fraction:
        reasons.append("checkerboard_fallthrough_detected")
    if luma_stddev <= _MAX_UNIFORM_LUMA_STDDEV:
        reasons.append("uniform_frame_detected")
    if content_regions == 0:
        reasons.append("no_content_regions")

    return _FrameStats(
        path=str(path),
        width=width,
        height=height,
        black_fraction=round(black_fraction, 6),
        checkerboard_fraction=round(checkerboard_fraction, 6),
        content_regions=content_regions,
        luma_mean=round(luma_mean, 6),
        luma_stddev=round(luma_stddev, 6),
        reasons=tuple(reasons),
    )


def _paired_frame_metrics(
    final_path: Path,
    upstream_path: Path,
    *,
    ignored_rects: Sequence[tuple[int, int, int, int]] | None,
    ignored_masks: Sequence[Path] | None,
) -> tuple[float | None, float | None, bool]:
    with Image.open(final_path) as final_image:
        final_rgb = final_image.convert("RGB")
    with Image.open(upstream_path) as upstream_image:
        upstream_rgb = upstream_image.convert("RGB")
    final_gray = final_rgb.convert("L").resize(_ANALYSIS_SIZE)
    upstream_gray = upstream_rgb.convert("L").resize(_ANALYSIS_SIZE)
    valid_mask = _valid_mask(
        _ANALYSIS_SIZE,
        original_size=final_rgb.size,
        ignored_rects=ignored_rects,
        ignored_masks=ignored_masks,
    )

    final_values = list(final_gray.getdata())
    upstream_values = list(upstream_gray.getdata())
    valid_final = [value for value, valid in zip(final_values, valid_mask, strict=True) if valid]
    valid_upstream = [
        value for value, valid in zip(upstream_values, valid_mask, strict=True) if valid
    ]
    final_luma, _ = _mean_and_std(valid_final)
    upstream_luma, _ = _mean_and_std(valid_upstream)
    ratio = final_luma / upstream_luma if upstream_luma > _MIN_UPSTREAM_LUMA else None

    final_edges, upstream_edges = _edge_pairs(final_gray, upstream_gray, valid_mask)
    upstream_edge_mean, upstream_edge_stddev = _mean_and_std(upstream_edges)
    upstream_has_geometry = (
        upstream_edge_mean >= _MIN_UPSTREAM_EDGE_MEAN
        or upstream_edge_stddev >= _MIN_UPSTREAM_EDGE_STDDEV
    )
    if not upstream_has_geometry:
        return ratio, None, bool(ratio is not None)
    edge_correlation = _correlation(final_edges, upstream_edges)
    return ratio, edge_correlation, True


def _mean_and_std(values: Sequence[float | int]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(float(value) for value in values) / len(values)
    variance = sum((float(value) - mean) ** 2 for value in values) / len(values)
    return mean, variance**0.5


def _upstream_luma_stats(
    path: Path | None, final_values: list[int]
) -> tuple[float | None, float | None]:
    if path is None:
        return None, None
    try:
        with Image.open(path) as image:
            gray = image.convert("L").resize(_ANALYSIS_SIZE)
            upstream_values = list(gray.getdata())
            _, std = _mean_and_std(upstream_values)
            return std, _pearson(upstream_values, final_values)
    except OSError:
        return None, None


def _pearson(a: Sequence[float | int], b: Sequence[float | int]) -> float | None:
    if not a or len(a) != len(b):
        return None
    mean_a, std_a = _mean_and_std(a)
    mean_b, std_b = _mean_and_std(b)
    if std_a <= 1e-9 or std_b <= 1e-9:
        return None
    cov = sum(
        (float(av) - mean_a) * (float(bv) - mean_b) for av, bv in zip(a, b, strict=True)
    ) / len(a)
    return cov / (std_a * std_b)


def _checkerboard_fraction(gray: Image.Image, *, valid_mask: Sequence[bool] | None = None) -> float:
    width, height = gray.size
    values = list(gray.getdata())
    alternating_blocks = 0
    blocks = 0
    for y in range(height - 1):
        for x in range(width - 1):
            idx = y * width + x
            down_idx = (y + 1) * width + x
            if valid_mask is not None and not (
                valid_mask[idx]
                and valid_mask[idx + 1]
                and valid_mask[down_idx]
                and valid_mask[down_idx + 1]
            ):
                continue
            top_left = values[idx]
            top_right = values[idx + 1]
            bottom_left = values[down_idx]
            bottom_right = values[down_idx + 1]
            blocks += 1
            if _is_checkerboard_block(top_left, top_right, bottom_left, bottom_right):
                alternating_blocks += 1
    return alternating_blocks / blocks if blocks else 0.0


def _is_checkerboard_block(
    top_left: int,
    top_right: int,
    bottom_left: int,
    bottom_right: int,
) -> bool:
    """Return true for local 2x2 parity, not ordinary content edges."""
    values = (top_left, top_right, bottom_left, bottom_right)
    if max(values) - min(values) < 24:
        return False
    return (
        abs(top_left - bottom_right) <= 24
        and abs(top_right - bottom_left) <= 24
        and min(
            abs(top_left - top_right),
            abs(top_left - bottom_left),
            abs(bottom_right - top_right),
            abs(bottom_right - bottom_left),
        )
        >= 24
    )


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


def _quadrant_weights(
    gray: Image.Image, valid_mask: Sequence[bool] | None = None
) -> dict[str, float]:
    width, height = gray.size
    values = list(gray.getdata())
    counts = {"LT": 0, "RT": 0, "LB": 0, "RB": 0}
    total = 0
    for y in range(height):
        for x in range(width):
            idx = y * width + x
            if valid_mask is not None and not valid_mask[idx]:
                continue
            if values[idx] <= 18:
                continue
            key = ("L" if x < width / 2 else "R") + ("T" if y < height / 2 else "B")
            counts[key] += 1
            total += 1
    if total == 0:
        return {key: 0.0 for key in counts}
    return {key: round(value / total, 6) for key, value in counts.items()}


def _valid_mask(
    size: tuple[int, int],
    *,
    original_size: tuple[int, int],
    ignored_rects: Sequence[tuple[int, int, int, int]] | None,
    ignored_masks: Sequence[Path] | None,
) -> list[bool]:
    width, height = size
    valid = [True] * (width * height)
    original_w, original_h = original_size
    for x, y, rect_w, rect_h in ignored_rects or ():
        left = max(0, int(x * width / max(original_w, 1)))
        top = max(0, int(y * height / max(original_h, 1)))
        right = min(width, int((x + rect_w) * width / max(original_w, 1)))
        bottom = min(height, int((y + rect_h) * height / max(original_h, 1)))
        for yy in range(top, bottom):
            for xx in range(left, right):
                valid[yy * width + xx] = False

    for mask_path in ignored_masks or ():
        with Image.open(mask_path) as mask_image:
            mask = mask_image.convert("L").resize(size)
        for idx, value in enumerate(mask.getdata()):
            if value >= 128:
                valid[idx] = False
    return valid


def _edge_pairs(
    final_gray: Image.Image,
    upstream_gray: Image.Image,
    valid_mask: Sequence[bool],
) -> tuple[list[float], list[float]]:
    width, height = final_gray.size
    final_values = list(final_gray.getdata())
    upstream_values = list(upstream_gray.getdata())
    final_edges: list[float] = []
    upstream_edges: list[float] = []
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            idx = y * width + x
            neighbor_indices = (idx - 1, idx + 1, idx - width, idx + width)
            if not valid_mask[idx] or not all(valid_mask[nidx] for nidx in neighbor_indices):
                continue
            final_edges.append(_edge_at(final_values, idx, width))
            upstream_edges.append(_edge_at(upstream_values, idx, width))
    return final_edges, upstream_edges


def _edge_at(values: Sequence[int], idx: int, width: int) -> float:
    horizontal = abs(values[idx + 1] - values[idx - 1])
    vertical = abs(values[idx + width] - values[idx - width])
    return float(horizontal + vertical)


def _correlation(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) < 2 or len(right) < 2 or len(left) != len(right):
        return None
    left_mean, left_stddev = _mean_and_std(left)
    right_mean, right_stddev = _mean_and_std(right)
    if left_stddev <= 0.0 or right_stddev <= 0.0:
        return 0.0
    covariance = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right, strict=True)
    ) / len(left)
    return round(max(-1.0, min(1.0, covariance / (left_stddev * right_stddev))), 6)


def _rounded_median(values: Sequence[float]) -> float | None:
    return round(float(median(values)), 6) if values else None


def _rounded_span(values: Sequence[float]) -> float | None:
    return round(max(values) - min(values), 6) if values else None


def _rounded_max_step(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    return round(
        max(abs(current - previous) for previous, current in zip(values, values[1:], strict=False)),
        6,
    )
