"""Tests for shared.perceptual_coverage — camera frustum and mic pickup queries."""

from __future__ import annotations

from shared.perceptual_coverage import (
    MicSpec,
    best_mic_for,
    build_frustum,
    coverage_gaps,
    mic_sensitivity,
)


class TestBuildFrustum:
    def test_frustum_has_6_planes(self) -> None:
        f = build_frustum((0, 0, 1), yaw_deg=0, camera_id="test")
        assert len(f.planes) == 6

    def test_point_in_front_is_inside(self) -> None:
        f = build_frustum((0, 0, 1), yaw_deg=0, camera_id="test")
        assert f.contains_point((0, 1, 1))

    def test_point_behind_is_outside(self) -> None:
        f = build_frustum((0, 0, 1), yaw_deg=0, camera_id="test")
        assert not f.contains_point((0, -1, 1))

    def test_point_far_away_is_outside(self) -> None:
        f = build_frustum((0, 0, 1), yaw_deg=0, camera_id="test", far=3.0)
        assert not f.contains_point((0, 10, 1))

    def test_rotated_camera_sees_rotated_direction(self) -> None:
        f = build_frustum((0, 0, 1), yaw_deg=90, camera_id="test")
        assert f.contains_point((1, 0, 1))
        assert not f.contains_point((-1, 0, 1))

    def test_camera_id_preserved(self) -> None:
        f = build_frustum((0, 0, 1), yaw_deg=0, camera_id="brio-operator")
        assert f.camera_id == "brio-operator"


class TestMicSensitivity:
    def test_on_axis_maximum(self) -> None:
        mic = MicSpec("yeti", (0, 0, 0), 0.0, 0.5)
        on_axis = mic_sensitivity(mic, (0, 1, 0))
        off_axis = mic_sensitivity(mic, (1, 0, 0))
        assert on_axis > off_axis

    def test_omni_equal_all_directions(self) -> None:
        mic = MicSpec("omni", (0, 0, 0), 0.0, 1.0)
        front = mic_sensitivity(mic, (0, 1, 0))
        side = mic_sensitivity(mic, (1, 0, 0))
        assert abs(front - side) < 0.01

    def test_cardioid_null_at_rear(self) -> None:
        mic = MicSpec("cardioid", (0, 0, 0), 0.0, 0.5)
        rear = mic_sensitivity(mic, (0, -1, 0))
        assert rear < 0.1

    def test_distance_attenuation(self) -> None:
        mic = MicSpec("yeti", (0, 0, 0), 0.0, 0.5)
        close = mic_sensitivity(mic, (0, 1, 0))
        far = mic_sensitivity(mic, (0, 2, 0))
        assert close > far

    def test_best_mic_returns_closest_on_axis(self) -> None:
        mic_a = MicSpec("a", (0, 0, 0), 0.0, 0.5)
        mic_b = MicSpec("b", (0, 0.5, 0), 0.0, 0.5)
        target = (0, 0.6, 0)
        best = best_mic_for(target, [mic_a, mic_b])
        assert best is not None
        assert best.mic_id == "b"


class TestCoverageGaps:
    def test_returns_list(self) -> None:
        gaps = coverage_gaps(zone_bounds=(0, 0, 1, 1), grid_spacing=0.5)
        assert isinstance(gaps, list)

    def test_all_gaps_are_3d_points(self) -> None:
        gaps = coverage_gaps(zone_bounds=(0, 0, 1, 1), grid_spacing=0.5)
        for g in gaps:
            assert len(g) == 3
