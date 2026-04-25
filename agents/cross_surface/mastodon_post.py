"""Mastodon poster (ytb-010 Phase 3).

Tails ``/dev/shm/hapax-broadcast/events.jsonl`` and posts a status to
the operator's Mastodon instance on each ``broadcast_rotated`` event
via the ``Mastodon.py`` client. Same JSONL-cursor + allowlist-gate +
dry-run-default pattern as Discord (Phase 1) and Bluesky (Phase 2).

## Auth

Access-token authentication. Operator generates a token at
``<instance>/settings/applications`` (scope ``write:statuses``) and
exports two env vars via hapax-secrets:

  HAPAX_MASTODON_INSTANCE_URL    # e.g. ``https://mastodon.social``
  HAPAX_MASTODON_ACCESS_TOKEN    # the generated access token

Without either, daemon idles + logs ``no_credentials`` per event.

## Composition

Reuses ``metadata_composer.compose_metadata(scope="cross_surface")``
which produces ``mastodon_post`` (text only, ≤ 500 chars) already-
policed by the redaction + framing layers. The 500-char default
limit covers the majority of instances; per-instance overrides can
be supplied via ``HAPAX_MASTODON_TEXT_LIMIT``.

## Rate limit

Mastodon's per-instance rate is generous (~300 req / 5min). Our
contract caps us at 6/hour, 30/day — well under. Per-rotation
cadence (~11h) means ~2-3 posts/day in steady state.
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
        "HAPAX_MASTODON_CURSOR",
        str(Path.home() / ".cache/hapax/mastodon-post-cursor.txt"),
    )
)
METRICS_PORT: int = int(os.environ.get("HAPAX_MASTODON_METRICS_PORT", "9502"))
DEFAULT_TICK_S: float = float(os.environ.get("HAPAX_MASTODON_TICK_S", "30"))
MASTODON_TEXT_LIMIT: int = int(os.environ.get("HAPAX_MASTODON_TEXT_LIMIT", "500"))

ALLOWLIST_SURFACE = "mastodon-post"
ALLOWLIST_STATE_KIND = "broadcast.boundary"
EVENT_TYPE = "broadcast_rotated"


class MastodonPoster:
    """Tail broadcast events; post to Mastodon per rotation."""

    def __init__(
        self,
        *,
        instance_url: str | None = None,
        access_token: str | None = None,
        compose_fn=None,
        client_factory=None,
        event_path: Path = EVENT_PATH,
        cursor_path: Path = DEFAULT_CURSOR_PATH,
        registry: CollectorRegistry = REGISTRY,
        tick_s: float = DEFAULT_TICK_S,
        text_limit: int = MASTODON_TEXT_LIMIT,
        dry_run: bool = False,
    ) -> None:
        self._instance_url = instance_url
        self._access_token = access_token
        self._compose_fn = compose_fn
        self._client_factory = client_factory
        self._event_path = event_path
        self._cursor_path = cursor_path
        self._tick_s = max(1.0, tick_s)
        self._text_limit = max(1, text_limit)
        self._dry_run = dry_run
        self._stop_evt = threading.Event()
        self._client = None  # built on first non-dry-run apply

        self.posts_total = Counter(
            "hapax_broadcast_mastodon_posts_total",
            "Mastodon posts attempted, broken down by outcome.",
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
            "mastodon poster starting, port=%d tick=%.1fs dry_run=%s instance=%s",
            METRICS_PORT,
            self._tick_s,
            self._dry_run,
            self._instance_url or "<unset>",
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
            log.warning("allowlist DENY for mastodon post: %s", verdict.reason)
            self.posts_total.labels(result="denied").inc()
            return

        try:
            text = self._compose(event)
        except Exception:  # noqa: BLE001
            log.exception("composer failed for event")
            self.posts_total.labels(result="compose_error").inc()
            return

        text = text[: self._text_limit]

        if self._dry_run:
            log.info("DRY RUN — would post to mastodon: text=%r", text)
            self.posts_total.labels(result="dry_run").inc()
            return

        result = self._status_post(text)
        self.posts_total.labels(result=result).inc()

    def _compose(self, event: dict) -> str:
        if self._compose_fn is not None:
            return self._compose_fn(event)
        return _default_compose(event)

    def _status_post(self, text: str) -> str:
        if not (self._instance_url and self._access_token):
            log.warning(
                "HAPAX_MASTODON_INSTANCE_URL / HAPAX_MASTODON_ACCESS_TOKEN not set; "
                "skipping live post"
            )
            return "no_credentials"

        try:
            client = self._ensure_client()
        except Exception:  # noqa: BLE001
            log.exception("mastodon client init failed")
            return "auth_error"

        try:
            client.status_post(text)
        except Exception:  # noqa: BLE001
            log.exception("mastodon status_post raised")
            return "error"
        return "ok"

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        factory = self._client_factory or _default_client_factory
        self._client = factory(self._instance_url, self._access_token)
        return self._client


# ── Default helpers (composer + Mastodon client) ─────────────────────


def _default_compose(event: dict) -> str:
    """Build post text by deferring to metadata_composer."""
    from agents.metadata_composer.composer import compose_metadata

    composed = compose_metadata(triggering_event=event, scope="cross_surface")
    return composed.mastodon_post or "hapax — broadcast rotation"


def _default_client_factory(instance_url: str, access_token: str):
    """Lazy-build a Mastodon client."""
    from mastodon import Mastodon

    return Mastodon(access_token=access_token, api_base_url=instance_url)


def _credentials_from_env() -> tuple[str | None, str | None]:
    instance = os.environ.get("HAPAX_MASTODON_INSTANCE_URL", "").strip() or None
    token = os.environ.get("HAPAX_MASTODON_ACCESS_TOKEN", "").strip() or None
    return instance, token


# ── Orchestrator entry-point (PUB-P1-B foundation) ───────────────────


def publish_artifact(artifact) -> str:  # type: ignore[no-untyped-def]
    """Dispatch a ``PreprintArtifact`` to Mastodon.

    Static entry-point consumed by ``agents/publish_orchestrator``'s
    surface registry. Returns one of: ``ok | denied | auth_error |
    error | no_credentials``. Never raises.

    Composes via the artifact's ``title + abstract`` (truncated to
    ``MASTODON_TEXT_LIMIT``, default 500). The full ``BasePublisher``
    refactor that consolidates the JSONL-tail mode with this
    entry-point lands in a follow-up ticket.
    """
    instance_url, access_token = _credentials_from_env()
    if not (instance_url and access_token):
        return "no_credentials"

    text = _compose_artifact_text(artifact)
    if not text:
        return "error"

    try:
        client = _default_client_factory(instance_url, access_token)
    except Exception:  # noqa: BLE001
        log.exception("mastodon login failed for artifact %s", getattr(artifact, "slug", "?"))
        return "auth_error"

    try:
        client.status_post(text)
    except Exception:  # noqa: BLE001
        log.exception(
            "mastodon status_post raised for artifact %s",
            getattr(artifact, "slug", "?"),
        )
        return "error"
    return "ok"


def _compose_artifact_text(artifact) -> str:  # type: ignore[no-untyped-def]
    """Render a ``PreprintArtifact`` to Mastodon-bounded text.

    Default: ``"{title} — {abstract}"`` truncated to
    ``MASTODON_TEXT_LIMIT``. If the artifact carries a non-empty
    ``attribution_block``, prefer that as the body so per-artifact
    framing stays authoritative.
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

    return body[:MASTODON_TEXT_LIMIT]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agents.cross_surface.mastodon_post",
        description="Tail broadcast events and post to Mastodon.",
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

    instance, token = _credentials_from_env()
    poster = MastodonPoster(
        instance_url=instance,
        access_token=token,
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
