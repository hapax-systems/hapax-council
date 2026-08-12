"""The subscription claim must be measured or refused — never assumed.

The finding this closes: a transcript records no auth field, so an API-key-backed turn could
unblock a subscription-only route while the receipt merely labelled its own claim
``caller_asserted``. Labelling a hole is not closing one.

The hazard is live on this host — ``customApiKeyResponses.approved`` in the real ``~/.claude.json``
is non-empty — so these cases are about a path that exists, not one imagined for a test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.claude_auth_surface import (
    AUTH_SURFACE_PROVENANCE,
    CLAUDE_CONFIG_ENV,
    ClaudeAuthSurfaceUnavailable,
    observe_subscription_marker,
)

SUBSCRIBED = {
    "oauthAccount": {
        "billingType": "google_play_subscription",
        "organizationType": "claude_max",
    }
}


def _config(tmp_path: Path, payload: dict, monkeypatch) -> Path:
    path = tmp_path / "claude.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv(CLAUDE_CONFIG_ENV, str(path))
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return path


def test_a_subscription_account_with_no_key_path_is_measured(tmp_path, monkeypatch) -> None:
    _config(tmp_path, SUBSCRIBED, monkeypatch)

    marker = observe_subscription_marker()

    assert marker.billing_type == "google_play_subscription"
    assert marker.organization_type == "claude_max"
    assert marker.provenance == AUTH_SURFACE_PROVENANCE
    assert marker.provenance.startswith("measured:")


@pytest.mark.parametrize("var", ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_API_KEY"])
def test_an_api_key_in_the_environment_refuses(tmp_path, monkeypatch, var: str) -> None:
    """The condition that makes this a measurement rather than a guess.

    A subscription account with a metered key in reach cannot support the claim: nothing
    distinguishes which credential served the turn. There is no weaker true statement to fall
    back to, so it refuses.
    """
    _config(tmp_path, SUBSCRIBED, monkeypatch)
    monkeypatch.setenv(var, "sk-ant-whatever")

    with pytest.raises(ClaudeAuthSurfaceUnavailable) as exc:
        observe_subscription_marker()

    assert var in str(exc.value)
    assert "Next:" in str(exc.value)


def test_an_api_key_helper_refuses(tmp_path, monkeypatch) -> None:
    """A helper fetches a key at request time — same consequence as one sitting in the env."""
    _config(tmp_path, {**SUBSCRIBED, "apiKeyHelper": "/usr/local/bin/get-key"}, monkeypatch)

    with pytest.raises(ClaudeAuthSurfaceUnavailable, match="apiKeyHelper"):
        observe_subscription_marker()


def test_an_unfamiliar_billing_type_is_unknown_not_a_subscription(tmp_path, monkeypatch) -> None:
    """The fail-closed direction. A value nobody has classified is not evidence of anything."""
    _config(
        tmp_path,
        {"oauthAccount": {"billingType": "some_new_thing", "organizationType": "claude_max"}},
        monkeypatch,
    )

    with pytest.raises(ClaudeAuthSurfaceUnavailable) as exc:
        observe_subscription_marker()

    assert "some_new_thing" in str(exc.value)
    assert "SUBSCRIPTION_BILLING_TYPES" in str(exc.value), (
        "the refusal must name what a maintainer would have to measure to extend it"
    )


def test_a_metered_api_account_refuses(tmp_path, monkeypatch) -> None:
    _config(
        tmp_path,
        {"oauthAccount": {"billingType": "api_credits", "organizationType": "api"}},
        monkeypatch,
    )

    with pytest.raises(ClaudeAuthSurfaceUnavailable):
        observe_subscription_marker()


def test_a_non_subscription_seat_refuses(tmp_path, monkeypatch) -> None:
    _config(
        tmp_path,
        {
            "oauthAccount": {
                "billingType": "google_play_subscription",
                "organizationType": "enterprise_api",
            }
        },
        monkeypatch,
    )

    with pytest.raises(ClaudeAuthSurfaceUnavailable, match="organizationType"):
        observe_subscription_marker()


def test_a_missing_account_record_refuses(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(CLAUDE_CONFIG_ENV, str(tmp_path / "absent.json"))

    with pytest.raises(ClaudeAuthSurfaceUnavailable, match="no Claude Code account record"):
        observe_subscription_marker()


def test_an_unreadable_account_record_refuses(tmp_path, monkeypatch) -> None:
    path = tmp_path / "claude.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv(CLAUDE_CONFIG_ENV, str(path))

    with pytest.raises(ClaudeAuthSurfaceUnavailable, match="unreadable"):
        observe_subscription_marker()


def test_a_record_without_an_oauth_account_refuses(tmp_path, monkeypatch) -> None:
    _config(tmp_path, {"someOtherKey": 1}, monkeypatch)

    with pytest.raises(ClaudeAuthSurfaceUnavailable, match="records no oauthAccount"):
        observe_subscription_marker()


def test_no_credential_value_reaches_the_marker(tmp_path, monkeypatch) -> None:
    """Membership only. The module reads the CATEGORY of the billing relationship, never a token.

    A marker that carried a credential would turn every receipt and every log line that prints
    its provenance into a secret-bearing artifact.
    """
    _config(
        tmp_path,
        {
            "oauthAccount": {
                **SUBSCRIBED["oauthAccount"],
                "accountUuid": "uuid-should-not-travel",
                "emailAddress": "someone@example.test",
                "organizationUuid": "org-uuid-should-not-travel",
            },
            "customApiKeyResponses": {"approved": ["key-fragment-should-not-travel"]},
        },
        monkeypatch,
    )

    marker = observe_subscription_marker()

    blob = repr(marker) + marker.provenance
    for secret in (
        "uuid-should-not-travel",
        "someone@example.test",
        "org-uuid-should-not-travel",
        "key-fragment-should-not-travel",
    ):
        assert secret not in blob
