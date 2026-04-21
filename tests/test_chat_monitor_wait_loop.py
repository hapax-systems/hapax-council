"""LRR Phase 0 item 1 regression: chat-monitor wait-loop on missing video ID.

Pre-fix behavior: ``main()`` called ``sys.exit(1)`` when neither
``YOUTUBE_VIDEO_ID`` env var nor ``/dev/shm/hapax-compositor/youtube-video-id.txt``
were set. systemd auto-restart kicked in, restart counter climbed past 660
between 2026-04-13 and 2026-04-14, journal filled with the same error.

Post-fix behavior (this regression pin):
- ``main()`` does NOT raise SystemExit when video ID is missing
- A polling loop waits for the ID to appear
- Once the ID appears (env var update OR file write), monitoring starts
- Warning log is throttled to every 5 minutes, not every poll
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest import mock


def _load_chat_monitor():
    """Import scripts/chat-monitor.py as a module despite the hyphenated name."""
    spec_path = Path(__file__).resolve().parent.parent / "scripts" / "chat-monitor.py"
    spec = importlib.util.spec_from_file_location("chat_monitor_module", spec_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["chat_monitor_module"] = module
    spec.loader.exec_module(module)
    return module


class TestVideoIdResolution:
    def test_read_video_id_returns_env_var_when_set(self, monkeypatch) -> None:
        cm = _load_chat_monitor()
        monkeypatch.setenv("YOUTUBE_VIDEO_ID", "dQw4w9WgXcQ")
        assert cm._read_video_id() == "dQw4w9WgXcQ"

    def test_read_video_id_strips_whitespace(self, monkeypatch) -> None:
        cm = _load_chat_monitor()
        monkeypatch.setenv("YOUTUBE_VIDEO_ID", "  abc123  ")
        assert cm._read_video_id() == "abc123"

    def test_read_video_id_falls_back_to_shm_file(self, monkeypatch, tmp_path: Path) -> None:
        cm = _load_chat_monitor()
        monkeypatch.delenv("YOUTUBE_VIDEO_ID", raising=False)
        shm = tmp_path / "shm"
        shm.mkdir()
        (shm / "youtube-video-id.txt").write_text("from-shm-file\n")
        with mock.patch.object(cm, "SHM_DIR", shm):
            assert cm._read_video_id() == "from-shm-file"

    def test_read_video_id_returns_empty_when_neither_source_has_it(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        cm = _load_chat_monitor()
        monkeypatch.delenv("YOUTUBE_VIDEO_ID", raising=False)
        with mock.patch.object(cm, "SHM_DIR", tmp_path / "nonexistent"):
            assert cm._read_video_id() == ""


class TestWaitLoopDoesNotCrash:
    def test_wait_for_video_id_returns_when_env_appears(self, monkeypatch, tmp_path: Path) -> None:
        """The wait loop must NOT call sys.exit. It loops until an ID appears."""
        cm = _load_chat_monitor()
        monkeypatch.delenv("YOUTUBE_VIDEO_ID", raising=False)
        with mock.patch.object(cm, "SHM_DIR", tmp_path / "no-shm"):
            poll_count = {"n": 0}

            def fake_sleep(_seconds: float) -> None:
                # On the third tick, set the env var so the next poll resolves.
                poll_count["n"] += 1
                if poll_count["n"] == 3:
                    os.environ["YOUTUBE_VIDEO_ID"] = "appeared-mid-poll"

            with mock.patch.object(cm.time, "sleep", fake_sleep):
                resolved = cm._wait_for_video_id()
            assert resolved == "appeared-mid-poll"
            os.environ.pop("YOUTUBE_VIDEO_ID", None)

    def test_main_does_not_raise_system_exit_when_video_id_missing(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        """Regression pin: pre-fix main() called sys.exit(1)."""
        cm = _load_chat_monitor()
        monkeypatch.delenv("YOUTUBE_VIDEO_ID", raising=False)

        # Make _read_video_id return empty so main() falls into the
        # wait branch (otherwise the live youtube-video-id-publisher
        # service writes a real ID to /dev/shm/.../youtube-video-id.txt
        # and main() never reaches _wait_for_video_id). Then mock
        # _wait_for_video_id to return a fake ID after 1 tick to avoid
        # a real loop, and stub ChatMonitor so we don't actually start
        # a network connection.
        with (
            mock.patch.object(cm, "_read_video_id", return_value=""),
            mock.patch.object(cm, "_wait_for_video_id", return_value="stub-id"),
            mock.patch.object(cm, "ChatMonitor") as mock_ctor,
        ):
            mock_ctor.return_value.start = mock.MagicMock()
            cm.main()  # must not raise SystemExit
            mock_ctor.assert_called_once_with("stub-id")


class TestWaitLoopThrottlesWarnings:
    def test_warning_throttled_to_log_interval(self, monkeypatch, tmp_path: Path, caplog) -> None:
        """The 'no video ID' warning must NOT log on every poll. The throttle
        interval (5 min by default) gates it. Three polls inside the throttle
        window → one warning only."""
        cm = _load_chat_monitor()
        monkeypatch.delenv("YOUTUBE_VIDEO_ID", raising=False)

        caplog.set_level("WARNING", logger="chat-monitor")
        with mock.patch.object(cm, "SHM_DIR", tmp_path / "no-shm"):
            poll_count = {"n": 0}

            # monotonic always returns 0 → all polls are within the throttle
            # window (delta < 300s) → only the first warning fires.
            with (
                mock.patch.object(cm.time, "monotonic", return_value=0.0),
                mock.patch.object(cm.time, "sleep") as mock_sleep,
            ):

                def stop_after_three_polls(_seconds: float) -> None:
                    poll_count["n"] += 1
                    if poll_count["n"] >= 3:
                        # Force the loop to exit by setting the env var.
                        os.environ["YOUTUBE_VIDEO_ID"] = "stop"

                mock_sleep.side_effect = stop_after_three_polls
                cm._wait_for_video_id()
                os.environ.pop("YOUTUBE_VIDEO_ID", None)

            # Exactly one "no video ID" warning across three polls.
            no_id_warnings = [rec for rec in caplog.records if "no video ID" in rec.message]
            assert len(no_id_warnings) == 1


class TestSysExitGoneRegressionPin:
    def test_main_function_does_not_call_sys_exit_anywhere(self) -> None:
        """Belt-and-suspenders: scan the file source for `sys.exit(` outside
        comments. Pre-fix had `sys.exit(1)` in main(); post-fix has zero."""
        spec_path = Path(__file__).resolve().parent.parent / "scripts" / "chat-monitor.py"
        source = spec_path.read_text()
        # Strip lines that are pure comments.
        non_comment_lines = [
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        ]
        non_comment_source = "\n".join(non_comment_lines)
        assert "sys.exit(" not in non_comment_source, (
            "chat-monitor.py must not call sys.exit() — it should wait, not crash"
        )

    def test_threading_import_unaffected(self) -> None:
        """Sanity check that removing `import sys` did not break other imports."""
        cm = _load_chat_monitor()
        # threading is still used by the existing ChatMonitor class
        assert hasattr(cm, "threading")
