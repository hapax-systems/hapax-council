from __future__ import annotations

from pathlib import Path

from PIL import Image

from agents.studio_compositor.final_frame_classifier import classify_final_frame


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
