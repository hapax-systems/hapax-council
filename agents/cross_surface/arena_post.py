"""Are.na public-event poster.

Tails canonical ``ResearchVehiclePublicEvent`` JSONL records from
``/dev/shm/hapax-public-events/events.jsonl`` and posts a block to a
Hapax-owned Are.na channel only when the cross-surface aperture
contract, the publication allowlist, and the Are.na surface policy all
permit public fanout.

## Why Are.na

Are.na is the operative research-surface for the AGR (Acid Graphics
Revival) scene + Schwulst / Broskoski / Mindy Seu adjacent network.
The *citation-density* posture — every block annotated with technique,
WGSL preset, livestream timestamp — is the AGR-native legibility
move. Bot-permissive culture as long as the persona is named and the
curation has a soul (frnsys/arena patterns + Are.na Community Dev
Lounge). One block per eligible public event lands within typical
scene cadence (3-6/day).

## Auth

Personal Access Token authentication. Operator generates a token at
``https://dev.are.na/oauth/applications`` and exports via hapax-secrets:

  HAPAX_ARENA_TOKEN          # PAT, opaque string
  HAPAX_ARENA_CHANNEL_SLUG   # e.g. "hapax-visual-surface-auto-curated"

Without either, daemon idles + logs ``no_credentials`` per eligible
public event.

## Allowed event types

Per the canonical cross-surface aperture contract
(``shared/cross_surface_event_contract.py::CROSS_SURFACE_APERTURES``),
arena consumes event types that can materialize as public blocks:

- ``arena_block.candidate`` — producer-materialized block candidate
  (the canonical replacement for raw ``broadcast.boundary`` on this
  surface; producers convert rotation events into block candidates so
  the arena adapter never needs broadcast-rotation knowledge).
- ``aesthetic.frame_capture`` — frame-centric block; ``frame_ref`` URL
  becomes the link source.
- ``chronicle.high_salience`` — high-salience observation block;
  ``public_url`` becomes the link source.
- ``governance.enforcement`` — governance event block.
- ``omg.weblog`` — weblog post block; ``public_url`` becomes the link
  source.
- ``publication.artifact`` — published-artifact block (concept-DOI,
  weblog URL); ``public_url`` becomes the link source.
- ``velocity.digest`` — daily digest block.

Any other event type is silently skipped. Note that ``broadcast.boundary``
is intentionally not accepted directly — producers must materialize an
``arena_block.candidate`` event from the rotation event so the arena
sieve stays event-driven and not surface-aware.

## Block composition

Each event type yields a ``(content, source_url)`` pair. ``content``
defers to ``metadata_composer.compose_metadata(scope="cross_surface")``
when available (so cross-surface framing stays consistent with
mastodon, bluesky, etc.), and falls back to an event-type-specific
fallback that uses ``chapter_ref.label`` when present. ``source_url``
prefers ``public_url`` for chronicle/publication.artifact, and
``frame_ref.uri`` for aesthetic.frame_capture; arena_block.candidate
uses whichever is present.

Content is truncated to ``ARENA_BLOCK_TEXT_LIMIT`` (4096) per Are.na
block-content limit.

## Idempotency

Two-level: byte cursor at ``HAPAX_ARENA_CURSOR`` (advances on every
record processed, including malformed/skipped) plus event-id ledger
at ``HAPAX_ARENA_IDEMPOTENCY_PATH`` (so cursor loss does not double-
post). Mirrors the mastodon adapter pattern.

## Rate limit

Are.na has no documented rate limits but the contract caps at
6/hour, 30/day to mirror Bluesky discipline.

## Metrics

``hapax_broadcast_arena_posts_total{result}`` is preserved for
dashboard continuity. Results include ``ok``, ``dry_run``, ``denied``,
``compose_error``, ``no_credentials``, ``auth_error``, and ``error``.
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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prometheus_client import REGISTRY, CollectorRegistry, Counter, start_http_server
from pydantic import ValidationError

from agents.publication_bus.arena_publisher import ArenaPublisher
from agents.publication_bus.publisher_kit import PublisherPayload, PublisherResult
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
        "HAPAX_ARENA_CURSOR",
        str(Path.home() / ".cache/hapax/arena-post-cursor.txt"),
    )
)
DEFAULT_IDEMPOTENCY_PATH = Path(
    os.environ.get(
        "HAPAX_ARENA_IDEMPOTENCY_PATH",
        str(Path.home() / ".cache/hapax/arena-post-event-ids.json"),
    )
)
METRICS_PORT: int = int(os.environ.get("HAPAX_ARENA_METRICS_PORT", "9504"))
DEFAULT_TICK_S: float = float(os.environ.get("HAPAX_ARENA_TICK_S", "30"))
ARENA_BLOCK_TEXT_LIMIT = 4096
DEFAULT_PUBLICATION_TARGET = os.environ.get("HAPAX_ARENA_PUBLICATION_TARGET", "hapax")

ALLOWLIST_SURFACE = "arena-post"
ALLOWED_PUBLIC_EVENT_TYPES = frozenset(
    {
        "arena_block.candidate",
        "aesthetic.frame_capture",
        "chronicle.high_salience",
        "governance.enforcement",
        "omg.weblog",
        "publication.artifact",
        "velocity.digest",
    }
)


@dataclass(frozen=True)
class _TailRecord:
    byte_start: int
    byte_after: int
    event: ResearchVehiclePublicEvent | None
    error: str | None = None


@dataclass(frozen=True)
class _BlockResult:
    result: str
    detail: str | None = None


class ArenaPoster:
    """Tail canonical public events; post to a Hapax-owned Are.na channel when policy permits."""

    def __init__(
        self,
        *,
        token: str | None = None,
        channel_slug: str | None = None,
        compose_fn=None,
        publisher_factory=None,
        publication_target: str = DEFAULT_PUBLICATION_TARGET,
        event_path: Path = EVENT_PATH,
        cursor_path: Path = DEFAULT_CURSOR_PATH,
        idempotency_path: Path = DEFAULT_IDEMPOTENCY_PATH,
        registry: CollectorRegistry = REGISTRY,
        tick_s: float = DEFAULT_TICK_S,
        text_limit: int = ARENA_BLOCK_TEXT_LIMIT,
        dry_run: bool = False,
    ) -> None:
        self._token = token
        self._channel_slug = channel_slug
        self._compose_fn = compose_fn
        self._publisher_factory = publisher_factory
        self._publication_target = publication_target
        self._event_path = event_path
        self._cursor_path = cursor_path
        self._idempotency_path = idempotency_path
        self._tick_s = max(1.0, tick_s)
        self._text_limit = max(1, text_limit)
        self._dry_run = dry_run
        self._stop_evt = threading.Event()
        self._processed_event_ids: set[str] | None = None
        self._post_receipts: dict[str, dict[str, Any]] | None = None

        self.posts_total = Counter(
            "hapax_broadcast_arena_posts_total",
            "Are.na blocks attempted from ResearchVehiclePublicEvent records, broken down by outcome.",
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
            receipt = self._apply(event)
            self._mark_event_processed(event.event_id, receipt=receipt)
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
            "arena public-event poster starting, port=%d tick=%.1fs dry_run=%s channel=%s",
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

    def _mark_event_processed(
        self,
        event_id: str,
        *,
        receipt: dict[str, Any] | None = None,
    ) -> None:
        if self._processed_event_ids is None:
            self._processed_event_ids = self._read_processed_event_ids()
        self._processed_event_ids.add(event_id)
        try:
            self._idempotency_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._idempotency_path.with_suffix(".tmp")
            if self._post_receipts is None:
                self._post_receipts = self._read_post_receipts()
            if receipt is not None:
                self._post_receipts[event_id] = receipt
            payload = {
                "schema_version": 2,
                "event_ids": sorted(self._processed_event_ids),
                "posts": [self._post_receipts[key] for key in sorted(self._post_receipts)],
            }
            tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            tmp.replace(self._idempotency_path)
        except OSError:
            log.warning(
                "idempotency write failed at %s",
                self._idempotency_path,
                exc_info=True,
            )

    def _read_post_receipts(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self._idempotency_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        posts = raw.get("posts")
        if not isinstance(posts, list):
            return {}

        receipts: dict[str, dict[str, Any]] = {}
        for item in posts:
            if not isinstance(item, dict):
                continue
            event_id = item.get("event_id")
            if isinstance(event_id, str) and event_id:
                receipts[event_id] = item
        return receipts

    # ── Per-event apply ───────────────────────────────────────────────

    def _apply(self, event: ResearchVehiclePublicEvent) -> dict[str, Any] | None:
        fanout = decide_cross_surface_fanout(event, "arena", "publish")
        if fanout.decision != "allow":
            log.warning(
                "arena public-event fanout blocked for %s: %s",
                event.event_id,
                ",".join(fanout.reasons),
            )
            self.posts_total.labels(result="denied").inc()
            return _post_receipt(event, result="denied")

        verdict = allowlist_check(
            ALLOWLIST_SURFACE,
            event.event_type,
            _allowlist_payload(event),
        )
        if verdict.decision == "deny":
            log.warning("allowlist DENY for arena post: %s", verdict.reason)
            self.posts_total.labels(result="denied").inc()
            return _post_receipt(event, result="denied")

        try:
            content, source_url = self._compose(event)
        except Exception:  # noqa: BLE001
            log.exception("composer failed for event")
            self.posts_total.labels(result="compose_error").inc()
            return _post_receipt(event, result="compose_error")

        content = content[: self._text_limit]

        if self._dry_run:
            log.info(
                "DRY RUN — would post to arena channel=%s source=%r content=%r",
                self._channel_slug,
                source_url,
                content,
            )
            self.posts_total.labels(result="dry_run").inc()
            return _post_receipt(event, result="dry_run", content=content, source_url=source_url)

        result = self._send_block(content, source_url)
        self.posts_total.labels(result=result.result).inc()
        return _post_receipt(
            event,
            result=result.result,
            content=content,
            source_url=source_url,
            detail=result.detail,
        )

    def _compose(self, event: ResearchVehiclePublicEvent) -> tuple[str, str | None]:
        if self._compose_fn is not None:
            return self._compose_fn(event)
        return _default_compose(event)

    def _send_block(self, content: str, source_url: str | None) -> _BlockResult:
        try:
            publisher = self._build_publisher()
        except Exception:  # noqa: BLE001
            log.exception("arena publication-bus publisher init failed")
            return _BlockResult("auth_error")

        try:
            result = publisher.publish(
                PublisherPayload(
                    target=self._publication_target,
                    text=content,
                    metadata={"source_url": source_url},
                )
            )
        except Exception:  # noqa: BLE001
            log.exception("arena publication-bus publish raised")
            return _BlockResult("error")

        if result.ok:
            return _BlockResult("ok", detail=result.detail)
        if result.refused:
            if "credential" in result.detail.lower() or "creds" in result.detail.lower():
                return _BlockResult("no_credentials", detail=result.detail)
            return _BlockResult("denied", detail=result.detail)
        if result.error:
            return _BlockResult("error", detail=result.detail)
        return _BlockResult("error", detail=result.detail)

    def _build_publisher(self):
        factory = self._publisher_factory or _default_publisher_factory
        return factory(self._token, self._channel_slug)


def _default_publisher_factory(token: str | None, channel_slug: str | None):
    return ArenaPublisher(token=token, channel_slug=channel_slug)


def _publisher_result_to_status(result: PublisherResult) -> str:
    if result.ok:
        return "ok"
    if result.refused:
        if "credential" in result.detail.lower() or "creds" in result.detail.lower():
            return "no_credentials"
        return "denied"
    if result.error:
        return "error"
    return "error"


# ── Default helpers (composer) ───────────────────────────────────────


def _default_compose(event: ResearchVehiclePublicEvent) -> tuple[str, str | None]:
    """Build block content + optional source URL from canonical public-event metadata.

    Defers to ``metadata_composer.compose_metadata(scope="cross_surface")``
    for the body when available (so framing stays consistent with the
    mastodon/bluesky adapters); the source URL is derived directly from
    the event's frame_ref / public_url / chapter_ref per event type.
    """
    from agents.metadata_composer.composer import compose_metadata

    composed = compose_metadata(
        triggering_event=_composer_trigger_from_public_event(event),
        scope="cross_surface",
    )
    content = (
        getattr(composed, "arena_block", None)
        or getattr(composed, "bluesky_post", None)
        or _fallback_public_event_content(event)
    )
    source_url = _arena_source_url(event)
    return content, source_url


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
            "frame_uri": event.frame_ref.uri if event.frame_ref else None,
            "source_event_id": event.event_id,
        },
    }


def _event_intent(event: ResearchVehiclePublicEvent) -> str:
    if event.chapter_ref is not None and event.chapter_ref.label:
        return event.chapter_ref.label
    if event.event_type == "aesthetic.frame_capture":
        return "aesthetic frame"
    if event.event_type == "chronicle.high_salience":
        return "high-salience observation"
    if event.event_type == "governance.enforcement":
        return "governance enforcement"
    if event.event_type == "omg.weblog":
        return "weblog post"
    if event.event_type == "arena_block.candidate":
        return "arena block candidate"
    if event.event_type == "publication.artifact":
        return "publication artifact"
    if event.event_type == "velocity.digest":
        return "daily velocity digest"
    return event.event_type


def _fallback_public_event_content(event: ResearchVehiclePublicEvent) -> str:
    if event.event_type in {"governance.enforcement", "omg.weblog", "velocity.digest"}:
        return f"Hapax {_event_intent(event)}."
    return f"Hapax livestream: {_event_intent(event)}."


def _arena_source_url(event: ResearchVehiclePublicEvent) -> str | None:
    """Pick the most appropriate Are.na block ``source`` URL for this event.

    aesthetic.frame_capture prefers ``frame_ref.uri`` (image block), all
    other types prefer ``public_url`` (link block). arena_block.candidate
    falls back to ``frame_ref.uri`` if no ``public_url`` is set.
    """
    if event.event_type == "aesthetic.frame_capture":
        if event.frame_ref is not None:
            return event.frame_ref.uri
        return event.public_url
    if event.public_url:
        return event.public_url
    if event.frame_ref is not None:
        return event.frame_ref.uri
    return None


def _allowlist_payload(event: ResearchVehiclePublicEvent) -> dict[str, Any]:
    payload: dict[str, Any] = {"event": event.model_dump(mode="json")}
    if event.event_type in {
        "chronicle.high_salience",
        "governance.enforcement",
        "aesthetic.frame_capture",
        "omg.weblog",
        "publication.artifact",
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


def _post_receipt(
    event: ResearchVehiclePublicEvent,
    *,
    result: str,
    content: str | None = None,
    source_url: str | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "event_id": event.event_id,
        "result": result,
        "event_public_url": event.public_url,
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    if content:
        receipt["content"] = content
    if source_url:
        receipt["source_url"] = source_url
    if detail:
        receipt["detail"] = detail
    return receipt


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
        publisher = _default_publisher_factory(token, slug)
    except Exception:  # noqa: BLE001
        log.exception("arena publisher init failed for artifact %s", getattr(artifact, "slug", "?"))
        return "auth_error"

    try:
        result = publisher.publish(
            PublisherPayload(
                target=DEFAULT_PUBLICATION_TARGET,
                text=content,
                metadata={"source_url": source_url},
            )
        )
    except Exception:  # noqa: BLE001
        log.exception(
            "arena publication-bus publish raised for artifact %s", getattr(artifact, "slug", "?")
        )
        return "error"
    return _publisher_result_to_status(result)


def _compose_artifact_content(artifact) -> str:  # type: ignore[no-untyped-def]
    """Render a ``PreprintArtifact`` to Are.na-bounded block content.

    Prefers ``attribution_block`` so per-artifact framing stays
    authoritative; otherwise builds ``"{title} — {abstract}"``.
    Truncated to ``ARENA_BLOCK_TEXT_LIMIT`` (4096).

    The Refusal Brief's ``non_engagement_clause`` (LONG form, fits
    Are.na's 4096-char block) is appended when the artifact isn't the
    Refusal Brief itself and doesn't already cite the brief. Self-
    referential artifacts skip the clause; if the LONG form would
    exceed the block limit it falls back to the SHORT form, then drops
    silently if even SHORT doesn't fit.
    """
    from shared.attribution_block import (
        NON_ENGAGEMENT_CLAUSE_LONG,
        NON_ENGAGEMENT_CLAUSE_SHORT,
    )

    title = getattr(artifact, "title", "") or ""
    abstract = getattr(artifact, "abstract", "") or ""
    attribution = getattr(artifact, "attribution_block", "") or ""

    if attribution:
        body = attribution
    elif abstract:
        body = f"{title} — {abstract}"
    else:
        body = title or "hapax — publication artifact"

    body = body[:ARENA_BLOCK_TEXT_LIMIT]

    slug = getattr(artifact, "slug", "") or ""
    if slug != "refusal-brief" and "refusal" not in body.lower():
        for clause in (NON_ENGAGEMENT_CLAUSE_LONG, NON_ENGAGEMENT_CLAUSE_SHORT):
            candidate = f"{body}\n\n{clause}"
            if len(candidate) <= ARENA_BLOCK_TEXT_LIMIT:
                body = candidate
                break

    return body


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
        description="Tail canonical public events and post to a Hapax-owned Are.na channel.",
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
