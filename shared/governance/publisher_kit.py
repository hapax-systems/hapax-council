"""``BasePublisher`` ABC consolidating the cross_surface publisher pattern.

Phase 0 prerequisite (PUB-P0-B keystone) per the v5 workstream realignment.
The third of 4 Phase 0 primitives unblocking the auto-publisher capability
work; PUB-P0-C ``co_author_model`` (#1396) and PUB-P0-A ``preprint_artifact``
(#1400) are predecessors.

The pattern repeated verbatim across 4 cross_surface posters
(``bluesky_post.py``, ``mastodon_post.py``, ``arena_post.py``,
``discord_webhook.py``) is:

1. Tail ``/dev/shm/hapax-broadcast/events.jsonl``
2. Read JSONL-cursor durability
3. Filter by ``event_type``
4. Allowlist-gate via ``shared.governance.publication_allowlist.check``
5. Compose surface-specific text
6. Optional legal-name guard via ``shared.governance.omg_referent.safe_render``
7. Dry-run vs send
8. Prometheus ``Counter(metric_name, ..., ["result"])`` per outcome

This kit lifts ~140 LOC of repeated infrastructure into a single ABC.
Subclass surface drops to ~80 LOC: surface metadata as ``ClassVar``,
``compose(event)`` and ``send(composed)`` as the only required overrides.

## Refactor plan

This kit ships standalone with green tests; it does NOT bulk-refactor
existing publishers in the same PR. Each surface refactor (PUB-P1-A
bsky, PUB-P1-B mastodon, PUB-P1-C arena, plus discord_webhook) is a
separate ticket that diffs to ~−50 LOC net per publisher. Existing
constructor kwargs are preserved by the subclass to keep test
fixtures green.

## Generic over Composed shape

The compose output type is generic. Bluesky/Mastodon publishers compose
``str`` (single text body). Arena composes ``tuple[str, str | None]``
(content + optional source URL). Future publishers may compose richer
structs (``PreprintArtifact``-derived). The kit treats ``Composed`` as
opaque; only ``compose()`` and ``send()`` know its shape.
"""

from __future__ import annotations

import json
import logging
import signal as _signal
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

from prometheus_client import REGISTRY, CollectorRegistry, Counter

from shared.governance.omg_referent import OperatorNameLeak, safe_render
from shared.governance.publication_allowlist import check as allowlist_check

log = logging.getLogger(__name__)


class BasePublisher[Composed](ABC):
    """Cross_surface publisher base class.

    Subclasses set ``ClassVar`` surface metadata + override
    ``compose()`` and ``send()``. The base owns:

    - JSONL-cursor durability over ``event_path``
    - Allowlist gating
    - Optional legal-name leak guard via ``safe_render`` (if
      ``LEGAL_NAME_GUARD_FIELDS`` is non-empty)
    - Dry-run short-circuit
    - Prometheus ``Counter`` per-outcome accounting
    - Daemon loop with SIGTERM/SIGINT graceful shutdown

    Subclasses must populate the ClassVar metadata; the base will
    raise at instantiation if any required ClassVar is unset.
    """

    # ── Required ClassVar metadata ────────────────────────────────

    SURFACE: ClassVar[str] = ""
    """Allowlist surface slug (e.g. ``"bluesky-post"``). Must match the
    YAML filename at ``axioms/contracts/publication/{SURFACE}.yaml``."""

    STATE_KIND: ClassVar[str] = ""
    """Allowlist ``state_kinds`` entry that this publisher emits under
    (e.g. ``"broadcast.boundary"``, ``"publication.artifact"``)."""

    EVENT_TYPE: ClassVar[str] = ""
    """JSONL event ``event_type`` filter (e.g. ``"broadcast_rotated"``)."""

    METRIC_NAME: ClassVar[str] = ""
    """Prometheus counter name. Conventional shape:
    ``hapax_broadcast_{surface}_{verb}_total``."""

    METRIC_DESCRIPTION: ClassVar[str] = ""

    # ── Optional ClassVar metadata ────────────────────────────────

    LEGAL_NAME_GUARD_FIELDS: ClassVar[tuple[str, ...]] = ()
    """Tuple of attribute names on the ``Composed`` value to scan with
    ``safe_render`` before send. Empty tuple disables the scan. Used
    when ``Composed`` is a dataclass / Pydantic model with separable
    fields; for plain ``str`` composers, override
    ``_apply_legal_name_guard`` directly."""

    # ── Construction ──────────────────────────────────────────────

    def __init__(
        self,
        *,
        event_path: Path,
        cursor_path: Path,
        registry: CollectorRegistry = REGISTRY,
        tick_s: float = 30.0,
        dry_run: bool = False,
    ) -> None:
        self._validate_classvars()
        self._event_path = event_path
        self._cursor_path = cursor_path
        self._tick_s = max(1.0, tick_s)
        self._dry_run = dry_run
        self._stop_evt = threading.Event()

        self.posts_total = Counter(
            self.METRIC_NAME,
            self.METRIC_DESCRIPTION or f"{self.SURFACE} posts attempted, by outcome.",
            ["result"],
            registry=registry,
        )

    @classmethod
    def _validate_classvars(cls) -> None:
        for attr in ("SURFACE", "STATE_KIND", "EVENT_TYPE", "METRIC_NAME"):
            if not getattr(cls, attr):
                raise TypeError(f"{cls.__name__} must set ClassVar {attr!r}")

    # ── Abstract surface API ──────────────────────────────────────

    @abstractmethod
    def compose(self, event: dict) -> Composed:
        """Render the surface-specific payload from a JSONL event."""

    @abstractmethod
    def send(self, composed: Composed) -> str:
        """Send the composed payload to the live surface.

        Returns one of: ``"ok"``, ``"error"``, ``"auth_error"``,
        ``"no_credentials"``. Subclasses MUST NOT raise; per-outcome
        labels drive the Prometheus counter.
        """

    def credentials_present(self) -> tuple[bool, str]:
        """Subclasses override to check env vars / config files.

        Default returns ``(True, "")`` — equivalent to "always have
        credentials." Most publishers override; some (webmention)
        genuinely don't need them.
        """
        return True, ""

    # ── Public API ────────────────────────────────────────────────

    def run_once(self) -> int:
        """Process all pending events; return count handled."""
        cursor = self._read_cursor()
        handled = 0
        for event, byte_after in self._tail_from(cursor):
            if event.get("event_type") != self.EVENT_TYPE:
                cursor = byte_after
                continue
            self._apply(event)
            cursor = byte_after
            handled += 1
        if handled:
            self._write_cursor(cursor)
        return handled

    def run_forever(self) -> None:
        """Daemon loop. Trap SIGTERM/SIGINT for graceful shutdown."""
        for sig in (_signal.SIGTERM, _signal.SIGINT):
            try:
                _signal.signal(sig, lambda *_: self._stop_evt.set())
            except ValueError:
                pass

        log.info(
            "%s starting, surface=%s tick=%.1fs dry_run=%s",
            type(self).__name__,
            self.SURFACE,
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

    # ── Cursor + tail (JSONL) ─────────────────────────────────────

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

    # ── Per-event apply ───────────────────────────────────────────

    def _apply(self, event: dict) -> None:
        verdict = allowlist_check(self.SURFACE, self.STATE_KIND, {"event": event})
        if verdict.decision == "deny":
            log.warning("allowlist DENY for %s: %s", self.SURFACE, verdict.reason)
            self.posts_total.labels(result="denied").inc()
            return

        try:
            composed = self.compose(event)
        except Exception:  # noqa: BLE001
            log.exception("composer failed for event")
            self.posts_total.labels(result="compose_error").inc()
            return

        try:
            composed = self._apply_legal_name_guard(composed, event=event)
        except OperatorNameLeak:
            log.exception("legal-name leak detected; suppressing send")
            self.posts_total.labels(result="legal_name_leak").inc()
            return

        if self._dry_run:
            log.info("DRY RUN — would post to %s: %r", self.SURFACE, composed)
            self.posts_total.labels(result="dry_run").inc()
            return

        present, reason = self.credentials_present()
        if not present:
            log.warning("no credentials for %s (%s); skipping live post", self.SURFACE, reason)
            self.posts_total.labels(result="no_credentials").inc()
            return

        result = self.send(composed)
        self.posts_total.labels(result=result).inc()

    def _apply_legal_name_guard(self, composed: Composed, *, event: dict) -> Composed:
        """Run ``safe_render`` over each field named in
        ``LEGAL_NAME_GUARD_FIELDS``.

        Subclasses with non-attribute composed shapes (plain ``str``,
        ``tuple``) override this directly. Default implementation
        treats ``composed`` as a dataclass/Pydantic-model and rewrites
        the named attributes in-place via ``object.__setattr__`` (works
        for both mutable dataclasses and frozen-bypass paths; Pydantic
        models with ``model_config = ConfigDict(frozen=True)`` will
        need a per-field override).
        """
        if not self.LEGAL_NAME_GUARD_FIELDS:
            return composed

        segment_id = event.get("vod_segment_id") or event.get("incoming_broadcast_id")
        for field_name in self.LEGAL_NAME_GUARD_FIELDS:
            value = getattr(composed, field_name, None)
            if not isinstance(value, str):
                continue
            rendered = safe_render(value, segment_id=segment_id)
            object.__setattr__(composed, field_name, rendered)
        return composed


__all__ = ["BasePublisher"]
