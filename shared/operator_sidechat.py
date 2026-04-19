"""shared/operator_sidechat.py — Operator → Hapax private channel (task #132).

A private, local-only JSONL channel for the operator to whisper notes or
commands to the daimonion during a livestream, separate from the public
twitch chat. Distinct from the KDEConnect bridge (phone → commands);
sidechat is natural-language input that becomes an ``Impingement`` on the
daimonion's affordance loop.

**Privacy invariant (constitutional):** sidechat content is LOCAL-ONLY.
Nothing written to the JSONL is ever copied to twitch / YouTube / chat
surfaces or any other egress. The sidechat path is NOT in any egress
allowlist — it is only read by in-process consumers that dispatch to
local capabilities.

**Transport:** append-only JSONL at
``/dev/shm/hapax-compositor/operator-sidechat.jsonl`` written via
``O_APPEND`` so concurrent writers from multiple processes produce
well-formed, non-interleaved lines (POSIX atomic append for writes up to
PIPE_BUF, which PIPE_BUF ≥ 4096 covers — well above our 2048 text cap).

**Record format:** one JSON object per line::

    {"ts": 1776563400.123, "role": "operator", "text": "...",
     "channel": "sidechat", "msg_id": "hex12"}

**Producer / consumer API:**

- :func:`append_sidechat` — write one message (O_APPEND).
- :func:`tail_sidechat` — iterate messages since a timestamp.
- :func:`stream_sidechat` — async iterator over live messages (watchdog
  preferred, polling fallback at 0.5s cadence).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "SIDECHAT_PATH",
    "SIDECHAT_MAX_TEXT_LEN",
    "SIDECHAT_MAX_LINE_BYTES",
    "SidechatMessage",
    "append_sidechat",
    "tail_sidechat",
    "stream_sidechat",
]

log = logging.getLogger(__name__)

# Canonical JSONL path. Consumers read from here; producers append here.
SIDECHAT_PATH: Path = Path("/dev/shm/hapax-compositor/operator-sidechat.jsonl")

# Per-message text length cap. Past this, the message is rejected at the
# Pydantic layer — callers should surface the validation error to the UI
# rather than silently truncating.
SIDECHAT_MAX_TEXT_LEN: int = 2000

# Per-line byte cap (defense-in-depth on the file, not just the text).
# 64 KB is comfortably above 2000 UTF-8 chars even in worst-case
# encoding expansion.
SIDECHAT_MAX_LINE_BYTES: int = 64 * 1024


class SidechatMessage(BaseModel):
    """One operator → Hapax sidechat utterance.

    Immutable after construction. Validation fails closed: empty text or
    text past :data:`SIDECHAT_MAX_TEXT_LEN` raises ``ValidationError`` so
    the caller can surface it to the operator.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ts: float = Field(description="Unix timestamp (seconds, float).")
    role: Literal["operator", "hapax"] = Field(
        default="operator",
        description="Who wrote this line. Hapax replies in the same channel get role='hapax'.",
    )
    text: str = Field(description="Utterance body.")
    channel: Literal["sidechat"] = Field(
        default="sidechat",
        description="Channel tag — pinned so the record is self-describing on disk.",
    )
    msg_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex[:12],
        description="Opaque id for dedup / cursor tracking by consumers.",
    )

    @field_validator("text")
    @classmethod
    def _validate_text(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("sidechat text must be non-empty")
        if len(v) > SIDECHAT_MAX_TEXT_LEN:
            raise ValueError(f"sidechat text exceeds {SIDECHAT_MAX_TEXT_LEN} chars (got {len(v)})")
        return v


def _ensure_parent(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        log.debug("Could not create sidechat parent %s", path.parent, exc_info=True)


def append_sidechat(
    text: str,
    *,
    ts: float | None = None,
    role: Literal["operator", "hapax"] = "operator",
    path: Path | None = None,
) -> SidechatMessage:
    """Append a sidechat message to the JSONL, atomically.

    Writes via ``os.open(..., O_APPEND | O_CREAT | O_WRONLY)`` so concurrent
    writers from multiple processes produce well-formed JSONL (POSIX
    atomic append for writes within PIPE_BUF, which is 4096+ on Linux —
    our 64 KB line cap is outside that guarantee, but for 2000-char
    messages we stay well under).

    Parameters
    ----------
    text : str
        Utterance body. Must be non-empty and ≤ SIDECHAT_MAX_TEXT_LEN.
    ts : float | None
        Timestamp. Defaults to :func:`time.time()` when omitted.
    role : {"operator", "hapax"}
        Who authored the line. Defaults to "operator".
    path : Path | None
        Override JSONL path (tests, relocation). Defaults to
        :data:`SIDECHAT_PATH`.

    Returns
    -------
    SidechatMessage
        The record actually written.
    """
    target = path if path is not None else SIDECHAT_PATH
    msg = SidechatMessage(
        ts=ts if ts is not None else time.time(),
        role=role,
        text=text,
    )
    line = msg.model_dump_json() + "\n"
    encoded = line.encode("utf-8")
    if len(encoded) > SIDECHAT_MAX_LINE_BYTES:
        raise ValueError(
            f"sidechat line exceeds {SIDECHAT_MAX_LINE_BYTES} bytes after serialization"
        )
    _ensure_parent(target)
    # O_APPEND guarantees the kernel serializes writes at the end of file;
    # individual writes up to PIPE_BUF are atomic on Linux. Our lines are
    # well under that threshold.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, encoded)
    finally:
        os.close(fd)
    return msg


def _iter_messages(path: Path) -> Iterator[SidechatMessage]:
    """Yield every parseable message in ``path`` (malformed lines skipped)."""
    if not path.exists():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        log.debug("Failed to read sidechat %s", path, exc_info=True)
        return
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
            yield SidechatMessage.model_validate(obj)
        except Exception:
            log.debug("Malformed sidechat line skipped: %s", stripped[:80])
            continue


def tail_sidechat(
    since_ts: float | None = None,
    *,
    path: Path | None = None,
) -> Iterator[SidechatMessage]:
    """Iterate messages with ``ts > since_ts``, chronologically.

    Returns an iterator rather than a list so callers can short-circuit
    on the first match when tailing large files.
    """
    target = path if path is not None else SIDECHAT_PATH
    cutoff = since_ts if since_ts is not None else float("-inf")
    for msg in _iter_messages(target):
        if msg.ts > cutoff:
            yield msg


async def stream_sidechat(
    *,
    path: Path | None = None,
    poll_interval_s: float = 0.5,
) -> AsyncIterator[SidechatMessage]:
    """Async iterator yielding new sidechat messages as they are appended.

    Uses ``watchdog`` when available (inotify on Linux) for low-latency
    wake-up, falling back to a ``poll_interval_s`` polling loop when
    watchdog is missing or import fails. Initial state is "last line
    seen" — callers that need historical replay should call
    :func:`tail_sidechat` first.

    Polling uses ``ts`` cursor, not byte offset, so a rotated file that
    rewrites timestamps will still be handled sanely (messages with
    ``ts > last_seen_ts`` fire; older ones are ignored).
    """
    target = path if path is not None else SIDECHAT_PATH
    _ensure_parent(target)

    # Seed cursor at the latest ts currently in file (skip backlog).
    last_ts: float = float("-inf")
    for msg in _iter_messages(target):
        if msg.ts > last_ts:
            last_ts = msg.ts

    # Watchdog-backed event for low-latency wakeup. Pure polling is the
    # fallback — correctness is identical, latency differs.
    wake = asyncio.Event()
    observer = None
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        loop = asyncio.get_running_loop()

        class _Handler(FileSystemEventHandler):
            def on_modified(self, event) -> None:  # type: ignore[no-untyped-def]
                if getattr(event, "src_path", None) and str(target) in event.src_path:
                    loop.call_soon_threadsafe(wake.set)

            def on_created(self, event) -> None:  # type: ignore[no-untyped-def]
                if getattr(event, "src_path", None) and str(target) in event.src_path:
                    loop.call_soon_threadsafe(wake.set)

        observer = Observer()
        observer.schedule(_Handler(), str(target.parent), recursive=False)
        observer.start()
    except Exception:
        log.debug("watchdog unavailable — falling back to polling sidechat", exc_info=True)
        observer = None

    try:
        while True:
            for msg in _iter_messages(target):
                if msg.ts > last_ts:
                    last_ts = msg.ts
                    yield msg
            try:
                await asyncio.wait_for(wake.wait(), timeout=poll_interval_s)
            except TimeoutError:
                pass
            wake.clear()
    finally:
        if observer is not None:
            try:
                observer.stop()
                observer.join(timeout=1.0)
            except Exception:
                log.debug("sidechat watchdog observer shutdown error", exc_info=True)
