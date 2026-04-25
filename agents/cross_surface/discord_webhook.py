"""Discord webhook poster (ytb-010 Phase 1).

Tails ``/dev/shm/hapax-broadcast/events.jsonl`` and POSTs an embed to
the operator's Discord webhook on each ``broadcast_rotated`` event.
Webhook URL comes from ``HAPAX_DISCORD_WEBHOOK_URL`` (operator
supplies via hapax-secrets); daemon errors gracefully when absent.

## Pipeline

- Inline JSONL tailer with persistent byte-offset cursor at
  ``~/.cache/hapax/discord-webhook-cursor.txt`` (atomic tmp+rename).
- Per-event apply: allowlist gate (``discord-webhook`` /
  ``broadcast.boundary``) → dry-run check → POST to webhook URL with
  embed body.
- 30s polling cadence; daemon never raises.

## Composition

Reuses ``metadata_composer.compose_metadata(scope="cross_surface")``
which produces ``discord_embed_title`` + ``discord_embed_description``
already-policed by the redaction + framing layers (operator-referent
picker via ``pick_for_vod_segment``, register enforcement, etc.).

## Rate limit

Discord allows 5 req / 2s per webhook. The contract caps us at
12 req/hour, 60/day — well under. Per-rotation cadence (~11h) means
~2-3 calls/day in steady state.

## Dry-run

``--dry-run`` prints the payload without POSTing. Default daemon
loop runs without flags.
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

import requests
from prometheus_client import REGISTRY, CollectorRegistry, Counter, start_http_server

from shared.governance.publication_allowlist import check as allowlist_check

log = logging.getLogger(__name__)

EVENT_PATH = Path(
    os.environ.get("HAPAX_BROADCAST_EVENT_PATH", "/dev/shm/hapax-broadcast/events.jsonl")
)
DEFAULT_CURSOR_PATH = Path(
    os.environ.get(
        "HAPAX_DISCORD_WEBHOOK_CURSOR",
        str(Path.home() / ".cache/hapax/discord-webhook-cursor.txt"),
    )
)
METRICS_PORT: int = int(os.environ.get("HAPAX_DISCORD_WEBHOOK_METRICS_PORT", "9500"))
DEFAULT_TICK_S: float = float(os.environ.get("HAPAX_DISCORD_WEBHOOK_TICK_S", "30"))
WEBHOOK_TIMEOUT_S: float = float(os.environ.get("HAPAX_DISCORD_WEBHOOK_TIMEOUT_S", "10"))

ALLOWLIST_SURFACE = "discord-webhook"
ALLOWLIST_STATE_KIND = "broadcast.boundary"
EVENT_TYPE = "broadcast_rotated"
DISCORD_EMBED_COLOR = 0x00FFFF  # mIRC slot 11 (cyan) — matches HOMAGE


class DiscordWebhookPoster:
    """Tail broadcast events; POST a Discord embed per rotation."""

    def __init__(
        self,
        *,
        webhook_url: str | None = None,
        compose_fn=None,
        post_fn=None,
        event_path: Path = EVENT_PATH,
        cursor_path: Path = DEFAULT_CURSOR_PATH,
        registry: CollectorRegistry = REGISTRY,
        tick_s: float = DEFAULT_TICK_S,
        dry_run: bool = False,
    ) -> None:
        self._webhook_url = webhook_url
        self._compose_fn = compose_fn
        self._post_fn = post_fn
        self._event_path = event_path
        self._cursor_path = cursor_path
        self._tick_s = max(1.0, tick_s)
        self._dry_run = dry_run
        self._stop_evt = threading.Event()

        self.posts_total = Counter(
            "hapax_broadcast_discord_webhook_posts_total",
            "Discord webhook POSTs attempted, broken down by outcome.",
            ["result"],
            registry=registry,
        )

    # ── Public API ────────────────────────────────────────────────────

    def run_once(self) -> int:
        """Process all pending events at the cursor; return count handled."""
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
            "discord webhook poster starting, port=%d tick=%.1fs dry_run=%s",
            METRICS_PORT,
            self._tick_s,
            self._dry_run,
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
            log.warning("allowlist DENY for discord post: %s", verdict.reason)
            self.posts_total.labels(result="denied").inc()
            return

        try:
            title, description = self._compose(event)
        except Exception:  # noqa: BLE001
            log.exception("composer failed for event")
            self.posts_total.labels(result="compose_error").inc()
            return

        payload = self._build_payload(title=title, description=description, event=event)

        if self._dry_run:
            log.info(
                "DRY RUN — would POST to discord webhook: title=%r description-bytes=%d",
                title,
                len(description),
            )
            self.posts_total.labels(result="dry_run").inc()
            return

        result = self._post(payload)
        self.posts_total.labels(result=result).inc()

    def _compose(self, event: dict) -> tuple[str, str]:
        if self._compose_fn is not None:
            return self._compose_fn(event)
        return _default_compose(event)

    def _build_payload(self, *, title: str, description: str, event: dict) -> dict:
        url = _broadcast_url_from_event(event)
        embed: dict = {
            "title": title,
            "description": description,
            "color": DISCORD_EMBED_COLOR,
        }
        if url:
            embed["url"] = url
        return {"embeds": [embed]}

    def _post(self, payload: dict) -> str:
        if not self._webhook_url:
            log.warning("HAPAX_DISCORD_WEBHOOK_URL not set; skipping live POST")
            return "no_webhook_url"
        post = self._post_fn or _default_post
        try:
            ok = post(self._webhook_url, payload, timeout=WEBHOOK_TIMEOUT_S)
        except Exception:  # noqa: BLE001
            log.exception("discord POST raised")
            return "error"
        return "ok" if ok else "error"


# ── Default helpers (composer + http) ────────────────────────────────


def _default_compose(event: dict) -> tuple[str, str]:
    """Build (title, description) by deferring to metadata_composer.

    Composer import is lazy so tests injecting ``compose_fn`` don't
    pay the heavy import cost or need pydantic-ai available.
    """
    from agents.metadata_composer.composer import compose_metadata

    composed = compose_metadata(triggering_event=event, scope="cross_surface")
    title = composed.discord_embed_title or "hapax — broadcast rotation"
    description = composed.discord_embed_description or ""
    return title, description


def _default_post(url: str, payload: dict, *, timeout: float) -> bool:
    """Default HTTP POST — returns True on 2xx."""
    response = requests.post(url, json=payload, timeout=timeout)
    if 200 <= response.status_code < 300:
        return True
    log.warning(
        "discord webhook POST got status=%d body=%r",
        response.status_code,
        response.text[:200],
    )
    return False


def _broadcast_url_from_event(event: dict) -> str | None:
    """Pull the incoming broadcast URL from a ``broadcast_rotated`` event."""
    url = event.get("incoming_broadcast_url")
    if url:
        return url
    bid = event.get("incoming_broadcast_id")
    if bid:
        return f"https://www.youtube.com/watch?v={bid}"
    return None


def _webhook_url_from_env() -> str | None:
    raw = os.environ.get("HAPAX_DISCORD_WEBHOOK_URL", "").strip()
    return raw or None


# ── Orchestrator entry-point (PUB-P1-D foundation) ───────────────────


def publish_artifact(artifact) -> str:  # type: ignore[no-untyped-def]
    """Dispatch a ``PreprintArtifact`` to the operator's Discord webhook.

    Static entry-point consumed by ``agents/publish_orchestrator``'s
    surface registry. Returns one of: ``ok | denied | auth_error |
    error | no_credentials``. Never raises.

    Composes via the artifact's ``title`` + (``attribution_block`` |
    ``abstract``) into a Discord embed payload (``title``,
    ``description``, ``color``, optional ``url``). The full
    ``BasePublisher`` refactor that consolidates the JSONL-tail mode
    with this entry-point lands in a follow-up ticket; this adds the
    orchestrator surface entry-point without the tail-mode rewrite.

    Discord webhooks accept raw-URL POSTs, so there is no
    ``auth_error`` distinct from ``error``; both surface as ``error``
    (the webhook either accepts or 4xx/5xxs, no separate login step).
    A missing webhook URL maps to ``no_credentials`` for parity with
    the bsky/mastodon/arena entry-points.
    """
    webhook_url = _webhook_url_from_env()
    if not webhook_url:
        return "no_credentials"

    payload = _compose_artifact_payload(artifact)

    try:
        ok = _default_post(webhook_url, payload, timeout=WEBHOOK_TIMEOUT_S)
    except Exception:  # noqa: BLE001
        log.exception("discord webhook POST raised for %s", getattr(artifact, "slug", "?"))
        return "error"
    return "ok" if ok else "error"


def _compose_artifact_payload(artifact) -> dict:  # type: ignore[no-untyped-def]
    """Render a ``PreprintArtifact`` to a Discord embed payload.

    Description preference order: ``attribution_block`` (V5
    per-artifact framing), else ``abstract``, else placeholder.
    Embed ``url`` is supplied when the artifact carries a ``doi``
    (renders as ``https://doi.org/{doi}``) so the embed becomes
    click-through.
    """
    title = getattr(artifact, "title", "") or "hapax — publication artifact"
    attribution = getattr(artifact, "attribution_block", "") or ""
    abstract = getattr(artifact, "abstract", "") or ""
    description = attribution or abstract or ""

    embed: dict = {
        "title": title[:256],  # Discord embed title limit
        "description": description[:4096],  # Discord embed description limit
        "color": DISCORD_EMBED_COLOR,
    }

    doi = getattr(artifact, "doi", None)
    if doi:
        embed["url"] = f"https://doi.org/{doi}"

    return {"embeds": [embed]}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agents.cross_surface.discord_webhook",
        description="Tail broadcast events and POST Discord embeds.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="log payloads without POSTing",
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

    poster = DiscordWebhookPoster(
        webhook_url=_webhook_url_from_env(),
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
