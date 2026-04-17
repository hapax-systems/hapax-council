"""Tests for Continuous-Loop Research Cadence §3.3 — chat queue file IPC.

Producer (chat-monitor) writes atomic snapshots to SNAPSHOT_PATH after
every push; consumer (daimonion director-loop during `chat`) reads +
unlinks atomically. ``author_id`` is stripped on snapshot write to
preserve the consent guarantee.
"""

from __future__ import annotations

import json
from pathlib import Path


def _q(max_size: int = 20):
    from agents.hapax_daimonion.chat_queue import ChatQueue

    return ChatQueue(max_size=max_size)


def _msg(text: str, ts: float = 0.0, author_id: str = "hidden"):
    from agents.hapax_daimonion.chat_queue import QueuedMessage

    return QueuedMessage(text=text, ts=ts, author_id=author_id)


class TestSnapshotToFile:
    def test_writes_atomic_json(self, tmp_path: Path):
        from agents.hapax_daimonion.chat_queue import snapshot_to_file

        q = _q()
        q.push(_msg("hello", ts=100.0, author_id="alice"))
        target = tmp_path / "snap.json"

        snapshot_to_file(q, path=target)

        payload = json.loads(target.read_text(encoding="utf-8"))
        assert payload == {"messages": [{"text": "hello", "ts": 100.0}]}

    def test_strips_author_id(self, tmp_path: Path):
        from agents.hapax_daimonion.chat_queue import snapshot_to_file

        q = _q()
        q.push(_msg("first", ts=1.0, author_id="alice"))
        q.push(_msg("second", ts=2.0, author_id="bob"))
        target = tmp_path / "snap.json"

        snapshot_to_file(q, path=target)

        raw = target.read_text(encoding="utf-8")
        assert "alice" not in raw
        assert "bob" not in raw
        assert "first" in raw

    def test_empty_queue_writes_empty_messages(self, tmp_path: Path):
        from agents.hapax_daimonion.chat_queue import snapshot_to_file

        q = _q()
        target = tmp_path / "snap.json"
        snapshot_to_file(q, path=target)

        payload = json.loads(target.read_text(encoding="utf-8"))
        assert payload == {"messages": []}

    def test_parent_dir_auto_created(self, tmp_path: Path):
        from agents.hapax_daimonion.chat_queue import snapshot_to_file

        q = _q()
        q.push(_msg("hi"))
        nested = tmp_path / "a" / "b" / "snap.json"
        snapshot_to_file(q, path=nested)
        assert nested.exists()

    def test_overwrites_prior_snapshot(self, tmp_path: Path):
        from agents.hapax_daimonion.chat_queue import snapshot_to_file

        target = tmp_path / "snap.json"
        target.write_text("stale content", encoding="utf-8")

        q = _q()
        q.push(_msg("fresh"))
        snapshot_to_file(q, path=target)

        payload = json.loads(target.read_text(encoding="utf-8"))
        assert payload["messages"][0]["text"] == "fresh"


class TestDrainFromFile:
    def test_missing_file_returns_empty(self, tmp_path: Path):
        from agents.hapax_daimonion.chat_queue import drain_from_file

        assert drain_from_file(path=tmp_path / "nope.json") == []

    def test_malformed_json_returns_empty(self, tmp_path: Path):
        from agents.hapax_daimonion.chat_queue import drain_from_file

        p = tmp_path / "bad.json"
        p.write_text("{not valid", encoding="utf-8")
        assert drain_from_file(path=p) == []

    def test_round_trip(self, tmp_path: Path):
        from agents.hapax_daimonion.chat_queue import drain_from_file, snapshot_to_file

        q = _q()
        q.push(_msg("one", ts=1.0))
        q.push(_msg("two", ts=2.0))
        p = tmp_path / "snap.json"
        snapshot_to_file(q, path=p)

        drained = drain_from_file(path=p)
        assert len(drained) == 2
        assert drained[0].text == "one"
        assert drained[0].ts == 1.0
        assert drained[1].text == "two"
        # Author id stripped in transit; consumer sees default empty string
        assert drained[0].author_id == ""

    def test_unlink_on_read(self, tmp_path: Path):
        from agents.hapax_daimonion.chat_queue import drain_from_file, snapshot_to_file

        q = _q()
        q.push(_msg("only"))
        p = tmp_path / "snap.json"
        snapshot_to_file(q, path=p)

        drain_from_file(path=p)
        assert not p.exists()

    def test_double_drain_returns_empty_second_time(self, tmp_path: Path):
        from agents.hapax_daimonion.chat_queue import drain_from_file, snapshot_to_file

        q = _q()
        q.push(_msg("msg"))
        p = tmp_path / "snap.json"
        snapshot_to_file(q, path=p)

        first = drain_from_file(path=p)
        second = drain_from_file(path=p)
        assert len(first) == 1
        assert second == []

    def test_non_dict_payload_returns_empty(self, tmp_path: Path):
        from agents.hapax_daimonion.chat_queue import drain_from_file

        p = tmp_path / "snap.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        assert drain_from_file(path=p) == []

    def test_non_string_text_entries_skipped(self, tmp_path: Path):
        from agents.hapax_daimonion.chat_queue import drain_from_file

        p = tmp_path / "snap.json"
        p.write_text(
            json.dumps(
                {
                    "messages": [
                        {"text": "good", "ts": 1.0},
                        {"text": None, "ts": 2.0},
                        {"ts": 3.0},  # missing text
                        {"text": "also good", "ts": "not-a-number"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        drained = drain_from_file(path=p)
        assert len(drained) == 2
        assert drained[0].text == "good"
        assert drained[1].text == "also good"
        assert drained[1].ts == 0.0  # malformed ts falls back to 0.0


class TestSnapshotPath:
    def test_default_path_is_shm(self):
        from agents.hapax_daimonion.chat_queue import SNAPSHOT_PATH

        assert str(SNAPSHOT_PATH).startswith("/dev/shm/")
        assert SNAPSHOT_PATH.name == "hapax-chat-queue-snapshot.json"
