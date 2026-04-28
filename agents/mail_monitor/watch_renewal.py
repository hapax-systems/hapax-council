"""Daily renewal driver for the Gmail ``users.watch()`` subscription.

Spec: ``docs/specs/2026-04-25-mail-monitor.md`` §5.2.

Run as a oneshot under ``hapax-mail-monitor-watch-renewal.timer`` once
every 24 hours. The Gmail watch lifetime is 7 days, so daily renewal
gives a 6-day safety margin. Each run:

1. Loads OAuth credentials.
2. Reads ``mail-monitor/google-project-id`` from ``pass``.
3. Calls :func:`agents.mail_monitor.label_bootstrap.bootstrap_labels` to
   resolve current Hapax label ids (idempotent — no-op if labels already
   exist).
4. Invokes :func:`agents.mail_monitor.watch.call_watch` with the four
   label ids and the topic path.
5. Persists the response and updates the
   ``hapax_mail_monitor_watch_age_seconds`` gauge.

Non-success outcomes increment
``hapax_mail_monitor_watch_renewal_total{result="…"}`` so a gap is
visible in Grafana before the watch actually expires.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import logging
import sys
from collections.abc import Iterator
from pathlib import Path

from prometheus_client import Counter, Gauge

from agents.mail_monitor.label_bootstrap import (
    HAPAX_LABEL_NAMES,
    LabelBootstrapError,
    bootstrap_labels,
)
from agents.mail_monitor.oauth import (
    _pass_show,
    build_gmail_service,
    load_credentials,
)
from agents.mail_monitor.pubsub_bootstrap import (
    PROJECT_ID_PASS_KEY,
    topic_path,
)
from agents.mail_monitor.watch import (
    WatchError,
    call_watch,
    watch_age_s,
)

log = logging.getLogger(__name__)

LOCK_PATH = Path("~/.cache/mail-monitor/watch-renewal.lock").expanduser()
SUCCESS_RESULT = "success"
NON_RETRYABLE_SKIP_RESULTS = frozenset({"no_credentials", "no_project", "locked"})

WATCH_RENEWAL_COUNTER = Counter(
    "hapax_mail_monitor_watch_renewal_total",
    "Gmail watch() renewal attempts by outcome.",
    labelnames=("result",),
)
for _result in (
    "success",
    "no_credentials",
    "no_project",
    "label_bootstrap_error",
    "api_error",
    "watch_error",
    "locked",
):
    WATCH_RENEWAL_COUNTER.labels(result=_result)

WATCH_AGE_GAUGE = Gauge(
    "hapax_mail_monitor_watch_age_seconds",
    "Seconds since the last successful Gmail watch() call.",
)


@contextlib.contextmanager
def _renewal_lock(path: Path = LOCK_PATH) -> Iterator[bool]:
    """Acquire the cross-process renewal lock without blocking."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def renew_once(*, lock_path: Path = LOCK_PATH) -> bool:
    """Single renewal attempt; return ``True`` on success."""
    return renew_once_result(lock_path=lock_path) == SUCCESS_RESULT


def renew_once_result(*, lock_path: Path = LOCK_PATH) -> str:
    """Single renewal attempt; return the labelled outcome.

    Each non-success mode increments a labelled counter. The CLI maps
    operator-actionable configuration skips (missing credentials/project
    and lock contention) to exit 0 so systemd does not crash-loop before
    bootstrap is complete; API/runtime failures still exit non-zero.
    """
    with _renewal_lock(lock_path) as acquired:
        if not acquired:
            WATCH_RENEWAL_COUNTER.labels(result="locked").inc()
            log.info("watch renewal skipped: another renewal process holds %s", lock_path)
            return "locked"
        return _renew_once_unlocked()


def _renew_once_unlocked() -> str:
    """Renew the Gmail watch while the cross-process lock is held."""

    creds = load_credentials()
    if creds is None:
        WATCH_RENEWAL_COUNTER.labels(result="no_credentials").inc()
        log.warning(
            "watch renewal aborted: load_credentials returned None. "
            "Run python -m agents.mail_monitor.oauth --first-consent."
        )
        return "no_credentials"

    service = build_gmail_service(creds=creds)
    if service is None:
        WATCH_RENEWAL_COUNTER.labels(result="no_credentials").inc()
        log.warning("watch renewal aborted: build_gmail_service returned None.")
        return "no_credentials"

    project_id = _pass_show(PROJECT_ID_PASS_KEY)
    if not project_id:
        WATCH_RENEWAL_COUNTER.labels(result="no_project").inc()
        log.warning(
            "watch renewal aborted: pass %s missing. "
            "Run pass insert mail-monitor/google-project-id.",
            PROJECT_ID_PASS_KEY,
        )
        return "no_project"

    try:
        label_ids_map = bootstrap_labels(service)
    except LabelBootstrapError as exc:
        WATCH_RENEWAL_COUNTER.labels(result="label_bootstrap_error").inc()
        log.warning("watch renewal aborted: label bootstrap failed: %s", exc)
        return "label_bootstrap_error"

    label_ids = [label_ids_map[name] for name in HAPAX_LABEL_NAMES]

    try:
        from googleapiclient.errors import HttpError

        try:
            call_watch(
                service,
                topic_path=topic_path(project_id),
                label_ids=label_ids,
            )
        except HttpError as exc:
            WATCH_RENEWAL_COUNTER.labels(result="api_error").inc()
            log.warning("watch renewal failed: HTTP %s", exc)
            return "api_error"
    except WatchError as exc:
        WATCH_RENEWAL_COUNTER.labels(result="watch_error").inc()
        log.warning("watch renewal aborted: %s", exc)
        return "watch_error"

    age = watch_age_s()
    if age is not None:
        WATCH_AGE_GAUGE.set(age)

    WATCH_RENEWAL_COUNTER.labels(result="success").inc()
    log.info("watch renewal succeeded for project=%s", project_id)
    return SUCCESS_RESULT


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m agents.mail_monitor.watch_renewal``.

    One renewal attempt. Missing bootstrap credentials/project are a
    clean skip so systemd does not crash-loop while setup is incomplete.
    Runtime/API errors exit 1 so ``Restart=on-failure`` retries transient
    issues with a 5-minute delay.
    """
    parser = argparse.ArgumentParser(
        prog="python -m agents.mail_monitor.watch_renewal",
        description="Renew the Gmail users.watch() subscription.",
    )
    parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    result = renew_once_result()
    return 0 if result == SUCCESS_RESULT or result in NON_RETRYABLE_SKIP_RESULTS else 1


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
