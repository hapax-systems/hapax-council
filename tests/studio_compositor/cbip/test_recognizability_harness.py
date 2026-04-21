"""Tests for cbip.recognizability_harness.

Spec §4 of `docs/superpowers/specs/2026-04-21-cbip-phase-1-design.md`.
"""

from __future__ import annotations

import shutil

import pytest
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from agents.studio_compositor.cbip.recognizability_harness import (
    CoverShape,
    HarnessResult,
    MetricResult,
    Severity,
    _character_accuracy,
    _levenshtein,
    edge_iou_sobel,
    evaluate,
    perceptual_hash_distance,
)

_TESSERACT_AVAILABLE = shutil.which("tesseract") is not None


def _make_geometric_cover(
    text: str = "ACID TRAX", size: tuple[int, int] = (400, 400)
) -> Image.Image:
    """Synthetic high-contrast cover with bold typography."""
    img = Image.new("RGB", size, (10, 10, 30))
    draw = ImageDraw.Draw(img)
    draw.rectangle((20, 20, size[0] - 20, size[1] - 20), outline=(220, 220, 240), width=4)
    try:
        font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", 56)
    except OSError:
        font = ImageFont.load_default()
    draw.text((40, size[1] // 2 - 40), text, fill=(240, 240, 255), font=font)
    return img


# ── Helpers ──────────────────────────────────────────────────────────────


def test_levenshtein_basic() -> None:
    assert _levenshtein("kitten", "sitting") == 3
    assert _levenshtein("", "abc") == 3
    assert _levenshtein("abc", "") == 3
    assert _levenshtein("same", "same") == 0


def test_character_accuracy_perfect() -> None:
    assert _character_accuracy("ACID TRAX", "ACID TRAX") == 1.0


def test_character_accuracy_empty_expected() -> None:
    assert _character_accuracy("anything", "") == 1.0


def test_character_accuracy_empty_observed() -> None:
    assert _character_accuracy("", "ACID TRAX") == 0.0


def test_character_accuracy_case_insensitive() -> None:
    assert _character_accuracy("acid trax", "ACID TRAX") == 1.0


def test_character_accuracy_partial() -> None:
    """Single-char drop in a 9-char string → ~88 % similarity."""
    score = _character_accuracy("ACI TRAX", "ACID TRAX")
    assert 0.85 <= score < 0.95


# ── Perceptual hash ─────────────────────────────────────────────────────


def test_perceptual_hash_identical_images_zero_distance() -> None:
    img = _make_geometric_cover()
    assert perceptual_hash_distance(img, img) == 0


def test_perceptual_hash_blur_within_invariant() -> None:
    """A mild blur preserves perceptual identity."""
    img = _make_geometric_cover()
    blurred = img.filter(ImageFilter.GaussianBlur(radius=1.0))
    assert perceptual_hash_distance(img, blurred) <= 8


def test_perceptual_hash_inverted_image_large_distance() -> None:
    """Inverting all colors should drift the perceptual hash heavily."""
    from PIL import ImageOps

    img = _make_geometric_cover()
    inverted = ImageOps.invert(img.convert("RGB"))
    assert perceptual_hash_distance(img, inverted) > 8


# ── Edge IoU ────────────────────────────────────────────────────────────


def test_edge_iou_identical_images_one() -> None:
    img = _make_geometric_cover()
    assert edge_iou_sobel(img, img) == pytest.approx(1.0, abs=1e-9)


def test_edge_iou_blur_preserves_majority() -> None:
    img = _make_geometric_cover()
    blurred = img.filter(ImageFilter.GaussianBlur(radius=1.0))
    iou = edge_iou_sobel(img, blurred)
    # mild blur should keep most edges; geometric threshold is 0.65.
    assert iou >= 0.50


def test_edge_iou_completely_different() -> None:
    """Solid red vs solid blue: zero edges in either → degenerate 1.0 OK."""
    red = Image.new("RGB", (200, 200), (255, 0, 0))
    blue = Image.new("RGB", (200, 200), (0, 0, 255))
    iou = edge_iou_sobel(red, blue)
    # both have no edges → IoU is degenerate; harness short-circuits to 1.0
    assert iou == pytest.approx(1.0, abs=1e-9)


# ── evaluate() integration ──────────────────────────────────────────────


def test_evaluate_identical_images_invariants_pass() -> None:
    """Phase-0 disposition: enhanced == original → invariants must pass."""
    img = _make_geometric_cover()
    result = evaluate(img, img)
    assert isinstance(result, HarnessResult)
    assert result.invariants_passed
    assert result.cover_shape is CoverShape.GEOMETRIC


def test_evaluate_records_phash_metric() -> None:
    img = _make_geometric_cover()
    result = evaluate(img, img)
    phash = next(m for m in result.metrics if m.name == "perceptual_hash_distance")
    assert phash.value == 0.0
    assert phash.passed
    assert phash.severity is Severity.INVARIANT


def test_evaluate_skips_ocr_without_expected_title() -> None:
    img = _make_geometric_cover()
    result = evaluate(img, img)
    names = {m.name for m in result.metrics}
    assert "ocr_title_accuracy" not in names


@pytest.mark.skipif(not _TESSERACT_AVAILABLE, reason="tesseract not installed")
def test_evaluate_includes_ocr_when_title_provided() -> None:
    img = _make_geometric_cover("ACID TRAX")
    result = evaluate(img, img, expected_title="ACID TRAX")
    ocr = next((m for m in result.metrics if m.name == "ocr_title_accuracy"), None)
    assert ocr is not None
    assert ocr.severity is Severity.INVARIANT


def test_evaluate_records_quality_metrics_below_invariant_severity() -> None:
    img = _make_geometric_cover()
    result = evaluate(img, img)
    quality_names = {m.name for m in result.metrics if m.severity is Severity.QUALITY}
    assert "palette_delta_e" in quality_names
    assert any(n.startswith("edge_iou_sobel_") for n in quality_names)


def test_evaluate_quality_metric_failure_doesnt_fail_invariants() -> None:
    """A blown delta-E must NOT make invariants_passed flip to False."""
    # Construct a result with a forced quality failure.
    metric = MetricResult(
        name="palette_delta_e",
        value=999.0,
        threshold=40.0,
        passed=False,
        severity=Severity.QUALITY,
    )
    invariant_pass = MetricResult(
        name="perceptual_hash_distance",
        value=0.0,
        threshold=8.0,
        passed=True,
        severity=Severity.INVARIANT,
    )
    result = HarnessResult(metrics=(metric, invariant_pass), cover_shape=CoverShape.GEOMETRIC)
    assert result.invariants_passed is True
    assert result.all_passed is False
    failures = result.failures
    assert len(failures) == 1
    assert failures[0].name == "palette_delta_e"


def test_evaluate_invariant_failure_blocks() -> None:
    metric = MetricResult(
        name="perceptual_hash_distance",
        value=999.0,
        threshold=8.0,
        passed=False,
        severity=Severity.INVARIANT,
    )
    result = HarnessResult(metrics=(metric,), cover_shape=CoverShape.GEOMETRIC)
    assert result.invariants_passed is False


def test_evaluate_uses_clip_scorer_when_supplied() -> None:
    img = _make_geometric_cover()
    calls: list[tuple] = []

    def fake_clip(orig, enh):
        calls.append((orig, enh))
        return 0.9

    result = evaluate(img, img, clip_scorer=fake_clip)
    assert len(calls) == 1
    clip_metric = next((m for m in result.metrics if m.name == "clip_cosine"), None)
    assert clip_metric is not None
    assert clip_metric.value == 0.9
    assert clip_metric.passed


def test_evaluate_clip_failure_warns_only() -> None:
    img = _make_geometric_cover()

    def below_threshold(orig, enh):
        return 0.5

    result = evaluate(img, img, clip_scorer=below_threshold)
    clip_metric = next(m for m in result.metrics if m.name == "clip_cosine")
    assert clip_metric.severity is Severity.QUALITY
    assert clip_metric.passed is False
    # quality failure does not block invariants
    assert result.invariants_passed is True


def test_evaluate_human_id_rate_records_invariant() -> None:
    img = _make_geometric_cover()
    result = evaluate(img, img, human_id_rate=0.85)
    hi = next(m for m in result.metrics if m.name == "human_identification_rate")
    assert hi.severity is Severity.INVARIANT
    assert hi.value == 0.85
    assert hi.passed


def test_evaluate_human_id_below_threshold_fails_invariant() -> None:
    img = _make_geometric_cover()
    result = evaluate(img, img, human_id_rate=0.7)
    assert result.invariants_passed is False


def test_evaluate_abstract_uses_lower_edge_threshold() -> None:
    img = _make_geometric_cover()
    result = evaluate(img, img, cover_shape=CoverShape.ABSTRACT)
    edge = next(m for m in result.metrics if m.name.startswith("edge_iou_sobel_"))
    assert edge.name.endswith("abstract")
    assert edge.threshold == pytest.approx(0.50)


def test_evaluate_geometric_uses_higher_edge_threshold() -> None:
    img = _make_geometric_cover()
    result = evaluate(img, img, cover_shape=CoverShape.GEOMETRIC)
    edge = next(m for m in result.metrics if m.name.startswith("edge_iou_sobel_"))
    assert edge.name.endswith("geometric")
    assert edge.threshold == pytest.approx(0.65)
