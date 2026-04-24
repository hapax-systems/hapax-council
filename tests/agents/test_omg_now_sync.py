"""Tests for agents/omg_now_sync — ytb-OMG3.

Verifies the /now page auto-sync daemon:
  - state readers return defaults gracefully when their source is absent
  - template renders current state with timestamp + placeholders
  - publisher hash-dedups + calls set_now with the right args
  - disabled client / unchanged content short-circuit cleanly
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from agents.omg_now_sync.data import (
    NowState,
    load_chronicle_recent,
    load_stimmung,
    load_working_mode,
)
from agents.omg_now_sync.sync import (
    OmgNowSync,
    render_now_markdown,
)


class TestLoadWorkingMode:
    def test_reads_mode_file(self, tmp_path: Path) -> None:
        mode_file = tmp_path / "working-mode"
        mode_file.write_text("research\n")
        assert load_working_mode(mode_file) == "research"

    def test_rnd_mode(self, tmp_path: Path) -> None:
        mode_file = tmp_path / "working-mode"
        mode_file.write_text("rnd\n")
        assert load_working_mode(mode_file) == "rnd"

    def test_missing_file_returns_unknown(self, tmp_path: Path) -> None:
        assert load_working_mode(tmp_path / "absent") == "unknown"

    def test_empty_file_returns_unknown(self, tmp_path: Path) -> None:
        mode_file = tmp_path / "working-mode"
        mode_file.write_text("")
        assert load_working_mode(mode_file) == "unknown"


class TestLoadStimmung:
    def test_reads_stimmung_json(self, tmp_path: Path) -> None:
        stimmung_file = tmp_path / "stimmung.json"
        stimmung_file.write_text(
            json.dumps(
                {
                    "stance": "seeking",
                    "dimensions": {"tension": 0.4, "coherence": 0.8, "depth": 0.6},
                }
            )
        )
        result = load_stimmung(stimmung_file)
        assert result is not None
        assert result["stance"] == "seeking"
        assert "dimensions" in result

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert load_stimmung(tmp_path / "absent.json") is None

    def test_malformed_json_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "stimmung.json"
        f.write_text("not-json {{{")
        assert load_stimmung(f) is None


class TestLoadChronicleRecent:
    def test_reads_recent_events(self, tmp_path: Path) -> None:
        events_file = tmp_path / "events.jsonl"
        # Write three events, only two are recent-and-salient enough.
        events = [
            {
                "ts": "2026-04-24T15:00:00Z",
                "source": "a",
                "summary": "old but salient",
                "salience": 0.9,
            },
            {
                "ts": "2026-04-24T15:50:00Z",
                "source": "b",
                "summary": "recent salient",
                "salience": 0.8,
            },
            {
                "ts": "2026-04-24T15:55:00Z",
                "source": "c",
                "summary": "recent but low salience",
                "salience": 0.3,
            },
        ]
        events_file.write_text("\n".join(json.dumps(e) for e in events))

        now_iso = "2026-04-24T16:00:00Z"
        result = load_chronicle_recent(
            events_file, now_iso=now_iso, window_minutes=30, min_salience=0.6
        )
        summaries = [e["summary"] for e in result]
        assert "recent salient" in summaries
        assert "old but salient" not in summaries  # outside 30-min window
        assert "recent but low salience" not in summaries  # below 0.6 threshold

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        result = load_chronicle_recent(
            tmp_path / "absent.jsonl",
            now_iso="2026-04-24T16:00:00Z",
            window_minutes=30,
            min_salience=0.6,
        )
        assert result == []

    def test_malformed_lines_skipped(self, tmp_path: Path) -> None:
        events_file = tmp_path / "events.jsonl"
        events_file.write_text(
            "\n".join(
                [
                    "not-json {{",
                    json.dumps(
                        {
                            "ts": "2026-04-24T15:50:00Z",
                            "source": "b",
                            "summary": "valid",
                            "salience": 0.9,
                        }
                    ),
                ]
            )
        )
        result = load_chronicle_recent(
            events_file,
            now_iso="2026-04-24T16:00:00Z",
            window_minutes=30,
            min_salience=0.6,
        )
        assert len(result) == 1
        assert result[0]["summary"] == "valid"


class TestRenderNowMarkdown:
    def test_renders_with_full_state(self) -> None:
        state = NowState(
            working_mode="research",
            stimmung={"stance": "nominal", "dominant_dimension": "coherence"},
            chronicle_recent=[{"ts": "2026-04-24T15:50Z", "source": "vla", "summary": "warm tone"}],
            timestamp_iso="2026-04-24T16:00:00Z",
        )
        md = render_now_markdown(state)
        assert "research" in md
        assert "nominal" in md
        assert "warm tone" in md
        assert "2026-04-24T16:00:00Z" in md

    def test_renders_with_missing_state(self) -> None:
        state = NowState(timestamp_iso="2026-04-24T16:00:00Z")
        md = render_now_markdown(state)
        # Should still render — placeholders appear instead of hard-failing.
        assert "now" in md.lower()
        assert "2026-04-24T16:00:00Z" in md

    def test_rendering_is_deterministic(self) -> None:
        state = NowState(working_mode="research", timestamp_iso="2026-04-24T16:00:00Z")
        a = render_now_markdown(state)
        b = render_now_markdown(state)
        assert a == b


class TestSyncPublisher:
    def _make_client(self) -> MagicMock:
        client = MagicMock()
        client.enabled = True
        client.set_now.return_value = {
            "request": {"statusCode": 200},
            "response": {"message": "ok"},
        }
        return client

    def test_sync_calls_set_now_on_first_run(self, tmp_path: Path) -> None:
        client = self._make_client()
        sync = OmgNowSync(
            client=client,
            state_file=tmp_path / "state.json",
            now_fn=lambda: "2026-04-24T16:00:00Z",
            read_working_mode=lambda: "research",
            read_stimmung=lambda: {"stance": "nominal"},
            read_chronicle_recent=lambda: [],
        )
        outcome = sync.run_once()
        assert outcome == "published"
        client.set_now.assert_called_once()
        call = client.set_now.call_args
        assert call.kwargs["content"]
        assert call.kwargs.get("listed") is True

    def test_sync_hash_dedups_when_unchanged(self, tmp_path: Path) -> None:
        client = self._make_client()
        sync = OmgNowSync(
            client=client,
            state_file=tmp_path / "state.json",
            now_fn=lambda: "2026-04-24T16:00:00Z",
            read_working_mode=lambda: "research",
            read_stimmung=lambda: {"stance": "nominal"},
            read_chronicle_recent=lambda: [],
        )
        first = sync.run_once()
        # Second run with same inputs should dedup despite timestamp diff —
        # the NowState strips the timestamp from the hash input since
        # always-changing timestamps would defeat dedup entirely.
        sync._now_fn = lambda: "2026-04-24T16:15:00Z"
        second = sync.run_once()
        assert first == "published"
        assert second == "skipped"
        assert client.set_now.call_count == 1

    def test_sync_republishes_when_state_changes(self, tmp_path: Path) -> None:
        client = self._make_client()
        state = {"working_mode": "research"}
        sync = OmgNowSync(
            client=client,
            state_file=tmp_path / "state.json",
            now_fn=lambda: "2026-04-24T16:00:00Z",
            read_working_mode=lambda: state["working_mode"],
            read_stimmung=lambda: {"stance": "nominal"},
            read_chronicle_recent=lambda: [],
        )
        sync.run_once()
        state["working_mode"] = "rnd"
        second = sync.run_once()
        assert second == "published"
        assert client.set_now.call_count == 2

    def test_dry_run_does_not_call_client(self, tmp_path: Path) -> None:
        client = self._make_client()
        sync = OmgNowSync(
            client=client,
            state_file=tmp_path / "state.json",
            now_fn=lambda: "2026-04-24T16:00:00Z",
            read_working_mode=lambda: "research",
            read_stimmung=lambda: {},
            read_chronicle_recent=lambda: [],
        )
        outcome = sync.run_once(dry_run=True)
        assert outcome == "dry-run"
        client.set_now.assert_not_called()

    def test_disabled_client_returns_client_disabled(self, tmp_path: Path) -> None:
        client = MagicMock()
        client.enabled = False
        sync = OmgNowSync(
            client=client,
            state_file=tmp_path / "state.json",
            now_fn=lambda: "2026-04-24T16:00:00Z",
            read_working_mode=lambda: "research",
            read_stimmung=lambda: {},
            read_chronicle_recent=lambda: [],
        )
        outcome = sync.run_once()
        assert outcome == "client-disabled"
        client.set_now.assert_not_called()

    def test_sync_failure_returns_failed(self, tmp_path: Path) -> None:
        client = self._make_client()
        client.set_now.return_value = None
        sync = OmgNowSync(
            client=client,
            state_file=tmp_path / "state.json",
            now_fn=lambda: "2026-04-24T16:00:00Z",
            read_working_mode=lambda: "research",
            read_stimmung=lambda: {},
            read_chronicle_recent=lambda: [],
        )
        outcome = sync.run_once()
        assert outcome == "failed"

    def test_state_persists_content_hash(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        client = self._make_client()
        sync = OmgNowSync(
            client=client,
            state_file=state_file,
            now_fn=lambda: "2026-04-24T16:00:00Z",
            read_working_mode=lambda: "research",
            read_stimmung=lambda: {},
            read_chronicle_recent=lambda: [],
        )
        sync.run_once()
        persisted = json.loads(state_file.read_text())
        assert "last_content_sha256" in persisted
        assert len(persisted["last_content_sha256"]) == 64
