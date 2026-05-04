"""Sanitization rules for live-chat text."""

from __future__ import annotations

from agents.youtube_chat_reader.sanitize import (
    MAX_LENGTH,
    extract_signals,
    sanitize_message,
)


def test_empty_input_returns_empty() -> None:
    assert sanitize_message("") == ""
    assert sanitize_message(None) == ""


def test_strips_control_characters() -> None:
    raw = "hello\x00\x01\x07world\x7f"
    assert sanitize_message(raw) == "helloworld"


def test_replaces_urls_with_placeholder() -> None:
    raw = "check out https://evil.example.com/payload now"
    cleaned = sanitize_message(raw)
    assert "https://" not in cleaned
    assert "[link]" in cleaned


def test_collapses_whitespace_runs() -> None:
    raw = "hello   \t\n\n  world"
    assert sanitize_message(raw) == "hello world"


def test_caps_length_with_ellipsis() -> None:
    raw = "x" * (MAX_LENGTH * 2)
    cleaned = sanitize_message(raw)
    assert len(cleaned) == MAX_LENGTH
    assert cleaned.endswith("…")


def test_nfkc_normalizes_compat_chars() -> None:
    # Fullwidth ASCII collapses to ASCII via NFKC.
    raw = "ＨＥＬＬＯ"
    assert sanitize_message(raw) == "HELLO"


def test_extract_signals_detects_question() -> None:
    s = extract_signals("Is hapax listening?")
    assert s["has_question"]
    assert not s["has_mention"]
    assert not s["is_command"]


def test_extract_signals_detects_mention() -> None:
    s = extract_signals("@hapax can you hear me")
    assert s["has_mention"]
    assert not s["has_question"]


def test_extract_signals_detects_command() -> None:
    s = extract_signals("!preset dub")
    assert s["is_command"]


def test_extract_signals_length_matches_text() -> None:
    text = "hello world"
    s = extract_signals(text)
    assert s["length"] == len(text)
