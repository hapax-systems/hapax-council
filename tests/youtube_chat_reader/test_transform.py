"""Pure-function transforms: chat item → bus + state records."""

from __future__ import annotations

from agents.youtube_chat_reader.anonymize import AuthorAnonymizer
from agents.youtube_chat_reader.transform import (
    BASE_STRENGTH,
    MENTION_STRENGTH_BONUS,
    QUESTION_STRENGTH_BONUS,
    SOURCE_TAG,
    build_bus_record,
    build_state_record,
    extract_published_at_ts,
    interrupt_token_for,
)


def _item(
    *,
    message: str,
    author_id: str = "UC-test-author",
    item_id: str = "msg-1",
    published_at: str = "2026-05-04T02:31:14.123456Z",
) -> dict:
    return {
        "id": item_id,
        "snippet": {
            "displayMessage": message,
            "publishedAt": published_at,
        },
        "authorDetails": {
            "channelId": author_id,
        },
    }


def test_interrupt_token_prefers_command() -> None:
    s = {"is_command": True, "has_mention": True, "has_question": True}
    assert interrupt_token_for(s) == "chat_command"


def test_interrupt_token_falls_through_to_mention() -> None:
    s = {"is_command": False, "has_mention": True, "has_question": True}
    assert interrupt_token_for(s) == "chat_mention"


def test_interrupt_token_falls_through_to_question() -> None:
    s = {"is_command": False, "has_mention": False, "has_question": True}
    assert interrupt_token_for(s) == "chat_question"


def test_interrupt_token_default_chat_message() -> None:
    s = {"is_command": False, "has_mention": False, "has_question": False}
    assert interrupt_token_for(s) == "chat_message"


def test_extract_published_at_parses_rfc3339() -> None:
    ts = extract_published_at_ts(_item(message="x"))
    assert ts > 0


def test_extract_published_at_falls_back_on_missing_field() -> None:
    item = {"snippet": {}}
    ts = extract_published_at_ts(item, fallback=12345.0)
    assert ts == 12345.0


def test_build_bus_record_has_required_fields() -> None:
    anon = AuthorAnonymizer()
    record = build_bus_record(
        _item(message="hello world"),
        anonymizer=anon,
        broadcast_id="bcast-1",
    )
    assert record is not None
    assert record["source"] == SOURCE_TAG
    assert record["type"] == "pattern_match"
    assert record["interrupt_token"] == "chat_message"
    assert record["strength"] == BASE_STRENGTH
    assert record["content"]["text"] == "hello world"
    assert record["content"]["broadcast_id"] == "bcast-1"
    assert record["content"]["narrative"].startswith("chat message arrived")


def test_build_bus_record_strength_boosts_for_mention_and_question() -> None:
    anon = AuthorAnonymizer()
    record = build_bus_record(
        _item(message="@hapax are you listening?"),
        anonymizer=anon,
    )
    assert record is not None
    expected = BASE_STRENGTH + MENTION_STRENGTH_BONUS + QUESTION_STRENGTH_BONUS
    assert record["strength"] == expected
    assert record["interrupt_token"] == "chat_mention"


def test_build_bus_record_drops_empty_after_sanitize() -> None:
    """Whitespace-only messages must not reach the bus."""
    anon = AuthorAnonymizer()
    record = build_bus_record(
        _item(message="   \x00\x01\x02   "),
        anonymizer=anon,
    )
    assert record is None


def test_build_bus_record_strips_urls_in_text() -> None:
    anon = AuthorAnonymizer()
    record = build_bus_record(
        _item(message="check https://evil.example.com/x out"),
        anonymizer=anon,
    )
    assert record is not None
    text = record["content"]["text"]
    assert "https://" not in text
    assert "[link]" in text


def test_bus_record_does_not_leak_raw_author_id() -> None:
    """The author's channelId must never appear anywhere in the record."""
    anon = AuthorAnonymizer()
    raw_author = "UC-secret-author-id"
    record = build_bus_record(
        _item(message="hello", author_id=raw_author),
        anonymizer=anon,
    )
    assert record is not None
    serialized = repr(record)
    assert raw_author not in serialized


def test_state_record_carries_same_token_as_bus() -> None:
    """State + bus records must share the in-session author token so
    consumers can correlate without round-tripping."""
    anon = AuthorAnonymizer()
    bus = build_bus_record(_item(message="hello"), anonymizer=anon)
    state = build_state_record(_item(message="hello"), anonymizer=anon)
    assert bus is not None
    assert state is not None
    assert bus["content"]["author_token"] == state["author_token"]


def test_state_record_includes_signals() -> None:
    anon = AuthorAnonymizer()
    state = build_state_record(
        _item(message="@hapax got a question?"),
        anonymizer=anon,
    )
    assert state is not None
    assert state["has_mention"]
    assert state["has_question"]
    assert state["text"] == "@hapax got a question?"


def test_state_record_drops_empty_after_sanitize() -> None:
    anon = AuthorAnonymizer()
    state = build_state_record(
        _item(message="   \x00   "),
        anonymizer=AuthorAnonymizer(),
    )
    assert state is None
    # Coverage of the second arg path:
    assert anon.token("anyone") != ""
