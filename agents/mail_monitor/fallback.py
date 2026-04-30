"""One-shot Gmail Pub/Sub outage fallback for mail-monitor.

Spec: ``docs/specs/2026-04-25-mail-monitor.md`` §1 / §7.3.

The fallback is intentionally a timer-driven one-shot, not a second
ingress daemon. It checks the Pub/Sub push-health marker and, only when
the marker is stale or absent, asks Gmail for the current mailbox
``historyId`` and delegates to :func:`agents.mail_monitor.runner.process_history`.
That keeps the existing ingestion lock, cursor, seen-set, label-scoped
history reads, and category dispatch path as the single implementation.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from prometheus_client import Counter

from agents.mail_monitor.correlations import PENDING_ACTIONS_PATH
from agents.mail_monitor.label_bootstrap import LabelBootstrapError, bootstrap_labels
from agents.mail_monitor.oauth import build_gmail_service, load_credentials
from agents.mail_monitor.runner import (
    HISTORY_CURSOR_PATH,
    LAST_PUSH_PATH,
    MAIL_MONITOR_LOCK_PATH,
    SEEN_SET_PATH,
    process_history,
)

log = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=60)

FallbackResult = Literal[
    "fresh",
    "stale_empty",
    "stale_processed",
    "no_credentials",
    "no_service",
    "no_history_id",
    "label_bootstrap_error",
    "api_error",
]

POLL_REASONS = frozenset({"missing_last_push", "malformed_last_push", "stale_last_push"})
CLEAN_EXIT_RESULTS = frozenset(
    {
        "fresh",
        "stale_empty",
        "stale_processed",
        "no_credentials",
        "no_service",
    }
)

FALLBACK_COUNTER = Counter(
    "hapax_mail_monitor_fallback_total",
    "Mail-monitor Pub/Sub fallback attempts by outcome.",
    labelnames=("result",),
)
for _result in (
    "fresh",
    "stale_empty",
    "stale_processed",
    "no_credentials",
    "no_service",
    "no_history_id",
    "label_bootstrap_error",
    "api_error",
):
    FALLBACK_COUNTER.labels(result=_result)


@dataclass(frozen=True)
class FallbackRun:
    """Redaction-safe summary of one fallback timer run."""

    result: FallbackResult
    reason: str
    processed: int = 0


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def read_last_push_at(path: Path = LAST_PUSH_PATH) -> tuple[datetime | None, str]:
    """Return the last Pub/Sub push timestamp and a decision reason."""

    if not path.exists():
        return None, "missing_last_push"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, "malformed_last_push"
    if not isinstance(data, dict):
        return None, "malformed_last_push"
    parsed = _parse_timestamp(data.get("last_push_at"))
    if parsed is None:
        return None, "malformed_last_push"
    return parsed, "loaded"


def fallback_poll_reason(
    *,
    last_push_path: Path = LAST_PUSH_PATH,
    stale_after: timedelta = STALE_AFTER,
    now: datetime | None = None,
) -> str:
    """Return why the fallback should poll, or ``fresh`` when it should not."""

    current = now or _utc_now()
    last_push_at, reason = read_last_push_at(last_push_path)
    if last_push_at is None:
        return reason
    age = current - last_push_at
    if age < timedelta(0):
        return "future_last_push"
    if age < stale_after:
        return "fresh"
    return "stale_last_push"


def _current_history_id(service: Any) -> str | None:
    profile = service.users().getProfile(userId="me").execute()
    history_id = profile.get("historyId")
    if history_id is None:
        return None
    value = str(history_id).strip()
    return value or None


def run_once(
    *,
    last_push_path: Path = LAST_PUSH_PATH,
    cursor_path: Path = HISTORY_CURSOR_PATH,
    seen_set_path: Path = SEEN_SET_PATH,
    pending_actions_path: Path = PENDING_ACTIONS_PATH,
    lock_path: Path = MAIL_MONITOR_LOCK_PATH,
    stale_after: timedelta = STALE_AFTER,
    now: datetime | None = None,
) -> FallbackRun:
    """Run one fallback check and optional label-scoped history poll."""

    current = now or _utc_now()
    reason = fallback_poll_reason(
        last_push_path=last_push_path,
        stale_after=stale_after,
        now=current,
    )
    if reason not in POLL_REASONS:
        FALLBACK_COUNTER.labels(result="fresh").inc()
        log.info("mail-monitor fallback no-op: reason=%s", reason)
        return FallbackRun(result="fresh", reason=reason)

    creds = load_credentials()
    if creds is None:
        FALLBACK_COUNTER.labels(result="no_credentials").inc()
        log.warning("mail-monitor fallback skipped: credentials unavailable")
        return FallbackRun(result="no_credentials", reason=reason)

    service = build_gmail_service(creds=creds)
    if service is None:
        FALLBACK_COUNTER.labels(result="no_service").inc()
        log.warning("mail-monitor fallback skipped: Gmail service unavailable")
        return FallbackRun(result="no_service", reason=reason)

    from googleapiclient.errors import HttpError

    try:
        label_ids = bootstrap_labels(service)
        history_id = _current_history_id(service)
        if history_id is None:
            FALLBACK_COUNTER.labels(result="no_history_id").inc()
            log.warning("mail-monitor fallback failed: users.getProfile returned no historyId")
            return FallbackRun(result="no_history_id", reason=reason)
        processed = process_history(
            service,
            history_id,
            label_ids_by_name=label_ids,
            cursor_path=cursor_path,
            last_push_path=last_push_path,
            seen_set_path=seen_set_path,
            pending_actions_path=pending_actions_path,
            lock_path=lock_path,
            now=current,
            record_last_push=False,
        )
    except LabelBootstrapError as exc:
        FALLBACK_COUNTER.labels(result="label_bootstrap_error").inc()
        log.warning("mail-monitor fallback failed: label bootstrap error: %s", exc)
        return FallbackRun(result="label_bootstrap_error", reason=reason)
    except HttpError as exc:
        FALLBACK_COUNTER.labels(result="api_error").inc()
        log.warning("mail-monitor fallback failed: Gmail API error: %s", exc)
        return FallbackRun(result="api_error", reason=reason)

    result: FallbackResult = "stale_processed" if processed else "stale_empty"
    FALLBACK_COUNTER.labels(result=result).inc()
    log.info("mail-monitor fallback poll complete: result=%s processed=%d", result, processed)
    return FallbackRun(result=result, reason=reason, processed=processed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agents.mail_monitor.fallback",
        description="Run one mail-monitor Pub/Sub outage fallback poll if last push is stale.",
    )
    parser.add_argument(
        "--stale-after-minutes",
        type=int,
        default=60,
        help="Poll only when last Pub/Sub push is at least this many minutes old.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    stale_after = timedelta(minutes=max(1, args.stale_after_minutes))
    result = run_once(stale_after=stale_after)
    print(json.dumps(asdict(result), sort_keys=True))
    return 0 if result.result in CLEAN_EXIT_RESULTS else 1


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
