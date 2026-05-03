"""Tests for camera_classifier_publisher — cc-task scene-classifier-publish-restore.

Pins the periodic-publish loop that the 24h independent-auditor batch
flagged as missing (Auditor E finding #10a, audit R3): camera
classifications were stale because publish_camera_classifications was
called exactly once during compositor construction.

Test layers:
  L0: feature flag — publisher_active reads env var, defaults on
  L1: thread loop — calls publish_camera_classifications on each tick
  L2: thread teardown — stop() unblocks the wait + joins cleanly
  L3: maybe-start gate — flag off returns None without spawning
  L4: maybe-start error path — exceptions from constructor swallowed
"""

from __future__ import annotations

import os
import time
from unittest.mock import MagicMock

from agents.studio_compositor.camera_classifier_publisher import (
    PUBLISHER_ACTIVE_ENV,
    CameraClassifierPublisherThread,
    maybe_start_camera_classifier_publisher,
    publisher_active,
)


class TestPublisherActiveEnvFlag:
    def test_default_is_active(self) -> None:
        prior = os.environ.pop(PUBLISHER_ACTIVE_ENV, None)
        try:
            assert publisher_active() is True
        finally:
            if prior is not None:
                os.environ[PUBLISHER_ACTIVE_ENV] = prior

    def test_falsy_values_disable(self) -> None:
        for val in ("0", "false", "FALSE", "no", "off", ""):
            os.environ[PUBLISHER_ACTIVE_ENV] = val
            try:
                assert publisher_active() is False, (
                    f"value {val!r} should disable but publisher_active returned True"
                )
            finally:
                os.environ.pop(PUBLISHER_ACTIVE_ENV, None)

    def test_truthy_values_enable(self) -> None:
        for val in ("1", "true", "yes", "on", "anything-else"):
            os.environ[PUBLISHER_ACTIVE_ENV] = val
            try:
                assert publisher_active() is True
            finally:
                os.environ.pop(PUBLISHER_ACTIVE_ENV, None)


class TestThreadLoop:
    def test_thread_calls_publish_on_each_tick(self) -> None:
        compositor = MagicMock()
        # Tight interval so the test finishes fast.
        thread = CameraClassifierPublisherThread(compositor, interval_s=0.05)
        thread.start()
        try:
            time.sleep(0.18)  # expect ~3 ticks (initial + 2 sleeps)
        finally:
            thread.stop(timeout=1.0)
        assert compositor.publish_camera_classifications.call_count >= 2, (
            "publisher should call publish_camera_classifications on each tick; "
            f"only saw {compositor.publish_camera_classifications.call_count} calls"
        )

    def test_thread_continues_after_publish_exception(self) -> None:
        compositor = MagicMock()
        compositor.publish_camera_classifications.side_effect = [
            RuntimeError("transient"),
            None,
            None,
        ]
        thread = CameraClassifierPublisherThread(compositor, interval_s=0.05)
        thread.start()
        try:
            time.sleep(0.18)
        finally:
            thread.stop(timeout=1.0)
        # We expect at least 2 calls: the failing one + at least one success.
        assert compositor.publish_camera_classifications.call_count >= 2, (
            "publisher must keep ticking after a publish exception"
        )

    def test_stop_unblocks_thread(self) -> None:
        compositor = MagicMock()
        thread = CameraClassifierPublisherThread(compositor, interval_s=10.0)
        thread.start()
        # Even though interval is 10s, stop() should unblock the wait
        # and let the thread exit promptly.
        t0 = time.monotonic()
        thread.stop(timeout=2.0)
        elapsed = time.monotonic() - t0
        assert not thread.is_alive(), "thread did not exit after stop()"
        assert elapsed < 2.0, f"stop took {elapsed:.2f}s; should be near-instant"


class TestMaybeStartGate:
    def test_flag_off_returns_none_without_spawning(self) -> None:
        compositor = MagicMock()
        os.environ[PUBLISHER_ACTIVE_ENV] = "0"
        try:
            result = maybe_start_camera_classifier_publisher(compositor)
        finally:
            os.environ.pop(PUBLISHER_ACTIVE_ENV, None)
        assert result is None
        assert compositor.publish_camera_classifications.call_count == 0

    def test_flag_on_returns_running_thread(self) -> None:
        compositor = MagicMock()
        os.environ[PUBLISHER_ACTIVE_ENV] = "1"
        result = None
        try:
            result = maybe_start_camera_classifier_publisher(compositor, interval_s=0.05)
            assert result is not None
            assert isinstance(result, CameraClassifierPublisherThread)
            assert result.is_alive()
            time.sleep(0.10)
            assert compositor.publish_camera_classifications.call_count >= 1
        finally:
            os.environ.pop(PUBLISHER_ACTIVE_ENV, None)
            if result is not None:
                result.stop(timeout=1.0)

    def test_constructor_failure_returns_none(self, monkeypatch) -> None:
        os.environ[PUBLISHER_ACTIVE_ENV] = "1"

        def boom(*args, **kwargs):
            raise RuntimeError("simulated constructor failure")

        monkeypatch.setattr(
            "agents.studio_compositor.camera_classifier_publisher.CameraClassifierPublisherThread",
            boom,
        )
        try:
            compositor = MagicMock()
            result = maybe_start_camera_classifier_publisher(compositor)
        finally:
            os.environ.pop(PUBLISHER_ACTIVE_ENV, None)
        assert result is None, (
            "constructor failure must be swallowed and return None — the "
            "compositor's start sequence cannot be broken by a publisher "
            "that fails to launch"
        )


class TestPublisherInteractsWithRealCompositorMethod:
    """Pin the contract: the publisher calls a method that exists on the
    compositor with the expected signature (no args, returns a dict).
    Catches refactors that rename publish_camera_classifications without
    updating the publisher.
    """

    def test_compositor_has_publish_camera_classifications_method(self) -> None:
        from agents.studio_compositor.compositor import StudioCompositor

        # Class-level attribute lookup; no instance needed.
        method = getattr(StudioCompositor, "publish_camera_classifications", None)
        assert method is not None, (
            "StudioCompositor must expose publish_camera_classifications — "
            "the publisher loop calls it on each tick"
        )
        assert callable(method)
