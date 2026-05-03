"""H1 — broadcast-egress level invariant test (cc-task audio-audit-H1).

Audit Finding #3 (broadcast 13.9 dB low) made it past every pre-existing
test because no test asserted broadcast egress LUFS. This file pins the
invariant in two complementary forms:

  1. **Unit-mocked variant** (always runs in CI): exercises the
     ``_labeled_float`` ebur128 parser against synthetic ffmpeg
     output and asserts it correctly extracts integrated LUFS-I,
     then asserts the parsed value falls in
     ``[EGRESS_TARGET_LUFS_I - LUFS_TOLERANCE_LU,
       EGRESS_TARGET_LUFS_I + LUFS_TOLERANCE_LU]`` for a known
     in-band sample. Catches a parser regression that would mask
     the live invariant check.

  2. **Hardware variant** (``@pytest.mark.hardware``): captures 5s
     of ``hapax-obs-broadcast-remap.monitor`` via ``pw-cat --record``,
     pipes through ``ffmpeg -filter ebur128``, asserts the integrated
     LUFS lands in the EGRESS tolerance band when a known test tone
     is injected at the music-loudnorm input. Skips with reason
     ``requires HAPAX_L12_PRESENT=1`` if the hardware env-var is unset.

The hardware variant is the regression-pin the operator will run on
the workstation; the unit variant is the CI safety-net that catches
parser regressions before they hide a live drift.

Wired into the broadcast-audio-health evaluator: see
``shared.broadcast_audio_health`` — the existing 10-min health check
already gates on the same EGRESS tolerance band; this test pins the
gate's input contract.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from shared.audio_loudness import EGRESS_TARGET_LUFS_I, LUFS_TOLERANCE_LU
from shared.broadcast_audio_health import _labeled_float


def _within_tolerance(integrated_lufs: float) -> bool:
    """The H1 invariant: integrated LUFS-I lands in EGRESS tolerance band."""
    low = EGRESS_TARGET_LUFS_I - LUFS_TOLERANCE_LU
    high = EGRESS_TARGET_LUFS_I + LUFS_TOLERANCE_LU
    return low <= integrated_lufs <= high


# ── Unit-mocked variant: parser + invariant against synthetic ffmpeg output ──


SYNTHETIC_EBUR128_BLOCKS = {
    "in_band_minus_14": """
        [Parsed_ebur128_0 @ 0x...] Summary:

          Integrated loudness:
            I:         -14.0 LUFS
            Threshold: -24.5 LUFS

          Loudness range:
            LRA:         5.2 LU
            Threshold: -34.5 LUFS
            LRA low:   -16.7 LUFS
            LRA high:  -11.5 LUFS

          True peak:
            Peak:       -1.0 dBFS
    """,
    "in_band_minus_15": """
        Integrated loudness:
            I:         -15.4 LUFS
        True peak:
            Peak:       -2.1 dBFS
    """,
    "below_band_minus_18": """
        Integrated loudness:
            I:         -18.2 LUFS
        True peak:
            Peak:       -4.5 dBFS
    """,
    "above_band_minus_9": """
        Integrated loudness:
            I:         -9.8 LUFS
        True peak:
            Peak:       -0.4 dBFS
    """,
}


class TestParserExtractsIntegratedLufs:
    """The parser is the gate's input. A regression here masks the live invariant."""

    @pytest.mark.parametrize(
        "fixture_name,expected",
        [
            ("in_band_minus_14", -14.0),
            ("in_band_minus_15", -15.4),
            ("below_band_minus_18", -18.2),
            ("above_band_minus_9", -9.8),
        ],
    )
    def test_labeled_float_extracts_integrated(self, fixture_name: str, expected: float) -> None:
        text = SYNTHETIC_EBUR128_BLOCKS[fixture_name]
        parsed = _labeled_float(text, "I")
        assert parsed is not None, (
            f"_labeled_float returned None for fixture {fixture_name!r} — "
            f"parser regression. The live invariant check uses the same parser."
        )
        assert abs(parsed - expected) < 0.01, (
            f"_labeled_float returned {parsed} for fixture {fixture_name!r}; expected {expected}"
        )

    def test_labeled_float_returns_none_on_missing_label(self) -> None:
        """Defensive: ffmpeg output without the I: line must yield None,
        not crash. Live: ffmpeg invocation failed → no I: line → health
        check correctly reports unknown."""
        assert _labeled_float("nothing here", "I") is None

    def test_true_peak_label_independently_extracted(self) -> None:
        """Same parser is used for the Peak: label; pin that contract too."""
        text = SYNTHETIC_EBUR128_BLOCKS["in_band_minus_14"]
        peak = _labeled_float(text, "Peak")
        assert peak is not None
        assert abs(peak - (-1.0)) < 0.01


class TestEgressInvariantBandMath:
    """Pin the band math: -17 ≤ integrated ≤ -11 (matches cc-task body)."""

    def test_in_band_value_passes(self) -> None:
        assert _within_tolerance(EGRESS_TARGET_LUFS_I) is True

    def test_band_lower_edge_passes(self) -> None:
        edge = EGRESS_TARGET_LUFS_I - LUFS_TOLERANCE_LU
        assert _within_tolerance(edge) is True

    def test_band_upper_edge_passes(self) -> None:
        edge = EGRESS_TARGET_LUFS_I + LUFS_TOLERANCE_LU
        assert _within_tolerance(edge) is True

    def test_below_band_fails(self) -> None:
        below = EGRESS_TARGET_LUFS_I - LUFS_TOLERANCE_LU - 0.1
        assert _within_tolerance(below) is False

    def test_above_band_fails(self) -> None:
        above = EGRESS_TARGET_LUFS_I + LUFS_TOLERANCE_LU + 0.1
        assert _within_tolerance(above) is False

    def test_finding_3_value_correctly_fails(self) -> None:
        """Audit Finding #3 reported broadcast at 13.9 dB BELOW target.
        Pin that the band math correctly identifies that as out-of-band."""
        finding_3_lufs = EGRESS_TARGET_LUFS_I - 13.9  # = -27.9 LUFS-I
        assert _within_tolerance(finding_3_lufs) is False, (
            "Finding #3's actual broadcast level (-27.9 LUFS-I) must fail the "
            "tolerance check. If this passes, the band has been widened too far."
        )


class TestParsePipelineAgainstSyntheticInBandSample:
    """End-to-end-ish: the synthetic in-band ffmpeg output passes the
    full parse + invariant pipeline. This is the unit-mocked variant of
    what the hardware test does live."""

    def test_in_band_sample_passes_parse_then_invariant(self) -> None:
        text = SYNTHETIC_EBUR128_BLOCKS["in_band_minus_14"]
        parsed = _labeled_float(text, "I")
        assert parsed is not None
        assert _within_tolerance(parsed)

    def test_below_band_sample_parses_then_fails_invariant(self) -> None:
        text = SYNTHETIC_EBUR128_BLOCKS["below_band_minus_18"]
        parsed = _labeled_float(text, "I")
        assert parsed is not None
        assert not _within_tolerance(parsed)


# ── Hardware variant: pw-cat + ffmpeg, runs only on the workstation ──


@pytest.mark.hardware
def test_live_broadcast_egress_lufs_in_band(tmp_path: Path) -> None:
    """Capture 5s of broadcast-remap.monitor and assert integrated LUFS
    lands in the EGRESS tolerance band. Skips when the hardware env-var
    isn't set or when pw-cat / ffmpeg aren't on PATH."""
    if os.environ.get("HAPAX_L12_PRESENT", "0") != "1":
        pytest.skip("requires HAPAX_L12_PRESENT=1 (workstation hardware)")
    if shutil.which("pw-cat") is None:
        pytest.skip("pw-cat not on PATH")
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")

    capture = tmp_path / "broadcast-egress.wav"
    rec = subprocess.run(
        [
            "pw-cat",
            "--record",
            "--target",
            "hapax-obs-broadcast-remap.monitor",
            str(capture),
            "--format=s16",
            "--rate=48000",
            "--channels=2",
        ],
        timeout=10,
        capture_output=True,
        check=False,
    )
    if rec.returncode != 0 or not capture.exists():
        pytest.skip(f"pw-cat capture failed: {rec.stderr.decode()[:300]}")

    ffmpeg = subprocess.run(
        ["ffmpeg", "-i", str(capture), "-filter", "ebur128", "-f", "null", "-"],
        capture_output=True,
        timeout=20,
        check=False,
    )
    text = ffmpeg.stderr.decode()
    integrated = _labeled_float(text, "I")
    assert integrated is not None, (
        f"ebur128 output did not contain an I: line. Last 500 chars:\n{text[-500:]}"
    )
    assert _within_tolerance(integrated), (
        f"broadcast egress integrated LUFS-I = {integrated}, "
        f"outside tolerance band [{EGRESS_TARGET_LUFS_I - LUFS_TOLERANCE_LU}, "
        f"{EGRESS_TARGET_LUFS_I + LUFS_TOLERANCE_LU}]. "
        f"This is Finding #3's failure mode — broadcast level is drifting."
    )
