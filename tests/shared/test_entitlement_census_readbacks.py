"""A provider response cannot turn a failed probe into live or dead supply."""

from datetime import UTC, datetime

import pytest

from shared.entitlement_census import HttpResponse, ReadbackRef, SecretRegister, run_readback

NOW = datetime(2026, 9, 28, tzinfo=UTC)


@pytest.mark.parametrize(
    ("status", "expected"),
    [(200, "live"), (401, "dead"), (403, "unobserved"), (302, "unobserved"), (None, "unobserved")],
)
def test_readback_outcomes_preserve_what_was_observed(status, expected):
    calls = []

    def http_get(url, headers, timeout):
        calls.append((url, headers, timeout))
        return HttpResponse(status=status, body=b"{}", error="timeout" if status is None else None)

    result = run_readback(
        ReadbackRef(readback_id="kimi_usages", credential_name="kimi-name"),
        now=NOW,
        resolve_secret=lambda _: "fixture-secret-value",
        http_get=http_get,
        secrets=SecretRegister(),
    )
    assert result.outcome == expected
    assert len(calls) == 1 and calls[0][1]["Authorization"] == "Bearer fixture-secret-value"
    assert "fixture-secret-value" not in repr(result)


def test_unresolvable_name_sends_no_request():
    def http_get(*_):
        raise AssertionError("no request may be sent")

    result = run_readback(
        ReadbackRef(readback_id="kimi_usages", credential_name="missing"),
        now=NOW,
        resolve_secret=lambda _: None,
        http_get=http_get,
        secrets=SecretRegister(),
    )
    assert result.outcome == "unobserved" and result.reason == "secret_unresolvable"
