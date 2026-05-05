"""Tests for agents/studio_compositor/hls_archive.py — LRR Phase 2 item 2."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from agents.studio_compositor import hls_archive
from shared.stream_archive import SegmentSidecar, sidecar_path_for


@pytest.fixture
def archive_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point archive root + condition pointer + stimmung at tmp_path."""
    archive_root_dir = tmp_path / "archive"
    monkeypatch.setenv("HAPAX_ARCHIVE_ROOT", str(archive_root_dir))
    return tmp_path


def _touch_segment(path: Path, *, age_seconds: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake ts segment")
    if age_seconds > 0:
        mtime = time.time() - age_seconds
        os.utime(path, (mtime, mtime))


class TestLoadStimmungSnapshot:
    """Queue #146 G1 — `_load_stimmung_snapshot` error-path coverage.

    The happy path is exercised via `rotate_segment` fixtures. The three
    defensive branches — missing file, malformed JSON, non-dict payload —
    were previously only indirectly exercised. These tests pin each branch
    so a future refactor cannot silently change the empty-dict fallback.

    Camera-salience contract: when the broker has no observations or
    fails closed, the snapshot OMITS the ``camera_salience`` key
    entirely (no ``"camera_salience": null`` in the serialized
    sidecar). The CI harness has no live broker, so all three error
    branches end up returning ``{}``.
    """

    def test_missing_file_returns_empty_dict(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.json"
        assert not missing.exists()
        assert hls_archive._load_stimmung_snapshot(missing) == {}

    def test_malformed_json_returns_empty_dict(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{this is not valid json", encoding="utf-8")
        assert hls_archive._load_stimmung_snapshot(bad) == {}

    def test_non_dict_payload_returns_empty_dict(self, tmp_path: Path) -> None:
        list_payload = tmp_path / "list.json"
        list_payload.write_text(json.dumps(["stance", "dimensions"]), encoding="utf-8")
        assert hls_archive._load_stimmung_snapshot(list_payload) == {}


class TestIsSegmentStable:
    def test_fresh_segment_not_stable(self, tmp_path: Path) -> None:
        seg = tmp_path / "segment00001.ts"
        _touch_segment(seg, age_seconds=0.0)
        now = time.time()
        assert not hls_archive.is_segment_stable(seg, now_ts=now, window_seconds=10.0)

    def test_old_segment_stable(self, tmp_path: Path) -> None:
        seg = tmp_path / "segment00001.ts"
        _touch_segment(seg, age_seconds=30.0)
        now = time.time()
        assert hls_archive.is_segment_stable(seg, now_ts=now, window_seconds=10.0)

    def test_missing_segment_not_stable(self, tmp_path: Path) -> None:
        seg = tmp_path / "does-not-exist.ts"
        now = time.time()
        assert not hls_archive.is_segment_stable(seg, now_ts=now, window_seconds=10.0)


class TestRotateSegment:
    def test_move_and_sidecar(self, archive_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        source = archive_env / "src"
        source.mkdir()
        seg = source / "segment00001.ts"
        _touch_segment(seg, age_seconds=30.0)

        target = archive_env / "archive" / "hls" / "2026-04-14"
        new_path = hls_archive.rotate_segment(
            seg,
            target_dir=target,
            condition_id="cond-phase-a-baseline-qwen-001",
            stimmung={"stance": "READY"},
        )

        assert new_path == target / "segment00001.ts"
        assert new_path.exists()
        assert not seg.exists()  # moved, not copied
        sidecar_p = sidecar_path_for(new_path)
        assert sidecar_p.exists()

        sidecar = SegmentSidecar.from_path(sidecar_p)
        assert sidecar.segment_id == "segment00001"
        assert sidecar.condition_id == "cond-phase-a-baseline-qwen-001"
        assert sidecar.stimmung_snapshot == {"stance": "READY"}
        assert sidecar.archive_kind == "hls"

    def test_rotate_segment_refuses_overwrite(
        self, archive_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = archive_env / "src"
        source.mkdir()
        seg = source / "segment00001.ts"
        _touch_segment(seg, age_seconds=30.0)

        target = archive_env / "archive" / "hls" / "2026-04-14"
        target.mkdir(parents=True)
        (target / "segment00001.ts").write_bytes(b"existing")

        with pytest.raises(FileExistsError):
            hls_archive.rotate_segment(
                seg,
                target_dir=target,
                condition_id=None,
                stimmung={},
            )


class TestRotatePass:
    def test_rotates_only_stable_segments(
        self, archive_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = archive_env / "hls"
        source.mkdir()
        _touch_segment(source / "segment00001.ts", age_seconds=30.0)  # stable
        _touch_segment(source / "segment00002.ts", age_seconds=30.0)  # stable
        _touch_segment(source / "segment00003.ts", age_seconds=0.0)  # fresh

        monkeypatch.setattr(
            hls_archive,
            "DEFAULT_CONDITION_POINTER",
            archive_env / "nonexistent-condition.txt",
        )
        monkeypatch.setattr(
            hls_archive,
            "DEFAULT_STIMMUNG_PATH",
            archive_env / "nonexistent-stimmung.json",
        )

        result = hls_archive.rotate_pass(source_dir=source, window_seconds=10.0)
        assert result.scanned == 3
        assert result.rotated == 2
        assert result.skipped_unstable == 1
        assert result.skipped_already_rotated == 0
        assert result.errors == []

        # Verify files moved
        assert not (source / "segment00001.ts").exists()
        assert not (source / "segment00002.ts").exists()
        assert (source / "segment00003.ts").exists()

    def test_missing_source_dir_is_noop(self, archive_env: Path) -> None:
        result = hls_archive.rotate_pass(source_dir=archive_env / "nonexistent")
        assert result.scanned == 0
        assert result.rotated == 0
        assert result.errors == []

    def test_condition_id_from_pointer(
        self, archive_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = archive_env / "hls"
        source.mkdir()
        _touch_segment(source / "segment00001.ts", age_seconds=30.0)

        pointer = archive_env / "current.txt"
        pointer.write_text("cond-phase-a-baseline-qwen-001\n")
        monkeypatch.setattr(hls_archive, "DEFAULT_CONDITION_POINTER", pointer)
        monkeypatch.setattr(
            hls_archive,
            "DEFAULT_STIMMUNG_PATH",
            archive_env / "nonexistent-stimmung.json",
        )

        hls_archive.rotate_pass(source_dir=source, window_seconds=10.0)

        target_dir = archive_env / "archive" / "hls"
        matches = list(target_dir.glob("*/segment00001.ts.json"))
        assert len(matches) == 1
        sidecar = SegmentSidecar.from_path(matches[0])
        assert sidecar.condition_id == "cond-phase-a-baseline-qwen-001"

    def test_stimmung_best_effort(self, archive_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        source = archive_env / "hls"
        source.mkdir()
        _touch_segment(source / "segment00001.ts", age_seconds=30.0)

        stimmung_file = archive_env / "stimmung.json"
        stimmung_file.write_text(
            json.dumps({"stance": "SEEKING", "dimensions": {"intensity": 0.6}})
        )
        monkeypatch.setattr(hls_archive, "DEFAULT_STIMMUNG_PATH", stimmung_file)
        monkeypatch.setattr(
            hls_archive,
            "DEFAULT_CONDITION_POINTER",
            archive_env / "nonexistent-condition.txt",
        )

        hls_archive.rotate_pass(source_dir=source, window_seconds=10.0)

        target_dir = archive_env / "archive" / "hls"
        matches = list(target_dir.glob("*/segment00001.ts.json"))
        assert len(matches) == 1
        sidecar = SegmentSidecar.from_path(matches[0])
        assert sidecar.stimmung_snapshot.get("stance") == "SEEKING"

    def test_corrupt_stimmung_is_tolerated(
        self, archive_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = archive_env / "hls"
        source.mkdir()
        _touch_segment(source / "segment00001.ts", age_seconds=30.0)

        stimmung_file = archive_env / "stimmung.json"
        stimmung_file.write_text("not json {{{")
        monkeypatch.setattr(hls_archive, "DEFAULT_STIMMUNG_PATH", stimmung_file)
        monkeypatch.setattr(
            hls_archive,
            "DEFAULT_CONDITION_POINTER",
            archive_env / "nonexistent.txt",
        )

        result = hls_archive.rotate_pass(source_dir=source, window_seconds=10.0)
        assert result.rotated == 1
        assert result.errors == []


class TestSegmentStartEndTimestamps:
    """Phase 1 audit H4 regression pins.

    ``hlssink2`` finalizes segments on close, so ``segment.stat().st_mtime``
    is the segment END time. The sidecar's ``segment_start_ts`` must be
    derived as ``mtime - target_duration_seconds``, not set to mtime
    (which would put start equal to end). ``segment_end_ts`` must be the
    mtime itself, not the rotator's run time (which is ``close_time +
    stable_window``, ~10-15s late).

    Without these pins, ``archive-search.py by-timerange`` queries
    silently miss condition-boundary segments because their reported
    start times are several seconds later than their actual start times.
    """

    def _read_sidecar(self, archive_env: Path) -> SegmentSidecar:
        target_dir = archive_env / "archive" / "hls"
        matches = list(target_dir.glob("*/segment00001.ts.json"))
        assert len(matches) == 1
        return SegmentSidecar.from_path(matches[0])

    def test_segment_end_ts_equals_mtime(
        self, archive_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``segment_end_ts`` must be the segment file's mtime (close time),
        not the rotator's run time."""
        import datetime as _dt

        source = archive_env / "hls"
        source.mkdir()
        seg = source / "segment00001.ts"
        _touch_segment(seg, age_seconds=30.0)

        # Pin mtime to a known value so we can assert against it.
        mtime_seconds = 1_744_656_789.0
        os.utime(seg, (mtime_seconds, mtime_seconds))
        monkeypatch.setattr(
            hls_archive,
            "DEFAULT_CONDITION_POINTER",
            archive_env / "nonexistent-cond.txt",
        )
        monkeypatch.setattr(
            hls_archive,
            "DEFAULT_STIMMUNG_PATH",
            archive_env / "nonexistent-stimmung.json",
        )

        # Rotator runs 12s after the segment close.
        now_ts = mtime_seconds + 12.0
        hls_archive.rotate_pass(source_dir=source, window_seconds=10.0, now_ts=now_ts)

        sidecar = self._read_sidecar(archive_env)
        end_dt = _dt.datetime.fromisoformat(sidecar.segment_end_ts.replace("Z", "+00:00"))
        expected_end = _dt.datetime.fromtimestamp(mtime_seconds, tz=_dt.UTC)
        assert end_dt == expected_end, (
            f"segment_end_ts must equal mtime (close time), got {end_dt} vs {expected_end}"
        )

    def test_segment_start_ts_is_target_duration_before_end(
        self, archive_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``segment_start_ts`` = ``segment_end_ts - target_duration_seconds``."""
        import datetime as _dt

        source = archive_env / "hls"
        source.mkdir()
        seg = source / "segment00001.ts"
        _touch_segment(seg, age_seconds=30.0)
        mtime_seconds = 1_744_656_789.0
        os.utime(seg, (mtime_seconds, mtime_seconds))
        monkeypatch.setattr(
            hls_archive,
            "DEFAULT_CONDITION_POINTER",
            archive_env / "nonexistent-cond.txt",
        )
        monkeypatch.setattr(
            hls_archive,
            "DEFAULT_STIMMUNG_PATH",
            archive_env / "nonexistent-stimmung.json",
        )

        hls_archive.rotate_pass(
            source_dir=source,
            window_seconds=10.0,
            now_ts=mtime_seconds + 12.0,
            target_duration_seconds=2.0,
        )

        sidecar = self._read_sidecar(archive_env)
        start_dt = _dt.datetime.fromisoformat(sidecar.segment_start_ts.replace("Z", "+00:00"))
        end_dt = _dt.datetime.fromisoformat(sidecar.segment_end_ts.replace("Z", "+00:00"))
        delta = (end_dt - start_dt).total_seconds()
        assert delta == 2.0, (
            f"segment_end_ts - segment_start_ts must equal target_duration_seconds (2.0), "
            f"got {delta}"
        )

    def test_custom_target_duration_honored(
        self, archive_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A caller that passes target_duration_seconds=4.0 (e.g. 4s HLS config)
        must get a 4s-wide sidecar window."""
        import datetime as _dt

        source = archive_env / "hls"
        source.mkdir()
        seg = source / "segment00001.ts"
        _touch_segment(seg, age_seconds=30.0)
        mtime_seconds = 1_744_656_789.0
        os.utime(seg, (mtime_seconds, mtime_seconds))
        monkeypatch.setattr(
            hls_archive,
            "DEFAULT_CONDITION_POINTER",
            archive_env / "nonexistent-cond.txt",
        )
        monkeypatch.setattr(
            hls_archive,
            "DEFAULT_STIMMUNG_PATH",
            archive_env / "nonexistent-stimmung.json",
        )

        hls_archive.rotate_pass(
            source_dir=source,
            window_seconds=10.0,
            now_ts=mtime_seconds + 12.0,
            target_duration_seconds=4.0,
        )

        sidecar = self._read_sidecar(archive_env)
        start_dt = _dt.datetime.fromisoformat(sidecar.segment_start_ts.replace("Z", "+00:00"))
        end_dt = _dt.datetime.fromisoformat(sidecar.segment_end_ts.replace("Z", "+00:00"))
        assert (end_dt - start_dt).total_seconds() == 4.0

    def test_start_before_mtime_before_end_rotator_time(
        self, archive_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Invariant from beta audit: start_ts < file_mtime <= end_ts,
        and end_ts < rotator_run_time."""
        import datetime as _dt

        source = archive_env / "hls"
        source.mkdir()
        seg = source / "segment00001.ts"
        _touch_segment(seg, age_seconds=30.0)
        mtime_seconds = 1_744_656_789.0
        os.utime(seg, (mtime_seconds, mtime_seconds))
        monkeypatch.setattr(
            hls_archive,
            "DEFAULT_CONDITION_POINTER",
            archive_env / "nonexistent-cond.txt",
        )
        monkeypatch.setattr(
            hls_archive,
            "DEFAULT_STIMMUNG_PATH",
            archive_env / "nonexistent-stimmung.json",
        )

        rotator_ts = mtime_seconds + 12.0
        hls_archive.rotate_pass(source_dir=source, window_seconds=10.0, now_ts=rotator_ts)

        sidecar = self._read_sidecar(archive_env)
        start_dt = _dt.datetime.fromisoformat(sidecar.segment_start_ts.replace("Z", "+00:00"))
        end_dt = _dt.datetime.fromisoformat(sidecar.segment_end_ts.replace("Z", "+00:00"))
        mtime_dt = _dt.datetime.fromtimestamp(mtime_seconds, tz=_dt.UTC)
        rotator_dt = _dt.datetime.fromtimestamp(rotator_ts, tz=_dt.UTC)

        assert start_dt < mtime_dt, "start_ts must be strictly before file mtime"
        assert end_dt == mtime_dt, "end_ts must equal file mtime"
        assert end_dt < rotator_dt, (
            "end_ts must be before rotator run time (close happened earlier)"
        )
