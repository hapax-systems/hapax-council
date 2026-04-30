"""mail-monitor message dispatcher.

Spec: ``docs/specs/2026-04-25-mail-monitor.md`` §3 / §5.4.

The runner is the post-classifier orchestrator. Given a fetched Gmail
message dict, it:

1. Classifies the message with deterministic label/correlation rules.
2. Looks up the per-category processor.
3. Invokes the processor.
4. Audits each step.

``process_history`` is the Pub/Sub-driven runtime loop. It reads Gmail
history per Hapax label id, fetches only those message ids, enriches
the message dict with classifier inputs, and dispatches to the
category-specific processor.
"""

from __future__ import annotations

import base64
import contextlib
import fcntl
import hashlib
import json
import logging
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from prometheus_client import Counter

from agents.mail_monitor.audit import audit_call
from agents.mail_monitor.auto_clicker import process_message as process_auto_accept
from agents.mail_monitor.classifier import Category, classify
from agents.mail_monitor.correlations import (
    PENDING_ACTIONS_PATH,
    find_pending_action,
    sender_domain,
    sender_email,
)
from agents.mail_monitor.processors.discard import process_discard
from agents.mail_monitor.processors.operational import process_operational
from agents.mail_monitor.processors.refusal_feedback import emit_refusal_feedback
from agents.mail_monitor.processors.suppress import process_suppress
from agents.mail_monitor.processors.verify import process_verify
from agents.mail_monitor.watch import load_watch_state

log = logging.getLogger(__name__)

STATE_DIR = Path("~/.cache/mail-monitor").expanduser()
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
HISTORY_CURSOR_PATH = STATE_DIR / "cursor.json"
LEGACY_HISTORY_CURSOR_PATH = STATE_DIR / "history-cursor.json"
LAST_PUSH_PATH = Path("/dev/shm/mail-monitor/last-push.json")
SEEN_SET_PATH = STATE_DIR / "seen-message-ids.json"
MAIL_MONITOR_LOCK_PATH = RUNTIME_DIR / "mail-monitor.lock"
SEEN_TTL = timedelta(days=90)

DISPATCH_COUNTER = Counter(
    "hapax_mail_monitor_dispatch_total",
    "Per-message dispatch attempts by category and outcome.",
    labelnames=("category", "result"),
)
for _category in Category:
    for _result in ("processed", "deferred", "error"):
        DISPATCH_COUNTER.labels(category=_category.value, result=_result)


def dispatch_message(service: Any, message: dict[str, Any]) -> Category:
    """Classify ``message`` and invoke the per-category processor.

    ``message`` is the dict returned by ``messages.get`` enriched with
    ``label_names``, ``replies_to_hapax_thread``, ``body_text`` (see
    classifier docstring). ``service`` is the authenticated Gmail
    discovery client.

    Returns the resolved :class:`Category`.
    """
    message_id = message.get("id") or message.get("messageId") or "<unknown>"
    category, source = classify(message)

    log.info(
        "mail dispatch: id=%s category=%s source=%s",
        message_id,
        category.value,
        source,
    )
    audit_call(
        "messages.get",
        message_id=message_id,
        label=_label_for_audit(message, category),
        result="ok",
    )

    if category is Category.F_ANTIPATTERN:
        ok = process_discard(service, message)
        DISPATCH_COUNTER.labels(
            category=category.value,
            result="processed" if ok else "error",
        ).inc()
        return category

    if category is Category.E_REFUSAL_FEEDBACK:
        emit_refusal_feedback(message, kind="feedback")
        DISPATCH_COUNTER.labels(category=category.value, result="processed").inc()
        return category

    if category is Category.C_SUPPRESS:
        ok = process_suppress(service, message)
        DISPATCH_COUNTER.labels(
            category=category.value,
            result="processed" if ok else "error",
        ).inc()
        return category

    if category is Category.B_VERIFY:
        ok = process_verify(service, message)
        DISPATCH_COUNTER.labels(
            category=category.value,
            result="processed" if ok else "error",
        ).inc()
        return category

    if category is Category.A_ACCEPT:
        ok = process_auto_accept(message)
        DISPATCH_COUNTER.labels(
            category=category.value,
            result="processed" if ok else "error",
        ).inc()
        return category

    if category is Category.D_OPERATIONAL:
        ok = process_operational(message)
        DISPATCH_COUNTER.labels(
            category=category.value,
            result="processed" if ok else "error",
        ).inc()
        return category

    # Future-proofing: should never reach here while Category enum has
    # only six members, but a defensive `error` outcome keeps the
    # exhaustiveness explicit.
    DISPATCH_COUNTER.labels(category=category.value, result="error").inc()  # pragma: no cover
    return category


def _label_for_audit(message: dict[str, Any], category: Category) -> str:
    """Return the most specific label name to record in the audit log."""
    names = message.get("label_names") or []
    for name in names:
        if name.startswith("Hapax/"):
            return name
    return f"<no-hapax-label;cat={category.value}>"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _persist_history_cursor(
    history_id: str,
    *,
    path: Path = HISTORY_CURSOR_PATH,
    last_push_at: datetime | None = None,
) -> None:
    timestamp = (last_push_at or _utc_now()).isoformat()
    _atomic_write_json(
        path,
        {
            "history_id": str(history_id),
            "historyId": str(history_id),
            "last_push_at": timestamp,
        },
    )


def _persist_last_push(
    history_id: str,
    *,
    path: Path = LAST_PUSH_PATH,
    last_push_at: datetime | None = None,
) -> None:
    _atomic_write_json(
        path,
        {
            "history_id": str(history_id),
            "last_push_at": (last_push_at or _utc_now()).isoformat(),
        },
    )


def _load_history_cursor(*, path: Path = HISTORY_CURSOR_PATH) -> str | None:
    if path == HISTORY_CURSOR_PATH and not path.exists() and LEGACY_HISTORY_CURSOR_PATH.exists():
        path = LEGACY_HISTORY_CURSOR_PATH
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    history_id = data.get("history_id") or data.get("historyId")
    return str(history_id) if history_id else None


def _initial_history_id(notification_history_id: str, *, cursor_path: Path) -> str:
    cursor = _load_history_cursor(path=cursor_path)
    if cursor:
        return cursor
    watch_state = load_watch_state()
    if watch_state and watch_state.get("historyId"):
        return str(watch_state["historyId"])
    return str(notification_history_id)


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    headers = payload.get("headers") or []
    return {
        str(header.get("name", "")).lower(): str(header.get("value", ""))
        for header in headers
        if header.get("name")
    }


def _decode_body_part(part: dict[str, Any]) -> str:
    data = (part.get("body") or {}).get("data")
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(str(data) + "==").decode("utf-8", errors="replace")
    except (ValueError, UnicodeDecodeError):
        return ""


def _body_text(payload: dict[str, Any]) -> str:
    if payload.get("mimeType") == "text/plain":
        return _decode_body_part(payload)
    for part in payload.get("parts") or []:
        if part.get("mimeType") == "text/plain":
            return _decode_body_part(part)
    return ""


def _enrich_message(
    raw: dict[str, Any],
    *,
    label_ids_by_name: dict[str, str],
    pending_actions_path: Path = PENDING_ACTIONS_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    id_to_name = {label_id: name for name, label_id in label_ids_by_name.items()}
    label_names = [
        id_to_name[label_id] for label_id in raw.get("labelIds", []) if label_id in id_to_name
    ]
    hapax_label_ids_by_name = {name: label_id for name, label_id in label_ids_by_name.items()}
    payload = raw.get("payload") or {}
    headers = _headers(payload)
    enriched = dict(raw)
    enriched["label_names"] = label_names
    enriched["label_ids_by_name"] = hapax_label_ids_by_name
    enriched["sender"] = headers.get("from", "")
    enriched["headers"] = headers
    enriched["envelope_from"] = sender_email(headers.get("return-path") or headers.get("from"))
    enriched["subject"] = headers.get("subject", "")
    enriched["body_text"] = _body_text(payload)
    enriched["message_id_header"] = headers.get("message-id", "")
    refs = " ".join(
        value for value in (headers.get("in-reply-to"), headers.get("references")) if value
    )
    enriched["replies_to_hapax_thread"] = "hapax" in refs.lower()
    _enrich_pending_action_correlation(
        enriched,
        pending_actions_path=pending_actions_path,
        now=now,
    )
    return enriched


def _enrich_pending_action_correlation(
    enriched: dict[str, Any],
    *,
    pending_actions_path: Path,
    now: datetime | None,
) -> None:
    """Attach bounded pending-action correlation fields to ``enriched``."""
    domain = sender_domain(enriched.get("envelope_from") or enriched.get("sender"))
    if domain is None:
        enriched["outbound_correlation_hit"] = False
        enriched["auto_accept_candidate"] = False
        return
    pending_record = find_pending_action(
        domain,
        path=pending_actions_path,
        now=(now.timestamp() if now is not None else None),
    )
    if pending_record is None:
        enriched["outbound_correlation_hit"] = False
        enriched["auto_accept_candidate"] = False
        return
    enriched["outbound_correlation_hit"] = True
    enriched["auto_accept_candidate"] = True
    artefact_id = _artefact_id_from_pending_record(pending_record)
    if artefact_id is not None:
        enriched["artefact_id"] = artefact_id


def _artefact_id_from_pending_record(record: dict[str, Any]) -> str | None:
    for key in ("artefact_id", "artifact_id", "artefact", "artifact"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _message_ids_from_history_page(page: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for history in page.get("history", []) or []:
        for key in ("messagesAdded", "labelsAdded"):
            for item in history.get(key, []) or []:
                message = item.get("message") or {}
                message_id = message.get("id")
                if message_id:
                    ids.append(str(message_id))
    return ids


@contextlib.contextmanager
def _mail_monitor_lock(path: Path = MAIL_MONITOR_LOCK_PATH) -> Iterator[None]:
    """Serialize push/fallback ingestion across processes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _load_seen_set(
    *,
    path: Path = SEEN_SET_PATH,
    now: datetime | None = None,
) -> dict[str, str]:
    if not path.exists():
        return {}
    current = now or _utc_now()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    cutoff = current - SEEN_TTL
    seen: dict[str, str] = {}
    for digest, timestamp in raw.items():
        if not isinstance(digest, str) or not isinstance(timestamp, str):
            continue
        try:
            seen_at = datetime.fromisoformat(timestamp)
        except ValueError:
            continue
        if seen_at.tzinfo is None:
            seen_at = seen_at.replace(tzinfo=UTC)
        if seen_at >= cutoff:
            seen[digest] = timestamp
    return seen


def _persist_seen_set(path: Path, seen: dict[str, str]) -> None:
    _atomic_write_json(path, seen)


def _message_dedup_digest(message: dict[str, Any]) -> str:
    message_id = str(
        message.get("message_id_header") or message.get("Message-ID") or message.get("id") or ""
    )
    return hashlib.sha1(message_id.encode("utf-8"), usedforsecurity=False).hexdigest()


def process_history(
    service: Any,
    notification_history_id: str,
    *,
    label_ids_by_name: dict[str, str],
    cursor_path: Path = HISTORY_CURSOR_PATH,
    last_push_path: Path = LAST_PUSH_PATH,
    seen_set_path: Path = SEEN_SET_PATH,
    pending_actions_path: Path = PENDING_ACTIONS_PATH,
    lock_path: Path = MAIL_MONITOR_LOCK_PATH,
    now: datetime | None = None,
    record_last_push: bool = True,
) -> int:
    """Process Gmail history after a Pub/Sub notification.

    The public entrypoint owns the global ingestion lock. This keeps
    Pub/Sub push and cron fallback from racing cursor/seen-set updates.
    """

    with _mail_monitor_lock(lock_path):
        return _process_history_unlocked(
            service,
            notification_history_id,
            label_ids_by_name=label_ids_by_name,
            cursor_path=cursor_path,
            last_push_path=last_push_path,
            seen_set_path=seen_set_path,
            pending_actions_path=pending_actions_path,
            now=now,
            record_last_push=record_last_push,
        )


def _process_history_unlocked(
    service: Any,
    notification_history_id: str,
    *,
    label_ids_by_name: dict[str, str],
    cursor_path: Path,
    last_push_path: Path,
    seen_set_path: Path,
    pending_actions_path: Path,
    now: datetime | None = None,
    record_last_push: bool = True,
) -> int:
    """Process Gmail history after a Pub/Sub notification.

    History reads are label-scoped per Hapax label. The cursor is advanced
    only after all fetched messages have been dispatched.
    """
    processed_at = now or _utc_now()
    start_history_id = _initial_history_id(
        str(notification_history_id),
        cursor_path=cursor_path,
    )
    seen_gmail_ids: set[str] = set()
    seen_messages = _load_seen_set(path=seen_set_path, now=processed_at)
    seen_changed = False
    processed = 0
    for label_id in label_ids_by_name.values():
        page_token: str | None = None
        while True:
            req = (
                service.users()
                .history()
                .list(
                    userId="me",
                    startHistoryId=start_history_id,
                    labelId=label_id,
                    historyTypes=["messageAdded", "labelAdded"],
                    pageToken=page_token,
                )
            )
            page = req.execute()
            for message_id in _message_ids_from_history_page(page):
                if message_id in seen_gmail_ids:
                    continue
                seen_gmail_ids.add(message_id)
                raw = (
                    service.users()
                    .messages()
                    .get(userId="me", id=message_id, format="full")
                    .execute()
                )
                enriched = _enrich_message(
                    raw,
                    label_ids_by_name=label_ids_by_name,
                    pending_actions_path=pending_actions_path,
                    now=processed_at,
                )
                digest = _message_dedup_digest(enriched)
                if digest in seen_messages:
                    continue
                dispatch_message(
                    service,
                    enriched,
                )
                seen_messages[digest] = processed_at.isoformat()
                seen_changed = True
                processed += 1
            page_token = page.get("nextPageToken")
            if not page_token:
                break
    if seen_changed:
        _persist_seen_set(seen_set_path, seen_messages)
    _persist_history_cursor(
        str(notification_history_id),
        path=cursor_path,
        last_push_at=processed_at,
    )
    if record_last_push:
        _persist_last_push(
            str(notification_history_id),
            path=last_push_path,
            last_push_at=processed_at,
        )
    return processed


def register_processor(
    category: Category,
    fn: Callable[[Any, dict[str, Any]], bool],  # noqa: ARG001 — rejected API compatibility
) -> None:  # pragma: no cover
    """Reject dynamic processor registration.

    All six category processors are now wired statically in
    ``dispatch_message`` so dispatch remains auditable and side effects
    are easy to review.
    """
    raise NotImplementedError(
        "register_processor is unsupported; mail-monitor processors are wired statically."
    )
