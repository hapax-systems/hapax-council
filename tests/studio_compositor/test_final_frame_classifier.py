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
