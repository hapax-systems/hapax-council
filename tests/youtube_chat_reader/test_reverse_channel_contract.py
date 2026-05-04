"""ChatReader satisfies the reverse-channel Protocol consumed by
the chat-poster lane (cc-task ``chat-response-verbal-and-text``)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from prometheus_client import CollectorRegistry

from agents.youtube_chat_reader import (
    ChatMessageSnapshot,
    ChatReader,
    YoutubeChatReader,
    YoutubeChatReaderUnavailable,
    clear_reader,
    get_active_reader,
    register_reader,
)


@pytest.fixture(autouse=True)
def _isolate_registry() -> None:
    """Each test starts with no registered reader."""
    clear_reader()
    yield
    clear_reader()


def _make_reader(tmp_path: Path) -> ChatReader:
    client = MagicMock()
    client.enabled = True
    client.yt = MagicMock()
    return ChatReader(
        client=client,
        impingement_path=tmp_path / "i.jsonl",
        chat_state_path=tmp_path / "s.jsonl",
        registry=CollectorRegistry(),
    )


def test_chat_reader_implements_protocol(tmp_path: Path) -> None:
    """Structural Protocol satisfaction — ChatReader must walk like a duck.

    The Protocol is not ``@runtime_checkable`` (kept clean by design),
    so verify the contract surface manually.
    """
    reader = _make_reader(tmp_path)
    assert callable(reader.live_chat_id)
    assert callable(reader.recent_messages)
    # Protocol type imports without ImportError == module-level wiring is intact.
    assert YoutubeChatReader is not None


def test_live_chat_id_raises_when_idle(tmp_path: Path) -> None:
    reader = _make_reader(tmp_path)
    with pytest.raises(YoutubeChatReaderUnavailable):
        reader.live_chat_id()


def test_live_chat_id_returns_active_id(tmp_path: Path) -> None:
    reader = _make_reader(tmp_path)
    reader._active_live_chat_id = "LC-abc"  # noqa: SLF001 — direct state for test
    assert reader.live_chat_id() == "LC-abc"


def test_recent_messages_returns_snapshots(tmp_path: Path) -> None:
    reader = _make_reader(tmp_path)
    reader._ring.append(  # noqa: SLF001
        {
            "author_token": "abc123",
            "text": "hello",
            "length": 5,
            "ts": 1000.0,
        }
    )
    snaps = reader.recent_messages(limit=10)
    assert len(snaps) == 1
    assert isinstance(snaps[0], ChatMessageSnapshot)
    assert snaps[0].author_hash == "abc123"
    assert snaps[0].text == "hello"
    assert snaps[0].sentiment == 0.0
    assert snaps[0].length == 5
    assert snaps[0].posted_at_unix == 1000.0


def test_recent_messages_caps_at_limit(tmp_path: Path) -> None:
    reader = _make_reader(tmp_path)
    for i in range(20):
        reader._ring.append(  # noqa: SLF001
            {
                "author_token": f"a{i}",
                "text": f"m{i}",
                "length": 2,
                "ts": float(i),
            }
        )
    snaps = reader.recent_messages(limit=5)
    assert len(snaps) == 5
    # Last 5 — most recent.
    assert [s.text for s in snaps] == ["m15", "m16", "m17", "m18", "m19"]


def test_register_and_get_active_reader_round_trip(tmp_path: Path) -> None:
    assert get_active_reader() is None
    reader = _make_reader(tmp_path)
    register_reader(reader)
    assert get_active_reader() is reader


def test_register_is_idempotent_last_write_wins(tmp_path: Path) -> None:
    r1 = _make_reader(tmp_path)
    r2 = _make_reader(tmp_path)
    register_reader(r1)
    register_reader(r2)
    assert get_active_reader() is r2
