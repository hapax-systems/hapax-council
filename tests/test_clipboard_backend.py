"""Tests for clipboard intent classification backend."""

from __future__ import annotations

from agents.hapax_daimonion.backends.clipboard import classify_clipboard


class TestClipboardClassification:
    def test_empty(self):
        assert classify_clipboard("") == "empty"
        assert classify_clipboard("   ") == "empty"

    def test_url(self):
        assert classify_clipboard("https://example.com/path") == "url"
        assert classify_clipboard("check http://foo.bar") == "url"

    def test_error_stacktrace(self):
        assert classify_clipboard("Traceback (most recent call last):") == "error"
        assert classify_clipboard("TypeError: cannot read property") == "error"
        assert classify_clipboard("FAILED test_something") == "error"
        assert classify_clipboard("panic: runtime error") == "error"

    def test_code_snippet(self):
        assert classify_clipboard("def foo():\n    return 42") == "code"
        assert classify_clipboard("const x = {a: 1};") == "code"

    def test_plain_text(self):
        assert classify_clipboard("Just a regular sentence.") == "text"
        assert classify_clipboard("Meeting notes from today") == "text"
