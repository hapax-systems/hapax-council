"""Mastodon public-event poster.

Tails canonical ``ResearchVehiclePublicEvent`` JSONL records from
``/dev/shm/hapax-public-events/events.jsonl`` and posts a status to the
operator's Mastodon instance only when the event contract, Mastodon aperture
policy, and publication allowlist all permit public fanout.

## Auth

Access-token authentication. Operator generates a token at
``<instance>/settings/applications`` (scope ``write:statuses``) and
exports two env vars via hapax-secrets:

  HAPAX_MASTODON_INSTANCE_URL    # e.g. ``https://mastodon.social``
  HAPAX_MASTODON_ACCESS_TOKEN    # the generated access token

Without either, daemon idles + logs ``no_credentials`` per eligible public
event.

## Composition

Reuses ``metadata_composer.compose_metadata(scope="cross_surface")`` with a
canonical public-event trigger projection. The resulting ``mastodon_post`` is
text only and capped at 500 chars. The 500-char default limit covers the
majority of instances; per-instance overrides can be supplied via
``HAPAX_MASTODON_TEXT_LIMIT``.

## Legacy input

Legacy ``broadcast_rotated`` tailing is removed from this adapter. Broadcast
rotation events reach Mastodon through
``agents.broadcast_boundary_public_event_producer`` which emits
``broadcast.boundary`` ``ResearchVehiclePublicEvent`` records onto the canonical
public-event bus.

## Rate limit

Mastodon's per-instance rate is generous (~300 req / 5min). Our
contract caps us at 6/hour, 30/day — well under. Per-rotation
cadence (~11h) means ~2-3 posts/day in steady state.

## Metrics

``hapax_broadcast_mastodon_posts_total{result}`` is preserved for dashboard
continuity. Results include ``ok``, ``dry_run``, ``denied``,
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

from agents.publication_bus.mastodon_publisher import MastodonPublisher
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
        "HAPAX_MASTODON_CURSOR",
        str(Path.home() / ".cache/hapax/mastodon-post-cursor.txt"),
    )
)
DEFAULT_IDEMPOTENCY_PATH = Path(
    os.environ.get(
        "HAPAX_MASTODON_IDEMPOTENCY_PATH",
        str(Path.home() / ".cache/hapax/mastodon-post-event-ids.json"),
    )
)
METRICS_PORT: int = int(os.environ.get("HAPAX_MASTODON_METRICS_PORT", "9502"))
DEFAULT_TICK_S: float = float(os.environ.get("HAPAX_MASTODON_TICK_S", "30"))
MASTODON_TEXT_LIMIT: int = int(os.environ.get("HAPAX_MASTODON_TEXT_LIMIT", "500"))
DEFAULT_PUBLICATION_TARGET = os.environ.get("HAPAX_MASTODON_PUBLICATION_TARGET", "hapax")

ALLOWLIST_SURFACE = "mastodon-post"
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


@dataclass(frozen=True)
class _StatusResult:
    result: str
    uri: str | None = None
    public_url: str | None = None


class MastodonPoster:
    """Tail canonical public events; post to Mastodon when policy permits."""

    def __init__(
        self,
        *,
        instance_url: str | None = None,
        access_token: str | None = None,
        compose_fn=None,
        publisher_factory=None,
        publication_target: str = DEFAULT_PUBLICATION_TARGET,
        event_path: Path = EVENT_PATH,
        cursor_path: Path = DEFAULT_CURSOR_PATH,
        idempotency_path: Path = DEFAULT_IDEMPOTENCY_PATH,
        registry: CollectorRegistry = REGISTRY,
        tick_s: float = DEFAULT_TICK_S,
        text_limit: int = MASTODON_TEXT_LIMIT,
        dry_run: bool = False,
    ) -> None:
        self._instance_url = instance_url
        self._access_token = access_token
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
            "hapax_broadcast_mastodon_posts_total",
            "Mastodon posts attempted from ResearchVehiclePublicEvent records, broken down by outcome.",
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
            "mastodon public-event poster starting, port=%d tick=%.1fs dry_run=%s instance=%s",
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
        fanout = decide_cross_surface_fanout(event, "mastodon", "publish")
        if fanout.decision != "allow":
            log.warning(
                "mastodon public-event fanout blocked for %s: %s",
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
            log.warning("allowlist DENY for mastodon post: %s", verdict.reason)
            self.posts_total.labels(result="denied").inc()
            return _post_receipt(event, result="denied")

        try:
            text = self._compose(event)
        except Exception:  # noqa: BLE001
            log.exception("composer failed for event")
            self.posts_total.labels(result="compose_error").inc()
            return _post_receipt(event, result="compose_error")

        text = text[: self._text_limit]

        if self._dry_run:
            log.info("DRY RUN — would post to mastodon: text=%r", text)
            self.posts_total.labels(result="dry_run").inc()
            return _post_receipt(event, result="dry_run", text=text)

        status = self._status_post(text)
        self.posts_total.labels(result=status.result).inc()
        return _post_receipt(
            event,
            result=status.result,
            text=text,
            uri=status.uri,
            public_url=status.public_url,
        )

    def _compose(self, event: ResearchVehiclePublicEvent) -> str:
        if self._compose_fn is not None:
            return self._compose_fn(event)
        return _default_compose(event)

    def _status_post(self, text: str) -> _StatusResult:
        try:
            publisher = self._build_publisher()
        except Exception:  # noqa: BLE001
            log.exception("mastodon publication-bus publisher init failed")
            return _StatusResult("auth_error")

        try:
            result = publisher.publish(PublisherPayload(target=self._publication_target, text=text))
        except Exception:  # noqa: BLE001
            log.exception("mastodon publication-bus publish raised")
            return _StatusResult("error")

        if result.ok:
            uri, public_url = _extract_publisher_receipt(result)
            return _StatusResult("ok", uri=uri, public_url=public_url)
        if result.refused:
            if "credential" in result.detail.lower() or "creds" in result.detail.lower():
                return _StatusResult("no_credentials")
            return _StatusResult("denied")
        if result.error:
            return _StatusResult("error")
        return _StatusResult("error")

    def _build_publisher(self):
        factory = self._publisher_factory or _default_publisher_factory
        return factory(self._instance_url, self._access_token)


def _default_publisher_factory(instance_url: str | None, access_token: str | None):
    return MastodonPublisher(instance_url=instance_url, access_token=access_token)


def _extract_publisher_receipt(result: PublisherResult) -> tuple[str | None, str | None]:
    try:
        raw = json.loads(result.detail)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(raw, dict):
        return None, None
    uri = raw.get("uri")
    public_url = raw.get("public_url")
    return (
        uri if isinstance(uri, str) and uri else None,
        public_url if isinstance(public_url, str) and public_url else None,
    )


# ── Default helpers (composer + Mastodon client) ─────────────────────


def _default_compose(event: ResearchVehiclePublicEvent) -> str:
    """Build post text by deferring to metadata_composer."""
    if event.event_type == "omg.weblog" and event.public_url:
        return _fallback_public_event_text(event)

    from agents.metadata_composer.composer import compose_metadata

    composed = compose_metadata(
        triggering_event=_composer_trigger_from_public_event(event),
        scope="cross_surface",
    )
    return composed.mastodon_post or _fallback_public_event_text(event)


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


def _post_receipt(
    event: ResearchVehiclePublicEvent,
    *,
    result: str,
    text: str | None = None,
    uri: str | None = None,
    public_url: str | None = None,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "event_id": event.event_id,
        "result": result,
        "event_public_url": event.public_url,
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    if text:
        receipt["text"] = text
    if uri:
        receipt["uri"] = uri
    if public_url:
        receipt["public_url"] = public_url
    return receipt


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

    text = _compose_artifact_text(artifact)
    if not text:
        return "error"

    try:
        publisher = _default_publisher_factory(instance_url, access_token)
    except Exception:  # noqa: BLE001
        log.exception(
            "mastodon publisher init failed for artifact %s", getattr(artifact, "slug", "?")
        )
        return "auth_error"

    try:
        result = publisher.publish(
            PublisherPayload(
                target=DEFAULT_PUBLICATION_TARGET,
                text=text,
                metadata={"artifact_slug": getattr(artifact, "slug", "")},
            )
        )
    except Exception:  # noqa: BLE001
        log.exception(
            "mastodon publication-bus publish raised for artifact %s",
            getattr(artifact, "slug", "?"),
        )
        return "error"
    if result.ok:
        return "ok"
    if result.refused:
        if "credential" in result.detail.lower() or "creds" in result.detail.lower():
            return "no_credentials"
        return "denied"
    if result.error:
        return "error"
    return "ok"


def _compose_artifact_text(artifact) -> str:  # type: ignore[no-untyped-def]
    """Render a ``PreprintArtifact`` to Mastodon-bounded text.

    Default: ``"{title} — {abstract}"`` truncated to
    ``MASTODON_TEXT_LIMIT``. If the artifact carries a non-empty
    ``attribution_block``, prefer that as the body so per-artifact
    framing stays authoritative.

    The Refusal Brief's ``non_engagement_clause`` (SHORT form, fits
    Mastodon's 500-char body cap with room to spare) is appended when
    the artifact isn't the Refusal Brief itself and doesn't already
    cite the brief. Self-referential artifacts skip the clause; if
    appending the clause would exceed MASTODON_TEXT_LIMIT it's
    dropped silently (artifact framing wins).
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

    body = body[:MASTODON_TEXT_LIMIT]

    slug = getattr(artifact, "slug", "") or ""
    if slug != "refusal-brief" and "refusal" not in body.lower():
        candidate = f"{body}\n\n{NON_ENGAGEMENT_CLAUSE_SHORT}"
        if len(candidate) <= MASTODON_TEXT_LIMIT:
            body = candidate

    return body


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agents.cross_surface.mastodon_post",
        description="Tail canonical public events and post to Mastodon.",
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
