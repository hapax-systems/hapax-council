"""Pins for recording purge range closure at consent removal and pause."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agents.studio_compositor import consent as recording_consent

CONTRACT = "synthetic-successor-contract"


def _compositor(tmp_path):
    recordings = tmp_path / "recordings"
    role = recordings / "camera"
    role.mkdir(parents=True)
    hls = tmp_path / "hls"
    hls.mkdir()
    return (
        SimpleNamespace(
            config=SimpleNamespace(
                recording=SimpleNamespace(output_dir=recordings),
                hls=SimpleNamespace(output_dir=hls),
            )
        ),
        role,
    )


def _write_audit(path, entries):
    path.write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries),
        encoding="utf-8",
    )


def _entry(timestamp, event, contracts):
    return {
        "timestamp": timestamp,
        "event": event,
        "active_contracts": contracts,
    }


@pytest.mark.parametrize("event", ["consent_changed", "recording_paused"])
def test_purge_closes_at_removal_or_pause(tmp_path, monkeypatch, event):
    compositor, role = _compositor(tmp_path)
    audit = tmp_path / "consent.jsonl"
    monkeypatch.setattr(recording_consent, "CONSENT_AUDIT_PATH", audit)
    _write_audit(
        audit,
        [
            _entry("2026-09-28T00:00:00+00:00", "recording_resumed", [CONTRACT]),
            _entry(
                "2026-09-28T00:01:00+00:00",
                event,
                [CONTRACT] if event == "recording_paused" else [],
            ),
            _entry("2026-09-28T00:02:00+00:00", "recording_paused", []),
        ],
    )
    before_removal = role / "clip_20260928-000030_segment.mkv"
    after_removal = role / "clip_20260928-000130_segment.mkv"
    before_removal.write_bytes(b"purge")
    after_removal.write_bytes(b"keep")

    result = recording_consent.purge_video_recordings(compositor, CONTRACT)

    assert result.items_purged == 1
    assert result.failures == ()
    assert result.purge_complete is True
    assert not before_removal.exists()
    assert after_removal.exists()


def test_purge_result_reports_partial_deletion_fields(tmp_path, monkeypatch):
    compositor, role = _compositor(tmp_path)
    audit = tmp_path / "consent.jsonl"
    monkeypatch.setattr(recording_consent, "CONSENT_AUDIT_PATH", audit)
    _write_audit(
        audit,
        [_entry("2026-09-28T00:00:00+00:00", "recording_resumed", [CONTRACT])],
    )
    valid = role / "clip_20260928-000030_segment.mkv"
    malformed = role / "clip_without_timestamp.mkv"
    valid.write_bytes(b"purge")
    malformed.write_bytes(b"malformed")

    result = recording_consent.purge_video_recordings(compositor, CONTRACT)

    assert result.items_purged == 1
    assert result.failures == ("recording_timestamp_invalid",)
    assert result.purge_complete is False


def test_removal_instant_is_exclusive_for_recording_and_hls(tmp_path, monkeypatch):
    import os
    from datetime import datetime

    compositor, role = _compositor(tmp_path)
    audit = tmp_path / "consent.jsonl"
    monkeypatch.setattr(recording_consent, "CONSENT_AUDIT_PATH", audit)
    removal = "2026-09-28T00:01:00+00:00"
    _write_audit(
        audit,
        [
            _entry("2026-09-28T00:00:00+00:00", "recording_resumed", [CONTRACT]),
            _entry(removal, "consent_changed", []),
        ],
    )
    # The audit row describes the state at its timestamp: this contract is absent.
    before = role / "clip_20260928-000059_segment.mkv"
    boundary = role / "clip_20260928-000100_segment.mkv"
    hls_before = compositor.config.hls.output_dir / "before.ts"
    hls_boundary = compositor.config.hls.output_dir / "boundary.ts"
    for path in (before, boundary, hls_before, hls_boundary):
        path.write_bytes(b"synthetic")
    end = datetime.fromisoformat(removal).timestamp()
    os.utime(hls_before, (end - 1, end - 1))
    os.utime(hls_boundary, (end, end))
    result = recording_consent.purge_video_recordings(compositor, CONTRACT)
    assert result.items_purged == 2
    assert result.purge_complete
    assert not before.exists() and not hls_before.exists()
    assert boundary.exists() and hls_boundary.exists()


@pytest.mark.parametrize(
    "reason, missing_key",
    [
        ("recording_audit_unreadable", False),
        ("recording_audit_unreadable", True),
        ("compat_missing", False),
    ],
)
def test_purge_failure_preserves_files(
    reason, missing_key, tmp_path, monkeypatch, caplog, synthetic_custody
):
    from tests.shared.synthetic_custody import ENTRY

    compositor, role = _compositor(tmp_path)
    files = (role / "clip_20260928-000030_segment.mkv", compositor.config.hls.output_dir / "a.ts")
    for path in files:
        path.write_bytes(b"keep")
    audit = tmp_path / "audit.jsonl"
    if missing_key:
        _write_audit(
            audit,
            [
                _entry("2026-09-28T00:00:00+00:00", "recording_resumed", [CONTRACT]),
                {"timestamp": "2026-09-28T00:01:00+00:00", "event": "consent_changed"},
            ],
        )
    else:
        audit.write_text("synthetic-private-invalid-json")
    monkeypatch.setattr(recording_consent, "CONSENT_AUDIT_PATH", audit)
    if reason == "compat_missing":
        synthetic_custody.delete(ENTRY)
    result = recording_consent.purge_video_recordings(compositor, CONTRACT)
    assert result.items_purged == 0 and not result.purge_complete
    assert result.failures == (reason,)
    assert all(path.read_bytes() == b"keep" for path in files)
    if reason == "recording_audit_unreadable":
        assert caplog.record_tuples == [(recording_consent.__name__, 30, reason)]
