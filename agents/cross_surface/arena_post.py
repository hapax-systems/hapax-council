"""Are.na poster — auto-publish livestream/research artifacts to a Hapax channel.

Tails ``/dev/shm/hapax-broadcast/events.jsonl`` and posts to Are.na on
each ``broadcast_rotated`` event via the ``arena`` Python client. Uses
the same JSONL-cursor + allowlist-gate + dry-run-default pattern as
the Bluesky poster (``bluesky_post.py``).

## Why Are.na

Are.na is the operative research-surface for the AGR (Acid Graphics
Revival) scene + Schwulst / Broskoski / Mindy Seu adjacent network.
The *citation-density* posture — every block annotated with technique,
WGSL preset, livestream timestamp — is the AGR-native legibility
move. Bot-permissive culture as long as the persona is named and the
curation has a soul (frnsys/arena patterns + Are.na Community Dev
Lounge). One block per ``broadcast_rotated`` event lands within
typical scene cadence (3-6/day).

## Auth

Personal Access Token authentication. Operator generates a token at
``https://dev.are.na/oauth/applications`` and exports via hapax-secrets:

  HAPAX_ARENA_TOKEN          # PAT, opaque string
  HAPAX_ARENA_CHANNEL_SLUG   # e.g. "hapax-visual-surface-auto-curated"

Without either, the daemon idles + logs ``no_credentials`` per event.

## Composition

Reuses ``metadata_composer.compose_metadata(scope="cross_surface")``;
the ``arena_block`` field carries the post text (≤ 4096 chars per
Are.na block-content limit, no enforced ceiling here since composer
is conservative). The block source URL — when present in the
triggering event — becomes a link-block; otherwise text-block.

## Rate limit

Are.na has no documented rate limits but the contract caps at
6/hour, 30/day to mirror Bluesky discipline.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal as _signal
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

from prometheus_client import REGISTRY, CollectorRegistry, Counter, start_http_server

from shared.governance.publication_allowlist import check as allowlist_check

log = logging.getLogger(__name__)

EVENT_PATH = Path(
    os.environ.get("HAPAX_BROADCAST_EVENT_PATH", "/dev/shm/hapax-broadcast/events.jsonl")
)
DEFAULT_CURSOR_PATH = Path(
    os.environ.get(
        "HAPAX_ARENA_CURSOR",
        str(Path.home() / ".cache/hapax/arena-post-cursor.txt"),
    )
)
METRICS_PORT: int = int(os.environ.get("HAPAX_ARENA_METRICS_PORT", "9504"))
DEFAULT_TICK_S: float = float(os.environ.get("HAPAX_ARENA_TICK_S", "30"))
ARENA_BLOCK_TEXT_LIMIT = 4096

ALLOWLIST_SURFACE = "arena-post"
ALLOWLIST_STATE_KIND = "broadcast.boundary"
EVENT_TYPE = "broadcast_rotated"


class ArenaPoster:
    """Tail broadcast events; post to a Hapax-owned Are.na channel per rotation."""

    def __init__(
        self,
        *,
        token: str | None = None,
        channel_slug: str | None = None,
        compose_fn=None,
        client_factory=None,
        event_path: Path = EVENT_PATH,
        cursor_path: Path = DEFAULT_CURSOR_PATH,
        registry: CollectorRegistry = REGISTRY,
        tick_s: float = DEFAULT_TICK_S,
        dry_run: bool = False,
    ) -> None:
        self._token = token
        self._channel_slug = channel_slug
        self._compose_fn = compose_fn
        self._client_factory = client_factory
        self._event_path = event_path
        self._cursor_path = cursor_path
        self._tick_s = max(1.0, tick_s)
        self._dry_run = dry_run
        self._stop_evt = threading.Event()
        self._client = None  # built on first non-dry-run apply

        self.posts_total = Counter(
            "hapax_broadcast_arena_posts_total",
            "Are.na blocks attempted, broken down by outcome.",
            ["result"],
            registry=registry,
        )

    # ── Public API ────────────────────────────────────────────────────

    def run_once(self) -> int:
        cursor = self._read_cursor()
        handled = 0
        for event, byte_after in self._tail_from(cursor):
            if event.get("event_type") != EVENT_TYPE:
                cursor = byte_after
                continue
            self._apply(event)
            cursor = byte_after
            handled += 1
        if handled:
            self._write_cursor(cursor)
        return handled

    def run_forever(self) -> None:
        for sig in (_signal.SIGTERM, _signal.SIGINT):
            try:
                _signal.signal(sig, lambda *_: self._stop_evt.set())
            except ValueError:
                pass

        log.info(
            "arena poster starting, port=%d tick=%.1fs dry_run=%s channel=%s",
            METRICS_PORT,
            self._tick_s,
            self._dry_run,
            self._channel_slug or "<unset>",
        )
        while not self._stop_evt.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001
                log.exception("tick failed; continuing on next cadence")
            self._stop_evt.wait(self._tick_s)

    def stop(self) -> None:
        self._stop_evt.set()

    # ── Cursor + tail ─────────────────────────────────────────────────

    def _read_cursor(self) -> int:
        try:
            return int(self._cursor_path.read_text().strip())
        except (FileNotFoundError, ValueError):
            return 0

    def _write_cursor(self, byte_offset: int) -> None:
        try:
            self._cursor_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cursor_path.with_suffix(".tmp")
            tmp.write_text(str(byte_offset))
            tmp.replace(self._cursor_path)
        except OSError:
            log.warning("cursor write failed at %s", self._cursor_path, exc_info=True)

    def _tail_from(self, byte_offset: int) -> Iterator[tuple[dict, int]]:
        if not self._event_path.exists():
            return
        try:
            with self._event_path.open("rb") as fh:
                fh.seek(byte_offset)
                while True:
                    line = fh.readline()
                    if not line:
                        return
                    new_offset = fh.tell()
                    text = line.decode("utf-8", errors="replace").strip()
                    if not text:
                        continue
                    try:
                        event = json.loads(text)
                    except json.JSONDecodeError:
                        log.warning("malformed event line at offset %d", byte_offset)
                        continue
                    yield event, new_offset
                    byte_offset = new_offset
        except OSError:
            log.warning("event file read failed at %s", self._event_path, exc_info=True)

    # ── Per-event apply ───────────────────────────────────────────────

    def _apply(self, event: dict) -> None:
        verdict = allowlist_check(
            ALLOWLIST_SURFACE,
            ALLOWLIST_STATE_KIND,
            {"event": event},
        )
        if verdict.decision == "deny":
            log.warning("allowlist DENY for arena post: %s", verdict.reason)
            self.posts_total.labels(result="denied").inc()
            return

        try:
            content, source_url = self._compose(event)
        except Exception:  # noqa: BLE001
            log.exception("composer failed for event")
            self.posts_total.labels(result="compose_error").inc()
            return

        content = content[:ARENA_BLOCK_TEXT_LIMIT]

        if self._dry_run:
            log.info(
                "DRY RUN — would post to arena channel=%s source=%r content=%r",
                self._channel_slug,
                source_url,
                content,
            )
            self.posts_total.labels(result="dry_run").inc()
            return

        result = self._send_block(content, source_url)
        self.posts_total.labels(result=result).inc()

    def _compose(self, event: dict) -> tuple[str, str | None]:
        if self._compose_fn is not None:
            return self._compose_fn(event)
        return _default_compose(event)

    def _send_block(self, content: str, source_url: str | None) -> str:
        if not (self._token and self._channel_slug):
            log.warning("HAPAX_ARENA_TOKEN / HAPAX_ARENA_CHANNEL_SLUG not set; skipping live post")
            return "no_credentials"

        try:
            client = self._ensure_client()
        except Exception:  # noqa: BLE001
            log.exception("arena client init failed")
            return "auth_error"

        try:
            client.add_block(self._channel_slug, content=content, source=source_url)
        except Exception:  # noqa: BLE001
            log.exception("arena add_block raised")
            return "error"
        return "ok"

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        factory = self._client_factory or _default_client_factory
        self._client = factory(self._token)
        return self._client


# ── Default helpers (composer + arena client) ────────────────────────


def _default_compose(event: dict) -> tuple[str, str | None]:
    """Build block content + optional source URL from event metadata."""
    from agents.metadata_composer.composer import compose_metadata

    composed = compose_metadata(triggering_event=event, scope="cross_surface")
    content = (
        getattr(composed, "arena_block", None)
        or getattr(composed, "bluesky_post", None)
        or "hapax — broadcast rotation"
    )
    source_url = event.get("source_url") or getattr(composed, "broadcast_url", None)
    return content, source_url


class _ArenaAdapter:
    """Minimal Are.na adapter wrapping ``arena`` Python client.

    Exposes the single ``add_block(slug, content, source)`` method
    used by ``ArenaPoster._send_block``. Picks ``content`` for text
    blocks, ``source`` for link/image blocks. Falls back to text when
    only content is provided.
    """

    def __init__(self, token: str) -> None:
        from arena import Arena

        self._arena = Arena(access_token=token)

    def add_block(
        self,
        channel_slug: str,
        *,
        content: str,
        source: str | None = None,
    ) -> None:
        channel = self._arena.channels.channel(channel_slug)
        if source:
            channel.add_block(source=source, content=content)
        else:
            channel.add_block(content=content)


def _default_client_factory(token: str) -> _ArenaAdapter:
    """Lazy-build an Are.na adapter."""
    return _ArenaAdapter(token)


def _credentials_from_env() -> tuple[str | None, str | None]:
    token = os.environ.get("HAPAX_ARENA_TOKEN", "").strip() or None
    slug = os.environ.get("HAPAX_ARENA_CHANNEL_SLUG", "").strip() or None
    return token, slug


# ── Orchestrator entry-point (PUB-P1-C foundation) ───────────────────


def publish_artifact(artifact) -> str:  # type: ignore[no-untyped-def]
    """Dispatch a ``PreprintArtifact`` to Are.na.

    Static entry-point consumed by ``agents/publish_orchestrator``'s
    surface registry. Returns one of: ``ok | denied | auth_error |
    error | no_credentials``. Never raises.

    Composes via the artifact's ``attribution_block`` (preferred) or
    ``title + abstract``, truncated to ``ARENA_BLOCK_TEXT_LIMIT``. If
    the artifact carries a ``doi``, it is rendered as a ``https://doi.org/``
    link and supplied as the block ``source`` (Are.na renders link
    blocks distinctly from text blocks). The full ``BasePublisher``
    refactor that consolidates the JSONL-tail mode with this
    entry-point lands in a follow-up ticket; this adds the orchestrator
    surface entry-point without the tail-mode rewrite.
    """
    token, slug = _credentials_from_env()
    if not (token and slug):
        return "no_credentials"

    content = _compose_artifact_content(artifact)
    if not content:
        return "error"

    source_url = _artifact_source_url(artifact)

    try:
        client = _default_client_factory(token)
    except Exception:  # noqa: BLE001
        log.exception("arena client init failed for artifact %s", getattr(artifact, "slug", "?"))
        return "auth_error"

    try:
        client.add_block(slug, content=content, source=source_url)
    except Exception:  # noqa: BLE001
        log.exception("arena add_block raised for artifact %s", getattr(artifact, "slug", "?"))
        return "error"
    return "ok"


def _compose_artifact_content(artifact) -> str:  # type: ignore[no-untyped-def]
    """Render a ``PreprintArtifact`` to Are.na-bounded block content.

    Prefers ``attribution_block`` so per-artifact framing stays
    authoritative; otherwise builds ``"{title} — {abstract}"``.
    Truncated to ``ARENA_BLOCK_TEXT_LIMIT`` (4096).
    """
    title = getattr(artifact, "title", "") or ""
    abstract = getattr(artifact, "abstract", "") or ""
    attribution = getattr(artifact, "attribution_block", "") or ""

    if attribution:
        body = attribution
    elif abstract:
        body = f"{title} — {abstract}"
    else:
        body = title or "hapax — publication artifact"

    return body[:ARENA_BLOCK_TEXT_LIMIT]


def _artifact_source_url(artifact) -> str | None:  # type: ignore[no-untyped-def]
    """Derive an Are.na block ``source`` URL from the artifact, if any.

    DOI takes precedence (rendered as ``https://doi.org/{doi}``);
    falls back to ``embed_image_url`` so image-bearing artifacts land
    as media blocks rather than plain text.
    """
    doi = getattr(artifact, "doi", None)
    if doi:
        return f"https://doi.org/{doi}"
    return getattr(artifact, "embed_image_url", None)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agents.cross_surface.arena_post",
        description="Tail broadcast events and post to a Hapax-owned Are.na channel.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="log block content without sending",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="process pending events then exit (default: daemon loop)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("HAPAX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args(argv)

    token, slug = _credentials_from_env()
    poster = ArenaPoster(
        token=token,
        channel_slug=slug,
        dry_run=args.dry_run,
    )

    if args.once:
        handled = poster.run_once()
        log.info("processed %d event(s)", handled)
        return 0

    start_http_server(METRICS_PORT, addr="127.0.0.1")
    poster.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
