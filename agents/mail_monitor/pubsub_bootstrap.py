"""Idempotent Pub/Sub topic + push-subscription installer for mail-monitor.

Spec: ``docs/specs/2026-04-25-mail-monitor.md`` §5.2.

The push subscription targets the operator-configured webhook URL with
Google IAM JWT auth (``oidc_token`` mode). The receiver
(``mail-monitor-006``) verifies the JWT against Google's public keys.
The topic also grants Gmail's publisher service account
``roles/pubsub.publisher`` so ``users.watch()`` can publish label-filtered
events into the topic.

Operator-physical config (read at install time):

- ``pass mail-monitor/google-project-id`` — GCP project from
  ``mail-monitor-002``.
- ``pass mail-monitor/webhook-url`` — full HTTPS URL of the gmail
  webhook receiver (``…/webhook/gmail``).
- ``pass mail-monitor/pubsub-sa-email`` — Google service-account
  email Google signs the JWT as.
- Optional ``pass mail-monitor/google-service-account-json`` — service
  account JSON used for Pub/Sub administrative calls when workstation
  Application Default Credentials are absent.

Missing config short-circuits with a logged warning and the daemon
stays in DEGRADED state — bootstrap never silently no-ops.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from typing import Any

from prometheus_client import Counter

from agents.mail_monitor.oauth import _pass_show

log = logging.getLogger(__name__)

TOPIC_NAME = "hapax-mail-monitor"
SUBSCRIPTION_NAME = "hapax-mail-monitor-push"
GMAIL_PUBLISHER_MEMBER = "serviceAccount:gmail-api-push@system.gserviceaccount.com"
PUBSUB_PUBLISHER_ROLE = "roles/pubsub.publisher"

PROJECT_ID_PASS_KEY = "mail-monitor/google-project-id"
WEBHOOK_URL_PASS_KEY = "mail-monitor/webhook-url"
PUBSUB_SA_EMAIL_PASS_KEY = "mail-monitor/pubsub-sa-email"
SERVICE_ACCOUNT_JSON_PASS_KEY = "mail-monitor/google-service-account-json"

ACK_DEADLINE_SECONDS = 60
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

# Webhook URL must be HTTPS — Pub/Sub push refuses plain HTTP.
_WEBHOOK_URL_RE = re.compile(r"^https://[^/]+/webhook/gmail$")

PUBSUB_INSTALLS_COUNTER = Counter(
    "hapax_mail_monitor_pubsub_install_total",
    "Pub/Sub install attempts by resource and outcome.",
    labelnames=("resource", "result"),
)
for _resource in ("topic", "topic_iam", "subscription"):
    for _result in ("created", "exists", "error", "missing_config"):
        PUBSUB_INSTALLS_COUNTER.labels(resource=_resource, result=_result)


class PubsubBootstrapError(RuntimeError):
    """Raised when topic / subscription cannot be created or read."""


def _pass_show_text(key: str, *, timeout_s: float = 5.0) -> str | None:
    """Return full ``pass show <key>`` output, stripped, or ``None``."""
    try:
        result = subprocess.run(
            ["pass", "show", key],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        log.warning("pass show %s failed: %s", key, exc)
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _pubsub_client_kwargs() -> dict[str, Any]:
    """Return Pub/Sub client kwargs, preferring pass-stored credentials.

    The workstation may not have Google Application Default Credentials
    even though all credentials are present in ``pass``. When
    ``mail-monitor/google-service-account-json`` exists, construct
    service-account credentials in memory and pass them directly to the
    Pub/Sub clients. If the key is absent, return an empty dict so the
    Google client falls back to ADC as usual.
    """
    key_json = _pass_show_text(SERVICE_ACCOUNT_JSON_PASS_KEY)
    if not key_json:
        return {}
    try:
        info = json.loads(key_json)
    except json.JSONDecodeError as exc:
        raise PubsubBootstrapError(
            f"pass {SERVICE_ACCOUNT_JSON_PASS_KEY} does not contain valid JSON: {exc}"
        ) from exc

    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_info(
        info,
        scopes=[CLOUD_PLATFORM_SCOPE],
    )
    return {"credentials": credentials}


def topic_path(project_id: str) -> str:
    return f"projects/{project_id}/topics/{TOPIC_NAME}"


def subscription_path(project_id: str) -> str:
    return f"projects/{project_id}/subscriptions/{SUBSCRIPTION_NAME}"


def _validate_webhook_url(url: str) -> None:
    if not _WEBHOOK_URL_RE.match(url):
        raise PubsubBootstrapError(
            f"webhook url {url!r} must match {_WEBHOOK_URL_RE.pattern!r}; "
            "https + path /webhook/gmail required by spec §5.2."
        )


def bootstrap_topic(project_id: str) -> str:
    """Create the mail-monitor topic if missing; return its full path.

    Reuses any existing topic with the same name (Pub/Sub raises
    :class:`google.api_core.exceptions.AlreadyExists` which is treated
    as success).
    """
    from google.api_core import exceptions as gax
    from google.cloud import pubsub_v1

    publisher = pubsub_v1.PublisherClient(**_pubsub_client_kwargs())
    path = publisher.topic_path(project_id, TOPIC_NAME)
    try:
        publisher.create_topic(request={"name": path})
    except gax.AlreadyExists:
        PUBSUB_INSTALLS_COUNTER.labels(resource="topic", result="exists").inc()
        log.info("Pub/Sub topic %s already exists; reusing", path)
        return path
    except gax.GoogleAPICallError as exc:
        PUBSUB_INSTALLS_COUNTER.labels(resource="topic", result="error").inc()
        raise PubsubBootstrapError(f"create_topic({path}) failed: {exc}") from exc

    PUBSUB_INSTALLS_COUNTER.labels(resource="topic", result="created").inc()
    log.info("created Pub/Sub topic %s", path)
    return path


def ensure_gmail_publisher(topic_path: str) -> None:
    """Allow Gmail API push delivery to publish into ``topic_path``.

    Gmail ``users.watch()`` requires the fixed Google-managed service
    account ``gmail-api-push@system.gserviceaccount.com`` to have
    ``roles/pubsub.publisher`` on the topic. Creating the topic alone is
    not enough; without this binding, watch renewal can fail even though
    the topic and subscription both exist.
    """
    from google.api_core import exceptions as gax
    from google.cloud import pubsub_v1

    publisher = pubsub_v1.PublisherClient(**_pubsub_client_kwargs())
    try:
        policy = publisher.get_iam_policy(request={"resource": topic_path})
    except gax.GoogleAPICallError as exc:
        PUBSUB_INSTALLS_COUNTER.labels(resource="topic_iam", result="error").inc()
        raise PubsubBootstrapError(f"get_iam_policy({topic_path}) failed: {exc}") from exc

    for binding in policy.bindings:
        if binding.role == PUBSUB_PUBLISHER_ROLE and GMAIL_PUBLISHER_MEMBER in binding.members:
            PUBSUB_INSTALLS_COUNTER.labels(resource="topic_iam", result="exists").inc()
            log.info("Gmail Pub/Sub publisher binding already exists on %s", topic_path)
            return

    binding = policy.bindings.add()
    binding.role = PUBSUB_PUBLISHER_ROLE
    binding.members.append(GMAIL_PUBLISHER_MEMBER)

    try:
        publisher.set_iam_policy(request={"resource": topic_path, "policy": policy})
    except gax.GoogleAPICallError as exc:
        PUBSUB_INSTALLS_COUNTER.labels(resource="topic_iam", result="error").inc()
        raise PubsubBootstrapError(f"set_iam_policy({topic_path}) failed: {exc}") from exc

    PUBSUB_INSTALLS_COUNTER.labels(resource="topic_iam", result="created").inc()
    log.info("granted Gmail Pub/Sub publisher binding on %s", topic_path)


def bootstrap_subscription(
    project_id: str,
    *,
    topic_path: str,
    webhook_url: str,
    sa_email: str,
) -> str:
    """Create the push subscription if missing; return its full path.

    The subscription pushes Pub/Sub messages to ``webhook_url`` with a
    Google-signed OIDC JWT whose ``aud`` claim equals the webhook URL.
    The webhook receiver verifies the signature.
    """
    _validate_webhook_url(webhook_url)

    from google.api_core import exceptions as gax
    from google.cloud import pubsub_v1

    subscriber = pubsub_v1.SubscriberClient(**_pubsub_client_kwargs())
    sub_path = subscriber.subscription_path(project_id, SUBSCRIPTION_NAME)
    push_config = pubsub_v1.types.PushConfig(
        push_endpoint=webhook_url,
        oidc_token=pubsub_v1.types.PushConfig.OidcToken(
            service_account_email=sa_email,
            audience=webhook_url,
        ),
    )
    request = {
        "name": sub_path,
        "topic": topic_path,
        "push_config": push_config,
        "ack_deadline_seconds": ACK_DEADLINE_SECONDS,
    }
    try:
        subscriber.create_subscription(request=request)
    except gax.AlreadyExists:
        PUBSUB_INSTALLS_COUNTER.labels(resource="subscription", result="exists").inc()
        log.info("Pub/Sub subscription %s already exists; reusing", sub_path)
        return sub_path
    except gax.GoogleAPICallError as exc:
        PUBSUB_INSTALLS_COUNTER.labels(resource="subscription", result="error").inc()
        raise PubsubBootstrapError(f"create_subscription({sub_path}) failed: {exc}") from exc

    PUBSUB_INSTALLS_COUNTER.labels(resource="subscription", result="created").inc()
    log.info("created Pub/Sub push subscription %s → %s", sub_path, webhook_url)
    return sub_path


def bootstrap_pubsub() -> tuple[str, str] | None:
    """Read all operator config from ``pass``; install topic + subscription.

    Returns ``(topic_path, subscription_path)`` on success, ``None``
    when any required config is missing. Both metric outcomes
    (``missing_config`` per resource) are emitted in the missing-config
    branch so observers see the gap.
    """
    project_id = _pass_show(PROJECT_ID_PASS_KEY)
    webhook_url = _pass_show(WEBHOOK_URL_PASS_KEY)
    sa_email = _pass_show(PUBSUB_SA_EMAIL_PASS_KEY)

    if not project_id or not webhook_url or not sa_email:
        PUBSUB_INSTALLS_COUNTER.labels(resource="topic", result="missing_config").inc()
        PUBSUB_INSTALLS_COUNTER.labels(resource="topic_iam", result="missing_config").inc()
        PUBSUB_INSTALLS_COUNTER.labels(resource="subscription", result="missing_config").inc()
        log.warning(
            "Pub/Sub bootstrap incomplete: project=%s webhook=%s sa=%s. "
            "Run pass insert mail-monitor/{google-project-id, webhook-url, "
            "pubsub-sa-email}.",
            bool(project_id),
            bool(webhook_url),
            bool(sa_email),
        )
        return None

    tp = bootstrap_topic(project_id)
    ensure_gmail_publisher(tp)
    sp = bootstrap_subscription(
        project_id,
        topic_path=tp,
        webhook_url=webhook_url,
        sa_email=sa_email,
    )
    return tp, sp


def main(argv: list[str] | None = None) -> int:
    """CLI: install the Pub/Sub topic, IAM binding, and push subscription."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m agents.mail_monitor.pubsub_bootstrap",
        description="Install mail-monitor Pub/Sub topic + push subscription.",
    )
    parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        result = bootstrap_pubsub()
    except PubsubBootstrapError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if result is None:
        print("FAIL: Pub/Sub bootstrap config is incomplete.", file=sys.stderr)
        return 1
    print(json.dumps({"topic": result[0], "subscription": result[1]}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
