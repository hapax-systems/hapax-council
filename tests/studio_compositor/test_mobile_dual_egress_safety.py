"""Mobile substream dual-egress and capture-time protection pins."""

from __future__ import annotations

import inspect

from agents.studio_compositor.compositor import StudioCompositor
from agents.studio_compositor.rtmp_output import MobileRtmpOutputBin


class _FakeBin:
    def __init__(self) -> None:
        self.attached = False
        self.attach_calls = 0
        self.detach_calls = 0

    def is_attached(self) -> bool:
        return self.attached

    def build_and_attach(self, pipeline: object) -> bool:
        assert pipeline is not None
        self.attach_calls += 1
        self.attached = True
        return True

    def detach_and_teardown(self, pipeline: object) -> None:
        assert pipeline is not None
        self.detach_calls += 1
        self.attached = False


def test_apply_livestream_mode_attaches_both_bins_for_dual() -> None:
    compositor = object.__new__(StudioCompositor)
    compositor.pipeline = object()
    compositor._rtmp_bin = _FakeBin()
    compositor._mobile_rtmp_bin = _FakeBin()

    ok, detail = StudioCompositor._apply_livestream_mode(
        compositor,
        activate=True,
        mode="dual",
    )

    assert ok, detail
    assert compositor._rtmp_bin.attached
    assert compositor._mobile_rtmp_bin.attached

    ok, detail = StudioCompositor._apply_livestream_mode(
        compositor,
        activate=False,
        mode="dual",
    )
    assert ok, detail
    assert not compositor._rtmp_bin.attached
    assert not compositor._mobile_rtmp_bin.attached


def test_desktop_mode_detaches_mobile_bin() -> None:
    compositor = object.__new__(StudioCompositor)
    compositor.pipeline = object()
    compositor._rtmp_bin = _FakeBin()
    compositor._mobile_rtmp_bin = _FakeBin()
    compositor._mobile_rtmp_bin.attached = True

    ok, detail = StudioCompositor._apply_livestream_mode(
        compositor,
        activate=True,
        mode="desktop",
    )

    assert ok, detail
    assert compositor._rtmp_bin.attached
    assert not compositor._mobile_rtmp_bin.attached
    assert compositor._mobile_rtmp_bin.detach_calls == 1


def test_mobile_support_threads_wait_for_attached_mobile_bin(monkeypatch) -> None:
    compositor = object.__new__(StudioCompositor)
    compositor._broadcast_mode = "dual"
    compositor._mobile_rtmp_bin = _FakeBin()
    starts: list[object] = []
    stops: list[object] = []

    monkeypatch.setattr(
        StudioCompositor,
        "_ensure_mobile_support_threads",
        lambda self: starts.append(self),
    )
    monkeypatch.setattr(
        StudioCompositor,
        "_stop_mobile_support_threads",
        lambda self: stops.append(self),
    )

    StudioCompositor._sync_mobile_support_threads(compositor)
    assert starts == []
    assert stops == [compositor]

    compositor._mobile_rtmp_bin.attached = True
    StudioCompositor._sync_mobile_support_threads(compositor)
    assert starts == [compositor]


def test_capture_path_masks_before_jpeg_and_fails_closed() -> None:
    from agents.studio_compositor import cameras

    source = inspect.getsource(cameras.add_camera_snapshot_branch)
    obscure_idx = source.index("obscure_frame_for_camera(frame, snap_role)")
    encode_idx = source.index("cv2.imencode")

    assert obscure_idx < encode_idx
    assert "frame[:, :, :] = (40, 40, 40)" in source


def test_camera_snapshot_branch_rate_limits_before_conversion() -> None:
    from agents.studio_compositor import cameras

    source = inspect.getsource(cameras.add_camera_snapshot_branch)
    chain_idx = source.index("chain = [queue, rate, rate_caps, convert")
    convert_idx = source.index('Gst.ElementFactory.make("videoconvert"')

    assert chain_idx > convert_idx


def test_camera_snapshot_framerate_env_accepts_fraction(monkeypatch: object) -> None:
    from agents.studio_compositor import cameras

    monkeypatch.setenv("HAPAX_CAMERA_SNAPSHOT_FRAMERATE", "1/2")

    assert cameras._camera_snapshot_framerate().numerator == 1
    assert cameras._camera_snapshot_framerate().denominator == 2


def test_mobile_bin_does_not_repeat_capture_protection_stage() -> None:
    from agents.studio_compositor import rtmp_output

    source = inspect.getsource(rtmp_output)
    mobile_source = inspect.getsource(MobileRtmpOutputBin)

    assert "obscure_frame_for_camera" not in source
    assert "mobile_rtmp_" in mobile_source


def test_mobile_default_crop_scales_design_crop_to_720p_source() -> None:
    mobile_bin = MobileRtmpOutputBin(
        gst=object(),
        glib=object(),
        video_tee=object(),
        source_width=1280,
        source_height=720,
    )

    assert mobile_bin._default_crop() == (437, 0, 438, 0)


def test_mobile_metrics_registered() -> None:
    from prometheus_client.exposition import generate_latest

    from agents.studio_compositor import metrics

    text = generate_latest(metrics.REGISTRY).decode("utf-8")

    assert "# HELP hapax_mobile_substream_frames_total" in text
    assert "# HELP hapax_mobile_substream_bitrate_kbps" in text
    assert "# HELP hapax_broadcast_mode" in text
    assert "# HELP hapax_mobile_cairo_render_duration_ms" in text

    metrics.set_broadcast_mode("mobile")
    assert metrics.HAPAX_BROADCAST_MODE._value.get() == 1
    metrics.set_broadcast_mode("dual")
