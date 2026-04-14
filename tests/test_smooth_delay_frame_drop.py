"""Delta drop #29 F / cam-stability rollup Ring 1 item F regression pins.

Before this fix, ``smooth_delay.py`` ran ``gldownload`` at the 30fps
input rate even though the downstream ``videorate`` dropped to 2fps
— every frame paid the full 1920×1080×4 = 8.3 MB PCIe transfer,
wasting ~250 MB/s of GPU→CPU bandwidth. Fix: a pad probe on
``gldownload``'s sink pad that drops frames BEFORE they cross the
bus, using the same ``OUTPUT_FPS`` target as the downstream rate.

These pins lock in:
1. The ``should_pass_gldownload`` pure function enforces the
   1/fps minimum interval.
2. Edge cases: first frame, exactly at the interval boundary, well
   after the boundary, zero/negative fps.
"""

from __future__ import annotations

from agents.studio_compositor.smooth_delay import (
    OUTPUT_FPS,
    should_pass_gldownload,
)


class TestShouldPassGldownload:
    def test_first_frame_passes(self) -> None:
        """When last_pass_ts=0 (never passed), the first buffer must pass."""
        assert should_pass_gldownload(now_ts=100.0, last_pass_ts=0.0) is True

    def test_second_frame_within_interval_drops(self) -> None:
        """At 2fps (0.5s interval), a second frame 0.1s after the first
        must be dropped."""
        assert should_pass_gldownload(now_ts=100.1, last_pass_ts=100.0) is False

    def test_second_frame_at_interval_boundary_passes(self) -> None:
        """At exactly the interval boundary, the next frame passes."""
        assert should_pass_gldownload(now_ts=100.5, last_pass_ts=100.0) is True

    def test_second_frame_well_after_boundary_passes(self) -> None:
        """Several seconds later, definitely passes."""
        assert should_pass_gldownload(now_ts=103.0, last_pass_ts=100.0) is True

    def test_custom_fps_8hz(self) -> None:
        """At 8fps, the interval is 0.125s."""
        assert should_pass_gldownload(100.10, 100.0, fps=8.0) is False
        assert should_pass_gldownload(100.125, 100.0, fps=8.0) is True
        assert should_pass_gldownload(100.20, 100.0, fps=8.0) is True

    def test_zero_fps_always_passes(self) -> None:
        """Degenerate: fps=0 means no rate limiting, every frame passes."""
        assert should_pass_gldownload(100.0, 99.999, fps=0.0) is True

    def test_negative_fps_always_passes(self) -> None:
        """Defensive: fps<0 same as fps=0."""
        assert should_pass_gldownload(100.0, 99.999, fps=-1.0) is True

    def test_default_fps_matches_output_fps_constant(self) -> None:
        """The default ``fps`` parameter must match the OUTPUT_FPS module
        constant so the probe and the downstream videorate agree."""
        # Call without fps → uses OUTPUT_FPS default
        result_default = should_pass_gldownload(100.5, 100.0)
        result_explicit = should_pass_gldownload(100.5, 100.0, fps=OUTPUT_FPS)
        assert result_default == result_explicit

    def test_30fps_cadence_through_2hz_gate(self) -> None:
        """Simulate a 30fps input stream through the 2Hz (OUTPUT_FPS) gate.

        Over 1 second of input (30 frames at 0.0333s spacing), exactly
        2 frames must pass — the first at t=0 and the next at t>=0.5.
        Starting the simulation with ``last_pass_ts=-1.0`` puts the
        first frame comfortably past the interval boundary so it
        definitely passes.
        """
        last_pass = -1.0
        passed = 0
        dropped = 0
        for i in range(30):
            now = i * (1.0 / 30.0)
            if should_pass_gldownload(now, last_pass):
                passed += 1
                last_pass = now
            else:
                dropped += 1
        # At 30fps input through a 2Hz gate over 1 second, we expect 2
        # passes (t=0.0, then the first frame >= 0.5s after = t≈0.5).
        assert passed == 2, f"expected 2 passes in 1 second, got {passed}"
        assert dropped == 28
