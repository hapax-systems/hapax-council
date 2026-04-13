"""Phase 5 native RTMP output tests.

These tests exercise RtmpOutputBin without touching real NVENC or a real
YouTube endpoint. The bin is attached to a fake GstPipeline with a
videotestsrc → tee upstream; rtmp2sink is replaced via a runtime shim when
real NVENC is not available.

See docs/superpowers/specs/2026-04-12-native-rtmp-delivery-design.md
"""

from __future__ import annotations

from unittest import mock

import pytest


@pytest.fixture(scope="module")
def gst():
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    Gst.init(None)
    return Gst


class TestRtmpOutputBinConstruction:
    def test_build_with_real_elements_if_available(self, gst) -> None:
        from agents.studio_compositor.rtmp_output import RtmpOutputBin

        Gst = gst
        # Build a minimal pipeline: videotestsrc → tee → fakesink
        pipeline = Gst.Pipeline.new("rtmp-test-pipeline")
        src = Gst.ElementFactory.make("videotestsrc", "test_src")
        src.set_property("is-live", True)
        src_caps = Gst.ElementFactory.make("capsfilter", "test_caps")
        src_caps.set_property(
            "caps",
            Gst.Caps.from_string("video/x-raw,format=NV12,width=320,height=240,framerate=30/1"),
        )
        tee = Gst.ElementFactory.make("tee", "test_tee")
        sink = Gst.ElementFactory.make("fakesink", "test_sink")
        sink.set_property("sync", False)

        for el in [src, src_caps, tee, sink]:
            pipeline.add(el)
        src.link(src_caps)
        src_caps.link(tee)

        # Drain tee's first pad to a fakesink so it has a consumer
        fake_queue = Gst.ElementFactory.make("queue", "test_fake_queue")
        pipeline.add(fake_queue)
        tee.link(fake_queue)
        fake_queue.link(sink)

        bin_obj = RtmpOutputBin(
            gst=Gst,
            video_tee=tee,
            rtmp_location="rtmp://127.0.0.1:19999/test",  # nonexistent port
            bitrate_kbps=1000,
            gop_size=60,
        )

        # attach may fail if nvh264enc is missing in the test env; we only
        # assert the roundtrip API returns cleanly in both cases.
        attached = bin_obj.build_and_attach(pipeline)
        if attached:
            assert bin_obj.is_attached() is True
            bin_obj.detach_and_teardown(pipeline)
            assert bin_obj.is_attached() is False
        else:
            assert bin_obj.is_attached() is False

        pipeline.set_state(Gst.State.NULL)


class TestRebuildRoundtrip:
    def test_rebuild_count_increments(self, gst) -> None:
        from agents.studio_compositor.rtmp_output import RtmpOutputBin

        Gst = gst
        pipeline = Gst.Pipeline.new("rebuild-count-pipeline")
        tee = Gst.ElementFactory.make("tee", "rc_tee")
        pipeline.add(tee)

        bin_obj = RtmpOutputBin(gst=Gst, video_tee=tee)
        assert bin_obj.rebuild_count == 0

        # rebuild should bump the counter regardless of attach result
        bin_obj.rebuild_in_place(pipeline)
        assert bin_obj.rebuild_count == 1
        bin_obj.rebuild_in_place(pipeline)
        assert bin_obj.rebuild_count == 2

        bin_obj.detach_and_teardown(pipeline)
        pipeline.set_state(Gst.State.NULL)

    def test_detach_when_not_attached_is_noop(self, gst) -> None:
        from agents.studio_compositor.rtmp_output import RtmpOutputBin

        Gst = gst
        pipeline = Gst.Pipeline.new("detach-noop-pipeline")
        tee = Gst.ElementFactory.make("tee", "noop_tee")
        pipeline.add(tee)

        bin_obj = RtmpOutputBin(gst=Gst, video_tee=tee)
        assert bin_obj.is_attached() is False
        bin_obj.detach_and_teardown(pipeline)  # should not raise
        assert bin_obj.is_attached() is False

        pipeline.set_state(Gst.State.NULL)


class TestToggleLivestreamApi:
    def test_toggle_without_rtmp_bin_returns_false(self) -> None:
        # Fake compositor shell
        fake = mock.Mock()
        fake._rtmp_bin = None
        fake.pipeline = None

        # Import the actual method to test logic
        from agents.studio_compositor.compositor import StudioCompositor

        ok, msg = StudioCompositor.toggle_livestream(fake, activate=True, reason="test")
        assert ok is False
        assert "rtmp bin not constructed" in msg

    def test_toggle_activate_already_attached(self) -> None:
        from agents.studio_compositor.compositor import StudioCompositor

        fake = mock.Mock()
        fake._rtmp_bin = mock.Mock()
        fake._rtmp_bin.is_attached.return_value = True
        fake.pipeline = mock.Mock()

        ok, msg = StudioCompositor.toggle_livestream(fake, activate=True, reason="already")
        assert ok is True
        assert "already live" in msg

    def test_toggle_deactivate_not_attached(self) -> None:
        from agents.studio_compositor.compositor import StudioCompositor

        fake = mock.Mock()
        fake._rtmp_bin = mock.Mock()
        fake._rtmp_bin.is_attached.return_value = False
        fake.pipeline = mock.Mock()

        ok, msg = StudioCompositor.toggle_livestream(fake, activate=False, reason="already off")
        assert ok is True
        assert "already off" in msg
