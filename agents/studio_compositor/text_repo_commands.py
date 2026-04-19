"""Sidechat command parsers for the Hapax-managed text repo (#126).

The operator whispers ``add-text <body>`` / ``rotate-text`` via
``hapax-sidechat``; these helpers recognize the commands and convert them
into :class:`shared.text_repo.TextRepo` operations. Mirrors the
``link <url>`` parser in :mod:`agents.studio_compositor.yt_shared_links`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from shared.text_repo import TextEntry, TextRepo

__all__ = [
    "ADD_TEXT_PREFIX",
    "ROTATE_TEXT_TOKEN",
    "parse_add_text_command",
    "is_rotate_text_command",
    "apply_sidechat_command",
]

log = logging.getLogger(__name__)

ADD_TEXT_PREFIX: str = "add-text"
ROTATE_TEXT_TOKEN: str = "rotate-text"


def parse_add_text_command(text: str) -> str | None:
    """Return the entry body if ``text`` is an ``add-text <body>`` command.

    Lenient parsing: accepts leading / trailing whitespace and is
    case-insensitive on the prefix. Returns ``None`` if ``text`` is not
    an add-text command or the body after the prefix is empty.
    """
    if not text:
        return None
    stripped = text.strip()
    lower = stripped.lower()
    if not lower.startswith(ADD_TEXT_PREFIX):
        return None
    tail = stripped[len(ADD_TEXT_PREFIX) :]
    # Require at least one whitespace separator so "add-texty" isn't a hit.
    if tail and not tail[0].isspace():
        return None
    body = tail.strip()
    return body or None


def is_rotate_text_command(text: str) -> bool:
    """True when ``text`` is exactly the ``rotate-text`` token (trimmed)."""
    if not text:
        return False
    return text.strip().lower() == ROTATE_TEXT_TOKEN


def apply_sidechat_command(
    text: str,
    *,
    repo: TextRepo | None = None,
    path: Path | None = None,
) -> TextEntry | bool | None:
    """Dispatch an ``add-text`` / ``rotate-text`` sidechat command.

    Returns:
        * The created :class:`TextEntry` when an ``add-text`` command was
          recognized and persisted.
        * ``True`` when a ``rotate-text`` command was recognized (the
          overlay zone runner re-reads the repo on every tick, so the
          "rotation" is simply invalidating any cached selection).
        * ``None`` when the text is not a text-repo command — the caller
          should fall through to normal sidechat handling.

    ``repo`` is injectable for tests; production callers should omit it
    and rely on the default :class:`TextRepo` at
    :data:`shared.text_repo.DEFAULT_REPO_PATH`.
    """
    body = parse_add_text_command(text)
    if body is not None:
        target = repo if repo is not None else TextRepo(path=path)
        try:
            if repo is None:
                target.load()
            entry = target.add_entry(body, tags=["sidechat"])
            log.info("Sidechat add-text: %s (%s)", entry.id, body[:80])
            return entry
        except Exception:
            log.debug("apply_sidechat_command add-text failed", exc_info=True)
            return None
    if is_rotate_text_command(text):
        log.info("Sidechat rotate-text received; overlay zone will reselect on next tick")
        return True
    return None
