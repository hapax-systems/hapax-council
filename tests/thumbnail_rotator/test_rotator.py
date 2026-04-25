"""Tests for ``agents.thumbnail_rotator``."""

from __future__ import annotations

import io
from pathlib import Path
from unittest import mock

from PIL import Image
from prometheus_client import CollectorRegistry

from agents.thumbnail_rotator.rotator import (
    THUMBNAIL_HEIGHT,
    THUMBNAIL_WIDTH,
    ThumbnailRotator,
    prepare_thumbnail_jpeg,
)


def _write_test_jpeg(path: Path, *, size=(1920, 1080), color=(64, 96, 128)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="JPEG", quality=90)


def _make_rotator(
    *,
    video_id: str | None = "test-video-id",
    upload_fn=None,
    snapshot_path: Path,
    tick_s: float = 60.0,
    dry_run: bool = False,
    slot_dir: Path | None = None,
) -> tuple[ThumbnailRotator, mock.Mock]:
    if upload_fn is None:
        upload_fn = mock.Mock(return_value="ok")
    if slot_dir is None:
        # Use a dedicated tmp slot dir per rotator so tests don't collide.
        slot_dir = snapshot_path.parent / "slots"
    rotator = ThumbnailRotator(
        video_id=video_id,
        upload_fn=upload_fn,
        snapshot_path=snapshot_path,
        tick_s=tick_s,
        dry_run=dry_run,
        slot_dir=slot_dir,
        registry=CollectorRegistry(),
    )
    return rotator, upload_fn


# ── prepare_thumbnail_jpeg ──────────────────────────────────────────


class TestPrepareThumbnailJpeg:
    def test_resizes_1080p_to_720p(self, tmp_path):
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src, size=(1920, 1080))
        out = prepare_thumbnail_jpeg(src)
        assert out is not None
        with Image.open(io.BytesIO(out)) as img:
            assert img.size == (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)

    def test_handles_non_16x9_aspect(self, tmp_path):
        """4:3 input fits inside 1280x720 box, preserving aspect."""
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src, size=(1600, 1200))  # 4:3
        out = prepare_thumbnail_jpeg(src)
        assert out is not None
        with Image.open(io.BytesIO(out)) as img:
            assert img.size[0] <= THUMBNAIL_WIDTH
            assert img.size[1] <= THUMBNAIL_HEIGHT

    def test_missing_file_returns_none(self, tmp_path):
        assert prepare_thumbnail_jpeg(tmp_path / "absent.jpg") is None

    def test_non_image_returns_none(self, tmp_path):
        bad = tmp_path / "snapshot.jpg"
        bad.write_text("not an image")
        assert prepare_thumbnail_jpeg(bad) is None

    def test_output_under_500kb(self, tmp_path):
        """Quality 85 keeps under ~500KB on synthetic content."""
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src, size=(1920, 1080))
        out = prepare_thumbnail_jpeg(src)
        assert out is not None
        assert len(out) < 500_000

    def test_palette_mode_converted_to_rgb(self, tmp_path):
        """Pillow needs RGB for JPEG; the converter handles palette/grayscale inputs."""
        src = tmp_path / "snapshot.png"
        Image.new("P", (1280, 720), 42).save(src, format="PNG")
        out = prepare_thumbnail_jpeg(src)
        assert out is not None
        with Image.open(io.BytesIO(out)) as img:
            assert img.mode == "RGB"


# ── Video ID gate ───────────────────────────────────────────────────


class TestVideoIdGate:
    def test_no_video_id_skips_upload(self, tmp_path):
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src)
        rotator, upload = _make_rotator(video_id=None, snapshot_path=src)
        assert rotator.run_once() == "no_video_id"
        upload.assert_not_called()

    def test_env_var_provides_video_id(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HAPAX_YOUTUBE_VIDEO_ID", "env-video-id")
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src)
        upload = mock.Mock(return_value="ok")
        rotator = ThumbnailRotator(
            upload_fn=upload, snapshot_path=src, registry=CollectorRegistry()
        )
        assert rotator.run_once() == "ok"
        assert upload.call_args.args[0] == "env-video-id"

    def test_explicit_video_id_overrides_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HAPAX_YOUTUBE_VIDEO_ID", "env-video-id")
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src)
        rotator, upload = _make_rotator(video_id="explicit-id", snapshot_path=src)
        rotator.run_once()
        assert upload.call_args.args[0] == "explicit-id"


# ── Snapshot gate ───────────────────────────────────────────────────


class TestSnapshotGate:
    def test_missing_snapshot_skips_upload(self, tmp_path):
        rotator, upload = _make_rotator(snapshot_path=tmp_path / "absent.jpg")
        assert rotator.run_once() == "no_snapshot"
        upload.assert_not_called()


# ── Dry run ─────────────────────────────────────────────────────────


class TestDryRun:
    def test_dry_run_skips_upload_but_consumes_snapshot(self, tmp_path):
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src)
        rotator, upload = _make_rotator(snapshot_path=src, dry_run=True)
        assert rotator.run_once() == "dry_run"
        upload.assert_not_called()

    def test_dry_run_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HAPAX_THUMBNAIL_DRY_RUN", "1")
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src)
        upload = mock.Mock(return_value="ok")
        rotator = ThumbnailRotator(
            video_id="vid",
            upload_fn=upload,
            snapshot_path=src,
            registry=CollectorRegistry(),
        )
        assert rotator.run_once() == "dry_run"
        upload.assert_not_called()


# ── Upload outcomes ─────────────────────────────────────────────────


class TestUploadOutcomes:
    def test_ok_increments_counter(self, tmp_path):
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src)
        rotator, upload = _make_rotator(snapshot_path=src)
        rotator.run_once()
        # First rotation lands in slot a (default).
        assert rotator.rotations_total.labels(result="ok", slot="a")._value.get() == 1.0

    def test_upload_exception_yields_error(self, tmp_path):
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src)
        upload = mock.Mock(side_effect=RuntimeError("api down"))
        rotator, _ = _make_rotator(snapshot_path=src, upload_fn=upload)
        assert rotator.run_once() == "error"

    def test_upload_returns_label_through(self, tmp_path):
        """Whatever string the upload_fn returns becomes the result + label."""
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src)
        upload = mock.Mock(return_value="auth_error")
        rotator, _ = _make_rotator(snapshot_path=src, upload_fn=upload)
        assert rotator.run_once() == "auth_error"
        assert rotator.rotations_total.labels(result="auth_error", slot="a")._value.get() == 1.0


# ── Tick cadence floor ──────────────────────────────────────────────


class TestTickFloor:
    def test_tick_s_floor_at_60s(self, tmp_path):
        """Don't permit aggressive cadences that would blow YouTube quota."""
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src)
        rotator, _ = _make_rotator(snapshot_path=src, tick_s=10.0)
        assert rotator._tick_s >= 60.0


# ── A/B slot retention (Phase 3) ────────────────────────────────────


class TestSlotRetention:
    """A/B alternation: each rotation flips the persisted slot pointer.

    Phase 3 of ytb-003 — keeps two recent thumbnails on disk (operator-
    inspectable) and alternates uploads so YouTube's freshness signal
    sees a moving target. Slot pointer persists across daemon restarts
    so the alternation cadence is unaffected by service flaps.
    """

    def test_first_rotation_uses_slot_a(self, tmp_path):
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src)
        rotator, _ = _make_rotator(snapshot_path=src)
        rotator.run_once()
        assert rotator.rotations_total.labels(result="ok", slot="a")._value.get() == 1.0
        assert rotator.rotations_total.labels(result="ok", slot="b")._value.get() == 0.0

    def test_second_rotation_uses_slot_b(self, tmp_path):
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src)
        rotator, _ = _make_rotator(snapshot_path=src)
        rotator.run_once()
        rotator.run_once()
        assert rotator.rotations_total.labels(result="ok", slot="a")._value.get() == 1.0
        assert rotator.rotations_total.labels(result="ok", slot="b")._value.get() == 1.0

    def test_alternates_across_many_rotations(self, tmp_path):
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src)
        rotator, _ = _make_rotator(snapshot_path=src)
        for _ in range(6):
            rotator.run_once()
        # 3 a, 3 b — perfect alternation.
        assert rotator.rotations_total.labels(result="ok", slot="a")._value.get() == 3.0
        assert rotator.rotations_total.labels(result="ok", slot="b")._value.get() == 3.0

    def test_slot_jpegs_persisted_to_disk(self, tmp_path):
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src)
        slot_dir = tmp_path / "slots"
        rotator, _ = _make_rotator(snapshot_path=src, slot_dir=slot_dir)
        rotator.run_once()
        rotator.run_once()
        assert (slot_dir / "slot-a.jpg").exists()
        assert (slot_dir / "slot-b.jpg").exists()
        assert (slot_dir / "state.json").exists()

    def test_slot_state_persists_across_rotator_instances(self, tmp_path):
        """A new rotator pointed at the same slot dir resumes the alternation."""
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src)
        slot_dir = tmp_path / "slots"
        # First daemon: 1 rotation → slot a.
        rotator1, _ = _make_rotator(snapshot_path=src, slot_dir=slot_dir)
        rotator1.run_once()
        # Second daemon (simulates restart) reuses slot dir; next slot is b.
        rotator2, _ = _make_rotator(snapshot_path=src, slot_dir=slot_dir)
        rotator2.run_once()
        assert rotator2.rotations_total.labels(result="ok", slot="b")._value.get() == 1.0

    def test_slot_persisted_even_when_upload_skipped(self, tmp_path):
        """no_video_id / no_snapshot still flip the pointer (atomic alternation)."""
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src)
        slot_dir = tmp_path / "slots"
        rotator, _ = _make_rotator(video_id=None, snapshot_path=src, slot_dir=slot_dir)
        rotator.run_once()  # slot a
        rotator.run_once()  # slot b
        assert rotator.rotations_total.labels(result="no_video_id", slot="a")._value.get() == 1.0
        assert rotator.rotations_total.labels(result="no_video_id", slot="b")._value.get() == 1.0

    def test_corrupt_state_defaults_to_slot_a(self, tmp_path):
        """Malformed state.json doesn't block rotation; falls back to slot a."""
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src)
        slot_dir = tmp_path / "slots"
        slot_dir.mkdir()
        (slot_dir / "state.json").write_text("not json", encoding="utf-8")
        rotator, _ = _make_rotator(snapshot_path=src, slot_dir=slot_dir)
        rotator.run_once()
        assert rotator.rotations_total.labels(result="ok", slot="a")._value.get() == 1.0


# ── Salience-triggered loop ─────────────────────────────────────────


class TestSalienceTriggeredLoop:
    """The salience-triggered loop fires run_once iff trigger.should_fire().

    Drives one iteration per stop call so we can pin the gate behavior
    without spinning the actual daemon loop.
    """

    def test_fire_triggers_run_once(self, tmp_path):
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src)
        rotator, upload = _make_rotator(snapshot_path=src)
        trigger = mock.Mock()
        trigger.should_fire.side_effect = [True, False]  # fire then idle

        # Stop after the second wait so the loop runs exactly twice.
        original_wait = rotator._stop_evt.wait

        def stop_after_two(timeout):
            if not hasattr(stop_after_two, "calls"):
                stop_after_two.calls = 0
            stop_after_two.calls += 1
            if stop_after_two.calls >= 2:
                rotator._stop_evt.set()
            return original_wait(0)

        with mock.patch.object(rotator._stop_evt, "wait", side_effect=stop_after_two):
            rotator.run_forever_salience_triggered(trigger, poll_s=0.01)

        assert trigger.should_fire.call_count == 2
        assert upload.call_count == 1

    def test_no_fire_skips_run_once(self, tmp_path):
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src)
        rotator, upload = _make_rotator(snapshot_path=src)
        trigger = mock.Mock()
        trigger.should_fire.return_value = False

        original_wait = rotator._stop_evt.wait

        def stop_after_one(timeout):
            rotator._stop_evt.set()
            return original_wait(0)

        with mock.patch.object(rotator._stop_evt, "wait", side_effect=stop_after_one):
            rotator.run_forever_salience_triggered(trigger, poll_s=0.01)

        upload.assert_not_called()

    def test_trigger_exception_does_not_break_loop(self, tmp_path):
        src = tmp_path / "snapshot.jpg"
        _write_test_jpeg(src)
        rotator, _ = _make_rotator(snapshot_path=src)
        trigger = mock.Mock()
        trigger.should_fire.side_effect = [RuntimeError("boom"), False]

        original_wait = rotator._stop_evt.wait

        def stop_after_two(timeout):
            if not hasattr(stop_after_two, "calls"):
                stop_after_two.calls = 0
            stop_after_two.calls += 1
            if stop_after_two.calls >= 2:
                rotator._stop_evt.set()
            return original_wait(0)

        with mock.patch.object(rotator._stop_evt, "wait", side_effect=stop_after_two):
            # Should not raise even though the first should_fire() raised.
            rotator.run_forever_salience_triggered(trigger, poll_s=0.01)

        assert trigger.should_fire.call_count == 2
