"""Tests for ``agents.hapax_daimonion.cpal.chat_destination``."""

from dataclasses import dataclass, field

from agents.hapax_daimonion.cpal.chat_destination import (
    ChatDestination,
    ResponseModality,
    classify_response_modality,
)


@dataclass
class _Imp:
    source: str = ""
    content: dict = field(default_factory=dict)


def test_chat_destination_enum_values():
    assert ChatDestination.YOUTUBE_LIVE_CHAT.value == "youtube_live_chat"


def test_response_modality_values():
    assert {m.value for m in ResponseModality} == {"verbal", "text_chat", "both", "drop"}


def test_chat_message_short_response_text_only():
    imp = _Imp(
        source="youtube.live_chat",
        content={"kind": "chat_message", "response_text": "thanks 🙏"},
    )
    assert classify_response_modality(imp) == ResponseModality.TEXT_CHAT


def test_chat_message_long_response_verbal_only():
    long_text = "I think the deeper point here is that " + "x " * 200
    imp = _Imp(
        source="youtube.live_chat",
        content={"kind": "chat_message", "response_text": long_text},
    )
    assert classify_response_modality(imp) == ResponseModality.VERBAL


def test_chat_message_with_both_intent():
    imp = _Imp(
        source="youtube.live_chat",
        content={
            "kind": "chat_message",
            "response_text": "ok",
            "response_modality_hint": "both",
        },
    )
    assert classify_response_modality(imp) == ResponseModality.BOTH


def test_non_chat_impingement_routes_verbal():
    imp = _Imp(source="microphone.blue_yeti", content={"response_text": "x"})
    assert classify_response_modality(imp) == ResponseModality.VERBAL


def test_empty_response_text_drops():
    imp = _Imp(source="youtube.live_chat", content={"kind": "chat_message"})
    assert classify_response_modality(imp) == ResponseModality.DROP


def test_none_impingement_drops():
    assert classify_response_modality(None) == ResponseModality.DROP


def test_chat_prefix_alternate():
    imp = _Imp(
        source="chat.discord",
        content={"kind": "chat_message", "response_text": "hi"},
    )
    assert classify_response_modality(imp) == ResponseModality.TEXT_CHAT


def test_invalid_hint_falls_through_to_length_classification():
    imp = _Imp(
        source="youtube.live_chat",
        content={
            "kind": "chat_message",
            "response_text": "x",
            "response_modality_hint": "garbage",
        },
    )
    assert classify_response_modality(imp) == ResponseModality.TEXT_CHAT
