"""Tests for agents.studio_compositor.youtube_description_syncer (Phase 8 item 7)."""

from __future__ import annotations


class TestSnapshotState:
    def test_empty_marker_returns_empty_condition(self, monkeypatch):
        from agents.studio_compositor import youtube_description_syncer as sync

        state = sync._snapshot_state(
            marker_reader=lambda: {},
            objectives_reader=lambda: [],
        )
        assert state["condition_id"] == ""
        assert state["objectives"] == []

    def test_populated_marker_propagates(self, monkeypatch):
        from agents.studio_compositor import youtube_description_syncer as sync

        state = sync._snapshot_state(
            marker_reader=lambda: {"condition_id": "cond-abc-001", "claim_id": "claim-5"},
            objectives_reader=lambda: [
                {"title": "T", "priority": "high", "objective_id": "obj-001"}
            ],
        )
        assert state["condition_id"] == "cond-abc-001"
        assert state["claim_id"] == "claim-5"
        assert state["objectives"][0]["title"] == "T"


class TestSyncOnce:
    def test_no_video_id_noop(self, monkeypatch, tmp_path):
        from agents.studio_compositor import youtube_description_syncer as sync

        monkeypatch.setattr(sync, "LAST_STATE_FILE", tmp_path / "last.json")
        monkeypatch.delenv("HAPAX_YOUTUBE_VIDEO_ID", raising=False)
        called = {"n": 0}

        def _updater(*a, **kw):
            called["n"] += 1
            return True

        assert (
            sync.sync_once(
                marker_reader=lambda: {"condition_id": "x"},
                objectives_reader=lambda: [],
                updater=_updater,
            )
            is False
        )
        assert called["n"] == 0

    def test_sends_on_first_sync(self, monkeypatch, tmp_path):
        from agents.studio_compositor import youtube_description_syncer as sync

        monkeypatch.setattr(sync, "LAST_STATE_FILE", tmp_path / "last.json")
        sent_payload = {}

        def _updater(video_id, description, *, dry_run=False):
            sent_payload["video_id"] = video_id
            sent_payload["description"] = description
            return True

        result = sync.sync_once(
            video_id="vid-001",
            marker_reader=lambda: {"condition_id": "cond-abc-001"},
            objectives_reader=lambda: [
                {"title": "Ship Cycle 2", "priority": "high", "objective_id": "obj-001"}
            ],
            updater=_updater,
        )
        assert result is True
        assert sent_payload["video_id"] == "vid-001"
        assert "cond-abc-001" in sent_payload["description"]
        assert "Ship Cycle 2" in sent_payload["description"]
        # Last-state file should exist
        assert (tmp_path / "last.json").exists()

    def test_skips_when_state_unchanged(self, monkeypatch, tmp_path):
        from agents.studio_compositor import youtube_description_syncer as sync

        monkeypatch.setattr(sync, "LAST_STATE_FILE", tmp_path / "last.json")
        calls = {"n": 0}

        def _updater(*a, **kw):
            calls["n"] += 1
            return True

        kwargs = dict(
            video_id="vid-001",
            marker_reader=lambda: {"condition_id": "cond-abc-001"},
            objectives_reader=lambda: [
                {"title": "Same", "priority": "high", "objective_id": "obj-001"}
            ],
            updater=_updater,
        )
        # First call sends
        assert sync.sync_once(**kwargs) is True
        # Second call with identical state should no-op
        assert sync.sync_once(**kwargs) is False
        assert calls["n"] == 1

    def test_sends_again_on_state_change(self, monkeypatch, tmp_path):
        from agents.studio_compositor import youtube_description_syncer as sync

        monkeypatch.setattr(sync, "LAST_STATE_FILE", tmp_path / "last.json")
        payloads: list[str] = []

        def _updater(video_id, description, *, dry_run=False):
            payloads.append(description)
            return True

        # First state
        sync.sync_once(
            video_id="vid-001",
            marker_reader=lambda: {"condition_id": "cond-A"},
            objectives_reader=lambda: [],
            updater=_updater,
        )
        # Different state — should send
        sync.sync_once(
            video_id="vid-001",
            marker_reader=lambda: {"condition_id": "cond-B"},
            objectives_reader=lambda: [],
            updater=_updater,
        )
        assert len(payloads) == 2
        assert "cond-A" in payloads[0]
        assert "cond-B" in payloads[1]

    def test_quota_exhaustion_no_state_persist(self, monkeypatch, tmp_path):
        """When the updater returns False (quota exhausted), we must NOT
        persist the state hash — otherwise a genuine state-change next
        cycle would be missed because its hash matches the 'sent' hash."""
        from agents.studio_compositor import youtube_description_syncer as sync

        monkeypatch.setattr(sync, "LAST_STATE_FILE", tmp_path / "last.json")

        def _updater(*a, **kw):
            return False  # quota exhausted, skip_silent

        result = sync.sync_once(
            video_id="vid-001",
            marker_reader=lambda: {"condition_id": "cond-A"},
            objectives_reader=lambda: [],
            updater=_updater,
        )
        assert result is False
        # Last-state file should NOT exist (we didn't save)
        assert not (tmp_path / "last.json").exists()

    def test_reads_video_id_from_env_when_arg_missing(self, monkeypatch, tmp_path):
        from agents.studio_compositor import youtube_description_syncer as sync

        monkeypatch.setattr(sync, "LAST_STATE_FILE", tmp_path / "last.json")
        monkeypatch.setenv("HAPAX_YOUTUBE_VIDEO_ID", "env-vid-999")

        seen = {}

        def _updater(video_id, description, *, dry_run=False):
            seen["video_id"] = video_id
            return True

        sync.sync_once(
            marker_reader=lambda: {"condition_id": "cond-A"},
            objectives_reader=lambda: [],
            updater=_updater,
        )
        assert seen["video_id"] == "env-vid-999"


class TestStateHash:
    def test_same_state_same_hash(self):
        from agents.studio_compositor.youtube_description_syncer import _state_hash

        s1 = {"condition_id": "x", "objectives": [{"title": "a", "priority": "high"}]}
        s2 = {"condition_id": "x", "objectives": [{"title": "a", "priority": "high"}]}
        assert _state_hash(s1) == _state_hash(s2)

    def test_different_state_different_hash(self):
        from agents.studio_compositor.youtube_description_syncer import _state_hash

        s1 = {"condition_id": "x", "objectives": []}
        s2 = {"condition_id": "y", "objectives": []}
        assert _state_hash(s1) != _state_hash(s2)
