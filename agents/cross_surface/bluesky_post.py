"""Bluesky public-event poster.

Tails canonical ``ResearchVehiclePublicEvent`` JSONL records from
``/dev/shm/hapax-public-events/events.jsonl`` and posts to Bluesky only when
the event contract, Bluesky aperture policy, and publication allowlist all
permit public fanout.

## Auth

App-password authentication (no OAuth flow). Operator generates a
Bluesky app password at
``https://bsky.app/settings/app-passwords`` and exports two env vars
via hapax-secrets:

  HAPAX_BLUESKY_HANDLE          # e.g. ``hapax.bsky.social``
  HAPAX_BLUESKY_APP_PASSWORD    # 19-char app-password from Bluesky

Without either, daemon idles + logs ``no_credentials`` per event.

## Composition

Reuses ``metadata_composer.compose_metadata(scope="cross_surface")`` with a
canonical public-event trigger projection. The resulting ``bluesky_post`` is
text only and capped at 300 chars.

## Rate limit

Bluesky's per-account rate is generous (~5000 ops/hour). Our contract
caps us at 6/hour, 30/day — well under. Per-rotation cadence (~11h)
means ~2-3 posts/day in steady state.

## Embed

This adapter ships text-only posts. A follow-up could add a
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prometheus_client import REGISTRY, CollectorRegistry, Counter, start_http_server
from pydantic import ValidationError

from shared.cross_surface_event_contract import decide_cross_surface_fanout
from shared.governance.publication_allowlist import check as allowlist_check
from shared.research_vehicle_public_event import ResearchVehiclePublicEvent

log = logging.getLogger(__name__)

EVENT_PATH = Path(
    os.environ.get(
        "HAPAX_RESEARCH_VEHICLE_PUBLIC_EVENT_PATH",
        "/dev/shm/hapax-public-events/events.jsonl",
    )
)
DEFAULT_CURSOR_PATH = Path(
    os.environ.get(
        "HAPAX_BLUESKY_CURSOR",
        str(Path.home() / ".cache/hapax/bluesky-post-cursor.txt"),
    )
)
DEFAULT_IDEMPOTENCY_PATH = Path(
    os.environ.get(
        "HAPAX_BLUESKY_IDEMPOTENCY_PATH",
        str(Path.home() / ".cache/hapax/bluesky-post-event-ids.json"),
    )
)
METRICS_PORT: int = int(os.environ.get("HAPAX_BLUESKY_METRICS_PORT", "9501"))
DEFAULT_TICK_S: float = float(os.environ.get("HAPAX_BLUESKY_TICK_S", "30"))
BLUESKY_TEXT_LIMIT = 300

ALLOWLIST_SURFACE = "bluesky-post"
ALLOWED_PUBLIC_EVENT_TYPES = frozenset(
    {
        "broadcast.boundary",
        "chronicle.high_salience",
        "governance.enforcement",
        "omg.weblog",
        "shorts.upload",
        "velocity.digest",
    }
)


@dataclass(frozen=True)
class _TailRecord:
    byte_start: int
    byte_after: int
    event: ResearchVehiclePublicEvent | None
    error: str | None = None


class BlueskyPoster:
    """Tail canonical public events; post to Bluesky when policy permits."""

    def __init__(
        self,
        *,
        handle: str | None = None,
        app_password: str | None = None,
        compose_fn=None,
        client_factory=None,
        event_path: Path = EVENT_PATH,
        cursor_path: Path = DEFAULT_CURSOR_PATH,
        idempotency_path: Path = DEFAULT_IDEMPOTENCY_PATH,
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
        self._idempotency_path = idempotency_path
        self._tick_s = max(1.0, tick_s)
        self._dry_run = dry_run
        self._stop_evt = threading.Event()
        self._client = None  # built on first non-dry-run apply
        self._processed_event_ids: set[str] | None = None

        self.posts_total = Counter(
            "hapax_broadcast_bluesky_posts_total",
            "Bluesky posts attempted from ResearchVehiclePublicEvent records, broken down by outcome.",
            ["result"],
            registry=registry,
        )

    # ── Public API ────────────────────────────────────────────────────

    def run_once(self) -> int:
        handled = 0
        for record in self._tail_from():
            if record.event is None:
                if record.error:
                    log.warning(
                        "skipping malformed public event at byte %d: %s",
                        record.byte_start,
                        record.error,
                    )
                self._write_cursor(record.byte_after)
                continue
            event = record.event
            if event.event_type not in ALLOWED_PUBLIC_EVENT_TYPES:
                self._write_cursor(record.byte_after)
                continue
            if self._event_already_processed(event.event_id):
                self._write_cursor(record.byte_after)
                continue
            self._apply(event)
            self._mark_event_processed(event.event_id)
            self._write_cursor(record.byte_after)
            handled += 1
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

    def _tail_from(self) -> Iterator[_TailRecord]:
        try:
            size = self._event_path.stat().st_size
        except OSError:
            return

        byte_offset = self._read_cursor()
        if byte_offset > size:
            log.warning(
                "public-event file shrank from cursor %d to %d bytes; restarting from 0",
                byte_offset,
                size,
            )
            byte_offset = 0
            self._write_cursor(0)

        try:
            with self._event_path.open("rb") as fh:
                fh.seek(byte_offset)
                while True:
                    byte_start = fh.tell()
                    line = fh.readline()
                    if not line:
                        return
                    new_offset = fh.tell()
                    text = line.decode("utf-8", errors="replace").strip()
                    if not text:
                        yield _TailRecord(
                            byte_start=byte_start,
                            byte_after=new_offset,
                            event=None,
                        )
                        continue
                    try:
                        raw_event = json.loads(text)
                    except json.JSONDecodeError:
                        yield _TailRecord(
                            byte_start=byte_start,
                            byte_after=new_offset,
                            event=None,
                            error="json_decode_error",
                        )
                        continue
                    if not isinstance(raw_event, dict):
                        yield _TailRecord(
                            byte_start=byte_start,
                            byte_after=new_offset,
                            event=None,
                            error="json_not_object",
                        )
                        continue
                    try:
                        event = ResearchVehiclePublicEvent.model_validate(raw_event)
                    except ValidationError as exc:
                        yield _TailRecord(
                            byte_start=byte_start,
                            byte_after=new_offset,
                            event=None,
                            error=f"schema_validation_error:{exc.errors()[0]['type']}",
                        )
                        continue
                    yield _TailRecord(byte_start=byte_start, byte_after=new_offset, event=event)
                    byte_offset = new_offset
        except OSError:
            log.warning("event file read failed at %s", self._event_path, exc_info=True)

    def _event_already_processed(self, event_id: str) -> bool:
        if self._processed_event_ids is None:
            self._processed_event_ids = self._read_processed_event_ids()
        return event_id in self._processed_event_ids

    def _read_processed_event_ids(self) -> set[str]:
        try:
            raw = json.loads(self._idempotency_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return set()
        if isinstance(raw, dict):
            ids = raw.get("event_ids")
        else:
            ids = raw
        if not isinstance(ids, list):
            return set()
        return {item for item in ids if isinstance(item, str) and item}

    def _mark_event_processed(self, event_id: str) -> None:
        if self._processed_event_ids is None:
            self._processed_event_ids = self._read_processed_event_ids()
        self._processed_event_ids.add(event_id)
        try:
            self._idempotency_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._idempotency_path.with_suffix(".tmp")
            payload = {
                "schema_version": 1,
                "event_ids": sorted(self._processed_event_ids),
            }
            tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            tmp.replace(self._idempotency_path)
        except OSError:
            log.warning(
                "idempotency write failed at %s",
                self._idempotency_path,
                exc_info=True,
            )

    # ── Per-event apply ───────────────────────────────────────────────

    def _apply(self, event: ResearchVehiclePublicEvent) -> None:
        fanout = decide_cross_surface_fanout(event, "bluesky", "publish")
        if fanout.decision != "allow":
            log.warning(
                "bluesky public-event fanout blocked for %s: %s",
                event.event_id,
                ",".join(fanout.reasons),
            )
            self.posts_total.labels(result="denied").inc()
            return

        verdict = allowlist_check(
            ALLOWLIST_SURFACE,
            event.event_type,
            _allowlist_payload(event),
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

    def _compose(self, event: ResearchVehiclePublicEvent) -> str:
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


def _default_compose(event: ResearchVehiclePublicEvent) -> str:
    """Build post text by deferring to metadata_composer."""
    from agents.metadata_composer.composer import compose_metadata

    composed = compose_metadata(
        triggering_event=_composer_trigger_from_public_event(event),
        scope="cross_surface",
    )
    return composed.bluesky_post or _fallback_public_event_text(event)


def _composer_trigger_from_public_event(event: ResearchVehiclePublicEvent) -> dict[str, Any]:
    """Project canonical public events into the metadata composer trigger shape."""

    intent = _event_intent(event)
    return {
        "id": event.event_id,
        "event_type": event.event_type,
        "ts": event.occurred_at,
        "payload": {
            "intent_family": intent,
            "salience": event.salience,
            "broadcast_id": event.broadcast_id,
            "public_url": event.public_url,
            "source_event_id": event.event_id,
        },
    }


def _event_intent(event: ResearchVehiclePublicEvent) -> str:
    if event.event_type == "broadcast.boundary":
        if event.chapter_ref is not None and event.chapter_ref.label:
            return event.chapter_ref.label
        return "broadcast boundary"
    if event.event_type == "chronicle.high_salience":
        if event.chapter_ref is not None and event.chapter_ref.label:
            return event.chapter_ref.label
        return "high-salience observation"
    if event.event_type == "omg.weblog":
        if event.chapter_ref is not None and event.chapter_ref.label:
            return f"weblog: {event.chapter_ref.label}"
        return "weblog post"
    if event.event_type == "velocity.digest":
        return "daily velocity digest"
    if event.event_type == "governance.enforcement":
        return "governance enforcement"
    if event.event_type == "shorts.upload":
        return "shorts upload"
    return event.event_type


def _fallback_public_event_text(event: ResearchVehiclePublicEvent) -> str:
    if event.event_type == "omg.weblog" and event.public_url:
        return f"Hapax weblog: {_event_intent(event)}. {event.public_url}"
    if event.event_type in {"governance.enforcement", "velocity.digest"}:
        return f"Hapax {_event_intent(event)}."
    return f"Hapax livestream: {_event_intent(event)}."


def _allowlist_payload(event: ResearchVehiclePublicEvent) -> dict[str, Any]:
    payload: dict[str, Any] = {"event": event.model_dump(mode="json")}
    if event.event_type in {
        "chronicle.high_salience",
        "governance.enforcement",
        "omg.weblog",
        "shorts.upload",
        "velocity.digest",
    }:
        payload["grounding_gate_result"] = _grounding_gate_from_public_event(event)
    return payload


def _grounding_gate_from_public_event(event: ResearchVehiclePublicEvent) -> dict[str, Any]:
    mode = _publication_mode(event)
    source_refs = _dedupe(
        [
            event.source.evidence_ref,
            *event.provenance.evidence_refs,
            *event.provenance.citation_refs,
            *event.attribution_refs,
        ]
    )
    evidence_refs = _dedupe([event.source.evidence_ref, *event.provenance.evidence_refs])
    publishable = mode in {"public_live", "public_archive", "public_monetizable"} and (
        event.surface_policy.dry_run_reason is None
    )
    return {
        "schema_version": 1,
        "public_private_mode": mode,
        "gate_state": "pass" if publishable else "hold",
        "claim": {
            "evidence_refs": evidence_refs,
            "provenance": {"source_refs": source_refs},
            "freshness": {"status": "fresh" if publishable else "stale"},
            "rights_state": event.rights_class,
            "privacy_state": event.privacy_class,
            "public_private_mode": mode,
            "refusal_correction_path": {
                "refusal_reason": event.surface_policy.dry_run_reason,
                "correction_event_ref": None,
                "artifact_ref": None,
            },
        },
        "gate_result": {
            "may_emit_claim": publishable,
            "may_publish_live": publishable and mode == "public_live",
            "may_publish_archive": publishable and mode == "public_archive",
            "may_monetize": publishable and mode == "public_monetizable",
        },
    }


def _publication_mode(event: ResearchVehiclePublicEvent) -> str:
    if event.surface_policy.claim_monetizable:
        return "public_monetizable"
    if event.surface_policy.claim_live:
        return "public_live"
    if event.surface_policy.claim_archive:
        return "public_archive"
    return "dry_run"


def _dedupe(values: list[str | None]) -> list[str]:
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        text = value.strip()
        if text and text not in result:
            result.append(text)
    return result


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

    The Refusal Brief's ``non_engagement_clause`` (SHORT form for bsky's
    300-char body cap) is appended when (a) the artifact's
    attribution_block doesn't already reference the brief, and (b) the
    SHORT clause fits in remaining capacity. The append is best-effort:
    if appending the clause would push the body over BLUESKY_TEXT_LIMIT,
    the clause is dropped (artifact framing wins). Self-referential
    artifacts (the Refusal Brief itself) are detected by checking
    ``artifact.slug``.
    """
    from shared.attribution_block import NON_ENGAGEMENT_CLAUSE_SHORT

    title = getattr(artifact, "title", "") or ""
    abstract = getattr(artifact, "abstract", "") or ""
    attribution = getattr(artifact, "attribution_block", "") or ""

    if attribution:
        body = attribution
    elif abstract:
        body = f"{title} — {abstract}"
    else:
        body = title or "hapax — publication artifact"

    body = body[:BLUESKY_TEXT_LIMIT]

    # Append the Refusal Brief reference if it fits and isn't self-
    # referential (the Refusal Brief itself doesn't cite itself).
    slug = getattr(artifact, "slug", "") or ""
    if slug != "refusal-brief" and "refusal" not in body.lower():
        candidate = f"{body}\n\n{NON_ENGAGEMENT_CLAUSE_SHORT}"
        if len(candidate) <= BLUESKY_TEXT_LIMIT:
            body = candidate

    return body


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agents.cross_surface.bluesky_post",
        description="Tail canonical public events and post to Bluesky.",
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
