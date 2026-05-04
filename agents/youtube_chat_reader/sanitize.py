"""Message-text sanitization for live-chat ingestion.

Chat input is adversarial: URLs (exfiltration / link-bait), control
characters (terminal-injection / log-poisoning), Unicode confusables
(homograph attacks against pattern matching), and arbitrarily long
strings (prompt-injection / log volume). Everything that flows
downstream — impingement bus, chat-state surface, LLM context — goes
through :func:`sanitize_message` first.

Sanitization is conservative-by-default but content-preserving: we
strip dangerous shape, never silently translate semantics. If a
message becomes empty after sanitization the caller should drop it.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["MAX_LENGTH", "sanitize_message", "extract_signals"]

MAX_LENGTH = 240

_URL_RE = re.compile(r"https?://\S+", flags=re.IGNORECASE)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")
_MENTION_RE = re.compile(r"@\w+")
_QUESTION_RE = re.compile(r"\?")


def sanitize_message(raw: str | None) -> str:
    """Return a sanitized, length-capped, NFKC-normalised version of ``raw``.

    Order matters: NFKC first so confusables collapse to canonical
    ASCII before regex; control-char strip second because some control
    chars survive NFKC; URL strip third (URLs only meaningful as URLs);
    whitespace collapse last so the length cap operates on visible
    glyphs rather than runs of spaces.
    """
    if not raw:
        return ""
    text = unicodedata.normalize("NFKC", raw)
    text = _CONTROL_RE.sub("", text)
    text = _URL_RE.sub("[link]", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if len(text) > MAX_LENGTH:
        text = text[: MAX_LENGTH - 1] + "…"
    return text


def extract_signals(clean_text: str) -> dict[str, bool | int]:
    """Compute structural signals from sanitized chat text.

    These flow into impingement strength / interrupt-token selection
    without exposing the raw message to consumers that don't need it.
    Pure on the input string — no regex side effects, no I/O.
    """
    return {
        "length": len(clean_text),
        "has_question": bool(_QUESTION_RE.search(clean_text)),
        "has_mention": bool(_MENTION_RE.search(clean_text)),
        "is_command": clean_text.startswith("!") if clean_text else False,
    }
