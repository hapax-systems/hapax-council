from __future__ import annotations

from pathlib import Path
from random import Random

from PIL import Image

from agents.studio_compositor.final_frame_classifier import (
    classify_final_frame,
    classify_final_frame_series,
)


def test_classifier_flags_unclassified_black_frame(tmp_path: Path) -> None:
    image_path = tmp_path / "black.jpg"
    Image.new("RGB", (64, 36), (0, 0, 0)).save(image_path)

    classification = classify_final_frame(image_path)

    assert classification.black_fraction == 1.0
    assert classification.content_regions == 0
    assert "unclassified_black_exceeds_threshold" in classification.reasons
    assert "no_content_regions" in classification.reasons


def test_classifier_flags_checkerboard_fallthrough(tmp_path: Path) -> None:
    image_path = tmp_path / "checker.png"
    image = Image.new("RGB", (64, 36), (0, 0, 0))
    pixels = image.load()
    for y in range(36):
        for x in range(64):
            pixels[x, y] = (255, 255, 255) if (x + y) % 2 == 0 else (0, 0, 0)
    image.save(image_path)

    classification = classify_final_frame(image_path)

    assert classification.checkerboard_fraction > 0.9
    assert "checkerboard_fallthrough_detected" in classification.reasons


def test_classifier_reports_quadrant_weights_for_content(tmp_path: Path) -> None:
    image_path = tmp_path / "content.png"
    image = Image.new("RGB", (64, 36), (0, 0, 0))
    pixels = image.load()
    for y in range(0, 18):
        for x in range(0, 32):
            pixels[x, y] = (200, 120, 60)
    image.save(image_path)

    classification = classify_final_frame(image_path)

    assert classification.content_regions == 1
    assert classification.quadrant_weights["LT"] == 1.0
    assert classification.quadrant_weights["RT"] == 0.0


def test_classifier_flags_uniform_grey_final_egress_with_live_upstream(
    tmp_path: Path,
) -> None:
    final_path = tmp_path / "final-grey.jpg"
    upstream_path = tmp_path / "upstream-content.jpg"
    Image.new("RGB", (64, 36), (128, 128, 128)).save(final_path)

    upstream = Image.new("RGB", (64, 36), (0, 0, 0))
    pixels = upstream.load()
    for y in range(4, 30):
        for x in range(8, 56):
            pixels[x, y] = (220, 120, 40)
    upstream.save(upstream_path)

    classification = classify_final_frame(final_path, upstream_path=upstream_path)

    assert classification.luma_standard_deviation <= 2.5
    assert classification.upstream_luma_standard_deviation is not None
    assert classification.upstream_luma_standard_deviation >= 8.0
    assert "uniform_gray_final_egress_collapse" in classification.reasons


def test_classifier_flags_geometry_destroying_noise_with_live_upstream(
    tmp_path: Path,
) -> None:
    final_path = tmp_path / "final-noise.png"
    upstream_path = tmp_path / "upstream-grid.png"
    upstream = Image.new("RGB", (128, 72), (0, 0, 0))
    upstream_pixels = upstream.load()
    for y in range(0, 72):
        for x in range(0, 128):
            if 16 <= x < 56 and 12 <= y < 36:
                upstream_pixels[x, y] = (230, 140, 40)
            elif 72 <= x < 112 and 36 <= y < 60:
                upstream_pixels[x, y] = (40, 180, 230)
    upstream.save(upstream_path)

    final = Image.new("RGB", (128, 72), (0, 0, 0))
    final_pixels = final.load()
    for y in range(72):
        for x in range(128):
            n = (x * 37 + y * 83 + ((x * y) % 97)) % 256
            final_pixels[x, y] = (n, (n * 5) % 256, (n * 11) % 256)
    final.save(final_path)

    classification = classify_final_frame(final_path, upstream_path=upstream_path)

    assert classification.upstream_luma_correlation is not None
    assert abs(classification.upstream_luma_correlation) < 0.15
    assert "geometry_decorrelation_final_egress_collapse" in classification.reasons


def test_series_classifier_flags_temporal_luma_pumping(tmp_path: Path) -> None:
    final_paths: list[Path] = []
    upstream_paths: list[Path] = []
    for index, scale in enumerate((0.95, 0.55, 0.96, 0.54, 0.95, 0.55)):
        upstream = _pattern_image()
        final = _scale_image(upstream, scale)
        upstream_path = tmp_path / f"upstream-{index}.png"
        final_path = tmp_path / f"final-{index}.png"
        upstream.save(upstream_path)
        final.save(final_path)
        upstream_paths.append(upstream_path)
        final_paths.append(final_path)

    classification = classify_final_frame_series(
        final_paths,
        upstream_paths=upstream_paths,
        require_upstream=True,
    )

    assert classification.luma_ratio_span is not None
    assert classification.luma_ratio_span > 0.18
    assert any(
        reason.startswith("final_pixel_proof:luma_ratio_span_exceeds_threshold")
        for reason in classification.reasons
    )
    assert any(
        reason.startswith("final_pixel_proof:luma_ratio_step_exceeds_threshold")
        for reason in classification.reasons
    )


def test_series_classifier_flags_geometry_collapse(tmp_path: Path) -> None:
    final_paths: list[Path] = []
    upstream_paths: list[Path] = []
    rng = Random(7)
    for index in range(6):
        upstream = _pattern_image()
        final = _noise_image(rng)
        upstream_path = tmp_path / f"upstream-{index}.png"
        final_path = tmp_path / f"final-{index}.png"
        upstream.save(upstream_path)
        final.save(final_path)
        upstream_paths.append(upstream_path)
        final_paths.append(final_path)

    classification = classify_final_frame_series(
        final_paths,
        upstream_paths=upstream_paths,
        require_upstream=True,
    )

    assert classification.edge_correlation_median is not None
    assert classification.edge_correlation_median < 0.45
    assert any(
        reason.startswith("final_pixel_proof:edge_correlation_median_below_threshold")
        for reason in classification.reasons
    )


def test_series_classifier_allows_stable_sparse_layout_with_brightness_shift(
    tmp_path: Path,
) -> None:
    final_paths: list[Path] = []
    upstream_paths: list[Path] = []
    for index in range(6):
        upstream = _sparse_layout_image()
        final = _scale_image(upstream, 1.65)
        upstream_path = tmp_path / f"upstream-{index}.png"
        final_path = tmp_path / f"final-{index}.png"
        upstream.save(upstream_path)
        final.save(final_path)
        upstream_paths.append(upstream_path)
        final_paths.append(final_path)

    classification = classify_final_frame_series(
        final_paths,
        upstream_paths=upstream_paths,
        require_upstream=True,
    )

    assert classification.black_fraction_max is not None
    assert classification.black_fraction_max > 0.08
    assert classification.content_region_min is not None
    assert classification.content_region_min > 0
    assert classification.luma_ratio_median is not None
    assert classification.luma_ratio_median > 1.35
    assert classification.reasons == ()


def _pattern_image() -> Image.Image:
    image = Image.new("RGB", (128, 72), (0, 0, 0))
    pixels = image.load()
    for y in range(72):
        for x in range(128):
            if 8 <= x < 58 and 8 <= y < 38:
                pixels[x, y] = (230, 150, 40)
            elif 70 <= x < 120 and 28 <= y < 66:
                pixels[x, y] = (40, 190, 220)
            elif (x // 9 + y // 7) % 3 == 0:
                pixels[x, y] = (90, 120, 70)
    return image


def _sparse_layout_image() -> Image.Image:
    image = Image.new("RGB", (128, 72), (0, 0, 0))
    pixels = image.load()
    for y in range(10, 36):
        for x in range(8, 58):
            pixels[x, y] = (210, 130, 45)
    for y in range(28, 64):
        for x in range(72, 120):
            pixels[x, y] = (40, 150, 210)
    return image


def _scale_image(image: Image.Image, scale: float) -> Image.Image:
    out = Image.new("RGB", image.size, (0, 0, 0))
    in_pixels = image.load()
    out_pixels = out.load()
    width, height = image.size
    for y in range(height):
        for x in range(width):
            r, g, b = in_pixels[x, y]
            out_pixels[x, y] = (
                min(255, int(r * scale)),
                min(255, int(g * scale)),
                min(255, int(b * scale)),
            )
    return out


def _noise_image(rng: Random) -> Image.Image:
    image = Image.new("RGB", (128, 72), (0, 0, 0))
    pixels = image.load()
    for y in range(72):
        for x in range(128):
            n = rng.randrange(256)
            pixels[x, y] = (n, (n * 5) % 256, (n * 11) % 256)
    return image
