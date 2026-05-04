"""Tests for ``agents.hapax_daimonion.cpal.response_dispatch``."""

from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from agents.hapax_daimonion.cpal.chat_destination import ResponseModality
from agents.hapax_daimonion.cpal.response_dispatch import (
    OPERATOR_PLACEHOLDER,
    dispatch_response,
    moderate_chat_text,
)
from agents.publication_bus.publisher_kit.base import PublisherResult
from agents.youtube_chat_reader import (
    clear_reader,
    register_reader,
)


@dataclass
class _Imp:
    source: str = ""
    content: dict = field(default_factory=dict)


@pytest.fixture(autouse=True)
def _reset_reader():
    clear_reader()
    yield
    clear_reader()


def _stub_reader(live_chat_id="abc"):
    reader = MagicMock()
    reader.live_chat_id.return_value = live_chat_id
    return reader


def test_text_chat_only_short_chat_message_posts_no_audio():
    register_reader(_stub_reader("abc"))
    publisher = MagicMock()
    publisher.publish.return_value = PublisherResult(ok=True, detail="ok")
    imp = _Imp(
        source="youtube.live_chat",
        content={"kind": "chat_message", "response_text": "thanks 🙏"},
    )
    result = dispatch_response(imp, publisher=publisher)
    assert result.modality == ResponseModality.TEXT_CHAT
    assert result.chat_result is not None
    assert result.chat_result.ok is True
    assert result.audio_decision is None
    assert publisher.publish.call_count == 1
    payload = publisher.publish.call_args.args[0]
    assert payload.target == "abc"
    assert "thanks" in payload.text


def test_verbal_only_long_chat_message_returns_audio_decision_no_chat():
    register_reader(_stub_reader("abc"))
    publisher = MagicMock()
    long_text = "a longer reply " * 30
    imp = _Imp(
        source="youtube.live_chat",
        content={"kind": "chat_message", "response_text": long_text},
    )
    result = dispatch_response(imp, publisher=publisher)
    assert result.modality == ResponseModality.VERBAL
    assert result.audio_decision is not None
    assert result.chat_result is None
    assert publisher.publish.call_count == 0


def test_both_modality_emits_in_parallel():
    register_reader(_stub_reader("abc"))
    publisher = MagicMock()
    publisher.publish.return_value = PublisherResult(ok=True, detail="ok")
    imp = _Imp(
        source="youtube.live_chat",
        content={
            "kind": "chat_message",
            "response_text": "ok",
            "response_modality_hint": "both",
        },
    )
    result = dispatch_response(imp, publisher=publisher)
    assert result.modality == ResponseModality.BOTH
    assert result.audio_decision is not None
    assert result.chat_result is not None
    assert publisher.publish.call_count == 1


def test_chat_path_skipped_when_no_reader_registered():
    publisher = MagicMock()
    imp = _Imp(
        source="youtube.live_chat",
        content={"kind": "chat_message", "response_text": "thanks"},
    )
    result = dispatch_response(imp, publisher=publisher)
    assert result.modality == ResponseModality.TEXT_CHAT
    assert result.chat_result is None
    assert result.skip_reason == "no_reader_registered"
    assert publisher.publish.call_count == 0


def test_chat_path_skipped_when_live_chat_id_unavailable():
    reader = MagicMock()
    reader.live_chat_id.side_effect = RuntimeError("no broadcast active")
    register_reader(reader)
    publisher = MagicMock()
    imp = _Imp(
        source="youtube.live_chat",
        content={"kind": "chat_message", "response_text": "thanks"},
    )
    result = dispatch_response(imp, publisher=publisher)
    assert result.skip_reason == "live_chat_id_unavailable"
    assert result.chat_result is None
    assert publisher.publish.call_count == 0


def test_drop_modality_emits_nothing():
    register_reader(_stub_reader("abc"))
    publisher = MagicMock()
    imp = _Imp(source="youtube.live_chat", content={"kind": "chat_message"})
    result = dispatch_response(imp, publisher=publisher)
    assert result.modality == ResponseModality.DROP
    assert result.audio_decision is None
    assert result.chat_result is None
    assert publisher.publish.call_count == 0


def test_text_signed_with_operator_referent():
    register_reader(_stub_reader("abc"))
    publisher = MagicMock()
    publisher.publish.return_value = PublisherResult(ok=True, detail="ok")
    imp = _Imp(
        source="youtube.live_chat",
        content={
            "kind": "chat_message",
            "response_text": "noted",
            "impingement_id": "imp-42",
        },
    )
    dispatch_response(imp, publisher=publisher, attribution=True)
    payload = publisher.publish.call_args.args[0]
    referents = ("The Operator", "Oudepode", "Oudepode The Operator", "OTO")
    assert any(r in payload.text for r in referents)
    assert "noted" in payload.text


def test_attribution_can_be_disabled():
    register_reader(_stub_reader("abc"))
    publisher = MagicMock()
    publisher.publish.return_value = PublisherResult(ok=True, detail="ok")
    imp = _Imp(
        source="youtube.live_chat",
        content={"kind": "chat_message", "response_text": "noted"},
    )
    dispatch_response(imp, publisher=publisher, attribution=False)
    payload = publisher.publish.call_args.args[0]
    referents = ("The Operator", "Oudepode", "Oudepode The Operator", "OTO")
    assert not any(r in payload.text for r in referents)
    assert payload.text == "noted"


def test_sticky_referent_per_impingement():
    register_reader(_stub_reader("abc"))
    publisher = MagicMock()
    publisher.publish.return_value = PublisherResult(ok=True, detail="ok")
    imp = _Imp(
        source="youtube.live_chat",
        content={
            "kind": "chat_message",
            "response_text": "noted",
            "impingement_id": "imp-stable",
        },
    )
    dispatch_response(imp, publisher=publisher, attribution=True)
    first_text = publisher.publish.call_args.args[0].text
    publisher.publish.reset_mock()
    dispatch_response(imp, publisher=publisher, attribution=True)
    second_text = publisher.publish.call_args.args[0].text
    assert first_text == second_text


# ── moderate_chat_text ────────────────────────────────────────────────────


REFERENTS = ("The Operator", "Oudepode", "Oudepode The Operator", "OTO")


def test_moderate_substitutes_operator_placeholder():
    out = moderate_chat_text(
        f"now spinning at {OPERATOR_PLACEHOLDER}'s desk",
        impingement_id="imp-1",
    )
    assert OPERATOR_PLACEHOLDER not in out
    assert any(r in out for r in REFERENTS)


def test_moderate_no_placeholder_passes_through():
    out = moderate_chat_text("plain text without placeholder", impingement_id="imp-1")
    assert out == "plain text without placeholder"


def test_moderate_sticky_per_impingement():
    text = f"{OPERATOR_PLACEHOLDER} says hi"
    first = moderate_chat_text(text, impingement_id="imp-stable")
    second = moderate_chat_text(text, impingement_id="imp-stable")
    assert first == second


def test_moderate_replaces_all_occurrences():
    out = moderate_chat_text(
        f"{OPERATOR_PLACEHOLDER} likes {OPERATOR_PLACEHOLDER}'s couch",
        impingement_id="imp-1",
    )
    assert OPERATOR_PLACEHOLDER not in out
    # Both placeholders use the same sticky pick, so the same referent appears
    # at both positions.
    referent = next(r for r in REFERENTS if r in out)
    assert out.count(referent) == 2


def test_dispatch_substitutes_placeholder_in_chat_post():
    register_reader(_stub_reader("abc"))
    publisher = MagicMock()
    publisher.publish.return_value = PublisherResult(ok=True, detail="ok")
    imp = _Imp(
        source="youtube.live_chat",
        content={
            "kind": "chat_message",
            "response_text": f"thanks from {OPERATOR_PLACEHOLDER}",
            "impingement_id": "imp-99",
        },
    )
    dispatch_response(imp, publisher=publisher, attribution=False)
    payload = publisher.publish.call_args.args[0]
    assert OPERATOR_PLACEHOLDER not in payload.text
    assert any(r in payload.text for r in REFERENTS)


def test_dispatch_moderation_runs_even_when_attribution_disabled():
    """Moderation is independent of the attribution suffix.

    Operator-referent policy applies to placeholder substitution
    unconditionally — the attribution flag only controls the trailing
    suffix sign, not whether the placeholder gets resolved.
    """
    register_reader(_stub_reader("abc"))
    publisher = MagicMock()
    publisher.publish.return_value = PublisherResult(ok=True, detail="ok")
    imp = _Imp(
        source="youtube.live_chat",
        content={
            "kind": "chat_message",
            "response_text": f"hello from {OPERATOR_PLACEHOLDER}",
            "impingement_id": "imp-100",
        },
    )
    dispatch_response(imp, publisher=publisher, attribution=False)
    payload = publisher.publish.call_args.args[0]
    assert OPERATOR_PLACEHOLDER not in payload.text
    # No attribution suffix appended (attribution=False), so no " — " separator.
    assert " — " not in payload.text
