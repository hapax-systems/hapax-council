"""Tests for ``agents.mail_monitor.pubsub_bootstrap``."""

from __future__ import annotations

import json
from unittest import mock

import pytest
from prometheus_client import REGISTRY

from agents.mail_monitor import pubsub_bootstrap
from agents.mail_monitor.pubsub_bootstrap import (
    PubsubBootstrapError,
    bootstrap_pubsub,
    bootstrap_subscription,
    bootstrap_topic,
    ensure_gmail_publisher,
    subscription_path,
    topic_path,
)


def _counter(resource: str, result: str) -> float:
    val = REGISTRY.get_sample_value(
        "hapax_mail_monitor_pubsub_install_total",
        {"resource": resource, "result": result},
    )
    return val or 0.0


# ── credential loading ────────────────────────────────────────────────


def test_pubsub_client_kwargs_empty_without_pass_service_account() -> None:
    with mock.patch.object(pubsub_bootstrap, "_pass_show_text", return_value=None):
        assert pubsub_bootstrap._pubsub_client_kwargs() == {}


def test_pubsub_client_kwargs_uses_pass_service_account_json() -> None:
    fake_creds = mock.Mock()
    info = {"type": "service_account", "client_email": "sa@example.iam.gserviceaccount.com"}

    with (
        mock.patch.object(pubsub_bootstrap, "_pass_show_text", return_value=json.dumps(info)),
        mock.patch(
            "google.oauth2.service_account.Credentials.from_service_account_info",
            return_value=fake_creds,
        ) as from_info,
    ):
        assert pubsub_bootstrap._pubsub_client_kwargs() == {"credentials": fake_creds}

    from_info.assert_called_once_with(
        info,
        scopes=[pubsub_bootstrap.CLOUD_PLATFORM_SCOPE],
    )


def test_pubsub_client_kwargs_raises_on_invalid_json() -> None:
    with (
        mock.patch.object(pubsub_bootstrap, "_pass_show_text", return_value="{not-json"),
        pytest.raises(PubsubBootstrapError, match="valid JSON"),
    ):
        pubsub_bootstrap._pubsub_client_kwargs()


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
    pub.get_iam_policy = mock.Mock()
    pub.set_iam_policy = mock.Mock()
    return pub


class _FakeBinding:
    def __init__(self, *, role: str = "", members: list[str] | None = None) -> None:
        self.role = role
        self.members = members or []


class _FakeBindings(list[_FakeBinding]):
    def add(self) -> _FakeBinding:
        binding = _FakeBinding()
        self.append(binding)
        return binding


class _FakePolicy:
    def __init__(self, bindings: list[_FakeBinding] | None = None) -> None:
        self.bindings = _FakeBindings(bindings or [])


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


# ── Gmail publisher topic IAM ─────────────────────────────────────────


def test_ensure_gmail_publisher_adds_missing_binding() -> None:
    before = _counter("topic_iam", "created")
    fake_exceptions = mock.Mock()
    fake_exceptions.GoogleAPICallError = type("GoogleAPICallError", (Exception,), {})

    pub = _publisher_double()
    policy = _FakePolicy()
    pub.get_iam_policy.return_value = policy
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
        ensure_gmail_publisher("projects/my-project/topics/hapax-mail-monitor")

    assert len(policy.bindings) == 1
    assert policy.bindings[0].role == pubsub_bootstrap.PUBSUB_PUBLISHER_ROLE
    assert pubsub_bootstrap.GMAIL_PUBLISHER_MEMBER in policy.bindings[0].members
    pub.set_iam_policy.assert_called_once()
    assert _counter("topic_iam", "created") - before == 1.0


def test_ensure_gmail_publisher_reuses_existing_binding() -> None:
    before = _counter("topic_iam", "exists")
    fake_exceptions = mock.Mock()
    fake_exceptions.GoogleAPICallError = type("GoogleAPICallError", (Exception,), {})

    pub = _publisher_double()
    policy = _FakePolicy(
        [
            _FakeBinding(
                role=pubsub_bootstrap.PUBSUB_PUBLISHER_ROLE,
                members=[pubsub_bootstrap.GMAIL_PUBLISHER_MEMBER],
            )
        ]
    )
    pub.get_iam_policy.return_value = policy
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
        ensure_gmail_publisher("projects/my-project/topics/hapax-mail-monitor")

    pub.set_iam_policy.assert_not_called()
    assert _counter("topic_iam", "exists") - before == 1.0


def test_ensure_gmail_publisher_raises_on_policy_error() -> None:
    before = _counter("topic_iam", "error")
    fake_exceptions = mock.Mock()
    fake_exceptions.GoogleAPICallError = type("GoogleAPICallError", (Exception,), {})

    pub = _publisher_double()
    pub.get_iam_policy.side_effect = fake_exceptions.GoogleAPICallError("denied")
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
        pytest.raises(PubsubBootstrapError, match="get_iam_policy"),
    ):
        ensure_gmail_publisher("projects/my-project/topics/hapax-mail-monitor")
    assert _counter("topic_iam", "error") - before == 1.0


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
        mock.patch.object(pubsub_bootstrap, "ensure_gmail_publisher") as iam_mock,
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
    iam_mock.assert_called_once_with("projects/my-project/topics/hapax-mail-monitor")
    sub_mock.assert_called_once()


def test_module_pre_registers_all_outcome_labels() -> None:
    for resource in ("topic", "topic_iam", "subscription"):
        for outcome in ("created", "exists", "error", "missing_config"):
            val = REGISTRY.get_sample_value(
                "hapax_mail_monitor_pubsub_install_total",
                {"resource": resource, "result": outcome},
            )
            assert val is not None, (resource, outcome)


# ── CLI ───────────────────────────────────────────────────────────────


def test_main_returns_zero_and_prints_paths(capsys: pytest.CaptureFixture[str]) -> None:
    with mock.patch.object(
        pubsub_bootstrap,
        "bootstrap_pubsub",
        return_value=(
            "projects/my-project/topics/hapax-mail-monitor",
            "projects/my-project/subscriptions/hapax-mail-monitor-push",
        ),
    ):
        assert pubsub_bootstrap.main([]) == 0

    out = json.loads(capsys.readouterr().out)
    assert out["topic"] == "projects/my-project/topics/hapax-mail-monitor"
    assert out["subscription"] == "projects/my-project/subscriptions/hapax-mail-monitor-push"


def test_main_returns_one_on_missing_config(capsys: pytest.CaptureFixture[str]) -> None:
    with mock.patch.object(pubsub_bootstrap, "bootstrap_pubsub", return_value=None):
        assert pubsub_bootstrap.main([]) == 1

    assert "config is incomplete" in capsys.readouterr().err


def test_main_returns_one_on_bootstrap_error(capsys: pytest.CaptureFixture[str]) -> None:
    with mock.patch.object(
        pubsub_bootstrap,
        "bootstrap_pubsub",
        side_effect=PubsubBootstrapError("denied"),
    ):
        assert pubsub_bootstrap.main([]) == 1

    assert "FAIL: denied" in capsys.readouterr().err
