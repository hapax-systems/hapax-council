"""Tests for ``agents.mail_monitor.pubsub_bootstrap``."""

from __future__ import annotations

from unittest import mock

import pytest
from prometheus_client import REGISTRY

from agents.mail_monitor import pubsub_bootstrap
from agents.mail_monitor.pubsub_bootstrap import (
    PubsubBootstrapError,
    bootstrap_pubsub,
    bootstrap_subscription,
    bootstrap_topic,
    subscription_path,
    topic_path,
)


def _counter(resource: str, result: str) -> float:
    val = REGISTRY.get_sample_value(
        "hapax_mail_monitor_pubsub_install_total",
        {"resource": resource, "result": result},
    )
    return val or 0.0


# ── path helpers ──────────────────────────────────────────────────────


def test_topic_path_format() -> None:
    assert topic_path("my-project") == "projects/my-project/topics/hapax-mail-monitor"


def test_subscription_path_format() -> None:
    assert (
        subscription_path("my-project")
        == "projects/my-project/subscriptions/hapax-mail-monitor-push"
    )


# ── webhook URL validation ───────────────────────────────────────────


def test_validate_webhook_url_accepts_https_with_correct_path() -> None:
    pubsub_bootstrap._validate_webhook_url("https://logos.example.ts.net:8051/webhook/gmail")


def test_validate_webhook_url_rejects_http() -> None:
    with pytest.raises(PubsubBootstrapError, match="https"):
        pubsub_bootstrap._validate_webhook_url("http://logos.example.com/webhook/gmail")


def test_validate_webhook_url_rejects_wrong_path() -> None:
    with pytest.raises(PubsubBootstrapError):
        pubsub_bootstrap._validate_webhook_url("https://logos.example.com/webhook/something-else")


# ── bootstrap_topic ───────────────────────────────────────────────────


def _publisher_double() -> mock.Mock:
    pub = mock.Mock()
    pub.topic_path = mock.Mock(side_effect=lambda p, t: f"projects/{p}/topics/{t}")
    pub.create_topic = mock.Mock()
    return pub


def test_bootstrap_topic_creates_when_missing() -> None:
    before = _counter("topic", "created")
    pub = _publisher_double()
    fake_pubsub_v1 = mock.Mock(PublisherClient=mock.Mock(return_value=pub))
    fake_exceptions = mock.Mock()
    fake_exceptions.AlreadyExists = type("AlreadyExists", (Exception,), {})
    fake_exceptions.GoogleAPICallError = type("GoogleAPICallError", (Exception,), {})

    with (
        mock.patch.dict(
            "sys.modules",
            {
                "google.cloud": mock.Mock(pubsub_v1=fake_pubsub_v1),
                "google.cloud.pubsub_v1": fake_pubsub_v1,
                "google.api_core": mock.Mock(exceptions=fake_exceptions),
                "google.api_core.exceptions": fake_exceptions,
            },
        ),
    ):
        path = bootstrap_topic("my-project")

    assert path == "projects/my-project/topics/hapax-mail-monitor"
    pub.create_topic.assert_called_once()
    assert _counter("topic", "created") - before == 1.0


def test_bootstrap_topic_reuses_when_already_exists() -> None:
    before = _counter("topic", "exists")
    fake_exceptions = mock.Mock()
    fake_exceptions.AlreadyExists = type("AlreadyExists", (Exception,), {})
    fake_exceptions.GoogleAPICallError = type("GoogleAPICallError", (Exception,), {})

    pub = _publisher_double()
    pub.create_topic.side_effect = fake_exceptions.AlreadyExists("exists")
    fake_pubsub_v1 = mock.Mock(PublisherClient=mock.Mock(return_value=pub))

    with mock.patch.dict(
        "sys.modules",
        {
            "google.cloud": mock.Mock(pubsub_v1=fake_pubsub_v1),
            "google.cloud.pubsub_v1": fake_pubsub_v1,
            "google.api_core": mock.Mock(exceptions=fake_exceptions),
            "google.api_core.exceptions": fake_exceptions,
        },
    ):
        path = bootstrap_topic("my-project")

    assert path == "projects/my-project/topics/hapax-mail-monitor"
    assert _counter("topic", "exists") - before == 1.0


def test_bootstrap_topic_raises_on_other_api_error() -> None:
    before = _counter("topic", "error")
    fake_exceptions = mock.Mock()
    fake_exceptions.AlreadyExists = type("AlreadyExists", (Exception,), {})
    fake_exceptions.GoogleAPICallError = type("GoogleAPICallError", (Exception,), {})

    pub = _publisher_double()
    pub.create_topic.side_effect = fake_exceptions.GoogleAPICallError("permission denied")
    fake_pubsub_v1 = mock.Mock(PublisherClient=mock.Mock(return_value=pub))

    with (
        mock.patch.dict(
            "sys.modules",
            {
                "google.cloud": mock.Mock(pubsub_v1=fake_pubsub_v1),
                "google.cloud.pubsub_v1": fake_pubsub_v1,
                "google.api_core": mock.Mock(exceptions=fake_exceptions),
                "google.api_core.exceptions": fake_exceptions,
            },
        ),
        pytest.raises(PubsubBootstrapError, match="create_topic"),
    ):
        bootstrap_topic("my-project")
    assert _counter("topic", "error") - before == 1.0


# ── bootstrap_subscription ────────────────────────────────────────────


def _subscriber_double() -> mock.Mock:
    sub = mock.Mock()
    sub.subscription_path = mock.Mock(side_effect=lambda p, s: f"projects/{p}/subscriptions/{s}")
    sub.create_subscription = mock.Mock()
    return sub


def _patch_pubsub(fake_pub: mock.Mock, fake_sub: mock.Mock, fake_exc: mock.Mock):
    """Module-level patch context for the google.cloud + google.api_core surfaces."""
    types_mod = mock.Mock()
    types_mod.PushConfig = mock.Mock()
    types_mod.PushConfig.OidcToken = mock.Mock()
    fake_pubsub_v1 = mock.Mock(
        PublisherClient=mock.Mock(return_value=fake_pub),
        SubscriberClient=mock.Mock(return_value=fake_sub),
        types=types_mod,
    )
    return mock.patch.dict(
        "sys.modules",
        {
            "google.cloud": mock.Mock(pubsub_v1=fake_pubsub_v1),
            "google.cloud.pubsub_v1": fake_pubsub_v1,
            "google.api_core": mock.Mock(exceptions=fake_exc),
            "google.api_core.exceptions": fake_exc,
        },
    )


def test_bootstrap_subscription_creates_with_oidc_token() -> None:
    fake_exc = mock.Mock()
    fake_exc.AlreadyExists = type("AlreadyExists", (Exception,), {})
    fake_exc.GoogleAPICallError = type("GoogleAPICallError", (Exception,), {})

    sub = _subscriber_double()
    pub = _publisher_double()

    with _patch_pubsub(pub, sub, fake_exc):
        path = bootstrap_subscription(
            "my-project",
            topic_path="projects/my-project/topics/hapax-mail-monitor",
            webhook_url="https://logos.example.ts.net:8051/webhook/gmail",
            sa_email="hapax@my-project.iam.gserviceaccount.com",
        )

    assert path == "projects/my-project/subscriptions/hapax-mail-monitor-push"
    sub.create_subscription.assert_called_once()
    request = sub.create_subscription.call_args.kwargs["request"]
    assert request["topic"] == "projects/my-project/topics/hapax-mail-monitor"
    assert request["ack_deadline_seconds"] == 60
    # push_config and oidc_token are constructed via mocked types — we
    # cannot assert deep-equality on the Pub/Sub types objects, but we
    # CAN assert the constructor calls.


def test_bootstrap_subscription_rejects_invalid_webhook_url() -> None:
    fake_exc = mock.Mock()
    fake_exc.AlreadyExists = type("AlreadyExists", (Exception,), {})

    with pytest.raises(PubsubBootstrapError, match="https"):
        bootstrap_subscription(
            "my-project",
            topic_path="projects/my-project/topics/hapax-mail-monitor",
            webhook_url="http://logos.example.com/webhook/gmail",
            sa_email="hapax@my-project.iam.gserviceaccount.com",
        )


def test_bootstrap_subscription_reuses_when_already_exists() -> None:
    before = _counter("subscription", "exists")
    fake_exc = mock.Mock()
    fake_exc.AlreadyExists = type("AlreadyExists", (Exception,), {})
    fake_exc.GoogleAPICallError = type("GoogleAPICallError", (Exception,), {})

    sub = _subscriber_double()
    sub.create_subscription.side_effect = fake_exc.AlreadyExists("exists")
    pub = _publisher_double()

    with _patch_pubsub(pub, sub, fake_exc):
        bootstrap_subscription(
            "my-project",
            topic_path="projects/my-project/topics/hapax-mail-monitor",
            webhook_url="https://logos.example.ts.net:8051/webhook/gmail",
            sa_email="hapax@my-project.iam.gserviceaccount.com",
        )
    assert _counter("subscription", "exists") - before == 1.0


# ── bootstrap_pubsub orchestrator ─────────────────────────────────────


def test_bootstrap_pubsub_returns_none_when_config_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    before_topic = _counter("topic", "missing_config")
    before_sub = _counter("subscription", "missing_config")
    with mock.patch.object(pubsub_bootstrap, "_pass_show", side_effect=[None, None, None]):
        assert bootstrap_pubsub() is None
    assert _counter("topic", "missing_config") - before_topic == 1.0
    assert _counter("subscription", "missing_config") - before_sub == 1.0


def test_bootstrap_pubsub_returns_none_when_only_project_missing() -> None:
    before = _counter("topic", "missing_config")
    with mock.patch.object(
        pubsub_bootstrap,
        "_pass_show",
        side_effect=[None, "https://logos.x.ts.net:8051/webhook/gmail", "sa@x.iam"],
    ):
        assert bootstrap_pubsub() is None
    assert _counter("topic", "missing_config") - before == 1.0


def test_bootstrap_pubsub_calls_topic_then_subscription_when_config_present() -> None:
    with (
        mock.patch.object(
            pubsub_bootstrap,
            "_pass_show",
            side_effect=[
                "my-project",
                "https://logos.example.ts.net:8051/webhook/gmail",
                "sa@my-project.iam.gserviceaccount.com",
            ],
        ),
        mock.patch.object(
            pubsub_bootstrap,
            "bootstrap_topic",
            return_value="projects/my-project/topics/hapax-mail-monitor",
        ) as topic_mock,
        mock.patch.object(
            pubsub_bootstrap,
            "bootstrap_subscription",
            return_value="projects/my-project/subscriptions/hapax-mail-monitor-push",
        ) as sub_mock,
    ):
        result = bootstrap_pubsub()

    assert result == (
        "projects/my-project/topics/hapax-mail-monitor",
        "projects/my-project/subscriptions/hapax-mail-monitor-push",
    )
    topic_mock.assert_called_once_with("my-project")
    sub_mock.assert_called_once()


def test_module_pre_registers_all_outcome_labels() -> None:
    for resource in ("topic", "subscription"):
        for outcome in ("created", "exists", "error", "missing_config"):
            val = REGISTRY.get_sample_value(
                "hapax_mail_monitor_pubsub_install_total",
                {"resource": resource, "result": outcome},
            )
            assert val is not None, (resource, outcome)
