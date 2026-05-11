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

    def test_sync_filters_private_markers_before_update(self, monkeypatch, tmp_path):
        from agents.studio_compositor import youtube_description_syncer as sync

        monkeypatch.setattr(sync, "LAST_STATE_FILE", tmp_path / "last.json")
        captured = {}

        def _updater(video_id, description, *, dry_run=False):
            captured["description"] = description
            return True

        sync.sync_once(
            video_id="vid-private-filter",
            marker_reader=lambda: {
                "condition_id": "PRIVATE_MEDIA_ROLE",
                "claim_id": "claim-PRIVATE",
            },
            objectives_reader=lambda: [
                {
                    "title": "non-broadcast private monitor route",
                    "priority": "high",
                    "objective_id": "obj-private",
                }
            ],
            attribution_reader=lambda: [],
            substrate_model="hapax-private",
            updater=_updater,
        )

        description = captured["description"]
        assert "Condition: unknown" in description
        assert "Substrate: unknown" in description
        assert "PRIVATE" not in description
        assert "non-broadcast" not in description
        assert "hapax-private" not in description


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


class TestSharedLinkFiltering:
    def test_append_links_filters_private_markers_from_existing_and_new_urls(self):
        from agents.studio_compositor.youtube_description_syncer import (
            _append_links_to_description,
        )

        description = _append_links_to_description(
            "Condition: cond-A\nSubstrate: hapax-private\n--- Links ---\nhttps://safe.old\n",
            [
                "https://safe.new",
                "https://example.invalid/PRIVATE_MEDIA_ROLE",
                "https://example.invalid/non-broadcast",
            ],
        )

        assert "Condition: cond-A" in description
        description_lines = description.splitlines()
        assert "https://safe.old" in description_lines
        assert "https://safe.new" in description_lines
        assert "hapax-private" not in description
        assert "PRIVATE_MEDIA_ROLE" not in description
        assert "non-broadcast" not in description

    def test_shared_link_sync_advances_cursor_for_filtered_private_records(self, tmp_path):
        from agents.studio_compositor import youtube_description_syncer as sync

        cursor = {"value": 0.0}
        calls = {"updater": 0, "queued": 0}

        def _links_reader(*, since_ts):
            assert since_ts == 0.0
            return [
                {
                    "ts": 10.0,
                    "url": "https://example.invalid/PRIVATE_MEDIA_ROLE",
                    "source": "sidechat",
                }
            ]

        def _updater(*_args, **_kwargs):
            calls["updater"] += 1
            return True

        def _queue_writer(_record):
            calls["queued"] += 1

        processed = sync.sync_shared_links_once(
            video_id="vid",
            links_reader=_links_reader,
            updater=_updater,
            description_reader=lambda _video_id: "",
            cursor_loader=lambda: cursor["value"],
            cursor_saver=lambda ts: cursor.update(value=ts),
            queue_writer=_queue_writer,
        )

        assert processed == 0
        assert cursor["value"] == 10.0
        assert calls == {"updater": 0, "queued": 0}


# ── YT bundle B2 — attribution backflow into syncer ──────────────────


class TestAttributionBackflow:
    """sync_once now enumerates AttributionSource entries and threads
    them through assemble_description so chat URLs surface in the live
    broadcast description."""

    def _make_entries(self):
        from datetime import UTC, datetime

        from shared.attribution import AttributionEntry

        return [
            AttributionEntry(
                kind="github",
                url="https://github.com/example/repo",
                title="example",
                source="chat:abc123",
                emitted_at=datetime.fromtimestamp(100, tz=UTC),
            ),
            AttributionEntry(
                kind="youtube",
                url="https://youtu.be/xyz",
                source="chat:def456",
                emitted_at=datetime.fromtimestamp(200, tz=UTC),
            ),
        ]

    def test_snapshot_state_includes_attributions(self):
        from agents.studio_compositor.youtube_description_syncer import _snapshot_state

        entries = self._make_entries()
        state = _snapshot_state(
            marker_reader=lambda: {"condition_id": "cond-A"},
            objectives_reader=lambda: [],
            attribution_reader=lambda: entries,
        )
        assert state["attributions"] == entries

    def test_snapshot_attribution_reader_failure_returns_empty(self, monkeypatch):
        """A bad attribution reader must NOT break the snapshot — the
        syncer's job is to publish state, not be derailed by a vault
        outage."""
        import sys

        from agents.studio_compositor.youtube_description_syncer import (
            _read_attribution_entries,
        )

        # Force the AttributionFileWriter import to fail.
        monkeypatch.setitem(sys.modules, "shared.attribution", None)
        result = _read_attribution_entries()
        assert result == []

    def test_sync_passes_attributions_to_assemble(self, monkeypatch, tmp_path):
        from agents.studio_compositor import youtube_description_syncer as sync

        monkeypatch.setattr(sync, "LAST_STATE_FILE", tmp_path / "last.json")
        captured = {}

        def _updater(video_id, description, *, dry_run=False):
            captured["description"] = description
            return True

        entries = self._make_entries()
        sync.sync_once(
            video_id="vid-attribution",
            marker_reader=lambda: {"condition_id": "cond-A"},
            objectives_reader=lambda: [],
            attribution_reader=lambda: entries,
            updater=_updater,
        )
        assert "https://github.com/example/repo" in captured["description"]
        assert "https://youtu.be/xyz" in captured["description"]
        assert "Sources:" in captured["description"]

    def test_state_hash_stable_across_repeat_reads(self):
        """Same on-disk attribution entries → same hash → no churn-update."""
        from agents.studio_compositor.youtube_description_syncer import (
            _snapshot_state,
            _state_hash,
        )

        entries = self._make_entries()
        s1 = _snapshot_state(
            marker_reader=lambda: {"condition_id": "x"},
            objectives_reader=lambda: [],
            attribution_reader=lambda: entries,
        )
        s2 = _snapshot_state(
            marker_reader=lambda: {"condition_id": "x"},
            objectives_reader=lambda: [],
            attribution_reader=lambda: entries,
        )
        assert _state_hash(s1) == _state_hash(s2)

    def test_state_hash_changes_when_new_url_added(self):
        """A newly-extracted URL must trigger a description update."""
        from datetime import UTC, datetime

        from agents.studio_compositor.youtube_description_syncer import (
            _snapshot_state,
            _state_hash,
        )
        from shared.attribution import AttributionEntry

        before = [
            AttributionEntry(
                kind="github",
                url="https://github.com/x/y",
                source="t",
                emitted_at=datetime.fromtimestamp(100, tz=UTC),
            )
        ]
        after = before + [
            AttributionEntry(
                kind="youtube",
                url="https://youtu.be/new",
                source="t",
                emitted_at=datetime.fromtimestamp(200, tz=UTC),
            )
        ]
        s1 = _snapshot_state(
            marker_reader=lambda: {"condition_id": "x"},
            objectives_reader=lambda: [],
            attribution_reader=lambda: before,
        )
        s2 = _snapshot_state(
            marker_reader=lambda: {"condition_id": "x"},
            objectives_reader=lambda: [],
            attribution_reader=lambda: after,
        )
        assert _state_hash(s1) != _state_hash(s2)
