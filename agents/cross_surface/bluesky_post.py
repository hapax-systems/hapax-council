"""Bluesky poster (ytb-010 Phase 2).

Tails ``/dev/shm/hapax-broadcast/events.jsonl`` and posts to Bluesky on
each ``broadcast_rotated`` event via the ``atproto`` client. Uses the
same JSONL-cursor + allowlist-gate + dry-run-default pattern as the
Discord poster (Phase 1, ``discord_webhook.py``).

## Auth

App-password authentication (no OAuth flow). Operator generates a
Bluesky app password at
``https://bsky.app/settings/app-passwords`` and exports two env vars
via hapax-secrets:

  HAPAX_BLUESKY_HANDLE          # e.g. ``hapax.bsky.social``
  HAPAX_BLUESKY_APP_PASSWORD    # 19-char app-password from Bluesky

Without either, daemon idles + logs ``no_credentials`` per event.

## Composition

Reuses ``metadata_composer.compose_metadata(scope="cross_surface")``
which produces ``bluesky_post`` (text only, ≤ 300 chars) already-
policed by the redaction + framing layers.

## Rate limit

Bluesky's per-account rate is generous (~5000 ops/hour). Our contract
caps us at 6/hour, 30/day — well under. Per-rotation cadence (~11h)
means ~2-3 posts/day in steady state.

## Embed

Phase 2 ships text-only posts. A follow-up could add a
``AppBskyEmbedExternal.Main`` link card with the broadcast URL,
title, and thumbnail; deferred to keep this PR tight.
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
        "HAPAX_BLUESKY_CURSOR",
        str(Path.home() / ".cache/hapax/bluesky-post-cursor.txt"),
    )
)
METRICS_PORT: int = int(os.environ.get("HAPAX_BLUESKY_METRICS_PORT", "9501"))
DEFAULT_TICK_S: float = float(os.environ.get("HAPAX_BLUESKY_TICK_S", "30"))
BLUESKY_TEXT_LIMIT = 300

ALLOWLIST_SURFACE = "bluesky-post"
ALLOWLIST_STATE_KIND = "broadcast.boundary"
EVENT_TYPE = "broadcast_rotated"


class BlueskyPoster:
    """Tail broadcast events; post to Bluesky per rotation."""

    def __init__(
        self,
        *,
        handle: str | None = None,
        app_password: str | None = None,
        compose_fn=None,
        client_factory=None,
        event_path: Path = EVENT_PATH,
        cursor_path: Path = DEFAULT_CURSOR_PATH,
        registry: CollectorRegistry = REGISTRY,
        tick_s: float = DEFAULT_TICK_S,
        dry_run: bool = False,
    ) -> None:
        self._handle = handle
        self._app_password = app_password
        self._compose_fn = compose_fn
        self._client_factory = client_factory
        self._event_path = event_path
        self._cursor_path = cursor_path
        self._tick_s = max(1.0, tick_s)
        self._dry_run = dry_run
        self._stop_evt = threading.Event()
        self._client = None  # built on first non-dry-run apply

        self.posts_total = Counter(
            "hapax_broadcast_bluesky_posts_total",
            "Bluesky posts attempted, broken down by outcome.",
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
            "bluesky poster starting, port=%d tick=%.1fs dry_run=%s handle=%s",
            METRICS_PORT,
            self._tick_s,
            self._dry_run,
            self._handle or "<unset>",
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
            log.warning("allowlist DENY for bluesky post: %s", verdict.reason)
            self.posts_total.labels(result="denied").inc()
            return

        try:
            text = self._compose(event)
        except Exception:  # noqa: BLE001
            log.exception("composer failed for event")
            self.posts_total.labels(result="compose_error").inc()
            return

        text = text[:BLUESKY_TEXT_LIMIT]

        if self._dry_run:
            log.info("DRY RUN — would post to bluesky: text=%r", text)
            self.posts_total.labels(result="dry_run").inc()
            return

        result = self._send_post(text)
        self.posts_total.labels(result=result).inc()

    def _compose(self, event: dict) -> str:
        if self._compose_fn is not None:
            return self._compose_fn(event)
        return _default_compose(event)

    def _send_post(self, text: str) -> str:
        if not (self._handle and self._app_password):
            log.warning(
                "HAPAX_BLUESKY_HANDLE / HAPAX_BLUESKY_APP_PASSWORD not set; skipping live post"
            )
            return "no_credentials"

        try:
            client = self._ensure_client()
        except Exception:  # noqa: BLE001
            log.exception("bluesky login failed")
            return "auth_error"

        try:
            client.send_post(text=text)
        except Exception:  # noqa: BLE001
            log.exception("bluesky send_post raised")
            return "error"
        return "ok"

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        factory = self._client_factory or _default_client_factory
        self._client = factory(self._handle, self._app_password)
        return self._client


# ── Default helpers (composer + atproto client) ──────────────────────


def _default_compose(event: dict) -> str:
    """Build post text by deferring to metadata_composer."""
    from agents.metadata_composer.composer import compose_metadata

    composed = compose_metadata(triggering_event=event, scope="cross_surface")
    return composed.bluesky_post or "hapax — broadcast rotation"


def _default_client_factory(handle: str, app_password: str):
    """Lazy-build + login an atproto Client."""
    from atproto import Client

    client = Client()
    client.login(handle, app_password)
    return client


def _credentials_from_env() -> tuple[str | None, str | None]:
    handle = os.environ.get("HAPAX_BLUESKY_HANDLE", "").strip() or None
    pw = os.environ.get("HAPAX_BLUESKY_APP_PASSWORD", "").strip() or None
    return handle, pw


# ── Orchestrator entry-point (PUB-P1-A foundation) ───────────────────


def publish_artifact(artifact) -> str:  # type: ignore[no-untyped-def]
    """Dispatch a ``PreprintArtifact`` to Bluesky.

    Static entry-point consumed by ``agents/publish_orchestrator``'s
    surface registry. Returns one of the orchestrator-recognized
    result strings: ``ok | denied | auth_error | error |
    no_credentials``. Never raises.

    Composes via the artifact's ``title + abstract`` (truncated to the
    300-char Bluesky limit). The full ``BasePublisher`` refactor that
    consolidates the JSONL-tail mode with this entry-point lands in a
    follow-up ticket; this adds the orchestrator surface entry-point
    without the tail-mode rewrite.
    """
    handle, app_password = _credentials_from_env()
    if not (handle and app_password):
        return "no_credentials"

    text = _compose_artifact_text(artifact)
    if not text:
        return "error"

    try:
        client = _default_client_factory(handle, app_password)
    except Exception:  # noqa: BLE001
        log.exception("bluesky login failed for artifact %s", getattr(artifact, "slug", "?"))
        return "auth_error"

    try:
        client.send_post(text=text)
    except Exception:  # noqa: BLE001
        log.exception("bluesky send_post raised for artifact %s", getattr(artifact, "slug", "?"))
        return "error"
    return "ok"


def _compose_artifact_text(artifact) -> str:  # type: ignore[no-untyped-def]
    """Render a ``PreprintArtifact`` to Bluesky-bounded text.

    Default form: ``"{title} — {abstract}"``, truncated to 300 chars.
    If the artifact carries a non-empty ``attribution_block``, prefer
    that as the body so per-artifact framing stays authoritative.
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

    return body[:BLUESKY_TEXT_LIMIT]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agents.cross_surface.bluesky_post",
        description="Tail broadcast events and post to Bluesky.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="log post text without sending",
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

    handle, password = _credentials_from_env()
    poster = BlueskyPoster(
        handle=handle,
        app_password=password,
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
