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
