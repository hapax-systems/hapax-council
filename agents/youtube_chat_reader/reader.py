"""Reader loop: poll ``liveChatMessages.list`` and emit impingements.

Run shape::

    python -m agents.youtube_chat_reader

The daemon owns one :class:`YouTubeApiClient` (scoped streaming token),
one :class:`AuthorAnonymizer` (per-process key), and one in-memory
ring of last-N sanitized messages for the chat-state surface. State
that needs to survive restart (per-broadcast ``nextPageToken``) is
not load-bearing — restart pulls everything from the broadcast's chat
backlog within a few API calls.

Idle / active state machine:

* **Idle** (no live broadcast) — sleep ``IDLE_INTERVAL_S``, recheck.
  Zero ``liveChatMessages.list`` calls in this state, so quota is only
  consumed during active streams.
* **Active** — paginate through ``liveChatMessages.list`` honouring
  the response's ``pollingIntervalMillis``. On 404 / 410 / "chat
  ended" the daemon drops back to Idle and re-resolves on the next
  tick.
"""

from __future__ import annotations

import json
import logging
import os
import signal as _signal
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from prometheus_client import REGISTRY, CollectorRegistry, Counter, Gauge

from agents.youtube_chat_reader.anonymize import AuthorAnonymizer
from agents.youtube_chat_reader.transform import (
    SOURCE_TAG,
    build_bus_record,
    build_state_record,
)
from shared.youtube_api_client import READONLY_SCOPES, YouTubeApiClient
from shared.youtube_rate_limiter import QuotaBucket

log = logging.getLogger(__name__)

DEFAULT_IMPINGEMENT_PATH = Path("/dev/shm/hapax-dmn/impingements.jsonl")
DEFAULT_CHAT_STATE_PATH = Path("/dev/shm/hapax-chat/recent.jsonl")
DEFAULT_RING_SIZE = 50
DEFAULT_IDLE_INTERVAL_S = 60.0
DEFAULT_MIN_POLL_INTERVAL_S = 2.0
DEFAULT_MAX_POLL_INTERVAL_S = 30.0
LIVECHAT_ENDPOINT = "liveChatMessages.list"
LIVEBROADCAST_ENDPOINT = "liveBroadcasts.list"
LIVECHAT_QUOTA_COST = 5
LIVEBROADCAST_QUOTA_COST = 1


class ChatReader:
    """YouTube live-chat impingement emitter.

    Public surface mirrors :class:`agents.youtube_telemetry.emitter.TelemetryEmitter`:
    :meth:`tick_once` for tests / one-shot drives, :meth:`run_forever`
    for the systemd daemon.
    """

    def __init__(
        self,
        *,
        client: YouTubeApiClient | None = None,
        anonymizer: AuthorAnonymizer | None = None,
        impingement_path: Path = DEFAULT_IMPINGEMENT_PATH,
        chat_state_path: Path = DEFAULT_CHAT_STATE_PATH,
        ring_size: int = DEFAULT_RING_SIZE,
        idle_interval_s: float = DEFAULT_IDLE_INTERVAL_S,
        min_poll_interval_s: float = DEFAULT_MIN_POLL_INTERVAL_S,
        max_poll_interval_s: float = DEFAULT_MAX_POLL_INTERVAL_S,
        registry: CollectorRegistry = REGISTRY,
    ) -> None:
        self._client = client if client is not None else _build_default_client()
        self._anonymizer = anonymizer if anonymizer is not None else AuthorAnonymizer()
        self._impingement_path = impingement_path
        self._chat_state_path = chat_state_path
        self._ring: deque[dict[str, Any]] = deque(maxlen=ring_size)
        self._idle_interval_s = idle_interval_s
        self._min_poll_interval_s = min_poll_interval_s
        self._max_poll_interval_s = max_poll_interval_s
        self._stop_evt = threading.Event()

        # Per-broadcast ephemeral state (None when idle).
        self._active_broadcast_id: str | None = None
        self._active_live_chat_id: str | None = None
        self._next_page_token: str | None = None
        self._next_poll_at: float = 0.0

        self._messages_total = _get_or_create_counter(
            registry,
            "hapax_youtube_chat_messages_total",
            "Live-chat messages emitted to the impingement bus.",
            ["interrupt_token"],
        )
        self._poll_total = _get_or_create_counter(
            registry,
            "hapax_youtube_chat_polls_total",
            "Live-chat poll attempts and outcomes.",
            ["result"],
        )
        self._active_gauge = _get_or_create_gauge(
            registry,
            "hapax_youtube_chat_active",
            "1 when the daemon is paginating an active live broadcast, else 0.",
        )
        self._ring_size_gauge = _get_or_create_gauge(
            registry,
            "hapax_youtube_chat_ring_size",
            "Current size of the in-memory chat-state ring buffer.",
        )

    # ── Public API ────────────────────────────────────────────────────

    def tick_once(self, *, now: float | None = None) -> None:
        """Drive one iteration of the state machine."""
        now = time.time() if now is None else now
        if not self._client.enabled:
            log.debug("client disabled — no credentials; idling")
            self._active_gauge.set(0)
            return

        if self._active_live_chat_id is None:
            self._enter_active_or_idle(now)
            return

        if now < self._next_poll_at:
            return

        self._poll_chat(now)

    def run_forever(self) -> None:
        """Block until SIGTERM/SIGINT, ticking the state machine."""
        for sig in (_signal.SIGTERM, _signal.SIGINT):
            try:
                _signal.signal(sig, lambda *_: self._stop_evt.set())
            except ValueError:
                pass

        log.info(
            "youtube_chat_reader starting — bus=%s state=%s",
            self._impingement_path,
            self._chat_state_path,
        )
        while not self._stop_evt.is_set():
            try:
                self.tick_once()
            except Exception:  # noqa: BLE001
                log.exception("tick failed; sleeping before retry")
                self._stop_evt.wait(self._idle_interval_s)
                continue
            sleep_s = self._sleep_for_state()
            self._stop_evt.wait(sleep_s)

    def stop(self) -> None:
        self._stop_evt.set()

    # ── Reverse-channel Protocol surface ──────────────────────────────
    # Satisfies ``agents.youtube_chat_reader.YoutubeChatReader``. The
    # poster lane (cc-task ``chat-response-verbal-and-text``) calls
    # ``live_chat_id()`` to resolve the POST target for
    # ``liveChatMessages.insert``.

    def live_chat_id(self) -> str:
        """Return the active broadcast's ``liveChatId``.

        Imported lazily to avoid a circular import at package load
        time — ``__init__.py`` imports this module, so a top-level
        ``from agents.youtube_chat_reader import ...`` would loop.
        """
        from agents.youtube_chat_reader import YoutubeChatReaderUnavailable

        if self._active_live_chat_id is None:
            raise YoutubeChatReaderUnavailable("no active broadcast — liveChatId unresolved")
        return self._active_live_chat_id

    def recent_messages(self, *, limit: int = 50) -> list:
        """Return the last ``limit`` chat messages as ChatMessageSnapshot.

        Lazy import on the snapshot type for the same reason as
        ``live_chat_id``. Sentiment is reported as ``0.0`` because the
        reader deliberately does no per-message sentiment scoring (see
        ``scripts/chat-monitor.py`` design note: "no individual message
        is ever scored as good or bad"). A future enrichment lane may
        attach sentiment as a separate signal without touching the
        reader's invariants.
        """
        from agents.youtube_chat_reader import ChatMessageSnapshot

        items = list(self._ring)[-limit:] if limit > 0 else []
        return [
            ChatMessageSnapshot(
                author_hash=entry["author_token"],
                text=entry["text"],
                sentiment=0.0,
                length=entry["length"],
                posted_at_unix=entry["ts"],
            )
            for entry in items
        ]

    # ── State machine internals ───────────────────────────────────────

    def _sleep_for_state(self) -> float:
        if self._active_live_chat_id is None:
            return self._idle_interval_s
        delay = max(0.0, self._next_poll_at - time.time())
        return max(self._min_poll_interval_s, min(delay, self._max_poll_interval_s))

    def _enter_active_or_idle(self, now: float) -> None:
        broadcast = self._resolve_active_broadcast()
        if broadcast is None:
            self._active_broadcast_id = None
            self._active_live_chat_id = None
            self._next_page_token = None
            self._active_gauge.set(0)
            self._next_poll_at = now + self._idle_interval_s
            return

        broadcast_id, live_chat_id = broadcast
        if live_chat_id != self._active_live_chat_id:
            log.info(
                "active broadcast: %s (liveChatId=%s) — entering active state",
                broadcast_id,
                live_chat_id,
            )
        self._active_broadcast_id = broadcast_id
        self._active_live_chat_id = live_chat_id
        self._next_page_token = None
        self._next_poll_at = now
        self._active_gauge.set(1)

    def _drop_to_idle(self, reason: str) -> None:
        log.info("dropping to idle: %s", reason)
        self._active_broadcast_id = None
        self._active_live_chat_id = None
        self._next_page_token = None
        self._active_gauge.set(0)

    def _resolve_active_broadcast(self) -> tuple[str, str] | None:
        """Return ``(broadcast_id, liveChatId)`` for the active live, or None.

        Picks the first item with ``lifeCycleStatus`` in ``("live",
        "liveStarting", "testing")``. Channel-side filtering is unnecessary
        because ``mine=true`` runs against the operator's authenticated
        token (single-operator axiom — there is no other channel).
        """
        try:
            response = self._client.execute(
                self._client.yt.liveBroadcasts().list(
                    part="id,snippet,status",
                    mine=True,
                    maxResults=50,
                ),
                endpoint=LIVEBROADCAST_ENDPOINT,
                quota_cost_hint=LIVEBROADCAST_QUOTA_COST,
            )
        except Exception:  # noqa: BLE001
            log.warning("liveBroadcasts.list failed", exc_info=True)
            return None
        if response is None:
            return None
        active_family = ("live", "liveStarting", "testing")
        for item in response.get("items") or []:
            lifecycle = (item.get("status") or {}).get("lifeCycleStatus")
            if lifecycle in active_family:
                broadcast_id = item.get("id")
                snippet = item.get("snippet") or {}
                live_chat_id = snippet.get("liveChatId")
                if broadcast_id and live_chat_id:
                    return broadcast_id, live_chat_id
        return None

    def _poll_chat(self, now: float) -> None:
        try:
            request = self._client.yt.liveChatMessages().list(
                liveChatId=self._active_live_chat_id,
                part="id,snippet,authorDetails",
                maxResults=200,
                pageToken=self._next_page_token,
            )
            response = self._client.execute(
                request,
                endpoint=LIVECHAT_ENDPOINT,
                quota_cost_hint=LIVECHAT_QUOTA_COST,
            )
        except Exception:  # noqa: BLE001
            log.warning("liveChatMessages.list raised", exc_info=True)
            self._poll_total.labels(result="error").inc()
            self._drop_to_idle("api raise")
            return

        if response is None:
            # YouTubeApiClient already metricised the cause (rate-limited,
            # disabled, quota_exhausted). Push back hard so we don't burn
            # the rest of the budget retrying inside the same tick.
            self._poll_total.labels(result="skip").inc()
            self._next_poll_at = now + self._max_poll_interval_s
            return

        items = response.get("items") or []
        page_token = response.get("nextPageToken")
        polling_interval_ms = response.get("pollingIntervalMillis") or 5000

        emitted = self._emit_items(items, now=now)
        self._next_page_token = page_token
        self._next_poll_at = now + max(self._min_poll_interval_s, polling_interval_ms / 1000.0)
        self._poll_total.labels(result="ok").inc()
        log.debug(
            "polled liveChatId=%s items=%d emitted=%d nextPoll=%.1fs",
            self._active_live_chat_id,
            len(items),
            emitted,
            polling_interval_ms / 1000.0,
        )

    # ── Emit + persist ────────────────────────────────────────────────

    def _emit_items(self, items: list[dict[str, Any]], *, now: float) -> int:
        if not items:
            return 0
        bus_lines: list[str] = []
        ring_added = 0
        for item in items:
            bus = build_bus_record(
                item,
                anonymizer=self._anonymizer,
                broadcast_id=self._active_broadcast_id,
                now=now,
            )
            if bus is None:
                continue
            bus_lines.append(json.dumps(bus, default=str))

            state = build_state_record(
                item,
                anonymizer=self._anonymizer,
                broadcast_id=self._active_broadcast_id,
                now=now,
            )
            if state is not None:
                self._ring.append(state)
                ring_added += 1

            self._messages_total.labels(interrupt_token=bus["interrupt_token"]).inc()

        if bus_lines:
            self._append_bus(bus_lines)
        if ring_added:
            self._write_ring()
        self._ring_size_gauge.set(len(self._ring))
        return len(bus_lines)

    def _append_bus(self, lines: list[str]) -> None:
        try:
            self._impingement_path.parent.mkdir(parents=True, exist_ok=True)
            with self._impingement_path.open("a", encoding="utf-8") as fh:
                for line in lines:
                    fh.write(line + "\n")
        except OSError:
            log.warning("impingement bus write failed", exc_info=True)

    def _write_ring(self) -> None:
        """Atomically rewrite the chat-state ring buffer.

        Tmp + rename so a reader never observes a partial ring. The
        ring carries the most recent ``ring_size`` records — chat ward
        consumers tail it to render the live message column.
        """
        try:
            self._chat_state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._chat_state_path.with_suffix(self._chat_state_path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                for entry in self._ring:
                    fh.write(json.dumps(entry, default=str) + "\n")
            tmp.replace(self._chat_state_path)
        except OSError:
            log.warning("chat-state surface write failed", exc_info=True)


# ── Module helpers ────────────────────────────────────────────────────


def _build_default_client() -> YouTubeApiClient:
    quota_bucket_path_env = os.environ.get("HAPAX_YT_RATE_LIMIT_STATE")
    quota_bucket = (
        QuotaBucket(state_path=Path(quota_bucket_path_env))
        if quota_bucket_path_env
        else QuotaBucket.default()
    )
    return YouTubeApiClient(scopes=READONLY_SCOPES, rate_limiter=quota_bucket)


def _get_or_create_counter(
    registry: CollectorRegistry, name: str, doc: str, labels: list[str]
) -> Counter:
    """Return existing Counter named ``name`` or create one.

    Re-registration raises in process-global ``REGISTRY`` if the test
    suite spins up multiple :class:`ChatReader` instances. The lookup
    keeps unit tests insulated without leaking state.
    """
    existing = getattr(registry, "_names_to_collectors", {}).get(name)
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Counter(name, doc, labels, registry=registry)


def _get_or_create_gauge(registry: CollectorRegistry, name: str, doc: str) -> Gauge:
    existing = getattr(registry, "_names_to_collectors", {}).get(name)
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Gauge(name, doc, registry=registry)


__all__ = [
    "DEFAULT_CHAT_STATE_PATH",
    "DEFAULT_IDLE_INTERVAL_S",
    "DEFAULT_IMPINGEMENT_PATH",
    "DEFAULT_MAX_POLL_INTERVAL_S",
    "DEFAULT_MIN_POLL_INTERVAL_S",
    "DEFAULT_RING_SIZE",
    "LIVECHAT_ENDPOINT",
    "LIVECHAT_QUOTA_COST",
    "SOURCE_TAG",
    "ChatReader",
]
