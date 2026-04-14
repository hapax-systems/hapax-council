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


class TestEncoderWalkQueueIsolation:
    """Delta 2026-04-14-encoder-output-path-walk findings #4 + #5 pins.

    Before the fix, the RTMP bin had:
    - Zero queues in the audio path (pipewiresrc → convert → resample →
      caps → voaacenc → aacparse → flvmux). Any voaacenc stall
      backpressured directly into pipewiresrc, risking PipeWire xruns.
    - No queue between videoconvert and nvh264enc. An NVENC stall
      blocked videoconvert, which backpressured the input queue and
      dropped oldest frames (leaky=downstream).

    These pins assert that three new thread-isolation queues are
    present by name: one between videoconvert and the video encoder,
    one after pipewiresrc, one before voaacenc.
    """

    def test_audio_and_video_queues_present_in_bin(self, gst) -> None:
        from agents.studio_compositor.rtmp_output import RtmpOutputBin

        Gst = gst
        pipeline = Gst.Pipeline.new("rtmp-queue-test-pipeline")
        src = Gst.ElementFactory.make("videotestsrc", "qtest_src")
        src.set_property("is-live", True)
        src_caps = Gst.ElementFactory.make("capsfilter", "qtest_caps")
        src_caps.set_property(
            "caps",
            Gst.Caps.from_string("video/x-raw,format=NV12,width=320,height=240,framerate=30/1"),
        )
        tee = Gst.ElementFactory.make("tee", "qtest_tee")
        sink = Gst.ElementFactory.make("fakesink", "qtest_sink")
        sink.set_property("sync", False)
        for el in [src, src_caps, tee, sink]:
            pipeline.add(el)
        src.link(src_caps)
        src_caps.link(tee)
        fake_queue = Gst.ElementFactory.make("queue", "qtest_fake_queue")
        pipeline.add(fake_queue)
        tee.link(fake_queue)
        fake_queue.link(sink)

        bin_obj = RtmpOutputBin(
            gst=Gst,
            video_tee=tee,
            rtmp_location="rtmp://127.0.0.1:19999/qtest",
            bitrate_kbps=1000,
            gop_size=60,
        )

        attached = bin_obj.build_and_attach(pipeline)
        try:
            if not attached:
                # Test env without nvh264enc / voaacenc / pipewiresrc —
                # we can still skip cleanly.
                import pytest as _pt

                _pt.skip("RTMP bin attach failed — GStreamer deps missing in CI")

            inner_bin = bin_obj._bin  # type: ignore[attr-defined]
            assert inner_bin is not None

            # Finding #5: video encoder-isolation queue between
            # videoconvert and nvh264enc.
            video_encoder_queue = inner_bin.get_by_name("rtmp_video_encoder_queue")
            assert video_encoder_queue is not None, (
                "rtmp_video_encoder_queue missing — videoconvert + nvh264enc "
                "must not share a thread (delta drop #28/#30 walk finding #5)"
            )

            # Finding #4: audio source-side queue after pipewiresrc.
            audio_src_queue = inner_bin.get_by_name("rtmp_audio_src_queue")
            assert audio_src_queue is not None, (
                "rtmp_audio_src_queue missing — pipewiresrc must not "
                "backpressure directly into audioconvert (finding #4)"
            )

            # Finding #4 continued: audio encoder-isolation queue before
            # voaacenc.
            audio_encoder_queue = inner_bin.get_by_name("rtmp_audio_encoder_queue")
            assert audio_encoder_queue is not None, (
                "rtmp_audio_encoder_queue missing — voaacenc must not "
                "share a thread with audioresample (finding #4)"
            )

            # Basic configuration sanity — all three should be
            # leaky=downstream so they drop at the queue instead of
            # propagating backpressure upstream.
            for q in (video_encoder_queue, audio_src_queue, audio_encoder_queue):
                leaky = q.get_property("leaky")
                assert int(leaky) == 2, (
                    f"queue {q.get_name()} must be leaky=downstream (2) "
                    f"to match the existing bin's buffering strategy; got {leaky}"
                )
        finally:
            if attached:
                bin_obj.detach_and_teardown(pipeline)
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


class TestLivestreamControlPoll:
    """process_livestream_control is the cross-process bridge between the
    daimonion's affordance dispatch loop and the compositor's toggle API.

    It runs inside the compositor's state_reader_loop at 10 Hz and is
    the ONLY path through which studio.toggle_livestream reaches the
    GStreamer pipeline after consent gating. These tests verify the
    control-file → toggle_livestream → status-file roundtrip.
    """

    def test_no_control_file_is_noop(self, tmp_path) -> None:
        from agents.studio_compositor.state import process_livestream_control

        fake = mock.Mock()
        fake._GLib = None
        fake.toggle_livestream = mock.Mock()

        result = process_livestream_control(fake, snapshot_dir=tmp_path)

        assert result is False
        fake.toggle_livestream.assert_not_called()

    def test_activate_dispatches_and_writes_status(self, tmp_path) -> None:
        import json as _json

        from agents.studio_compositor.state import process_livestream_control

        control = tmp_path / "livestream-control.json"
        control.write_text(
            _json.dumps(
                {
                    "activate": True,
                    "reason": "test recruitment",
                    "requested_at": 1700000000.0,
                }
            )
        )

        fake = mock.Mock()
        fake._GLib = None
        fake.toggle_livestream.return_value = (True, "rtmp bin attached")

        result = process_livestream_control(fake, snapshot_dir=tmp_path)

        assert result is True
        fake.toggle_livestream.assert_called_once_with(True, "test recruitment")
        assert not control.exists(), "control file must be consumed"

        status = _json.loads((tmp_path / "livestream-status.json").read_text())
        assert status["activate"] is True
        assert status["success"] is True
        assert status["message"] == "rtmp bin attached"
        assert status["requested_at"] == 1700000000.0
        assert "processed_at" in status

    def test_deactivate_dispatches_via_glib_idle_add(self, tmp_path) -> None:
        import json as _json

        from agents.studio_compositor.state import process_livestream_control

        control = tmp_path / "livestream-control.json"
        control.write_text(_json.dumps({"activate": False, "reason": "wrap"}))

        fake = mock.Mock()
        fake.toggle_livestream.return_value = (True, "rtmp bin detached")

        glib = mock.Mock()

        def _immediate(fn):
            fn()

        glib.idle_add.side_effect = _immediate
        fake._GLib = glib

        result = process_livestream_control(fake, snapshot_dir=tmp_path)

        assert result is True
        glib.idle_add.assert_called_once()
        fake.toggle_livestream.assert_called_once_with(False, "wrap")
        status = _json.loads((tmp_path / "livestream-status.json").read_text())
        assert status["activate"] is False
        assert status["success"] is True

    def test_toggle_exception_lands_in_status_as_failure(self, tmp_path) -> None:
        import json as _json

        from agents.studio_compositor.state import process_livestream_control

        control = tmp_path / "livestream-control.json"
        control.write_text(_json.dumps({"activate": True, "reason": "boom"}))

        fake = mock.Mock()
        fake._GLib = None
        fake.toggle_livestream.side_effect = RuntimeError("nvenc missing")

        result = process_livestream_control(fake, snapshot_dir=tmp_path)

        assert result is True
        assert not control.exists()
        status = _json.loads((tmp_path / "livestream-status.json").read_text())
        assert status["success"] is False
        assert "raised" in status["message"]

    def test_malformed_control_file_is_deleted_and_no_dispatch(self, tmp_path) -> None:
        from agents.studio_compositor.state import process_livestream_control

        control = tmp_path / "livestream-control.json"
        control.write_text("{not json")

        fake = mock.Mock()
        fake._GLib = None

        result = process_livestream_control(fake, snapshot_dir=tmp_path)

        assert result is True
        assert not control.exists(), "malformed control file must be deleted to avoid retry storm"
        fake.toggle_livestream.assert_not_called()

    def test_missing_activate_defaults_to_false(self, tmp_path) -> None:
        """The compositor side is strict: missing activate means don't start."""
        import json as _json

        from agents.studio_compositor.state import process_livestream_control

        control = tmp_path / "livestream-control.json"
        control.write_text(_json.dumps({"reason": "ambiguous"}))

        fake = mock.Mock()
        fake._GLib = None
        fake.toggle_livestream.return_value = (True, "already off")

        process_livestream_control(fake, snapshot_dir=tmp_path)

        fake.toggle_livestream.assert_called_once_with(False, "ambiguous")
